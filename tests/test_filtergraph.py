from vided.filtergraph import build_final_filtergraph
from vided.redactions import Rect, Redaction


def test_final_filtergraph_contains_crop_blur_and_overlay() -> None:
    graph = build_final_filtergraph(
        [
            Redaction(
                id="r1",
                start=1.0,
                end=2.0,
                rect=Rect(x=10, y=20, w=100, h=80),
                style={"type": "blur", "luma_radius": 18, "luma_power": 3},
            )
        ]
    )
    assert "crop=w=100:h=80:x=10:y=20" in graph
    assert "boxblur=luma_radius=18:luma_power=3:chroma_radius=18:chroma_power=3" in graph
    assert "overlay=x='if(between(t\\,1.000000\\,2.000000)\\,10\\,NAN)'" in graph
    assert "[vout]" in graph


def test_chroma_radius_is_clamped_for_small_rectangles() -> None:
    graph = build_final_filtergraph(
        [
            Redaction(
                id="r1",
                start=1.0,
                end=2.0,
                rect=Rect(x=10, y=20, w=10, h=6),
                style={"type": "blur", "luma_radius": 99, "luma_power": 3},
            )
        ]
    )
    assert "boxblur=luma_radius=3:luma_power=3:chroma_radius=1:chroma_power=3" in graph
