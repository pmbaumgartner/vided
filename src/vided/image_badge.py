from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

Color = tuple[int, int, int, int]


@dataclass(frozen=True)
class BadgeStyle:
    box_fill: Color
    box_outline: Color
    text_fill: Color
    stroke_fill: Color


DARK_BADGE_STYLE = BadgeStyle(
    box_fill=(0, 0, 0, 166),
    box_outline=(255, 255, 255, 80),
    text_fill=(255, 255, 255, 255),
    stroke_fill=(0, 0, 0, 220),
)
LIGHT_BADGE_STYLE = BadgeStyle(
    box_fill=(255, 255, 255, 178),
    box_outline=(0, 0, 0, 84),
    text_fill=(0, 0, 0, 255),
    stroke_fill=(255, 255, 255, 230),
)


def render_text_badge(
    label: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    *,
    style: BadgeStyle,
) -> Image.Image:
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
    width = text_width + padding_x * 2
    height = text_height + padding_y * 2

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=max(6, round(height * 0.22)),
        fill=style.box_fill,
        outline=style.box_outline,
        width=1,
    )
    text_x = (width - text_width) / 2 - left
    text_y = (height - text_height) / 2 - top
    draw.text(
        (text_x, text_y),
        label,
        font=font,
        fill=style.text_fill,
        stroke_width=stroke_width,
        stroke_fill=style.stroke_fill,
    )
    return image
