"""Tests for validation_reports.py. Run: python3 -m unittest discover -s <this directory>"""
from __future__ import annotations

import io
import json
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from typing import List, Optional, Tuple
from unittest import mock

import validation_reports as vr
from marketplace import CheckError
from test_support import FakeClaude, MarketplaceTestCase, entry, git, validator_output, write
from validation_reports import (REPORT_NAME, Report, ReportError, Target, check_reports,
                                changed_targets, content_hash, load_report, resolve_base,
                                run_claude, run_git, targets, write_reports)


class ReportTestCase(MarketplaceTestCase):
    def edit(self, skill: str, text: str = "changed\n") -> None:
        with (self.skill(skill) / "SKILL.md").open("a", encoding="utf-8") as handle:
            handle.write(text)

    def target(self, kind: str, name: Optional[str] = None) -> Target:
        wanted = name or (self.PLUGIN if kind == "plugin" else f"{self.PLUGIN}:one")
        return next(t for t in targets(self.root) if (t.kind, t.name) == (kind, wanted))

    def labels(self, base: Optional[str] = None) -> List[str]:
        return [t.label for t in changed_targets(self.root, run_git, base)]

    def write(self, claude: Optional[FakeClaude] = None) -> List[Tuple[Target, Report]]:
        return write_reports(self.root, run_git, claude or FakeClaude(), None)

    def check(self) -> List[str]:
        with redirect_stdout(io.StringIO()):
            return check_reports(self.root, run_git, None)


class ChangedTargetsTests(ReportTestCase):
    def test_targets_list_plugin_then_its_skills(self) -> None:
        self.assertEqual([t.label for t in targets(self.root)],
                         ["plugin alpha", "skill alpha:one", "skill alpha:two"])

    def test_nothing_changed(self) -> None:
        self.assertEqual(self.labels(), [])

    def test_uncommitted_edit_marks_its_skill_and_plugin(self) -> None:
        self.edit("one")
        self.assertEqual(self.labels(), ["plugin alpha", "skill alpha:one"])

    def test_untracked_file_counts(self) -> None:
        write(self.skill("two") / "scripts" / "new.py")
        self.assertEqual(self.labels(), ["plugin alpha", "skill alpha:two"])

    def test_committed_change_on_a_branch_counts(self) -> None:
        git(self.root, "switch", "-c", "feature")
        self.edit("one")
        self.commit("edit one")
        self.assertEqual(self.labels(), ["plugin alpha", "skill alpha:one"])

    def test_plugin_level_change_leaves_skills_alone(self) -> None:
        write(self.plugin / ".claude-plugin" / "plugin.json", '{"name": "alpha", "version": "2"}')
        self.assertEqual(self.labels(), ["plugin alpha"])

    def test_removing_a_skill_marks_only_the_plugin(self) -> None:
        (self.skill("two") / "SKILL.md").unlink()
        self.assertEqual(self.labels(), ["plugin alpha"])

    def test_reports_alone_are_not_a_change(self) -> None:
        write(self.skill("one") / REPORT_NAME)
        write(self.plugin / REPORT_NAME)
        self.assertEqual(self.labels(), [])

    def test_files_outside_plugins_and_sibling_prefixes_are_ignored(self) -> None:
        write(self.root / "README.md")
        write(self.root / "plugins" / "alpha-other" / "file.txt")
        self.assertEqual(self.labels(), [])

    def test_base_defaults_to_main_and_prefers_origin_main(self) -> None:
        self.assertEqual(resolve_base(self.root, run_git, None), "main")
        git(self.root, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertEqual(resolve_base(self.root, run_git, None), "origin/main")
        self.assertEqual(resolve_base(self.root, run_git, "main"), "main")

    def test_unknown_base_is_an_error(self) -> None:
        with self.assertRaisesRegex(CheckError, "cannot find the base branch .*nope"):
            resolve_base(self.root, run_git, "nope")


class ContentHashTests(ReportTestCase):
    def test_hash_tracks_content_but_not_reports_or_ignored_files(self) -> None:
        target = self.target("skill")
        before = content_hash(target, run_git)
        self.assertRegex(before, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(content_hash(target, run_git), before)

        write(target.path / REPORT_NAME, "anything")
        write(target.path / "__pycache__" / "x.pyc")
        self.assertEqual(content_hash(target, run_git), before)

        self.edit("one")
        edited = content_hash(target, run_git)
        self.assertNotEqual(edited, before)
        write(target.path / "new.txt")
        self.assertNotEqual(content_hash(target, run_git), edited)

    def test_hash_depends_on_file_names(self) -> None:
        target = self.target("skill")
        before = content_hash(target, run_git)
        (target.path / "SKILL.md").rename(target.path / "RENAMED.md")
        self.assertNotEqual(content_hash(target, run_git), before)

    def test_tracked_but_deleted_files_are_skipped(self) -> None:
        target = self.target("plugin")
        before = content_hash(target, run_git)
        (self.plugin / ".claude-plugin" / "plugin.json").unlink()
        self.assertNotEqual(content_hash(target, run_git), before)

    def test_unreadable_file_is_reported(self) -> None:
        with mock.patch.object(Path, "read_bytes", side_effect=PermissionError(13, "denied")):
            with self.assertRaisesRegex(CheckError, "cannot read"):
                content_hash(self.target("skill"), run_git)


class WriteReportsTests(ReportTestCase):
    def plugin_manifest(self) -> dict:
        return entry(self.plugin / ".claude-plugin" / "plugin.json", "plugin")

    def test_nothing_changed_writes_nothing_and_never_calls_claude(self) -> None:
        claude = FakeClaude()
        self.assertEqual(self.write(claude), [])
        self.assertEqual(claude.validated, [])

    def test_writes_a_report_per_changed_plugin_and_skill(self) -> None:
        self.edit("one")
        self.edit("two")
        claude = FakeClaude()
        written = self.write(claude)
        self.assertEqual([t.label for t, _ in written],
                         ["plugin alpha", "skill alpha:one", "skill alpha:two"])
        # one run for the plugin, one shared by both skills
        self.assertEqual(claude.validated, [self.plugin, self.plugin / "skills"])
        for target, report in written:
            on_disk = json.loads(target.report_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["schemaVersion"], 1)
            self.assertEqual((on_disk["kind"], on_disk["name"]), (target.kind, target.name))
            self.assertEqual(on_disk["contentHash"], content_hash(target, run_git))
            self.assertIs(on_disk["success"], True)
            self.assertEqual(load_report(target.report_path), report)
        self.assertTrue(target.report_path.read_text(encoding="utf-8").endswith("}\n"))

    def test_results_use_repo_relative_paths_and_keep_only_the_skills_own_files(self) -> None:
        self.edit("one")
        self.edit("two")

        def handler(path: Path) -> Tuple[int, str, str]:
            if path.name == "skills":
                files = [entry(self.skill("one") / "SKILL.md"),
                         entry(self.skill("two") / "SKILL.md", warnings=[{"message": "w"}])]
                return 1, validator_output(path, False, contents=files), ""
            return 0, validator_output(path, manifest=self.plugin_manifest()), ""

        by_label = {t.label: r for t, r in self.write(FakeClaude(handler))}
        self.assertEqual([e["file"] for e in by_label["plugin alpha"].results],
                         ["plugins/alpha/.claude-plugin/plugin.json"])
        self.assertTrue(by_label["plugin alpha"].success)
        self.assertEqual([e["file"] for e in by_label["skill alpha:one"].results],
                         ["plugins/alpha/skills/one/SKILL.md"])
        self.assertTrue(by_label["skill alpha:one"].success)
        self.assertEqual([e["file"] for e in by_label["skill alpha:two"].results],
                         ["plugins/alpha/skills/two/SKILL.md"])
        self.assertFalse(by_label["skill alpha:two"].success)

    def test_failed_plugin_validation_is_recorded(self) -> None:
        self.edit("one")
        error = {"path": "name", "message": "bad"}

        def handler(path: Path) -> Tuple[int, str, str]:
            if path.name == "skills":
                return 0, validator_output(path), ""
            return 1, validator_output(path, False, entry(self.plugin, "plugin", errors=[error])), ""

        by_label = {t.label: r for t, r in self.write(FakeClaude(handler))}
        self.assertFalse(by_label["plugin alpha"].success)
        self.assertEqual(by_label["plugin alpha"].results[0]["errors"], [error])
        self.assertTrue(by_label["skill alpha:one"].success)

    def test_run_level_manifest_problem_fails_every_skill(self) -> None:
        self.edit("one")
        error = {"path": "directory", "message": "symlinked"}

        def handler(path: Path) -> Tuple[int, str, str]:
            if path.name == "skills":
                return 1, validator_output(path, False, entry(path, "plugin", errors=[error])), ""
            return 0, validator_output(path), ""

        by_label = {t.label: r for t, r in self.write(FakeClaude(handler))}
        self.assertFalse(by_label["skill alpha:one"].success)
        self.assertEqual(by_label["skill alpha:one"].results[0]["errors"], [error])

    def test_validator_crash_is_an_error(self) -> None:
        self.edit("one")
        with self.assertRaisesRegex(CheckError, r"failed unexpectedly \(exit 2\): boom"):
            self.write(FakeClaude(lambda path: (2, "", "boom\n")))

    def test_unusable_validator_output_is_an_error(self) -> None:
        self.edit("one")
        good_file = entry(self.skill("one") / "SKILL.md")
        cases = {
            "printed invalid JSON": "not json",
            "unexpected report shape": "[]",
            "unexpected report shape ": json.dumps({"success": "yes", "contents": []}),
            "unexpected entry": json.dumps({"success": True, "contents": ["x"]}),
            "unexpected entry ": json.dumps({"success": True, "contents": [{"type": "skill"}]}),
            "outside the repository": json.dumps(
                {"success": True, "contents": [entry(Path("/definitely/elsewhere/SKILL.md"))]}),
            "non-list 'errors'": json.dumps(
                {"success": True, "contents": [{**good_file, "errors": "oops"}]}),
        }
        for message, stdout in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(CheckError, message.strip()):
                    self.write(FakeClaude(lambda path, out=stdout: (0, out, "")))

    def test_missing_optional_fields_default_to_empty(self) -> None:
        self.edit("one")
        bare = {"file": str(self.skill("one") / "SKILL.md")}
        stdout = json.dumps({"success": True, "contents": [bare]})
        by_label = {t.label: r for t, r in self.write(FakeClaude(lambda p: (0, stdout, "")))}
        self.assertEqual(by_label["skill alpha:one"].results,
                         [{"file": "plugins/alpha/skills/one/SKILL.md", "type": None,
                           "errors": [], "warnings": [], "notes": []}])


class CheckReportsTests(ReportTestCase):
    def test_nothing_changed_needs_no_reports(self) -> None:
        self.assertEqual(self.check(), [])

    def test_changed_without_reports_fails_for_each_target(self) -> None:
        self.edit("one")
        failures = self.check()
        self.assertEqual(len(failures), 2)
        self.assertIn(f"plugin alpha: missing {REPORT_NAME}", failures[0])
        self.assertIn("skill alpha:one: missing", failures[1])
        self.assertIn("scripts/validate-changes.sh", failures[1])

    def test_fresh_reports_pass(self) -> None:
        self.edit("one")
        self.write()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(check_reports(self.root, run_git, None), [])
        self.assertIn("ok: plugin alpha", out.getvalue())
        self.assertIn("ok: skill alpha:one", out.getvalue())

    def test_report_goes_stale_when_the_directory_changes_again(self) -> None:
        self.edit("one")
        self.write()
        self.edit("one", "more\n")
        failures = self.check()
        self.assertEqual(len(failures), 2)
        self.assertTrue(all("report is stale" in f for f in failures))

    def test_untouched_skill_report_stays_valid_when_a_sibling_changes(self) -> None:
        self.edit("one")
        self.edit("two")
        self.write()
        self.edit("one", "again\n")
        failures = self.check()
        self.assertEqual([f.split(":")[0] for f in failures], ["plugin alpha", "skill alpha"])
        self.assertTrue(all("report is stale" in f for f in failures))
        self.assertIn("skill alpha:one: report is stale", failures[1])
        self.assertFalse(any("alpha:two" in f for f in failures))

    def test_a_recorded_failure_fails_the_check(self) -> None:
        self.edit("one")
        warning = {"message": "w"}

        def handler(path: Path) -> Tuple[int, str, str]:
            if path.name != "skills":
                return 0, validator_output(path), ""
            files = [entry(self.skill("one") / "SKILL.md", warnings=[warning])]
            return 1, validator_output(path, False, contents=files), ""

        self.write(FakeClaude(handler))
        failures = self.check()
        self.assertEqual(len(failures), 1)
        self.assertIn("skill alpha:one: the recorded validation failed", failures[0])

    def test_unusable_reports_fail_with_a_reason(self) -> None:
        self.edit("one")
        self.write()
        path = self.skill("one") / REPORT_NAME
        good = json.loads(path.read_text(encoding="utf-8"))
        cases = {
            "not valid JSON": "not json",
            "not a JSON object": "[]",
            "schemaVersion 2": json.dumps({**good, "schemaVersion": 2}),
            "is malformed": json.dumps({**good, "success": "yes"}),
            "is malformed ": json.dumps({k: v for k, v in good.items() if k != "contentHash"}),
            "report is for skill other:name": json.dumps({**good, "name": "other:name"}),
            "report is for plugin alpha": json.dumps({**good, "kind": "plugin", "name": "alpha"}),
        }
        for message, text in cases.items():
            with self.subTest(message=message):
                path.write_text(text, encoding="utf-8")
                failures = [f for f in self.check() if f.startswith("skill alpha:one")]
                self.assertEqual(len(failures), 1)
                self.assertIn(message.strip(), failures[0])

    def test_unreadable_report_is_a_report_error(self) -> None:
        with mock.patch.object(Path, "read_text", side_effect=PermissionError(13, "denied")):
            with self.assertRaisesRegex(ReportError, "cannot read"):
                load_report(self.root / REPORT_NAME)


class ToolRunnerTests(ReportTestCase):
    def test_run_git_returns_stdout(self) -> None:
        self.assertEqual(run_git(self.root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip(), "main")

    def test_run_git_failure_is_a_check_error(self) -> None:
        with self.assertRaisesRegex(CheckError, "failed: "):
            run_git(self.root, ["rev-parse", "--verify", "no-such-ref"])

    def test_missing_executables_are_check_errors(self) -> None:
        with mock.patch.object(vr.subprocess, "run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(CheckError, "`git` is not installed"):
                run_git(self.root, ["status"])
            with self.assertRaisesRegex(CheckError, "`claude` CLI is not installed"):
                run_claude(["plugin", "validate", "."])

    def test_run_claude_returns_exit_code_and_output(self) -> None:
        done = subprocess.CompletedProcess(["claude"], 1, stdout="out", stderr="err")
        with mock.patch.object(vr.subprocess, "run", return_value=done) as run:
            self.assertEqual(run_claude(["plugin", "validate", "x"]), (1, "out", "err"))
        self.assertEqual(run.call_args.args[0], ["claude", "plugin", "validate", "x"])


if __name__ == "__main__":
    import unittest

    unittest.main()
