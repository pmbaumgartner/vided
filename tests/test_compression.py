from __future__ import annotations

from pathlib import Path

import pytest

from helpers import video_info
from vided.compression import (
    choose_smart_compression,
    sample_windows,
    smart_audio_bitrate,
    smart_compression_candidates,
    smart_fps_cap,
)
from vided.errors import ValidationError


def test_smart_fps_cap_only_caps_high_fps() -> None:
    assert smart_fps_cap(video_info(Path("source.mp4"), fps=60.0), max_fps=None) == 30.0
    assert smart_fps_cap(video_info(Path("source.mp4"), fps=30.0), max_fps=None) is None
    assert smart_fps_cap(video_info(Path("source.mp4"), fps=60.0), max_fps=24.0) == 24.0


def test_smart_audio_bitrate_never_increases_source_audio() -> None:
    assert (
        smart_audio_bitrate(
            video_info(Path("source.mp4"), audio_bit_rate=64_000),
            {"audio_bitrate": "192k"},
        )
        == "64k"
    )
    assert (
        smart_audio_bitrate(
            video_info(Path("source.mp4"), audio_bit_rate=192_000),
            {"audio_bitrate": "192k"},
        )
        == "96k"
    )


def test_compatibility_candidates_do_not_use_hevc() -> None:
    candidates = smart_compression_candidates(
        video_info(Path("source.mp4"), fps=60.0),
        {},
        priority="compatibility",
        max_fps=None,
    )

    assert [candidate.video_codec for candidate in candidates] == ["libx264", "libx264"]
    assert all(candidate.max_fps == 30.0 for candidate in candidates)


def test_size_candidates_can_use_hevc() -> None:
    candidates = smart_compression_candidates(
        video_info(Path("source.mp4"), fps=60.0),
        {},
        priority="size",
        max_fps=None,
    )

    assert [candidate.video_codec for candidate in candidates] == [
        "libx264",
        "libx265",
        "libx265",
    ]
    assert candidates[1].video_tag == "hvc1"


def test_sample_windows_use_representative_points_for_long_videos() -> None:
    windows = sample_windows(1000.0)

    assert len(windows) == 3
    assert [window.duration for window in windows] == [10.0, 10.0, 10.0]
    assert [round(window.start) for window in windows] == [95, 495, 845]


def test_choose_smart_compression_selects_smallest_viable_candidate(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("vided.compression.ensure_tool", lambda _: "ffmpeg")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"x" * 1000)
    calls: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> None:
        calls.append(cmd)
        output = Path(cmd[-1])
        if "smart-h264-balanced" in output.name:
            output.write_bytes(b"x" * 100)
        else:
            output.write_bytes(b"x" * 80)

    decision = choose_smart_compression(
        source,
        video_info(source, duration=10.0, fps=60.0, audio_bit_rate=128_000),
        {},
        full_duration=10.0,
        sample_dir=tmp_path / "samples",
        sample_label="final",
        runner=fake_runner,
    )

    assert decision.candidate.name == "smart-h264-small"
    assert decision.estimate is not None
    assert decision.estimate.estimated_full_size_bytes == 80
    assert calls[0][calls[0].index("-vf") + 1] == "fps=fps=30"
    assert calls[0][calls[0].index("-b:a") + 1] == "96k"


def test_choose_smart_compression_rejects_when_samples_do_not_save_size(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("vided.compression.ensure_tool", lambda _: "ffmpeg")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"x" * 1000)

    def fake_runner(cmd: list[str]) -> None:
        Path(cmd[-1]).write_bytes(b"x" * 980)

    with pytest.raises(ValidationError, match="could not find"):
        choose_smart_compression(
            source,
            video_info(source, duration=10.0, fps=60.0),
            {},
            full_duration=10.0,
            sample_dir=tmp_path / "samples",
            runner=fake_runner,
        )
