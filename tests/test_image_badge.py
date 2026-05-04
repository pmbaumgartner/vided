from __future__ import annotations

from PIL import ImageFont

from vided.image_badge import DARK_BADGE_STYLE, LIGHT_BADGE_STYLE, render_text_badge


def test_render_text_badge_generates_non_empty_rgba_image() -> None:
    font = ImageFont.load_default(size=16)

    image = render_text_badge("1.25s", font, style=DARK_BADGE_STYLE)

    assert image.mode == "RGBA"
    assert image.size[0] > 0
    assert image.size[1] > 0
    assert image.getchannel("A").getbbox() is not None


def test_render_text_badge_applies_style_and_scales_with_font() -> None:
    small_font = ImageFont.load_default(size=14)
    large_font = ImageFont.load_default(size=28)

    dark = render_text_badge("8x", small_font, style=DARK_BADGE_STYLE)
    light = render_text_badge("8x", small_font, style=LIGHT_BADGE_STYLE)
    large = render_text_badge("8x", large_font, style=DARK_BADGE_STYLE)

    assert dark.tobytes() != light.tobytes()
    assert large.size[0] > dark.size[0]
    assert large.size[1] > dark.size[1]
