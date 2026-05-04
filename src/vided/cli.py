from __future__ import annotations

import io
import re
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import cyclopts
from cyclopts import App, Parameter

from .contact_sheet import render_contact_sheet
from .errors import VidedError
from .ffmpeg import ToolError, ensure_tool
from .project import create_project, project_paths
from .redactions import load_redactions, render_redactions, validate_redaction_document
from .render import render_project
from .skill_installer import install_skill
from .trimmer import TrimOptions, VadOptions, plan_trim, run_trim_plan

Detector = Literal["audio", "vad"]
TrimMode = Literal["hybrid", "speed", "cut", "keep"]
SpeedIndicatorCorner = Literal["top-left", "top-right", "bottom-left", "bottom-right"]
SpeedIndicatorStyle = Literal["dark", "light"]
AgentName = Literal["codex", "claude"]

StoreTrue = Parameter(negative=())


def _default_project_dir(source: Path) -> Path:
    name = re.sub(r"[^A-Za-z0-9]+", "-", source.stem).strip("-").lower()
    return Path(name or "video-project")


@Parameter(name="*")
@dataclass(frozen=True)
class VadCliOptions:
    vad_threshold: float | None = None
    vad_min_speech_ms: int | None = None
    vad_min_silence_ms: int | None = None
    vad_speech_pad_ms: int | None = None
    vad_merge_gap: float | None = None

    def to_vad_options(self) -> VadOptions:
        return VadOptions(
            threshold=self.vad_threshold,
            min_speech_duration_ms=self.vad_min_speech_ms,
            min_silence_duration_ms=self.vad_min_silence_ms,
            speech_pad_ms=self.vad_speech_pad_ms,
            merge_speech_gap_seconds=self.vad_merge_gap,
        )


@Parameter(name="*")
@dataclass(frozen=True)
class SpeedIndicatorCliOptions:
    speed_indicator: bool | None = None
    speed_indicator_corner: SpeedIndicatorCorner | None = None
    speed_indicator_style: SpeedIndicatorStyle | None = None
    speed_indicator_min_seconds: float | None = None


@Parameter(name="*")
@dataclass(frozen=True)
class TrimCliOptions:
    detector: Annotated[Detector | None, Parameter(name=["--detector", "--engine"])] = None
    mode: TrimMode | None = None
    margin: str | None = None
    smooth: str | None = None
    silent_speed: float | None = None
    mute_silent_audio: bool | None = None
    vad: VadCliOptions | None = None
    speed_indicator: SpeedIndicatorCliOptions | None = None

    def to_trim_options(self) -> TrimOptions:
        vad = self.vad or VadCliOptions()
        speed = self.speed_indicator or SpeedIndicatorCliOptions()
        return TrimOptions(
            detector=self.detector,
            mode=self.mode,
            margin=self.margin,
            smooth=self.smooth,
            silent_speed=self.silent_speed,
            mute_silent_audio=self.mute_silent_audio,
            vad=vad.to_vad_options(),
            speed_indicator=speed.speed_indicator,
            speed_indicator_corner=speed.speed_indicator_corner,
            speed_indicator_style=speed.speed_indicator_style,
            speed_indicator_min_display_seconds=speed.speed_indicator_min_seconds,
        )


def _trim_options_from_cli(options: TrimCliOptions | None) -> TrimOptions:
    return (options or TrimCliOptions()).to_trim_options()


app = App(
    name="vided",
    help="Simple local video silence speeder and rectangular blur redactor.",
    help_formatter="plain",
    version_flags=[],
    result_action="return_int_as_exit_code_else_zero",
    print_error=False,
    exit_on_error=False,
)


@app.command(help="Create a one-video project folder.", sort_key=0)
def init(
    source: Path,
    /,
    *,
    output_dir: Annotated[
        Path | None,
        Parameter(
            alias="-o",
            help="Project folder to create. Defaults to a name based on the input video.",
        ),
    ] = None,
    frame_interval: Annotated[float, Parameter(help="Default thumbnail interval.")] = 1.0,
    symlink: Annotated[
        bool, StoreTrue, Parameter(help="Symlink instead of copying input video.")
    ] = False,
    overwrite: Annotated[
        bool,
        StoreTrue,
        Parameter(help="Allow reusing a non-empty folder."),
    ] = False,
) -> int:
    project_root = output_dir or _default_project_dir(source)
    cfg = create_project(
        source,
        project_root,
        frame_interval=frame_interval,
        copy_input=not symlink,
        overwrite=overwrite,
    )
    action = "linked" if symlink else "copied"
    print(f"Created project: {project_root.resolve()}")
    print(f"Source {action} to: {cfg['original_path']}")
    print("Next: uv run vided trim <project>")
    return 0


@app.command(help="Run the trim renderer on the source video.", sort_key=1)
def trim(
    project: Path,
    /,
    *,
    options: TrimCliOptions | None = None,
    overwrite: Annotated[bool, StoreTrue] = False,
    dry_run: Annotated[bool, StoreTrue] = False,
) -> int:
    plan = plan_trim(
        project,
        options=_trim_options_from_cli(options),
        allow_vad_detection=not dry_run,
    )
    result = run_trim_plan(plan, overwrite=overwrite, dry_run=dry_run)
    print(f"Trimmed video: {result.path}")
    return 0


@app.command(help="Start the local annotation UI, generating frames if needed.", sort_key=3)
def ui(
    project: Path,
    /,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    no_open: Annotated[
        bool, StoreTrue, Parameter(help="Do not open the browser automatically.")
    ] = False,
    frame_interval: Annotated[
        float | None,
        Parameter(help="Seconds between thumbnails."),
    ] = None,
    thumbnail_width: int | None = None,
    regenerate_frames: Annotated[
        bool,
        StoreTrue,
        Parameter(help="Regenerate thumbnails before opening the UI."),
    ] = False,
) -> int:
    from .ui_server import run_ui

    run_ui(
        project,
        host=host,
        port=port,
        open_browser=not no_open,
        frame_interval=frame_interval,
        thumbnail_width=thumbnail_width,
        regenerate_frames=regenerate_frames,
    )
    return 0


@app.command(help="Render final or debug preview video.", sort_key=4)
def render(
    project: Path,
    /,
    *,
    debug: Annotated[
        bool,
        StoreTrue,
        Parameter(help="Render visible rectangles instead of blur."),
    ] = False,
    contact_sheet: Annotated[
        bool,
        StoreTrue,
        Parameter(help="Render a contact sheet from the final video."),
    ] = False,
    final_video: Annotated[
        Path | None,
        Parameter(help="Final video to sample when rendering a contact sheet."),
    ] = None,
    output: Path | None = None,
    overwrite: Annotated[bool, StoreTrue] = False,
    dry_run: Annotated[bool, StoreTrue] = False,
) -> int:
    if contact_sheet:
        if debug:
            raise ValueError("Use either --debug or --contact-sheet, not both.")
        sheet = render_contact_sheet(
            project,
            final_video=final_video,
            output=output,
            overwrite=overwrite,
            dry_run=dry_run,
        )
        print(f"Contact sheet: {sheet}")
        return 0
    if final_video is not None:
        raise ValueError("--final-video can only be used with --contact-sheet.")

    rendered = render_project(
        project,
        debug=debug,
        output=output,
        overwrite=overwrite,
        dry_run=dry_run,
    )
    print(f"Rendered video: {rendered}")
    return 0


@app.command(show=False, sort_key=5)
def validate(project: Path, /) -> int:
    data = load_redactions(project)
    validate_redaction_document(data)
    redactions = render_redactions(data)
    print(f"OK: {len(redactions)} redaction(s) valid in {project_paths(project).redactions_json}")
    return 0


@app.command(help="Check external tool availability.", sort_key=6)
def doctor() -> int:
    ok = True
    for tool in ["ffmpeg", "ffprobe"]:
        try:
            resolved = ensure_tool(tool)
            print(f"OK: {tool} -> {resolved}")
        except ToolError as exc:
            ok = False
            print(f"MISSING: {exc}")
    return 0 if ok else 1


@app.command(name="install-skill", help="Install the packaged agent skill.", sort_key=7)
def install_skill_command(
    *,
    agent: Annotated[AgentName, Parameter(help="Personal skill directory to install into.")],
    overwrite: Annotated[bool, StoreTrue] = False,
    dry_run: Annotated[bool, StoreTrue] = False,
) -> int:
    result = install_skill(
        agent,
        overwrite=overwrite,
        dry_run=dry_run,
    )
    action = "Would install" if result.dry_run else "Installed"
    print(f"{action} {agent} skill: {result.path}")
    return 0


def build_app() -> App:
    return app


def help_text(tokens: list[str] | None = None) -> str:
    output = io.StringIO()
    with redirect_stdout(output):
        app.help_print(tokens)
    return output.getvalue()


def main(argv: list[str] | None = None) -> int:
    tokens = sys.argv[1:] if argv is None else argv
    if not tokens:
        print(help_text(), end="")
        return 2

    try:
        return int(app(tokens))
    except cyclopts.CycloptsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, FileExistsError, VidedError, ValueError, ToolError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
