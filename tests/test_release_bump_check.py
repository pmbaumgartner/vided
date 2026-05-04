from __future__ import annotations

from dataclasses import dataclass
import subprocess
from pathlib import Path

import pytest

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


@dataclass(frozen=True)
class ReleaseRepo:
    root: Path

    def initialize(self) -> None:
        self.git("init", "-q")
        self.git("branch", "-M", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test User")
        write_project(self.root, "0.1.0")
        self.root.joinpath("src/vided").mkdir(parents=True)
        self.root.joinpath("src/vided/__init__.py").write_text("", encoding="utf-8")
        self.root.joinpath("README.md").write_text("initial\n", encoding="utf-8")
        self.root.joinpath("tests").mkdir()
        self.root.joinpath("tests/test_placeholder.py").write_text(
            "def test_placeholder():\n    pass\n"
        )
        self.add(".")
        self.commit("initial")

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return git(self.root, *args)

    def branch(self, name: str = "feature") -> None:
        self.git("switch", "-c", name)

    def base_ref(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()

    def change_source(self, content: str = "VALUE = 1\n") -> None:
        self.root.joinpath("src/vided/__init__.py").write_text(content, encoding="utf-8")

    def change_docs_and_tests(self) -> None:
        self.root.joinpath("README.md").write_text("changed\n", encoding="utf-8")
        self.root.joinpath("tests/test_placeholder.py").write_text(
            "def test_placeholder():\n    assert 1\n",
            encoding="utf-8",
        )

    def bump(
        self,
        version: str = "0.1.1",
        *,
        dependencies: list[str] | None = None,
        dev_dependencies: list[str] | None = None,
    ) -> None:
        write_project(
            self.root,
            version,
            dependencies=dependencies,
            dev_dependencies=dev_dependencies,
        )

    def add(self, *paths: str) -> None:
        self.git("add", *(paths or (".",)))

    def commit(self, message: str = "change") -> None:
        assert self.git("commit", "-m", message).returncode == 0

    def tag(self, version: str = "0.1.1") -> None:
        assert self.git("tag", "-a", f"v{version}", "-m", f"v{version}").returncode == 0

    def run_check(self) -> subprocess.CompletedProcess[str]:
        return run_check(self.root)

    def run_ci_check(
        self, base_ref: str, head_ref: str = "HEAD"
    ) -> subprocess.CompletedProcess[str]:
        return run_ci_check(self.root, base_ref, head_ref=head_ref)


@pytest.fixture
def release_repo(tmp_path: Path) -> ReleaseRepo:
    repo = ReleaseRepo(tmp_path)
    repo.initialize()
    return repo


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


def test_source_files_require_staged_zerover_bump(release_repo: ReleaseRepo) -> None:
    release_repo.change_source()
    release_repo.add("src/vided/__init__.py")

    result = release_repo.run_check()

    assert result.returncode == 1
    assert "version was not bumped" in result.stderr
    assert "uv version --bump patch" in result.stderr


def test_feature_branch_skips_zerover_bump_check(release_repo: ReleaseRepo) -> None:
    release_repo.branch()
    release_repo.change_source()
    release_repo.add("src/vided/__init__.py")

    result = release_repo.run_check()

    assert result.returncode == 0, result.stderr


def test_source_files_pass_with_staged_lockstep_bump(release_repo: ReleaseRepo) -> None:
    release_repo.change_source()
    release_repo.bump()
    release_repo.add(".")

    result = release_repo.run_check()

    assert result.returncode == 0, result.stderr


def test_tests_docs_and_workflows_do_not_require_bump(release_repo: ReleaseRepo) -> None:
    release_repo.change_docs_and_tests()
    release_repo.root.joinpath(".github/workflows").mkdir(parents=True)
    release_repo.root.joinpath(".github/workflows/tests.yml").write_text("name: Tests\n")
    release_repo.add(".")

    result = release_repo.run_check()

    assert result.returncode == 0, result.stderr


def test_dev_dependency_changes_do_not_require_bump(release_repo: ReleaseRepo) -> None:
    release_repo.bump("0.1.0", dev_dependencies=["pytest>=8.0", "ruff>=0.8"])
    release_repo.add("pyproject.toml")

    result = release_repo.run_check()

    assert result.returncode == 0, result.stderr


def test_ci_source_files_require_zerover_bump(release_repo: ReleaseRepo) -> None:
    base_ref = release_repo.base_ref()
    release_repo.branch()
    release_repo.change_source()
    release_repo.add("src/vided/__init__.py")
    release_repo.commit("change source")

    result = release_repo.run_ci_check(base_ref)

    assert result.returncode == 1
    assert "Base version: 0.1.0" in result.stderr
    assert "Head version: 0.1.0" in result.stderr
    assert "src/vided/__init__.py" in result.stderr


def test_ci_source_files_pass_with_lockstep_bump(release_repo: ReleaseRepo) -> None:
    base_ref = release_repo.base_ref()
    release_repo.branch()
    release_repo.change_source()
    release_repo.bump()
    release_repo.add(".")
    release_repo.commit("change source")

    result = release_repo.run_ci_check(base_ref)

    assert result.returncode == 0, result.stderr


def test_ci_source_files_pass_when_matching_tag_points_at_head(
    release_repo: ReleaseRepo,
) -> None:
    base_ref = release_repo.base_ref()
    release_repo.branch()
    release_repo.change_source()
    release_repo.bump()
    release_repo.add(".")
    release_repo.commit("change source")
    release_repo.tag()

    result = release_repo.run_ci_check(base_ref)

    assert result.returncode == 0, result.stderr


def test_ci_source_files_reject_existing_tag_on_different_commit(
    release_repo: ReleaseRepo,
) -> None:
    base_ref = release_repo.base_ref()
    release_repo.tag()
    release_repo.branch()
    release_repo.change_source()
    release_repo.bump()
    release_repo.add(".")
    release_repo.commit("change source")

    result = release_repo.run_ci_check(base_ref)

    assert result.returncode == 1
    assert "Tag 'v0.1.1' already exists" in result.stderr


def test_ci_tests_docs_and_workflows_do_not_require_bump(
    release_repo: ReleaseRepo,
) -> None:
    base_ref = release_repo.base_ref()
    release_repo.branch()
    release_repo.change_docs_and_tests()
    release_repo.add(".")
    release_repo.commit("change docs and tests")

    result = release_repo.run_ci_check(base_ref)

    assert result.returncode == 0, result.stderr


def test_project_dependency_changes_require_bump(release_repo: ReleaseRepo) -> None:
    release_repo.bump("0.1.0", dependencies=["Pillow>=10.1", "requests>=2.0"])
    release_repo.add("pyproject.toml")

    result = release_repo.run_check()

    assert result.returncode == 1
    assert "pyproject.toml" in result.stderr


def test_non_zerover_version_fails(release_repo: ReleaseRepo) -> None:
    release_repo.bump("1.0.0")
    release_repo.add("pyproject.toml", "uv.lock")

    result = release_repo.run_check()

    assert result.returncode == 1
    assert "0.MINOR.PATCH" in result.stderr
