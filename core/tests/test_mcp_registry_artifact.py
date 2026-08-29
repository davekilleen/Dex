"""The proven read-only Dex MCP server packs as an unpublished npm artifact."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SOURCE = REPO_ROOT / "packages" / "dex-mcp"
PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-agent-plugin"
BUILDER = REPO_ROOT / "scripts" / "build-mcp-registry-artifact.py"
SAFE_PUBLISHER = REPO_ROOT / "scripts" / "run-mcp-publisher-safe.py"
READ_ONLY_TOOLS = {
    "dex_harness_profiles",
    "boot_today",
    "get_person_context",
    "check_safety_gate",
}


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_mcp_registry_artifact", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mcp_roundtrip(plugin_root: Path, messages: list[dict], *, vault: Path) -> list[dict]:
    payload = "".join(json.dumps(message) + "\n" for message in messages)
    completed = subprocess.run(
        ["node", str(plugin_root / "bin" / "dex-python.mjs"), "mcp"],
        input=payload,
        text=True,
        capture_output=True,
        cwd=vault,
        env={**os.environ, "PYTHONNOUSERSITE": "1", "DEX_VAULT_PATH": str(vault)},
        check=True,
    )
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def test_source_package_is_npm_shaped_and_unpublished() -> None:
    package = json.loads((PACKAGE_SOURCE / "package.json").read_text(encoding="utf-8"))
    server = json.loads((PACKAGE_SOURCE / "server.json").read_text(encoding="utf-8"))
    readme = (PACKAGE_SOURCE / "README.md").read_text(encoding="utf-8")

    assert package["name"] == "dex-mcp"
    assert package["private"] is True
    assert package["mcpName"] == "io.github.davekilleen/dex"
    assert package["bin"]["dex-mcp"] == "./bin/dex-python.mjs"
    assert "prepublishOnly" in package["scripts"]
    assert server["name"] == package["mcpName"]
    assert server["packages"][0]["identifier"] == "dex-mcp"
    assert server["packages"][0]["registryType"] == "npm"
    assert server["packages"][0]["transport"]["type"] == "stdio"
    assert "io.github.davekilleen/dex" in readme
    assert "npx -y dex-mcp" in readme
    assert "will not create an npm account" in readme
    assert "not publish" in readme
    assert "@heydex" not in json.dumps(package)
    assert "npm adduser" not in readme


def test_builder_packs_checksums_validates_and_stays_unreleased(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(BUILDER), "--output-dir", str(tmp_path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Still unreleased" in completed.stdout
    assert "Did not publish" in completed.stdout

    tarball = tmp_path / "dex-mcp-1.0.0.tgz"
    checksum = tmp_path / "dex-mcp-1.0.0.tgz.sha256"
    index = json.loads((tmp_path / "artifacts.json").read_text(encoding="utf-8"))
    staged = tmp_path / "dex-mcp"
    assert tarball.is_file()
    assert checksum.is_file()
    assert index["release_status"] == "unreleased"
    assert index["published"] is False
    assert index["one_line_after_publish"] == "io.github.davekilleen/dex"
    assert index["validation"]["npm_publish"] == "dry-run"
    assert index["artifacts"][0]["sha256"] == _sha256(tarball)
    assert checksum.read_text(encoding="utf-8").startswith(index["artifacts"][0]["sha256"])

    schema = _load_builder()._official_schema()
    if schema is not None:
        jsonschema.validate(
            json.loads((staged / "server.json").read_text(encoding="utf-8")),
            schema,
        )

    with tarfile.open(tarball, "r:gz") as archive:
        names = set(archive.getnames())
        package_file = archive.extractfile("package/package.json")
        server_file = archive.extractfile("package/server.py")
        assert package_file is not None
        assert server_file is not None
        package = json.loads(package_file.read())
        server_py = server_file.read()
    assert "package/server.py" in names
    assert "package/bin/dex-python.mjs" in names
    assert "package/runtime/core/gates/safety.py" in names
    assert package["private"] is True
    assert package["mcpName"] == "io.github.davekilleen/dex"
    assert server_py == (PLUGIN_ROOT / "server.py").read_bytes()
    assert not any(name.startswith("package/skills/") for name in names)


def test_packed_server_still_reads_a_vault_and_refuses_destruction(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, str(BUILDER), "--output-dir", str(tmp_path / "artifacts")],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    plugin_root = tmp_path / "artifacts" / "dex-mcp"
    vault = tmp_path / "Dex folder"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "pillars.yaml").write_text(
        'pillars:\n  - id: focus\n    name: "Focus"\n    description: "Do the important work"\n',
        encoding="utf-8",
    )
    person_dir = vault / "05-Areas" / "People" / "Internal"
    person_dir.mkdir(parents=True)
    (person_dir / "Ada_Lovelace.md").write_text(
        "---\nname: Ada Lovelace\nrole: Founder\ncompany: Analytical Engines\n---\n- [ ] Send the operating memo\n",
        encoding="utf-8",
    )
    responses = _mcp_roundtrip(
        plugin_root,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "boot_today", "arguments": {"vault_path": str(vault)}},
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "check_safety_gate",
                    "arguments": {"vault_path": str(vault), "command": "rm -rf /"},
                },
            },
        ],
        vault=vault,
    )
    assert {tool["name"] for tool in responses[1]["result"]["tools"]} == READ_ONLY_TOOLS
    assert responses[2]["result"]["structuredContent"]["pillars"][0]["name"] == "Focus"
    assert responses[3]["result"]["structuredContent"]["refused"] is True


def test_live_npm_publish_is_refused(tmp_path: Path) -> None:
    builder = _load_builder()
    staged = builder.stage_package(tmp_path)
    try:
        builder._forbid_live_publish(["npm", "publish"])
    except builder.RegistryArtifactError as error:
        assert "refusing live npm publish" in str(error)
    else:
        raise AssertionError("live npm publish must be refused")
    try:
        builder._forbid_live_publish(["mcp-publisher", "publish", "server.json"])
    except builder.RegistryArtifactError as error:
        assert "refusing mcp-publisher publish" in str(error)
    else:
        raise AssertionError("mcp-publisher publish must be refused")
    try:
        builder._forbid_live_publish(["mcp-publisher", "publish", "server.json", "--dry-run"])
    except builder.RegistryArtifactError as error:
        assert "refusing mcp-publisher publish" in str(error)
    else:
        raise AssertionError("mcp-publisher publish is refused even with --dry-run")

    blocked = subprocess.run(
        ["npm", "publish"],
        cwd=staged,
        text=True,
        capture_output=True,
        check=False,
    )
    assert blocked.returncode != 0
    assert "unreleased" in blocked.stderr.lower() or "dry-run" in blocked.stderr.lower()


def test_safe_publisher_wrapper_only_validates(tmp_path: Path) -> None:
    fake = tmp_path / "mcp-publisher"
    fake.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$0.args\"\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    refused = subprocess.run(
        [
            sys.executable,
            str(SAFE_PUBLISHER),
            "publish",
            str(PACKAGE_SOURCE / "server.json"),
            "--mcp-publisher",
            str(fake),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert refused.returncode != 0
    assert not Path(str(fake) + ".args").exists()

    completed = subprocess.run(
        [
            sys.executable,
            str(SAFE_PUBLISHER),
            "validate",
            str(PACKAGE_SOURCE / "server.json"),
            "--mcp-publisher",
            str(fake),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    recorded = Path(str(fake) + ".args").read_text(encoding="utf-8")
    assert recorded.startswith("validate ")
    assert "publish" not in recorded
    assert completed.returncode == 0


def test_builder_rejects_a_released_channel(tmp_path: Path) -> None:
    builder = _load_builder()
    try:
        builder.build(tmp_path, release_status="stable")
    except builder.RegistryArtifactError as error:
        assert "unreleased" in str(error)
    else:
        raise AssertionError("a released channel must be rejected")
