#!/usr/bin/env python3
"""Fetch your GitHub commits for a date range and render a per-day work log.

Two commands, used by the work-log skill:

  fetch   Search GitHub (via the `gh` CLI) for commits authored by the logged-in user,
          save them to a JSON file and print a per-day digest of commit subjects.
  render  Combine the saved commits with per-day summaries into a Markdown work log.

Standard library only; requires Python 3.9+ and an authenticated `gh` CLI.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# GitHub search API limits: https://docs.github.com/en/rest/search/search
SEARCH_RESULT_CAP = 1000  # "up to 1,000 results for each search"
PER_PAGE = 100  # maximum page size for search/commits
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_WAIT_SECONDS = 60  # search allows 30 requests per minute when authenticated

MERGE_SUBJECT = re.compile(r"^Merge (pull request|branch|remote)")

GhRunner = Callable[[Sequence[str]], str]
Sleeper = Callable[[float], None]


class WorkLogError(Exception):
    """A failure the user must act on; printed without a traceback."""


@dataclass(frozen=True)
class Commit:
    sha: str
    repo: str
    date: str  # ISO 8601 author date with the author's local UTC offset
    message: str
    url: str

    @property
    def day(self) -> str:
        """Author-local calendar day (the offset in `date` is the author's own)."""
        return self.date[:10]

    @property
    def time(self) -> str:
        return self.date[11:16]

    @property
    def subject(self) -> str:
        return self.message.split("\n", 1)[0]

    @property
    def is_merge(self) -> bool:
        return MERGE_SUBJECT.match(self.subject) is not None

    @property
    def merge_title(self) -> str:
        """For a PR merge, the PR title (first non-empty body line); otherwise the subject."""
        body = [line for line in self.message.split("\n")[1:] if line.strip()]
        return body[0].strip() if self.is_merge and body else self.subject

    @classmethod
    def from_search_item(cls, item: object) -> Commit:
        """Parse one item of the GitHub search/commits response."""
        try:
            if not isinstance(item, dict):
                raise TypeError("item is not an object")
            commit = item["commit"]
            fields = {
                "sha": item["sha"],
                "repo": item["repository"]["full_name"],
                "date": commit["author"]["date"],
                "message": commit["message"],
                "url": item["html_url"],
            }
        except (KeyError, TypeError) as exc:
            raise WorkLogError(f"unexpected commit shape in GitHub response: {exc!r}") from exc
        return cls._validated(fields, "GitHub response")

    @classmethod
    def from_saved(cls, data: object) -> Commit:
        if not isinstance(data, dict):
            raise WorkLogError("saved commit is not an object")
        return cls._validated(data, "saved commits file")

    @classmethod
    def _validated(cls, fields: Dict[str, object], source: str) -> Commit:
        expected = ("sha", "repo", "date", "message", "url")
        missing = [k for k in expected if not isinstance(fields.get(k), str)]
        if missing:
            raise WorkLogError(f"commit in {source} has missing/non-string fields: {missing}")
        commit_date = str(fields["date"])
        try:
            date.fromisoformat(commit_date[:10])
        except ValueError as exc:
            raise WorkLogError(f"commit in {source} has an invalid date: {commit_date!r}") from exc
        return cls(**{k: str(fields[k]) for k in expected})


@dataclass(frozen=True)
class CommitSet:
    author: str
    owner: Optional[str]
    start: date
    end: date
    commits: List[Commit]


# --- GitHub access ---------------------------------------------------------------------------


def run_gh(args: Sequence[str]) -> str:
    try:
        result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise WorkLogError("GitHub CLI `gh` is not installed: https://cli.github.com") from exc
    if result.returncode != 0:
        raise WorkLogError(f"`gh {' '.join(args)}` failed: {result.stderr.strip()}")
    return result.stdout


def with_rate_limit_retry(gh: GhRunner, sleep: Sleeper = time.sleep) -> GhRunner:
    def runner(args: Sequence[str]) -> str:
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                return gh(args)
            except WorkLogError as exc:
                if "rate limit" not in str(exc).lower() or attempt == RATE_LIMIT_RETRIES:
                    raise
                print(f"GitHub rate limit hit, waiting {RATE_LIMIT_WAIT_SECONDS}s…", file=sys.stderr)
                sleep(RATE_LIMIT_WAIT_SECONDS)
        raise AssertionError("unreachable")

    return runner


def parse_json(raw: str, what: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkLogError(f"could not parse {what} as JSON: {exc}") from exc


def current_login(gh: GhRunner) -> str:
    user = parse_json(gh(["api", "user"]), "`gh api user` output")
    login = user.get("login") if isinstance(user, dict) else None
    if not isinstance(login, str) or not login:
        raise WorkLogError("could not determine your GitHub login; run `gh auth login`")
    return login


def build_query(author: str, owner: Optional[str], start: date, end: date) -> str:
    query = f"author:{author} author-date:{start.isoformat()}..{end.isoformat()}"
    return f"{query} org:{owner}" if owner else query


def search_page(gh: GhRunner, query: str, page: int) -> Tuple[int, List[Commit]]:
    raw = gh(["api", "-X", "GET", "search/commits", "-f", f"q={query}",
              "-f", f"per_page={PER_PAGE}", "-f", f"page={page}"])
    data = parse_json(raw, "GitHub search response")
    if not isinstance(data, dict) or not isinstance(data.get("total_count"), int) \
            or not isinstance(data.get("items"), list):
        raise WorkLogError("GitHub search response is missing total_count/items")
    return data["total_count"], [Commit.from_search_item(i) for i in data["items"]]


def fetch_window(gh: GhRunner, author: str, owner: Optional[str],
                 start: date, end: date) -> List[Commit]:
    """Fetch every commit in [start, end], splitting the window when it exceeds the search cap."""
    query = build_query(author, owner, start, end)
    total, commits = search_page(gh, query, 1)
    if total > SEARCH_RESULT_CAP:
        if start == end:
            raise WorkLogError(f"{total} commits on {start} exceed GitHub's "
                               f"{SEARCH_RESULT_CAP}-result search cap; cannot fetch them all")
        middle = start + (end - start) // 2
        return (fetch_window(gh, author, owner, start, middle)
                + fetch_window(gh, author, owner, middle + timedelta(days=1), end))
    page = 1
    while len(commits) < total:
        page += 1
        _, items = search_page(gh, query, page)
        if not items:
            break
        commits.extend(items)
    if len(commits) != total:
        raise WorkLogError(f"GitHub reported {total} commits for `{query}` but returned "
                           f"{len(commits)}; rerun, or narrow the date range")
    return commits


def month_windows(start: date, end: date) -> List[Tuple[date, date]]:
    windows = []
    current = start
    while current <= end:
        next_month = (current.replace(day=1) + timedelta(days=32)).replace(day=1)
        window_end = min(end, next_month - timedelta(days=1))
        windows.append((current, window_end))
        current = window_end + timedelta(days=1)
    return windows


def fetch_commits(gh: GhRunner, author: str, owner: Optional[str],
                  start: date, end: date) -> List[Commit]:
    """Commits whose author-local day lies in [start, end], deduplicated and sorted by date.

    The search is widened by a day on each side because GitHub's date qualifier need not use
    the author's time zone; the result is then filtered on the author-local day.
    """
    by_sha: Dict[str, Commit] = {}
    for window_start, window_end in month_windows(start - timedelta(days=1), end + timedelta(days=1)):
        for commit in fetch_window(gh, author, owner, window_start, window_end):
            by_sha.setdefault(commit.sha, commit)
    in_range = [c for c in by_sha.values() if start.isoformat() <= c.day <= end.isoformat()]
    return sorted(in_range, key=lambda c: c.date)


# --- Persistence -----------------------------------------------------------------------------


def save_commit_set(commit_set: CommitSet, path: Path) -> None:
    payload = {
        "author": commit_set.author,
        "owner": commit_set.owner,
        "from": commit_set.start.isoformat(),
        "to": commit_set.end.isoformat(),
        "commits": [asdict(c) for c in commit_set.commits],
    }
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def load_commit_set(path: Path) -> CommitSet:
    data = parse_json(read_text(path), str(path))
    if not isinstance(data, dict) or not isinstance(data.get("commits"), list) \
            or not isinstance(data.get("author"), str):
        raise WorkLogError(f"{path} is not a commits file written by `work_log.py fetch`")
    owner = data.get("owner")
    return CommitSet(
        author=data["author"],
        owner=owner if isinstance(owner, str) else None,
        start=parse_day(str(data.get("from")), f"{path} 'from'"),
        end=parse_day(str(data.get("to")), f"{path} 'to'"),
        commits=[Commit.from_saved(c) for c in data["commits"]],
    )


def load_summaries(path: Path) -> Dict[str, str]:
    data = parse_json(read_text(path), str(path))
    if not isinstance(data, dict):
        raise WorkLogError(f"{path} must be a JSON object of {{\"YYYY-MM-DD\": \"summary\"}}")
    summaries = {}
    for day, text in data.items():
        parse_day(day, f"summary key in {path}")
        if not isinstance(text, str) or not text.strip():
            raise WorkLogError(f"summary for {day} in {path} must be a non-empty string")
        summaries[day] = text.strip()
    return summaries


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkLogError(f"cannot read {path}: {exc.strerror}") from exc


def parse_day(value: str, what: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise WorkLogError(f"{what} must be a YYYY-MM-DD date, got {value!r}") from exc


# --- Output ----------------------------------------------------------------------------------


def group_by_day(commits: Sequence[Commit]) -> Dict[str, List[Commit]]:
    by_day: Dict[str, List[Commit]] = defaultdict(list)
    for commit in sorted(commits, key=lambda c: c.date):
        by_day[commit.day].append(commit)
    return dict(sorted(by_day.items()))


def weekdays_without_commits(days_with_commits: Sequence[str], start: date, end: date) -> List[str]:
    active = set(days_with_commits)
    result = []
    current = start
    while current <= end:
        if current.weekday() < 5 and current.isoformat() not in active:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def short_repo(repo: str) -> str:
    return repo.split("/", 1)[-1]


def digest(commits: Sequence[Commit]) -> str:
    """Per-day, per-repo commit subjects for writing summaries; merges show the PR title."""
    lines = []
    for day, day_commits in group_by_day(commits).items():
        lines.append(f"## {day}")
        by_repo: Dict[str, List[Commit]] = defaultdict(list)
        for commit in day_commits:
            by_repo[commit.repo].append(commit)
        for repo, repo_commits in sorted(by_repo.items()):
            lines.append(f"[{short_repo(repo)}]")
            lines.extend(f"- merged: {c.merge_title}" if c.is_merge else f"- {c.subject}"
                         for c in repo_commits)
    return "\n".join(lines)


def escape_markdown(text: str) -> str:
    return re.sub(r"([\\`*_\[\]<>|])", r"\\\1", text)


def render(commit_set: CommitSet, summaries: Dict[str, str]) -> str:
    by_day = group_by_day(commit_set.commits)
    missing = [d for d in by_day if d not in summaries]
    extra = sorted(d for d in summaries if d not in by_day)
    if missing or extra:
        raise WorkLogError(f"summaries don't match commit days: missing={missing} "
                           f"without commits={extra}")
    start, end = commit_set.start.isoformat(), commit_set.end.isoformat()
    scope = f" in `{commit_set.owner}`" if commit_set.owner else ""
    idle = weekdays_without_commits(list(by_day), commit_set.start, commit_set.end)
    lines = [
        f"# Work log {start} – {end}",
        "",
        f"Source: GitHub commit search for `{commit_set.author}`{scope} (default branches only). "
        f"{len(commit_set.commits)} commits on {len(by_day)} days.",
        "",
        "Weekdays with no GitHub commits: " + (", ".join(idle) or "none") + ".",
        "",
    ]
    for day, day_commits in by_day.items():
        weekday = date.fromisoformat(day).strftime("%a")
        lines += [f"## {weekday} {day}", "", summaries[day], "",
                  f"<details><summary>{len(day_commits)} commits</summary>", ""]
        lines.extend(f"- {c.time} `{short_repo(c.repo)}` [{c.sha[:7]}]({c.url}) "
                     f"{escape_markdown(c.subject)}" for c in day_commits)
        lines += ["", "</details>", ""]
    return "\n".join(lines)


# --- CLI -------------------------------------------------------------------------------------


def cmd_fetch(args: argparse.Namespace, gh: GhRunner) -> None:
    start, end = parse_day(args.start, "FROM"), parse_day(args.end, "TO")
    if start > end:
        raise WorkLogError(f"FROM ({start}) is after TO ({end})")
    author = args.author or current_login(gh)
    commits = fetch_commits(gh, author, args.owner, start, end)
    save_commit_set(CommitSet(author, args.owner, start, end, commits), Path(args.out))
    print(digest(commits))
    print(f"\nSaved {len(commits)} commits on {len(group_by_day(commits))} days by {author} "
          f"to {args.out}", file=sys.stderr)


def cmd_render(args: argparse.Namespace) -> None:
    commit_set = load_commit_set(Path(args.commits))
    output = render(commit_set, load_summaries(Path(args.summaries)))
    Path(args.out).write_text(output, encoding="utf-8")
    print(f"Wrote {args.out}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="download commits and print a per-day digest")
    fetch.add_argument("start", metavar="FROM", help="first day, YYYY-MM-DD")
    fetch.add_argument("end", metavar="TO", help="last day, YYYY-MM-DD")
    fetch.add_argument("--out", required=True, help="commits JSON file to write")
    fetch.add_argument("--owner", help="only repositories of this GitHub organization")
    fetch.add_argument("--author", help="GitHub login (default: the `gh` logged-in user)")
    rend = sub.add_parser("render", help="write the Markdown work log")
    rend.add_argument("--commits", required=True, help="file written by `fetch`")
    rend.add_argument("--summaries", required=True, help='JSON object {"YYYY-MM-DD": "summary"}')
    rend.add_argument("--out", required=True, help="Markdown file to write")
    return parser


def main(argv: Optional[Sequence[str]] = None, gh: Optional[GhRunner] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "fetch":
            cmd_fetch(args, gh or with_rate_limit_retry(run_gh))
        else:
            cmd_render(args)
    except WorkLogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
