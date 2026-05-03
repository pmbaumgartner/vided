from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading
from urllib.request import Request, urlopen

import pytest

from vided.ffmpeg import probe_media
from vided.frames import generate_frames
from vided.project import create_project, paths
from vided.trimmer import run_trim
from vided.ui_server import make_handler


FIXTURE = Path(__file__).parent / "fixtures" / "media" / "realistic-speech-gaps-short.mp4"


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        pytest.skip(f"{name} is required for e2e tests")


def _require_realistic_fixture() -> Path:
    if not FIXTURE.exists():
        pytest.skip(f"fixture is missing: {FIXTURE}")
    if FIXTURE.stat().st_size < 1024:
        pytest.skip(f"fixture appears to be a Git LFS pointer: {FIXTURE}")
    return FIXTURE


def _read_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


@pytest.mark.e2e
def test_realistic_fixture_compares_default_and_vad_trim(tmp_path: Path) -> None:
    _require_tool("ffmpeg")
    _require_tool("ffprobe")
    pytest.importorskip("onnxruntime")
    source = _require_realistic_fixture()

    durations: dict[str, float] = {}
    for detector in ("audio", "silero"):
        project = tmp_path / detector
        create_project(source, project, copy_input=False)
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
def test_realistic_fixture_generates_frames_and_serves_ui_api(tmp_path: Path) -> None:
    _require_tool("ffmpeg")
    _require_tool("ffprobe")
    source = _require_realistic_fixture()

    project = tmp_path / "ui-project"
    create_project(source, project, copy_input=False)
    run_trim(project, overwrite=True)
    frames_json = generate_frames(
        project,
        interval_seconds=5.0,
        thumbnail_width=160,
        overwrite=True,
    )
    frames = json.loads(frames_json.read_text(encoding="utf-8"))["frames"]
    assert len(frames) >= 3

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(project))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    try:
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
            assert json.loads(response.read().decode("utf-8"))["ok"] is True

        redactions = _read_json(f"{base_url}/api/redactions")
        assert redactions["redactions"][0]["id"] == "e2e-redaction"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
