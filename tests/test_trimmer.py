from __future__ import annotations

from pathlib import Path
import struct

from PIL import Image

from vided import trimmer
from vided.project import default_project_config, write_json
from vided.ffmpeg import VideoInfo


def test_default_project_config_uses_hybrid_trim_mode() -> None:
    cfg = default_project_config(
        original_path=Path("/tmp/project/input/original.mp4"),
        source_path=Path("/tmp/source.mp4"),
        source_info=VideoInfo(
            path=Path("/tmp/source.mp4"),
            width=1920,
            height=1080,
            duration=12.0,
            fps=60.0,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        ),
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
    assert cfg["trim"]["silero"]["threshold"] == 0.5
    assert cfg["trim"]["silero"]["manual_keep_ranges"] == []


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


def test_ffmpeg_trim_command_uses_concat_segments(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    (project / "input").mkdir(parents=True)
    (project / "work").mkdir()
    original = project / "input" / "original.mp4"
    original.write_bytes(b"")
    write_json(
        project / "project.json",
        {
            "original_path": "input/original.mp4",
            "trimmed_path": "work/trimmed.mp4",
            "trim": {
                "mode": "hybrid",
                "margin": "0.2s",
                "smooth": "0.2s,0.1s",
                "audio_threshold": 0.04,
                "long_silence_min_seconds": 1.5,
                "silent_speed": 8.0,
                "mute_silent_audio": True,
            },
            "render": {
                "video_codec": "libx264",
                "crf": 16,
                "preset": "medium",
                "pixel_format": "yuv420p",
                "audio_bitrate": "192k",
            },
        },
    )
    monkeypatch.setattr(
        trimmer,
        "probe_media",
        lambda path: VideoInfo(
            path=path,
            width=1920,
            height=1080,
            duration=10.0,
            fps=60.0,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        ),
    )
    monkeypatch.setattr(
        trimmer,
        "_trim_segments",
        lambda *args, **kwargs: [
            trimmer.TrimSegment(start=0.0, end=2.0),
            trimmer.TrimSegment(start=3.0, end=7.0, speed=8.0, mute_audio=True),
        ],
    )

    cmd = trimmer.build_ffmpeg_trim_command(project)
    graph = cmd[cmd.index("-filter_complex") + 1]

    assert "trim=start=0:end=2,setpts=(PTS-STARTPTS)/1[v0]" in graph
    assert "trim=start=3:end=7,setpts=(PTS-STARTPTS)/8[v1]" in graph
    assert "atempo=2,atempo=2,atempo=2,volume=0[a1]" in graph
    assert "concat=n=2:v=1:a=1[vout][aout]" in graph


def test_ffmpeg_trim_command_overlays_speed_indicator_on_sped_segments(
    tmp_path, monkeypatch
) -> None:
    project = tmp_path / "project"
    (project / "input").mkdir(parents=True)
    (project / "work").mkdir()
    original = project / "input" / "original.mp4"
    original.write_bytes(b"")
    write_json(
        project / "project.json",
        {
            "original_path": "input/original.mp4",
            "trimmed_path": "work/trimmed.mp4",
            "trim": {
                "mode": "hybrid",
                "margin": "0.2s",
                "smooth": "0.2s,0.1s",
                "audio_threshold": 0.04,
                "long_silence_min_seconds": 1.5,
                "silent_speed": 8.0,
                "mute_silent_audio": True,
                "speed_indicator": {
                    "enabled": True,
                    "corner": "bottom-left",
                    "style": "light",
                },
            },
            "render": {
                "video_codec": "libx264",
                "crf": 16,
                "preset": "medium",
                "pixel_format": "yuv420p",
                "audio_bitrate": "192k",
            },
        },
    )
    monkeypatch.setattr(
        trimmer,
        "probe_media",
        lambda path: VideoInfo(
            path=path,
            width=1920,
            height=1080,
            duration=20.0,
            fps=60.0,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        ),
    )
    monkeypatch.setattr(
        trimmer,
        "_trim_segments",
        lambda *args, **kwargs: [
            trimmer.TrimSegment(start=0.0, end=2.0),
            trimmer.TrimSegment(start=3.0, end=15.0, speed=8.0, mute_audio=True),
        ],
    )

    cmd = trimmer.build_ffmpeg_trim_command(project)
    graph = cmd[cmd.index("-filter_complex") + 1]
    badge = project / "work" / "speed-indicator-8x-light.png"

    assert cmd[cmd.index("-loop") + 1] == "1"
    assert str(badge) in cmd
    assert badge.exists()
    assert "trim=start=0:end=2,setpts=(PTS-STARTPTS)/1[v0]" in graph
    assert "trim=start=3:end=15,setpts=(PTS-STARTPTS)/8[v1base]" in graph
    assert (
        "[v1base][1:v]overlay=x=38:y=main_h-overlay_h-38:"
        "shortest=1:eof_action=repeat:repeatlast=1[v1]"
    ) in graph
    assert "concat=n=2:v=1:a=1[vout][aout]" in graph


def test_ffmpeg_trim_command_skips_speed_indicator_for_short_sped_segments(
    tmp_path, monkeypatch
) -> None:
    project = tmp_path / "project"
    (project / "input").mkdir(parents=True)
    (project / "work").mkdir()
    original = project / "input" / "original.mp4"
    original.write_bytes(b"")
    write_json(
        project / "project.json",
        {
            "original_path": "input/original.mp4",
            "trimmed_path": "work/trimmed.mp4",
            "trim": {
                "mode": "hybrid",
                "margin": "0.2s",
                "smooth": "0.2s,0.1s",
                "audio_threshold": 0.04,
                "long_silence_min_seconds": 1.5,
                "silent_speed": 8.0,
                "mute_silent_audio": True,
                "speed_indicator": {
                    "enabled": True,
                    "min_display_seconds": 1.0,
                },
            },
            "render": {
                "video_codec": "libx264",
                "crf": 16,
                "preset": "medium",
                "pixel_format": "yuv420p",
                "audio_bitrate": "192k",
            },
        },
    )
    monkeypatch.setattr(
        trimmer,
        "probe_media",
        lambda path: VideoInfo(
            path=path,
            width=1920,
            height=1080,
            duration=10.0,
            fps=60.0,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        ),
    )
    monkeypatch.setattr(
        trimmer,
        "_trim_segments",
        lambda *args, **kwargs: [
            trimmer.TrimSegment(start=0.0, end=2.0),
            trimmer.TrimSegment(start=3.0, end=7.0, speed=8.0, mute_audio=True),
        ],
    )

    cmd = trimmer.build_ffmpeg_trim_command(project)
    graph = cmd[cmd.index("-filter_complex") + 1]

    assert "-loop" not in cmd
    assert "overlay=" not in graph
    assert not list((project / "work").glob("speed-indicator-*.png"))


def test_ffmpeg_trim_command_skips_speed_indicator_without_sped_segments(
    tmp_path, monkeypatch
) -> None:
    project = tmp_path / "project"
    (project / "input").mkdir(parents=True)
    (project / "work").mkdir()
    original = project / "input" / "original.mp4"
    original.write_bytes(b"")
    write_json(
        project / "project.json",
        {
            "original_path": "input/original.mp4",
            "trimmed_path": "work/trimmed.mp4",
            "trim": {
                "mode": "keep",
                "speed_indicator": {"enabled": True},
            },
            "render": {
                "video_codec": "libx264",
                "crf": 16,
                "preset": "medium",
                "pixel_format": "yuv420p",
            },
        },
    )
    monkeypatch.setattr(
        trimmer,
        "probe_media",
        lambda path: VideoInfo(
            path=path,
            width=1920,
            height=1080,
            duration=10.0,
            fps=60.0,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        ),
    )

    cmd = trimmer.build_ffmpeg_trim_command(project)
    graph = cmd[cmd.index("-filter_complex") + 1]

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
        media_info=VideoInfo(
            path=source,
            width=1920,
            height=1080,
            duration=1.0,
            fps=10.0,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
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
        media_info=VideoInfo(
            path=source,
            width=1920,
            height=1080,
            duration=10.0,
            fps=30.0,
            video_codec="h264",
            audio_codec=None,
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
