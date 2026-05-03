from __future__ import annotations

import json
import mimetypes
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .project import paths, read_json, write_json
from .redactions import parse_redactions

STATIC_DIR = Path(__file__).parent / "static"


def _json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    raw = json.dumps(payload, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _error(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
    _json_response(handler, {"error": message}, status=status)


def _safe_join(base: Path, relative: str) -> Path | None:
    relative = unquote(relative).lstrip("/")
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return None
    return candidate


def make_handler(project_root: Path):
    p = paths(project_root)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            print(f"[ui] {self.address_string()} - {format % args}")

        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            parsed = urlparse(self.path)
            route = parsed.path
            try:
                if route == "/" or route == "/index.html":
                    self._send_file(STATIC_DIR / "index.html")
                elif route.startswith("/static/"):
                    file = _safe_join(STATIC_DIR, route.removeprefix("/static/"))
                    if file is None:
                        _error(self, 400, "Invalid static path")
                    else:
                        self._send_file(file)
                elif route.startswith("/frames/"):
                    file = _safe_join(p.frames_dir, route.removeprefix("/frames/"))
                    if file is None:
                        _error(self, 400, "Invalid frame path")
                    else:
                        self._send_file(file)
                elif route == "/api/project":
                    self._send_project()
                elif route == "/api/redactions":
                    _json_response(self, read_json(p.redactions_json, default={"redactions": []}))
                elif route == "/api/health":
                    _json_response(self, {"ok": True})
                else:
                    _error(self, 404, f"Not found: {route}")
            except Exception as exc:  # intentionally broad for a local dev server
                _error(self, 500, str(exc))

        def do_POST(self) -> None:  # noqa: N802
            self._handle_write()

        def do_PUT(self) -> None:  # noqa: N802
            self._handle_write()

        def _handle_write(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/api/redactions":
                _error(self, 404, f"Not found: {parsed.path}")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                payload = json.loads(body)
                parse_redactions(payload)  # validation
                write_json(p.redactions_json, payload)
                _json_response(self, {"ok": True, "redactions": payload.get("redactions", [])})
            except Exception as exc:
                _error(self, 400, str(exc))

        def _send_project(self) -> None:
            project = read_json(p.project_json, default={})
            frames = read_json(p.frames_json, default={"frames": []})
            redactions = read_json(p.redactions_json, default={"redactions": []})
            _json_response(
                self,
                {
                    "project": project,
                    "frames": frames,
                    "redactions": redactions,
                },
            )

        def _send_file(self, path: Path) -> None:
            if not path.exists() or not path.is_file():
                _error(self, 404, f"File not found: {path.name}")
                return
            content_type, _ = mimetypes.guess_type(str(path))
            content_type = content_type or "application/octet-stream"
            raw = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return Handler


def run_ui(
    project_root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    p = paths(project_root)
    if not p.project_json.exists():
        raise FileNotFoundError(f"Project not found: {p.project_json}")
    if not p.frames_json.exists():
        print("Warning: frames.json not found. Run `vided frames` before opening the UI.")

    server = ThreadingHTTPServer((host, port), make_handler(project_root))
    url = f"http://{host}:{port}/"
    print(f"Serving annotation UI at {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping UI server.")
    finally:
        server.server_close()
