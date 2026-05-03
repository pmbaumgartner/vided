from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ffmpeg import VideoInfo, probe_media

PROJECT_FILE = "project.json"
REDACTIONS_FILE = "redactions.json"
FRAMES_FILE = "work/frames/frames.json"


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


def paths(root: Path) -> ProjectPaths:
    root = root.resolve()
    input_dir = root / "input"
    work_dir = root / "work"
    frames_dir = work_dir / "frames"
    output_dir = root / "output"
    return ProjectPaths(
        root=root,
        input_dir=input_dir,
        work_dir=work_dir,
        frames_dir=frames_dir,
        output_dir=output_dir,
        original=input_dir / "original.mp4",
        trimmed=work_dir / "trimmed.mp4",
        project_json=root / PROJECT_FILE,
        redactions_json=root / REDACTIONS_FILE,
        frames_json=root / FRAMES_FILE,
        filtergraph=work_dir / "filtergraph.txt",
    )


def ensure_project_dirs(p: ProjectPaths) -> None:
    p.input_dir.mkdir(parents=True, exist_ok=True)
    p.work_dir.mkdir(parents=True, exist_ok=True)
    p.frames_dir.mkdir(parents=True, exist_ok=True)
    p.output_dir.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_project(root: Path) -> dict[str, Any]:
    p = paths(root)
    return read_json(p.project_json)


def save_project(root: Path, data: dict[str, Any]) -> None:
    p = paths(root)
    write_json(p.project_json, data)


def create_project(
    source: Path,
    root: Path,
    *,
    frame_interval: float = 1.0,
    copy_input: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    source = source.expanduser().resolve()
    root = root.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    if root.exists() and any(root.iterdir()) and not overwrite:
        raise FileExistsError(
            f"Project folder already exists and is not empty: {root}. Use --overwrite to reuse it."
        )

    p = paths(root)
    ensure_project_dirs(p)

    original_ext = source.suffix.lower() or ".mp4"
    original_path = p.input_dir / f"original{original_ext}"
    if copy_input:
        shutil.copy2(source, original_path)
    else:
        if original_path.exists() or original_path.is_symlink():
            original_path.unlink()
        original_path.symlink_to(source)

    # paths() assumes .mp4, but keep the actual extension in project.json.
    src_info = probe_media(original_path)
    config = default_project_config(
        original_path=original_path,
        source_path=source,
        source_info=src_info,
        frame_interval=frame_interval,
    )
    write_json(p.project_json, config)
    write_json(p.redactions_json, default_redactions(src_info, trimmed_path=p.trimmed))
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
            "silero": {
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
