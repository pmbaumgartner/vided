from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audio_presets import audio_filter_for_preset, normalize_audio_preset
from .errors import ProjectError, ValidationError
from .ffmpeg import VideoInfo, ensure_tool, probe_media, run_command
from .project import load_project, project_paths
from .trimmer import build_trim_timeline, plan_trim

DEFAULT_PREVIEW_DURATION = 15.0


@dataclass(frozen=True)
class TimelineSegment:
    source_start: float
    source_end: float
    output_start: float
    output_end: float
    speed: float
    mute_audio: bool

    @property
    def output_duration(self) -> float:
        return max(0.0, self.output_end - self.output_start)


@dataclass(frozen=True)
class AudioPreviewWindow:
    start: float
    duration: float
    automatic: bool
    fallback: bool = False


def render_audio_preview(
    project_root: Path,
    *,
    audio_preset: str,
    start: float | None = None,
    duration: float | None = None,
    output: Path | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> Path:
    ensure_tool("ffmpeg")
    cfg = load_project(project_root)
    p = project_paths(project_root, config=cfg)
    trimmed = p.trimmed
    if not trimmed.exists():
        raise FileNotFoundError(f"Trimmed video not found: {trimmed}. Run `vided trim` first.")

    media_info = probe_media(trimmed)
    preset = normalize_audio_preset(audio_preset)
    audio_filter = audio_filter_for_preset(preset)
    window = select_audio_preview_window(
        project_root,
        cfg=cfg,
        media_info=media_info,
        start=start,
        duration=duration,
    )

    if output is None:
        output = p.output_dir / f"audio-preview-{preset}-{_seconds_label(window.start)}.mp4"
    elif not output.is_absolute():
        output = p.root / output
    if not dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y" if overwrite else "-n",
        "-ss",
        _format_seconds(window.start),
        "-i",
        str(trimmed),
        "-t",
        _format_seconds(window.duration),
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
    ]

    if audio_filter is None:
        cmd.extend(["-map", "0:a?", "-c:a", "copy"])
    elif media_info.has_audio:
        render_cfg = cfg.get("render", {})
        render_cfg = render_cfg if isinstance(render_cfg, dict) else {}
        cmd.extend(
            [
                "-map",
                "0:a:0",
                "-af",
                audio_filter,
                "-c:a",
                "aac",
                "-b:a",
                str(render_cfg.get("audio_bitrate", "192k")),
            ]
        )
    else:
        print(
            "warning: audio preset requested but trimmed video has no audio stream", file=sys.stderr
        )

    cmd.extend(["-sn", "-dn", "-map_chapters", "-1", "-movflags", "+faststart", str(output)])
    run_command(cmd, dry_run=dry_run)
    return output


def select_audio_preview_window(
    project_root: Path,
    *,
    cfg: dict[str, Any] | None = None,
    media_info: VideoInfo | None = None,
    start: float | None = None,
    duration: float | None = None,
) -> AudioPreviewWindow:
    cfg = load_project(project_root) if cfg is None else cfg
    p = project_paths(project_root, config=cfg)
    media_info = probe_media(p.trimmed) if media_info is None else media_info
    requested_duration = _preview_duration(duration)
    media_duration = max(0.0, float(media_info.duration))

    if start is not None:
        start_seconds = _preview_start(start)
        return AudioPreviewWindow(
            start=start_seconds,
            duration=_cap_duration(requested_duration, start_seconds, media_duration),
            automatic=False,
        )

    segment = _longest_preview_segment(project_root, cfg)
    if segment is None:
        print(
            "warning: no normal-speed audio segment found; previewing from the start",
            file=sys.stderr,
        )
        return AudioPreviewWindow(
            start=0.0,
            duration=_cap_duration(requested_duration, 0.0, media_duration),
            automatic=True,
            fallback=True,
        )

    return AudioPreviewWindow(
        start=segment.output_start,
        duration=_cap_duration(
            min(requested_duration, segment.output_duration),
            segment.output_start,
            media_duration,
        ),
        automatic=True,
    )


def _longest_preview_segment(project_root: Path, cfg: dict[str, Any]) -> TimelineSegment | None:
    candidates = [
        item
        for item in _trim_timeline_segments(project_root, cfg)
        if item.output_duration > 0 and not item.mute_audio and abs(item.speed - 1.0) < 0.000001
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.output_duration, -item.output_start))


def _trim_timeline_segments(project_root: Path, cfg: dict[str, Any]) -> list[TimelineSegment]:
    timeline = cfg.get("trim_timeline")
    if isinstance(timeline, dict):
        segments = _parse_timeline_segments(timeline.get("segments", []))
        if segments:
            return segments

    try:
        plan = plan_trim(project_root, allow_vad_detection=False)
    except ProjectError as exc:
        raise ProjectError(
            f"Trim timeline metadata not found or stale. Run `vided trim {project_root}` first."
        ) from exc
    return _parse_timeline_segments(build_trim_timeline(plan.segments)["segments"])


def _parse_timeline_segments(raw: Any) -> list[TimelineSegment]:
    if not isinstance(raw, list):
        return []

    segments: list[TimelineSegment] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            segment = TimelineSegment(
                source_start=float(item["source_start"]),
                source_end=float(item["source_end"]),
                output_start=float(item["output_start"]),
                output_end=float(item["output_end"]),
                speed=float(item.get("speed", 1.0)),
                mute_audio=bool(item.get("mute_audio", False)),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if segment.output_end > segment.output_start:
            segments.append(segment)
    return segments


def _preview_duration(value: float | None) -> float:
    duration = DEFAULT_PREVIEW_DURATION if value is None else float(value)
    if duration <= 0:
        raise ValidationError("audio preview duration must be greater than 0")
    return duration


def _preview_start(value: float) -> float:
    start = float(value)
    if start < 0:
        raise ValidationError("audio preview start must be greater than or equal to 0")
    return start


def _cap_duration(duration: float, start: float, media_duration: float) -> float:
    if media_duration <= 0:
        return duration
    if start >= media_duration:
        raise ValidationError("audio preview start must be before the end of the trimmed video")
    return min(duration, max(0.0, media_duration - start))


def _format_seconds(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _seconds_label(value: float) -> str:
    return _format_seconds(value).replace(".", "p") + "s"
