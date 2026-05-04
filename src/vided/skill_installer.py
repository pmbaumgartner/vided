from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Literal

AgentName = Literal["codex", "claude"]


@dataclass(frozen=True)
class SkillInstallResult:
    path: Path
    wrote: bool
    dry_run: bool


def skill_destination(agent: AgentName) -> Path:
    match agent:
        case "codex":
            codex_home = os.environ.get("CODEX_HOME")
            base = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
        case "claude":
            base = Path.home() / ".claude"
        case _:
            raise ValueError("agent must be one of: codex, claude")
    return base / "skills" / "vided" / "SKILL.md"


def load_packaged_skill() -> str:
    return (
        resources.files("vided").joinpath("skills", "vided", "SKILL.md").read_text(encoding="utf-8")
    )


def install_skill(
    agent: AgentName,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
) -> SkillInstallResult:
    destination = skill_destination(agent)
    if destination.exists() and not overwrite:
        raise FileExistsError(
            f"Skill already exists: {destination}. Use --overwrite to replace it."
        )

    if dry_run:
        return SkillInstallResult(path=destination, wrote=False, dry_run=True)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(load_packaged_skill(), encoding="utf-8")
    return SkillInstallResult(path=destination, wrote=True, dry_run=False)
