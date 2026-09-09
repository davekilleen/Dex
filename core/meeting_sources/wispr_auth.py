"""Hold a Wispr Flow credential so Dex can use it without a host session.

Wispr ships a remote MCP server behind a standards-compliant OAuth 2.1
authorization server. Nothing about it requires the credential to live in an
MCP client's connector store, which is where it ends up if you connect through
one. Held here instead, the same connection works from a scheduled job, from a
different MCP client, or from a plain script.

Three properties of this provider drive the whole design, and each one has bitten:

1. **Access tokens live 300 seconds.** Refresh is not an occasional repair, it
   is part of nearly every invocation.
2. **The refresh token rotates on every use.** The old one dies immediately, so
   a lost or torn write of the new one permanently breaks the connection and
   the only recovery is a human in a browser. Writes here are atomic and the
   previous credential is kept until the replacement is durable.
3. **RFC 8707 resource binding is mandatory.** Without ``resource``, the server
   issues a token whose audience is Wispr's own first-party client, and the MCP
   endpoint rejects it with 401 while the token looks perfectly valid.
   ``audience`` is silently ignored, which makes this look like a credentials
   fault rather than a binding one.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

AUTH_SERVER = "https://mcp-auth.wisprflow.com"
TOKEN_ENDPOINT = f"{AUTH_SERVER}/oauth2/token"
RESOURCE = "https://api.wisprflow.ai/connect/mcp"

# Refresh this far before nominal expiry. With a 300s token, a call that starts
# comfortably inside the window can still land outside it.
EXPIRY_MARGIN_SECONDS = 60


class WisprAuthError(RuntimeError):
    """The credential is missing, unusable, or could not be refreshed."""


class WisprNotConnected(WisprAuthError):
    """No credential at all. Distinct from one that failed: setup, not repair."""


def _store_path(vault_root: Path) -> Path:
    return vault_root / "System" / ".dex" / "wispr-credential.json"


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise WisprNotConnected(
            "Wispr is not connected. Run /wispr-setup to authorise it once."
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise WisprAuthError(f"Wispr credential is unreadable: {error}") from error


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Replace the credential in one step, never leaving a partial file.

    The rotated refresh token is the only copy that still works, so a crash
    between truncate and write would cost the connection outright.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _post_token(body: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=urllib.parse.urlencode(body).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:200]
        raise WisprAuthError(f"Wispr refused the token request ({error.code}): {detail}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise WisprAuthError(f"Wispr token request failed: {error}") from error


def access_token(vault_root: Path) -> str:
    """Return a live, resource-bound access token, refreshing when needed."""
    path = _store_path(vault_root)
    stored = _read(path)

    token = stored.get("access_token")
    expires_at = stored.get("expires_at", 0)
    if token and time.time() < expires_at - EXPIRY_MARGIN_SECONDS:
        return token

    refresh = stored.get("refresh_token")
    client_id = stored.get("client_id")
    if not refresh or not client_id:
        raise WisprNotConnected(
            "The stored Wispr credential has no refresh token. Re-run /wispr-setup."
        )

    fresh = _post_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
            # Without this the audience is Wispr's own client and every MCP
            # call returns 401 holding a token that looks entirely valid.
            "resource": RESOURCE,
        }
    )
    if "access_token" not in fresh:
        raise WisprAuthError("Wispr returned no access token on refresh")

    updated = dict(stored)
    updated["access_token"] = fresh["access_token"]
    updated["expires_at"] = time.time() + int(fresh.get("expires_in", 300))
    # Rotation: keep the replacement only once it is written. If the server did
    # not rotate, the existing one stays valid and reusing it is correct.
    updated["refresh_token"] = fresh.get("refresh_token", refresh)
    _write_atomic(path, updated)
    return updated["access_token"]


def save_credential(vault_root: Path, *, client_id: str, token: dict[str, Any]) -> Path:
    """Record a freshly authorised credential. Used by setup, not at runtime."""
    path = _store_path(vault_root)
    _write_atomic(
        path,
        {
            "schema_version": 1,
            "client_id": client_id,
            "access_token": token.get("access_token"),
            "refresh_token": token.get("refresh_token"),
            "expires_at": time.time() + int(token.get("expires_in", 300)),
        },
    )
    return path


def is_connected(vault_root: Path) -> bool:
    """Whether a credential exists at all. Never raises: absence is a valid state."""
    try:
        stored = _read(_store_path(vault_root))
    except WisprAuthError:
        return False
    return bool(stored.get("refresh_token") and stored.get("client_id"))
