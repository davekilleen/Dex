#!/usr/bin/env python3
"""Exercise the portable plugin runtime on the current operating system."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.harnesses.registry import get_platform_release  # noqa: E402

PLUGIN = ROOT / "packages" / "dex-agent-plugin"
LAUNCHER = PLUGIN / "bin" / "dex-python.mjs"


def _environment() -> dict[str, str]:
    return {
        **os.environ,
        "DEX_PYTHON": sys.executable,
        "PYTHONNOUSERSITE": "1",
    }


def _run(mode: str, payload: str, *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(LAUNCHER), mode],
        input=payload,
        text=True,
        capture_output=True,
        cwd=cwd,
        env=_environment(),
        check=check,
    )


def verify_runtime() -> None:
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    mcp = _run("mcp", "".join(json.dumps(row) + "\n" for row in messages), cwd=ROOT)
    responses = [json.loads(line) for line in mcp.stdout.splitlines() if line.strip()]
    if len(responses) != 2 or responses[0].get("id") != 1:
        raise RuntimeError("portable MCP bridge did not complete its initialize round trip")
    tools = responses[1].get("result", {}).get("tools", [])
    if "check_safety_gate" not in {tool.get("name") for tool in tools}:
        raise RuntimeError("portable MCP bridge did not expose the shared safety tool")

    with tempfile.TemporaryDirectory(prefix="dex-plugin-runtime-") as temporary:
        vault = Path(temporary)
        system = vault / "System"
        system.mkdir()
        (system / "pillars.yaml").write_text(
            "pillars:\n  - id: portable\n    name: Portable\n    description: Verified\n",
            encoding="utf-8",
        )
        session = _run(
            "hook",
            json.dumps({"hook_event_name": "SessionStart", "cwd": str(vault)}),
            cwd=vault,
        )
        if "Portable" not in session.stdout:
            raise RuntimeError("SessionStart hook did not inject shared Dex context")
        blocked = _run(
            "hook",
            json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "cwd": str(vault),
                    "tool_name": "Bash",
                    "tool_input": {"command": "rm -rf /"},
                }
            ),
            cwd=vault,
            check=False,
        )
        if blocked.returncode != 2 or json.loads(blocked.stdout).get("decision") != "block":
            raise RuntimeError("PreToolUse hook did not preserve the shared safety refusal")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-release-ready",
        action="store_true",
        help="fail when the current platform is not included in this release",
    )
    args = parser.parse_args()
    verify_runtime()
    release = get_platform_release()
    print(f"Portable plugin runtime verified: {release['label']} ({release['readiness']}).")
    if args.require_release_ready and release["readiness"] != "release_ready":
        print(f"{release['label']} is outside this release: {release['notes']}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
