from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading

import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    BrowserType,
    Error as PlaywrightError,
    Page,
    expect,
)

from vided.ffmpeg import probe_media
from vided.frames import generate_frames
from vided.project import create_project
from vided.render import render_project
from vided.trimmer import run_trim
from vided.ui_server import make_handler


FIXTURE = Path(__file__).parent / "fixtures" / "media" / "realistic-speech-gaps-short.mp4"


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        pytest.skip(f"{name} is required for browser e2e tests")


def _require_realistic_fixture() -> Path:
    if not FIXTURE.exists():
        pytest.skip(f"fixture is missing: {FIXTURE}")
    if FIXTURE.stat().st_size < 1024:
        pytest.skip(f"fixture appears to be a Git LFS pointer: {FIXTURE}")
    return FIXTURE


def _new_page(browser_type: BrowserType) -> tuple[Browser, BrowserContext, Page]:
    try:
        browser = browser_type.launch()
    except PlaywrightError as exc:
        message = str(exc)
        if "Executable doesn't exist" in message or "playwright install" in message:
            pytest.skip(
                "Playwright browser is not installed; run `uv run playwright install chromium`"
            )
        raise

    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    return browser, context, page


@pytest.mark.e2e
@pytest.mark.browser
def test_short_fixture_browser_workflow_renders_final_output(
    tmp_path: Path,
    browser_type: BrowserType,
) -> None:
    _require_tool("ffmpeg")
    _require_tool("ffprobe")
    source = _require_realistic_fixture()

    project = tmp_path / "browser-project"
    create_project(source, project, copy_input=False)
    trimmed = run_trim(project, overwrite=True)
    trimmed_info = probe_media(trimmed)
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
    browser, context, page = _new_page(browser_type)

    try:
        page.goto(base_url)
        expect(page.locator("#projectMeta")).to_contain_text("thumbnails")
        page.wait_for_function(
            """
            () => {
              const canvas = document.querySelector("#frameCanvas");
              return canvas && canvas.width > 0 && canvas.height > 0;
            }
            """
        )

        page.locator("#setStartButton").click()
        canvas = page.locator("#frameCanvas")
        box = canvas.bounding_box()
        assert box is not None
        page.mouse.move(box["x"] + box["width"] * 0.25, box["y"] + box["height"] * 0.25)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] * 0.65, box["y"] + box["height"] * 0.65)
        page.mouse.up()

        page.locator("#filmstrip .thumb").nth(1).click()
        expect(page.locator("#currentFrameLabel")).to_have_text("Frame 2")
        add_button = page.locator("#saveDraftButton")
        expect(add_button).to_be_enabled()
        with page.expect_response(
            lambda response: (
                response.url.endswith("/api/redactions")
                and response.request.method == "PUT"
                and response.status == 200
            )
        ):
            add_button.click()

        expect(page.locator("#saveState")).to_have_text("Saved")
        expect(page.locator(".redaction-row")).to_have_count(1)
    finally:
        context.close()
        browser.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    redactions = json.loads((project / "redactions.json").read_text(encoding="utf-8"))
    assert len(redactions["redactions"]) == 1
    rect = redactions["redactions"][0]["rect"]
    assert rect["w"] > 0
    assert rect["h"] > 0

    final_output = render_project(project, overwrite=True)
    final_info = probe_media(final_output)
    filtergraph = (project / "work" / "filtergraph.txt").read_text(encoding="utf-8")

    assert final_output.exists()
    assert final_info.duration > 0
    assert abs(final_info.duration - trimmed_info.duration) < 0.75
    assert "boxblur" in filtergraph
    assert "overlay" in filtergraph
