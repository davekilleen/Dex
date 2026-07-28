"""Socket-free HTTP and settings-section coverage for the Dex Dashboard."""

from __future__ import annotations

import importlib
import io
import json
import os
import time
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore", category=pytest.PytestUnknownMarkWarning)


def _server():
    return importlib.import_module("core.dashboard.server")


def _settings():
    return importlib.import_module("core.dashboard.sections.settings")


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _vault(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    _write(
        vault / "System" / "user-profile.yaml",
        """\
name: "Alex"
communication:
  formality: "professional_casual"
  directness: "balanced"
entity_creation:
  mode: suggest
analytics:
  enabled: true
""",
    )
    _write(
        vault / "System" / "integrations" / "config.yaml",
        """\
enabled:
  slack: false
hooks:
  meeting_prep:
    use_slack: false
detected:
  slack: null
todoist:
  enabled: true
  api_key_env_var: NEVER_RETURN_THIS_SECRET
""",
    )
    _write(
        vault / "System" / "usage_log.md",
        "**Health telemetry:** pending\n",
    )
    page = _write(
        tmp_path / "dashboard.html",
        """<!doctype html>
<meta name="dashboard-port" content="__DEX_DASHBOARD_PORT__">
<script>const token = "__DEX_DASHBOARD_TOKEN__";</script>
""",
    )
    return vault, page


def _json(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


def _app(tmp_path: Path):
    server = _server()
    vault, page = _vault(tmp_path)
    return (
        server.DashboardApplication(
            vault=vault,
            html_path=page,
            token="correct-token",
            port=43123,
        ),
        vault,
    )


@pytest.mark.parametrize(
    ("method", "target", "body"),
    [
        ("GET", "/", b""),
        ("GET", "/?t=wrong", b""),
        ("GET", "/api/state", b""),
        ("POST", "/api/toggle?t=wrong", b"{}"),
        ("POST", "/api/close", b""),
    ],
)
def test_every_endpoint_requires_the_run_token(
    tmp_path: Path,
    method: str,
    target: str,
    body: bytes,
) -> None:
    app, _vault_path = _app(tmp_path)

    response = app.handle(method, target, body)

    assert response.status == 403
    assert _json(response) == {"error": "Forbidden"}
    assert response.headers["Cache-Control"] == "no-store"


def test_token_authentication_uses_constant_time_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server()
    app, _vault_path = _app(tmp_path)
    compared: list[tuple[str, str]] = []
    real_compare = server.hmac.compare_digest

    def recording_compare(left: str, right: str) -> bool:
        compared.append((left, right))
        return real_compare(left, right)

    monkeypatch.setattr(server.hmac, "compare_digest", recording_compare)

    response = app.handle("GET", "/api/state?t=correct-token")

    assert response.status == 200
    assert compared == [("correct-token", "correct-token")]


def test_http_adapter_checks_token_before_content_length(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server()
    app, _vault_path = _app(tmp_path)
    handler = object.__new__(server.DashboardHTTPRequestHandler)
    handler.application = app
    handler.path = "/api/toggle"
    handler.headers = {"Content-Length": str(server.MAX_REQUEST_BYTES + 1)}
    handler.rfile = io.BytesIO()
    captured = []
    monkeypatch.setattr(handler, "_write_response", captured.append)

    handler.do_POST()

    assert len(captured) == 1
    assert captured[0].status == 403


def test_get_root_serves_in_memory_rewritten_html(tmp_path: Path) -> None:
    app, _vault_path = _app(tmp_path)

    response = app.handle("GET", "/?t=correct-token")

    text = response.body.decode("utf-8")
    assert response.status == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert "__DEX_DASHBOARD_TOKEN__" not in text
    assert "__DEX_DASHBOARD_PORT__" not in text
    assert '"correct-token"' in text
    assert 'content="43123"' in text


def test_state_is_re_read_and_toggle_write_returns_undo_values(tmp_path: Path) -> None:
    app, vault = _app(tmp_path)

    state_response = app.handle("GET", "/api/state?t=correct-token")
    toggle_response = app.handle(
        "POST",
        "/api/toggle?t=correct-token",
        json.dumps({"setting_id": "formality", "value": "casual"}).encode(),
    )

    assert state_response.status == 200
    assert _json(state_response)["settings"]["formality"] == "professional_casual"
    assert _json(state_response)["unavailable"] == {}
    assert toggle_response.status == 200
    assert _json(toggle_response) == {
        "ok": True,
        "setting_id": "formality",
        "old": "professional_casual",
        "new": "casual",
    }
    assert 'formality: "casual"' in (vault / "System" / "user-profile.yaml").read_text(encoding="utf-8")
    refreshed = app.handle("GET", "/api/state?t=correct-token")
    assert _json(refreshed)["settings"]["formality"] == "casual"


def test_missing_entity_creation_keeps_other_settings_live_and_returns_400_on_write(
    tmp_path: Path,
) -> None:
    app, vault = _app(tmp_path)
    profile = vault / "System" / "user-profile.yaml"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace(
            "entity_creation:\n  mode: suggest\n",
            "",
        ),
        encoding="utf-8",
    )

    state_response = app.handle("GET", "/api/state?t=correct-token")
    state = _json(state_response)

    assert state_response.status == 200
    assert state["settings"]["formality"] == "professional_casual"
    assert "entity_creation" not in state["settings"]
    assert "entity_creation" not in state["unavailable"]

    formality_response = app.handle(
        "POST",
        "/api/toggle?t=correct-token",
        b'{"setting_id":"formality","value":"casual"}',
    )
    entity_response = app.handle(
        "POST",
        "/api/toggle?t=correct-token",
        b'{"setting_id":"entity_creation","value":"off"}',
    )

    assert formality_response.status == 200
    assert entity_response.status == 400
    assert _json(entity_response) == {
        "error": "That setting is not present in this Dex's files yet."
    }


def test_duplicated_setting_is_unavailable_without_blocking_other_writes(
    tmp_path: Path,
) -> None:
    app, vault = _app(tmp_path)
    profile = vault / "System" / "user-profile.yaml"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace(
            '  directness: "balanced"',
            '  directness: "balanced"\n  directness: "supportive"',
        ),
        encoding="utf-8",
    )

    state_response = app.handle("GET", "/api/state?t=correct-token")
    state = _json(state_response)

    assert state_response.status == 200
    assert state["settings"]["formality"] == "professional_casual"
    assert "directness" not in state["settings"]
    assert set(state["unavailable"]) == {"directness"}
    assert "exactly once" in state["unavailable"]["directness"]

    directness_response = app.handle(
        "POST",
        "/api/toggle?t=correct-token",
        b'{"setting_id":"directness","value":"supportive"}',
    )
    formality_response = app.handle(
        "POST",
        "/api/toggle?t=correct-token",
        b'{"setting_id":"formality","value":"casual"}',
    )

    assert directness_response.status == 409
    assert "exactly once" in _json(directness_response)["error"]
    assert formality_response.status == 200


def test_successful_post_advances_only_the_cached_get_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _vault_path = _app(tmp_path)
    assert app.handle("GET", "/api/state?t=correct-token").status == 200

    def unexpected_read():
        raise AssertionError("POST must not accept a fresh disk state as the user's GET state")

    monkeypatch.setattr(app.session.engine, "read_state", unexpected_read)

    response = app.handle(
        "POST",
        "/api/toggle?t=correct-token",
        b'{"setting_id":"formality","value":"casual"}',
    )

    assert response.status == 200
    assert app.session.snapshot is not None
    assert app.session.snapshot.values["formality"] == "casual"


def test_toggle_requires_state_read_and_rejects_concurrent_changes(tmp_path: Path) -> None:
    app, vault = _app(tmp_path)

    before_state = app.handle(
        "POST",
        "/api/toggle?t=correct-token",
        b'{"setting_id":"formality","value":"formal"}',
    )
    assert before_state.status == 409
    assert "refresh" in _json(before_state)["error"].lower()

    assert app.handle("GET", "/api/state?t=correct-token").status == 200
    profile = vault / "System" / "user-profile.yaml"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace('name: "Alex"', 'name: "Sam"'),
        encoding="utf-8",
    )
    conflict = app.handle(
        "POST",
        "/api/toggle?t=correct-token",
        b'{"setting_id":"formality","value":"formal"}',
    )

    assert conflict.status == 409
    assert "refresh" in _json(conflict)["error"].lower()
    assert 'formality: "professional_casual"' in profile.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        (b"{bad json", 400),
        (b"[]", 400),
        (b'{"setting_id":"unknown","value":true}', 400),
        (b'{"setting_id":"formality","value":"junk"}', 400),
        (b'{"setting_id":"analytics_enabled","value":1}', 400),
        (b'{"setting_id":"formality"}', 400),
    ],
)
def test_bad_toggle_requests_are_safe_client_errors(
    tmp_path: Path,
    payload: bytes,
    status: int,
) -> None:
    app, _vault_path = _app(tmp_path)
    app.handle("GET", "/api/state?t=correct-token")

    response = app.handle("POST", "/api/toggle?t=correct-token", payload)

    assert response.status == status
    assert set(_json(response)) == {"error"}
    assert b"NEVER_RETURN_THIS_SECRET" not in response.body


def test_close_endpoint_requests_shutdown_without_a_socket(tmp_path: Path) -> None:
    app, _vault_path = _app(tmp_path)

    response = app.handle("POST", "/api/close?t=correct-token", b"")

    assert response.status == 200
    assert _json(response) == {"ok": True}
    assert app.close_requested.is_set()


def test_unknown_routes_do_not_serve_files(tmp_path: Path) -> None:
    app, _vault_path = _app(tmp_path)

    response = app.handle("GET", "/../../System/user-profile.yaml?t=correct-token")

    assert response.status == 404
    assert _json(response) == {"error": "Not found"}


def test_settings_section_escapes_data_and_returns_interactive_javascript() -> None:
    settings = _settings()
    data = {
        "integrations": {
            "apps": {
                "slack": {"enabled": True},
                "Slack & Co": {"enabled": True},
                '<script>alert("x")</script>': {"enabled": False},
            }
        },
        "profile": {
            "api_key": "NEVER_RENDER",
            "communication": {
                "formality": "professional_casual",
                "directness": "balanced",
                "detail_level": "concise",
                "coaching_style": "collaborative",
            },
            "analytics": {"enabled": True},
            "entity_creation": {"mode": "suggest"},
            "entity_gardener": {"enabled": True},
            "meeting_intelligence": {
                "extract_action_items": True,
                "extract_decisions": False,
            },
            "journaling": {
                "morning": False,
                "evening": False,
                "weekly": True,
            },
            "capabilities": {
                "career": {"enabled": False},
                "companies": {"enabled": True},
                "quarter_goals": {"enabled": False},
            },
        },
    }

    fragment, script = settings.render(
        data,
        {
            "token": '"</script><script>alert(1)</script>',
            "port": 43123,
        },
    )

    assert 'id="settings"' in fragment
    assert 'data-setting-id="analytics_enabled"' in fragment
    assert 'data-setting-id="entity_creation"' in fragment
    assert 'data-setting-id="formality"' in fragment
    assert 'data-setting-id="directness"' in fragment
    assert 'data-setting-id="detail_level"' in fragment
    assert 'data-setting-id="coaching_style"' in fragment
    assert 'data-setting-id="health_telemetry"' in fragment
    assert 'data-setting-id="capability:career"' in fragment
    assert 'data-setting-id="capability:companies"' in fragment
    assert 'data-setting-id="capability:quarter_goals"' in fragment
    assert 'data-setting-id="meeting_intel:extract_action_items"' in fragment
    assert 'data-setting-id="meeting_intel:extract_decisions"' in fragment
    assert 'data-setting-id="entity_gardener"' in fragment
    assert 'data-setting-id="journaling_morning"' in fragment
    assert 'data-setting-id="journaling_evening"' in fragment
    assert 'data-setting-id="journaling_weekly"' in fragment
    assert 'data-setting-id="integration:slack.enabled"' in fragment
    group_names = [
        "privacy",
        "communication",
        "capabilities",
        "meetings",
        "journaling",
        "connections",
    ]
    positions = [
        fragment.index(f'data-settings-group="{group_name}"')
        for group_name in group_names
    ]
    assert positions == sorted(positions)
    for label in (
        "Privacy",
        "Communication",
        "Capabilities",
        "Meetings",
        "Journaling",
        "Connections",
    ):
        assert f'<h3 class="settings-group-label">{label}</h3>' in fragment
    assert "Behavior" not in fragment
    assert "Career coaching, evidence capture and resume tools" in fragment
    assert "unlocks a set of skills" in fragment
    assert "Slack &amp; Co" in fragment
    assert '<script>alert("x")</script>' not in fragment
    assert "NEVER_RENDER" not in fragment
    assert "Set up Todoist" in fragment
    assert "/todoist-setup" in fragment
    assert "fetch(" in script
    assert "/api/state" in script
    assert "/api/toggle" in script
    assert "/api/close" in script
    assert "payload.unavailable" in script
    assert "Not set up in this vault yet." in script
    assert "pagehide" in script
    assert "beforeunload" in script
    assert "undo" in script.lower()
    assert "\\u003c/script\\u003e" in script
    assert "</script>" not in script


def test_settings_section_has_the_same_full_inventory_read_only_without_a_server() -> None:
    settings = _settings()
    data = {
        "profile": {
            "communication": {
                "formality": "professional_casual",
                "directness": "balanced",
                "detail_level": "comprehensive",
                "coaching_style": "challenging",
            },
            "analytics": {"enabled": True},
            "entity_creation": {"mode": "auto"},
            "entity_gardener": {"enabled": False},
            "meeting_intelligence": {
                "extract_action_items": True,
                "custom_follow_up_signal": False,
            },
            "journaling": {"morning": True, "evening": False, "weekly": True},
            "capabilities": {
                "career": {"enabled": True},
                "companies": {"enabled": False},
                "quarter_goals": {"enabled": True},
            },
        },
        "integrations": {"apps": {"slack": {"enabled": True}}},
    }

    fragment, script = settings.render(data, None)

    assert script == ""
    for setting_id in (
        "analytics_enabled",
        "health_telemetry",
        "formality",
        "directness",
        "detail_level",
        "coaching_style",
        "capability:career",
        "capability:companies",
        "capability:quarter_goals",
        "meeting_intel:extract_action_items",
        "meeting_intel:custom_follow_up_signal",
        "entity_creation",
        "entity_gardener",
        "journaling_morning",
        "journaling_evening",
        "journaling_weekly",
        "integration:slack.enabled",
    ):
        assert f'data-setting-id="{setting_id}"' in fragment
    assert "Read-only" in fragment
    assert "fetch(" not in fragment
    assert 'value="comprehensive" selected' in fragment
    assert 'id="setting-capability:career"' in fragment
    assert 'id="setting-capability:career"\n            type="checkbox"' in fragment
    assert 'data-setting-id="capability:career"' in fragment
    assert "checked" in fragment
    assert fragment.count('data-settings-group="') == 6


def test_run_server_prints_the_tokened_url_once_and_flushes_before_opening_browser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server()
    vault, page = _vault(tmp_path)

    class RecordingStdout:
        def __init__(self) -> None:
            self.text = ""
            self.flush_count = 0

        def write(self, text: str) -> int:
            self.text += text
            return len(text)

        def flush(self) -> None:
            self.flush_count += 1

    class ImmediateServer:
        instance: "ImmediateServer"

        def __init__(self, _address, _handler) -> None:
            self.server_address = ("127.0.0.1", 43123)
            self.timeout = None
            self.handled_requests = 0
            self.closed = False
            type(self).instance = self

        def handle_request(self) -> None:
            self.handled_requests += 1

        def server_close(self) -> None:
            self.closed = True

    stdout = RecordingStdout()
    monkeypatch.setattr(server.sys, "stdout", stdout)
    opened: list[str] = []

    def browser_open(url: str) -> bool:
        assert stdout.text == f"Dashboard: {url}\n"
        assert stdout.flush_count >= 1
        opened.append(url)
        return True

    result = server.run_server(
        vault=vault,
        html_path=page,
        idle_timeout=0.01,
        token="demo-token",
        server_class=ImmediateServer,
        browser_open=browser_open,
    )

    expected_url = "http://127.0.0.1:43123/?t=demo-token"
    assert result["reason"] == "idle"
    assert opened == [expected_url]
    assert stdout.text == f"Dashboard: {expected_url}\n"
    assert stdout.text.count(expected_url) == 1
    assert ImmediateServer.instance.handled_requests > 0
    assert ImmediateServer.instance.closed


def test_run_server_keeps_serving_when_injected_browser_open_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    server = _server()
    vault, page = _vault(tmp_path)

    class ImmediateServer:
        instance: "ImmediateServer"

        def __init__(self, _address, _handler) -> None:
            self.server_address = ("127.0.0.1", 43124)
            self.timeout = None
            self.handled_requests = 0
            self.closed = False
            type(self).instance = self

        def handle_request(self) -> None:
            self.handled_requests += 1

        def server_close(self) -> None:
            self.closed = True

    result = server.run_server(
        vault=vault,
        html_path=page,
        idle_timeout=0.01,
        token="demo-token",
        server_class=ImmediateServer,
        browser_open=lambda _url: False,
    )

    expected_url = "http://127.0.0.1:43124/?t=demo-token"
    assert result["reason"] == "idle"
    assert capsys.readouterr().out == (
        f"Dashboard: {expected_url}\n"
        "Could not open a browser — paste the URL above into Chrome.\n"
    )
    assert ImmediateServer.instance.handled_requests > 0
    assert ImmediateServer.instance.closed


def test_default_browser_open_uses_macos_open_after_webbrowser_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server()
    calls: list[tuple[object, ...]] = []

    class CompletedProcess:
        returncode = 0

    monkeypatch.setattr(server.sys, "platform", "darwin")
    monkeypatch.setattr(server.webbrowser, "open", lambda _url: False)
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *args, **kwargs: (calls.append((*args, kwargs)), CompletedProcess())[1],
    )

    assert server._default_browser_open("http://127.0.0.1:43123/?t=demo-token")
    assert calls == [(["open", "http://127.0.0.1:43123/?t=demo-token"], {"check": False})]


@pytest.mark.socket_smoke
@pytest.mark.skipif(
    os.environ.get("DEX_SOCKET_SMOKE") != "1",
    reason="requires normal local socket permissions; set DEX_SOCKET_SMOKE=1",
)
def test_real_server_exits_after_idle_timeout(tmp_path: Path) -> None:
    server = _server()
    vault, page = _vault(tmp_path)
    started = time.monotonic()

    result = server.run_server(
        vault=vault,
        html_path=page,
        idle_timeout=0.05,
        open_browser=False,
    )

    assert result["reason"] == "idle"
    assert time.monotonic() - started < 2
