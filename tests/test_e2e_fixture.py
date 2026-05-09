from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
from PIL import Image

from vided.contact_sheet import render_contact_sheet
from vided.ffmpeg import probe_media
from vided.project import create_project, paths
from vided.render import render_project
from vided.trimmer import TrimOptions, plan_trim, run_trim_plan


def _read_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


@pytest.mark.e2e
def test_realistic_fixture_compares_default_and_vad_trim(
    tmp_path: Path,
    realistic_short_fixture: Path,
    require_tools,
) -> None:
    require_tools("ffmpeg", "ffprobe")
    pytest.importorskip("onnxruntime")

    durations: dict[str, float] = {}
    for detector in ("audio", "vad"):
        project = tmp_path / detector
        create_project(realistic_short_fixture, project, copy_input=False)
        plan = plan_trim(project, options=TrimOptions(detector=detector), allow_vad_detection=True)
        output = run_trim_plan(plan, overwrite=True).path

        assert output.exists()
        durations[detector] = probe_media(output).duration

    report_path = tmp_path / "vad" / "work" / "vad_ranges.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert len(report["speech_ranges"]) >= 5
    assert 15.0 < durations["audio"] < 18.5
    assert 11.0 < durations["vad"] < 14.0
    assert durations["vad"] < durations["audio"] - 2.0


@pytest.mark.e2e
def test_full_fixture_generates_contact_sheets_with_multiple_redactions(
    prepared_full_e2e_project,
    served_ui,
) -> None:
    project = prepared_full_e2e_project.root
    frames = prepared_full_e2e_project.frames

    with served_ui(project) as base_url:
        assert _read_json(f"{base_url}/api/health") == {"ok": True}
        project_payload = _read_json(f"{base_url}/api/project")
        assert len(project_payload["frames"]["frames"]) == len(frames)

        with urlopen(f"{base_url}/{frames[0]['image']}", timeout=5) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "image/jpeg"

        redactions_path = paths(project).redactions_json
        payload = json.loads(redactions_path.read_text(encoding="utf-8"))
        payload["redactions"] = [
            {
                "id": "e2e-redaction-early",
                "selected_start_seconds": 5.0,
                "selected_end_seconds": 11.0,
                "rect": {"x": 60, "y": 40, "w": 180, "h": 140},
                "style": {"type": "blur", "filter": "boxblur", "luma_radius": 18},
            },
            {
                "id": "e2e-redaction-middle",
                "selected_start_seconds": 25.0,
                "selected_end_seconds": 31.0,
                "rect": {"x": 150, "y": 80, "w": 180, "h": 150},
                "style": {"type": "blur", "filter": "boxblur", "luma_radius": 18},
            },
            {
                "id": "e2e-redaction-late",
                "selected_start_seconds": 55.0,
                "selected_end_seconds": 61.0,
                "rect": {"x": 230, "y": 120, "w": 160, "h": 150},
                "style": {"type": "blur", "filter": "boxblur", "luma_radius": 18},
            },
        ]
        request = Request(
            f"{base_url}/api/redactions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urlopen(request, timeout=5) as response:
            assert len(json.loads(response.read().decode("utf-8"))["redactions"]) == 3

        redactions = _read_json(f"{base_url}/api/redactions")
        assert [redaction["id"] for redaction in redactions["redactions"]] == [
            "e2e-redaction-early",
            "e2e-redaction-middle",
            "e2e-redaction-late",
        ]

    preview_sheet = render_contact_sheet(project, overwrite=True)
    final_video = render_project(project, overwrite=True)
    final_sheet = render_contact_sheet(project, source="final", overwrite=True)
    final_info = probe_media(final_video)
    filtergraph = (project / "work" / "filtergraph.txt").read_text(encoding="utf-8")

    assert preview_sheet == paths(project).output_dir / "contact-sheet-preview.jpg"
    assert final_sheet == paths(project).output_dir / "contact-sheet.jpg"
    assert preview_sheet.exists()
    assert final_sheet.exists()
    assert final_video.exists()
    assert final_info.duration > 0
    assert abs(final_info.duration - prepared_full_e2e_project.trimmed_info.duration) < 0.75
    assert "boxblur" in filtergraph
    assert "overlay" in filtergraph

    with Image.open(preview_sheet) as preview, Image.open(final_sheet) as final:
        assert preview.size[0] > 0
        assert preview.size[1] > 0
        assert final.size == preview.size
