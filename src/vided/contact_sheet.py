from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .ffmpeg import ensure_tool, probe_media, run_command
from .frames import FrameExtractionOptions, resolve_frame_extraction_options
from .image_badge import DARK_BADGE_STYLE, render_text_badge
from .project import load_project, project_paths
from .redactions import Redaction, load_redactions, render_redactions

BACKGROUND = "#101218"
NORMAL_BORDER = "#303746"
REDACTION_BORDER = "#7db8ff"
REDACTION_FILL = (125, 184, 255, 34)
CAPTION_TEXT = "#eef1f5"
ContactSheetSource = Literal["preview", "final"]
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
    source: ContactSheetSource = "preview",
    final_video: Path | None = None,
    output: Path | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> Path:
    cfg = load_project(project_root)
    p = project_paths(project_root, config=cfg)

    if source not in {"preview", "final"}:
        raise ValueError("contact sheet source must be 'preview' or 'final'")
    if final_video is not None and source != "final":
        raise ValueError("--final-video can only be used with --source final.")

    video = _resolve_contact_sheet_video(p.root, p.output_dir, p.trimmed, source, final_video)
    if not video.exists():
        if source == "preview":
            raise FileNotFoundError(f"Trimmed video not found: {video}. Run `vided trim` first.")
        raise FileNotFoundError(
            f"Final video not found: {video}. Run `vided render {p.root}` first."
        )

    if output is None:
        output = p.output_dir / (
            "contact-sheet-preview.jpg" if source == "preview" else "contact-sheet.jpg"
        )
    elif not output.is_absolute():
        output = p.root / output

    if output.exists() and not overwrite and not dry_run:
        raise FileExistsError(
            f"Contact sheet already exists: {output}. Use --overwrite to replace it."
        )

    ensure_tool("ffmpeg")
    options = resolve_frame_extraction_options(cfg, error_prefix="frames.")
    info = probe_media(video)
    timestamps = _contact_sheet_timestamps(info.duration, options.interval_seconds)

    work_dir = p.work_dir / f"contact-sheet-{source}"
    frame_paths = [work_dir / f"frame_{index + 1:06d}.jpg" for index in range(len(timestamps))]

    if not dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

    for timestamp, frame_path in zip(timestamps, frame_paths, strict=True):
        cmd = _build_contact_sheet_frame_command(
            video,
            frame_path,
            timestamp=timestamp,
            options=options,
        )
        run_command(cmd, dry_run=dry_run)
    if dry_run:
        return output

    frames = sorted(work_dir.glob("frame_*.jpg"))
    if not frames:
        raise ValueError(f"No frames were extracted from {source} video: {video}")

    redactions = render_redactions(load_redactions(project_root))
    compose_contact_sheet(
        frames,
        timestamps=timestamps,
        redactions=redactions,
        output=output,
        draw_redaction_rectangles=source == "preview",
        video_size=(info.width, info.height),
    )
    return output


def _contact_sheet_timestamps(duration: float, interval_seconds: float) -> list[float]:
    sample_count = max(1, math.ceil(max(duration, 0.0) / interval_seconds))
    return [round(index * interval_seconds, 6) for index in range(sample_count)]


def _build_contact_sheet_frame_command(
    source: Path,
    output: Path,
    *,
    timestamp: float,
    options: FrameExtractionOptions,
) -> list[str]:
    # Seek each tile by timestamp so labels, borders, and pixels describe the same instant.
    return [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-ss",
        f"{timestamp:.6f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        f"scale={options.thumbnail_width}:-2",
        "-q:v",
        "2",
        "-update",
        "1",
        str(output),
    ]


def compose_contact_sheet(
    frame_paths: list[Path],
    *,
    timestamps: list[float],
    redactions: list[Redaction],
    output: Path,
    draw_redaction_rectangles: bool = False,
    video_size: tuple[int, int] | None = None,
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
    draw = ImageDraw.Draw(sheet, "RGBA")
    font = _load_contact_sheet_font(_timestamp_font_size(tile_width, tile_height))

    for index, (image, timestamp) in enumerate(zip(images, timestamps, strict=True)):
        row, column = divmod(index, columns)
        x = padding + column * (cell_width + gap)
        y = padding + row * (cell_height + gap)
        image_x = x + border
        image_y = y + border
        active_redactions = redactions_at_timestamp(timestamp, redactions)
        redacted = bool(active_redactions)
        border_color = REDACTION_BORDER if redacted else NORMAL_BORDER
        border_width = border if redacted else 2
        display_image = image
        if draw_redaction_rectangles:
            display_image = _blur_redaction_regions(
                image,
                active_redactions,
                video_size=video_size,
            )

        draw.rectangle(
            [x, y, x + tile_width + border * 2 - 1, y + tile_height + border * 2 - 1],
            outline=border_color,
            width=border_width,
        )
        sheet.alpha_composite(display_image.convert("RGBA"), (image_x, image_y))
        if draw_redaction_rectangles:
            _draw_redaction_rectangles(
                sheet,
                active_redactions,
                video_size=video_size,
                image_origin=(image_x, image_y),
                image_size=display_image.size,
            )
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
    return bool(redactions_at_timestamp(timestamp, redactions))


def redactions_at_timestamp(timestamp: float, redactions: list[Redaction]) -> list[Redaction]:
    return [redaction for redaction in redactions if redaction.start <= timestamp < redaction.end]


def _draw_redaction_rectangles(
    sheet: Image.Image,
    redactions: list[Redaction],
    *,
    video_size: tuple[int, int] | None,
    image_origin: tuple[int, int],
    image_size: tuple[int, int],
) -> None:
    if not redactions or video_size is None:
        return
    video_width, video_height = video_size
    if video_width <= 0 or video_height <= 0:
        return

    outline_width = max(2, round(min(image_size) * 0.015))
    boxes: list[tuple[int, int, int, int]] = []
    for redaction in redactions:
        box = _scaled_redaction_box(
            redaction,
            video_size=video_size,
            image_origin=image_origin,
            image_size=image_size,
        )
        if box is None:
            continue
        boxes.append(box)

    if not boxes:
        return

    overlay = Image.new("RGBA", sheet.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay, "RGBA")
    for box in boxes:
        overlay_draw.rectangle(box, fill=REDACTION_FILL)
    sheet.alpha_composite(overlay)

    outline_draw = ImageDraw.Draw(sheet)
    for box in boxes:
        outline_draw.rectangle(box, outline=REDACTION_BORDER, width=outline_width)


def _blur_redaction_regions(
    image: Image.Image,
    redactions: list[Redaction],
    *,
    video_size: tuple[int, int] | None,
) -> Image.Image:
    if not redactions or video_size is None:
        return image

    blurred_image = image.copy()
    radius = max(2, round(min(image.size) * 0.035))
    for redaction in redactions:
        box = _scaled_redaction_box(
            redaction,
            video_size=video_size,
            image_origin=(0, 0),
            image_size=image.size,
        )
        if box is None:
            continue
        crop = blurred_image.crop(_inclusive_box_to_crop_box(box))
        blurred_image.paste(crop.filter(ImageFilter.GaussianBlur(radius=radius)), box[:2])
    return blurred_image


def _scaled_redaction_box(
    redaction: Redaction,
    *,
    video_size: tuple[int, int],
    image_origin: tuple[int, int],
    image_size: tuple[int, int],
) -> tuple[int, int, int, int] | None:
    video_width, video_height = video_size
    image_x, image_y = image_origin
    image_width, image_height = image_size
    sx = image_width / video_width
    sy = image_height / video_height
    x0 = image_x + round(redaction.rect.x * sx)
    y0 = image_y + round(redaction.rect.y * sy)
    x1 = image_x + round((redaction.rect.x + redaction.rect.w) * sx)
    y1 = image_y + round((redaction.rect.y + redaction.rect.h) * sy)
    x0 = _clamp(x0, image_x, image_x + image_width - 1)
    y0 = _clamp(y0, image_y, image_y + image_height - 1)
    x1 = _clamp(x1, image_x, image_x + image_width - 1)
    y1 = _clamp(y1, image_y, image_y + image_height - 1)
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _inclusive_box_to_crop_box(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return x0, y0, x1 + 1, y1 + 1


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def _resolve_final_video(project_root: Path, output_dir: Path, final_video: Path | None) -> Path:
    if final_video is None:
        return output_dir / "final.mp4"
    if final_video.is_absolute():
        return final_video
    return project_root / final_video


def _resolve_contact_sheet_video(
    project_root: Path,
    output_dir: Path,
    trimmed: Path,
    source: ContactSheetSource,
    final_video: Path | None,
) -> Path:
    if source == "preview":
        return trimmed
    return _resolve_final_video(project_root, output_dir, final_video)


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
    chip = render_text_badge(label, font, style=DARK_BADGE_STYLE)
    inset = max(8, round(min(image_size) * 0.025))
    chip_x = image_origin[0] + inset
    chip_y = image_origin[1] + image_size[1] - chip.height - inset
    sheet.alpha_composite(chip, (chip_x, chip_y))


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
