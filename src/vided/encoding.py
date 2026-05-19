from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .errors import ValidationError


@dataclass(frozen=True)
class SampleEstimate:
    path: Path
    sample_duration: float
    full_duration: float
    sample_size_bytes: int | None
    estimated_full_size_bytes: int | None


def video_encode_args(render_config: Mapping[str, Any]) -> list[str]:
    video_codec = str(render_config.get("video_codec", "libx264"))
    crf = str(render_config.get("crf", 16))
    preset = str(render_config.get("preset", "medium"))
    pix_fmt = str(render_config.get("pixel_format", "yuv420p"))
    video_tag = render_config.get("video_tag")

    args = ["-c:v", video_codec]
    if video_codec in {"libx264", "libx265", "libsvtav1"}:
        args.extend(["-crf", crf, "-preset", preset])
    if pix_fmt:
        args.extend(["-pix_fmt", pix_fmt])
    if video_tag:
        args.extend(["-tag:v", str(video_tag)])
    return args


def sample_duration_seconds(value: float | int | None) -> float | None:
    if value is None:
        return None
    duration = float(value)
    if duration <= 0:
        raise ValidationError("sample duration must be greater than 0 seconds")
    return duration


def sample_output_path(
    *,
    requested: Path | None,
    default_dir: Path,
    label: str,
    suffix: str = "current",
) -> Path:
    if requested is not None:
        return requested
    return default_dir / f"{label}-sample-{suffix}.mp4"


def output_duration_from_segments(segments: list[Any]) -> float:
    duration = 0.0
    for segment in segments:
        speed = float(getattr(segment, "speed", 1.0) or 1.0)
        if speed <= 0:
            speed = 1.0
        duration += float(getattr(segment, "duration", 0.0)) / speed
    return duration


def build_sample_estimate(
    path: Path,
    *,
    sample_duration: float,
    full_duration: float,
    dry_run: bool,
) -> SampleEstimate:
    if dry_run or not path.exists():
        return SampleEstimate(
            path=path,
            sample_duration=sample_duration,
            full_duration=full_duration,
            sample_size_bytes=None,
            estimated_full_size_bytes=None,
        )

    sample_size = path.stat().st_size
    measured_duration = (
        min(sample_duration, full_duration) if full_duration > 0 else sample_duration
    )
    if measured_duration <= 0:
        estimated_size = None
    else:
        estimated_size = round(sample_size * (full_duration / measured_duration))
    return SampleEstimate(
        path=path,
        sample_duration=sample_duration,
        full_duration=full_duration,
        sample_size_bytes=sample_size,
        estimated_full_size_bytes=estimated_size,
    )


def format_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "unknown"
    units = ["B", "KiB", "MiB", "GiB"]
    value = float(size_bytes)
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{int(value)} {unit}"
    return f"{value:.1f} {unit}"


def format_sample_estimate(estimate: SampleEstimate) -> str:
    return (
        f"Sample size: {format_size(estimate.sample_size_bytes)}; "
        f"estimated full size: {format_size(estimate.estimated_full_size_bytes)}"
    )


def ensure_output_not_larger(
    output: Path,
    reference: Path,
    *,
    allow_larger: bool,
    dry_run: bool,
) -> None:
    if allow_larger or dry_run:
        return
    if not output.exists() or not reference.exists():
        return

    output_size = output.stat().st_size
    reference_size = reference.stat().st_size
    if output_size <= reference_size:
        return

    try:
        output.unlink()
    except OSError:
        pass
    raise ValidationError(
        "compressed output would be larger than its source "
        f"({format_size(output_size)} > {format_size(reference_size)}). "
        "Use --allow-larger to keep it anyway, or try --compression-priority size "
        "or a lower --max-fps."
    )
