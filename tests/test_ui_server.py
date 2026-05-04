from __future__ import annotations

from helpers import (
    BasicProject,
    GenerateFramesCall,
    stub_generate_frames,
    write_existing_frame_state,
)
from vided import ui_server


def test_ensure_ui_frames_generates_missing_frames(
    basic_project: BasicProject, monkeypatch
) -> None:
    project = basic_project.root
    calls = stub_generate_frames(monkeypatch, ui_server, basic_project.paths.frames_json)

    assert ui_server.ensure_ui_frames(project) == basic_project.paths.frames_json
    assert calls == [
        GenerateFramesCall(
            project,
            {"interval_seconds": None, "thumbnail_width": None, "overwrite": False},
        )
    ]


def test_ensure_ui_frames_regenerates_when_metadata_is_missing(
    basic_project: BasicProject, monkeypatch
) -> None:
    project = basic_project.root
    write_existing_frame_state(project, with_metadata=False)
    calls = stub_generate_frames(monkeypatch, ui_server, basic_project.paths.frames_json)

    assert ui_server.ensure_ui_frames(project) == basic_project.paths.frames_json
    assert calls == [
        GenerateFramesCall(
            project,
            {"interval_seconds": None, "thumbnail_width": None, "overwrite": True},
        )
    ]


def test_ensure_ui_frames_skips_existing_frames(basic_project: BasicProject, monkeypatch) -> None:
    project = basic_project.root
    write_existing_frame_state(project)
    calls = stub_generate_frames(monkeypatch, ui_server, basic_project.paths.frames_json)

    assert ui_server.ensure_ui_frames(project) is None
    assert calls == []


def test_ensure_ui_frames_regenerates_when_requested(
    basic_project: BasicProject, monkeypatch
) -> None:
    project = basic_project.root
    write_existing_frame_state(project)
    calls = stub_generate_frames(monkeypatch, ui_server, basic_project.paths.frames_json)

    assert ui_server.ensure_ui_frames(project, regenerate=True) == basic_project.paths.frames_json
    assert calls == [
        GenerateFramesCall(
            project,
            {"interval_seconds": None, "thumbnail_width": None, "overwrite": True},
        )
    ]


def test_ensure_ui_frames_regenerates_when_frame_options_change(
    basic_project: BasicProject, monkeypatch
) -> None:
    project = basic_project.root
    write_existing_frame_state(project)
    calls = stub_generate_frames(monkeypatch, ui_server, basic_project.paths.frames_json)

    assert (
        ui_server.ensure_ui_frames(project, interval_seconds=0.5, thumbnail_width=960)
        == basic_project.paths.frames_json
    )
    assert calls == [
        GenerateFramesCall(
            project,
            {"interval_seconds": 0.5, "thumbnail_width": 960, "overwrite": True},
        )
    ]
