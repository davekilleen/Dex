"""Unit tests for the Pipedrive CRM MCP server (no live API calls)."""

from __future__ import annotations

import asyncio
import json
import subprocess

import pytest

from core.mcp import pipedrive_server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode(result):
    return json.loads(result[0].text)


def _call(name, arguments=None):
    return asyncio.run(pipedrive_server.handle_call_tool(name, arguments or {}))


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload if payload is not None else {"success": True, "data": {}}

    def json(self):
        if self._payload is Ellipsis:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """An isolated vault with Pipedrive enabled and configured."""
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    integrations = tmp_path / "System" / "integrations"
    integrations.mkdir(parents=True)
    (integrations / "config.yaml").write_text("pipedrive:\n  enabled: true\n")
    (integrations / "pipedrive.yaml").write_text(
        "company_domain: example\n"
        "stage_mapping:\n  proposal: 4\n"
        "owner_mapping:\n  'A Person': 42\n"
    )
    return tmp_path


@pytest.fixture
def connected(vault, monkeypatch):
    """A configured vault whose token resolves from the environment."""
    monkeypatch.setattr(pipedrive_server.shutil, "which", lambda _name: None)
    monkeypatch.setenv("PIPEDRIVE_API_TOKEN", "env-token")
    return vault


@pytest.fixture
def http(monkeypatch):
    """Capture outgoing HTTP requests; never touch the network."""
    calls = []

    def fake_request(method, url, params=None, json=None, timeout=None):
        calls.append({"method": method, "url": url, "params": params, "json": json})
        return FakeResponse(payload={"success": True, "data": {"id": 7}})

    monkeypatch.setattr(pipedrive_server.requests, "request", fake_request)
    return calls


# ---------------------------------------------------------------------------
# Token resolution order: Keychain -> env var -> .env file -> not configured
# ---------------------------------------------------------------------------

def test_token_prefers_keychain_json_blob(vault, monkeypatch):
    monkeypatch.setattr(pipedrive_server.shutil, "which", lambda _name: "/usr/bin/security")

    def fake_run(command, **kwargs):
        assert command[0] == "security"
        return subprocess.CompletedProcess(
            command, 0,
            stdout='{"api_token": "kc-token", "company_domain": "kcdomain"}\n',
            stderr="",
        )

    monkeypatch.setattr(pipedrive_server.subprocess, "run", fake_run)
    monkeypatch.setenv("PIPEDRIVE_API_TOKEN", "env-token")

    token = pipedrive_server._load_token()
    assert token == {"api_token": "kc-token", "company_domain": "kcdomain"}


def test_token_accepts_bare_keychain_string(vault, monkeypatch):
    monkeypatch.setattr(pipedrive_server.shutil, "which", lambda _name: "/usr/bin/security")
    monkeypatch.setattr(
        pipedrive_server.subprocess, "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="plain-token\n", stderr=""),
    )
    assert pipedrive_server._load_token() == {"api_token": "plain-token"}


def test_token_falls_back_to_env_var_without_security_binary(vault, monkeypatch):
    """Non-macOS systems (no `security` binary) must not crash."""
    monkeypatch.setattr(pipedrive_server.shutil, "which", lambda _name: None)
    monkeypatch.setenv("PIPEDRIVE_API_TOKEN", "env-token")
    assert pipedrive_server._load_token() == {"api_token": "env-token"}


def test_token_falls_back_to_env_file(vault, monkeypatch):
    monkeypatch.setattr(pipedrive_server.shutil, "which", lambda _name: None)
    monkeypatch.delenv("PIPEDRIVE_API_TOKEN", raising=False)
    (vault / ".env").write_text("# secrets\nexport PIPEDRIVE_API_TOKEN='file-token'\n")
    assert pipedrive_server._load_token() == {"api_token": "file-token"}


def test_token_absent_everywhere(vault, monkeypatch):
    monkeypatch.setattr(pipedrive_server.shutil, "which", lambda _name: None)
    monkeypatch.delenv("PIPEDRIVE_API_TOKEN", raising=False)
    assert pipedrive_server._load_token() == {}


def test_keychain_failure_degrades_to_env_var(vault, monkeypatch):
    monkeypatch.setattr(pipedrive_server.shutil, "which", lambda _name: "/usr/bin/security")

    def boom(command, **kwargs):
        raise OSError("keychain unavailable")

    monkeypatch.setattr(pipedrive_server.subprocess, "run", boom)
    monkeypatch.setenv("PIPEDRIVE_API_TOKEN", "env-token")
    assert pipedrive_server._load_token() == {"api_token": "env-token"}


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------

def test_enabled_canonical_shape(vault):
    assert pipedrive_server._is_enabled() is True


def test_enabled_legacy_shape(vault):
    (vault / "System" / "integrations" / "config.yaml").write_text(
        "enabled:\n  pipedrive: true\n"
    )
    assert pipedrive_server._is_enabled() is True


def test_enabled_defaults_false(vault):
    (vault / "System" / "integrations" / "config.yaml").write_text("pipedrive:\n  enabled: false\n")
    assert pipedrive_server._is_enabled() is False


def test_settings_parse_mappings(vault):
    settings = pipedrive_server._load_settings()
    assert settings["stage_mapping"] == {"proposal": 4}
    assert settings["owner_mapping"] == {"A Person": 42}


def test_resolve_derives_base_url_from_domain(connected):
    env = pipedrive_server._resolve()
    assert env["ok"] is True
    assert env["base_url"] == "https://example.pipedrive.com"


def test_creates_allowed_defaults_off():
    assert pipedrive_server._creates_allowed({}) is False
    assert pipedrive_server._creates_allowed({"writes": {}}) is False
    assert pipedrive_server._creates_allowed({"writes": {"allow_create": "yes"}}) is False
    assert pipedrive_server._creates_allowed({"writes": {"allow_create": True}}) is True


# ---------------------------------------------------------------------------
# feature_status contract
# ---------------------------------------------------------------------------

def test_no_token_reports_off_not_error(vault, monkeypatch):
    monkeypatch.setattr(pipedrive_server.shutil, "which", lambda _name: None)
    monkeypatch.delenv("PIPEDRIVE_API_TOKEN", raising=False)
    payload = _decode(_call("pipedrive_status"))
    assert payload["feature_status"] == "off"
    assert payload["success"] is False
    assert "/pipedrive-setup" in payload["user_message"]


def test_disabled_reports_off(connected):
    (connected / "System" / "integrations" / "config.yaml").write_text(
        "pipedrive:\n  enabled: false\n"
    )
    payload = _decode(_call("pipedrive_status"))
    assert payload["feature_status"] == "off"
    assert "switched off" in payload["user_message"]


def test_missing_base_url_reports_broken(connected):
    (connected / "System" / "integrations" / "pipedrive.yaml").write_text("{}\n")
    payload = _decode(_call("pipedrive_status"))
    assert payload["feature_status"] == "broken"
    assert "company_domain" in payload["user_message"]


def test_status_ok_when_api_reachable(connected, monkeypatch):
    monkeypatch.setattr(
        pipedrive_server.requests, "request",
        lambda *a, **k: FakeResponse(payload={
            "success": True,
            "data": {"id": 1, "name": "A User", "email": "user@example.com",
                     "company_domain": "example"},
        }),
    )
    payload = _decode(_call("pipedrive_status"))
    assert payload["feature_status"] == "ok"
    assert payload["success"] is True
    assert payload["user"]["name"] == "A User"


def test_status_broken_on_auth_failure(connected, monkeypatch):
    monkeypatch.setattr(
        pipedrive_server.requests, "request",
        lambda *a, **k: FakeResponse(status_code=401, payload={"success": False}),
    )
    payload = _decode(_call("pipedrive_status"))
    assert payload["feature_status"] == "broken"
    assert "401" in payload["user_message"]


# ---------------------------------------------------------------------------
# dry_run: exact payload back, no HTTP call
# ---------------------------------------------------------------------------

def test_add_note_dry_run_returns_payload_without_http(connected, http):
    payload = _decode(_call("pipedrive_add_deal_note", {
        "deal_id": 12, "content": "Meeting summary", "dry_run": True,
    }))
    assert payload == {
        "dry_run": True, "method": "POST", "endpoint": "notes",
        "payload": {"deal_id": 12, "content": "Meeting summary"},
    }
    assert http == []


def test_add_activity_dry_run_payload_shape(connected, http):
    payload = _decode(_call("pipedrive_add_deal_activity", {
        "deal_id": 12, "subject": "Follow up", "due_date": "2026-08-14",
        "type": "call", "done": True, "dry_run": True,
    }))
    assert payload["payload"] == {
        "deal_id": 12, "subject": "Follow up", "type": "call",
        "done": 1, "due_date": "2026-08-14",
    }
    assert http == []


def test_update_deal_dry_run_whitelists_fields(connected, http):
    payload = _decode(_call("pipedrive_update_deal", {
        "deal_id": 12,
        "fields": {"value": 250000, "title": "Renamed", "stage_id": 4},
        "dry_run": True,
    }))
    assert payload["payload"] == {"value": 250000, "stage_id": 4}
    assert payload["rejected_fields"] == ["title"]
    assert http == []


def test_update_deal_rejects_all_unwritable_fields(connected, http):
    payload = _decode(_call("pipedrive_update_deal", {
        "deal_id": 12, "fields": {"title": "Renamed"},
    }))
    assert payload["ok"] is False
    assert http == []


def test_add_note_real_send_posts_once(connected, http):
    payload = _decode(_call("pipedrive_add_deal_note", {
        "deal_id": 12, "content": "Meeting summary",
    }))
    assert payload["ok"] is True
    assert payload["note_id"] == 7
    assert len(http) == 1
    assert http[0]["method"] == "POST"
    assert http[0]["url"].endswith("/api/v1/notes")
    assert http[0]["json"] == {"deal_id": 12, "content": "Meeting summary"}
    assert http[0]["params"]["api_token"] == "env-token"


# ---------------------------------------------------------------------------
# Creation gate (writes.allow_create, default off)
# ---------------------------------------------------------------------------

def _enable_creation(vault):
    (vault / "System" / "integrations" / "pipedrive.yaml").write_text(
        "company_domain: example\nwrites:\n  allow_create: true\n"
    )


def test_create_deal_gate_off_returns_calm_off_message(connected, http):
    payload = _decode(_call("pipedrive_create_deal", {"title": "New Deal", "dry_run": True}))
    assert payload["feature_status"] == "off"
    assert "allow_create" in payload["user_message"]
    assert http == []


def test_create_org_gate_off_returns_calm_off_message(connected, http):
    payload = _decode(_call("pipedrive_create_org", {"name": "Acme"}))
    assert payload["feature_status"] == "off"
    assert http == []


def test_create_deal_gate_on_dry_run_payload(connected, http):
    _enable_creation(connected)
    payload = _decode(_call("pipedrive_create_deal", {
        "title": "Platform Migration", "org_id": 9, "value": 250000,
        "currency": "GBP", "stage_id": 4, "probability": 60,
        "owner_id": 42, "expected_close_date": "2026-12-01", "dry_run": True,
    }))
    assert payload == {
        "dry_run": True, "method": "POST", "endpoint": "deals",
        "payload": {
            "title": "Platform Migration", "org_id": 9, "value": 250000,
            "currency": "GBP", "stage_id": 4, "probability": 60,
            "expected_close_date": "2026-12-01", "user_id": 42,
        },
    }
    assert http == []


def test_create_deal_gate_on_real_send(connected, http):
    _enable_creation(connected)
    payload = _decode(_call("pipedrive_create_deal", {"title": "New Deal", "org_id": 9}))
    assert payload["ok"] is True
    assert len(http) == 1
    assert http[0]["url"].endswith("/api/v1/deals")
    assert http[0]["json"] == {"title": "New Deal", "org_id": 9}


def test_create_org_gate_on_dry_run_and_send(connected, http):
    _enable_creation(connected)
    dry = _decode(_call("pipedrive_create_org", {"name": "Acme", "dry_run": True}))
    assert dry == {"dry_run": True, "method": "POST", "endpoint": "organizations",
                   "payload": {"name": "Acme"}}
    assert http == []
    sent = _decode(_call("pipedrive_create_org", {"name": "Acme"}))
    assert sent["ok"] is True
    assert sent["org_id"] == 7
    assert len(http) == 1


# ---------------------------------------------------------------------------
# Mapping cache (local only, no API needed)
# ---------------------------------------------------------------------------

def test_mapping_cache_roundtrip_without_token(vault, monkeypatch):
    monkeypatch.setattr(pipedrive_server.shutil, "which", lambda _name: None)
    monkeypatch.delenv("PIPEDRIVE_API_TOKEN", raising=False)

    saved = _decode(_call("pipedrive_save_mapping", {
        "dex_key": "Acme/Platform Migration", "deal_id": 123, "org_id": 9,
        "title": "Platform Migration",
    }))
    assert saved["ok"] is True

    mapping = _decode(_call("pipedrive_get_mapping"))
    assert mapping["deals"]["Acme/Platform Migration"]["deal_id"] == 123


def test_save_mapping_requires_key_and_deal_id(vault):
    payload = _decode(_call("pipedrive_save_mapping", {"dex_key": "Acme"}))
    assert payload["ok"] is False


# ---------------------------------------------------------------------------
# Deal shaping
# ---------------------------------------------------------------------------

def test_slim_deal_flattens_nested_org_and_owner():
    slim = pipedrive_server._slim_deal({
        "id": 1, "title": "Deal",
        "org_id": {"value": 9, "name": "Acme"},
        "user_id": {"id": 42, "name": "A Person"},
        "value": 1000, "currency": "GBP", "stage_id": 4,
        "status": "open", "probability": 60,
    })
    assert slim["org_id"] == 9
    assert slim["org_name"] == "Acme"
    assert slim["owner_id"] == 42
    assert slim["owner_name"] == "A Person"


def test_slim_deal_tolerates_non_dict():
    assert pipedrive_server._slim_deal(None) == {}


# ---------------------------------------------------------------------------
# SAFETY: the API token never reaches an error string
# ---------------------------------------------------------------------------

def test_network_error_does_not_leak_the_token(connected, monkeypatch):
    """requests quotes the full URL - including ?api_token=... - in its
    exception text. That text is returned to the model, printed by
    /dex-doctor and written to the doctor's report file on disk."""
    def boom(method, url, params=None, json=None, timeout=None):
        raise pipedrive_server.requests.RequestException(
            f"HTTPSConnectionPool(host='example.pipedrive.com', port=443): "
            f"Max retries exceeded with url: /api/v1/users/me?api_token={params['api_token']}"
        )

    monkeypatch.setattr(pipedrive_server.requests, "request", boom)
    payload = _decode(_call("pipedrive_status"))
    blob = json.dumps(payload)
    assert "env-token" not in blob
    assert "***redacted***" in blob


def test_api_error_body_echoing_the_token_is_redacted(connected, monkeypatch):
    monkeypatch.setattr(
        pipedrive_server.requests, "request",
        lambda *a, **k: FakeResponse(status_code=400, payload={
            "success": False, "error": "bad request for /api/v1/deals?api_token=env-token",
        }),
    )
    payload = _decode(_call("pipedrive_list_deals"))
    assert "env-token" not in json.dumps(payload)


def test_redact_is_a_noop_without_a_token():
    assert pipedrive_server._redact("plain text", None) == "plain text"


# ---------------------------------------------------------------------------
