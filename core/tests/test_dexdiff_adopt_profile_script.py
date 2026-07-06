"""Tests for the standalone skill script .claude/skills/diff-adopt-profile/scripts/adopt_profile.py.

The script is the bootstrap-distributed twin of core/dexdiff_profile_adopt.py
(vaults installed via the heydex.ai bootstrap do not have the core module).
These tests run it as a real subprocess and enforce artifact parity with the
module so the two implementations cannot drift silently.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / ".claude" / "skills" / "diff-adopt-profile" / "scripts" / "adopt_profile.py"

dexdiff_profile_adopt = importlib.import_module("core.dexdiff_profile_adopt")


def _bundle() -> dict:
    methodology = 'dexdiff_schema: "2.0"\n' + ("methodology:\n  problem: |\n    real content\n" * 60)
    return {
        "contractVersion": "2026-04-10",
        "profile": {
            "handle": "davekilleen",
            "displayName": "Dave Killeen",
            "role": "Field CPO, EMEA",
            "company": "Pendo",
        },
        "workflows": [
            {"diffId": "meeting-intelligence", "name": "Meeting Intelligence", "methodology": methodology},
            {"diffId": "deal-intelligence", "name": "Deal Intelligence", "methodology": methodology},
        ],
        "loveLetter": {"text": "Dex made my work calmer."},
    }


@pytest.fixture
def stub_server():
    servers = []

    def start(status: int, body: str) -> str:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                payload = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / ".claude").mkdir(parents=True)
    return vault


def _run(args: list[str], vault: Path | None, **kwargs):
    env = dict(kwargs.pop("env", {}))
    env.setdefault("PATH", "/usr/bin:/bin")
    if vault is not None:
        env["VAULT_PATH"] = str(vault)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        **kwargs,
    )


def test_script_happy_path_writes_all_artifacts(stub_server, tmp_path):
    base = stub_server(200, json.dumps(_bundle()))
    vault = _make_vault(tmp_path)

    result = _run(["@davekilleen", "--base-url", base, "--json"], vault)

    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["handle"] == "davekilleen"
    assert output["warnings"] == []

    storage = vault / "04-Projects/DexDiff/beta/profile/adopted/davekilleen"
    assert (storage / "profile-bundle.json").is_file()
    assert (storage / "workflows/01-meeting-intelligence.yaml").is_file()
    assert (storage / "workflows/02-deal-intelligence.yaml").is_file()
    assert (storage / "love-letter.md").is_file()
    log = json.loads((vault / "System/.dex/adoptions/profiles/davekilleen.json").read_text())
    assert log["workflow_ids"] == ["meeting-intelligence", "deal-intelligence"]


def test_script_refuses_outside_a_vault(stub_server, tmp_path):
    base = stub_server(200, json.dumps(_bundle()))
    not_vault = tmp_path / "plain-folder"
    not_vault.mkdir()

    result = _run(["@davekilleen", "--base-url", base], not_vault)

    assert result.returncode == 6
    assert "does not look like a Dex vault" in result.stdout
    assert "Nothing was changed" in result.stdout


def test_script_profile_not_found(stub_server, tmp_path):
    base = stub_server(404, '{"error":"Profile bundle not found"}')
    vault = _make_vault(tmp_path)

    result = _run(["@ghost", "--base-url", base], vault)

    assert result.returncode == 4
    assert "PROFILE NOT FOUND" in result.stdout
    assert "may be private" in result.stdout


def test_script_network_down(tmp_path):
    vault = _make_vault(tmp_path)
    result = _run(["@davekilleen", "--base-url", "http://127.0.0.1:1"], vault)
    assert result.returncode == 3
    assert "NETWORK ERROR" in result.stdout
    assert "Nothing was changed locally" in result.stdout


def test_script_malformed_payload(stub_server, tmp_path):
    bad = _bundle()
    bad["workflows"] = []
    base = stub_server(200, json.dumps(bad))
    vault = _make_vault(tmp_path)

    result = _run(["@davekilleen", "--base-url", base], vault)

    assert result.returncode == 5
    assert "BAD RESPONSE" in result.stdout
    assert "malformed" in result.stdout


def test_script_fetch_only_writes_nothing(stub_server, tmp_path):
    base = stub_server(200, json.dumps(_bundle()))
    vault = _make_vault(tmp_path)

    result = _run(["@davekilleen", "--base-url", base, "--fetch-only"], vault)

    assert result.returncode == 0
    assert not (vault / "04-Projects").exists()
    assert not (vault / "System").exists()


def test_script_flags_v1_summaries(stub_server, tmp_path):
    thin = _bundle()
    for workflow in thin["workflows"]:
        workflow["methodology"] = "A one sentence summary."
    base = stub_server(200, json.dumps(thin))
    vault = _make_vault(tmp_path)

    result = _run(["@davekilleen", "--base-url", base], vault)

    assert result.returncode == 0
    assert "WARNING" in result.stdout
    assert "v1 summary" in result.stdout


def test_script_artifacts_match_core_module(stub_server, tmp_path, monkeypatch):
    """Parity gate: the standalone script and the core module must write the
    same artifact set with the same content (timestamps excluded)."""
    base = stub_server(200, json.dumps(_bundle()))

    script_vault = _make_vault(tmp_path / "script")
    result = _run(["@davekilleen", "--base-url", base], script_vault)
    assert result.returncode == 0, result.stdout + result.stderr

    module_vault = tmp_path / "module" / "vault"
    (module_vault / ".claude").mkdir(parents=True)
    monkeypatch.setattr(dexdiff_profile_adopt, "VAULT_ROOT", module_vault)
    monkeypatch.setattr(
        dexdiff_profile_adopt,
        "DEXDIFF_PROFILE_DRAFTS_DIR",
        module_vault / "04-Projects/DexDiff/beta/profile",
    )
    monkeypatch.setattr(
        dexdiff_profile_adopt,
        "PROFILE_ADOPTIONS_DIR",
        module_vault / "System/.dex/adoptions/profiles",
    )
    source = f"{base}/api/profile-bundle?handle=davekilleen"
    dexdiff_profile_adopt.write_profile_bundle(_bundle(), source=source)

    script_files = sorted(
        str(p.relative_to(script_vault)) for p in script_vault.rglob("*") if p.is_file()
    )
    module_files = sorted(
        str(p.relative_to(module_vault)) for p in module_vault.rglob("*") if p.is_file()
    )
    assert script_files == module_files

    for relative in script_files:
        left = (script_vault / relative).read_text(encoding="utf-8")
        right = (module_vault / relative).read_text(encoding="utf-8")
        if relative.endswith(".json"):
            left_data = {k: v for k, v in json.loads(left).items() if k not in ("saved_at", "adopted_at")}
            right_data = {k: v for k, v in json.loads(right).items() if k not in ("saved_at", "adopted_at")}
            assert left_data == right_data, f"JSON drift in {relative}"
        else:
            assert left == right, f"Content drift in {relative}"
