#!/usr/bin/env python3
"""Build and validate Dex's portable, multi-harness plugin package.

The package keeps the Agent Plugins v1.0.0 root contract while adding the
native manifests used by Codex and Claude Code/Cowork. Shared, dependency-free
context and safety modules are vendored from ``core`` so every host executes
the same read-only behavior rather than a rewritten approximation.
"""

from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-agent-plugin"
SKILLS_SOURCE = REPO_ROOT / ".agents" / "skills"
METADATA_SOURCE = REPO_ROOT / "core" / "harnesses"
SCHEMA_URL = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA_URL = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
RUNTIME_SOURCES = (
    Path("core/__init__.py"),
    Path("core/path_safety.py"),
    Path("core/context/__init__.py"),
    Path("core/context/person_context.py"),
    Path("core/context/session_boot.py"),
    Path("core/gates/__init__.py"),
    Path("core/gates/safety.py"),
)


def _plugin_json() -> dict:
    return {
        "$schema": SCHEMA_URL,
        "name": "dex-agent-plugin",
        "version": "1.0.0",
        "description": "Dex's portable Agent Skills and MCP surface for compatible harnesses.",
        "author": {"name": "Dex"},
        "homepage": "https://heydex.ai",
        "repository": "https://github.com/davekilleen/Dex",
        "license": "MIT",
        "keywords": ["dex", "productivity", "agent-skills", "mcp"],
        "extensions": {
            "ai.heydex.dex": {
                "registry": "./metadata/harnesses/registry.json",
                "portability": "./metadata/harnesses/portability.json",
                "adapters": "./ai.heydex.dex/adapters",
            }
        },
    }


def _mcp_json() -> dict:
    return {
        "$schema": MCP_SCHEMA_URL,
        "mcpServers": {
            "dex-core": {
                "type": "stdio",
                "command": "./bin/dex-mcp",
                "args": ["--stdio"],
                "env": {"DEX_PLUGIN_DATA": "${PLUGIN_DATA}"},
                "cwd": "${PLUGIN_ROOT}",
            }
        },
    }


def _native_mcp_json(root_variable: str, *, wrapped: bool) -> dict:
    servers = {
        "dex-core": {
            "command": "python3",
            "args": [f"${{{root_variable}}}/server.py"],
        }
    }
    return {"mcpServers": servers} if wrapped else servers


def _codex_plugin_json() -> dict:
    return {
        "name": "dex",
        "version": "1.0.0",
        "description": "Portable Dex context, safety, and work skills.",
        "skills": "./skills/",
        "mcpServers": "./.codex-mcp.json",
        "hooks": "./hooks/hooks.json",
    }


def _claude_plugin_json() -> dict:
    return {
        "name": "dex",
        "version": "1.0.0",
        "description": "Portable Dex context, safety, and work skills.",
        "author": {"name": "Dex"},
        "homepage": "https://heydex.ai",
        "repository": "https://github.com/davekilleen/Dex",
        "license": "MIT",
    }


def _hooks_json() -> dict:
    root = "${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-.}}"
    command = f'python3 "{root}/hook.py"'
    return {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|resume|clear|compact",
                    "hooks": [{"type": "command", "command": command}],
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "Bash|apply_patch|Write|Edit|MultiEdit",
                    "hooks": [{"type": "command", "command": command}],
                }
            ],
        }
    }


def _marketplace_json() -> dict:
    return {
        "name": "dex-unreleased",
        "interface": {"displayName": "Dex (unreleased local build)"},
        "plugins": [
            {
                "name": "dex",
                "source": {
                    "source": "local",
                    "path": "./packages/dex-agent-plugin",
                },
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        ],
    }


def _json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def _relative_files(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return ()
    return (
        path.relative_to(root)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not any(part.endswith("-custom") for part in path.relative_to(root).parts)
    )


def expected_plugin_files(repo_root: Path = REPO_ROOT) -> dict[Path, bytes]:
    plugin_root = repo_root / "packages" / "dex-agent-plugin"
    skills_source = repo_root / ".agents" / "skills"
    metadata_source = repo_root / "core" / "harnesses"
    expected: dict[Path, bytes] = {
        Path(".agents/plugins/marketplace.json"): _json_bytes(_marketplace_json()),
        Path("packages/dex-agent-plugin/plugin.json"): _json_bytes(_plugin_json()),
        Path("packages/dex-agent-plugin/mcp.json"): _json_bytes(_mcp_json()),
        Path("packages/dex-agent-plugin/.codex-plugin/plugin.json"): _json_bytes(
            _codex_plugin_json()
        ),
        Path("packages/dex-agent-plugin/.claude-plugin/plugin.json"): _json_bytes(
            _claude_plugin_json()
        ),
        Path("packages/dex-agent-plugin/.codex-mcp.json"): _json_bytes(
            _native_mcp_json("PLUGIN_ROOT", wrapped=False)
        ),
        Path("packages/dex-agent-plugin/.mcp.json"): _json_bytes(
            _native_mcp_json("CLAUDE_PLUGIN_ROOT", wrapped=True)
        ),
        Path("packages/dex-agent-plugin/hooks/hooks.json"): _json_bytes(_hooks_json()),
    }
    # Static launcher and bridge are source-controlled; include their exact
    # bytes in the golden map so --check detects a hard-coded path regression.
    for relative in (
        Path("bin/dex-mcp"),
        Path("server.py"),
        Path("hook.py"),
        Path("README.md"),
    ):
        source = plugin_root / relative
        if not source.is_file():
            raise ValueError(f"missing plugin source file: {source}")
        expected[(Path("packages/dex-agent-plugin") / relative)] = source.read_bytes()
    for relative in RUNTIME_SOURCES:
        source = repo_root / relative
        if not source.is_file():
            raise ValueError(f"missing portable runtime source file: {source}")
        expected[Path("packages/dex-agent-plugin/runtime") / relative] = source.read_bytes()
    for relative in _relative_files(skills_source):
        expected[Path("packages/dex-agent-plugin/skills") / relative] = (skills_source / relative).read_bytes()
    for relative in (Path("registry.json"), Path("portability.json")):
        source = metadata_source / relative
        expected[Path("packages/dex-agent-plugin/metadata/harnesses") / relative] = source.read_bytes()
    for relative in sorted((metadata_source / "adapters").glob("*.json")):
        expected[Path("packages/dex-agent-plugin/ai.heydex.dex/adapters") / relative.name] = relative.read_bytes()
        expected[Path("packages/dex-agent-plugin/metadata/harnesses/adapters") / relative.name] = relative.read_bytes()
    return expected


def _is_custom_path(path: Path, root: Path) -> bool:
    return any(part.endswith("-custom") for part in path.relative_to(root).parts)


def _existing_generated_files(plugin_root: Path, repo_root: Path) -> set[Path]:
    skills = plugin_root / "skills"
    metadata = plugin_root / "metadata" / "harnesses"
    extension = plugin_root / "ai.heydex.dex"
    runtime = plugin_root / "runtime"
    paths: set[Path] = set()
    for root in (skills, metadata, extension, runtime):
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and not _is_custom_path(path, root):
                paths.add(path)
    return paths


def write_plugin(repo_root: Path = REPO_ROOT) -> int:
    expected = expected_plugin_files(repo_root)
    plugin_root = repo_root / "packages" / "dex-agent-plugin"
    written = 0
    for relative, payload in expected.items():
        target = repo_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_bytes() != payload:
            target.write_bytes(payload)
            written += 1
    launcher = plugin_root / "bin" / "dex-mcp"
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    expected_paths = {repo_root / relative for relative in expected}
    removed = 0
    for stale in _existing_generated_files(plugin_root, repo_root):
        if stale not in expected_paths:
            stale.unlink()
            removed += 1
    print(f"Generated Agent Plugin ({len(expected)} files, {written} written, {removed} removed).")
    return 0


def check_plugin(repo_root: Path = REPO_ROOT) -> int:
    expected = expected_plugin_files(repo_root)
    errors: list[str] = []
    for relative, payload in expected.items():
        target = repo_root / relative
        if not target.is_file():
            errors.append(f"missing {relative.as_posix()}")
        elif target.read_bytes() != payload:
            errors.append(f"drifted {relative.as_posix()}")
    plugin_root = repo_root / "packages" / "dex-agent-plugin"
    expected_paths = {repo_root / relative for relative in expected}
    for extra in _existing_generated_files(plugin_root, repo_root):
        if extra not in expected_paths:
            errors.append(f"unexpected {extra.relative_to(repo_root).as_posix()}")
    launcher = plugin_root / "bin" / "dex-mcp"
    if launcher.is_file() and not launcher.stat().st_mode & stat.S_IXUSR:
        errors.append("bin/dex-mcp is not executable")
    if errors:
        print("❌ Agent Plugin is stale or incomplete:", file=sys.stderr)
        for error in errors[:40]:
            print(f"  {error}", file=sys.stderr)
        return 1
    print(f"Agent Plugin is current ({len(expected)} files).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the committed package")
    args = parser.parse_args()
    return check_plugin() if args.check else write_plugin()


if __name__ == "__main__":
    raise SystemExit(main())
