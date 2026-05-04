from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from helpers import basic_project_at, patch_probe_media
import vided.audio_preview as audio_preview
from vided.project import read_json, write_json
from vided.trimmer import TrimSegment, build_trim_timeline


def _capture_audio_preview_command(monkeypatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    monkeypatch.setattr(audio_preview, "ensure_tool", lambda _: "ffmpeg")

    def fake_run_command(cmd: list[str], *, dry_run: bool = False):
        calls["cmd"] = cmd
        calls["dry_run"] = dry_run

    monkeypatch.setattr(audio_preview, "run_command", fake_run_command)
    return calls


def _project_with_trimmed_video(tmp_path: Path, monkeypatch, *, duration: float = 30.0):
    project = basic_project_at(tmp_path / "project").root
    (project / "work" / "trimmed.mp4").write_bytes(b"video")
    patch_probe_media(monkeypatch, audio_preview, duration=duration)
    return project


def _write_trim_timeline(project: Path, segments: list[TrimSegment]) -> None:
    cfg = read_json(project / "project.json")
    cfg["trim_timeline"] = build_trim_timeline(segments)
    write_json(project / "project.json", cfg)


def test_audio_preview_defaults_to_longest_normal_unmuted_segment_start(
    tmp_path, monkeypatch
) -> None:
    project = _project_with_trimmed_video(tmp_path, monkeypatch, duration=30.0)
    _write_trim_timeline(
        project,
        [
            TrimSegment(start=0.0, end=5.0),
            TrimSegment(start=5.0, end=13.0, speed=8.0, mute_audio=True),
            TrimSegment(start=13.0, end=33.0),
        ],
    )
    calls = _capture_audio_preview_command(monkeypatch)

    output = audio_preview.render_audio_preview(
        project,
        audio_preset="voice-safe",
        overwrite=True,
        dry_run=True,
    )

    cmd = calls["cmd"]
    assert output == project / "output" / "audio-preview-voice-safe-6s.mp4"
    assert cmd[cmd.index("-ss") + 1] == "6"
    assert cmd[cmd.index("-t") + 1] == "15"
    assert cmd[cmd.index("-af") + 1] == audio_preview.audio_filter_for_preset("voice-safe")


def test_audio_preview_caps_auto_duration_to_selected_segment(tmp_path, monkeypatch) -> None:
    project = _project_with_trimmed_video(tmp_path, monkeypatch, duration=30.0)
    _write_trim_timeline(project, [TrimSegment(start=0.0, end=6.0)])
    calls = _capture_audio_preview_command(monkeypatch)

    audio_preview.render_audio_preview(
        project,
        audio_preset="level",
        duration=20.0,
        dry_run=True,
    )

    cmd = calls["cmd"]
    assert cmd[cmd.index("-ss") + 1] == "0"
    assert cmd[cmd.index("-t") + 1] == "6"


def test_audio_preview_manual_start_defaults_to_fifteen_seconds(tmp_path, monkeypatch) -> None:
    project = _project_with_trimmed_video(tmp_path, monkeypatch, duration=30.0)
    calls = _capture_audio_preview_command(monkeypatch)

    audio_preview.render_audio_preview(
        project,
        audio_preset="level",
        start=2.5,
        dry_run=True,
    )

    cmd = calls["cmd"]
    assert cmd[cmd.index("-ss") + 1] == "2.5"
    assert cmd[cmd.index("-t") + 1] == "15"


def test_audio_preview_falls_back_when_no_normal_unmuted_segment(
    tmp_path, monkeypatch, capsys
) -> None:
    project = _project_with_trimmed_video(tmp_path, monkeypatch, duration=30.0)
    _write_trim_timeline(project, [TrimSegment(start=0.0, end=8.0, speed=8.0, mute_audio=True)])
    calls = _capture_audio_preview_command(monkeypatch)

    audio_preview.render_audio_preview(project, audio_preset="level", dry_run=True)

    cmd = calls["cmd"]
    assert cmd[cmd.index("-ss") + 1] == "0"
    assert cmd[cmd.index("-t") + 1] == "15"
    assert "no normal-speed audio segment found" in capsys.readouterr().err


def test_audio_preview_reconstructs_missing_timeline_from_trim_plan(tmp_path, monkeypatch) -> None:
    project = _project_with_trimmed_video(tmp_path, monkeypatch, duration=20.0)
    calls = _capture_audio_preview_command(monkeypatch)
    monkeypatch.setattr(
        audio_preview,
        "plan_trim",
        lambda *args, **kwargs: type(
            "Plan",
            (),
            {"segments": [TrimSegment(start=0.0, end=3.0), TrimSegment(start=10.0, end=18.0)]},
        )(),
    )

    audio_preview.render_audio_preview(project, audio_preset="level", dry_run=True)

    cmd = calls["cmd"]
    assert cmd[cmd.index("-ss") + 1] == "3"
    assert cmd[cmd.index("-t") + 1] == "8"


def test_audio_preview_rejects_invalid_manual_start(tmp_path, monkeypatch) -> None:
    project = _project_with_trimmed_video(tmp_path, monkeypatch, duration=10.0)

    with pytest.raises(ValueError, match="start must be before"):
        audio_preview.render_audio_preview(
            project,
            audio_preset="level",
            start=10.0,
            dry_run=True,
        )
