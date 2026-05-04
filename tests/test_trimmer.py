from __future__ import annotations

from pathlib import Path
import struct

from PIL import Image

from helpers import (
    BasicProject,
    build_trim_command_for_test,
    filtergraph_from,
    patch_probe_media,
    stub_trim_segments,
    video_info,
    write_basic_project,
)
from vided import trimmer
from vided.project import default_project_config


def test_default_project_config_uses_hybrid_trim_mode() -> None:
    cfg = default_project_config(
        original_path=Path("/tmp/project/input/original.mp4"),
        source_path=Path("/tmp/source.mp4"),
        source_info=video_info(Path("/tmp/source.mp4"), duration=12.0),
        frame_interval=1.0,
    )

    assert cfg["trim"]["detector"] == "audio"
    assert cfg["trim"]["mode"] == "hybrid"
    assert "renderer" not in cfg["trim"]
    assert "edit_method" not in cfg["trim"]
    assert cfg["trim"]["smooth"] == "0.2s,0.1s"
    assert cfg["trim"]["long_silence_min_seconds"] == 1.5
    assert cfg["trim"]["audio_threshold"] == 0.04
    assert cfg["trim"]["speed_indicator"] == {
        "enabled": False,
        "corner": "top-right",
        "style": "dark",
        "min_display_seconds": 1.0,
    }
    assert cfg["trim"]["vad"]["threshold"] == 0.5
    assert cfg["trim"]["vad"]["manual_keep_ranges"] == []
    assert cfg["audio"]["preset"] == "none"


def test_build_trim_timeline_maps_source_segments_to_trimmed_output() -> None:
    timeline = trimmer.build_trim_timeline(
        [
            trimmer.TrimSegment(start=0.0, end=4.0),
            trimmer.TrimSegment(start=5.0, end=13.0, speed=8.0, mute_audio=True),
            trimmer.TrimSegment(start=14.0, end=18.0),
        ]
    )

    assert timeline == {
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
            {
                "source_start": 14.0,
                "source_end": 18.0,
                "output_start": 5.0,
                "output_end": 9.0,
                "speed": 1.0,
                "mute_audio": False,
            },
        ],
    }


def test_speed_indicator_badge_generates_rgba_png(tmp_path) -> None:
    assert trimmer._speed_indicator_display_label("8x") == "\u25b6\u25b6 8x"
    assert all(not Path(candidate).is_absolute() for candidate in trimmer._FONT_CANDIDATES)

    for style in ["dark", "light"]:
        small = tmp_path / f"{style}-small.png"
        large = tmp_path / f"{style}-large.png"

        trimmer._write_speed_indicator_badge(
            small,
            label="8x",
            style=style,
            video_width=480,
            video_height=360,
        )
        trimmer._write_speed_indicator_badge(
            large,
            label="8x",
            style=style,
            video_width=1920,
            video_height=1080,
        )

        with Image.open(small) as image:
            assert image.mode == "RGBA"
            assert image.size[0] >= 48
            assert image.size[1] >= 20
            assert image.getchannel("A").getbbox() is not None
            small_size = image.size

        with Image.open(large) as image:
            assert image.mode == "RGBA"
            assert image.size[0] > small_size[0]
            assert image.size[1] > small_size[1]
            assert image.getchannel("A").getbbox() is not None


def test_pcm_audio_levels_chunks_peak_amplitude_across_channels() -> None:
    pcm = struct.pack("<hhhhhhhh", 0, 1000, -32768, 0, 100, 200, 3000, -4000)

    levels = trimmer._pcm_audio_levels(
        pcm,
        sample_rate=4,
        channels=2,
        timebase_fps=2.0,
    )

    assert levels == [1.0, 4000 / 32767.0]


def test_ffmpeg_trim_command_uses_concat_segments(basic_project: BasicProject, monkeypatch) -> None:
    project = basic_project.root
    patch_probe_media(monkeypatch, trimmer)
    stub_trim_segments(
        monkeypatch,
        trimmer.TrimSegment(start=0.0, end=2.0),
        trimmer.TrimSegment(start=3.0, end=7.0, speed=8.0, mute_audio=True),
    )

    cmd = build_trim_command_for_test(project)
    graph = filtergraph_from(cmd)

    assert "trim=start=0:end=2,setpts=(PTS-STARTPTS)/1[v0]" in graph
    assert "trim=start=3:end=7,setpts=(PTS-STARTPTS)/8[v1]" in graph
    assert "atempo=2,atempo=2,atempo=2,volume=0[a1]" in graph
    assert "concat=n=2:v=1:a=1[vout][aout]" in graph


def test_ffmpeg_trim_command_outputs_only_filtered_media_streams(
    basic_project: BasicProject, monkeypatch
) -> None:
    project = basic_project.root
    patch_probe_media(monkeypatch, trimmer)
    stub_trim_segments(monkeypatch, trimmer.TrimSegment(start=0.0, end=10.0))

    cmd = build_trim_command_for_test(project)
    mapped_streams = [cmd[index + 1] for index, arg in enumerate(cmd[:-1]) if arg == "-map"]

    assert mapped_streams == ["[vout]", "[aout]"]
    assert "0:v" not in mapped_streams
    assert "0:a" not in mapped_streams
    assert "-sn" in cmd
    assert "-dn" in cmd
    assert cmd[cmd.index("-map_chapters") + 1] == "-1"
    assert "-shortest" in cmd


def test_ffmpeg_trim_command_overlays_speed_indicator_on_sped_segments(
    tmp_path, monkeypatch
) -> None:
    project = write_basic_project(
        tmp_path / "project",
        trim_overrides={
            "speed_indicator": {
                "enabled": True,
                "corner": "bottom-left",
                "style": "light",
            },
        },
    )
    patch_probe_media(monkeypatch, trimmer, duration=20.0)
    stub_trim_segments(
        monkeypatch,
        trimmer.TrimSegment(start=0.0, end=2.0),
        trimmer.TrimSegment(start=3.0, end=15.0, speed=8.0, mute_audio=True),
    )

    cmd = build_trim_command_for_test(project)
    graph = filtergraph_from(cmd)
    badge = project / "work" / "speed-indicator-8x-light.png"

    assert cmd[cmd.index("-loop") + 1] == "1"
    assert str(badge) in cmd
    assert not badge.exists()
    assert "trim=start=0:end=2,setpts=(PTS-STARTPTS)/1[v0]" in graph
    assert "trim=start=3:end=15,setpts=(PTS-STARTPTS)/8[v1base]" in graph
    assert (
        "[v1base][1:v]overlay=x=38:y=main_h-overlay_h-38:"
        "shortest=1:eof_action=repeat:repeatlast=1[v1]"
    ) in graph
    assert "concat=n=2:v=1:a=1[vout][aout]" in graph

    monkeypatch.setattr(trimmer, "ensure_tool", lambda _: "ffmpeg")
    monkeypatch.setattr(trimmer, "run_command", lambda *args, **kwargs: None)
    plan = trimmer.plan_trim(project)
    dry_result = trimmer.run_trim_plan(plan, overwrite=True, dry_run=True)
    assert dry_result.wrote_files is False
    assert not badge.exists()

    result = trimmer.run_trim_plan(plan, overwrite=True)
    assert result.wrote_files is True
    assert badge.exists()


def test_ffmpeg_trim_command_skips_speed_indicator_for_short_sped_segments(
    tmp_path, monkeypatch
) -> None:
    project = write_basic_project(
        tmp_path / "project",
        trim_overrides={
            "speed_indicator": {
                "enabled": True,
                "min_display_seconds": 1.0,
            },
        },
    )
    patch_probe_media(monkeypatch, trimmer)
    stub_trim_segments(
        monkeypatch,
        trimmer.TrimSegment(start=0.0, end=2.0),
        trimmer.TrimSegment(start=3.0, end=7.0, speed=8.0, mute_audio=True),
    )

    cmd = build_trim_command_for_test(project)
    graph = filtergraph_from(cmd)

    assert "-loop" not in cmd
    assert "overlay=" not in graph
    assert not list((project / "work").glob("speed-indicator-*.png"))


def test_ffmpeg_trim_command_skips_speed_indicator_without_sped_segments(
    tmp_path, monkeypatch
) -> None:
    project = write_basic_project(
        tmp_path / "project",
        trim_overrides={
            "mode": "keep",
            "speed_indicator": {"enabled": True},
        },
    )
    patch_probe_media(monkeypatch, trimmer)

    cmd = build_trim_command_for_test(project)
    graph = filtergraph_from(cmd)

    assert "-loop" not in cmd
    assert "overlay=" not in graph
    assert not list((project / "work").glob("speed-indicator-*.png"))


def test_activity_ranges_apply_margin_and_smoothing(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"")
    monkeypatch.setattr(
        trimmer,
        "_read_audio_levels",
        lambda *args, **kwargs: [
            0.05,
            0.05,
            0.0,
            0.05,
            0.05,
            0.0,
            0.0,
            0.05,
            0.0,
            0.0,
        ],
    )

    ranges = trimmer._activity_ranges(
        source,
        media_info=video_info(
            source,
            duration=1.0,
            fps=10.0,
            audio_sample_rate=10,
            audio_channels=1,
        ),
        duration=1.0,
        threshold=0.04,
        margin=(0.0, 0.0),
        smooth=(0.2, 0.2),
        timebase_fps=10.0,
    )

    assert ranges == [
        (0.0, 0.5, True),
        (0.5, 1.0, False),
    ]


def test_no_audio_trim_segments_keep_whole_video(tmp_path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"")

    segments = trimmer._trim_segments(
        source,
        media_info=video_info(
            source,
            duration=10.0,
            fps=30.0,
            has_audio=False,
        ),
        duration=10.0,
        mode="hybrid",
        threshold=0.04,
        margin=(0.2, 0.2),
        smooth=(0.2, 0.1),
        timebase_fps=30.0,
        silent_speed=8.0,
        mute_silent_audio=True,
        long_silence_min_seconds=1.5,
    )

    assert segments == [trimmer.TrimSegment(start=0.0, end=10.0)]
