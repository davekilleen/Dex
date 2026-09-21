"""Connecting once must leave behind a credential that survives unattended.

The failure this guards against is a setup flow that appears to succeed and
produces something that cannot refresh: the user believes they are connected,
and the first scheduled sync after the access token expires finds nothing it
can do.
"""
from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
import urllib.parse
from io import BytesIO

import pytest

from core.meeting_sources import wispr_setup
from core.meeting_sources.wispr_auth import RESOURCE, WisprAuthError


class _Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _urlopen(monkeypatch, payload, *, capture=None):
    def fake(request, timeout=None):
        if capture is not None:
            capture["url"] = request.full_url
            capture["body"] = request.data.decode() if request.data else ""
        return _Response(json.dumps(payload).encode())

    monkeypatch.setattr(wispr_setup.urllib.request, "urlopen", fake)


def _http_error(monkeypatch, status, body):
    def fake(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, status, "err", {}, BytesIO(body.encode()))

    monkeypatch.setattr(wispr_setup.urllib.request, "urlopen", fake)


def test_registration_asks_for_a_public_client(monkeypatch):
    """A secret shipped inside a local install is not a secret."""
    capture: dict = {}
    _urlopen(monkeypatch, {"client_id": "client_NEW"}, capture=capture)

    registration = wispr_setup.register_client()

    assert registration["client_id"] == "client_NEW"
    body = json.loads(capture["body"])
    assert body["token_endpoint_auth_method"] == "none"
    assert body["redirect_uris"] == [wispr_setup.REDIRECT_URI]


def test_registration_does_not_ask_for_device_code(monkeypatch):
    """The server advertises it and then rejects it, failing the whole call."""
    capture: dict = {}
    _urlopen(monkeypatch, {"client_id": "c"}, capture=capture)

    wispr_setup.register_client()

    assert json.loads(capture["body"])["grant_types"] == ["authorization_code", "refresh_token"]


def test_a_registration_without_a_client_id_is_refused(monkeypatch):
    _urlopen(monkeypatch, {"ok": True})

    with pytest.raises(WisprAuthError, match="no client_id"):
        wispr_setup.register_client()


def test_a_refused_registration_says_what_the_server_said(monkeypatch):
    _http_error(monkeypatch, 400, '{"message":"Validation failed"}')

    with pytest.raises(WisprAuthError, match="Validation failed"):
        wispr_setup.register_client()


def test_the_authorization_url_carries_pkce_and_the_resource():
    verifier, challenge = wispr_setup._pkce()
    url = wispr_setup.authorization_url("client_TEST", challenge, "state-123")
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    assert params["code_challenge_method"] == ["S256"]
    assert params["resource"] == [RESOURCE]
    assert params["state"] == ["state-123"]
    assert params["scope"] == [wispr_setup.SCOPES]


def test_the_pkce_challenge_is_a_real_s256_of_the_verifier():
    verifier, challenge = wispr_setup._pkce()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()

    assert challenge == expected


def test_the_code_exchange_binds_the_token_to_the_resource(monkeypatch):
    """Without this the token is audienced elsewhere and every call 401s."""
    capture: dict = {}
    _urlopen(monkeypatch, {"access_token": "a", "refresh_token": "r"}, capture=capture)

    wispr_setup.exchange_code("client_TEST", "code-1", "verifier-1")

    body = urllib.parse.parse_qs(capture["body"])
    assert body["resource"] == [RESOURCE]
    assert body["code_verifier"] == ["verifier-1"]
    assert body["grant_type"] == ["authorization_code"]


def test_connect_refuses_a_credential_that_cannot_refresh(monkeypatch, tmp_path):
    """A connection that cannot survive its own access token is not a connection."""
    monkeypatch.setattr(wispr_setup, "register_client", lambda **_k: {"client_id": "c"})
    monkeypatch.setattr(wispr_setup, "_await_callback", lambda _state: "code-1")
    monkeypatch.setattr(
        wispr_setup, "exchange_code", lambda *_a: {"access_token": "a", "expires_in": 300}
    )

    with pytest.raises(WisprAuthError, match="no refresh token"):
        wispr_setup.connect(tmp_path, open_browser=False, print_url=lambda _u: None)


def test_connect_stores_a_usable_credential(monkeypatch, tmp_path):
    from core.meeting_sources import wispr_auth

    monkeypatch.setattr(wispr_setup, "register_client", lambda **_k: {"client_id": "client_X"})
    monkeypatch.setattr(wispr_setup, "_await_callback", lambda _state: "code-1")
    monkeypatch.setattr(
        wispr_setup,
        "exchange_code",
        lambda *_a: {"access_token": "a", "refresh_token": "r", "expires_in": 300},
    )

    path = wispr_setup.connect(tmp_path, open_browser=False, print_url=lambda _u: None)

    assert path.stat().st_mode & 0o777 == 0o600
    assert wispr_auth.is_connected(tmp_path) is True
    assert json.loads(path.read_text())["client_id"] == "client_X"
