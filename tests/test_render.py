from __future__ import annotations

from pathlib import Path
from typing import Any

from helpers import basic_project_at, filtergraph_from, patch_probe_media
from vided.errors import ValidationError
from vided.project import read_json, write_json
from vided.render import copy_trimmed_to_final, render_project
import vided.render as render


def test_copy_trimmed_to_final_writes_default_final_output(tmp_path) -> None:
    project = basic_project_at(tmp_path / "project").root
    trimmed = project / "work" / "trimmed.mp4"
    trimmed.write_bytes(b"trimmed video")

    output = copy_trimmed_to_final(project)

    assert output == project / "output" / "final.mp4"
    assert output.read_bytes() == b"trimmed video"


def test_copy_trimmed_to_final_respects_custom_output(tmp_path) -> None:
    project = basic_project_at(tmp_path / "project").root
    trimmed = project / "work" / "trimmed.mp4"
    trimmed.write_bytes(b"trimmed video")

    output = copy_trimmed_to_final(project, output=Path("output/auto-edited.mp4"))

    assert output == project / "output" / "auto-edited.mp4"
    assert output.read_bytes() == b"trimmed video"


def test_copy_trimmed_to_final_refuses_existing_output_without_overwrite(tmp_path) -> None:
    project = basic_project_at(tmp_path / "project").root
    trimmed = project / "work" / "trimmed.mp4"
    trimmed.write_bytes(b"trimmed video")
    output = project / "output" / "final.mp4"
    output.parent.mkdir()
    output.write_bytes(b"existing")

    try:
        copy_trimmed_to_final(project)
    except FileExistsError as exc:
        assert "Use --overwrite" in str(exc)
    else:
        raise AssertionError("existing final output should fail without overwrite")


def test_copy_trimmed_to_final_dry_run_does_not_require_trimmed_video(tmp_path) -> None:
    project = basic_project_at(tmp_path / "project").root

    output = copy_trimmed_to_final(project, dry_run=True)

    assert output == project / "output" / "final.mp4"
    assert not output.exists()


def test_render_without_redactions_copies_trimmed_without_ffmpeg(tmp_path, monkeypatch) -> None:
    project = basic_project_at(tmp_path / "project").root
    trimmed = project / "work" / "trimmed.mp4"
    trimmed.write_bytes(b"trimmed video")

    monkeypatch.setattr(render, "ensure_tool", lambda _: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(
        render, "run_command", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError)
    )

    output = render_project(project)

    assert output == project / "output" / "final.mp4"
    assert output.read_bytes() == b"trimmed video"


def test_render_auto_uses_trimmed_path_when_redactions_exist(tmp_path, monkeypatch) -> None:
    project = _project_with_redaction_and_timeline(tmp_path)
    (project / "work" / "trimmed.mp4").write_bytes(b"trimmed")
    calls = _capture_command(monkeypatch)

    render_project(project, dry_run=True)

    cmd = calls["cmd"]
    graph = filtergraph_from(cmd)
    assert str(project / "work" / "trimmed.mp4") in cmd
    assert str(project / "input" / "original.mp4") not in cmd
    assert "concat=n=2" not in graph


def test_render_one_pass_uses_original_when_trim_timeline_is_available(
    tmp_path, monkeypatch
) -> None:
    project = _project_with_redaction_and_timeline(tmp_path)
    calls = _capture_command(monkeypatch)

    render_project(project, render_mode="one-pass", dry_run=True)

    cmd = calls["cmd"]
    graph = filtergraph_from(cmd)
    assert str(project / "input" / "original.mp4") in cmd
    assert str(project / "work" / "trimmed.mp4") not in cmd
    assert "[0:v]trim=start=0:end=4" in graph
    assert "concat=n=2:v=1:a=1[trimv][trima]" in graph
    assert "[trimv]setpts=PTS-STARTPTS[base0]" in graph
    assert "[vout]" in cmd
    assert "[trima]" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "aac"


def test_render_trimmed_mode_bypasses_one_pass(tmp_path, monkeypatch) -> None:
    project = _project_with_redaction_and_timeline(tmp_path)
    (project / "work" / "trimmed.mp4").write_bytes(b"trimmed")
    calls = _capture_command(monkeypatch)

    render_project(project, render_mode="trimmed", dry_run=True)

    cmd = calls["cmd"]
    graph = filtergraph_from(cmd)
    assert str(project / "work" / "trimmed.mp4") in cmd
    assert str(project / "input" / "original.mp4") not in cmd
    assert "concat=n=2" not in graph


def test_render_one_pass_fails_without_trim_timeline(tmp_path) -> None:
    project = basic_project_at(tmp_path / "project").root
    write_json(
        project / "redactions.json",
        {
            "video": {"duration": 10.0, "width": 1920, "height": 1080},
            "redactions": [
                {
                    "start": 1.0,
                    "end": 2.0,
                    "rect": {"x": 10, "y": 20, "w": 100, "h": 80},
                }
            ],
        },
    )

    try:
        render_project(project, render_mode="one-pass", dry_run=True)
    except ValidationError as exc:
        assert "trim_timeline" in str(exc)
    else:
        raise AssertionError("one-pass render should require trim_timeline")


def _capture_command(monkeypatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}
    monkeypatch.setattr(render, "ensure_tool", lambda _: "ffmpeg")
    monkeypatch.setattr(render, "run_command", lambda cmd, dry_run=False: calls.update(cmd=cmd))
    patch_probe_media(monkeypatch, render)
    return calls


def _project_with_redaction_and_timeline(tmp_path: Path) -> Path:
    project = basic_project_at(tmp_path / "project").root
    cfg = read_json(project / "project.json")
    cfg["trim_timeline"] = {
        "schema_version": 1,
        "segments": [
            {
                "source_start": 0.0,
                "source_end": 4.0,
                "output_start": 0.0,
                "output_end": 4.0,
                "speed": 1.0,
                "mute_audio": False,
            },
            {
                "source_start": 5.0,
                "source_end": 13.0,
                "output_start": 4.0,
                "output_end": 5.0,
                "speed": 8.0,
                "mute_audio": True,
            },
        ],
    }
    write_json(project / "project.json", cfg)
    write_json(
        project / "redactions.json",
        {
            "video": {"duration": 5.0, "width": 1920, "height": 1080},
            "redactions": [
                {
                    "start": 1.0,
                    "end": 2.0,
                    "rect": {"x": 10, "y": 20, "w": 100, "h": 80},
                }
            ],
        },
    )
    return project
