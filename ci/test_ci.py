"""Tests for ci.py. Run: python3 -m unittest discover -s <this directory>"""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import List, Sequence, Tuple

from ci import COVERAGE_THRESHOLD, Component, Tools, check_component, components, main, run_command
from test_support import FakeClaude, MarketplaceTestCase, entry, validator_output, write
from validation_reports import REPORT_NAME


class FakeRun:
    """Records the commands ci.py would run and answers with scripted exit codes."""

    def __init__(self, *codes: int) -> None:
        self.codes = list(codes)
        self.commands: List[List[str]] = []

    def __call__(self, args: Sequence[str]) -> int:
        self.commands.append(list(args))
        return self.codes.pop(0) if self.codes else 0


class ComponentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def component(self, *files: str) -> Component:
        for name in files:
            write(self.root / name)
        return Component("demo", self.root)

    def test_files_are_classified_and_pycache_is_ignored(self) -> None:
        component = self.component("a.py", "test_a.py", "sub/test_b.py", "__pycache__/x.py", "n.txt")
        self.assertEqual([p.name for p in component.source_files()], ["a.py"])
        self.assertEqual([p.name for p in component.test_files()], ["test_b.py", "test_a.py"])
        self.assertEqual(component.test_dirs(), [self.root, self.root / "sub"])

    def test_without_python_code_there_is_nothing_to_test(self) -> None:
        run = FakeRun()
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(check_component(self.component("notes.md"), run, self.root), [])
        self.assertIn("nothing to test", out.getvalue())
        self.assertEqual(run.commands, [])

    def test_python_code_without_tests_fails(self) -> None:
        failures = check_component(self.component("a.py"), FakeRun(), self.root)
        self.assertEqual(failures, ["demo: has Python code but no test_*.py tests"])

    def test_failing_tests_are_reported_per_directory_and_skip_the_coverage_report(self) -> None:
        run = FakeRun(1, 0)
        component = self.component("a.py", "test_a.py", "sub/test_b.py")
        failures = check_component(component, run, self.root)
        self.assertEqual(failures, [f"demo: tests failed in {self.root}"])
        self.assertEqual(len(run.commands), 2)  # no `coverage report`

    def test_coverage_runs_branch_coverage_and_enforces_the_threshold(self) -> None:
        run = FakeRun()
        self.assertEqual(check_component(self.component("a.py", "test_a.py"), run, self.root), [])
        measure, report = run.commands
        self.assertEqual(measure[1:5], ["-m", "coverage", "run", "--append"])
        self.assertIn("--branch", measure)
        self.assertIn(f"--source={self.root}", measure)
        self.assertEqual(report[1:4], ["-m", "coverage", "report"])
        self.assertIn(f"--fail-under={COVERAGE_THRESHOLD}", report)

    def test_coverage_below_threshold_fails(self) -> None:
        run = FakeRun(0, 2)
        failures = check_component(self.component("a.py", "test_a.py"), run, self.root)
        self.assertEqual(failures, [f"demo: branch coverage below {COVERAGE_THRESHOLD}%"])

    def test_run_command_returns_the_exit_code_and_echoes_the_command(self) -> None:
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run_command([sys.executable, "-c", "pass"]), 0)
            self.assertEqual(run_command([sys.executable, "-c", "raise SystemExit(3)"]), 3)
        self.assertIn("$ ", out.getvalue())


class MainTests(MarketplaceTestCase):
    def run_main(self, *argv: str, tools: Tools = Tools()) -> Tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--repo", str(self.root), *argv], tools)
        return code, out.getvalue(), err.getvalue()

    def edit_skill(self) -> None:
        with (self.skill("one") / "SKILL.md").open("a", encoding="utf-8") as handle:
            handle.write("changed\n")

    def test_components_are_ci_plus_every_skill(self) -> None:
        self.assertEqual([c.name for c in components(self.root)], ["ci", "alpha:one", "alpha:two"])

    def test_plugins_command_lists_plugin_directories(self) -> None:
        code, out, _ = self.run_main("plugins")
        self.assertEqual((code, out), (0, "plugins/alpha\n"))

    def test_tests_pass_when_nothing_changed(self) -> None:
        code, out, _ = self.run_main("tests", tools=Tools(run=FakeRun()))
        self.assertEqual(code, 0)
        self.assertIn("tests + 90% branch coverage and validation reports: all passed", out)

    def test_failing_unit_tests_fail_the_run(self) -> None:
        write(self.skill("one") / "scripts" / "tool.py")
        write(self.skill("one") / "scripts" / "test_tool.py")
        self.commit("add python")
        code, _, err = self.run_main("tests", tools=Tools(run=FakeRun(1)))
        self.assertEqual(code, 1)
        self.assertIn("alpha:one: tests failed", err)

    def test_changed_skill_without_reports_fails_the_run(self) -> None:
        self.edit_skill()
        code, _, err = self.run_main("tests", tools=Tools(run=FakeRun()))
        self.assertEqual(code, 1)
        self.assertIn(f"skill alpha:one: missing {REPORT_NAME}", err)

    def test_validate_then_tests_pass(self) -> None:
        self.edit_skill()
        code, out, _ = self.run_main("validate", tools=Tools(claude=FakeClaude()))
        self.assertEqual(code, 0)
        self.assertIn("passed: skill alpha:one", out)
        self.assertTrue((self.skill("one") / REPORT_NAME).is_file())
        self.assertTrue((self.plugin / REPORT_NAME).is_file())
        code, _, err = self.run_main("tests", tools=Tools(run=FakeRun()))
        self.assertEqual((code, err), (0, ""))

    def test_validate_reports_failures_but_still_writes_the_report(self) -> None:
        self.edit_skill()
        file = entry(self.skill("one") / "SKILL.md", warnings=[{"message": "w"}])

        def handler(path: Path) -> Tuple[int, str, str]:
            contents = [file] if path.name == "skills" else []
            return 1, validator_output(path, False, contents=contents), ""

        code, out, err = self.run_main("validate", tools=Tools(claude=FakeClaude(handler)))
        self.assertEqual(code, 1)
        self.assertIn("FAILED: plugin alpha", out)
        self.assertIn("FAILED: skill alpha:one", out)
        self.assertIn("skill alpha:one: validation failed", err)
        self.assertTrue((self.skill("one") / REPORT_NAME).is_file())

    def test_validate_with_nothing_changed(self) -> None:
        claude = FakeClaude()
        code, out, _ = self.run_main("validate", tools=Tools(claude=claude))
        self.assertEqual(code, 0)
        self.assertIn("no plugin or skill changed", out)
        self.assertEqual(claude.validated, [])

    def test_unknown_base_exits_with_2(self) -> None:
        code, _, err = self.run_main("--base", "nope", "validate")
        self.assertEqual(code, 2)
        self.assertIn("error: cannot find the base branch", err)

    def test_missing_marketplace_exits_with_2(self) -> None:
        (self.root / ".claude-plugin" / "marketplace.json").unlink()
        code, _, err = self.run_main("plugins")
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)


if __name__ == "__main__":
    unittest.main()
