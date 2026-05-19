from __future__ import annotations

from pathlib import Path

import pytest

from vided.encoding import (
    build_sample_estimate,
    ensure_output_not_larger,
    format_sample_estimate,
    sample_output_path,
    video_encode_args,
)
from vided.errors import ValidationError


def test_h264_video_args_use_crf_preset_and_pixel_format() -> None:
    args = video_encode_args(
        {
            "video_codec": "libx264",
            "crf": 23,
            "preset": "slow",
            "pixel_format": "yuv420p",
        }
    )

    assert args == [
        "-c:v",
        "libx264",
        "-crf",
        "23",
        "-preset",
        "slow",
        "-pix_fmt",
        "yuv420p",
    ]


def test_hevc_video_args_include_compatibility_tag() -> None:
    args = video_encode_args(
        {
            "video_codec": "libx265",
            "crf": 28,
            "preset": "medium",
            "pixel_format": "yuv420p",
            "video_tag": "hvc1",
        }
    )

    assert args == [
        "-c:v",
        "libx265",
        "-crf",
        "28",
        "-preset",
        "medium",
        "-pix_fmt",
        "yuv420p",
        "-tag:v",
        "hvc1",
    ]


def test_sample_output_path_uses_suffix() -> None:
    assert sample_output_path(
        requested=None,
        default_dir=Path("output"),
        label="final",
        suffix="smart",
    ) == Path("output/final-sample-smart.mp4")


def test_sample_estimate_scales_sample_size(tmp_path: Path) -> None:
    sample = tmp_path / "sample.mp4"
    sample.write_bytes(b"x" * 100)

    estimate = build_sample_estimate(
        sample,
        sample_duration=10.0,
        full_duration=60.0,
        dry_run=False,
    )

    assert estimate.sample_size_bytes == 100
    assert estimate.estimated_full_size_bytes == 600
    assert "estimated full size" in format_sample_estimate(estimate)


def test_size_guard_removes_larger_output(tmp_path: Path) -> None:
    output = tmp_path / "output.mp4"
    reference = tmp_path / "reference.mp4"
    output.write_bytes(b"x" * 20)
    reference.write_bytes(b"x" * 10)

    with pytest.raises(ValidationError, match="would be larger"):
        ensure_output_not_larger(
            output,
            reference,
            allow_larger=False,
            dry_run=False,
        )

    assert not output.exists()
