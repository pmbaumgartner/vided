from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from .audio_presets import audio_filter_for_preset
from .ffmpeg import ensure_tool, probe_media, run_command
from .filtergraph import build_debug_filtergraph, build_final_filtergraph, write_filtergraph
from .project import load_project, project_paths
from .redactions import load_redactions, render_redactions


def copy_trimmed_to_final(
    project_root: Path,
    *,
    source: Path | None = None,
    output: Path | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> Path:
    cfg = load_project(project_root)
    p = project_paths(project_root, config=cfg)
    trimmed = source or p.trimmed
    if source is not None and not trimmed.is_absolute() and not trimmed.exists():
        trimmed = p.root / trimmed
    if output is None:
        output = p.output_dir / "final.mp4"
    elif not output.is_absolute():
        output = p.root / output

    if not dry_run:
        if not trimmed.exists():
            raise FileNotFoundError(f"Trimmed video not found: {trimmed}. Run `vided trim` first.")
        same_file = trimmed.resolve() == output.resolve()
        if output.exists() and not overwrite and not same_file:
            raise FileExistsError(
                f"Final video already exists: {output}. Use --overwrite to replace it."
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        if not same_file:
            shutil.copy2(trimmed, output)

    return output


def render_project(
    project_root: Path,
    *,
    debug: bool = False,
    output: Path | None = None,
    audio_preset: str | None = None,
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

    render_cfg_raw = cfg.get("render", {})
    render_cfg: dict[str, Any] = render_cfg_raw if isinstance(render_cfg_raw, dict) else {}
    video_codec = str(render_cfg.get("video_codec", "libx264"))
    crf = str(render_cfg.get("crf", 16))
    preset = str(render_cfg.get("preset", "medium"))
    pix_fmt = str(render_cfg.get("pixel_format", "yuv420p"))
    audio_codec = str(render_cfg.get("audio_codec", "copy"))
    audio_cfg_raw = cfg.get("audio", {})
    audio_cfg: dict[str, Any] = audio_cfg_raw if isinstance(audio_cfg_raw, dict) else {}
    selected_audio_preset = audio_preset if audio_preset is not None else audio_cfg.get("preset")
    audio_filter = audio_filter_for_preset(str(selected_audio_preset or "none"))

    if output is None:
        output = p.output_dir / ("debug-preview.mp4" if debug else "final.mp4")
    elif not output.is_absolute():
        output = p.root / output
    if not dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)

    base_cmd = ["ffmpeg", "-hide_banner", "-y" if overwrite else "-n", "-i", str(trimmed)]
    if audio_filter is None:
        cmd = [
            *base_cmd,
            "-filter_complex",
            graph,
            "-map",
            "[vout]",
            "-map",
            "0:a?",
            "-c:v",
            video_codec,
        ]
        _extend_video_encode_args(
            cmd, video_codec=video_codec, crf=crf, preset=preset, pix_fmt=pix_fmt
        )
        if audio_codec == "copy":
            cmd.extend(["-c:a", "copy"])
        elif audio_codec == "aac":
            cmd.extend(["-c:a", "aac", "-b:a", str(render_cfg.get("audio_bitrate", "192k"))])
        else:
            cmd.extend(["-c:a", audio_codec])
    else:
        media_info = probe_media(trimmed)
        if not media_info.has_audio:
            print(
                "warning: audio preset requested but trimmed video has no audio stream",
                file=sys.stderr,
            )

        if redactions:
            graph_for_render = graph
            cmd = [
                *base_cmd,
                "-filter_complex",
                graph_for_render,
                "-map",
                "[vout]",
            ]
            if media_info.has_audio:
                graph_for_render = f"{graph};\n[0:a]{audio_filter}[aout]"
                cmd[cmd.index("-filter_complex") + 1] = graph_for_render
                cmd.extend(["-map", "[aout]"])
            cmd.extend(["-c:v", video_codec])
            _extend_video_encode_args(
                cmd, video_codec=video_codec, crf=crf, preset=preset, pix_fmt=pix_fmt
            )
        else:
            cmd = [*base_cmd, "-map", "0:v:0"]
            if media_info.has_audio:
                cmd.extend(["-map", "0:a:0", "-af", audio_filter])
            cmd.extend(["-c:v", "copy"])

        if media_info.has_audio:
            cmd.extend(["-c:a", "aac", "-b:a", str(render_cfg.get("audio_bitrate", "192k"))])

    cmd.extend(["-movflags", "+faststart", str(output)])
    run_command(cmd, dry_run=dry_run)
    return output


def _extend_video_encode_args(
    cmd: list[str],
    *,
    video_codec: str,
    crf: str,
    preset: str,
    pix_fmt: str,
) -> None:
    if video_codec in {"libx264", "libx265", "libsvtav1"}:
        cmd.extend(["-crf", crf, "-preset", preset])
    if pix_fmt:
        cmd.extend(["-pix_fmt", pix_fmt])
