from __future__ import annotations

from pathlib import Path

import pytest

from vided.frames import (
    FrameExtractionOptions,
    build_frame_extraction_command,
    resolve_frame_extraction_options,
)


def test_resolve_frame_extraction_options_uses_defaults_and_overrides() -> None:
    assert resolve_frame_extraction_options({}) == FrameExtractionOptions(
        interval_seconds=1.0,
        thumbnail_width=640,
    )
    assert resolve_frame_extraction_options(
        {"frames": {"interval_seconds": 2.0, "thumbnail_width": 320}},
        interval_seconds=0.5,
        thumbnail_width=960,
    ) == FrameExtractionOptions(interval_seconds=0.5, thumbnail_width=960)


def test_resolve_frame_extraction_options_validates_explicit_zeroes() -> None:
    with pytest.raises(ValueError, match="interval_seconds must be greater than 0"):
        resolve_frame_extraction_options(
            {"frames": {"interval_seconds": 2.0}},
            interval_seconds=0,
        )
    with pytest.raises(ValueError, match="thumbnail_width must be greater than 0"):
        resolve_frame_extraction_options(
            {"frames": {"thumbnail_width": 320}},
            thumbnail_width=0,
        )


def test_build_frame_extraction_command_preserves_ffmpeg_filter_shape() -> None:
    cmd = build_frame_extraction_command(
        Path("input.mp4"),
        Path("frames/frame_%06d.jpg"),
        options=FrameExtractionOptions(interval_seconds=0.5, thumbnail_width=960),
        overwrite=False,
    )

    assert cmd == [
        "ffmpeg",
        "-hide_banner",
        "-n",
        "-i",
        "input.mp4",
        "-vf",
        "fps=2.00000000,scale=960:-2",
        "-q:v",
        "2",
        "frames/frame_%06d.jpg",
    ]
    assert (
        build_frame_extraction_command(
            Path("input.mp4"),
            Path("frames/frame_%06d.jpg"),
            options=FrameExtractionOptions(interval_seconds=1.0, thumbnail_width=640),
            overwrite=True,
        )[2]
        == "-y"
    )
