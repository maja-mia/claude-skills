"""Validation reports: proof that `claude plugin validate` passed on every changed plugin and skill.

Every plugin and every skill directory carries a `validation-report.json`. It is written locally
by `ci.py validate` — the only step that needs the `claude` CLI — and CI only checks, without
`claude`, that each plugin/skill changed compared to the base branch has a report that passed
and still matches the directory's content.

A directory's content is the files git would commit (tracked or untracked, minus ignored ones),
excluding the reports themselves, so writing a report never invalidates it.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from marketplace import CheckError, plugin_dirs, skill_dirs

REPORT_NAME = "validation-report.json"
SCHEMA_VERSION = 1
BASE_CANDIDATES = ("origin/main", "main")
FIX_HINT = "run scripts/validate-changes.sh"

Git = Callable[[Path, Sequence[str]], str]
Claude = Callable[[Sequence[str]], Tuple[int, str, str]]
Entry = Dict[str, object]  # one validated file: {file, type, errors, warnings, notes}


class ReportError(Exception):
    """A validation report that is unreadable or malformed."""


@dataclass(frozen=True)
class Target:
    """A plugin or skill directory that must carry a validation report."""

    kind: str  # "plugin" or "skill"
    name: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.kind} {self.name}"

    @property
    def report_path(self) -> Path:
        return self.path / REPORT_NAME


@dataclass(frozen=True)
class Report:
    kind: str
    name: str
    content_hash: str
    success: bool
    results: List[Entry]

    def to_json(self) -> str:
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": self.kind,
            "name": self.name,
            "contentHash": self.content_hash,
            "success": self.success,
            "results": self.results,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


@dataclass(frozen=True)
class Validation:
    """One `claude plugin validate --json` run: the verdict plus its per-file results."""

    success: bool
    manifest: Optional[Entry]
    files: List[Entry]


# --- External tools --------------------------------------------------------------------------


def run_git(repo: Path, args: Sequence[str]) -> str:
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                                check=False)
    except FileNotFoundError as exc:
        raise CheckError("`git` is not installed") from exc
    if result.returncode != 0:
        raise CheckError(f"`git {' '.join(args)}` failed: {result.stderr.strip()}")
    return result.stdout


def run_claude(args: Sequence[str]) -> Tuple[int, str, str]:
    try:
        result = subprocess.run(["claude", *args], capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise CheckError("the `claude` CLI is not installed; it is needed to write "
                         "validation reports") from exc
    return result.returncode, result.stdout, result.stderr


# --- Which plugins and skills changed --------------------------------------------------------


def targets(repo: Path) -> List[Target]:
    found = []
    for plugin_dir in plugin_dirs(repo):
        found.append(Target("plugin", plugin_dir.name, plugin_dir))
        for skill_dir in skill_dirs(plugin_dir):
            found.append(Target("skill", f"{plugin_dir.name}:{skill_dir.name}", skill_dir))
    return found


def resolve_base(repo: Path, git: Git, base: Optional[str]) -> str:
    candidates = [base] if base else list(BASE_CANDIDATES)
    for ref in candidates:
        try:
            git(repo, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
        except CheckError:
            continue
        return ref
    raise CheckError(f"cannot find the base branch ({' or '.join(candidates)}); "
                     "fetch it, or pass --base")


def changed_files(repo: Path, git: Git, base_ref: str) -> Set[str]:
    """Paths (relative to `repo`) that differ from the base branch, committed or not."""
    merge_base = git(repo, ["merge-base", "HEAD", base_ref]).strip()
    tracked = git(repo, ["diff", "--name-only", "--no-renames", "--relative", "-z", merge_base])
    untracked = git(repo, ["ls-files", "-z", "--others", "--exclude-standard"])
    paths = {p for p in (tracked + untracked).split("\0") if p}
    return {p for p in paths if Path(p).name != REPORT_NAME}


def changed_targets(repo: Path, git: Git, base: Optional[str]) -> List[Target]:
    changed = changed_files(repo, git, resolve_base(repo, git, base))
    selected = []
    for target in targets(repo):
        prefix = target.path.relative_to(repo)
        if any(Path(p).is_relative_to(prefix) for p in changed):
            selected.append(target)
    return selected


# --- Content hash ----------------------------------------------------------------------------


def content_hash(target: Target, git: Git) -> str:
    """SHA-256 over the relative path and content of every file git would commit in `target`."""
    listing = git(target.path, ["ls-files", "-z", "--cached", "--others", "--exclude-standard",
                                "--", "."])
    digest = hashlib.sha256()
    for rel in sorted({p for p in listing.split("\0") if p}):
        path = target.path / rel
        if Path(rel).name == REPORT_NAME or not path.is_file():
            continue  # reports don't count; tracked-but-deleted files are gone
        try:
            file_digest = hashlib.sha256(path.read_bytes()).digest()
        except OSError as exc:
            raise CheckError(f"cannot read {path}: {exc.strerror}") from exc
        digest.update(rel.encode("utf-8") + b"\0" + file_digest)
    return f"sha256:{digest.hexdigest()}"


# --- Writing reports (local, needs `claude`) -------------------------------------------------


def parse_entry(item: object, repo_root: Path) -> Entry:
    """One validator result, with its machine-specific absolute path made repo-relative."""
    if not isinstance(item, dict) or not isinstance(item.get("file"), str):
        raise CheckError(f"unexpected entry in validator output: {item!r}")
    try:
        file = Path(item["file"]).resolve().relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise CheckError(f"validator reported a file outside the repository: "
                         f"{item['file']}") from exc
    entry: Entry = {"file": file, "type": item.get("type")}
    for key in ("errors", "warnings", "notes"):
        findings = item.get(key, [])
        if not isinstance(findings, list):
            raise CheckError(f"validator output has a non-list {key!r} for {file}")
        entry[key] = findings
    return entry


def run_validate(claude: Claude, path: Path, repo_root: Path) -> Validation:
    code, stdout, stderr = claude(["plugin", "validate", str(path), "--strict", "--json"])
    if code not in (0, 1):
        raise CheckError(f"`claude plugin validate {path}` failed unexpectedly "
                         f"(exit {code}): {stderr.strip()}")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CheckError(f"`claude plugin validate {path}` printed invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("success"), bool) \
            or not isinstance(data.get("contents"), list):
        raise CheckError(f"`claude plugin validate {path}` printed an unexpected report shape")
    manifest = data.get("manifest")
    return Validation(
        success=data["success"],
        manifest=None if manifest is None else parse_entry(manifest, repo_root),
        files=[parse_entry(item, repo_root) for item in data["contents"]],
    )


def has_findings(entry: Entry) -> bool:
    return bool(entry["errors"] or entry["warnings"])


def build_report(target: Target, validation: Validation, repo_root: Path, git: Git) -> Report:
    manifest = [validation.manifest] if validation.manifest else []
    if target.kind == "plugin":
        entries, success = manifest + validation.files, validation.success
    else:
        # One run covers all of a plugin's skills: keep this skill's files. A run-level
        # manifest result (e.g. the skills directory is a symlink) concerns every skill.
        skill_rel = target.path.resolve().relative_to(repo_root)
        entries = manifest + [e for e in validation.files
                              if Path(str(e["file"])).is_relative_to(skill_rel)]
        success = not any(has_findings(e) for e in entries)
    return Report(target.kind, target.name, content_hash(target, git), success, entries)


def write_reports(repo: Path, git: Git, claude: Claude,
                  base: Optional[str]) -> List[Tuple[Target, Report]]:
    """Validate every changed plugin and skill and write its report; returns what was written."""
    repo_root = repo.resolve()
    skills_runs: Dict[Path, Validation] = {}
    written = []
    for target in changed_targets(repo, git, base):
        if target.kind == "plugin":
            validation = run_validate(claude, target.path, repo_root)
        else:
            skills_dir = target.path.parent
            if skills_dir not in skills_runs:
                skills_runs[skills_dir] = run_validate(claude, skills_dir, repo_root)
            validation = skills_runs[skills_dir]
        report = build_report(target, validation, repo_root, git)
        target.report_path.write_text(report.to_json(), encoding="utf-8")
        written.append((target, report))
    return written


# --- Checking reports (CI, no `claude` needed) -----------------------------------------------


def load_report(path: Path) -> Report:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReportError(f"cannot read {path}: {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise ReportError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ReportError(f"{path} is not a JSON object")
    if data.get("schemaVersion") != SCHEMA_VERSION:
        raise ReportError(f"{path} has schemaVersion {data.get('schemaVersion')!r}, "
                          f"expected {SCHEMA_VERSION}")
    kind, name, content_hash_ = data.get("kind"), data.get("name"), data.get("contentHash")
    success, results = data.get("success"), data.get("results")
    if not (isinstance(kind, str) and isinstance(name, str) and isinstance(content_hash_, str)
            and isinstance(success, bool) and isinstance(results, list)):
        raise ReportError(f"{path} is malformed: expected string kind/name/contentHash, "
                          "boolean success and a results array")
    return Report(kind, name, content_hash_, success, results)


def check_target(target: Target, git: Git) -> Optional[str]:
    """None when the target's report is present, passed and current; else why not."""
    if not target.report_path.is_file():
        return f"{target.label}: missing {REPORT_NAME} — {FIX_HINT}"
    try:
        report = load_report(target.report_path)
    except ReportError as exc:
        return f"{target.label}: {exc} — {FIX_HINT}"
    if (report.kind, report.name) != (target.kind, target.name):
        return f"{target.label}: report is for {report.kind} {report.name} — {FIX_HINT}"
    if not report.success:
        return f"{target.label}: the recorded validation failed, see {target.report_path}"
    if report.content_hash != content_hash(target, git):
        return (f"{target.label}: report is stale, the directory changed since it was written "
                f"— {FIX_HINT}")
    return None


def check_reports(repo: Path, git: Git, base: Optional[str]) -> List[str]:
    """Failure messages for every changed plugin/skill without a passing, current report."""
    failures = []
    for target in changed_targets(repo, git, base):
        failure = check_target(target, git)
        if failure:
            failures.append(failure)
        else:
            print(f"ok: {target.label}")
    return failures
