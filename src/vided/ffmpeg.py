from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, overload

from .errors import ExternalToolError


class ToolError(ExternalToolError):
    """Raised when an external media tool fails."""


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    width: int
    height: int
    duration: float
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    has_audio: bool
    audio_sample_rate: int | None = None
    audio_channels: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "width": self.width,
            "height": self.height,
            "duration": self.duration,
            "fps": self.fps,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "has_audio": self.has_audio,
            "audio_sample_rate": self.audio_sample_rate,
            "audio_channels": self.audio_channels,
        }


def ensure_tool(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise ToolError(f"Required tool '{name}' was not found on PATH. Install it and try again.")
    return resolved


@overload
def run_command(
    argv: list[str],
    *,
    cwd: Path | None = None,
    output: Literal["none"] = "none",
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]: ...


@overload
def run_command(
    argv: list[str],
    *,
    cwd: Path | None = None,
    output: Literal["text"],
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]: ...


@overload
def run_command(
    argv: list[str],
    *,
    cwd: Path | None = None,
    output: Literal["bytes"],
    dry_run: bool = False,
) -> subprocess.CompletedProcess[bytes]: ...


def run_command(
    argv: list[str],
    *,
    cwd: Path | None = None,
    output: Literal["none", "text", "bytes"] = "none",
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    """Run an external command with predictable output and error handling."""

    printable = " ".join(argv)
    if dry_run:
        if output != "none":
            raise ValueError("dry_run is only supported when output='none'")
        print(f"[dry-run] {printable}")
        return subprocess.CompletedProcess(argv, 0, "", "")

    text = output != "bytes"
    capture_output = output != "none"
    try:
        return subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            check=True,
            text=text,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
        )
    except subprocess.CalledProcessError as exc:
        stderr = _command_output_text(exc.stderr)
        stdout = _command_output_text(exc.stdout)
        details = "\n".join(part for part in [stdout, stderr] if part.strip())
        raise ToolError(f"Command failed: {printable}\n{details}".rstrip()) from exc


def _command_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _parse_fraction(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    if "/" in value:
        left, right = value.split("/", 1)
        try:
            denominator = float(right)
            if denominator == 0:
                return None
            return float(left) / denominator
        except ValueError:
            return None
    try:
        return float(value)
    except ValueError:
        return None


def probe_media(path: Path) -> VideoInfo:
    """Return the basic media info this project needs."""

    ensure_tool("ffprobe")
    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        output="text",
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ToolError(f"No video stream found in {path}")

    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})

    duration_raw = video.get("duration") or fmt.get("duration") or 0
    try:
        duration = float(duration_raw)
    except (TypeError, ValueError):
        duration = 0.0

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)

    # Some mobile videos carry rotation metadata. This skeleton records encoded dimensions;
    # the README notes that rotation normalization is a v1 limitation.
    fps = _parse_fraction(video.get("avg_frame_rate")) or _parse_fraction(video.get("r_frame_rate"))

    return VideoInfo(
        path=path,
        width=width,
        height=height,
        duration=duration,
        fps=fps,
        video_codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name") if audio else None,
        has_audio=audio is not None,
        audio_sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        audio_channels=int(audio["channels"]) if audio and audio.get("channels") else None,
    )


def seconds(value: float | int | str) -> str:
    """Format seconds for ffmpeg-ish command arguments."""

    if isinstance(value, str):
        return value
    return f"{float(value):.6f}s"
