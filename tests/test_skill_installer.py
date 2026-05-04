from __future__ import annotations

from pathlib import Path

import pytest

from vided.skill_installer import (
    install_skill,
    load_packaged_skill,
    skill_destination,
)


def test_skill_destination_uses_agent_personal_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)

    assert skill_destination("codex") == home / ".codex" / "skills" / "vided" / "SKILL.md"
    assert skill_destination("claude") == home / ".claude" / "skills" / "vided" / "SKILL.md"


def test_codex_destination_respects_codex_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    assert skill_destination("codex") == codex_home / "skills" / "vided" / "SKILL.md"


def test_install_skill_writes_packaged_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))

    result = install_skill("codex")

    assert result.wrote is True
    assert result.dry_run is False
    assert result.path.read_text(encoding="utf-8") == load_packaged_skill()


def test_install_skill_refuses_existing_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    destination = skill_destination("claude")
    destination.parent.mkdir(parents=True)
    destination.write_text("existing\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Use --overwrite"):
        install_skill("claude")

    assert destination.read_text(encoding="utf-8") == "existing\n"


def test_install_skill_overwrites_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    destination = skill_destination("claude")
    destination.parent.mkdir(parents=True)
    destination.write_text("existing\n", encoding="utf-8")

    install_skill("claude", overwrite=True)

    assert destination.read_text(encoding="utf-8") == load_packaged_skill()


def test_install_skill_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))

    result = install_skill("codex", dry_run=True)

    assert result.wrote is False
    assert result.dry_run is True
    assert not result.path.exists()


def test_packaged_skill_has_required_metadata_and_uvx_guidance() -> None:
    content = load_packaged_skill()

    assert content.startswith("---\n")
    assert "\nname: vided\n" in content
    assert "\ndescription: " in content
    assert "uvx vided --help" in content
    assert "uvx vided init" in content
    assert "uvx vided trim" in content
    assert "uvx vided ui" in content
    assert "uvx vided render" in content
    assert 'uvx --from "vided[vad]" vided trim' in content
    assert "<command> --help" in content
