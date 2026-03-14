#!/usr/bin/env python3
"""
Get delegated Office 365 refresh token using OAuth device code flow.

Outputs JSON:
{
  "success": true,
  "refresh_token": "...",
  "access_token": "...",
  "expires_in": 3600
}
"""

import json
import os
import time
from pathlib import Path

import requests


def load_dotenv(vault_path: Path) -> None:
    env_path = vault_path / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value


def main():
    vault = Path(os.environ.get("VAULT_PATH", Path.cwd()))
    load_dotenv(vault)

    tenant_id = os.environ.get("MS_TENANT_ID", "").strip()
    client_id = os.environ.get("MS_CLIENT_ID", "").strip()
    client_secret = os.environ.get("MS_CLIENT_SECRET", "").strip()

    if not tenant_id or not client_id:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "Missing required env vars: MS_TENANT_ID and MS_CLIENT_ID",
                }
            )
        )
        return

    scope = "openid profile offline_access User.Read Calendars.Read"
    device_code_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/devicecode"
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    dc_resp = requests.post(
        device_code_url,
        data={"client_id": client_id, "scope": scope},
        timeout=20,
    )
    if not dc_resp.ok:
        print(json.dumps({"success": False, "error": f"Device code request failed: {dc_resp.text[:500]}"}))
        return

    dc = dc_resp.json()
    print("=== Microsoft Sign-In Required ===", flush=True)
    print(dc.get("message", ""), flush=True)
    print("==================================", flush=True)

    interval = int(dc.get("interval", 5))
    expires_in = int(dc.get("expires_in", 900))
    deadline = time.time() + expires_in

    while time.time() < deadline:
        base_payload = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": client_id,
            "device_code": dc.get("device_code"),
        }

        # Try with secret first (confidential clients), then without (public clients).
        attempts = []
        if client_secret:
            attempts.append({**base_payload, "client_secret": client_secret})
        attempts.append(base_payload)

        tok_resp = None
        for payload in attempts:
            candidate = requests.post(token_url, data=payload, timeout=20)
            # Stop trying variants if auth is pending/slowdown/success.
            if candidate.ok:
                tok_resp = candidate
                break
            err_code = ""
            try:
                err_code = (candidate.json() or {}).get("error", "")
            except Exception:
                pass
            if err_code in ("authorization_pending", "slow_down"):
                tok_resp = candidate
                break
            # For invalid_client, try next variant.
            tok_resp = candidate

        if tok_resp is None:
            print(json.dumps({"success": False, "error": "Token polling failed: no response"}))
            return

        if tok_resp.ok:
            body = tok_resp.json()
            print(
                json.dumps(
                    {
                        "success": True,
                        "refresh_token": body.get("refresh_token", ""),
                        "access_token": body.get("access_token", ""),
                        "expires_in": body.get("expires_in"),
                        "scope": body.get("scope", ""),
                    }
                )
            )
            return

        err = tok_resp.json().get("error", "")
        if err in ("authorization_pending", "slow_down"):
            time.sleep(interval + (2 if err == "slow_down" else 0))
            continue

        print(json.dumps({"success": False, "error": f"Token polling failed: {tok_resp.text[:500]}"}))
        return

    print(json.dumps({"success": False, "error": "Timed out waiting for device authorization"}))


if __name__ == "__main__":
    main()
