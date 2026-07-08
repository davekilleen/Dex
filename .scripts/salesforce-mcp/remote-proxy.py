#!/usr/bin/env python3
"""
Salesforce remote MCP proxy — forwards stdio MCP calls to the Cloudflare Worker.

Reads credentials from environment or .env.local at the vault root:
  SF_WORKER_URL  — full /mcp endpoint URL (defaults to barsantc.workers.dev)
  SF_MCP_SECRET  — bearer token for the worker
"""

import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ── Load .env.local if vars not already set ────────────────────────────────────

def _load_env_local():
    script_dir = Path(__file__).resolve().parent
    # Walk up to find vault root (.env.local lives next to .claude/)
    for parent in [script_dir, script_dir.parent, script_dir.parent.parent]:
        env_file = parent / ".env.local"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key not in os.environ:
                        os.environ[key] = val
            break

_load_env_local()

WORKER_URL = os.environ.get(
    "SF_WORKER_URL",
    "https://salesforce-mcp.barsantc.workers.dev/mcp",
)
MCP_SECRET = os.environ.get("SF_MCP_SECRET", "")

# ── HTTP forwarding ────────────────────────────────────────────────────────────

def forward(msg: dict) -> dict:
    data = json.dumps(msg).encode()
    headers = {"Content-Type": "application/json"}
    if MCP_SECRET:
        headers["Authorization"] = f"Bearer {MCP_SECRET}"
    req = Request(WORKER_URL, data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code} from worker: {body[:200]}")
    except URLError as e:
        raise RuntimeError(f"Network error reaching worker: {e.reason}")


# ── stdio MCP loop ─────────────────────────────────────────────────────────────

def send(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        msg_id = msg.get("id")
        method = msg.get("method", "")

        # notifications have no id — just forward and don't reply
        if msg_id is None and method.startswith("notifications/"):
            try:
                forward(msg)
            except Exception:
                pass
            continue

        try:
            result = forward(msg)
            send(result)
        except Exception as e:
            if msg_id is not None:
                send({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32000, "message": str(e)},
                })


if __name__ == "__main__":
    main()
