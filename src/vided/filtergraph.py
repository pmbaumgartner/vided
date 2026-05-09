from __future__ import annotations

import re
from pathlib import Path

from .redactions import Redaction

_COLOR_RE = re.compile(r"^[A-Za-z0-9#@._-]+$")


def _expr_between(start: float, end: float) -> str:
    # Commas inside expressions must be escaped for ffmpeg's filtergraph parser.
    return f"between(t\\,{start:.6f}\\,{end:.6f})"


def _clean_color(value: str | None, fallback: str = "black") -> str:
    if value and _COLOR_RE.match(value):
        return value
    return fallback


def build_final_filtergraph(
    redactions: list[Redaction],
    *,
    input_label: str = "0:v",
    output_label: str = "vout",
) -> str:
    """Build the final blur/solid redaction filtergraph."""

    if not redactions:
        return f"[{input_label}]setpts=PTS-STARTPTS[{output_label}]"

    solid = [r for r in redactions if r.style.get("type") == "solid"]
    blur = [r for r in redactions if r.style.get("type", "blur") != "solid"]

    parts: list[str] = []
    base_label = "base0"
    parts.append(f"[{input_label}]setpts=PTS-STARTPTS[{base_label}]")

    for idx, r in enumerate(solid, start=1):
        out = f"base{idx}"
        color = _clean_color(str(r.style.get("color", "black")))
        enable = _expr_between(r.start, r.end)
        parts.append(
            f"[{base_label}]drawbox=x={r.rect.x}:y={r.rect.y}:w={r.rect.w}:h={r.rect.h}:"
            f"color={color}:t=fill:enable='{enable}'[{out}]"
        )
        base_label = out

    if not blur:
        # Relabel the last base as vout. ffmpeg's null filter is a simple way to do that.
        parts.append(f"[{base_label}]null[{output_label}]")
        return ";\n".join(parts)

    split_labels = "".join(f"[r{idx}src]" for idx in range(len(blur)))
    parts.append(f"[{base_label}]split={len(blur) + 1}[base]{split_labels}")

    for idx, r in enumerate(blur):
        requested_radius = int(r.style.get("luma_radius", 18))
        power = int(r.style.get("luma_power", 3))
        # Keep radii legal for cropped yuv420p streams. Chroma planes are usually smaller
        # than luma planes, so explicitly set a smaller chroma radius instead of letting
        # ffmpeg copy the luma radius into chroma_radius.
        min_side = max(1, min(r.rect.w, r.rect.h))
        luma_radius = max(1, min(requested_radius, max(1, min_side // 2)))
        chroma_radius = max(1, min(requested_radius, max(1, min_side // 4)))
        enable = _expr_between(r.start, r.end)
        parts.append(
            f"[r{idx}src]crop=w={r.rect.w}:h={r.rect.h}:x={r.rect.x}:y={r.rect.y},"
            f"boxblur=luma_radius={luma_radius}:luma_power={power}:"
            f"chroma_radius={chroma_radius}:chroma_power={power}:enable='{enable}'[r{idx}]"
        )

    current = "base"
    for idx, r in enumerate(blur):
        out = output_label if idx == len(blur) - 1 else f"vblur{idx}"
        enable = _expr_between(r.start, r.end)
        parts.append(
            f"[{current}][r{idx}]overlay=x={r.rect.x}:y={r.rect.y}:"
            f"eof_action=pass:enable='{enable}'[{out}]"
        )
        current = out

    return ";\n".join(parts)


def write_filtergraph(path: Path, graph: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(graph + "\n", encoding="utf-8")
    return path
