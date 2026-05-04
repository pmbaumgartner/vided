from __future__ import annotations

from dataclasses import dataclass
import shutil
from pathlib import Path
from typing import Any

from .ffmpeg import ensure_tool, probe_media, run_command
from .project import load_project, project_paths, save_project, write_json


@dataclass(frozen=True)
class FrameExtractionOptions:
    interval_seconds: float
    thumbnail_width: int


def resolve_frame_extraction_options(
    cfg: dict[str, Any],
    *,
    interval_seconds: float | None = None,
    thumbnail_width: int | None = None,
    error_prefix: str = "",
) -> FrameExtractionOptions:
    frame_cfg: dict[str, Any] = cfg.get("frames", {})
    resolved_interval = float(
        frame_cfg.get("interval_seconds", 1.0) if interval_seconds is None else interval_seconds
    )
    resolved_width = int(
        frame_cfg.get("thumbnail_width", 640) if thumbnail_width is None else thumbnail_width
    )
    if resolved_interval <= 0:
        raise ValueError(f"{error_prefix}interval_seconds must be greater than 0")
    if resolved_width <= 0:
        raise ValueError(f"{error_prefix}thumbnail_width must be greater than 0")
    return FrameExtractionOptions(
        interval_seconds=resolved_interval,
        thumbnail_width=resolved_width,
    )


def build_frame_extraction_command(
    source: Path,
    frame_pattern: Path,
    *,
    options: FrameExtractionOptions,
    overwrite: bool,
) -> list[str]:
    fps = 1.0 / options.interval_seconds
    vf = f"fps={fps:.8f},scale={options.thumbnail_width}:-2"
    return [
        "ffmpeg",
        "-hide_banner",
        "-y" if overwrite else "-n",
        "-i",
        str(source),
        "-vf",
        vf,
        "-q:v",
        "2",
        str(frame_pattern),
    ]


def generate_frames(
    project_root: Path,
    *,
    interval_seconds: float | None = None,
    thumbnail_width: int | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> Path:
    ensure_tool("ffmpeg")
    cfg = load_project(project_root)
    p = project_paths(project_root, config=cfg)
    trimmed = p.trimmed
    if not trimmed.exists():
        raise FileNotFoundError(f"Trimmed video not found: {trimmed}. Run `vided trim` first.")

    options = resolve_frame_extraction_options(
        cfg,
        interval_seconds=interval_seconds,
        thumbnail_width=thumbnail_width,
    )

    if p.frames_dir.exists() and overwrite and not dry_run:
        shutil.rmtree(p.frames_dir)
    if not dry_run:
        p.frames_dir.mkdir(parents=True, exist_ok=True)

    existing = list(p.frames_dir.glob("frame_*.jpg")) if p.frames_dir.exists() else []
    if existing and not overwrite and not dry_run:
        raise FileExistsError(
            f"Frames already exist in {p.frames_dir}. Use --overwrite to regenerate them."
        )

    frame_pattern = p.frames_dir / "frame_%06d.jpg"
    cmd = build_frame_extraction_command(
        trimmed,
        frame_pattern,
        options=options,
        overwrite=overwrite,
    )
    run_command(cmd, dry_run=dry_run)

    if dry_run:
        return p.frames_json

    info = probe_media(trimmed)
    frames = []
    for idx, file in enumerate(sorted(p.frames_dir.glob("frame_*.jpg"))):
        t = min(idx * options.interval_seconds, max(info.duration, 0.0))
        frames.append(
            {
                "index": idx,
                "time": round(t, 6),
                "image": f"frames/{file.name}",
            }
        )

    frames_json = {
        "schema_version": 1,
        "video": {
            "path": str(trimmed),
            "width": info.width,
            "height": info.height,
            "duration": info.duration,
        },
        "interval_seconds": options.interval_seconds,
        "thumbnail_width": options.thumbnail_width,
        "frames": frames,
    }
    write_json(p.frames_json, frames_json)

    cfg.setdefault("frames", {})
    cfg["frames"].update(
        {
            "interval_seconds": options.interval_seconds,
            "thumbnail_width": options.thumbnail_width,
            "last_generated_count": len(frames),
        }
    )
    cfg["trimmed_video"] = info.as_dict()
    save_project(project_root, cfg)
    return p.frames_json
