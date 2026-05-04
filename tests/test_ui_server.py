from __future__ import annotations

from pathlib import Path

from helpers import write_basic_project
from vided import ui_server
from vided.project import project_paths, write_json


def test_ensure_ui_frames_generates_missing_frames(tmp_path, monkeypatch) -> None:
    project = write_basic_project(tmp_path / "project")
    frames_json = project_paths(project).frames_json
    calls: dict[str, object] = {}

    def fake_generate_frames(project_root: Path, **kwargs: object) -> Path:
        calls["project_root"] = project_root
        calls["kwargs"] = kwargs
        return frames_json

    monkeypatch.setattr(ui_server, "generate_frames", fake_generate_frames)

    assert ui_server.ensure_ui_frames(project) == frames_json
    assert calls == {
        "project_root": project,
        "kwargs": {"interval_seconds": None, "thumbnail_width": None, "overwrite": False},
    }


def test_ensure_ui_frames_regenerates_when_metadata_is_missing(tmp_path, monkeypatch) -> None:
    project = write_basic_project(tmp_path / "project")
    p = project_paths(project)
    p.frames_dir.mkdir(parents=True)
    (p.frames_dir / "frame_000001.jpg").write_bytes(b"jpg")
    calls: dict[str, object] = {}

    def fake_generate_frames(project_root: Path, **kwargs: object) -> Path:
        calls["project_root"] = project_root
        calls["kwargs"] = kwargs
        return p.frames_json

    monkeypatch.setattr(ui_server, "generate_frames", fake_generate_frames)

    assert ui_server.ensure_ui_frames(project) == p.frames_json
    assert calls == {
        "project_root": project,
        "kwargs": {"interval_seconds": None, "thumbnail_width": None, "overwrite": True},
    }


def test_ensure_ui_frames_skips_existing_frames(tmp_path, monkeypatch) -> None:
    project = write_basic_project(tmp_path / "project")
    p = project_paths(project)
    p.frames_dir.mkdir(parents=True)
    (p.frames_dir / "frame_000001.jpg").write_bytes(b"jpg")
    write_json(p.frames_json, {"frames": [{"image": "frames/frame_000001.jpg"}]})

    def fake_generate_frames(project_root: Path, **kwargs: object) -> Path:
        raise AssertionError("frames should already be ready")

    monkeypatch.setattr(ui_server, "generate_frames", fake_generate_frames)

    assert ui_server.ensure_ui_frames(project) is None


def test_ensure_ui_frames_regenerates_when_requested(tmp_path, monkeypatch) -> None:
    project = write_basic_project(tmp_path / "project")
    p = project_paths(project)
    p.frames_dir.mkdir(parents=True)
    (p.frames_dir / "frame_000001.jpg").write_bytes(b"jpg")
    write_json(p.frames_json, {"frames": [{"image": "frames/frame_000001.jpg"}]})
    calls: dict[str, object] = {}

    def fake_generate_frames(project_root: Path, **kwargs: object) -> Path:
        calls["project_root"] = project_root
        calls["kwargs"] = kwargs
        return p.frames_json

    monkeypatch.setattr(ui_server, "generate_frames", fake_generate_frames)

    assert ui_server.ensure_ui_frames(project, regenerate=True) == p.frames_json
    assert calls == {
        "project_root": project,
        "kwargs": {"interval_seconds": None, "thumbnail_width": None, "overwrite": True},
    }


def test_ensure_ui_frames_regenerates_when_frame_options_change(tmp_path, monkeypatch) -> None:
    project = write_basic_project(tmp_path / "project")
    p = project_paths(project)
    p.frames_dir.mkdir(parents=True)
    (p.frames_dir / "frame_000001.jpg").write_bytes(b"jpg")
    write_json(p.frames_json, {"frames": [{"image": "frames/frame_000001.jpg"}]})
    calls: dict[str, object] = {}

    def fake_generate_frames(project_root: Path, **kwargs: object) -> Path:
        calls["project_root"] = project_root
        calls["kwargs"] = kwargs
        return p.frames_json

    monkeypatch.setattr(ui_server, "generate_frames", fake_generate_frames)

    assert (
        ui_server.ensure_ui_frames(project, interval_seconds=0.5, thumbnail_width=960)
        == p.frames_json
    )
    assert calls == {
        "project_root": project,
        "kwargs": {"interval_seconds": 0.5, "thumbnail_width": 960, "overwrite": True},
    }
