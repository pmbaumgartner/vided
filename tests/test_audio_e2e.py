from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shutil

import pytest

from vided.audio_presets import list_audio_presets
from vided.audio_preview import render_audio_preview
from vided.ffmpeg import probe_media, run_command
from vided.project import create_project, load_project, project_paths, save_project
from vided.render import render_project
from vided.trimmer import TrimOptions, TrimSegment, build_trim_timeline, plan_trim, run_trim_plan


@pytest.mark.e2e
def test_audio_presets_and_preview_smoke_with_ffmpeg(
    tmp_path: Path, require_tools: Callable[..., None]
) -> None:
    require_tools("ffmpeg", "ffprobe")
    source = tmp_path / "source.mp4"
    run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=30:duration=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ]
    )

    project = tmp_path / "project"
    create_project(source, project, copy_input=False)
    p = project_paths(project)
    p.trimmed.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, p.trimmed)

    cfg = load_project(project)
    cfg["trim_timeline"] = build_trim_timeline([TrimSegment(start=0.0, end=3.0)])
    save_project(project, cfg)

    preview = render_audio_preview(project, audio_preset="level", overwrite=True)
    final = render_project(project, audio_preset="voice-safe", overwrite=True)

    assert probe_media(preview).has_audio
    assert probe_media(final).has_audio


@pytest.mark.e2e
def test_realistic_fixture_audio_preview_and_render_all_presets(
    tmp_path: Path,
    realistic_short_fixture: Path,
    require_tools: Callable[..., None],
) -> None:
    require_tools("ffmpeg", "ffprobe")
    pytest.importorskip("onnxruntime")

    project = tmp_path / "fixture-audio-presets"
    create_project(realistic_short_fixture, project, copy_input=False)
    trimmed = run_trim_plan(
        plan_trim(
            project,
            options=TrimOptions(detector="vad"),
            allow_vad_detection=True,
        ),
        overwrite=True,
    ).path
    trimmed_info = probe_media(trimmed)

    for preset in list_audio_presets():
        preview = render_audio_preview(
            project,
            audio_preset=preset.name,
            output=Path(f"output/audio-preview-{preset.name}.mp4"),
            overwrite=True,
        )
        final = render_project(
            project,
            audio_preset=preset.name,
            output=Path(f"output/final-{preset.name}.mp4"),
            overwrite=True,
        )

        preview_info = probe_media(preview)
        final_info = probe_media(final)

        assert preview.exists()
        assert final.exists()
        assert preview_info.has_audio
        assert final_info.has_audio
        assert 0.0 < preview_info.duration <= 15.25
        assert abs(final_info.duration - trimmed_info.duration) < 0.75
