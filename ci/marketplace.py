"""Marketplace layout: which plugin and skill directories the repository ships."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

MARKETPLACE_FILE = Path(".claude-plugin") / "marketplace.json"


class CheckError(Exception):
    """A repository layout problem that makes the checks impossible to run."""


def plugin_dirs(repo: Path) -> List[Path]:
    """Plugin directories listed in the marketplace (relative-path sources only)."""
    path = repo / MARKETPLACE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CheckError(f"cannot read {path}: {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise CheckError(f"{path} is not valid JSON: {exc}") from exc
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, list):
        raise CheckError(f"{path} has no 'plugins' array")
    dirs = []
    for entry in plugins:
        source = entry.get("source") if isinstance(entry, dict) else None
        if not isinstance(source, str) or not source.startswith("./"):
            raise CheckError(f"unsupported plugin source in {path}: {source!r} "
                             "(only relative './…' paths are supported)")
        plugin_dir = repo / source[2:]
        if not plugin_dir.is_dir():
            raise CheckError(f"plugin source {source} does not exist")
        dirs.append(plugin_dir)
    return dirs


def skill_dirs(plugin_dir: Path) -> List[Path]:
    """Skill directories of a plugin: every `skills/<name>/` that holds a SKILL.md."""
    return sorted(skill_md.parent for skill_md in plugin_dir.glob("skills/*/SKILL.md"))
