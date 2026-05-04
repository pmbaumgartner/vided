from __future__ import annotations

from importlib import metadata
from pathlib import Path
import tomllib

PACKAGE_NAME = "vided"
UNKNOWN_VERSION = "0+unknown"


def _repo_pyproject() -> Path:
    return Path(__file__).resolve().parents[2] / "pyproject.toml"


def _version_from_pyproject(pyproject: Path) -> str | None:
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None

    project = data.get("project")
    if not isinstance(project, dict):
        return None
    if project.get("name") != PACKAGE_NAME:
        return None

    version = project.get("version")
    return version if isinstance(version, str) and version else None


def _version_from_metadata() -> str | None:
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return None


def get_version() -> str:
    return _version_from_pyproject(_repo_pyproject()) or _version_from_metadata() or UNKNOWN_VERSION
