from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .contact_sheet import render_contact_sheet
from .errors import VidedError
from .ffmpeg import ToolError, ensure_tool
from .project import create_project, project_paths
from .redactions import load_redactions, render_redactions, validate_redaction_document
from .render import render_project
from .skill_installer import install_skill
from .trimmer import TrimOptions, VadOptions, build_trim_command, plan_trim, run_trim_plan
from .vad import run_vad_detection


def _default_project_dir(source: Path) -> Path:
    name = re.sub(r"[^A-Za-z0-9]+", "-", source.stem).strip("-").lower()
    return Path(name or "video-project")


def _add_vad_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--vad-threshold", type=float, default=None)
    parser.add_argument("--vad-min-speech-ms", type=int, default=None)
    parser.add_argument("--vad-min-silence-ms", type=int, default=None)
    parser.add_argument("--vad-speech-pad-ms", type=int, default=None)
    parser.add_argument("--vad-merge-gap", type=float, default=None)


def _add_trim_detector_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--detector",
        "--engine",
        choices=["audio", "vad"],
        default=None,
        help="Detector used to classify normal-speed sections.",
    )
    _add_vad_options(parser)


def _add_speed_indicator_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--speed-indicator",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Show a small speed label on sped-up silent sections.",
    )
    parser.add_argument(
        "--speed-indicator-corner",
        choices=["top-left", "top-right", "bottom-left", "bottom-right"],
        default=None,
    )
    parser.add_argument(
        "--speed-indicator-style",
        choices=["dark", "light"],
        default=None,
    )
    parser.add_argument(
        "--speed-indicator-min-seconds",
        type=float,
        default=None,
        help="Only show the badge when the sped-up section lasts at least this long after speedup.",
    )


def _add_diagnostic_parser(subparsers, name: str) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name)
    # Keep diagnostic commands parseable without putting them in top-level help.
    subparsers._choices_actions = [
        action for action in subparsers._choices_actions if action.dest != name
    ]
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vided",
        description="Simple local video silence speeder and rectangular blur redactor.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    init = sub.add_parser("init", help="Create a one-video project folder.")
    init.add_argument("source", type=Path, help="Input video path.")
    init.add_argument(
        "project",
        type=Path,
        nargs="?",
        help="Project folder to create. Defaults to a folder name based on the input video.",
    )
    init.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Project folder to create when using the input video shorthand.",
    )
    init.add_argument(
        "--frame-interval", type=float, default=1.0, help="Default thumbnail interval."
    )
    init.add_argument(
        "--symlink", action="store_true", help="Symlink instead of copying input video."
    )
    init.add_argument("--overwrite", action="store_true", help="Allow reusing a non-empty folder.")
    init.set_defaults(func=cmd_init)

    trim = sub.add_parser("trim", help="Run the trim renderer on the source video.")
    trim.add_argument("project", type=Path)
    _add_trim_detector_options(trim)
    trim.add_argument("--mode", choices=["hybrid", "speed", "cut", "keep"], default=None)
    trim.add_argument("--margin", default=None, help="Trim margin, e.g. 0.2s or 0.3s,1.0s")
    trim.add_argument("--smooth", default=None, help="Trim smoothing pair, e.g. 0.2s,0.1s")
    trim.add_argument("--silent-speed", type=float, default=None, help="Speed for silent sections.")
    trim.add_argument(
        "--mute-silent-audio",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="When speed mode is used, chain volume:0 onto silent sections.",
    )
    _add_speed_indicator_options(trim)
    trim.add_argument("--overwrite", action="store_true")
    trim.add_argument("--dry-run", action="store_true")
    trim.set_defaults(func=cmd_trim)

    vad = _add_diagnostic_parser(sub, "vad")
    vad.add_argument("project", type=Path)
    _add_vad_options(vad)
    vad.set_defaults(func=cmd_vad)

    ui = sub.add_parser("ui", help="Start the local annotation UI, generating frames if needed.")
    ui.add_argument("project", type=Path)
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")
    ui.add_argument(
        "--frame-interval", type=float, default=None, help="Seconds between thumbnails."
    )
    ui.add_argument("--thumbnail-width", type=int, default=None)
    ui.add_argument(
        "--regenerate-frames",
        action="store_true",
        help="Regenerate thumbnails before opening the UI.",
    )
    ui.set_defaults(func=cmd_ui)

    render = sub.add_parser("render", help="Render final or debug preview video.")
    render.add_argument("project", type=Path)
    render.add_argument(
        "--debug", action="store_true", help="Render visible rectangles instead of blur."
    )
    render.add_argument(
        "--contact-sheet",
        action="store_true",
        help="Render a contact sheet from the final video.",
    )
    render.add_argument(
        "--final-video",
        type=Path,
        default=None,
        help="Final video to sample when rendering a contact sheet.",
    )
    render.add_argument("--output", type=Path, default=None)
    render.add_argument("--overwrite", action="store_true")
    render.add_argument("--dry-run", action="store_true")
    render.set_defaults(func=cmd_render)

    validate = _add_diagnostic_parser(sub, "validate")
    validate.add_argument("project", type=Path)
    validate.set_defaults(func=cmd_validate)

    doctor = sub.add_parser("doctor", help="Check external tool availability.")
    doctor.set_defaults(func=cmd_doctor)

    install_skill_parser = sub.add_parser("install-skill", help="Install the packaged agent skill.")
    install_skill_parser.add_argument(
        "--agent",
        choices=["codex", "claude"],
        required=True,
        help="Personal skill directory to install into.",
    )
    install_skill_parser.add_argument("--overwrite", action="store_true")
    install_skill_parser.add_argument("--dry-run", action="store_true")
    install_skill_parser.set_defaults(func=cmd_install_skill)

    preview = _add_diagnostic_parser(sub, "trim-command")
    preview.add_argument("project", type=Path)
    _add_trim_detector_options(preview)
    preview.add_argument("--mode", choices=["hybrid", "speed", "cut", "keep"], default=None)
    preview.add_argument("--margin", default=None)
    preview.add_argument("--smooth", default=None)
    preview.add_argument("--silent-speed", type=float, default=None)
    preview.add_argument("--mute-silent-audio", action=argparse.BooleanOptionalAction, default=None)
    _add_speed_indicator_options(preview)
    preview.set_defaults(func=cmd_trim_command)

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    if args.project is not None and args.output_dir is not None:
        raise ValueError("Use either the project argument or --output-dir, not both.")

    project = args.output_dir or args.project or _default_project_dir(args.source)
    cfg = create_project(
        args.source,
        project,
        frame_interval=args.frame_interval,
        copy_input=not args.symlink,
        overwrite=args.overwrite,
    )
    action = "linked" if args.symlink else "copied"
    print(f"Created project: {project.resolve()}")
    print(f"Source {action} to: {cfg['original_path']}")
    print("Next: uv run vided trim <project>")
    return 0


def cmd_trim(args: argparse.Namespace) -> int:
    plan = plan_trim(
        args.project,
        options=_trim_options_from_args(args),
        allow_vad_detection=not args.dry_run,
    )
    result = run_trim_plan(plan, overwrite=args.overwrite, dry_run=args.dry_run)
    print(f"Trimmed video: {result.path}")
    return 0


def cmd_vad(args: argparse.Namespace) -> int:
    output = run_vad_detection(
        args.project,
        threshold=args.vad_threshold,
        min_speech_duration_ms=args.vad_min_speech_ms,
        min_silence_duration_ms=args.vad_min_silence_ms,
        speech_pad_ms=args.vad_speech_pad_ms,
        merge_speech_gap_seconds=args.vad_merge_gap,
    )
    print(f"VAD ranges: {output}")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    from .ui_server import run_ui

    run_ui(
        args.project,
        host=args.host,
        port=args.port,
        open_browser=not args.no_open,
        frame_interval=args.frame_interval,
        thumbnail_width=args.thumbnail_width,
        regenerate_frames=args.regenerate_frames,
    )
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    if args.contact_sheet:
        if args.debug:
            raise ValueError("Use either --debug or --contact-sheet, not both.")
        output = render_contact_sheet(
            args.project,
            final_video=args.final_video,
            output=args.output,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
        print(f"Contact sheet: {output}")
        return 0
    if args.final_video is not None:
        raise ValueError("--final-video can only be used with --contact-sheet.")

    output = render_project(
        args.project,
        debug=args.debug,
        output=args.output,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )
    print(f"Rendered video: {output}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    data = load_redactions(args.project)
    validate_redaction_document(data)
    redactions = render_redactions(data)
    print(
        f"OK: {len(redactions)} redaction(s) valid in {project_paths(args.project).redactions_json}"
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:  # noqa: ARG001
    ok = True
    for tool in ["ffmpeg", "ffprobe"]:
        try:
            resolved = ensure_tool(tool)
            print(f"OK: {tool} -> {resolved}")
        except ToolError as exc:
            ok = False
            print(f"MISSING: {exc}")
    return 0 if ok else 1


def cmd_install_skill(args: argparse.Namespace) -> int:
    result = install_skill(
        args.agent,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )
    action = "Would install" if result.dry_run else "Installed"
    print(f"{action} {args.agent} skill: {result.path}")
    return 0


def cmd_trim_command(args: argparse.Namespace) -> int:
    plan = plan_trim(
        args.project,
        options=_trim_options_from_args(args),
        allow_vad_detection=False,
    )
    cmd = build_trim_command(plan)
    print(" ".join(cmd))
    return 0


def _trim_options_from_args(args: argparse.Namespace) -> TrimOptions:
    return TrimOptions(
        detector=args.detector,
        mode=args.mode,
        margin=args.margin,
        smooth=args.smooth,
        silent_speed=args.silent_speed,
        mute_silent_audio=args.mute_silent_audio,
        vad=VadOptions(
            threshold=args.vad_threshold,
            min_speech_duration_ms=args.vad_min_speech_ms,
            min_silence_duration_ms=args.vad_min_silence_ms,
            speech_pad_ms=args.vad_speech_pad_ms,
            merge_speech_gap_seconds=args.vad_merge_gap,
        ),
        speed_indicator=args.speed_indicator,
        speed_indicator_corner=args.speed_indicator_corner,
        speed_indicator_style=args.speed_indicator_style,
        speed_indicator_min_display_seconds=args.speed_indicator_min_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2

    try:
        return int(args.func(args))
    except (FileNotFoundError, FileExistsError, VidedError, ValueError, ToolError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
