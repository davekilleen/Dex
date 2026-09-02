#!/usr/bin/env python3
"""Generate harness-specific MCP configuration from the single source of truth.

The canonical MCP manifest lives at ``System/.mcp.json.example`` and is the only
place server definitions are authored. This tool materialises it for whatever
harness you actually run, so one Drex vault connects from any MCP client:

    --format mcp       write .mcp.json  (Claude Code, Cursor, or any stdio MCP client)
    --format opencode  write the "mcp" block for opencode.json
    --format list      print the available server names + source files

Filtering matches core/provision.cjs's configuredMcp(): a server whose env still
holds an unresolved ``{{...}}`` placeholder is treated as optional/secret and
skipped, and the venv interpreter is swapped for the Windows path on win32.

Examples
--------
    # Emit the vault's .mcp.json (Claude/Cursor) to stdout
    python3 scripts/generate-harness-config.py --format mcp --vault "."

    # Splice the "mcp" block into the vault's opencode.json (other keys untouched)
    python3 scripts/generate-harness-config.py --format opencode --write opencode.json

    # Show only non-integration servers
    python3 scripts/generate-harness-config.py --format list --exclude pipedrive slack
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

TEMPLATE_REL = "System/.mcp.json.example"
MCP_TARGET_REL = ".mcp.json"
OPENCODE_TARGET_REL = "opencode.json"
_PLACEHOLDER = re.compile(r"\{\{")


def find_vault(start: Path | None = None) -> Path:
    """Resolve the vault root: --vault, $VAULT_PATH, else walk up for the template."""
    configured = os.environ.get("VAULT_PATH")
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if (candidate / TEMPLATE_REL).is_file():
            return candidate
    cursor = Path(start or Path.cwd()).resolve()
    for directory in (cursor, *cursor.parents):
        if (directory / TEMPLATE_REL).is_file():
            return directory
    raise SystemExit(
        f"Could not locate a Dex vault (no {TEMPLATE_REL} found). "
        "Pass --vault explicitly or run from inside the vault."
    )


def load_servers(vault: Path) -> dict:
    """Load the canonical template, materialise placeholders, apply provision filters.

    Mirrors core/provision.cjs#configuredMcp.
    """
    template_path = vault / TEMPLATE_REL
    source = template_path.read_text(encoding="utf-8").replace("{{VAULT_PATH}}", str(vault))
    if sys.platform == "win32":
        source = source.replace(".venv/bin/python", ".venv/Scripts/python.exe")
    config = json.loads(source)
    servers = config.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise SystemExit(f"{template_path} must contain a 'mcpServers' object")
    filtered = {}
    for name, server in servers.items():
        if name.startswith("_"):
            continue
        env = server.get("env") or {}
        unresolved = any(_PLACEHOLDER.search(str(value)) for value in env.values())
        if unresolved:
            continue
        filtered[name] = server
    return filtered


def render_mcp(servers: dict) -> dict:
    """Full .mcp.json document (Claude Code / Cursor / any stdio MCP client)."""
    return {"mcpServers": servers}


def render_opencode(vault: Path, servers: dict) -> dict:
    """The 'mcp' object for opencode.json.

    opencode's local server shape: {type: local, command: [interpreter, script],
    enabled: bool, environment: {...}}. Absolute paths keep it valid regardless
    of the cwd opencode is launched from.
    """
    block = {}
    for name, server in servers.items():
        command = str(server.get("command", ""))
        args = [str(arg) for arg in server.get("args", [])]
        entry = {
            "type": "local",
            "command": [command, *args],
            "enabled": True,
        }
        env = server.get("env") or {}
        if env:
            entry["environment"] = {str(k): str(v) for k, v in env.items()}
        block[name] = entry
    return block


def splice_opencode(target: Path, block: dict) -> dict:
    """Merge the generated block into an existing opencode.json's top-level "mcp".

    Seeds from ``opencode.json.example`` when the target does not exist yet (a
    fresh clone), then keeps every non-MCP key (agent, instructions, ...) and any MCP entry the
    user added by hand that does not point at this vault's own servers, so the
    file can be regenerated without losing customisation.
    """
    doc = {}
    seed = target if target.is_file() else target.with_name(target.name + ".example")
    if seed.is_file():
        try:
            doc = json.loads(seed.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{seed} is not valid JSON: {exc}")
        if not isinstance(doc, dict):
            raise SystemExit(f"{seed} must contain a JSON object")
    doc.setdefault("$schema", "https://opencode.ai/config.json")
    existing = doc.get("mcp") or {}
    kept = {
        name: entry
        for name, entry in existing.items()
        if name not in block and not _is_vault_server(entry)
    }
    doc["mcp"] = {**kept, **block}
    return doc


def _is_vault_server(entry: dict) -> bool:
    """True when an opencode MCP entry launches one of this vault's own servers."""
    command = entry.get("command") if isinstance(entry, dict) else None
    if not isinstance(command, list):
        return False
    return any("core/mcp/" in str(part) or "core/integrations/" in str(part) for part in command)


def render_list(servers: dict) -> str:
    lines = []
    for name in sorted(servers):
        server = servers[name]
        script = next((a for a in server.get("args", []) if a.endswith(".py")), "")
        lines.append(f"{name}\t{script}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", default=None, help="Vault root (default: $VAULT_PATH or auto-detect)")
    parser.add_argument(
        "--format",
        choices=["mcp", "opencode", "list"],
        default="mcp",
        help="Which harness config to emit (default: mcp)",
    )
    parser.add_argument(
        "--include",
        nargs="*",
        default=None,
        help="Restrict output to these server names (default: all available)",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=None,
        help="Drop these server names from output",
    )
    parser.add_argument(
        "--write",
        default=None,
        help="Write the output to this path (relative to the vault). Default prints to stdout.",
    )
    args = parser.parse_args()

    vault = find_vault(args.vault)
    servers = load_servers(vault)

    if args.include:
        servers = {n: s for n, s in servers.items() if n in args.include}
    if args.exclude:
        servers = {n: s for n, s in servers.items() if n not in args.exclude}

    if args.format == "list":
        out = render_list(servers) + "\n"
    elif args.format == "opencode":
        out = json.dumps(render_opencode(vault, servers), indent=2) + "\n"
    else:
        out = json.dumps(render_mcp(servers), indent=2) + "\n"

    if args.write:
        target = Path(args.write)
        if not target.is_absolute():
            target = vault / target
        target.parent.mkdir(parents=True, exist_ok=True)
        if args.format == "opencode":
            doc = splice_opencode(target, render_opencode(vault, servers))
            out = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        target.write_text(out, encoding="utf-8")
        print(f"Wrote {target} ({len(servers)} servers)")
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
