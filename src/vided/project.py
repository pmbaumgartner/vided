from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .ffmpeg import VideoInfo, probe_media

PROJECT_FILE = "project.json"
REDACTIONS_FILE = "redactions.json"
FRAMES_FILE = "work/frames/frames.json"
_MISSING = object()


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    input_dir: Path
    work_dir: Path
    frames_dir: Path
    output_dir: Path
    original: Path
    trimmed: Path
    project_json: Path
    redactions_json: Path
    frames_json: Path
    filtergraph: Path


def project_paths(
    project_root: Path,
    *,
    config: Mapping[str, Any] | None = None,
) -> ProjectPaths:
    project_root = project_root.resolve()
    input_dir = project_root / "input"
    work_dir = project_root / "work"
    frames_dir = work_dir / "frames"
    output_dir = project_root / "output"
    if config is None:
        config = _read_project_config_for_paths(project_root)
    original = project_root / str(config.get("original_path", "input/original.mp4"))
    trimmed = project_root / str(config.get("trimmed_path", "work/trimmed.mp4"))
    return ProjectPaths(
        root=project_root,
        input_dir=input_dir,
        work_dir=work_dir,
        frames_dir=frames_dir,
        output_dir=output_dir,
        original=original,
        trimmed=trimmed,
        project_json=project_root / PROJECT_FILE,
        redactions_json=project_root / REDACTIONS_FILE,
        frames_json=project_root / FRAMES_FILE,
        filtergraph=work_dir / "filtergraph.txt",
    )


def paths(root: Path) -> ProjectPaths:
    return project_paths(root)


def _read_project_config_for_paths(project_root: Path) -> dict[str, Any]:
    path = project_root / PROJECT_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def ensure_project_dirs(p: ProjectPaths) -> None:
    p.input_dir.mkdir(parents=True, exist_ok=True)
    p.work_dir.mkdir(parents=True, exist_ok=True)
    p.frames_dir.mkdir(parents=True, exist_ok=True)
    p.output_dir.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any = _MISSING) -> Any:
    if not path.exists():
        if default is not _MISSING:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_project(project_root: Path) -> dict[str, Any]:
    p = project_paths(project_root)
    return read_json(p.project_json)


def save_project(project_root: Path, data: dict[str, Any]) -> None:
    p = project_paths(project_root, config=data)
    write_json(p.project_json, data)


def create_project(
    source: Path,
    project_root: Path,
    *,
    frame_interval: float = 1.0,
    copy_input: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    source = source.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    if project_root.exists() and any(project_root.iterdir()) and not overwrite:
        raise FileExistsError(
            f"Project folder already exists and is not empty: {project_root}. "
            "Use --overwrite to reuse it."
        )

    p = project_paths(project_root)
    ensure_project_dirs(p)

    original_ext = source.suffix.lower() or ".mp4"
    original_path = p.input_dir / f"original{original_ext}"
    if copy_input:
        shutil.copy2(source, original_path)
    else:
        if original_path.exists() or original_path.is_symlink():
            original_path.unlink()
        original_path.symlink_to(source)

    src_info = probe_media(original_path)
    config = default_project_config(
        original_path=original_path,
        source_path=source,
        source_info=src_info,
        frame_interval=frame_interval,
    )
    write_json(p.project_json, config)
    write_json(
        p.redactions_json,
        default_redactions(
            src_info,
            trimmed_path=project_paths(project_root, config=config).trimmed,
        ),
    )
    return config


def default_project_config(
    *,
    original_path: Path,
    source_path: Path,
    source_info: VideoInfo,
    frame_interval: float,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(source_path),
        "original_path": str(original_path.relative_to(original_path.parents[1])),
        "trimmed_path": "work/trimmed.mp4",
        "video": source_info.as_dict(),
        "trim": {
            "detector": "audio",
            "mode": "hybrid",
            "margin": "0.2s",
            "smooth": "0.2s,0.1s",
            "audio_threshold": 0.04,
            "long_silence_min_seconds": 1.5,
            "silent_speed": 8.0,
            "mute_silent_audio": True,
            "silent_volume": 0.0,
            "speed_indicator": {
                "enabled": False,
                "corner": "top-right",
                "style": "dark",
                "min_display_seconds": 1.0,
            },
            "silero-vad": {
                "threshold": 0.5,
                "min_speech_duration_ms": 250,
                "min_silence_duration_ms": 300,
                "speech_pad_ms": 150,
                "merge_speech_gap_seconds": 0.25,
                "manual_keep_ranges": [],
            },
        },
        "frames": {
            "interval_seconds": frame_interval,
            "thumbnail_width": 640,
        },
        "render": {
            "video_codec": "libx264",
            "crf": 16,
            "preset": "medium",
            "pixel_format": "yuv420p",
            "audio_codec": "copy",
        },
        "redaction_defaults": {
            "buffer_pre_seconds": 0.5,
            "buffer_post_seconds": 0.5,
            "style": {
                "type": "blur",
                "filter": "boxblur",
                "luma_radius": 18,
                "luma_power": 3,
            },
        },
    }


def default_redactions(info: VideoInfo, *, trimmed_path: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "video": {
            "path": str(trimmed_path),
            "width": info.width,
            "height": info.height,
            "duration": info.duration,
        },
        "defaults": {
            "buffer_pre_seconds": 0.5,
            "buffer_post_seconds": 0.5,
            "style": {
                "type": "blur",
                "filter": "boxblur",
                "luma_radius": 18,
                "luma_power": 3,
            },
        },
        "redactions": [],
    }
