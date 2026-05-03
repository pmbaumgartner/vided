from __future__ import annotations

from vided.redactions import render_redactions, validate_redaction_document


def test_validate_redaction_document_preserves_selected_times_and_buffers() -> None:
    payload = {
        "schema_version": 1,
        "video": {"width": 1920, "height": 1080, "duration": 10.0},
        "defaults": {"buffer_pre_seconds": 0.25, "buffer_post_seconds": 0.5},
        "redactions": [
            {
                "id": "face",
                "selected_start_seconds": 2.0,
                "selected_end_seconds": 3.0,
                "buffer_pre_seconds": 0.75,
                "rect": {"x": 10, "y": 20, "w": 100, "h": 80},
            }
        ],
    }

    document = validate_redaction_document(payload)
    rendered = render_redactions(payload)

    assert document.data is payload
    assert document.redactions[0]["selected_start_seconds"] == 2.0
    assert document.redactions[0]["buffer_pre_seconds"] == 0.75
    assert rendered[0].start == 1.25
    assert rendered[0].end == 3.5
