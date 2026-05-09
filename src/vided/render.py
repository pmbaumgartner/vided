from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any, Literal

from .audio_presets import audio_filter_for_preset
from .errors import ValidationError
from .ffmpeg import ensure_tool, probe_media, run_command
from .filtergraph import build_final_filtergraph, write_filtergraph
from .project import load_project, project_paths
from .redactions import Redaction, load_redactions, render_redactions
from .trimmer import TrimSegment, build_trim_filtergraph

RenderMode = Literal["auto", "trimmed", "one-pass"]


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
    output: Path | None = None,
    audio_preset: str | None = None,
    render_mode: RenderMode = "auto",
    overwrite: bool = False,
    dry_run: bool = False,
) -> Path:
    if render_mode not in {"auto", "trimmed", "one-pass"}:
        raise ValueError("render mode must be one of: auto, trimmed, one-pass")

    cfg = load_project(project_root)
    p = project_paths(project_root, config=cfg)
    redaction_data = load_redactions(project_root)
    redactions = render_redactions(redaction_data)

    render_cfg_raw = cfg.get("render", {})
    render_cfg: dict[str, Any] = render_cfg_raw if isinstance(render_cfg_raw, dict) else {}
    audio_cfg_raw = cfg.get("audio", {})
    audio_cfg: dict[str, Any] = audio_cfg_raw if isinstance(audio_cfg_raw, dict) else {}
    selected_audio_preset = audio_preset if audio_preset is not None else audio_cfg.get("preset")
    audio_filter = audio_filter_for_preset(str(selected_audio_preset or "none"))

    if output is None:
        output = p.output_dir / "final.mp4"
    elif not output.is_absolute():
        output = p.root / output

    if not redactions and audio_filter is None:
        return copy_trimmed_to_final(
            project_root,
            source=p.trimmed,
            output=output,
            overwrite=overwrite,
            dry_run=dry_run,
        )

    if render_mode == "one-pass" and not redactions:
        raise ValidationError(
            "One-pass render is only available when redactions require video rendering."
        )

    if render_mode == "one-pass" and redactions:
        one_pass_segments, one_pass_error = _one_pass_segments(cfg, p.original)
        if one_pass_error is None:
            return _render_one_pass(
                p.original,
                output,
                segments=one_pass_segments,
                redactions=redactions,
                render_cfg=render_cfg,
                audio_filter=audio_filter,
                filtergraph_path=p.work_dir / "filtergraph.txt",
                overwrite=overwrite,
                dry_run=dry_run,
            )
        raise ValidationError(f"One-pass render is unavailable: {one_pass_error}")

    return _render_from_trimmed(
        p.trimmed,
        output,
        redactions=redactions,
        render_cfg=render_cfg,
        audio_filter=audio_filter,
        filtergraph_path=p.work_dir / "filtergraph.txt",
        overwrite=overwrite,
        dry_run=dry_run,
    )


def _render_from_trimmed(
    trimmed: Path,
    output: Path,
    *,
    redactions: list[Redaction],
    render_cfg: dict[str, Any],
    audio_filter: str | None,
    filtergraph_path: Path,
    overwrite: bool,
    dry_run: bool,
) -> Path:
    ensure_tool("ffmpeg")
    if not trimmed.exists():
        raise FileNotFoundError(f"Trimmed video not found: {trimmed}. Run `vided trim` first.")

    graph = build_final_filtergraph(redactions)
    if not dry_run:
        write_filtergraph(filtergraph_path, graph)
        output.parent.mkdir(parents=True, exist_ok=True)

    video_codec = str(render_cfg.get("video_codec", "libx264"))
    crf = str(render_cfg.get("crf", 16))
    preset = str(render_cfg.get("preset", "medium"))
    pix_fmt = str(render_cfg.get("pixel_format", "yuv420p"))
    audio_codec = str(render_cfg.get("audio_codec", "copy"))

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


def _render_one_pass(
    original: Path,
    output: Path,
    *,
    segments: list[TrimSegment],
    redactions: list[Redaction],
    render_cfg: dict[str, Any],
    audio_filter: str | None,
    filtergraph_path: Path,
    overwrite: bool,
    dry_run: bool,
) -> Path:
    ensure_tool("ffmpeg")
    media_info = probe_media(original)
    trim_graph = build_trim_filtergraph(
        segments,
        has_audio=media_info.has_audio,
        video_output_label="trimv",
        audio_output_label="trima",
    )
    final_graph = build_final_filtergraph(redactions, input_label="trimv", output_label="vout")
    graph_parts = [trim_graph, final_graph]

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y" if overwrite else "-n",
        "-i",
        str(original),
        "-filter_complex",
        "",
        "-map",
        "[vout]",
    ]

    if audio_filter is not None and not media_info.has_audio:
        print(
            "warning: audio preset requested but original video has no audio stream",
            file=sys.stderr,
        )

    if media_info.has_audio:
        if audio_filter is None:
            cmd.extend(["-map", "[trima]"])
        else:
            graph_parts.append(f"[trima]{audio_filter}[aout]")
            cmd.extend(["-map", "[aout]"])

    graph = ";\n".join(graph_parts)
    cmd[cmd.index("-filter_complex") + 1] = graph

    video_codec = str(render_cfg.get("video_codec", "libx264"))
    crf = str(render_cfg.get("crf", 16))
    preset = str(render_cfg.get("preset", "medium"))
    pix_fmt = str(render_cfg.get("pixel_format", "yuv420p"))
    cmd.extend(["-c:v", video_codec])
    _extend_video_encode_args(cmd, video_codec=video_codec, crf=crf, preset=preset, pix_fmt=pix_fmt)
    if media_info.has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", str(render_cfg.get("audio_bitrate", "192k"))])
    cmd.extend(
        ["-sn", "-dn", "-map_chapters", "-1", "-shortest", "-movflags", "+faststart", str(output)]
    )

    if not dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
        write_filtergraph(filtergraph_path, graph)
    run_command(cmd, dry_run=dry_run)
    return output


def _one_pass_segments(cfg: dict[str, Any], original: Path) -> tuple[list[TrimSegment], str | None]:
    if not original.exists():
        return [], f"original input not found: {original}"
    if _trim_speed_indicator_enabled(cfg):
        return [], "trim speed indicators are not supported by one-pass render yet"

    timeline = cfg.get("trim_timeline")
    if not isinstance(timeline, dict):
        return [], "project is missing trim_timeline; run `vided trim` first"
    raw_segments = timeline.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        return [], "trim_timeline has no segments; rerun `vided trim`"

    segments: list[TrimSegment] = []
    try:
        for item in raw_segments:
            if not isinstance(item, dict):
                raise ValueError("segment is not an object")
            start = float(item["source_start"])
            end = float(item["source_end"])
            speed = float(item.get("speed", 1.0))
            mute_audio = bool(item.get("mute_audio", False))
            if end <= start:
                raise ValueError("segment end must be after start")
            if speed <= 0:
                raise ValueError("segment speed must be greater than zero")
            segments.append(TrimSegment(start=start, end=end, speed=speed, mute_audio=mute_audio))
    except (KeyError, TypeError, ValueError) as exc:
        return [], f"trim_timeline is invalid: {exc}"

    return segments, None


def _trim_speed_indicator_enabled(cfg: dict[str, Any]) -> bool:
    trim_cfg_raw = cfg.get("trim", {})
    trim_cfg: dict[str, Any] = trim_cfg_raw if isinstance(trim_cfg_raw, dict) else {}
    speed_indicator_raw = trim_cfg.get("speed_indicator", {})
    speed_indicator: dict[str, Any] = (
        speed_indicator_raw if isinstance(speed_indicator_raw, dict) else {}
    )
    return bool(speed_indicator.get("enabled", False))


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
