"""Tests for marketplace.py. Run: python3 -m unittest discover -s <this directory>"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from marketplace import MARKETPLACE_FILE, CheckError, plugin_dirs, skill_dirs
from test_support import write


class PluginDirsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def marketplace(self, plugins: object) -> None:
        write(self.root / MARKETPLACE_FILE, json.dumps({"plugins": plugins}))

    def test_lists_plugin_directories_in_marketplace_order(self) -> None:
        (self.root / "plugins" / "b").mkdir(parents=True)
        (self.root / "plugins" / "a").mkdir(parents=True)
        self.marketplace([{"source": "./plugins/b"}, {"source": "./plugins/a"}])
        self.assertEqual(plugin_dirs(self.root),
                         [self.root / "plugins" / "b", self.root / "plugins" / "a"])

    def test_missing_marketplace_file(self) -> None:
        with self.assertRaisesRegex(CheckError, "cannot read"):
            plugin_dirs(self.root)

    def test_invalid_json(self) -> None:
        write(self.root / MARKETPLACE_FILE, "not json")
        with self.assertRaisesRegex(CheckError, "not valid JSON"):
            plugin_dirs(self.root)

    def test_plugins_must_be_an_array(self) -> None:
        for bad in (None, {}, "x"):
            with self.subTest(bad=bad):
                self.marketplace(bad)
                with self.assertRaisesRegex(CheckError, "no 'plugins' array"):
                    plugin_dirs(self.root)

    def test_only_relative_sources_are_supported(self) -> None:
        for bad in ([{"source": "plugins/a"}], [{"source": {"source": "github"}}], ["a"], [{}]):
            with self.subTest(bad=bad):
                self.marketplace(bad)
                with self.assertRaisesRegex(CheckError, "unsupported plugin source"):
                    plugin_dirs(self.root)

    def test_source_must_exist(self) -> None:
        self.marketplace([{"source": "./plugins/missing"}])
        with self.assertRaisesRegex(CheckError, "does not exist"):
            plugin_dirs(self.root)


class SkillDirsTests(unittest.TestCase):
    def test_only_directories_with_skill_md_sorted(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        write(root / "skills" / "b" / "SKILL.md")
        write(root / "skills" / "a" / "SKILL.md")
        write(root / "skills" / "no-skill-md" / "notes.md")
        write(root / "skills" / "loose.md")
        self.assertEqual(skill_dirs(root), [root / "skills" / "a", root / "skills" / "b"])

    def test_plugin_without_skills(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.assertEqual(skill_dirs(root), [])


if __name__ == "__main__":
    unittest.main()
