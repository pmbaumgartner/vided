from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .ffmpeg import ensure_tool, probe_media, run_command
from .project import load_project, paths, save_project, write_json


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
    p = paths(project_root)
    trimmed = p.root / cfg.get("trimmed_path", "work/trimmed.mp4")
    if not trimmed.exists():
        raise FileNotFoundError(f"Trimmed video not found: {trimmed}. Run `vided trim` first.")

    frame_cfg: dict[str, Any] = cfg.get("frames", {})
    interval_seconds = float(interval_seconds or frame_cfg.get("interval_seconds", 1.0))
    thumbnail_width = int(thumbnail_width or frame_cfg.get("thumbnail_width", 640))
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than 0")
    if thumbnail_width <= 0:
        raise ValueError("thumbnail_width must be greater than 0")

    if p.frames_dir.exists() and overwrite and not dry_run:
        shutil.rmtree(p.frames_dir)
    p.frames_dir.mkdir(parents=True, exist_ok=True)

    existing = list(p.frames_dir.glob("frame_*.jpg"))
    if existing and not overwrite and not dry_run:
        raise FileExistsError(
            f"Frames already exist in {p.frames_dir}. Use --overwrite to regenerate them."
        )

    fps = 1.0 / interval_seconds
    frame_pattern = p.frames_dir / "frame_%06d.jpg"
    vf = f"fps={fps:.8f},scale={thumbnail_width}:-2"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y" if overwrite else "-n",
        "-i",
        str(trimmed),
        "-vf",
        vf,
        "-q:v",
        "2",
        str(frame_pattern),
    ]
    run_command(cmd, dry_run=dry_run)

    if dry_run:
        return p.frames_json

    info = probe_media(trimmed)
    frames = []
    for idx, file in enumerate(sorted(p.frames_dir.glob("frame_*.jpg"))):
        t = min(idx * interval_seconds, max(info.duration, 0.0))
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
        "interval_seconds": interval_seconds,
        "thumbnail_width": thumbnail_width,
        "frames": frames,
    }
    write_json(p.frames_json, frames_json)

    cfg.setdefault("frames", {})
    cfg["frames"].update(
        {
            "interval_seconds": interval_seconds,
            "thumbnail_width": thumbnail_width,
            "last_generated_count": len(frames),
        }
    )
    cfg["trimmed_video"] = info.as_dict()
    save_project(project_root, cfg)
    return p.frames_json
