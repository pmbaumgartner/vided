"""Public Python API for vided."""

from .contact_sheet import render_contact_sheet
from .errors import (
    ExternalToolError,
    OptionalDependencyError,
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
from .render import render_project
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

__version__ = "0.1.0"

__all__ = [
    "ExternalToolError",
    "OperationResult",
    "OptionalDependencyError",
    "ProjectError",
    "ProjectPaths",
    "Rect",
    "Redaction",
    "RedactionDocument",
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
    "create_project",
    "generate_frames",
    "load_project",
    "load_redactions",
    "normalize_detector",
    "plan_trim",
    "probe_media",
    "project_paths",
    "read_json",
    "render_contact_sheet",
    "render_project",
    "render_redactions",
    "run_trim_plan",
    "run_vad_detection",
    "save_project",
    "save_redactions",
    "validate_redaction_document",
    "write_json",
]
