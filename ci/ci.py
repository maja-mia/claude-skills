#!/usr/bin/env python3
"""Repository checks for the claude-skills marketplace.

Used through scripts/test.sh (locally and in CI, inside Docker) and scripts/validate-changes.sh.

  plugins    Print the plugin directories listed in the marketplace, one per line (relative).
  tests      Run the unittest tests of every component (each skill, plus ci/ itself) with branch
             coverage of at least COVERAGE_THRESHOLD %; a component with Python code but no
             tests fails. Then check the validation reports: every plugin and skill changed
             compared to the base branch needs a passing, current validation-report.json
             (see validation_reports.py).
  validate   Local only, needs the `claude` CLI: run `claude plugin validate` on every plugin
             and skill changed compared to the base branch and write their reports.

The base branch is --base, else origin/main, else main. Standard library only (coverage runs
as a subprocess); Python 3.9 is the version we test.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence

import validation_reports as reports
from marketplace import CheckError, plugin_dirs, skill_dirs

COVERAGE_THRESHOLD = 90
TEST_PATTERN = "test_*.py"

Runner = Callable[[Sequence[str]], int]


@dataclass(frozen=True)
class Component:
    """A directory whose Python code must be tested: a skill, or the CI tooling itself."""

    name: str
    path: Path

    def python_files(self) -> List[Path]:
        return sorted(p for p in self.path.rglob("*.py") if "__pycache__" not in p.parts)

    def test_files(self) -> List[Path]:
        return [p for p in self.python_files() if p.match(TEST_PATTERN)]

    def source_files(self) -> List[Path]:
        return [p for p in self.python_files() if not p.match(TEST_PATTERN)]

    def test_dirs(self) -> List[Path]:
        return sorted({p.parent for p in self.test_files()})


def run_command(args: Sequence[str]) -> int:
    print(f"$ {' '.join(args)}", flush=True)
    return subprocess.run(list(args), check=False).returncode


@dataclass(frozen=True)
class Tools:
    """The external commands the checks shell out to, replaceable in tests."""

    run: Runner = run_command
    git: reports.Git = reports.run_git
    claude: reports.Claude = reports.run_claude


def components(repo: Path) -> List[Component]:
    found = [Component("ci", repo / "ci")]
    for plugin_dir in plugin_dirs(repo):
        for skill_dir in skill_dirs(plugin_dir):
            found.append(Component(f"{plugin_dir.name}:{skill_dir.name}", skill_dir))
    return found


def check_component(component: Component, run: Runner, data_dir: Path) -> List[str]:
    """Run a component's tests with branch coverage; return failure messages (none if it passes)."""
    if not component.source_files():
        print("no Python code, nothing to test")
        return []
    if not component.test_files():
        return [f"{component.name}: has Python code but no {TEST_PATTERN} tests"]
    failures = []
    data_file = data_dir / (component.name.replace(":", "_") + ".coverage")
    for test_dir in component.test_dirs():
        command = [sys.executable, "-m", "coverage", "run", "--append", "--branch",
                   f"--data-file={data_file}", f"--source={component.path}",
                   f"--omit=*/{TEST_PATTERN}",
                   "-m", "unittest", "discover", "-s", str(test_dir), "-p", TEST_PATTERN]
        if run(command) != 0:
            failures.append(f"{component.name}: tests failed in {test_dir}")
    if not failures:
        report = [sys.executable, "-m", "coverage", "report", f"--data-file={data_file}",
                  "--show-missing", f"--fail-under={COVERAGE_THRESHOLD}"]
        if run(report) != 0:
            failures.append(f"{component.name}: branch coverage below {COVERAGE_THRESHOLD}%")
    return failures


def cmd_tests(repo: Path, tools: Tools, base: Optional[str]) -> List[str]:
    failures: List[str] = []
    with tempfile.TemporaryDirectory() as data_dir:
        for component in components(repo):
            print(f"\n== {component.name} ==", flush=True)
            failures += check_component(component, tools.run, Path(data_dir))
    print("\n== validation reports ==", flush=True)
    return failures + reports.check_reports(repo, tools.git, base)


def cmd_validate(repo: Path, tools: Tools, base: Optional[str]) -> List[str]:
    written = reports.write_reports(repo, tools.git, tools.claude, base)
    if not written:
        print("no plugin or skill changed compared to the base branch")
    failures = []
    for target, report in written:
        print(f"{'passed' if report.success else 'FAILED'}: {target.label} "
              f"-> {target.report_path}")
        if not report.success:
            failures.append(f"{target.label}: validation failed, see {target.report_path}")
    return failures


def main(argv: Optional[Sequence[str]] = None, tools: Tools = Tools()) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    parser.add_argument("--base", help="branch that 'changed' is measured against "
                                       "(default: origin/main, else main)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plugins", help="list plugin directories")
    sub.add_parser("tests", help="run tests with coverage and check validation reports")
    sub.add_parser("validate", help="write validation reports for changed plugins and skills")
    args = parser.parse_args(argv)
    repo = Path(args.repo)
    try:
        if args.command == "plugins":
            for plugin_dir in plugin_dirs(repo):
                print(plugin_dir.relative_to(repo).as_posix())
            return 0
        if args.command == "validate":
            failures = cmd_validate(repo, tools, args.base)
        else:
            failures = cmd_tests(repo, tools, args.base)
    except CheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if failures:
        print("\nFAILED:\n" + "\n".join(f"  - {f}" for f in failures), file=sys.stderr)
        return 1
    if args.command == "validate":
        return 0
    print(f"\ntests + {COVERAGE_THRESHOLD}% branch coverage and validation reports: all passed")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
