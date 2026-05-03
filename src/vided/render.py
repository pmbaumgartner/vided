from __future__ import annotations

from pathlib import Path
from typing import Any

from .ffmpeg import ensure_tool, run_command
from .filtergraph import build_debug_filtergraph, build_final_filtergraph, write_filtergraph
from .project import load_project, project_paths
from .redactions import load_redactions, render_redactions


def render_project(
    project_root: Path,
    *,
    debug: bool = False,
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

    redaction_data = load_redactions(project_root)
    redactions = render_redactions(redaction_data)
    graph = build_debug_filtergraph(redactions) if debug else build_final_filtergraph(redactions)
    filtergraph_path = p.work_dir / ("filtergraph.debug.txt" if debug else "filtergraph.txt")
    if not dry_run:
        write_filtergraph(filtergraph_path, graph)

    render_cfg: dict[str, Any] = cfg.get("render", {})
    video_codec = str(render_cfg.get("video_codec", "libx264"))
    crf = str(render_cfg.get("crf", 16))
    preset = str(render_cfg.get("preset", "medium"))
    pix_fmt = str(render_cfg.get("pixel_format", "yuv420p"))
    audio_codec = str(render_cfg.get("audio_codec", "copy"))

    if output is None:
        output = p.output_dir / ("debug-preview.mp4" if debug else "final.mp4")
    elif not output.is_absolute():
        output = p.root / output
    if not dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y" if overwrite else "-n",
        "-i",
        str(trimmed),
        "-filter_complex",
        graph,
        "-map",
        "[vout]",
        "-map",
        "0:a?",
        "-c:v",
        video_codec,
    ]

    if video_codec in {"libx264", "libx265", "libsvtav1"}:
        cmd.extend(["-crf", crf, "-preset", preset])
    if pix_fmt:
        cmd.extend(["-pix_fmt", pix_fmt])

    if audio_codec == "copy":
        cmd.extend(["-c:a", "copy"])
    elif audio_codec == "aac":
        cmd.extend(["-c:a", "aac", "-b:a", str(render_cfg.get("audio_bitrate", "192k"))])
    else:
        cmd.extend(["-c:a", audio_codec])

    cmd.extend(["-movflags", "+faststart", str(output)])
    run_command(cmd, dry_run=dry_run)
    return output
