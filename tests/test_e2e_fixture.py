from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from vided.ffmpeg import probe_media
from vided.project import create_project, paths
from vided.trimmer import run_trim


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
    for detector in ("audio", "silero"):
        project = tmp_path / detector
        create_project(realistic_short_fixture, project, copy_input=False)
        output = run_trim(project, detector=detector, overwrite=True)

        assert output.exists()
        durations[detector] = probe_media(output).duration

    report_path = tmp_path / "silero" / "work" / "vad_ranges.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert len(report["speech_ranges"]) >= 5
    assert 15.0 < durations["audio"] < 18.5
    assert 11.0 < durations["silero"] < 14.0
    assert durations["silero"] < durations["audio"] - 2.0


@pytest.mark.e2e
def test_realistic_fixture_generates_frames_and_serves_ui_api(
    prepared_e2e_project,
    served_ui,
) -> None:
    project = prepared_e2e_project.root
    frames = prepared_e2e_project.frames

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
                "id": "e2e-redaction",
                "selected_start_seconds": 1.0,
                "selected_end_seconds": 2.0,
                "rect": {"x": 10, "y": 20, "w": 80, "h": 60},
                "style": {"type": "blur", "filter": "boxblur", "luma_radius": 18},
            }
        ]
        request = Request(
            f"{base_url}/api/redactions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urlopen(request, timeout=5) as response:
            assert json.loads(response.read().decode("utf-8"))["redactions"][0]["id"] == (
                "e2e-redaction"
            )

        redactions = _read_json(f"{base_url}/api/redactions")
        assert redactions["redactions"][0]["id"] == "e2e-redaction"
