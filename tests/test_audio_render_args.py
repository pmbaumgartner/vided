from __future__ import annotations

from pathlib import Path
from typing import Any

from helpers import basic_project_at, filtergraph_from, patch_probe_media
from vided.audio_presets import audio_filter_for_preset
from vided.project import write_json
import vided.render as render


def _capture_render_command(monkeypatch, *, has_audio: bool = True) -> dict[str, Any]:
    calls: dict[str, Any] = {}
    monkeypatch.setattr(render, "ensure_tool", lambda _: "ffmpeg")
    monkeypatch.setattr(render, "run_command", lambda cmd, dry_run=False: calls.update(cmd=cmd))
    patch_probe_media(monkeypatch, render, has_audio=has_audio)
    return calls


def _project_with_trimmed_video(tmp_path: Path) -> Path:
    project = basic_project_at(tmp_path / "project").root
    (project / "work" / "trimmed.mp4").write_bytes(b"video")
    return project


def test_render_audio_preset_none_uses_copy_fast_path(tmp_path, monkeypatch) -> None:
    project = _project_with_trimmed_video(tmp_path)
    calls = _capture_render_command(monkeypatch)

    render.render_project(project, audio_preset="none", dry_run=True)

    assert calls == {}


def test_render_audio_preset_filters_audio_and_copies_video_without_redactions(
    tmp_path, monkeypatch
) -> None:
    project = _project_with_trimmed_video(tmp_path)
    calls = _capture_render_command(monkeypatch)

    render.render_project(project, audio_preset="level", dry_run=True)

    cmd = calls["cmd"]
    assert "-filter_complex" not in cmd
    assert cmd[cmd.index("-map") + 1] == "0:v:0"
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd[cmd.index("-af") + 1] == audio_filter_for_preset("level")
    assert cmd[cmd.index("-c:a") + 1] == "aac"


def test_render_audio_preset_combines_audio_and_redaction_filtergraphs(
    tmp_path, monkeypatch
) -> None:
    project = _project_with_trimmed_video(tmp_path)
    write_json(
        project / "redactions.json",
        {
            "video": {"duration": 10.0, "width": 1920, "height": 1080},
            "redactions": [
                {
                    "start": 1.0,
                    "end": 2.0,
                    "rect": {"x": 10, "y": 20, "w": 100, "h": 80},
                    "style": {"type": "solid", "color": "black"},
                }
            ],
        },
    )
    calls = _capture_render_command(monkeypatch)

    render.render_project(project, audio_preset="voice-safe", dry_run=True)

    cmd = calls["cmd"]
    graph = filtergraph_from(cmd)
    assert "drawbox" in graph
    assert f"[0:a]{audio_filter_for_preset('voice-safe')}[aout]" in graph
    assert "[aout]" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "aac"


def test_render_audio_preset_warns_and_renders_video_only_without_audio(
    tmp_path, monkeypatch, capsys
) -> None:
    project = _project_with_trimmed_video(tmp_path)
    calls = _capture_render_command(monkeypatch, has_audio=False)

    render.render_project(project, audio_preset="level", dry_run=True)

    cmd = calls["cmd"]
    assert "-c:a" not in cmd
    assert "audio preset requested but trimmed video has no audio stream" in capsys.readouterr().err
