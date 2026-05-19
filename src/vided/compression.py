from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from .errors import ValidationError
from .ffmpeg import VideoInfo, ensure_tool, run_command
from .encoding import format_size, video_encode_args

CompressionMode = Literal["off", "smart"]
CompressionPriority = Literal["compatibility", "size"]

_DEFAULT_MAX_FPS = 30.0
_MAX_AUDIO_BIT_RATE = 96_000
_MIN_SAVINGS_RATIO = 0.95


@dataclass(frozen=True)
class SampleWindow:
    start: float
    duration: float


@dataclass(frozen=True)
class CompressionCandidate:
    name: str
    description: str
    video_codec: str
    crf: int
    preset: str
    audio_bitrate: str
    audio_codec: str = "aac"
    pixel_format: str = "yuv420p"
    video_tag: str | None = None
    max_fps: float | None = None

    def as_render_config(self) -> dict[str, Any]:
        cfg: dict[str, Any] = {
            "video_codec": self.video_codec,
            "crf": self.crf,
            "preset": self.preset,
            "pixel_format": self.pixel_format,
            "audio_codec": self.audio_codec,
            "audio_bitrate": self.audio_bitrate,
        }
        if self.video_tag:
            cfg["video_tag"] = self.video_tag
        if self.max_fps is not None:
            cfg["max_fps"] = self.max_fps
        return cfg


@dataclass(frozen=True)
class CompressionEstimate:
    sample_size_bytes: int | None
    sample_duration: float
    estimated_full_size_bytes: int | None


@dataclass(frozen=True)
class CompressionDecision:
    mode: CompressionMode
    priority: CompressionPriority
    candidate: CompressionCandidate
    reference_size_bytes: int | None
    source_fps: float | None
    output_fps: float | None
    source_audio_bit_rate: int | None
    estimate: CompressionEstimate | None = None

    def as_render_config(self) -> dict[str, Any]:
        return self.candidate.as_render_config()


RunCommand = Callable[[list[str]], object]


def normalize_compression_mode(value: str | None) -> CompressionMode:
    if value is None:
        return "off"
    if value == "off":
        return "off"
    if value == "smart":
        return "smart"
    raise ValidationError("compression mode must be one of: off, smart")


def normalize_compression_priority(value: str | None) -> CompressionPriority:
    if value is None:
        return "compatibility"
    if value == "compatibility":
        return "compatibility"
    if value == "size":
        return "size"
    raise ValidationError("compression priority must be one of: compatibility, size")


def render_config_with_compression(
    render_config: Mapping[str, Any],
    decision: CompressionDecision | None,
) -> dict[str, Any]:
    cfg = dict(render_config)
    if decision is not None:
        cfg.update(decision.as_render_config())
    return cfg


def output_fps_filter(render_config: Mapping[str, Any]) -> str | None:
    value = render_config.get("max_fps")
    if value is None:
        return None
    try:
        fps = float(value)
    except (TypeError, ValueError):
        raise ValidationError("max fps must be a number")
    if fps <= 0:
        raise ValidationError("max fps must be greater than 0")
    return f"fps=fps={_format_number(fps)}"


def append_output_video_filter(
    graph: str,
    render_config: Mapping[str, Any],
    *,
    input_label: str = "vout",
    output_label: str = "voutfps",
) -> tuple[str, str]:
    fps_filter = output_fps_filter(render_config)
    if fps_filter is None:
        return graph, input_label
    return f"{graph};\n[{input_label}]{fps_filter}[{output_label}]", output_label


def video_filter_args(render_config: Mapping[str, Any]) -> list[str]:
    fps_filter = output_fps_filter(render_config)
    if fps_filter is None:
        return []
    return ["-vf", fps_filter]


def choose_smart_compression(
    reference: Path,
    media_info: VideoInfo,
    render_config: Mapping[str, Any],
    *,
    priority: str | None = None,
    max_fps: float | None = None,
    full_duration: float | None = None,
    sample_dir: Path | None = None,
    sample_label: str = "smart",
    dry_run: bool = False,
    runner: RunCommand | None = None,
) -> CompressionDecision:
    normalized_priority = normalize_compression_priority(priority)
    reference_size = _reference_size(reference, media_info)
    candidates = smart_compression_candidates(
        media_info,
        render_config,
        priority=normalized_priority,
        max_fps=max_fps,
    )
    if dry_run:
        candidate = candidates[0]
        return CompressionDecision(
            mode="smart",
            priority=normalized_priority,
            candidate=candidate,
            reference_size_bytes=reference_size,
            source_fps=media_info.fps,
            output_fps=candidate.max_fps,
            source_audio_bit_rate=media_info.audio_bit_rate,
            estimate=None,
        )

    if sample_dir is None:
        sample_dir = reference.parent
    sample_dir.mkdir(parents=True, exist_ok=True)
    ensure_tool("ffmpeg")

    duration = full_duration if full_duration is not None else media_info.duration
    windows = sample_windows(media_info.duration)
    runner = runner or _run_command

    decisions: list[CompressionDecision] = []
    for candidate in candidates:
        estimate = sample_candidate(
            reference,
            media_info,
            candidate,
            windows=windows,
            full_duration=duration,
            sample_dir=sample_dir,
            sample_label=sample_label,
            runner=runner,
        )
        decisions.append(
            CompressionDecision(
                mode="smart",
                priority=normalized_priority,
                candidate=candidate,
                reference_size_bytes=reference_size,
                source_fps=media_info.fps,
                output_fps=candidate.max_fps,
                source_audio_bit_rate=media_info.audio_bit_rate,
                estimate=estimate,
            )
        )

    viable = [
        decision
        for decision in decisions
        if _beats_reference(
            decision.estimate.estimated_full_size_bytes if decision.estimate else None,
            reference_size,
        )
    ]
    if viable:
        return min(
            viable,
            key=lambda decision: decision.estimate.estimated_full_size_bytes or 0,
        )

    best = min(
        decisions,
        key=lambda decision: (
            decision.estimate.estimated_full_size_bytes
            if decision.estimate and decision.estimate.estimated_full_size_bytes is not None
            else float("inf")
        ),
    )
    estimated = best.estimate.estimated_full_size_bytes if best.estimate else None
    raise ValidationError(
        "smart compression could not find a meaningfully smaller output from samples "
        f"(best estimate {format_size(estimated)} vs source {format_size(reference_size)}). "
        "Try --compression-priority size or lower --max-fps."
    )


def smart_compression_candidates(
    media_info: VideoInfo,
    render_config: Mapping[str, Any],
    *,
    priority: CompressionPriority,
    max_fps: float | None,
) -> list[CompressionCandidate]:
    audio_bitrate = smart_audio_bitrate(media_info, render_config)
    fps_cap = smart_fps_cap(media_info, max_fps=max_fps)
    h264_balanced = CompressionCandidate(
        name="smart-h264-balanced",
        description="H.264 screen recording compression.",
        video_codec="libx264",
        crf=23,
        preset="slow",
        audio_bitrate=audio_bitrate,
        max_fps=fps_cap,
    )
    h264_small = CompressionCandidate(
        name="smart-h264-small",
        description="Smaller H.264 screen recording compression.",
        video_codec="libx264",
        crf=26,
        preset="slow",
        audio_bitrate=audio_bitrate,
        max_fps=fps_cap,
    )
    if priority == "compatibility":
        return [h264_balanced, h264_small]

    return [
        h264_small,
        CompressionCandidate(
            name="smart-hevc-balanced",
            description="H.265 screen recording compression for smaller modern playback.",
            video_codec="libx265",
            crf=28,
            preset="medium",
            audio_bitrate=audio_bitrate,
            video_tag="hvc1",
            max_fps=fps_cap,
        ),
        CompressionCandidate(
            name="smart-hevc-small",
            description="Smallest H.265 screen recording compression.",
            video_codec="libx265",
            crf=30,
            preset="medium",
            audio_bitrate=audio_bitrate,
            video_tag="hvc1",
            max_fps=fps_cap,
        ),
    ]


def smart_fps_cap(media_info: VideoInfo, *, max_fps: float | None) -> float | None:
    cap = _DEFAULT_MAX_FPS if max_fps is None else float(max_fps)
    if cap <= 0:
        raise ValidationError("max fps must be greater than 0")
    if media_info.fps is None or media_info.fps <= cap + 0.01:
        return None
    return cap


def smart_audio_bitrate(media_info: VideoInfo, render_config: Mapping[str, Any]) -> str:
    if media_info.audio_bit_rate is not None and media_info.audio_bit_rate > 0:
        return _bitrate_arg(min(media_info.audio_bit_rate, _MAX_AUDIO_BIT_RATE))
    configured = render_config.get("audio_bitrate")
    if isinstance(configured, str):
        parsed = _parse_bitrate_arg(configured)
        if parsed is not None:
            return _bitrate_arg(min(parsed, _MAX_AUDIO_BIT_RATE))
    return _bitrate_arg(_MAX_AUDIO_BIT_RATE)


def sample_windows(duration: float) -> list[SampleWindow]:
    if duration <= 0:
        return [SampleWindow(start=0.0, duration=15.0)]
    if duration <= 90.0:
        return [SampleWindow(start=0.0, duration=min(15.0, duration))]

    window_duration = min(10.0, duration)
    starts: list[float] = []
    for ratio in [0.10, 0.50, 0.85]:
        center = duration * ratio
        start = max(0.0, min(center - (window_duration / 2.0), duration - window_duration))
        if not any(abs(start - existing) < 0.001 for existing in starts):
            starts.append(start)
    return [SampleWindow(start=start, duration=window_duration) for start in starts]


def sample_candidate(
    reference: Path,
    media_info: VideoInfo,
    candidate: CompressionCandidate,
    *,
    windows: list[SampleWindow],
    full_duration: float,
    sample_dir: Path,
    sample_label: str,
    runner: RunCommand,
) -> CompressionEstimate:
    sample_size = 0
    sample_duration = 0.0
    written: list[Path] = []
    try:
        for index, window in enumerate(windows, start=1):
            output = sample_dir / f"{sample_label}-{candidate.name}-{index}.mp4"
            cmd = _sample_command(reference, media_info, candidate, window, output)
            runner(cmd)
            if output.exists():
                sample_size += output.stat().st_size
            sample_duration += window.duration
            written.append(output)
    finally:
        for output in written:
            try:
                output.unlink()
            except OSError:
                pass

    estimated = None
    if sample_duration > 0 and full_duration > 0:
        estimated = round(sample_size * (full_duration / sample_duration))
    return CompressionEstimate(
        sample_size_bytes=sample_size,
        sample_duration=sample_duration,
        estimated_full_size_bytes=estimated,
    )


def format_compression_decision(decision: CompressionDecision) -> str:
    lines = [
        "Compression: smart",
        f"Strategy: {_format_strategy(decision)}",
    ]
    if decision.estimate is not None:
        lines.append(
            "Sample estimate: "
            f"{format_size(decision.estimate.estimated_full_size_bytes)} "
            f"from {format_size(decision.reference_size_bytes)} source"
        )
    return "\n".join(lines)


def format_compression_result(path: Path, decision: CompressionDecision) -> str | None:
    if not path.exists() or decision.reference_size_bytes is None:
        return None
    output_size = path.stat().st_size
    if decision.reference_size_bytes <= 0:
        return f"Final size: {format_size(output_size)}"
    saved = max(0.0, 1.0 - (output_size / decision.reference_size_bytes))
    return f"Final size: {format_size(output_size)}, saved {saved:.0%}"


def _sample_command(
    reference: Path,
    media_info: VideoInfo,
    candidate: CompressionCandidate,
    window: SampleWindow,
    output: Path,
) -> list[str]:
    render_config = candidate.as_render_config()
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        _format_number(window.start),
        "-t",
        _format_number(window.duration),
        "-i",
        str(reference),
        "-map",
        "0:v:0",
    ]
    if media_info.has_audio:
        cmd.extend(["-map", "0:a:0?"])
    cmd.extend(video_filter_args(render_config))
    cmd.extend(video_encode_args(render_config))
    if media_info.has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", candidate.audio_bitrate])
    cmd.extend(["-sn", "-dn", "-map_chapters", "-1", "-movflags", "+faststart", str(output)])
    return cmd


def _run_command(cmd: list[str]) -> object:
    return run_command(cmd)


def _reference_size(reference: Path, media_info: VideoInfo) -> int | None:
    if reference.exists():
        return reference.stat().st_size
    return media_info.file_size_bytes


def _beats_reference(estimated_size: int | None, reference_size: int | None) -> bool:
    if estimated_size is None or reference_size is None or reference_size <= 0:
        return False
    return estimated_size <= round(reference_size * _MIN_SAVINGS_RATIO)


def _bitrate_arg(bits_per_second: int) -> str:
    return f"{max(1, round(bits_per_second / 1000))}k"


def _parse_bitrate_arg(value: str) -> int | None:
    stripped = value.strip().lower()
    if not stripped:
        return None
    multiplier = 1
    if stripped.endswith("k"):
        multiplier = 1000
        stripped = stripped[:-1]
    elif stripped.endswith("m"):
        multiplier = 1_000_000
        stripped = stripped[:-1]
    try:
        return round(float(stripped) * multiplier)
    except ValueError:
        return None


def _format_number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _format_strategy(decision: CompressionDecision) -> str:
    parts = [
        decision.candidate.video_codec,
        f"CRF {decision.candidate.crf}",
    ]
    if decision.source_fps is not None and decision.output_fps is not None:
        parts.append(
            f"{_format_number(decision.source_fps)}fps -> {_format_number(decision.output_fps)}fps"
        )
    elif decision.source_fps is not None:
        parts.append(f"{_format_number(decision.source_fps)}fps")

    if decision.source_audio_bit_rate is not None:
        parts.append(
            f"audio {_bitrate_arg(decision.source_audio_bit_rate)} -> "
            f"{decision.candidate.audio_bitrate}"
        )
    else:
        parts.append(f"audio {decision.candidate.audio_bitrate}")
    return ", ".join(parts)
