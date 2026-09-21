"""Holding a Wispr credential correctly is the whole point of the adapter.

Three properties of this provider make the credential fragile in ways an API
key never was: 300-second access tokens, a refresh token that rotates on every
use, and mandatory RFC 8707 resource binding. Each of these has already caused
a real failure, so each has a test.
"""
from __future__ import annotations

import json
import time

import pytest

from core.meeting_sources import wispr_auth as auth


def _connected(tmp_path, **overrides):
    payload = {
        "schema_version": 1,
        "client_id": "client_TEST",
        "access_token": "at-old",
        "refresh_token": "rt-old",
        "expires_at": time.time() + 3600,
    }
    payload.update(overrides)
    path = auth._store_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def test_absent_credential_is_not_connected_rather_than_broken(tmp_path):
    """Never connected and failed-to-refresh need different answers.

    One is setup, the other is repair, and telling a user to re-authorise when
    they never authorised is how a first run looks like a fault.
    """
    with pytest.raises(auth.WisprNotConnected):
        auth.access_token(tmp_path)
    assert auth.is_connected(tmp_path) is False


def test_a_live_token_is_reused_without_touching_the_network(tmp_path, monkeypatch):
    _connected(tmp_path)
    monkeypatch.setattr(auth, "_post_token", lambda body: pytest.fail("must not refresh"))

    assert auth.access_token(tmp_path) == "at-old"


def test_refresh_sends_the_resource_parameter(tmp_path, monkeypatch):
    """Without RFC 8707 binding the token is audienced to Wispr's own client.

    The MCP endpoint then returns 401 while the token looks entirely valid,
    which reads as a credentials fault and is not one. `audience` is silently
    ignored by this server, so only `resource` will do.
    """
    _connected(tmp_path, expires_at=time.time() - 1)
    seen = {}

    def fake(body):
        seen.update(body)
        return {"access_token": "at-new", "refresh_token": "rt-new", "expires_in": 300}

    monkeypatch.setattr(auth, "_post_token", fake)
    auth.access_token(tmp_path)

    assert seen["resource"] == auth.RESOURCE
    assert seen["grant_type"] == "refresh_token"


def test_the_rotated_refresh_token_is_persisted(tmp_path, monkeypatch):
    """The old refresh token dies on use. Losing the new one costs the connection."""
    path = _connected(tmp_path, expires_at=time.time() - 1)
    monkeypatch.setattr(
        auth,
        "_post_token",
        lambda body: {"access_token": "at-new", "refresh_token": "rt-new", "expires_in": 300},
    )

    auth.access_token(tmp_path)

    stored = json.loads(path.read_text())
    assert stored["refresh_token"] == "rt-new"
    assert stored["access_token"] == "at-new"
    assert stored["expires_at"] > time.time()


def test_a_server_that_does_not_rotate_keeps_the_existing_refresh_token(tmp_path, monkeypatch):
    """Rotation is this server's behaviour, not a guarantee. Do not blank it."""
    path = _connected(tmp_path, expires_at=time.time() - 1)
    monkeypatch.setattr(
        auth, "_post_token", lambda body: {"access_token": "at-new", "expires_in": 300}
    )

    auth.access_token(tmp_path)

    assert json.loads(path.read_text())["refresh_token"] == "rt-old"


def test_a_failed_refresh_leaves_the_credential_intact(tmp_path, monkeypatch):
    """A transient outage must not cost the user a browser round trip."""
    path = _connected(tmp_path, expires_at=time.time() - 1)
    before = path.read_text()

    def boom(body):
        raise auth.WisprAuthError("token endpoint unavailable")

    monkeypatch.setattr(auth, "_post_token", boom)

    with pytest.raises(auth.WisprAuthError):
        auth.access_token(tmp_path)
    assert path.read_text() == before


def test_the_credential_is_written_atomically_and_private(tmp_path):
    path = auth.save_credential(
        tmp_path,
        client_id="client_TEST",
        token={"access_token": "a", "refresh_token": "r", "expires_in": 300},
    )

    assert path.stat().st_mode & 0o777 == 0o600
    assert not path.with_suffix(".tmp").exists(), "no temp file may survive the write"
    assert auth.is_connected(tmp_path) is True


def test_is_connected_never_raises_on_a_corrupt_store(tmp_path):
    path = auth._store_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")

    assert auth.is_connected(tmp_path) is False
