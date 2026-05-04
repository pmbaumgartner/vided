from __future__ import annotations

import array
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import ImageFont

from .errors import ValidationError
from .ffmpeg import VideoInfo, ensure_tool, probe_media, run_command
from .image_badge import DARK_BADGE_STYLE, LIGHT_BADGE_STYLE, render_text_badge
from .project import (
    default_redactions,
    load_project,
    project_paths,
    read_json,
    save_project,
    write_json,
)
from .vad import (
    activity_ranges_from_vad_report,
    load_or_create_vad_report,
    normalize_detector,
    vad_settings_from_trim_config,
)


@dataclass(frozen=True)
class TrimSegment:
    start: float
    end: float
    speed: float = 1.0
    mute_audio: bool = False

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class SpeedIndicatorSettings:
    enabled: bool = False
    corner: str = "top-right"
    style: str = "dark"
    min_display_seconds: float = 1.0


@dataclass(frozen=True)
class VadOptions:
    threshold: float | None = None
    min_speech_duration_ms: int | None = None
    min_silence_duration_ms: int | None = None
    speech_pad_ms: int | None = None
    merge_speech_gap_seconds: float | None = None


@dataclass(frozen=True)
class TrimOptions:
    detector: str | None = None
    mode: str | None = None
    margin: str | None = None
    smooth: str | None = None
    silent_speed: float | None = None
    mute_silent_audio: bool | None = None
    vad: VadOptions = field(default_factory=VadOptions)
    speed_indicator: bool | None = None
    speed_indicator_corner: str | None = None
    speed_indicator_style: str | None = None
    speed_indicator_min_display_seconds: float | None = None


@dataclass(frozen=True)
class TrimPlan:
    project_root: Path
    config: dict[str, Any]
    original: Path
    output: Path
    media_info: VideoInfo
    segments: list[TrimSegment]
    render_config: dict[str, Any]
    speed_indicator: SpeedIndicatorSettings
    speed_indicator_path: Path | None = None


@dataclass(frozen=True)
class OperationResult:
    path: Path
    command: list[str]
    dry_run: bool
    wrote_files: bool


_SPEED_INDICATOR_CORNERS = {"top-left", "top-right", "bottom-left", "bottom-right"}
_SPEED_INDICATOR_STYLES = {"dark", "light"}
_SPEED_INDICATOR_ICON = "\u25b6\u25b6"
_FONT_CANDIDATES = [
    "Arial Unicode.ttf",
    "DejaVuSans-Bold.ttf",
    "DejaVuSans.ttf",
    "NotoSansSymbols2-Regular.ttf",
    "NotoSansSymbols-Regular.ttf",
    "Segoe UI Symbol.ttf",
    "Apple Symbols.ttf",
    "Arial Bold.ttf",
    "Arial.ttf",
    "Helvetica.ttf",
    "Helvetica.ttc",
    "DejaVuSans-Bold.ttf",
    "DejaVuSans.ttf",
    "LiberationSans-Bold.ttf",
    "LiberationSans-Regular.ttf",
]


def _parse_seconds(value: float | int | str) -> float:
    if isinstance(value, int | float):
        return float(value)

    raw = value.strip().lower()
    if raw.endswith("ms"):
        return float(raw[:-2]) / 1000.0
    for suffix in ["seconds", "second", "secs", "sec", "s"]:
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    return float(raw)


def _parse_margin(value: str | None) -> tuple[float, float]:
    if not value:
        return (0.2, 0.2)
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) == 1:
        parsed = _parse_seconds(parts[0])
        return (parsed, parsed)
    if len(parts) == 2:
        return (_parse_seconds(parts[0]), _parse_seconds(parts[1]))
    raise ValueError("margin must be one or two comma-separated lengths")


def _parse_smooth(value: str | None) -> tuple[float, float]:
    if not value:
        return (0.2, 0.1)
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) == 1:
        parsed = _parse_seconds(parts[0])
        return (parsed, parsed)
    if len(parts) == 2:
        return (_parse_seconds(parts[0]), _parse_seconds(parts[1]))
    raise ValueError("smooth must be one or two comma-separated lengths")


def _format_number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _speed_label(speed: float) -> str:
    return f"{_format_number(speed)}x"


def _speed_indicator_display_label(label: str) -> str:
    return f"{_SPEED_INDICATOR_ICON} {label}"


def _safe_indicator_label(label: str) -> str:
    safe = "".join(char if char.isalnum() else "_" for char in label).strip("_")
    return safe or "speed"


def _load_badge_font(size: int) -> Any:
    for candidate in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _clamp_int(value: float, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(round(value))))


def _speed_indicator_inset(video_width: int, video_height: int) -> int:
    short_edge = max(1, min(video_width, video_height))
    return _clamp_int(short_edge * 0.035, 8, 48)


def _write_speed_indicator_badge(
    path: Path,
    *,
    label: str,
    style: str,
    video_width: int,
    video_height: int,
) -> None:
    if style not in _SPEED_INDICATOR_STYLES:
        raise ValueError("speed indicator style must be one of: dark, light")

    short_edge = max(1, min(video_width, video_height))
    font_size = _clamp_int(short_edge * 0.04, 14, 52)
    font = _load_badge_font(font_size)
    display_label = _speed_indicator_display_label(label)
    badge_style = DARK_BADGE_STYLE if style == "dark" else LIGHT_BADGE_STYLE
    image = render_text_badge(display_label, font, style=badge_style)

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")


def _speed_indicator_settings(
    trim_cfg: dict[str, Any],
    *,
    enabled: bool | None,
    corner: str | None,
    style: str | None,
    min_display_seconds: float | None,
) -> SpeedIndicatorSettings:
    cfg = trim_cfg.get("speed_indicator", {})
    if not isinstance(cfg, dict):
        cfg = {}

    resolved = SpeedIndicatorSettings(
        enabled=bool(cfg.get("enabled", False) if enabled is None else enabled),
        corner=str(corner or cfg.get("corner", "top-right")),
        style=str(style or cfg.get("style", "dark")),
        min_display_seconds=float(
            cfg.get("min_display_seconds", 1.0)
            if min_display_seconds is None
            else min_display_seconds
        ),
    )
    if resolved.corner not in _SPEED_INDICATOR_CORNERS:
        allowed = ", ".join(sorted(_SPEED_INDICATOR_CORNERS))
        raise ValueError(f"speed indicator corner must be one of: {allowed}")
    if resolved.style not in _SPEED_INDICATOR_STYLES:
        allowed = ", ".join(sorted(_SPEED_INDICATOR_STYLES))
        raise ValueError(f"speed indicator style must be one of: {allowed}")
    if resolved.min_display_seconds < 0:
        raise ValueError("speed indicator minimum display seconds must be non-negative")
    return resolved


def _indicator_overlay_xy(corner: str, *, inset: int) -> tuple[str, str]:
    inset_expr = str(inset)
    match corner:
        case "top-left":
            return inset_expr, inset_expr
        case "top-right":
            return f"main_w-overlay_w-{inset_expr}", inset_expr
        case "bottom-left":
            return inset_expr, f"main_h-overlay_h-{inset_expr}"
        case "bottom-right":
            return f"main_w-overlay_w-{inset_expr}", f"main_h-overlay_h-{inset_expr}"
    raise ValueError(f"unknown speed indicator corner: {corner}")


def _segment_shows_speed_indicator(segment: TrimSegment, *, min_display_seconds: float) -> bool:
    return segment.speed > 1.0 and segment.duration / segment.speed >= min_display_seconds


def _trim_timebase(media_info: VideoInfo) -> float:
    fps = media_info.fps
    if fps is None or fps <= 0:
        return 30.0

    rounded = round(float(fps), 2)
    for rate in [60000 / 1001, 30000 / 1001, 24000 / 1001]:
        if rounded == round(rate, 2):
            return rate
    return rounded


def _parse_threshold(value: str) -> float:
    raw = value.strip()
    if raw.endswith("%"):
        threshold = float(raw[:-1]) / 100.0
    elif raw.endswith("dB"):
        threshold = 10 ** (float(raw[:-2]) / 20.0)
    else:
        threshold = float(raw)

    if threshold < 0 or threshold > 1:
        raise ValueError(f"threshold must be between 0 and 1: {value}")
    return threshold


def _has_vad_overrides(
    *,
    vad_threshold: float | None,
    vad_min_speech_duration_ms: int | None,
    vad_min_silence_duration_ms: int | None,
    vad_speech_pad_ms: int | None,
    vad_merge_speech_gap_seconds: float | None,
) -> bool:
    return any(
        value is not None
        for value in [
            vad_threshold,
            vad_min_speech_duration_ms,
            vad_min_silence_duration_ms,
            vad_speech_pad_ms,
            vad_merge_speech_gap_seconds,
        ]
    )


def _pcm_audio_levels(
    pcm: bytes,
    *,
    sample_rate: int,
    channels: int,
    timebase_fps: float,
) -> list[float]:
    if sample_rate <= 0 or channels <= 0 or timebase_fps <= 0:
        return []

    sample_data = array.array("h")
    sample_data.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if sys.byteorder != "little":
        sample_data.byteswap()

    total_frames = len(sample_data) // channels
    if total_frames <= 0:
        return []

    exact_size = sample_rate / timebase_fps
    needed_frames = max(1, math.ceil(exact_size))
    accumulated_error = 0.0
    frame_start = 0
    levels: list[float] = []

    while total_frames - frame_start >= needed_frames:
        size_with_error = exact_size + accumulated_error
        current_size = max(1, int(math.floor(size_with_error + 0.5)))
        accumulated_error = size_with_error - current_size

        frame_end = min(total_frames, frame_start + current_size)
        sample_start = frame_start * channels
        sample_end = frame_end * channels
        max_abs = 0
        for sample_idx in range(sample_start, sample_end):
            sample = sample_data[sample_idx]
            max_abs = max(max_abs, min(abs(sample), 32767))
        levels.append(max_abs / 32767.0)
        frame_start = frame_end

    return levels


def _read_audio_levels(source: Path, *, media_info: VideoInfo, timebase_fps: float) -> list[float]:
    if not media_info.has_audio:
        return []
    if not media_info.audio_sample_rate or not media_info.audio_channels:
        raise ValueError(f"Audio stream metadata is incomplete for {source}")

    result = run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            "-f",
            "s16le",
            "-c:a",
            "pcm_s16le",
            "-",
        ],
        output="bytes",
    )
    pcm = result.stdout
    return _pcm_audio_levels(
        pcm,
        sample_rate=media_info.audio_sample_rate,
        channels=media_info.audio_channels,
        timebase_fps=timebase_fps,
    )


def _seconds_to_ticks(seconds: float, timebase_fps: float) -> int:
    return int(seconds * timebase_fps)


def _apply_margin(active: list[bool], start_margin: int, end_margin: int) -> list[bool]:
    output = active.copy()
    starts: list[int] = []
    ends: list[int] = []

    for idx in range(1, len(active)):
        if active[idx] == active[idx - 1]:
            continue
        if active[idx]:
            starts.append(idx)
        else:
            ends.append(idx)

    if start_margin > 0:
        for idx in starts:
            for margin_idx in range(max(idx - start_margin, 0), idx):
                output[margin_idx] = True
    elif start_margin < 0:
        for idx in starts:
            for margin_idx in range(idx, min(idx - start_margin, len(output))):
                output[margin_idx] = False

    if end_margin > 0:
        for idx in ends:
            for margin_idx in range(idx, min(idx + end_margin, len(output))):
                output[margin_idx] = True
    elif end_margin < 0:
        for idx in ends:
            for margin_idx in range(max(idx + end_margin, 0), idx):
                output[margin_idx] = False

    return output


def _smooth_activity(active: list[bool], mincut: int, minclip: int) -> list[bool]:
    output = active.copy()
    previous: list[bool] | None = None

    while previous != output:
        previous = output.copy()
        next_output = previous.copy()

        start_idx = 0
        in_run = False
        for idx, item in enumerate(previous):
            if item:
                if not in_run:
                    start_idx = idx
                    in_run = True
                if idx == len(previous) - 1 and idx - start_idx < minclip:
                    for run_idx in range(start_idx, len(previous)):
                        next_output[run_idx] = False
            elif in_run:
                if idx - start_idx < minclip:
                    for run_idx in range(start_idx, idx):
                        next_output[run_idx] = False
                in_run = False

        start_idx = 0
        in_run = False
        for idx, item in enumerate(previous):
            if not item:
                if not in_run:
                    start_idx = idx
                    in_run = True
                if idx == len(previous) - 1 and idx - start_idx < mincut:
                    for run_idx in range(start_idx, len(previous)):
                        next_output[run_idx] = True
            elif in_run:
                if idx - start_idx < mincut:
                    for run_idx in range(start_idx, idx):
                        next_output[run_idx] = True
                in_run = False

        output = next_output

    return output


def _activity_ranges(
    source: Path,
    *,
    media_info: VideoInfo,
    duration: float,
    threshold: float,
    margin: tuple[float, float],
    smooth: tuple[float, float],
    timebase_fps: float,
) -> list[tuple[float, float, bool]]:
    levels = _read_audio_levels(source, media_info=media_info, timebase_fps=timebase_fps)
    if not levels or duration <= 0:
        return []

    active = [level >= threshold for level in levels]
    active = _apply_margin(
        active,
        _seconds_to_ticks(margin[0], timebase_fps),
        _seconds_to_ticks(margin[1], timebase_fps),
    )
    active = _smooth_activity(
        active,
        _seconds_to_ticks(smooth[0], timebase_fps),
        _seconds_to_ticks(smooth[1], timebase_fps),
    )

    ranges: list[tuple[float, float, bool]] = []
    start_idx = 0
    current_active = active[0]
    for idx in range(1, len(active)):
        if active[idx] == current_active:
            continue
        ranges.append((start_idx / timebase_fps, min(idx / timebase_fps, duration), current_active))
        start_idx = idx
        current_active = active[idx]
    ranges.append((start_idx / timebase_fps, duration, current_active))
    return ranges


def _trim_segments(
    source: Path,
    *,
    media_info: VideoInfo,
    duration: float,
    mode: str,
    threshold: float,
    margin: tuple[float, float],
    smooth: tuple[float, float],
    timebase_fps: float,
    silent_speed: float,
    mute_silent_audio: bool,
    long_silence_min_seconds: float,
) -> list[TrimSegment]:
    if mode == "keep":
        return [TrimSegment(start=0.0, end=duration)]

    ranges = _activity_ranges(
        source,
        media_info=media_info,
        duration=duration,
        threshold=threshold,
        margin=margin,
        smooth=smooth,
        timebase_fps=timebase_fps,
    )
    return _trim_segments_from_activity_ranges(
        ranges,
        duration=duration,
        mode=mode,
        silent_speed=silent_speed,
        mute_silent_audio=mute_silent_audio,
        long_silence_min_seconds=long_silence_min_seconds,
    )


def _trim_segments_from_activity_ranges(
    ranges: list[tuple[float, float, bool]],
    *,
    duration: float,
    mode: str,
    silent_speed: float,
    mute_silent_audio: bool,
    long_silence_min_seconds: float,
) -> list[TrimSegment]:
    if not ranges:
        return [TrimSegment(start=0.0, end=duration)]

    segments: list[TrimSegment] = []
    for start, end, active in ranges:
        duration_seconds = end - start
        if duration_seconds <= 0:
            continue
        if active:
            segments.append(TrimSegment(start=start, end=end))
        elif mode == "speed" or (mode == "hybrid" and duration_seconds >= long_silence_min_seconds):
            segments.append(
                TrimSegment(
                    start=start,
                    end=end,
                    speed=silent_speed,
                    mute_audio=mute_silent_audio,
                )
            )
        elif mode == "cut" or mode == "hybrid":
            continue

    return segments or [TrimSegment(start=0.0, end=duration)]


def _atempo_filters(speed: float) -> list[str]:
    if speed <= 0:
        raise ValueError("speed must be greater than 0")
    if abs(speed - 1.0) < 0.000001:
        return []

    factors: list[float] = []
    remaining = speed
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return [f"atempo={_format_number(factor)}" for factor in factors]


def _build_ffmpeg_filtergraph(
    segments: list[TrimSegment],
    *,
    has_audio: bool,
    speed_indicator_input: int | None = None,
    speed_indicator_corner: str = "top-right",
    speed_indicator_inset: int = 20,
    speed_indicator_min_display_seconds: float = 1.0,
) -> str:
    parts: list[str] = []
    concat_inputs: list[str] = []
    indicator_xy = _indicator_overlay_xy(speed_indicator_corner, inset=speed_indicator_inset)

    for idx, segment in enumerate(segments):
        speed = _format_number(segment.speed)
        needs_indicator = speed_indicator_input is not None and _segment_shows_speed_indicator(
            segment,
            min_display_seconds=speed_indicator_min_display_seconds,
        )
        trim_label = f"v{idx}base" if needs_indicator else f"v{idx}"
        parts.append(
            "[0:v]"
            f"trim=start={_format_number(segment.start)}:end={_format_number(segment.end)},"
            f"setpts=(PTS-STARTPTS)/{speed}"
            f"[{trim_label}]"
        )
        if needs_indicator:
            x_expr, y_expr = indicator_xy
            parts.append(
                f"[{trim_label}][{speed_indicator_input}:v]"
                f"overlay=x={x_expr}:y={y_expr}:shortest=1:eof_action=repeat:repeatlast=1"
                f"[v{idx}]"
            )
        concat_inputs.append(f"[v{idx}]")

        if has_audio:
            audio_filters = [
                f"atrim=start={_format_number(segment.start)}:end={_format_number(segment.end)}",
                "asetpts=PTS-STARTPTS",
            ]
            audio_filters.extend(_atempo_filters(segment.speed))
            if segment.mute_audio:
                audio_filters.append("volume=0")
            parts.append(f"[0:a]{','.join(audio_filters)}[a{idx}]")
            concat_inputs.append(f"[a{idx}]")

    concat = "".join(concat_inputs)
    if has_audio:
        concat += f"concat=n={len(segments)}:v=1:a=1[vout][aout]"
    else:
        concat += f"concat=n={len(segments)}:v=1:a=0[vout]"
    parts.append(concat)
    return ";".join(parts)


def plan_trim(
    project_root: Path,
    *,
    options: TrimOptions | None = None,
    allow_vad_detection: bool = False,
) -> TrimPlan:
    options = options or TrimOptions()
    cfg = load_project(project_root)
    p = project_paths(project_root, config=cfg)

    original = p.original
    trimmed = p.trimmed
    trim_cfg_raw = cfg.get("trim", {})
    trim_cfg: dict[str, Any] = trim_cfg_raw if isinstance(trim_cfg_raw, dict) else {}
    media_info = probe_media(original)

    detector = normalize_detector(
        options.detector or trim_cfg.get("detector") or trim_cfg.get("engine") or "audio"
    )
    mode = options.mode or trim_cfg.get("mode", "hybrid")
    margin = options.margin or trim_cfg.get("margin", "0.2s")
    smooth = options.smooth or trim_cfg.get("smooth", "0.2s,0.1s")
    silent_speed = float(
        options.silent_speed
        if options.silent_speed is not None
        else trim_cfg.get("silent_speed", 8.0)
    )
    mute_silent_audio = bool(
        trim_cfg.get("mute_silent_audio", True)
        if options.mute_silent_audio is None
        else options.mute_silent_audio
    )
    long_silence_min_seconds = float(trim_cfg.get("long_silence_min_seconds", 1.5))
    speed_indicator_settings = _speed_indicator_settings(
        trim_cfg,
        enabled=options.speed_indicator,
        corner=options.speed_indicator_corner,
        style=options.speed_indicator_style,
        min_display_seconds=options.speed_indicator_min_display_seconds,
    )

    if mode not in {"hybrid", "speed", "cut", "keep"}:
        raise ValidationError("trim mode must be one of: hybrid, speed, cut, keep")

    if mode == "keep":
        segments = [TrimSegment(start=0.0, end=media_info.duration)]
    elif detector == "audio":
        audio_threshold = _parse_threshold(str(trim_cfg.get("audio_threshold", 0.04)))
        timebase_fps = _trim_timebase(media_info)
        segments = _trim_segments(
            original,
            media_info=media_info,
            duration=media_info.duration,
            mode=mode,
            threshold=audio_threshold,
            margin=_parse_margin(margin),
            smooth=_parse_smooth(smooth),
            timebase_fps=timebase_fps,
            silent_speed=silent_speed,
            mute_silent_audio=mute_silent_audio,
            long_silence_min_seconds=long_silence_min_seconds,
        )
    else:
        vad_settings = vad_settings_from_trim_config(
            trim_cfg,
            threshold=options.vad.threshold,
            min_speech_duration_ms=options.vad.min_speech_duration_ms,
            min_silence_duration_ms=options.vad.min_silence_duration_ms,
            speech_pad_ms=options.vad.speech_pad_ms,
            merge_speech_gap_seconds=options.vad.merge_speech_gap_seconds,
        )
        report = load_or_create_vad_report(
            project_root,
            source=original,
            media_info=media_info,
            settings=vad_settings,
            allow_detection=allow_vad_detection,
            force=_has_vad_overrides(
                vad_threshold=options.vad.threshold,
                vad_min_speech_duration_ms=options.vad.min_speech_duration_ms,
                vad_min_silence_duration_ms=options.vad.min_silence_duration_ms,
                vad_speech_pad_ms=options.vad.speech_pad_ms,
                vad_merge_speech_gap_seconds=options.vad.merge_speech_gap_seconds,
            ),
        )
        ranges = activity_ranges_from_vad_report(report, duration=media_info.duration)
        segments = _trim_segments_from_activity_ranges(
            ranges,
            duration=media_info.duration,
            mode=mode,
            silent_speed=silent_speed,
            mute_silent_audio=mute_silent_audio,
            long_silence_min_seconds=long_silence_min_seconds,
        )

    indicator_path: Path | None = None
    if speed_indicator_settings.enabled and any(
        _segment_shows_speed_indicator(
            segment,
            min_display_seconds=speed_indicator_settings.min_display_seconds,
        )
        for segment in segments
    ):
        label = _speed_label(silent_speed)
        indicator_path = (
            p.work_dir
            / f"speed-indicator-{_safe_indicator_label(label)}-{speed_indicator_settings.style}.png"
        )

    render_cfg_raw = cfg.get("render", {})
    render_cfg: dict[str, Any] = render_cfg_raw if isinstance(render_cfg_raw, dict) else {}
    return TrimPlan(
        project_root=p.root,
        config=cfg,
        original=original,
        output=trimmed,
        media_info=media_info,
        segments=segments,
        render_config=render_cfg,
        speed_indicator=speed_indicator_settings,
        speed_indicator_path=indicator_path,
    )


def build_trim_command(plan: TrimPlan) -> list[str]:
    graph = _build_ffmpeg_filtergraph(
        plan.segments,
        has_audio=plan.media_info.has_audio,
        speed_indicator_input=1 if plan.speed_indicator_path else None,
        speed_indicator_corner=plan.speed_indicator.corner,
        speed_indicator_inset=_speed_indicator_inset(
            plan.media_info.width,
            plan.media_info.height,
        ),
        speed_indicator_min_display_seconds=plan.speed_indicator.min_display_seconds,
    )

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(plan.original),
    ]
    if plan.speed_indicator_path is not None:
        cmd.extend(["-loop", "1", "-i", str(plan.speed_indicator_path)])
    cmd.extend(
        [
            "-filter_complex",
            graph,
            "-map",
            "[vout]",
        ]
    )
    if plan.media_info.has_audio:
        cmd.extend(["-map", "[aout]"])
    cmd.extend(["-sn", "-dn", "-shortest"])

    render_cfg = plan.render_config
    cmd.extend(
        [
            "-c:v",
            str(render_cfg.get("video_codec", "libx264")),
            "-crf",
            str(render_cfg.get("crf", 16)),
            "-preset",
            str(render_cfg.get("preset", "medium")),
            "-pix_fmt",
            str(render_cfg.get("pixel_format", "yuv420p")),
        ]
    )
    if plan.media_info.has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", str(render_cfg.get("audio_bitrate", "192k"))])
    cmd.extend(["-movflags", "+faststart", str(plan.output)])
    return cmd


def _write_trim_metadata(plan: TrimPlan) -> None:
    info = probe_media(plan.output)
    cfg = dict(plan.config)
    cfg["trimmed_video"] = info.as_dict()
    save_project(plan.project_root, cfg)

    p = project_paths(plan.project_root, config=cfg)
    redactions = read_json(p.redactions_json, default={})
    if not redactions or redactions.get("redactions") == []:
        write_json(p.redactions_json, default_redactions(info, trimmed_path=plan.output))
    else:
        redactions.setdefault("video", {})
        redactions["video"].update(
            {
                "path": str(plan.output),
                "width": info.width,
                "height": info.height,
                "duration": info.duration,
            }
        )
        write_json(p.redactions_json, redactions)


def _write_trim_assets(plan: TrimPlan) -> None:
    if plan.speed_indicator_path is None:
        return
    label = _speed_label(max((segment.speed for segment in plan.segments), default=1.0))
    _write_speed_indicator_badge(
        plan.speed_indicator_path,
        label=label,
        style=plan.speed_indicator.style,
        video_width=plan.media_info.width,
        video_height=plan.media_info.height,
    )


def run_trim_plan(
    plan: TrimPlan,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
) -> OperationResult:
    if plan.output.exists() and not overwrite and not dry_run:
        raise FileExistsError(
            f"Trimmed file already exists: {plan.output}. Use --overwrite to replace it."
        )

    ensure_tool("ffmpeg")
    cmd = build_trim_command(plan)

    if not dry_run:
        plan.output.parent.mkdir(parents=True, exist_ok=True)
        if overwrite and plan.output.exists():
            plan.output.unlink()
        _write_trim_assets(plan)

    run_command(cmd, dry_run=dry_run)

    if not dry_run:
        _write_trim_metadata(plan)
    return OperationResult(path=plan.output, command=cmd, dry_run=dry_run, wrote_files=not dry_run)
