#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
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


def current_branch() -> str:
    return git_stdout(["branch", "--show-current"]).strip()


def merge_in_progress() -> bool:
    merge_head = git_stdout(["rev-parse", "--git-path", "MERGE_HEAD"]).strip()
    return Path(merge_head).exists()


def should_require_release_bump() -> bool:
    return current_branch() == "main" or merge_in_progress()


def changed_files_between(base_ref: str, head_ref: str) -> list[str]:
    output = git_stdout(["diff", "--name-only", "--diff-filter=ACDMRT", base_ref, head_ref])
    return [line for line in output.splitlines() if line]


def staged_files() -> list[str]:
    output = git_stdout(["diff", "--cached", "--name-only", "--diff-filter=ACDMRT"])
    return [line for line in output.splitlines() if line]


def index_file(path: str) -> str:
    result = git(["show", f":{path}"])
    if result.returncode != 0:
        raise CheckError(f"{path} must be present in the staged index.")
    return result.stdout


def ref_file(ref: str, path: str) -> str | None:
    result = git(["show", f"{ref}:{path}"])
    if result.returncode != 0:
        return None
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


def version_changed(current_pyproject: str, previous_pyproject: str | None) -> bool:
    if previous_pyproject is None:
        return True
    _, current_version = project_name_and_version(current_pyproject)
    _, previous_version = project_name_and_version(previous_pyproject)
    return current_version != previous_version


def pyproject_release_surface_changed(
    current_pyproject: str, previous_pyproject: str | None
) -> bool:
    if previous_pyproject is None:
        return True
    return release_surface(current_pyproject) != release_surface(previous_pyproject)


def release_relevant_files(
    files: list[str], current_pyproject: str, previous_pyproject: str | None
) -> list[str]:
    relevant_files = [
        path
        for path in files
        if path.startswith(PACKAGE_SOURCE_PREFIX)
        or (
            path == PROJECT_FILE
            and pyproject_release_surface_changed(current_pyproject, previous_pyproject)
        )
    ]

    if PROJECT_FILE in files and version_changed(current_pyproject, previous_pyproject):
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


def require_release_bump_for_files(
    *,
    files: list[str],
    current_pyproject: str,
    previous_pyproject: str | None,
    current_lock: str,
    previous_version_label: str,
    current_version_label: str,
    files_label: str,
) -> None:
    files_requiring_bump = release_relevant_files(files, current_pyproject, previous_pyproject)
    if not files_requiring_bump:
        return

    project_name, current_version_text = project_name_and_version(current_pyproject)
    current_version = ZeroVersion.parse(current_version_text)

    previous_version_text = None
    if previous_pyproject is not None:
        _, previous_version_text = project_name_and_version(previous_pyproject)
        previous_version = ZeroVersion.parse(previous_version_text)
        if current_version <= previous_version:
            raise CheckError(
                "Release-relevant files changed, but the package version was not bumped.\n\n"
                f"{previous_version_label}: {previous_version_text}\n"
                f"{current_version_label}: {current_version_text}\n\n"
                f"{files_label}:\n"
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

    current_lock_version = lock_version(current_lock, project_name)
    if current_lock_version != current_version_text:
        raise CheckError(
            f"{LOCK_FILE} version for {project_name!r} is {current_lock_version!r}, "
            f"but {PROJECT_FILE} has {current_version_text!r}.\n\n"
            "Run `uv version --bump patch` or `uv version --bump minor`, then stage both files:\n"
            "  git add pyproject.toml uv.lock"
        )

    tag_name = f"v{current_version_text}"
    if tag_exists(tag_name):
        previous = f" Previous version: {previous_version_text}." if previous_version_text else ""
        raise CheckError(
            f"Tag {tag_name!r} already exists.{previous}\n"
            "Bump to a new 0.MINOR.PATCH version before committing these changes."
        )


def require_release_bump() -> None:
    require_release_bump_for_files(
        files=staged_files(),
        current_pyproject=index_file(PROJECT_FILE),
        previous_pyproject=head_file(PROJECT_FILE),
        current_lock=index_file(LOCK_FILE),
        previous_version_label="Current version",
        current_version_label="Staged version",
        files_label="Release-relevant staged files",
    )


def require_release_bump_between(base_ref: str, head_ref: str) -> None:
    head_pyproject = ref_file(head_ref, PROJECT_FILE)
    if head_pyproject is None:
        raise CheckError(f"{PROJECT_FILE} must be present at {head_ref!r}.")

    head_lock = ref_file(head_ref, LOCK_FILE)
    if head_lock is None:
        raise CheckError(f"{LOCK_FILE} must be present at {head_ref!r}.")

    require_release_bump_for_files(
        files=changed_files_between(base_ref, head_ref),
        current_pyproject=head_pyproject,
        previous_pyproject=ref_file(base_ref, PROJECT_FILE),
        current_lock=head_lock,
        previous_version_label="Base version",
        current_version_label="Head version",
        files_label="Release-relevant changed files",
    )


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Require package version bumps for release changes.")
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Compare two refs instead of checking the staged index.",
    )
    parser.add_argument("--base-ref", help="Base Git ref for --ci mode.")
    parser.add_argument("--head-ref", default="HEAD", help="Head Git ref for --ci mode.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.ci:
            if args.base_ref is None:
                raise CheckError("--base-ref is required with --ci.")
            require_release_bump_between(args.base_ref, args.head_ref)
        elif should_require_release_bump():
            require_release_bump()
    except CheckError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
