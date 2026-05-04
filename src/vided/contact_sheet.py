from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .ffmpeg import ensure_tool, probe_media, run_command
from .project import load_project, project_paths
from .redactions import Redaction, load_redactions, render_redactions

BACKGROUND = "#101218"
NORMAL_BORDER = "#303746"
REDACTION_BORDER = "#7db8ff"
CAPTION_TEXT = "#eef1f5"
_FONT_CANDIDATES = [
    "Arial Unicode.ttf",
    "DejaVuSans-Bold.ttf",
    "DejaVuSans.ttf",
    "NotoSansSymbols2-Regular.ttf",
    "NotoSansSymbols-Regular.ttf",
    "Segoe UI Symbol.ttf",
    "Apple Symbols.ttf",
    "Arial Bold.ttf",
    "Arial.ttf",
    "Helvetica.ttf",
]


def render_contact_sheet(
    project_root: Path,
    *,
    final_video: Path | None = None,
    output: Path | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> Path:
    cfg = load_project(project_root)
    p = project_paths(project_root, config=cfg)

    source = _resolve_final_video(p.root, p.output_dir, final_video)
    if not source.exists():
        raise FileNotFoundError(
            f"Final video not found: {source}. Run `vided render {p.root}` first."
        )

    if output is None:
        output = p.output_dir / "contact-sheet.jpg"
    elif not output.is_absolute():
        output = p.root / output

    if output.exists() and not overwrite and not dry_run:
        raise FileExistsError(
            f"Contact sheet already exists: {output}. Use --overwrite to replace it."
        )

    frame_cfg: dict[str, Any] = cfg.get("frames", {})
    interval_seconds = float(frame_cfg.get("interval_seconds", 1.0))
    thumbnail_width = int(frame_cfg.get("thumbnail_width", 640))
    if interval_seconds <= 0:
        raise ValueError("frames.interval_seconds must be greater than 0")
    if thumbnail_width <= 0:
        raise ValueError("frames.thumbnail_width must be greater than 0")

    ensure_tool("ffmpeg")
    work_dir = p.work_dir / "contact-sheet"
    frame_pattern = work_dir / "frame_%06d.jpg"
    fps = 1.0 / interval_seconds
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(source),
        "-vf",
        f"fps={fps:.8f},scale={thumbnail_width}:-2",
        "-q:v",
        "2",
        str(frame_pattern),
    ]

    if not dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

    run_command(cmd, dry_run=dry_run)
    if dry_run:
        return output

    frames = sorted(work_dir.glob("frame_*.jpg"))
    if not frames:
        raise ValueError(f"No frames were extracted from final video: {source}")

    info = probe_media(source)
    redactions = render_redactions(load_redactions(project_root))
    timestamps = [
        min(index * interval_seconds, max(info.duration, 0.0)) for index in range(len(frames))
    ]
    compose_contact_sheet(frames, timestamps=timestamps, redactions=redactions, output=output)
    return output


def compose_contact_sheet(
    frame_paths: list[Path],
    *,
    timestamps: list[float],
    redactions: list[Redaction],
    output: Path,
) -> Path:
    if len(frame_paths) != len(timestamps):
        raise ValueError("frame_paths and timestamps must have the same length")
    if not frame_paths:
        raise ValueError("contact sheet needs at least one frame")

    images = _load_images(frame_paths)
    tile_width = max(image.width for image in images)
    tile_height = max(image.height for image in images)
    columns = min(4, len(images))
    rows = math.ceil(len(images) / columns)
    padding = 16
    gap = 12
    border = 6
    cell_width = tile_width + border * 2
    cell_height = tile_height + border * 2
    width = padding * 2 + columns * cell_width + (columns - 1) * gap
    height = padding * 2 + rows * cell_height + (rows - 1) * gap

    sheet = Image.new("RGBA", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    font = _load_contact_sheet_font(_timestamp_font_size(tile_width, tile_height))

    for index, (image, timestamp) in enumerate(zip(images, timestamps, strict=True)):
        row, column = divmod(index, columns)
        x = padding + column * (cell_width + gap)
        y = padding + row * (cell_height + gap)
        image_x = x + border
        image_y = y + border
        redacted = frame_overlaps_redaction(timestamp, redactions)
        border_color = REDACTION_BORDER if redacted else NORMAL_BORDER
        border_width = border if redacted else 2

        draw.rectangle(
            [x, y, x + tile_width + border * 2 - 1, y + tile_height + border * 2 - 1],
            outline=border_color,
            width=border_width,
        )
        sheet.alpha_composite(image.convert("RGBA"), (image_x, image_y))
        _draw_timestamp_chip(
            sheet, (image_x, image_y), image.size, _format_seconds(timestamp), font
        )

    image_format = "PNG" if output.suffix.lower() == ".png" else "JPEG"
    if image_format == "JPEG":
        sheet.convert("RGB").save(output, format=image_format, quality=92)
    else:
        sheet.save(output, format=image_format)
    return output


def frame_overlaps_redaction(timestamp: float, redactions: list[Redaction]) -> bool:
    return any(redaction.start <= timestamp < redaction.end for redaction in redactions)


def _resolve_final_video(project_root: Path, output_dir: Path, final_video: Path | None) -> Path:
    if final_video is None:
        return output_dir / "final.mp4"
    if final_video.is_absolute():
        return final_video
    return project_root / final_video


def _load_images(paths: list[Path]) -> list[Image.Image]:
    images: list[Image.Image] = []
    for path in paths:
        with Image.open(path) as image:
            images.append(image.convert("RGB"))
    return images


def _load_contact_sheet_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _timestamp_font_size(tile_width: int, tile_height: int) -> int:
    short_edge = max(1, min(tile_width, tile_height))
    return max(12, min(34, int(round(short_edge * 0.052))))


def _draw_timestamp_chip(
    sheet: Image.Image,
    image_origin: tuple[int, int],
    image_size: tuple[int, int],
    label: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    font_size = max(12, int(getattr(font, "size", 16)))
    stroke_width = max(1, round(font_size * 0.08))
    padding_x = max(8, round(font_size * 0.55))
    padding_y = max(5, round(font_size * 0.35))
    left, top, right, bottom = measure.textbbox(
        (0, 0),
        label,
        font=font,
        stroke_width=stroke_width,
    )
    text_width = int(math.ceil(right - left))
    text_height = int(math.ceil(bottom - top))
    chip_width = text_width + padding_x * 2
    chip_height = text_height + padding_y * 2
    inset = max(8, round(min(image_size) * 0.025))
    chip_x = image_origin[0] + inset
    chip_y = image_origin[1] + image_size[1] - chip_height - inset

    overlay = Image.new("RGBA", sheet.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(
        (chip_x, chip_y, chip_x + chip_width - 1, chip_y + chip_height - 1),
        radius=max(6, round(chip_height * 0.22)),
        fill=(0, 0, 0, 166),
        outline=(255, 255, 255, 80),
        width=1,
    )
    text_x = chip_x + padding_x - left
    text_y = chip_y + padding_y - top
    draw.text(
        (text_x, text_y),
        label,
        font=font,
        fill=(255, 255, 255, 255),
        stroke_width=stroke_width,
        stroke_fill=(0, 0, 0, 220),
    )
    sheet.alpha_composite(overlay)


def _format_seconds(seconds: float) -> str:
    seconds = max(0.0, seconds)
    whole = int(seconds)
    tenths = int(round((seconds - whole) * 10))
    if tenths == 10:
        whole += 1
        tenths = 0
    minutes, second = divmod(whole, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minute:02d}:{second:02d}.{tenths:d}"
    return f"{minute:02d}:{second:02d}.{tenths:d}"
