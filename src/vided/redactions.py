from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .project import paths, read_json, write_json


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Redaction:
    id: str
    start: float
    end: float
    rect: Rect
    style: dict[str, Any]


def load_redactions(project_root: Path) -> dict[str, Any]:
    return read_json(paths(project_root).redactions_json, default={"redactions": []})


def save_redactions(project_root: Path, data: dict[str, Any]) -> None:
    write_json(paths(project_root).redactions_json, data)


def parse_redactions(data: dict[str, Any]) -> list[Redaction]:
    video = data.get("video", {})
    duration = float(video.get("duration") or 0.0)
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    defaults = data.get("defaults", {})
    default_style = defaults.get("style", {})

    parsed: list[Redaction] = []
    for index, item in enumerate(data.get("redactions", [])):
        rect_raw = item.get("rect", {})
        rect = Rect(
            x=int(round(float(rect_raw.get("x", 0)))),
            y=int(round(float(rect_raw.get("y", 0)))),
            w=int(round(float(rect_raw.get("w", 0)))),
            h=int(round(float(rect_raw.get("h", 0)))),
        )

        selected_start = float(item.get("selected_start_seconds", item.get("start", 0.0)))
        selected_end = float(item.get("selected_end_seconds", item.get("end", selected_start)))
        if selected_end < selected_start:
            selected_start, selected_end = selected_end, selected_start

        pre = float(item.get("buffer_pre_seconds", defaults.get("buffer_pre_seconds", 0.0)))
        post = float(item.get("buffer_post_seconds", defaults.get("buffer_post_seconds", 0.0)))
        start = float(item.get("effective_start_seconds", max(0.0, selected_start - pre)))
        end = float(item.get("effective_end_seconds", selected_end + post))
        if duration > 0:
            end = min(duration, end)
        start = max(0.0, start)

        style = item.get("style") or default_style or {"type": "blur"}
        rid = str(item.get("id") or f"redaction_{index + 1:03d}")

        validate_redaction(rid, start, end, rect, width=width, height=height)
        parsed.append(Redaction(id=rid, start=start, end=end, rect=rect, style=style))
    return parsed


def validate_redaction(
    redaction_id: str,
    start: float,
    end: float,
    rect: Rect,
    *,
    width: int,
    height: int,
) -> None:
    if start >= end:
        raise ValueError(f"{redaction_id}: start must be before end")
    if rect.w <= 0 or rect.h <= 0:
        raise ValueError(f"{redaction_id}: rectangle width and height must be greater than 0")
    if rect.x < 0 or rect.y < 0:
        raise ValueError(f"{redaction_id}: rectangle x/y cannot be negative")
    if width and rect.x + rect.w > width:
        raise ValueError(f"{redaction_id}: rectangle extends beyond video width")
    if height and rect.y + rect.h > height:
        raise ValueError(f"{redaction_id}: rectangle extends beyond video height")
