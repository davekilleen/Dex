"""Dedicated safety contracts for user-blessed local MCP startup checks."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.utils import doctor, mcp_handshake, smoke, trust_registry
from core.utils.mcp_handshake import mcp_stdio_handshake
from core.utils.trust_registry import (
    TrustRegistryError,
    bless_local_mcp,
    load_trusted_mcp_registry,
    snapshot_trusted_mcp,
)


def _valid_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "System" / "integrations").mkdir(parents=True)
    (vault / "custom-mcp").mkdir()
    (vault / "03-Tasks").mkdir()
    (vault / ".claude").mkdir()
    (vault / "System" / "user-profile.yaml").write_text("name: Safety Test\n")
    (vault / "System" / "pillars.yaml").write_text("pillars: []\n")
    (vault / "System" / ".onboarding-complete").write_text("{}\n")
    (vault / "System" / "integrations" / "config.yaml").write_text(
        "enabled: {}\nhooks: {}\n"
    )
    (vault / "03-Tasks" / "Tasks.md").write_text("# Tasks\n")
    (vault / ".claude" / "settings.json").write_text('{"hooks": {}}\n')
    return vault


def _entry(script: Path) -> dict[str, object]:
    return {"command": sys.executable, "args": [str(script)], "env": {"SENTINEL": "ignored"}}


def _write_config(vault: Path, name: str, entry: dict[str, object]) -> None:
    (vault / ".mcp.json").write_text(json.dumps({"mcpServers": {name: entry}}))


def _write_registry(vault: Path, name: str, relative: str, content: bytes) -> None:
    (vault / "System" / "trusted-mcps.yaml").write_text(
        "trusted_mcps:\n"
        f"  {name}:\n"
        f"    file: {relative}\n"
        f"    sha256: {hashlib.sha256(content).hexdigest()}\n"
    )


def _server(marker: Path, value: str) -> bytes:
    return (
        "import json, sys\n"
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text({value!r})\n"
        "request = json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': "
        "{'capabilities': {}, 'serverInfo': {'name': 'trusted-test', 'version': '1'}}}), "
        "flush=True)\n"
    ).encode()


def _smoke(vault: Path) -> dict[str, object]:
    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=Path(__file__).resolve().parents[2],
        journey_definitions=(smoke.JourneyDefinition("mcp_startup", 8.0),),
    )
    assert run.exit_code == 0
    return run.report["journeys"][0]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def test_s1_consent_text_never_calls_execution_a_sandbox() -> None:
    root = Path(__file__).resolve().parents[2]
    surfaces = [
        root / ".claude" / "skills" / "create-mcp" / "SKILL.md",
        root / "06-Resources" / "Dex_System" / "Dex_Technical_Guide.md",
        root / "System" / "trusted-mcps.example.yaml",
    ]
    joined = "\n".join(path.read_text(encoding="utf-8") for path in surfaces)

    assert "with your user permissions" in joined
    assert "nightly and in deep scans" in joined
    assert "trusts whatever it imports" in joined
    assert "sandbox" not in joined.lower()


def test_s2_open_fd_is_hashed_copied_and_executed_after_live_path_swap(
    tmp_path: Path,
) -> None:
    vault = _valid_vault(tmp_path)
    original_marker = tmp_path / "original-ran"
    swapped_marker = tmp_path / "swapped-ran"
    original = (
        f"from pathlib import Path\nPath({str(original_marker)!r}).write_text('ORIGINAL')\n"
    ).encode()
    swapped = (
        f"from pathlib import Path\nPath({str(swapped_marker)!r}).write_text('SWAPPED')\n"
    ).encode()
    script = vault / "custom-mcp" / "server.py"
    script.write_bytes(original)
    _write_registry(vault, "custom-sentinel", "custom-mcp/server.py", original)
    registry = load_trusted_mcp_registry(vault)

    def swap_after_open(_fd: int) -> None:
        replacement = script.with_suffix(".replacement")
        replacement.write_bytes(swapped)
        os.replace(replacement, script)

    decision = snapshot_trusted_mcp(
        vault,
        "custom-sentinel",
        _entry(script),
        registry,
        tmp_path / "snapshots",
        after_open=swap_after_open,
    )

    assert decision.trusted is True
    assert decision.snapshot_path is not None
    assert decision.snapshot_path.read_bytes() == original
    exec(compile(decision.snapshot_path.read_bytes(), str(decision.snapshot_path), "exec"))
    assert original_marker.read_text() == "ORIGINAL"
    assert not swapped_marker.exists()


def test_f1_snapshot_reads_source_descriptor_in_one_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _valid_vault(tmp_path)
    content = b"print('single pass')\n"
    script = vault / "custom-mcp" / "server.py"
    script.write_bytes(content)
    _write_registry(vault, "custom-single-pass", "custom-mcp/server.py", content)
    source_fd: int | None = None
    source_reads: list[bytes] = []
    original_read = trust_registry.os.read

    def remember_source(descriptor: int) -> None:
        nonlocal source_fd
        source_fd = descriptor

    def counting_read(descriptor: int, size: int) -> bytes:
        chunk = original_read(descriptor, size)
        if descriptor == source_fd:
            source_reads.append(chunk)
        return chunk

    monkeypatch.setattr(trust_registry.os, "read", counting_read)

    decision = snapshot_trusted_mcp(
        vault,
        "custom-single-pass",
        _entry(script),
        load_trusted_mcp_registry(vault),
        tmp_path / "snapshots",
        after_open=remember_source,
    )

    assert decision.trusted is True
    assert source_reads == [content, b""]
    assert decision.snapshot_path is not None
    assert decision.snapshot_path.read_bytes() == content


def test_f2_snapshot_replaced_before_launch_is_refused(tmp_path: Path) -> None:
    launch_root = tmp_path / "launch"
    launch_root.mkdir()
    snapshot_root = launch_root / "snapshot"
    snapshot_root.mkdir(mode=0o700)
    marker = tmp_path / "replacement-ran"
    original = _server(tmp_path / "original-ran", "ORIGINAL")
    replacement = _server(marker, "REPLACEMENT")
    digest = hashlib.sha256(original).hexdigest()
    snapshot = snapshot_root / f"custom-race-{digest}.py"
    snapshot.write_bytes(original)
    snapshot.chmod(0o400)
    replacement_path = snapshot_root / "replacement.py"
    replacement_path.write_bytes(replacement)
    replacement_path.chmod(0o400)
    os.replace(replacement_path, snapshot)

    bootstrap = smoke._install_network_guard(launch_root) / "server_bootstrap.py"
    isolated_vault = launch_root / "vault"
    isolated_vault.mkdir()
    result = mcp_stdio_handshake(
        [sys.executable, "-S", str(bootstrap), "--verified-snapshot", str(snapshot)],
        cwd=isolated_vault,
        env={"HOME": str(launch_root), "PATH": os.environ.get("PATH", "")},
        timeout=1.5,
    )

    assert result.ok is False
    assert "snapshot changed before launch" in result.stderr
    assert not marker.exists()


def test_f2_recurring_launch_reports_replaced_snapshot_as_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    snapshot_root = vault / ".dex-trusted-mcp-snapshots"
    snapshot_root.mkdir(parents=True, mode=0o700)
    marker = tmp_path / "replacement-ran"
    original = _server(tmp_path / "original-ran", "ORIGINAL")
    replacement = _server(marker, "REPLACEMENT")
    digest = hashlib.sha256(original).hexdigest()
    snapshot = snapshot_root / f"custom-race-{digest}.py"
    snapshot.write_bytes(original)
    snapshot.chmod(0o400)
    (vault / smoke.MCP_PLAN).write_text(
        json.dumps(
            {
                "state": "OK",
                "entries": [
                    {
                        "name": "custom-race",
                        "verdict": "EXECUTE",
                        "kind": "trusted-custom",
                        "script": snapshot.relative_to(vault).as_posix(),
                    }
                ],
            }
        )
    )
    bootstrap = smoke._install_network_guard(tmp_path) / "server_bootstrap.py"
    monkeypatch.setenv("DEX_SMOKE_SERVER_BOOTSTRAP", str(bootstrap))
    original_handshake = mcp_handshake.mcp_stdio_handshake

    def replace_then_launch(*args: object, **kwargs: object) -> object:
        replacement_path = snapshot_root / "replacement.py"
        replacement_path.write_bytes(replacement)
        replacement_path.chmod(0o400)
        os.replace(replacement_path, snapshot)
        return original_handshake(*args, **kwargs)

    monkeypatch.setattr(mcp_handshake, "mcp_stdio_handshake", replace_then_launch)

    result = smoke._journey_mcp_startup(vault, tmp_path / "release")

    assert result == {
        "verdict": "UNKNOWN",
        "detail": "custom-race: UNKNOWN — snapshot changed before launch",
    }
    assert not marker.exists()


@pytest.mark.parametrize(
    ("name", "registry_name", "registry_file", "entry", "reason"),
    [
        (
            "custom-real",
            "custom-other",
            "custom-mcp/server.py",
            None,
            "not registered under the same name",
        ),
        (
            "custom-real",
            "custom-real",
            "custom-mcp/other.py",
            None,
            "file does not match",
        ),
        (
            "custom-real",
            "custom-real",
            "custom-mcp/server.py",
            {"command": sys.executable, "args": ["-m", "server"]},
            "exactly one .py argument",
        ),
    ],
)
def test_s3_all_identity_fields_and_local_python_shape_must_match(
    tmp_path: Path,
    name: str,
    registry_name: str,
    registry_file: str,
    entry: dict[str, object] | None,
    reason: str,
) -> None:
    vault = _valid_vault(tmp_path)
    script = vault / "custom-mcp" / "server.py"
    script.write_text("pass\n")
    (vault / "custom-mcp" / "other.py").write_text("pass\n")
    _write_registry(vault, registry_name, registry_file, script.read_bytes())

    decision = snapshot_trusted_mcp(
        vault,
        name,
        entry or _entry(script),
        load_trusted_mcp_registry(vault),
        tmp_path / "snapshots",
    )

    assert decision.trusted is False
    assert reason in decision.detail


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (
            "shared: &entry\n  file: custom-mcp/server.py\n  sha256: " + "0" * 64
            + "\ntrusted_mcps:\n  custom-a: *entry\n",
            "anchors or aliases",
        ),
        (
            "trusted_mcps:\n  custom-a:\n    file: custom-mcp/server.py\n    file: custom-mcp/other.py\n    sha256: "
            + "0" * 64
            + "\n",
            "duplicate key",
        ),
        ("x" * (64 * 1024 + 1), "larger than 64KB"),
    ],
)
def test_s4_invalid_registry_is_treated_as_absent(
    tmp_path: Path,
    body: str,
    reason: str,
) -> None:
    vault = _valid_vault(tmp_path)
    (vault / "System" / "trusted-mcps.yaml").write_text(body)

    registry = load_trusted_mcp_registry(vault)

    assert registry.entries == {}
    assert registry.invalid_reason is not None
    assert reason in registry.invalid_reason


def test_h1_deeply_nested_registry_is_invalid_instead_of_crashing(tmp_path: Path) -> None:
    vault = _valid_vault(tmp_path)
    nested = "[" * 500 + "0" + "]" * 500
    (vault / "System" / "trusted-mcps.yaml").write_text(f"trusted_mcps: {nested}\n")

    registry = load_trusted_mcp_registry(vault)

    assert registry.entries == {}
    assert "registry YAML is invalid" in (registry.invalid_reason or "")


def test_h2_group_writable_registry_is_refused(tmp_path: Path) -> None:
    vault = _valid_vault(tmp_path)
    registry_path = vault / "System" / "trusted-mcps.yaml"
    registry_path.write_text("trusted_mcps: {}\n")
    registry_path.chmod(0o620)

    registry = load_trusted_mcp_registry(vault)

    assert registry.entries == {}
    assert registry.invalid_reason == "registry is group- or other-writable"


def test_h2_group_writable_snapshot_directory_is_refused(tmp_path: Path) -> None:
    vault = _valid_vault(tmp_path)
    script = vault / "custom-mcp" / "server.py"
    content = b"pass\n"
    script.write_bytes(content)
    _write_registry(vault, "custom-server", "custom-mcp/server.py", content)
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()
    snapshot_root.chmod(0o770)

    decision = snapshot_trusted_mcp(
        vault,
        "custom-server",
        _entry(script),
        load_trusted_mcp_registry(vault),
        snapshot_root,
    )

    assert decision.trusted is False
    assert decision.detail == "snapshot directory is group- or other-writable"


def test_f3_git_tracked_registry_is_refused(tmp_path: Path) -> None:
    vault = _valid_vault(tmp_path)
    script = vault / "custom-mcp" / "server.py"
    content = b"pass\n"
    script.write_bytes(content)
    _write_registry(vault, "custom-server", "custom-mcp/server.py", content)
    _git(vault, "init", "-b", "main")
    _git(vault, "config", "user.name", "Dex Test")
    _git(vault, "config", "user.email", "dex-test@example.com")
    _git(vault, "add", "-f", "System/trusted-mcps.yaml")

    registry = load_trusted_mcp_registry(vault)

    assert registry.entries == {}
    assert registry.invalid_reason == "registry is git-tracked; upstream files cannot grant consent"


def test_f3_update_guard_removes_registry_introduced_by_merge(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "System").mkdir()
    (repo / ".gitignore").write_text("System/trusted-mcps.yaml\n")
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Dex Test")
    _git(repo, "config", "user.email", "dex-test@example.com")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "baseline")
    state = tmp_path / "trust-state"
    guard = (
        Path(__file__).resolve().parents[2]
        / ".claude"
        / "skills"
        / "dex-update"
        / "scripts"
        / "protect_trust_registry.py"
    )
    captured = subprocess.run(
        [sys.executable, str(guard), "capture", "--repo", str(repo), "--state", str(state)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert captured.returncode == 0, captured.stderr

    _git(repo, "switch", "-c", "upstream-release")
    (repo / "System" / "trusted-mcps.yaml").write_text("trusted_mcps: {}\n")
    _git(repo, "add", "-f", "System/trusted-mcps.yaml")
    _git(repo, "commit", "-m", "upstream injects registry")
    _git(repo, "switch", "main")
    _git(repo, "merge", "upstream-release", "--no-edit")

    restored = subprocess.run(
        [sys.executable, str(guard), "restore", "--repo", str(repo), "--state", str(state)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert restored.returncode == 0, restored.stderr
    assert "rejected git-tracked System/trusted-mcps.yaml" in restored.stdout
    assert _git(repo, "ls-files", "--", "System/trusted-mcps.yaml").stdout == ""
    assert not (repo / "System" / "trusted-mcps.yaml").exists()


def test_s4_registry_rejects_symlink_paths_and_executable_keys(tmp_path: Path) -> None:
    vault = _valid_vault(tmp_path)
    registry_path = vault / "System" / "trusted-mcps.yaml"
    outside = tmp_path / "outside.yaml"
    outside.write_text("trusted_mcps: {}\n")
    registry_path.symlink_to(outside)
    assert "symlink" in (load_trusted_mcp_registry(vault).invalid_reason or "")

    registry_path.unlink()
    registry_path.write_text(
        "trusted_mcps:\n"
        "  custom-a:\n"
        "    file: ../outside.py\n"
        f"    sha256: {'0' * 64}\n"
        "    command: python\n"
    )
    reason = load_trusted_mcp_registry(vault).invalid_reason or ""
    assert "unknown key" in reason or "unsafe vault-relative path" in reason


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        ("[]", "must be a mapping"),
        (
            "{file: /tmp/server.py, sha256: " + "0" * 64 + "}",
            "unsafe vault-relative path",
        ),
        (
            "{file: custom-mcp/server.py, sha256: " + "0" * 64 + ", args: []}",
            "unknown key",
        ),
    ],
)
def test_s4_registry_rejects_non_mapping_absolute_and_executable_shapes(
    tmp_path: Path,
    entry: str,
    reason: str,
) -> None:
    vault = _valid_vault(tmp_path)
    (vault / "System" / "trusted-mcps.yaml").write_text(
        f"trusted_mcps:\n  custom-a: {entry}\n"
    )

    registry = load_trusted_mcp_registry(vault)

    assert registry.entries == {}
    assert reason in (registry.invalid_reason or "")


def test_s5_hand_blessed_npx_entry_is_structural_only(tmp_path: Path) -> None:
    vault = _valid_vault(tmp_path)
    script = vault / "custom-mcp" / "server.py"
    script.write_text("pass\n")
    _write_registry(vault, "custom-npx", "custom-mcp/server.py", script.read_bytes())

    decision = snapshot_trusted_mcp(
        vault,
        "custom-npx",
        {"command": "npx", "args": ["some-package"]},
        load_trusted_mcp_registry(vault),
        tmp_path / "snapshots",
    )

    assert decision.trusted is False
    assert "only local Python" in decision.detail


def test_s5_bless_command_refuses_npx_before_creating_registry(tmp_path: Path) -> None:
    vault = _valid_vault(tmp_path)
    _write_config(vault, "custom-npx", {"command": "npx", "args": ["some-package"]})

    with pytest.raises(TrustRegistryError, match="only local Python"):
        bless_local_mcp(vault, "custom-npx")

    assert not (vault / "System" / "trusted-mcps.yaml").exists()


def test_bless_command_creates_user_registry_and_binds_displayed_hash(tmp_path: Path) -> None:
    vault = _valid_vault(tmp_path)
    script = vault / "custom-mcp" / "server.py"
    script.write_text("pass\n")
    _write_config(vault, "custom-server", _entry(script))
    (vault / "System" / "trusted-mcps.example.yaml").write_text("trusted_mcps: {}\n")
    digest = hashlib.sha256(script.read_bytes()).hexdigest()

    trusted = bless_local_mcp(vault, "custom-server", expected_sha256=digest)

    assert trusted.file == "custom-mcp/server.py"
    assert trusted.sha256 == digest
    registry = load_trusted_mcp_registry(vault)
    assert registry.entries["custom-server"] == trusted
    assert (vault / "System" / "trusted-mcps.yaml").stat().st_mode & 0o777 == 0o600

    script.write_text("# changed\n")
    with pytest.raises(TrustRegistryError, match="changed after the consent details"):
        bless_local_mcp(vault, "custom-server", expected_sha256=digest)


def test_f4_one_off_without_consent_token_refuses_without_execution(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = _valid_vault(tmp_path)
    marker = tmp_path / "one-off-ran"
    script = vault / "custom-mcp" / "server.py"
    script.write_bytes(_server(marker, "UNCONSENTED"))
    _write_config(vault, "custom-once", _entry(script))

    exit_code = smoke.main(["--check-mcp-once", "custom-once"], vault_root=vault)

    assert exit_code == 1
    assert "valid fresh single-use consent token is required" in capsys.readouterr().out
    assert not marker.exists()


def test_f4_one_off_token_is_single_use_and_runs_in_temp_vault(tmp_path: Path) -> None:
    vault = _valid_vault(tmp_path)
    marker = tmp_path / "one-off-context.jsonl"
    script = vault / "custom-mcp" / "server.py"
    script.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"with Path({str(marker)!r}).open('a') as handle:\n"
        "    handle.write(json.dumps({'cwd': os.getcwd(), 'vault': os.environ['VAULT_PATH']}) + '\\n')\n"
        "request = json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': "
        "{'capabilities': {}, 'serverInfo': {'name': 'trusted-test', 'version': '1'}}}), flush=True)\n"
    )
    _write_config(vault, "custom-once", _entry(script))
    token = smoke.issue_mcp_once_consent_token("custom-once", directory=tmp_path)

    first = smoke.check_custom_mcp_once(vault, "custom-once", consent_token=token)
    second = smoke.check_custom_mcp_once(vault, "custom-once", consent_token=token)

    assert first["verdict"] == "OK"
    assert second == {
        "verdict": "UNKNOWN",
        "detail": "valid fresh single-use consent token is required",
    }
    assert not token.exists()
    contexts = [json.loads(line) for line in marker.read_text().splitlines()]
    assert len(contexts) == 1
    assert contexts[0]["cwd"] != str(vault)
    assert contexts[0]["vault"] != str(vault)
    assert contexts[0]["cwd"] == contexts[0]["vault"]


def test_blessed_local_python_executes_snapshot_with_configured_env_scrubbed(
    tmp_path: Path,
) -> None:
    vault = _valid_vault(tmp_path)
    marker = tmp_path / "blessed-ran"
    script = vault / "custom-mcp" / "server.py"
    script.write_bytes(
        (
            "import json, os, sys\n"
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text(os.environ.get('SENTINEL', 'SCRUBBED'))\n"
            "request = json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': "
            "{'capabilities': {}, 'serverInfo': {'name': 'trusted-test', 'version': '1'}}}), "
            "flush=True)\n"
        ).encode()
    )
    _write_config(vault, "custom-sentinel", _entry(script))
    _write_registry(vault, "custom-sentinel", "custom-mcp/server.py", script.read_bytes())

    result = _smoke(vault)

    assert result["verdict"] == "OK"
    assert result["detail"] == "custom-sentinel: OK"
    assert marker.read_text() == "SCRUBBED"


def test_s6_unregistered_custom_entry_keeps_existing_detail_and_never_executes(
    tmp_path: Path,
) -> None:
    vault = _valid_vault(tmp_path)
    marker = tmp_path / "unregistered-ran"
    script = vault / "custom-mcp" / "server.py"
    script.write_bytes(_server(marker, "UNREGISTERED"))
    _write_config(vault, "custom-sentinel", _entry(script))

    result = _smoke(vault)

    assert result["verdict"] == "UNKNOWN"
    assert result["detail"] == "custom-sentinel: UNKNOWN — not executed for safety"
    assert not marker.exists()


def test_s6_blessed_then_modified_never_executes_and_names_rebless_action(
    tmp_path: Path,
) -> None:
    vault = _valid_vault(tmp_path)
    original_marker = tmp_path / "original-ran"
    modified_marker = tmp_path / "modified-ran"
    script = vault / "custom-mcp" / "server.py"
    original = _server(original_marker, "ORIGINAL")
    script.write_bytes(original)
    _write_config(vault, "custom-sentinel", _entry(script))
    _write_registry(vault, "custom-sentinel", "custom-mcp/server.py", original)
    script.write_bytes(_server(modified_marker, "MODIFIED"))

    result = _smoke(vault)

    assert result["verdict"] == "UNKNOWN"
    assert "changed since you blessed it (content differs)" in result["detail"]
    assert "re-bless via /create-mcp or edit System/trusted-mcps.yaml" in result["detail"]
    assert not original_marker.exists()
    assert not modified_marker.exists()


def test_s6_blessed_symlink_target_never_executes(tmp_path: Path) -> None:
    vault = _valid_vault(tmp_path)
    marker = tmp_path / "symlink-ran"
    external = tmp_path / "external.py"
    content = _server(marker, "SYMLINK")
    external.write_bytes(content)
    script = vault / "custom-mcp" / "server.py"
    script.symlink_to(external)
    _write_config(vault, "custom-sentinel", _entry(script))
    _write_registry(vault, "custom-sentinel", "custom-mcp/server.py", content)

    result = _smoke(vault)

    assert result["verdict"] == "UNKNOWN"
    assert "symlink" in result["detail"]
    assert not marker.exists()


def test_s6_missing_blessed_file_is_unknown_with_precise_reason(tmp_path: Path) -> None:
    vault = _valid_vault(tmp_path)
    script = vault / "custom-mcp" / "missing.py"
    _write_config(vault, "custom-missing", _entry(script))
    _write_registry(vault, "custom-missing", "custom-mcp/missing.py", b"never existed")

    result = _smoke(vault)

    assert result["verdict"] == "UNKNOWN"
    assert "custom-mcp/missing.py file is missing" in result["detail"]


def test_s6_invalid_registry_reason_is_reported_without_execution(tmp_path: Path) -> None:
    vault = _valid_vault(tmp_path)
    marker = tmp_path / "invalid-registry-ran"
    script = vault / "custom-mcp" / "server.py"
    script.write_bytes(_server(marker, "INVALID"))
    _write_config(vault, "custom-sentinel", _entry(script))
    (vault / "System" / "trusted-mcps.yaml").write_text(
        "trusted_mcps:\n  custom-sentinel: &bad\n"
        "    file: custom-mcp/server.py\n"
        f"    sha256: {'0' * 64}\n"
    )

    result = _smoke(vault)

    assert result["verdict"] == "UNKNOWN"
    assert "registry is invalid" in result["detail"]
    assert "anchors or aliases" in result["detail"]
    assert not marker.exists()


def test_doctor_mirrors_blessed_and_changed_states_without_executing(tmp_path: Path) -> None:
    vault = _valid_vault(tmp_path)
    script = vault / "custom-mcp" / "server.py"
    content = b"pass\n"
    script.write_bytes(content)
    _write_config(vault, "custom-server", _entry(script))
    _write_registry(vault, "custom-server", "custom-mcp/server.py", content)
    context = doctor.DoctorContext(
        vault_root=vault,
        repo_root=vault,
        home=tmp_path / "home",
        now=datetime(2026, 7, 13, tzinfo=timezone.utc),
    )

    blessed = doctor._probe_customization_mcp(context)
    script.write_text("# changed\n")
    changed = doctor._probe_customization_mcp(context)

    assert blessed.verdict == "OK"
    assert "is blessed: this runs custom-mcp/server.py with your user permissions" in blessed.detail
    assert changed.verdict == "UNKNOWN"
    assert "changed since you blessed it (content differs)" in changed.detail
