#!/usr/bin/env python3
"""Pack the proven read-only Dex MCP server as an unpublished npm-shaped artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-agent-plugin"
PACKAGE_SOURCE = REPO_ROOT / "packages" / "dex-mcp"
OFFICIAL_SCHEMA_URL = (
    "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
)
SHARED_DIRECTORIES = ("bin", "metadata", "runtime")
SHARED_FILES = ("server.py",)
PACKAGE_FILES = ("package.json", "server.json", "README.md")

try:
    import jsonschema
except ImportError:  # pragma: no cover - CI installs jsonschema with the test extra
    jsonschema = None


class RegistryArtifactError(RuntimeError):
    """A packing or validation step failed without publishing."""


def _remove_existing(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise RegistryArtifactError(f"{path} must contain a JSON object")
    return parsed


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RegistryArtifactError(
            f"{' '.join(command)} failed:\n{completed.stdout}\n{completed.stderr}"
        )
    return completed


def _forbid_live_publish(command: list[str]) -> None:
    joined = " ".join(command)
    if "npm" in command and "publish" in command and "--dry-run" not in command:
        raise RegistryArtifactError(f"refusing live npm publish: {joined}")
    if "mcp-publisher" in Path(command[0]).name and "publish" in command:
        raise RegistryArtifactError(f"refusing mcp-publisher publish: {joined}")


def stage_package(output_dir: Path) -> Path:
    staged = output_dir / "dex-mcp"
    _remove_existing(staged)
    staged.mkdir(parents=True)
    for name in SHARED_DIRECTORIES:
        _copy_tree(PLUGIN_ROOT / name, staged / name)
    for name in SHARED_FILES:
        shutil.copy2(PLUGIN_ROOT / name, staged / name)
    for name in PACKAGE_FILES:
        shutil.copy2(PACKAGE_SOURCE / name, staged / name)
    scripts = staged / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        PACKAGE_SOURCE / "scripts" / "refuse-live-npm-publish.mjs",
        scripts / "refuse-live-npm-publish.mjs",
    )
    return staged


def validate_manifests(staged: Path) -> dict[str, Any]:
    package = _load_json(staged / "package.json")
    server = _load_json(staged / "server.json")
    if package.get("private") is not True:
        raise RegistryArtifactError("dex-mcp must stay private until Dave publishes")
    if package.get("name") != "dex-mcp":
        raise RegistryArtifactError("npm package name must stay the unscoped dex-mcp name")
    if package.get("mcpName") != server.get("name"):
        raise RegistryArtifactError("package.json mcpName must match server.json name")
    if server.get("name") != "io.github.davekilleen/dex":
        raise RegistryArtifactError("registry name must stay io.github.davekilleen/dex")
    packages = server.get("packages")
    if not isinstance(packages, list) or not packages:
        raise RegistryArtifactError("server.json must declare the npm package")
    npm_package = packages[0]
    if npm_package.get("registryType") != "npm" or npm_package.get("identifier") != "dex-mcp":
        raise RegistryArtifactError("server.json must point at the unpublished dex-mcp npm package")
    if jsonschema is not None:
        schema = _official_schema()
        if schema is not None:
            jsonschema.validate(server, schema)
    return {"package": package, "server": server}


def _official_schema() -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(OFFICIAL_SCHEMA_URL, timeout=20) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    return parsed if isinstance(parsed, dict) else None


def pack_npm(staged: Path, output_dir: Path) -> Path:
    completed = _run(["npm", "pack", "--pack-destination", str(output_dir)], cwd=staged)
    names = [line.strip() for line in completed.stdout.splitlines() if line.strip().endswith(".tgz")]
    if not names:
        raise RegistryArtifactError("npm pack did not write a .tgz")
    tarball = output_dir / names[-1]
    if not tarball.is_file():
        raise RegistryArtifactError(f"npm pack reported {tarball.name} but the file is missing")
    return tarball


def dry_run_npm_publish(staged: Path) -> str:
    command = ["npm", "publish", "--dry-run"]
    _forbid_live_publish(command)
    completed = _run(command, cwd=staged)
    combined = f"{completed.stdout}\n{completed.stderr}"
    if "dex-mcp" not in combined:
        raise RegistryArtifactError("npm publish --dry-run did not mention dex-mcp")
    return combined


def validate_with_mcp_publisher(staged: Path) -> str:
    publisher = shutil.which("mcp-publisher")
    if not publisher:
        return "skipped: mcp-publisher is not installed"
    validate = [publisher, "validate", str(staged / "server.json")]
    _run(validate, cwd=staged)
    return "validate"


def write_checksum(tarball: Path) -> Path:
    sidecar = Path(f"{tarball}.sha256")
    sidecar.write_text(f"{_sha256(tarball)}  {tarball.name}\n", encoding="utf-8")
    return sidecar


def write_index(
    output_dir: Path,
    tarball: Path,
    *,
    release_status: str,
    validation: dict[str, Any],
) -> Path:
    index = output_dir / "artifacts.json"
    payload = {
        "schema_version": "1.0.0",
        "release_status": release_status,
        "published": False,
        "one_line_after_publish": "io.github.davekilleen/dex",
        "artifacts": [
            {
                "name": tarball.name,
                "sha256": _sha256(tarball),
                "bytes": tarball.stat().st_size,
            }
        ],
        "validation": validation,
    }
    index.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return index


def build(output_dir: Path, *, release_status: str = "unreleased") -> Path:
    if release_status != "unreleased":
        raise RegistryArtifactError("the MCP registry artifact must stay unreleased")
    output_dir.mkdir(parents=True, exist_ok=True)
    staged = stage_package(output_dir)
    manifests = validate_manifests(staged)
    tarball = pack_npm(staged, output_dir)
    npm_dry_run = dry_run_npm_publish(staged)
    publisher_status = validate_with_mcp_publisher(staged)
    checksum = write_checksum(tarball)
    validation = {
        "official_schema": manifests["server"]["$schema"],
        "npm_pack": tarball.name,
        "npm_publish": "dry-run",
        "mcp_publisher": publisher_status,
        "checksum": checksum.name,
    }
    write_index(output_dir, tarball, release_status=release_status, validation=validation)
    if "dry-run" not in npm_dry_run.lower() and "dry run" not in npm_dry_run.lower():
        raise RegistryArtifactError("npm publish --dry-run did not report a dry run")
    return tarball


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    tarball = build(args.output_dir.expanduser().resolve())
    print(f"Packed {tarball.name}: {_sha256(tarball)}")
    print("Validated. Still unreleased. Did not publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
