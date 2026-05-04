from __future__ import annotations


class VidedError(Exception):
    """Base class for expected vided errors."""


class ProjectError(VidedError):
    """Raised when a project file or project state is invalid."""


class ValidationError(VidedError, ValueError):
    """Raised when user-provided data fails validation."""


class ExternalToolError(VidedError, RuntimeError):
    """Raised when an external media tool is missing or fails."""
