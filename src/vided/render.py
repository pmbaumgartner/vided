from __future__ import annotations

from dataclasses import dataclass
import shutil
import sys
from pathlib import Path
from typing import Any, Literal

from .audio_presets import audio_filter_for_preset
from .compression import (
    CompressionDecision,
    CompressionMode,
    CompressionPriority,
    append_output_video_filter,
    choose_smart_compression,
    normalize_compression_mode,
    normalize_compression_priority,
    render_config_with_compression,
    video_filter_args,
)
from .errors import ValidationError
from .encoding import (
    SampleEstimate,
    build_sample_estimate,
    ensure_output_not_larger,
    output_duration_from_segments,
    sample_duration_seconds,
    sample_output_path,
    video_encode_args,
)
from .ffmpeg import (
    audio_config_args,
    audio_encode_args,
    ffmpeg_base_args,
    ffmpeg_input_args,
    ffmpeg_output_args,
    ensure_tool,
    probe_media,
    run_command,
)
from .filtergraph import build_final_filtergraph, write_filtergraph
from .project import load_project, project_paths
from .redactions import Redaction, load_redactions, render_redactions
from .trimmer import TrimSegment, build_trim_filtergraph

RenderSource = Literal["auto", "trimmed", "original"]


@dataclass(frozen=True)
class RenderResult:
    path: Path
    command: list[str] | None
    dry_run: bool
    wrote_files: bool
    sample: SampleEstimate | None = None
    compression: CompressionDecision | None = None


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
    render_source: RenderSource = "auto",
    compress: CompressionMode = "off",
    compression_priority: CompressionPriority = "compatibility",
    max_fps: float | None = None,
    sample_duration: float | None = None,
    sample_output: Path | None = None,
    allow_larger: bool = False,
    overwrite: bool = False,
    dry_run: bool = False,
) -> RenderResult:
    if render_source not in {"auto", "trimmed", "original"}:
        raise ValueError("render source must be one of: auto, trimmed, original")
    compress = normalize_compression_mode(compress)
    compression_priority = normalize_compression_priority(compression_priority)
    sample_duration = sample_duration_seconds(sample_duration)

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

    final_output = output
    if sample_duration is not None:
        output = sample_output_path(
            requested=sample_output,
            default_dir=final_output.parent,
            label=final_output.stem,
            suffix="smart" if compress == "smart" else "current",
        )
        if not output.is_absolute():
            output = p.root / output
        if output.resolve() == final_output.resolve():
            raise ValidationError("render sample output cannot be the final output path")

    if (
        render_source != "original"
        and not redactions
        and audio_filter is None
        and compress == "off"
        and sample_duration is None
    ):
        rendered = copy_trimmed_to_final(
            project_root,
            source=p.trimmed,
            output=output,
            overwrite=overwrite,
            dry_run=dry_run,
        )
        return RenderResult(
            path=rendered,
            command=None,
            dry_run=dry_run,
            wrote_files=not dry_run,
        )

    full_duration = 0.0
    compression_decision: CompressionDecision | None = None
    if render_source == "original":
        one_pass_segments, one_pass_error = _one_pass_segments(cfg, p.original)
        if one_pass_error is None:
            full_duration = output_duration_from_segments(one_pass_segments)
            if compress == "smart":
                original_info = probe_media(p.original)
                compression_decision = choose_smart_compression(
                    p.original,
                    original_info,
                    render_cfg,
                    priority=compression_priority,
                    max_fps=max_fps,
                    full_duration=full_duration,
                    sample_dir=p.work_dir / "compression-samples",
                    sample_label=final_output.stem,
                    dry_run=dry_run,
                    runner=lambda cmd: run_command(cmd, dry_run=False),
                )
                render_cfg = render_config_with_compression(render_cfg, compression_decision)
            rendered, command = _render_one_pass(
                p.original,
                output,
                segments=one_pass_segments,
                redactions=redactions,
                render_cfg=render_cfg,
                audio_filter=audio_filter,
                filtergraph_path=p.work_dir / "filtergraph.txt",
                sample_duration=sample_duration,
                reference=p.original if compress == "smart" else None,
                allow_larger=allow_larger,
                overwrite=overwrite,
                dry_run=dry_run,
            )
            return _render_result(
                rendered,
                command=command,
                dry_run=dry_run,
                sample_duration=sample_duration,
                full_duration=full_duration,
                compression=compression_decision,
            )
        raise ValidationError(f"Original-source render is unavailable: {one_pass_error}")

    if sample_duration is not None or compress == "smart":
        trimmed_info = probe_media(p.trimmed)
        full_duration = trimmed_info.duration
    else:
        trimmed_info = None
    if compress == "smart":
        if trimmed_info is None:
            trimmed_info = probe_media(p.trimmed)
            full_duration = trimmed_info.duration
        compression_decision = choose_smart_compression(
            p.trimmed,
            trimmed_info,
            render_cfg,
            priority=compression_priority,
            max_fps=max_fps,
            full_duration=full_duration,
            sample_dir=p.work_dir / "compression-samples",
            sample_label=final_output.stem,
            dry_run=dry_run,
            runner=lambda cmd: run_command(cmd, dry_run=False),
        )
        render_cfg = render_config_with_compression(render_cfg, compression_decision)
    force_video_encode = compression_decision is not None or (
        sample_duration is not None and not redactions and audio_filter is None
    )
    rendered, command = _render_from_trimmed(
        p.trimmed,
        output,
        redactions=redactions,
        render_cfg=render_cfg,
        audio_filter=audio_filter,
        filtergraph_path=p.work_dir / "filtergraph.txt",
        force_video_encode=force_video_encode,
        sample_duration=sample_duration,
        reference=p.trimmed if compression_decision is not None else None,
        allow_larger=allow_larger,
        overwrite=overwrite,
        dry_run=dry_run,
    )
    return _render_result(
        rendered,
        command=command,
        dry_run=dry_run,
        sample_duration=sample_duration,
        full_duration=full_duration,
        compression=compression_decision,
    )


def _render_from_trimmed(
    trimmed: Path,
    output: Path,
    *,
    redactions: list[Redaction],
    render_cfg: dict[str, Any],
    audio_filter: str | None,
    filtergraph_path: Path,
    force_video_encode: bool,
    sample_duration: float | None,
    reference: Path | None,
    allow_larger: bool,
    overwrite: bool,
    dry_run: bool,
) -> tuple[Path, list[str]]:
    sample_duration = sample_duration_seconds(sample_duration)
    ensure_tool("ffmpeg")
    if not trimmed.exists():
        raise FileNotFoundError(f"Trimmed video not found: {trimmed}. Run `vided trim` first.")

    graph = build_final_filtergraph(redactions)
    video_label = "vout"
    graph, video_label = append_output_video_filter(graph, render_cfg, input_label=video_label)
    if not dry_run:
        write_filtergraph(filtergraph_path, graph)
        output.parent.mkdir(parents=True, exist_ok=True)

    base_cmd = [*ffmpeg_base_args(overwrite=overwrite), *ffmpeg_input_args(trimmed)]
    if audio_filter is None:
        cmd = [
            *base_cmd,
            "-filter_complex",
            graph,
            "-map",
            f"[{video_label}]",
            "-map",
            "0:a?",
        ]
        cmd.extend(video_encode_args(render_cfg))
        cmd.extend(audio_config_args(render_cfg, default_codec="copy"))
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
                f"[{video_label}]",
            ]
            if media_info.has_audio:
                graph_for_render = f"{graph};\n[0:a]{audio_filter}[aout]"
                cmd[cmd.index("-filter_complex") + 1] = graph_for_render
                cmd.extend(["-map", "[aout]"])
            cmd.extend(video_encode_args(render_cfg))
        else:
            cmd = [*base_cmd, "-map", "0:v:0"]
            if media_info.has_audio:
                cmd.extend(["-map", "0:a:0", "-af", audio_filter])
            if force_video_encode:
                cmd.extend(video_filter_args(render_cfg))
                cmd.extend(video_encode_args(render_cfg))
            else:
                cmd.extend(["-c:v", "copy"])

        if media_info.has_audio:
            cmd.extend(audio_encode_args(render_cfg))

    cmd.extend(ffmpeg_output_args(output, sample_duration=sample_duration))
    run_command(cmd, dry_run=dry_run)
    if reference is not None and sample_duration is None:
        ensure_output_not_larger(
            output,
            reference,
            allow_larger=allow_larger,
            dry_run=dry_run,
        )
    return output, cmd


def _render_one_pass(
    original: Path,
    output: Path,
    *,
    segments: list[TrimSegment],
    redactions: list[Redaction],
    render_cfg: dict[str, Any],
    audio_filter: str | None,
    filtergraph_path: Path,
    sample_duration: float | None,
    reference: Path | None,
    allow_larger: bool,
    overwrite: bool,
    dry_run: bool,
) -> tuple[Path, list[str]]:
    sample_duration = sample_duration_seconds(sample_duration)
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
    video_label = "vout"

    cmd = [
        *ffmpeg_base_args(overwrite=overwrite),
        *ffmpeg_input_args(original),
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
    graph, video_label = append_output_video_filter(graph, render_cfg, input_label=video_label)
    cmd[cmd.index("-filter_complex") + 1] = graph
    cmd[cmd.index("-map") + 1] = f"[{video_label}]"

    cmd.extend(video_encode_args(render_cfg))
    if media_info.has_audio:
        cmd.extend(audio_encode_args(render_cfg))
    cmd.extend(
        ffmpeg_output_args(
            output,
            sample_duration=sample_duration,
            drop_non_media=True,
            shortest=True,
        )
    )

    if not dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
        write_filtergraph(filtergraph_path, graph)
    run_command(cmd, dry_run=dry_run)
    if reference is not None and sample_duration is None:
        ensure_output_not_larger(
            output,
            reference,
            allow_larger=allow_larger,
            dry_run=dry_run,
        )
    return output, cmd


def _one_pass_segments(cfg: dict[str, Any], original: Path) -> tuple[list[TrimSegment], str | None]:
    if not original.exists():
        return [], f"original input not found: {original}"
    if _trim_speed_indicator_enabled(cfg):
        return [], "trim speed indicators are not supported by original-source render yet"

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


def _render_result(
    path: Path,
    *,
    command: list[str] | None,
    dry_run: bool,
    sample_duration: float | None,
    full_duration: float,
    compression: CompressionDecision | None,
) -> RenderResult:
    sample = None
    if sample_duration is not None:
        sample = build_sample_estimate(
            path,
            sample_duration=sample_duration,
            full_duration=full_duration,
            dry_run=dry_run,
        )
    return RenderResult(
        path=path,
        command=command,
        dry_run=dry_run,
        wrote_files=not dry_run,
        sample=sample,
        compression=compression,
    )
