"""Public Python API for vided."""

from ._version import get_version as _get_version
from .audio_presets import AudioPreset, list_audio_presets
from .audio_preview import render_audio_preview, select_audio_preview_window
from .contact_sheet import render_contact_sheet
from .errors import (
    ExternalToolError,
    ProjectError,
    ValidationError,
    VidedError,
)
from .ffmpeg import ToolError, VideoInfo, probe_media
from .frames import generate_frames
from .project import (
    ProjectPaths,
    create_project,
    load_project,
    project_paths,
    read_json,
    save_project,
    write_json,
)
from .redactions import (
    Rect,
    Redaction,
    RedactionDocument,
    load_redactions,
    render_redactions,
    save_redactions,
    validate_redaction_document,
)
from .render import copy_trimmed_to_final, render_project
from .skill_installer import SkillInstallResult, install_skill, load_packaged_skill
from .trimmer import (
    OperationResult,
    TrimOptions,
    TrimPlan,
    TrimSegment,
    VadOptions,
    build_trim_command,
    plan_trim,
    run_trim_plan,
)
from .vad import VadSettings, normalize_detector, run_vad_detection

__version__ = _get_version()

__all__ = [
    "AudioPreset",
    "ExternalToolError",
    "OperationResult",
    "ProjectError",
    "ProjectPaths",
    "Rect",
    "Redaction",
    "RedactionDocument",
    "SkillInstallResult",
    "ToolError",
    "TrimOptions",
    "TrimPlan",
    "TrimSegment",
    "VadOptions",
    "VadSettings",
    "ValidationError",
    "VidedError",
    "VideoInfo",
    "__version__",
    "build_trim_command",
    "copy_trimmed_to_final",
    "create_project",
    "generate_frames",
    "install_skill",
    "load_project",
    "load_packaged_skill",
    "load_redactions",
    "list_audio_presets",
    "normalize_detector",
    "plan_trim",
    "probe_media",
    "project_paths",
    "read_json",
    "render_audio_preview",
    "render_contact_sheet",
    "render_project",
    "render_redactions",
    "run_trim_plan",
    "run_vad_detection",
    "save_project",
    "save_redactions",
    "select_audio_preview_window",
    "validate_redaction_document",
    "write_json",
]
