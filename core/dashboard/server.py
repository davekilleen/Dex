#!/usr/bin/env python3
"""Serve one interactive Dex Dashboard on loopback for a bounded time."""

from __future__ import annotations

import argparse
import hmac
import json
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.dashboard.toggles import (
    StateSnapshot,
    ToggleConflictError,
    ToggleEngine,
    ToggleError,
    ToggleSchemaError,
)

MAX_REQUEST_BYTES = 64 * 1024
TOKEN_PLACEHOLDER = "__DEX_DASHBOARD_TOKEN__"
PORT_PLACEHOLDER = "__DEX_DASHBOARD_PORT__"


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    body: bytes
    headers: dict[str, str]


def _json_response(status: int, payload: dict[str, Any]) -> HTTPResponse:
    return HTTPResponse(
        status=status,
        body=(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


def _html_response(body: bytes) -> HTTPResponse:
    return HTTPResponse(
        status=200,
        body=body,
        headers={
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'; "
                "img-src data:; base-uri 'none'; form-action 'none'"
            ),
        },
    )


def _inline_script_text(value: str) -> str:
    return (
        json.dumps(value, ensure_ascii=False)[1:-1]
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _default_browser_open(url: str) -> bool:
    """Open a browser, with macOS's native launcher as a fallback."""
    try:
        if webbrowser.open(url):
            return True
    except (OSError, webbrowser.Error):
        pass
    if sys.platform != "darwin":
        return False
    try:
        return subprocess.run(["open", url], check=False).returncode == 0
    except OSError:
        return False


class ToggleSession:
    """Keep the last GET stamps so POST can reject external file changes."""

    def __init__(self, engine: ToggleEngine) -> None:
        self.engine = engine
        self.snapshot: StateSnapshot | None = None
        self._lock = threading.Lock()

    def read_state(self) -> StateSnapshot:
        with self._lock:
            self.snapshot = self.engine.read_state()
            return self.snapshot

    def write(self, setting_id: str, value: Any):
        with self._lock:
            if self.snapshot is None:
                raise ToggleConflictError("Refresh the dashboard before changing a setting.")
            expected = self.snapshot.stamps.get(setting_id)
            result = self.engine.write(setting_id, value, expected=expected)
            values = dict(self.snapshot.values)
            values[setting_id] = result.new
            stamps = {
                candidate_id: result.stamp if stamp == expected else stamp
                for candidate_id, stamp in self.snapshot.stamps.items()
            }
            self.snapshot = StateSnapshot(
                values=values,
                stamps=stamps,
                unavailable=dict(self.snapshot.unavailable),
            )
            return result


class DashboardApplication:
    """Socket-independent request handler used by the HTTP adapter and tests."""

    def __init__(
        self,
        *,
        vault: Path | str,
        html_path: Path | str,
        token: str,
        port: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.vault = Path(vault).expanduser().resolve()
        self.html_path = Path(html_path).expanduser().resolve()
        self.token = token
        self.port = port
        self.clock = clock
        self.last_activity = clock()
        self.close_requested = threading.Event()
        self.session = ToggleSession(ToggleEngine(self.vault))
        self._activity_lock = threading.Lock()

    def handle(self, method: str, target: str, body: bytes = b"") -> HTTPResponse:
        self._touch()
        parsed = urlsplit(target)
        if not self._authorized(parsed.query):
            return _json_response(403, {"error": "Forbidden"})
        return self._handle_authorized(method, parsed.path, body)

    def authorize_target(self, target: str) -> bool:
        """Authenticate before the HTTP adapter reads or validates a POST body."""
        self._touch()
        return self._authorized(urlsplit(target).query)

    def _handle_authorized(self, method: str, path: str, body: bytes) -> HTTPResponse:
        try:
            if method == "GET" and path == "/":
                return self._serve_page()
            if method == "GET" and path == "/api/state":
                snapshot = self.session.read_state()
                return _json_response(
                    200,
                    {
                        "settings": snapshot.values,
                        "unavailable": snapshot.unavailable,
                    },
                )
            if method == "POST" and path == "/api/toggle":
                return self._toggle(body)
            if method == "POST" and path == "/api/close":
                self.close_requested.set()
                return _json_response(200, {"ok": True})
            if path in {"/", "/api/state", "/api/toggle", "/api/close"}:
                return _json_response(405, {"error": "Method not allowed"})
            return _json_response(404, {"error": "Not found"})
        except ToggleError as error:
            scoped_schema_write = (
                method == "POST"
                and path == "/api/toggle"
                and isinstance(error, ToggleSchemaError)
            )
            if error.status_code == 409 and not scoped_schema_write:
                self.session.snapshot = None
            return _json_response(error.status_code, {"error": str(error)})
        except (OSError, UnicodeError):
            return _json_response(500, {"error": "Dex could not read or save the local settings."})

    def idle_for(self) -> float:
        with self._activity_lock:
            return self.clock() - self.last_activity

    def _touch(self) -> None:
        with self._activity_lock:
            self.last_activity = self.clock()

    def _authorized(self, query: str) -> bool:
        supplied = parse_qs(query, keep_blank_values=True).get("t", [])
        candidate = supplied[0] if len(supplied) == 1 else ""
        return hmac.compare_digest(candidate, self.token)

    def _serve_page(self) -> HTTPResponse:
        page = self.html_path.read_text(encoding="utf-8")
        page = page.replace(TOKEN_PLACEHOLDER, _inline_script_text(self.token))
        page = page.replace(PORT_PLACEHOLDER, str(self.port))
        return _html_response(page.encode("utf-8"))

    def _toggle(self, body: bytes) -> HTTPResponse:
        if len(body) > MAX_REQUEST_BYTES:
            return _json_response(400, {"error": "Request too large"})
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _json_response(400, {"error": "Request must be valid JSON"})
        if not isinstance(payload, dict) or set(payload) != {"setting_id", "value"}:
            return _json_response(
                400,
                {"error": "Request must contain setting_id and value only"},
            )
        setting_id = payload["setting_id"]
        if not isinstance(setting_id, str):
            return _json_response(400, {"error": "setting_id must be a string"})
        result = self.session.write(setting_id, payload["value"])
        return _json_response(
            200,
            {
                "ok": True,
                "setting_id": result.setting_id,
                "old": result.old,
                "new": result.new,
            },
        )


class DashboardHTTPRequestHandler(BaseHTTPRequestHandler):
    """Thin ``http.server`` adapter over ``DashboardApplication``."""

    application: DashboardApplication

    def do_GET(self) -> None:
        self._dispatch(b"")

    def do_POST(self) -> None:
        if not self.application.authorize_target(self.path):
            self._write_response(_json_response(403, {"error": "Forbidden"}))
            return
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            self._write_response(_json_response(400, {"error": "Invalid Content-Length"}))
            return
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._write_response(_json_response(400, {"error": "Request too large"}))
            return
        parsed = urlsplit(self.path)
        response = self.application._handle_authorized(
            self.command,
            parsed.path,
            self.rfile.read(length),
        )
        self._write_response(response)

    def log_message(self, _format: str, *_args: Any) -> None:
        """Avoid putting the ephemeral token into request logs."""

    def _dispatch(self, body: bytes) -> None:
        response = self.application.handle(self.command, self.path, body)
        self._write_response(response)

    def _write_response(self, response: HTTPResponse) -> None:
        self.send_response(response.status)
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        self.wfile.write(response.body)


def make_http_handler(
    application: DashboardApplication,
) -> type[DashboardHTTPRequestHandler]:
    """Bind one application to an injectable ``BaseHTTPRequestHandler`` class."""

    class BoundDashboardHTTPRequestHandler(DashboardHTTPRequestHandler):
        pass

    BoundDashboardHTTPRequestHandler.application = application
    return BoundDashboardHTTPRequestHandler


def run_server(
    *,
    vault: Path | str,
    html_path: Path | str,
    idle_timeout: float = 900,
    open_browser: bool = True,
    token: str | None = None,
    server_class: type[ThreadingHTTPServer] = ThreadingHTTPServer,
    browser_open: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Bind loopback, serve until close/idle/SIGINT, and never daemonize."""
    if idle_timeout <= 0:
        raise ValueError("idle_timeout must be greater than zero")
    run_token = token or secrets.token_urlsafe(32)
    application = DashboardApplication(
        vault=vault,
        html_path=html_path,
        token=run_token,
        port=0,
    )
    httpd = server_class(
        ("127.0.0.1", 0),
        make_http_handler(application),
    )
    application.port = int(httpd.server_address[1])
    httpd.timeout = min(0.5, max(0.01, idle_timeout / 5))
    url = f"http://127.0.0.1:{application.port}/?t={quote(run_token, safe='')}"
    reason = "idle"
    try:
        print(f"Dashboard: {url}", flush=True)
        if open_browser:
            try:
                opened = (browser_open or _default_browser_open)(url)
            except Exception:
                opened = False
            if not opened:
                print("Could not open a browser — paste the URL above into Chrome.")
        while True:
            if application.close_requested.is_set():
                reason = "close"
                break
            if application.idle_for() >= idle_timeout:
                reason = "idle"
                break
            httpd.handle_request()
    except KeyboardInterrupt:
        reason = "sigint"
    finally:
        httpd.server_close()
    return {"port": application.port, "reason": reason}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open one interactive Dex Dashboard on this Mac.")
    parser.add_argument("--vault", type=Path, required=True, help="Dex vault root")
    parser.add_argument("--html", type=Path, required=True, help="Rendered dashboard HTML")
    parser.add_argument("--idle-timeout", type=float, default=900)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    vault = args.vault.expanduser().resolve()
    html_path = args.html.expanduser().resolve()
    if not vault.is_dir():
        print("error: vault is not a directory", file=sys.stderr)
        return 2
    if not html_path.is_file():
        print("error: dashboard HTML is not a file", file=sys.stderr)
        return 2
    if args.idle_timeout <= 0:
        print("error: idle timeout must be greater than zero", file=sys.stderr)
        return 2
    result = run_server(
        vault=vault,
        html_path=html_path,
        idle_timeout=args.idle_timeout,
    )
    print(f"Dashboard closed ({result['reason']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
