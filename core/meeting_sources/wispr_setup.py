"""Authorise Dex against Wispr Flow once, so nothing needs a host afterwards.

Registers Dex as a public OAuth client, runs authorization code with PKCE
against a loopback redirect, and stores the result where the runtime can
refresh it. After this the credential is Dex's: a scheduled job, a different
MCP client, or a plain script all work identically.

Dynamic client registration is used because the provider supports it and it
avoids shipping a client secret that a locally installed application could not
protect anyway. The registered client is recorded alongside the tokens so a
later refresh can identify itself without re-registering.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from core.meeting_sources.wispr_auth import AUTH_SERVER, RESOURCE, WisprAuthError, save_credential

REGISTRATION_ENDPOINT = f"{AUTH_SERVER}/oauth2/register"
AUTHORIZE_ENDPOINT = f"{AUTH_SERVER}/oauth2/authorize"
TOKEN_ENDPOINT = f"{AUTH_SERVER}/oauth2/token"
CALLBACK_PORT = 8765
REDIRECT_URI = f"http://127.0.0.1:{CALLBACK_PORT}/callback"
SCOPES = "openid offline_access"
APPROVAL_TIMEOUT_SECONDS = 600


def register_client(*, client_name: str = "Dex") -> dict[str, Any]:
    """Register Dex as a public client and return the registration.

    Only authorization_code and refresh_token are requested. The server
    advertises device_code in its metadata but rejects it at registration, so
    asking for it fails the whole call.
    """
    body = json.dumps(
        {
            "client_name": client_name,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": SCOPES,
            "redirect_uris": [REDIRECT_URI],
        }
    ).encode()
    request = urllib.request.Request(
        REGISTRATION_ENDPOINT, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            registration = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise WisprAuthError(
            f"Wispr refused client registration ({error.code}): "
            f"{error.read().decode('utf-8', 'replace')[:200]}"
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise WisprAuthError(f"Wispr client registration failed: {error}") from error

    if "client_id" not in registration:
        raise WisprAuthError("Wispr registration returned no client_id")
    return registration


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def authorization_url(client_id: str, challenge: str, state: str) -> str:
    return f"{AUTHORIZE_ENDPOINT}?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # Assert the audience at the authorization request as well as the
            # exchange. The exchange is what actually binds the token on this
            # server, but the spec asks for both and a server that honours only
            # the former would otherwise issue an unusable token.
            "resource": RESOURCE,
        }
    )


def _await_callback(state: str) -> str:
    """Serve one loopback request and return the authorization code."""
    received: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib naming
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            received.update({key: value[0] for key, value in query.items()})
            good = "code" in received and received.get("state") == state
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<h2>Dex is connected to Wispr Flow. You can close this tab.</h2>"
                if good
                else b"<h2>Dex could not complete the connection.</h2>"
            )

        def log_message(self, *args):  # noqa: A003 - silence stdlib logging
            return

    server = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout=APPROVAL_TIMEOUT_SECONDS)
    server.server_close()

    if received.get("state") != state:
        raise WisprAuthError("The authorisation response did not match this request")
    if "code" not in received:
        raise WisprAuthError(
            f"Wispr did not return an authorisation code ({received.get('error', 'timed out')})"
        )
    return received["code"]


def exchange_code(client_id: str, code: str, verifier: str) -> dict[str, Any]:
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
            # Bind the token to the MCP endpoint. Without this the audience is
            # Wispr's own client and every call 401s on a valid-looking token.
            "resource": RESOURCE,
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_ENDPOINT, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise WisprAuthError(
            f"Wispr refused the code exchange ({error.code}): "
            f"{error.read().decode('utf-8', 'replace')[:200]}"
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise WisprAuthError(f"Wispr code exchange failed: {error}") from error


def connect(vault_root: Path, *, open_browser: bool = True, print_url=print) -> Path:
    """Run the whole first-time connection. Returns the credential path."""
    registration = register_client()
    client_id = registration["client_id"]
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(24)
    url = authorization_url(client_id, challenge, state)

    print_url(url)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - a headless box is not a failure
            pass

    code = _await_callback(state)
    token = exchange_code(client_id, code, verifier)
    if "refresh_token" not in token:
        raise WisprAuthError(
            "Wispr returned no refresh token, so unattended sync would not survive. "
            "Check that the offline_access scope was granted."
        )
    return save_credential(vault_root, client_id=client_id, token=token)
