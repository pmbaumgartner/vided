#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from typing import Any

PROJECT_FILE = "pyproject.toml"
LOCK_FILE = "uv.lock"
ZERO_VERSION_RE = re.compile(r"^0\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
PACKAGE_SOURCE_PREFIX = "src/"
PROJECT_RELEASE_KEYS = {
    "authors",
    "classifiers",
    "dependencies",
    "description",
    "dynamic",
    "entry-points",
    "gui-scripts",
    "keywords",
    "license",
    "license-files",
    "maintainers",
    "name",
    "optional-dependencies",
    "readme",
    "requires-python",
    "scripts",
    "urls",
}


class CheckError(Exception):
    pass


@dataclass(frozen=True, order=True)
class ZeroVersion:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, version: str) -> ZeroVersion:
        match = ZERO_VERSION_RE.fullmatch(version)
        if match is None:
            raise CheckError(
                f"{PROJECT_FILE} version must use zerover in 0.MINOR.PATCH form; got {version!r}."
            )
        return cls(0, int(match.group(1)), int(match.group(2)))


def git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def git_stdout(args: list[str]) -> str:
    result = git(args)
    if result.returncode != 0:
        raise CheckError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def staged_files() -> list[str]:
    output = git_stdout(["diff", "--cached", "--name-only", "--diff-filter=ACDMRT"])
    return [line for line in output.splitlines() if line]


def index_file(path: str) -> str:
    result = git(["show", f":{path}"])
    if result.returncode != 0:
        raise CheckError(f"{path} must be present in the staged index.")
    return result.stdout


def head_file(path: str) -> str | None:
    result = git(["show", f"HEAD:{path}"])
    if result.returncode != 0:
        return None
    return result.stdout


def project_name_and_version(pyproject_text: str) -> tuple[str, str]:
    try:
        project = tomllib.loads(pyproject_text)["project"]
        return str(project["name"]), str(project["version"])
    except (KeyError, tomllib.TOMLDecodeError) as error:
        raise CheckError(f"Could not read [project].name and [project].version: {error}") from error


def pyproject(pyproject_text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(pyproject_text)
    except tomllib.TOMLDecodeError as error:
        raise CheckError(f"Could not read {PROJECT_FILE}: {error}") from error


def release_surface(pyproject_text: str) -> dict[str, Any]:
    data = pyproject(pyproject_text)
    project = data.get("project", {})
    tool = data.get("tool", {})
    return {
        "build-system": data.get("build-system"),
        "project": {key: project.get(key) for key in PROJECT_RELEASE_KEYS if key in project},
        "tool": {"hatch": tool.get("hatch")},
    }


def version_changed(staged_pyproject: str, head_pyproject: str | None) -> bool:
    if head_pyproject is None:
        return True
    _, staged_version = project_name_and_version(staged_pyproject)
    _, head_version = project_name_and_version(head_pyproject)
    return staged_version != head_version


def pyproject_release_surface_changed() -> bool:
    staged_pyproject = index_file(PROJECT_FILE)
    head_pyproject = head_file(PROJECT_FILE)
    if head_pyproject is None:
        return True
    return release_surface(staged_pyproject) != release_surface(head_pyproject)


def release_relevant_files(files: list[str]) -> list[str]:
    relevant_files = [
        path
        for path in files
        if path.startswith(PACKAGE_SOURCE_PREFIX)
        or (path == PROJECT_FILE and pyproject_release_surface_changed())
    ]

    if PROJECT_FILE in files:
        staged_pyproject = index_file(PROJECT_FILE)
        if version_changed(staged_pyproject, head_file(PROJECT_FILE)):
            relevant_files.append(PROJECT_FILE)

    return sorted(set(relevant_files))


def lock_version(lock_text: str, project_name: str) -> str | None:
    try:
        lock = tomllib.loads(lock_text)
    except tomllib.TOMLDecodeError as error:
        raise CheckError(f"Could not read {LOCK_FILE}: {error}") from error

    matching_packages = [pkg for pkg in lock.get("package", []) if pkg.get("name") == project_name]
    for package in matching_packages:
        if package.get("source") == {"editable": "."}:
            return str(package.get("version"))
    if matching_packages:
        return str(matching_packages[0].get("version"))
    return None


def tag_exists(tag_name: str) -> bool:
    result = git(["rev-parse", "--quiet", "--verify", f"refs/tags/{tag_name}"])
    return result.returncode == 0


def format_staged_files(files: list[str]) -> str:
    shown_files = files[:12]
    lines = [f"  - {path}" for path in shown_files]
    if len(files) > len(shown_files):
        lines.append(f"  - ... and {len(files) - len(shown_files)} more")
    return "\n".join(lines)


def require_release_bump() -> None:
    files = staged_files()
    files_requiring_bump = release_relevant_files(files)
    if not files_requiring_bump:
        return

    project_name, staged_version_text = project_name_and_version(index_file(PROJECT_FILE))
    staged_version = ZeroVersion.parse(staged_version_text)

    head_pyproject = head_file(PROJECT_FILE)
    head_version_text = None
    if head_pyproject is not None:
        _, head_version_text = project_name_and_version(head_pyproject)
        head_version = ZeroVersion.parse(head_version_text)
        if staged_version <= head_version:
            raise CheckError(
                "Release-relevant staged files changed, but the package version was not bumped.\n\n"
                f"Current version: {head_version_text}\n"
                f"Staged version: {staged_version_text}\n\n"
                "Release-relevant staged files:\n"
                f"{format_staged_files(files_requiring_bump)}\n\n"
                "Use zerover for package source or release metadata changes:\n"
                "  uv version --bump patch\n"
                "  # or, for larger changes while still staying on major zero:\n"
                "  uv version --bump minor\n"
                "  git add pyproject.toml uv.lock\n\n"
                "After the commit succeeds, add the matching release tag:\n"
                "  git tag -a v<new-version> -m v<new-version>\n"
                "  git push origin HEAD --tags"
            )

    staged_lock_version = lock_version(index_file(LOCK_FILE), project_name)
    if staged_lock_version != staged_version_text:
        raise CheckError(
            f"{LOCK_FILE} version for {project_name!r} is {staged_lock_version!r}, "
            f"but {PROJECT_FILE} has {staged_version_text!r}.\n\n"
            "Run `uv version --bump patch` or `uv version --bump minor`, then stage both files:\n"
            "  git add pyproject.toml uv.lock"
        )

    tag_name = f"v{staged_version_text}"
    if tag_exists(tag_name):
        previous = f" Previous version: {head_version_text}." if head_version_text else ""
        raise CheckError(
            f"Tag {tag_name!r} already exists.{previous}\n"
            "Bump to a new 0.MINOR.PATCH version before committing these changes."
        )


def main() -> int:
    try:
        require_release_bump()
    except CheckError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
