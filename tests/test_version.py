from __future__ import annotations

from pathlib import Path

import vided
from vided import _version


def test_dunder_version_uses_dynamic_helper() -> None:
    assert vided.__version__ == _version.get_version()
    assert vided.__version__ != "0.1.7"


def test_version_from_pyproject_reads_matching_project(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "vided"
version = "1.2.3"
""".strip(),
        encoding="utf-8",
    )

    assert _version._version_from_pyproject(pyproject) == "1.2.3"


def test_version_from_pyproject_ignores_other_projects(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "other"
version = "1.2.3"
""".strip(),
        encoding="utf-8",
    )

    assert _version._version_from_pyproject(pyproject) is None


def test_get_version_falls_back_to_metadata(monkeypatch) -> None:
    monkeypatch.setattr(_version, "_version_from_pyproject", lambda pyproject: None)
    monkeypatch.setattr(_version, "_version_from_metadata", lambda: "2.0.0")

    assert _version.get_version() == "2.0.0"


def test_get_version_has_deterministic_unknown_fallback(monkeypatch) -> None:
    monkeypatch.setattr(_version, "_version_from_pyproject", lambda pyproject: None)
    monkeypatch.setattr(_version, "_version_from_metadata", lambda: None)

    assert _version.get_version() == "0+unknown"
