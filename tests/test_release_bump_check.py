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


def quoted_list(values: list[str]) -> str:
    return "[" + ", ".join(f'"{value}"' for value in values) + "]"


def write_project(
    repo: Path,
    version: str,
    *,
    dependencies: list[str] | None = None,
    dev_dependencies: list[str] | None = None,
) -> None:
    if dependencies is None:
        dependencies = ["Pillow>=10.1"]
    if dev_dependencies is None:
        dev_dependencies = ["pytest>=8.0"]

    repo.joinpath("pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "vided"',
                f'version = "{version}"',
                f"dependencies = {quoted_list(dependencies)}",
                "",
                "[dependency-groups]",
                f"dev = {quoted_list(dev_dependencies)}",
                "",
                "[build-system]",
                'requires = ["hatchling"]',
                'build-backend = "hatchling.build"',
                "",
            ]
        ),
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
    git(repo, "branch", "-M", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test User")
    write_project(repo, "0.1.0")
    repo.joinpath("src/vided").mkdir(parents=True)
    repo.joinpath("src/vided/__init__.py").write_text("", encoding="utf-8")
    repo.joinpath("README.md").write_text("initial\n", encoding="utf-8")
    repo.joinpath("tests").mkdir()
    repo.joinpath("tests/test_placeholder.py").write_text("def test_placeholder():\n    pass\n")
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


def run_ci_check(
    repo: Path, base_ref: str, head_ref: str = "HEAD"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", str(SCRIPT), "--ci", "--base-ref", base_ref, "--head-ref", head_ref],
        cwd=repo,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_source_files_require_staged_zerover_bump(tmp_path: Path) -> None:
    init_repo(tmp_path)
    tmp_path.joinpath("src/vided/__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(tmp_path, "add", "src/vided/__init__.py")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "version was not bumped" in result.stderr
    assert "uv version --bump patch" in result.stderr


def test_feature_branch_skips_zerover_bump_check(tmp_path: Path) -> None:
    init_repo(tmp_path)
    git(tmp_path, "switch", "-c", "feature")
    tmp_path.joinpath("src/vided/__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(tmp_path, "add", "src/vided/__init__.py")

    result = run_check(tmp_path)

    assert result.returncode == 0, result.stderr


def test_source_files_pass_with_staged_lockstep_bump(tmp_path: Path) -> None:
    init_repo(tmp_path)
    tmp_path.joinpath("src/vided/__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    write_project(tmp_path, "0.1.1")
    git(tmp_path, "add", ".")

    result = run_check(tmp_path)

    assert result.returncode == 0, result.stderr


def test_tests_docs_and_workflows_do_not_require_bump(tmp_path: Path) -> None:
    init_repo(tmp_path)
    tmp_path.joinpath("README.md").write_text("changed\n", encoding="utf-8")
    tmp_path.joinpath("tests/test_placeholder.py").write_text(
        "def test_placeholder():\n    assert 1\n"
    )
    tmp_path.joinpath(".github/workflows").mkdir(parents=True)
    tmp_path.joinpath(".github/workflows/tests.yml").write_text("name: Tests\n")
    git(tmp_path, "add", ".")

    result = run_check(tmp_path)

    assert result.returncode == 0, result.stderr


def test_dev_dependency_changes_do_not_require_bump(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_project(tmp_path, "0.1.0", dev_dependencies=["pytest>=8.0", "ruff>=0.8"])
    git(tmp_path, "add", "pyproject.toml")

    result = run_check(tmp_path)

    assert result.returncode == 0, result.stderr


def test_ci_source_files_require_zerover_bump(tmp_path: Path) -> None:
    init_repo(tmp_path)
    base_ref = git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    git(tmp_path, "switch", "-c", "feature")
    tmp_path.joinpath("src/vided/__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(tmp_path, "add", "src/vided/__init__.py")
    assert git(tmp_path, "commit", "-m", "change source").returncode == 0

    result = run_ci_check(tmp_path, base_ref)

    assert result.returncode == 1
    assert "Base version: 0.1.0" in result.stderr
    assert "Head version: 0.1.0" in result.stderr
    assert "src/vided/__init__.py" in result.stderr


def test_ci_source_files_pass_with_lockstep_bump(tmp_path: Path) -> None:
    init_repo(tmp_path)
    base_ref = git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    git(tmp_path, "switch", "-c", "feature")
    tmp_path.joinpath("src/vided/__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    write_project(tmp_path, "0.1.1")
    git(tmp_path, "add", ".")
    assert git(tmp_path, "commit", "-m", "change source").returncode == 0

    result = run_ci_check(tmp_path, base_ref)

    assert result.returncode == 0, result.stderr


def test_ci_tests_docs_and_workflows_do_not_require_bump(tmp_path: Path) -> None:
    init_repo(tmp_path)
    base_ref = git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    git(tmp_path, "switch", "-c", "feature")
    tmp_path.joinpath("README.md").write_text("changed\n", encoding="utf-8")
    tmp_path.joinpath("tests/test_placeholder.py").write_text(
        "def test_placeholder():\n    assert 1\n"
    )
    git(tmp_path, "add", ".")
    assert git(tmp_path, "commit", "-m", "change docs and tests").returncode == 0

    result = run_ci_check(tmp_path, base_ref)

    assert result.returncode == 0, result.stderr


def test_project_dependency_changes_require_bump(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_project(tmp_path, "0.1.0", dependencies=["Pillow>=10.1", "requests>=2.0"])
    git(tmp_path, "add", "pyproject.toml")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "pyproject.toml" in result.stderr


def test_non_zerover_version_fails(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_project(tmp_path, "1.0.0")
    git(tmp_path, "add", "pyproject.toml", "uv.lock")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "0.MINOR.PATCH" in result.stderr
