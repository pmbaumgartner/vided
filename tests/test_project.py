from __future__ import annotations

from helpers import video_info
from vided import project as project_module


def test_project_paths_uses_configured_original_extension(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.mov"
    source.write_bytes(b"video")
    project_root = tmp_path / "project"

    monkeypatch.setattr(
        project_module,
        "probe_media",
        lambda path: video_info(path, duration=3.0),
    )

    project_module.create_project(source, project_root)

    paths = project_module.project_paths(project_root)
    assert paths.original == project_root / "input" / "original.mov"
    assert paths.original.exists()


def test_read_json_default_can_be_none(tmp_path) -> None:
    assert project_module.read_json(tmp_path / "missing.json", default=None) is None
