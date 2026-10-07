"""Shared fixtures for the ci tests: a throwaway marketplace repo, real git, a fake `claude`."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

Handler = Callable[[Path], Tuple[int, str, str]]

GIT_IDENTITY = ["-c", "user.name=ci-tests", "-c", "user.email=ci-tests@example.invalid",
                "-c", "commit.gpgsign=false"]


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *GIT_IDENTITY, "-C", str(root), *args],
                            capture_output=True, text=True, check=True)
    return result.stdout


def write(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def entry(file: Path, kind: str = "skill", errors: Sequence[object] = (),
          warnings: Sequence[object] = ()) -> Dict[str, object]:
    return {"file": str(file), "type": kind, "errors": list(errors),
            "warnings": list(warnings), "notes": []}


def validator_output(target: Path, success: bool = True,
                     manifest: Optional[Dict[str, object]] = None,
                     contents: Sequence[Dict[str, object]] = ()) -> str:
    return json.dumps({"success": success, "strict": True, "target": str(target),
                       "manifest": manifest, "contents": list(contents)})


class FakeClaude:
    """Stands in for `claude`; `handler` maps the validated path to (exit code, stdout, stderr)."""

    def __init__(self, handler: Optional[Handler] = None) -> None:
        self.handler = handler or (lambda path: (0, validator_output(path), ""))
        self.validated: List[Path] = []

    def __call__(self, args: Sequence[str]) -> Tuple[int, str, str]:
        assert list(args[:2]) == ["plugin", "validate"] and args[3:] == ["--strict", "--json"], args
        path = Path(args[2])
        self.validated.append(path)
        return self.handler(path)


class MarketplaceTestCase(unittest.TestCase):
    """A git repo on `main` shipping plugin `alpha` with skills `one` and `two`."""

    PLUGIN = "alpha"
    SKILLS = ("one", "two")

    def setUp(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        self.root = Path(tempfile.mkdtemp()).resolve()  # resolved: the validator reports real paths
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.plugin = self.root / "plugins" / self.PLUGIN
        write(self.root / ".claude-plugin" / "marketplace.json", json.dumps(
            {"name": "m", "plugins": [{"name": self.PLUGIN, "source": f"./plugins/{self.PLUGIN}"}]}))
        write(self.plugin / ".claude-plugin" / "plugin.json", json.dumps({"name": self.PLUGIN}))
        for skill in self.SKILLS:
            write(self.skill(skill) / "SKILL.md", f"---\ndescription: {skill}\n---\n")
        write(self.root / ".gitignore", "__pycache__/\n")
        git(self.root, "init", "-b", "main")
        self.commit("initial")

    def skill(self, name: str) -> Path:
        return self.plugin / "skills" / name

    def commit(self, message: str) -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-m", message)
