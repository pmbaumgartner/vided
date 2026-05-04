from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_release_bump.py"


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def write_project(repo: Path, version: str) -> None:
    repo.joinpath("pyproject.toml").write_text(
        f'[project]\nname = "vided"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    repo.joinpath("uv.lock").write_text(
        "\n".join(
            [
                "version = 1",
                "revision = 3",
                'requires-python = ">=3.11"',
                "",
                "[[package]]",
                'name = "vided"',
                f'version = "{version}"',
                'source = { editable = "." }',
                "",
            ]
        ),
        encoding="utf-8",
    )


def init_repo(repo: Path) -> None:
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test User")
    write_project(repo, "0.1.0")
    repo.joinpath("README.md").write_text("initial\n", encoding="utf-8")
    git(repo, "add", ".")
    assert git(repo, "commit", "-m", "initial").returncode == 0


def run_check(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", str(SCRIPT)],
        cwd=repo,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_changed_files_require_staged_zerover_bump(tmp_path: Path) -> None:
    init_repo(tmp_path)
    tmp_path.joinpath("README.md").write_text("changed\n", encoding="utf-8")
    git(tmp_path, "add", "README.md")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "version was not bumped" in result.stderr
    assert "uv version --bump patch" in result.stderr


def test_changed_files_pass_with_staged_lockstep_bump(tmp_path: Path) -> None:
    init_repo(tmp_path)
    tmp_path.joinpath("README.md").write_text("changed\n", encoding="utf-8")
    write_project(tmp_path, "0.1.1")
    git(tmp_path, "add", ".")

    result = run_check(tmp_path)

    assert result.returncode == 0, result.stderr


def test_non_zerover_version_fails(tmp_path: Path) -> None:
    init_repo(tmp_path)
    tmp_path.joinpath("README.md").write_text("changed\n", encoding="utf-8")
    write_project(tmp_path, "1.0.0")
    git(tmp_path, "add", ".")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "0.MINOR.PATCH" in result.stderr
