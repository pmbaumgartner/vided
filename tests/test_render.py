from __future__ import annotations

from pathlib import Path
from typing import Any

from helpers import basic_project_at, filtergraph_from, patch_probe_media
from vided.compression import CompressionCandidate, CompressionDecision
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

    result = render_project(project)

    assert result.path == project / "output" / "final.mp4"
    assert result.command is None
    assert result.wrote_files is True
    assert result.path.read_bytes() == b"trimmed video"


def test_render_auto_uses_trimmed_path_when_redactions_exist(tmp_path, monkeypatch) -> None:
    project = _project_with_redaction_and_timeline(tmp_path)
    (project / "work" / "trimmed.mp4").write_bytes(b"trimmed")
    calls = _capture_command(monkeypatch)

    result = render_project(project, dry_run=True)

    cmd = result.command
    assert cmd == calls["cmd"]
    assert cmd is not None
    graph = filtergraph_from(cmd)
    assert str(project / "work" / "trimmed.mp4") in cmd
    assert str(project / "input" / "original.mp4") not in cmd
    assert "concat=n=2" not in graph


def test_render_original_source_uses_original_when_trim_timeline_is_available(
    tmp_path, monkeypatch
) -> None:
    project = _project_with_redaction_and_timeline(tmp_path)
    calls = _capture_command(monkeypatch)

    result = render_project(project, render_source="original", dry_run=True)

    cmd = result.command
    assert cmd == calls["cmd"]
    assert cmd is not None
    graph = filtergraph_from(cmd)
    assert str(project / "input" / "original.mp4") in cmd
    assert str(project / "work" / "trimmed.mp4") not in cmd
    assert "[0:v]trim=start=0:end=4" in graph
    assert "[0:v]trim=start=5:end=13,setpts=(PTS-STARTPTS)/8[v1]" in graph
    assert (
        "[0:a]atrim=start=5:end=13,asetpts=PTS-STARTPTS,atempo=2,atempo=2,atempo=2,volume=0[a1]"
        in graph
    )
    assert "concat=n=2:v=1:a=1[trimv][trima]" in graph
    assert "[trimv]setpts=PTS-STARTPTS[base0]" in graph
    assert "[vout]" in cmd
    assert "[trima]" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "aac"


def test_render_original_source_works_without_redactions(tmp_path, monkeypatch) -> None:
    project = basic_project_at(tmp_path / "project").root
    cfg = read_json(project / "project.json")
    cfg["trim_timeline"] = {
        "schema_version": 1,
        "segments": [
            {
                "source_start": 0.0,
                "source_end": 10.0,
                "output_start": 0.0,
                "output_end": 10.0,
                "speed": 1.0,
                "mute_audio": False,
            }
        ],
    }
    write_json(project / "project.json", cfg)
    calls = _capture_command(monkeypatch)

    result = render_project(project, render_source="original", dry_run=True)

    cmd = result.command
    assert cmd == calls["cmd"]
    assert cmd is not None
    graph = filtergraph_from(cmd)
    assert str(project / "input" / "original.mp4") in cmd
    assert str(project / "work" / "trimmed.mp4") not in cmd
    assert "concat=n=1:v=1:a=1[trimv][trima]" in graph
    assert "[trimv]setpts=PTS-STARTPTS[vout]" in graph


def test_render_trimmed_source_bypasses_original_source(tmp_path, monkeypatch) -> None:
    project = _project_with_redaction_and_timeline(tmp_path)
    (project / "work" / "trimmed.mp4").write_bytes(b"trimmed")
    calls = _capture_command(monkeypatch)

    result = render_project(project, render_source="trimmed", dry_run=True)

    cmd = result.command
    assert cmd == calls["cmd"]
    assert cmd is not None
    graph = filtergraph_from(cmd)
    assert str(project / "work" / "trimmed.mp4") in cmd
    assert str(project / "input" / "original.mp4") not in cmd
    assert "concat=n=2" not in graph


def test_render_original_source_fails_without_trim_timeline(tmp_path) -> None:
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
        render_project(project, render_source="original", dry_run=True)
    except ValidationError as exc:
        assert "trim_timeline" in str(exc)
    else:
        raise AssertionError("original-source render should require trim_timeline")


def test_render_original_source_rejects_invalid_trim_timeline(tmp_path) -> None:
    project = basic_project_at(tmp_path / "project").root
    cfg = read_json(project / "project.json")
    cfg["trim_timeline"] = {
        "schema_version": 1,
        "segments": [
            {
                "source_start": 0.0,
                "source_end": 10.0,
                "output_start": 0.0,
                "output_end": 99.0,
                "speed": 1.0,
                "mute_audio": False,
            }
        ],
    }
    write_json(project / "project.json", cfg)

    try:
        render_project(project, render_source="original", dry_run=True)
    except ValidationError as exc:
        assert "trim_timeline is invalid" in str(exc)
        assert "output duration" in str(exc)
    else:
        raise AssertionError("original-source render should reject invalid trim_timeline")


def test_render_smart_compression_caps_high_fps(tmp_path, monkeypatch) -> None:
    project = basic_project_at(tmp_path / "project").root
    (project / "work" / "trimmed.mp4").write_bytes(b"trimmed")
    calls = _capture_command(monkeypatch, fps=60.0, audio_bit_rate=128_000)

    result = render_project(project, compress="smart", dry_run=True)

    cmd = result.command
    assert cmd == calls["cmd"]
    assert cmd is not None
    graph = filtergraph_from(cmd)
    assert result.compression is not None
    assert result.compression.candidate.name == "smart-h264-balanced"
    assert "fps=fps=30[voutfps]" in graph
    assert "[voutfps]" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-crf") + 1] == "23"
    assert cmd[cmd.index("-b:a") + 1] == "96k"


def test_render_smart_compression_leaves_30fps_source_alone(tmp_path, monkeypatch) -> None:
    project = basic_project_at(tmp_path / "project").root
    (project / "work" / "trimmed.mp4").write_bytes(b"trimmed")
    calls = _capture_command(monkeypatch, fps=30.0)

    result = render_project(project, compress="smart", dry_run=True)

    assert result.command == calls["cmd"]
    assert result.command is not None
    graph = filtergraph_from(result.command)
    assert "fps=fps" not in graph


def test_render_sample_writes_sample_path_and_estimate(tmp_path, monkeypatch) -> None:
    project = basic_project_at(tmp_path / "project").root
    (project / "work" / "trimmed.mp4").write_bytes(b"trimmed")
    calls = _capture_command(monkeypatch)

    result = render_project(
        project,
        sample_duration=12.5,
        dry_run=True,
    )

    cmd = result.command
    assert cmd == calls["cmd"]
    assert cmd is not None
    assert result.path == project / "output" / "final-sample-current.mp4"
    assert result.sample is not None
    assert result.sample.sample_duration == 12.5
    assert result.sample.full_duration == 10.0
    assert result.sample.sample_size_bytes is None
    assert cmd[cmd.index("-t") + 1] == "12.5"
    assert str(result.path) in cmd


def test_render_smart_compression_refuses_larger_output(tmp_path, monkeypatch) -> None:
    project = basic_project_at(tmp_path / "project").root
    trimmed = project / "work" / "trimmed.mp4"
    trimmed.write_bytes(b"x" * 10)
    output = project / "output" / "final.mp4"
    monkeypatch.setattr(render, "ensure_tool", lambda _: "ffmpeg")
    patch_probe_media(monkeypatch, render)
    monkeypatch.setattr(
        render,
        "choose_smart_compression",
        lambda *args, **kwargs: CompressionDecision(
            mode="smart",
            priority="compatibility",
            candidate=CompressionCandidate(
                name="smart-h264-balanced",
                description="H.264 screen recording compression.",
                video_codec="libx264",
                crf=23,
                preset="slow",
                audio_bitrate="96k",
            ),
            reference_size_bytes=10,
            source_fps=60.0,
            output_fps=30.0,
            source_audio_bit_rate=128_000,
        ),
    )

    def fake_run_command(cmd, dry_run=False):
        Path(cmd[-1]).write_bytes(b"x" * 20)

    monkeypatch.setattr(render, "run_command", fake_run_command)

    try:
        render_project(project, compress="smart")
    except ValidationError as exc:
        assert "would be larger" in str(exc)
    else:
        raise AssertionError("larger compressed render should fail by default")

    assert not output.exists()


def _capture_command(monkeypatch, **video_info_kwargs: Any) -> dict[str, Any]:
    calls: dict[str, Any] = {}
    monkeypatch.setattr(render, "ensure_tool", lambda _: "ffmpeg")
    monkeypatch.setattr(render, "run_command", lambda cmd, dry_run=False: calls.update(cmd=cmd))
    patch_probe_media(monkeypatch, render, **video_info_kwargs)
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
