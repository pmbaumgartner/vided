from __future__ import annotations

from pathlib import Path

from PIL import Image

from helpers import BasicProject, video_info
from vided import contact_sheet
from vided.contact_sheet import (
    NORMAL_BORDER,
    REDACTION_BORDER,
    compose_contact_sheet,
    frame_overlaps_redaction,
    redactions_at_timestamp,
    render_contact_sheet,
)
from vided.project import write_json
from vided.redactions import Rect, Redaction


def test_frame_overlap_uses_half_open_redaction_ranges() -> None:
    redactions = [
        Redaction(
            id="r1",
            start=1.0,
            end=2.0,
            rect=Rect(x=0, y=0, w=10, h=10),
            style={"type": "blur"},
        )
    ]

    assert not frame_overlaps_redaction(0.99, redactions)
    assert frame_overlaps_redaction(1.0, redactions)
    assert not frame_overlaps_redaction(2.0, redactions)
    assert not frame_overlaps_redaction(2.01, redactions)
    assert redactions_at_timestamp(1.0, redactions) == redactions
    assert redactions_at_timestamp(2.0, redactions) == []


def test_compose_contact_sheet_highlights_redacted_frames(tmp_path) -> None:
    first = tmp_path / "frame_000001.jpg"
    second = tmp_path / "frame_000002.jpg"
    Image.new("RGB", (100, 80), (10, 20, 30)).save(first)
    Image.new("RGB", (100, 80), (40, 50, 60)).save(second)
    output = tmp_path / "sheet.png"

    compose_contact_sheet(
        [first, second],
        timestamps=[1.0, 4.0],
        redactions=[
            Redaction(
                id="r1",
                start=0.5,
                end=1.5,
                rect=Rect(x=0, y=0, w=10, h=10),
                style={"type": "blur"},
            )
        ],
        output=output,
    )

    with Image.open(output) as sheet:
        rgb = sheet.convert("RGB")
        red = _hex_to_rgb(REDACTION_BORDER)
        normal = _hex_to_rgb(NORMAL_BORDER)
        assert rgb.getpixel((16, 16)) == red
        assert rgb.getpixel((140, 16)) == normal
        assert rgb.getpixel((90, 30)) == (10, 20, 30)
        assert any(
            rgb.getpixel((x, y)) != (10, 20, 30) for x in range(30, 96) for y in range(66, 98)
        )


def test_compose_contact_sheet_draws_preview_rectangles(tmp_path) -> None:
    frame = tmp_path / "frame_000001.jpg"
    Image.new("RGB", (100, 80), (10, 20, 30)).save(frame)
    output = tmp_path / "sheet.png"

    compose_contact_sheet(
        [frame],
        timestamps=[1.0],
        redactions=[
            Redaction(
                id="r1",
                start=0.5,
                end=1.5,
                rect=Rect(x=20, y=20, w=40, h=40),
                style={"type": "blur"},
            )
        ],
        output=output,
        draw_redaction_rectangles=True,
        video_size=(200, 160),
    )

    with Image.open(output) as sheet:
        rgb = sheet.convert("RGB")
        interior = rgb.getpixel((40, 40))
        assert rgb.getpixel((32, 32)) == _hex_to_rgb(REDACTION_BORDER)
        assert interior != (10, 20, 30)
        assert interior != _hex_to_rgb(REDACTION_BORDER)


def test_preview_blur_only_changes_redaction_region() -> None:
    image = Image.new("RGB", (20, 10), (0, 0, 0))
    for x in range(10, 20):
        for y in range(10):
            image.putpixel((x, y), (255, 255, 255))

    blurred = contact_sheet._blur_redaction_regions(
        image,
        [
            Redaction(
                id="r1",
                start=0.0,
                end=1.0,
                rect=Rect(x=8, y=0, w=4, h=10),
                style={"type": "blur"},
            )
        ],
        video_size=(20, 10),
    )

    assert blurred.getpixel((9, 5)) != image.getpixel((9, 5))
    assert blurred.getpixel((1, 5)) == image.getpixel((1, 5))


def test_render_contact_sheet_requires_trimmed_video_by_default(
    basic_project: BasicProject,
) -> None:
    project = basic_project.root

    try:
        render_contact_sheet(project)
    except FileNotFoundError as exc:
        assert "Run `vided trim` first" in str(exc)
    else:
        raise AssertionError("missing trimmed video should fail")


def test_render_contact_sheet_final_source_requires_final_video(
    basic_project: BasicProject,
) -> None:
    project = basic_project.root

    try:
        render_contact_sheet(project, source="final")
    except FileNotFoundError as exc:
        assert "Run `vided render" in str(exc)
    else:
        raise AssertionError("missing final video should fail")


def test_render_contact_sheet_refuses_existing_output(basic_project: BasicProject) -> None:
    project = basic_project.root
    p = basic_project.paths
    p.trimmed.write_bytes(b"trimmed")
    p.output_dir.mkdir()
    output = p.output_dir / "contact-sheet-preview.jpg"
    output.write_bytes(b"existing")

    try:
        render_contact_sheet(project)
    except FileExistsError as exc:
        assert "Use --overwrite" in str(exc)
    else:
        raise AssertionError("existing contact sheet should fail without overwrite")


def test_render_contact_sheet_extracts_from_final_video(
    basic_project: BasicProject, monkeypatch
) -> None:
    project = basic_project.root
    p = basic_project.paths
    p.output_dir.mkdir()
    final = p.output_dir / "final.mp4"
    final.write_bytes(b"final")
    write_json(
        p.redactions_json,
        {
            "video": {"duration": 2.0, "width": 20, "height": 10},
            "redactions": [
                {
                    "id": "r1",
                    "effective_start_seconds": 0.0,
                    "effective_end_seconds": 0.5,
                    "rect": {"x": 1, "y": 1, "w": 4, "h": 4},
                }
            ],
        },
    )
    calls: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.setattr(contact_sheet, "ensure_tool", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(contact_sheet, "probe_media", lambda path: video_info(path, duration=2.0))

    def fake_run_command(cmd: list[str], **kwargs: object) -> object:
        calls.append((cmd, kwargs))
        frame_path = Path(cmd[-1])
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (20, 10), (10, 20, 30)).save(frame_path)
        return object()

    monkeypatch.setattr(contact_sheet, "run_command", fake_run_command)

    output = render_contact_sheet(project, source="final", overwrite=True)

    assert output == p.output_dir / "contact-sheet.jpg"
    assert output.exists()
    assert [cmd[cmd.index("-ss") + 1] for cmd, _ in calls] == ["0.000000", "1.000000"]
    assert all(str(final) in cmd for cmd, _ in calls)
    assert all(kwargs == {"dry_run": False} for _, kwargs in calls)


def test_render_contact_sheet_preview_extracts_from_trimmed_video(
    basic_project: BasicProject, monkeypatch
) -> None:
    project = basic_project.root
    p = basic_project.paths
    p.trimmed.write_bytes(b"trimmed")
    write_json(
        p.redactions_json,
        {
            "video": {"duration": 2.0, "width": 20, "height": 10},
            "redactions": [
                {
                    "id": "r1",
                    "effective_start_seconds": 0.0,
                    "effective_end_seconds": 0.5,
                    "rect": {"x": 1, "y": 1, "w": 4, "h": 4},
                }
            ],
        },
    )
    calls: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.setattr(contact_sheet, "ensure_tool", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(contact_sheet, "probe_media", lambda path: video_info(path, duration=2.0))

    def fake_run_command(cmd: list[str], **kwargs: object) -> object:
        calls.append((cmd, kwargs))
        frame_path = Path(cmd[-1])
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (20, 10), (10, 20, 30)).save(frame_path)
        return object()

    monkeypatch.setattr(contact_sheet, "run_command", fake_run_command)

    output = render_contact_sheet(project, overwrite=True)

    assert output == p.output_dir / "contact-sheet-preview.jpg"
    assert output.exists()
    assert [cmd[cmd.index("-ss") + 1] for cmd, _ in calls] == ["0.000000", "1.000000"]
    assert all(str(p.trimmed) in cmd for cmd, _ in calls)
    assert all(kwargs == {"dry_run": False} for _, kwargs in calls)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
