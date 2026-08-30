"""The proven read-only Dex MCP server packs as an unpublished npm artifact."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
from datetime import date
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
    "ask_what_was_decided",
    "ask_what_is_still_open_with_people",
    "ask_who_is_in_todays_plan",
    "ask_who_is_named_in_note",
    "ask_what_is_still_open_in_note",
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
    assert "package/runtime/core/context/decision_record.py" in names
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
        "---\nname: Ada Lovelace\nrole: Founder\ncompany: Analytical Engines\n"
        "last_interaction: 2026-04-12\n---\n- [ ] Send the operating memo\n",
        encoding="utf-8",
    )
    plans = vault / "00-Inbox" / "Daily_Plans"
    plans.mkdir(parents=True)
    (plans / f"{date.today().strftime('%Y-%m-%d')}.md").write_text(
        "# Daily Plan\n\n**Attendees:** Ada Lovelace\n",
        encoding="utf-8",
    )
    meetings = vault / "00-Inbox" / "Meetings"
    meetings.mkdir(parents=True)
    (meetings / "2026-08-30 - Engine review.md").write_text(
        "# Engine review\n\n"
        "Walked [[Ada Lovelace]] through the memo.\n"
        "- [ ] Follow up on the engine memo\n"
        "- [x] Already walked through it\n",
        encoding="utf-8",
    )
    decisions = vault / "06-Resources" / "Decisions"
    decisions.mkdir(parents=True)
    (decisions / "Decision_Log.md").write_text(
        "## 2026-04-12 — Keep pricing annual-only\n\n"
        "**Decision:** Sell only annual plans.\n",
        encoding="utf-8",
    )
    empty_vault = tmp_path / "empty Dex folder"
    empty_vault.mkdir()
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
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "ask_what_was_decided",
                    "arguments": {"vault_path": str(vault), "topic": "pricing"},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "ask_what_was_decided",
                    "arguments": {"vault_path": str(vault)},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "ask_what_is_still_open_with_people",
                    "arguments": {"vault_path": str(vault)},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "ask_what_is_still_open_with_people",
                    "arguments": {"vault_path": str(empty_vault)},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "ask_who_is_in_todays_plan",
                    "arguments": {"vault_path": str(vault)},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "ask_who_is_in_todays_plan",
                    "arguments": {"vault_path": str(empty_vault)},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "ask_who_is_named_in_note",
                    "arguments": {
                        "vault_path": str(vault),
                        "note_path": "00-Inbox/Meetings/2026-08-30 - Engine review.md",
                    },
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "ask_what_is_still_open_in_note",
                    "arguments": {
                        "vault_path": str(vault),
                        "note_path": "00-Inbox/Meetings/2026-08-30 - Engine review.md",
                    },
                },
            },
        ],
        vault=vault,
    )
    tools = responses[1]["result"]["tools"]
    assert {tool["name"] for tool in tools} == READ_ONLY_TOOLS
    ask_tool = next(tool for tool in tools if tool["name"] == "ask_what_was_decided")
    required = (ask_tool.get("inputSchema") or {}).get("required") or []
    assert "topic" not in required
    assert "lately" in ask_tool["description"]
    assert "no topic" in ask_tool["description"]
    open_tool = next(
        tool for tool in tools if tool["name"] == "ask_what_is_still_open_with_people"
    )
    assert "person" in open_tool["description"].lower()
    assert "page" in open_tool["description"].lower()
    today_tool = next(tool for tool in tools if tool["name"] == "ask_who_is_in_todays_plan")
    assert "today" in today_tool["description"].lower()
    assert "plan order" in today_tool["description"]
    required_today = (today_tool.get("inputSchema") or {}).get("required") or []
    assert "name" not in required_today
    assert responses[2]["result"]["structuredContent"]["pillars"][0]["name"] == "Focus"
    assert responses[3]["result"]["structuredContent"]["refused"] is True
    ask = responses[4]["result"]["structuredContent"]
    assert ask["found"] is True
    assert ask["matches"][0]["decision"] == "Sell only annual plans."
    assert ask["matches"][0]["file"] == "06-Resources/Decisions/Decision_Log.md"
    lately = responses[5]["result"]["structuredContent"]
    assert lately["found"] is True
    assert lately["topic"] == ""
    assert lately["matches"][0]["decision"] == "Sell only annual plans."
    assert lately["matches"][0]["file"] == "06-Resources/Decisions/Decision_Log.md"
    open_with_people = responses[6]["result"]["structuredContent"]
    assert open_with_people["found"] is True
    assert open_with_people["matches"][0]["item"] == "Send the operating memo"
    assert open_with_people["matches"][0]["person"] == "Ada Lovelace"
    assert open_with_people["matches"][0]["page"] == (
        "05-Areas/People/Internal/Ada_Lovelace.md"
    )
    assert (person_dir / "Ada_Lovelace.md").read_text(encoding="utf-8").startswith("---")
    none_open = responses[7]["result"]["structuredContent"]
    assert none_open["found"] is False
    assert none_open["matches"] == []
    assert none_open["sentence"] == "No unchecked to-dos on person pages."
    today_people = responses[8]["result"]["structuredContent"]
    assert today_people["found"] is True
    assert today_people["matches"][0]["person"] == "Ada Lovelace"
    assert today_people["matches"][0]["role"] == "Founder"
    assert today_people["matches"][0]["company"] == "Analytical Engines"
    assert today_people["matches"][0]["last_interaction"] == "2026-04-12"
    assert today_people["matches"][0]["open_items"] == ["Send the operating memo"]
    assert today_people["matches"][0]["page"] == (
        "05-Areas/People/Internal/Ada_Lovelace.md"
    )
    none_today = responses[9]["result"]["structuredContent"]
    assert none_today["found"] is False
    assert none_today["matches"] == []
    assert none_today["sentence"] == "Nobody is named in today's plan."
    note_tool = next(tool for tool in tools if tool["name"] == "ask_who_is_named_in_note")
    assert "note" in note_tool["description"].lower()
    assert "own order" in note_tool["description"]
    required_note = (note_tool.get("inputSchema") or {}).get("required") or []
    assert "note_path" in required_note
    who_in_note = responses[10]["result"]["structuredContent"]
    assert who_in_note["found"] is True
    assert who_in_note["matches"][0]["person"] == "Ada Lovelace"
    assert who_in_note["matches"][0]["role"] == "Founder"
    assert who_in_note["matches"][0]["company"] == "Analytical Engines"
    assert who_in_note["matches"][0]["last_interaction"] == "2026-04-12"
    assert who_in_note["matches"][0]["open_items"] == ["Send the operating memo"]
    assert who_in_note["matches"][0]["page"] == (
        "05-Areas/People/Internal/Ada_Lovelace.md"
    )
    open_in_note_tool = next(
        tool for tool in tools if tool["name"] == "ask_what_is_still_open_in_note"
    )
    assert "still open in one note" in open_in_note_tool["description"]
    assert "person pages" in open_in_note_tool["description"]
    required_open_note = (open_in_note_tool.get("inputSchema") or {}).get("required") or []
    assert "note_path" in required_open_note
    open_in_note = responses[11]["result"]["structuredContent"]
    assert open_in_note["found"] is True
    assert open_in_note["items"] == ["Follow up on the engine memo"]
    assert open_in_note["sentence"] == ""
    assert "Send the operating memo" not in open_in_note["items"]


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
