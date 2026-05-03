from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading

import pytest

from vided.ffmpeg import VideoInfo, probe_media
from vided.frames import generate_frames
from vided.project import create_project
from vided.trimmer import run_trim
from vided.ui_server import make_handler


REALISTIC_SHORT_FIXTURE = (
    Path(__file__).parent / "fixtures" / "media" / "realistic-speech-gaps-short.mp4"
)


@dataclass(frozen=True)
class PreparedE2EProject:
    root: Path
    trimmed: Path
    trimmed_info: VideoInfo
    frames_json: Path
    frames: list[dict[str, object]]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="run e2e tests that use real media and external tools",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-e2e"):
        return
    skip_e2e = pytest.mark.skip(reason="use --run-e2e to run e2e tests")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)


@pytest.fixture
def realistic_short_fixture() -> Path:
    if not REALISTIC_SHORT_FIXTURE.exists():
        pytest.skip(f"fixture is missing: {REALISTIC_SHORT_FIXTURE}")
    if REALISTIC_SHORT_FIXTURE.stat().st_size < 1024:
        pytest.skip(f"fixture appears to be a Git LFS pointer: {REALISTIC_SHORT_FIXTURE}")
    return REALISTIC_SHORT_FIXTURE


@pytest.fixture
def require_tools() -> Callable[..., None]:
    def _require(*names: str) -> None:
        for name in names:
            if shutil.which(name) is None:
                pytest.skip(f"{name} is required for e2e tests")

    return _require


@pytest.fixture
def prepared_e2e_project(
    tmp_path: Path,
    realistic_short_fixture: Path,
    require_tools: Callable[..., None],
) -> PreparedE2EProject:
    require_tools("ffmpeg", "ffprobe")

    project = tmp_path / "e2e-project"
    create_project(realistic_short_fixture, project, copy_input=False)
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

    return PreparedE2EProject(
        root=project,
        trimmed=trimmed,
        trimmed_info=trimmed_info,
        frames_json=frames_json,
        frames=frames,
    )


@pytest.fixture
def served_ui() -> Callable[[Path], AbstractContextManager[str]]:
    @contextmanager
    def _served(project: Path) -> Iterator[str]:
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(project))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    return _served
