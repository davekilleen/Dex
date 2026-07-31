"""Focused contracts for the one-time lifecycle-era updater bridge."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections import namedtuple
from pathlib import Path
from types import ModuleType

import pytest

from scripts import dex_update_bridge as bridge


class _Service:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def build_and_preview_topology_migration(self, vault_root: Path):
        self.calls.append("topology-preview")
        return {"preview": {"step": "topology"}, "approval_token": "topology-token"}

    def execute_approved_topology_migration(self, vault_root: Path, preview, approved_token: str):
        self.calls.append(f"topology-execute:{approved_token}")
        assert preview == {"step": "topology"}
        return {"receipt": "topology"}

    def build_and_preview_delivered_release(self, vault_root: Path, release):
        self.calls.append("release-preview")
        assert release == bridge.FOUNDATION.identity()
        return {"preview": {"step": "release"}, "approval_token": "release-token"}

    def execute_approved_delivered_release(self, vault_root: Path, preview, approved_token: str):
        self.calls.append(f"release-execute:{approved_token}")
        assert preview == {"step": "release"}
        return {"receipt": "release"}

    def build_and_preview_mcp_registration(self, vault_root: Path):
        self.calls.append("mcp-preview")
        return {
            "needed": True,
            "preview": {"step": "mcp-registration"},
            "approval_token": "mcp-token",
        }

    def execute_approved_mcp_registration(
        self,
        vault_root: Path,
        preview,
        approved_token: str,
    ):
        self.calls.append(f"mcp-execute:{approved_token}")
        assert preview == {"step": "mcp-registration"}
        return {"receipt": "mcp-registration"}



class _SplitService(_Service):
    def build_and_preview_topology_migration(self, vault_root: Path):
        self.calls.append("topology-preview")
        return {
            "topology": "post-split",
            "preview": {"status": "already complete"},
            "approval_token": None,
        }


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / ".git").mkdir(parents=True)
    (vault / ".dex" / "brain.git").mkdir(parents=True)
    (vault / "System").mkdir()
    return vault


def _completed_vault(tmp_path: Path) -> Path:
    vault = _vault(tmp_path)
    (vault / "System" / ".dex").mkdir()
    (vault / "System" / ".dex" / "topology.json").write_text(
        '{"topology":"brain-vault-split","vaultGitDir":".git",'
        '"brainGitDir":".dex/brain.git","installedRelease":"'
        + bridge.FOUNDATION.commit
        + '","environment":{"DEX_VAULT":"'
        + str(vault)
        + '"}}\n',
        encoding="utf-8",
    )
    (vault / ".git" / "dex-vault-v2").write_text('{"role":"vault"}\n', encoding="utf-8")
    (vault / ".dex" / "brain.git" / "dex-brain-v2").write_text(
        '{"role":"brain","installed":"' + bridge.FOUNDATION.commit + '"}\n',
        encoding="utf-8",
    )
    return vault


def _foundation_topology_adapter(
    tmp_path: Path,
) -> tuple[bridge._FoundationLifecycleService, ModuleType, Path, Path]:
    source = tmp_path / "foundation"
    migrator = source / bridge._TOPOLOGY_MIGRATOR_RELATIVE
    migrator.parent.mkdir(parents=True)
    migrator.write_text("'use strict';\n", encoding="utf-8")
    vault = _vault(tmp_path)
    engine = ModuleType("test_foundation_engine")
    engine.TOPOLOGY_MIGRATOR_RELATIVE = bridge._TOPOLOGY_MIGRATOR_RELATIVE

    def original_state(_vault_root: Path) -> str:
        return "invalid-combined"

    def original_command(_vault_root: Path, _mode: str) -> list[str]:
        raise RuntimeError("vault migrator was rejected")

    def original_run(vault_root: Path, mode: str):
        return subprocess.run(
            engine._migrator_command(vault_root, mode),
            cwd=vault_root,
            capture_output=True,
            text=True,
            check=False,
        )

    engine.topology_state = original_state
    engine._migrator_command = original_command
    engine._run_topology_migrator = original_run
    apply_update = ModuleType("test_foundation_apply_update")
    apply_update._tree_entries = lambda *_arguments: ()
    apply_update._verify_manifest = lambda *_arguments: None
    apply_update.portable_contract = ModuleType("test_portable_contract")
    apply_update.portable_contract.ContractViolation = RuntimeError
    apply_update.TreeEntry = tuple

    class Service:
        def build_and_preview_topology_migration(self, vault_root: Path):
            state = engine.topology_state(vault_root)
            return {
                "topology": state,
                "command": (
                    engine._migrator_command(vault_root, "--dry-run")
                    if state == "combined"
                    else None
                ),
            }

        def execute_approved_topology_migration(
            self,
            vault_root: Path,
            _preview,
            _approved_token: str,
        ):
            state = engine.topology_state(vault_root)
            return {
                "topology": state,
                "commands": [
                    engine._migrator_command(vault_root, "--auto"),
                    engine._migrator_command(vault_root, "--resume"),
                ],
            }

        def build_and_preview_delivered_release(self, vault_root: Path, release):
            return {"vault": str(vault_root), "release": release}

        def deliver_latest_release(self, vault_root: Path):
            return {"status": "delivered", "vault": str(vault_root)}

        def execute_approved_delivered_release(
            self,
            vault_root: Path,
            preview,
            approved_token: str,
        ):
            return {
                "vault": str(vault_root),
                "preview": preview,
                "approval_token": approved_token,
            }

    return (
        bridge._FoundationLifecycleService(
            Service(),
            engine,
            apply_update,
            source,
        ),
        engine,
        vault,
        migrator,
    )


def test_foundation_pin_is_closed_and_uses_only_the_release_channel() -> None:
    assert bridge.FOUNDATION.identity() == {
        "tag": "dist/release/v1.81.0-6bc490e",
        "tag_object": "54b1ceef8b1f7ad4f67e4d4d045a134ea443ab53",
        "commit": "6bc490e7caec22f60f097c6b54bb563382f542b8",
        "tree": "dad3e43774e772dfc42df698f8a9818956346d78",
        "version": "1.81.0",
        "channel": "stable",
    }


def test_foundation_fetch_survives_public_release_channel_advancing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The immutable first hop must still work after its follow-up is public."""

    vault = _vault(tmp_path)
    pin = bridge.FOUNDATION
    follow_up_commit = "b17ef028ce3fa8ec3ea3973688b9d392e4166a17"
    calls: list[tuple[str, ...]] = []
    private_release_ref = follow_up_commit

    def run_git(_directory: Path, *arguments: str) -> str:
        nonlocal private_release_ref
        calls.append(arguments)
        if arguments == (
            "update-ref",
            "refs/remotes/upstream/release",
            pin.commit,
        ):
            private_release_ref = pin.commit
            return ""
        if arguments == ("rev-parse", "--verify", f"refs/tags/{pin.tag}"):
            return pin.tag_object
        if arguments == ("rev-parse", "--verify", f"{pin.tag}^{{commit}}"):
            return pin.commit
        if arguments == ("rev-parse", "--verify", f"{pin.tag}^{{tree}}"):
            return pin.tree
        if arguments == (
            "rev-parse",
            "--verify",
            "refs/remotes/upstream/release^{commit}",
        ):
            return private_release_ref
        return ""

    monkeypatch.setattr(bridge, "_run_git", run_git)

    bridge._fetch_foundation_into_brain(vault, pin)

    fetch = next(arguments for arguments in calls if arguments[0] == "fetch")
    assert "+refs/heads/release:refs/remotes/upstream/release" not in fetch
    assert (
        "update-ref",
        "refs/remotes/upstream/release",
        pin.commit,
    ) in calls


def test_legacy_topology_pin_is_closed_to_exact_v1201_release() -> None:
    assert bridge.LEGACY_TOPOLOGY_FOUNDATION == bridge.LegacyTopologyPin(
        tag="v1.20.1",
        tag_object="3f7338dbe21ec98c015a3c8417d037cdd51b517d",
        commit="9e6f35d3282cb354008a4e7372b1cdb1d469ad3d",
        tree="b781bb94e417b2873d057a5a417d8c666a360bca",
    )


def test_legacy_topology_requires_exact_tag_commit_tree_and_current_ancestry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path)
    pin = bridge.LEGACY_TOPOLOGY_FOUNDATION
    values = {
        (
            "for-each-ref",
            "--format=%(objectname)",
            f"refs/tags/{pin.tag}",
        ): pin.tag_object,
        ("cat-file", "-t", pin.tag_object): "tag",
        ("rev-parse", "--verify", f"{pin.tag}^{{commit}}"): pin.commit,
        ("rev-parse", "--verify", f"{pin.tag}^{{tree}}"): pin.tree,
        ("rev-parse", "--verify", "HEAD^{commit}"): "f" * 40,
        ("merge-base", "--is-ancestor", pin.commit, "f" * 40): "",
    }
    monkeypatch.setattr(
        bridge,
        "_run_git",
        lambda _root, *arguments: values[arguments],
    )

    assert bridge._supported_legacy_topology(vault) is True

    values[("rev-parse", "--verify", f"{pin.tag}^{{tree}}")] = "0" * 40
    assert bridge._supported_legacy_topology(vault) is False


def test_legacy_topology_accepts_exact_pinned_commit_when_old_tag_was_pruned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path)
    pin = bridge.LEGACY_TOPOLOGY_FOUNDATION
    head = "f" * 40
    values = {
        (
            "for-each-ref",
            "--format=%(objectname)",
            f"refs/tags/{pin.tag}",
        ): "",
        ("cat-file", "-t", pin.commit): "commit",
        ("rev-parse", "--verify", f"{pin.commit}^{{commit}}"): pin.commit,
        ("rev-parse", "--verify", f"{pin.commit}^{{tree}}"): pin.tree,
        ("rev-parse", "--verify", "HEAD^{commit}"): head,
        ("merge-base", "--is-ancestor", pin.commit, head): "",
    }
    monkeypatch.setattr(
        bridge,
        "_run_git",
        lambda _root, *arguments: values[arguments],
    )

    assert bridge._supported_legacy_topology(vault) is True

    values[("rev-parse", "--verify", f"{pin.commit}^{{tree}}")] = "0" * 40
    assert bridge._supported_legacy_topology(vault) is False


def test_foundation_service_uses_verified_migrator_for_exact_legacy_topology_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, engine, vault, migrator = _foundation_topology_adapter(tmp_path)
    original_state = engine.topology_state
    original_command = engine._migrator_command
    monkeypatch.setattr(bridge, "_supported_legacy_topology", lambda _root: True)
    monkeypatch.setattr(
        bridge,
        "_trusted_executable",
        lambda name: Path("/trusted/node") if name == "node" else None,
    )

    preview = service.build_and_preview_topology_migration(vault)
    executed = service.execute_approved_topology_migration(
        vault,
        {"approved": True},
        "token",
    )

    command_prefix = [
        "/trusted/node",
        "--require",
        str(service._preload),
        str(migrator),
    ]
    assert preview == {
        "topology": "combined",
        "command": [*command_prefix, "--dry-run"],
    }
    assert executed == {
        "topology": "combined",
        "commands": [
            [*command_prefix, "--auto"],
            [*command_prefix, "--resume"],
        ],
    }
    assert not (vault / bridge._TOPOLOGY_MIGRATOR_RELATIVE).exists()
    assert engine.topology_state is original_state
    assert engine._migrator_command is original_command


def test_verified_legacy_migrator_gets_only_scoped_local_git_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, engine, vault, migrator = _foundation_topology_adapter(tmp_path)
    subprocess.run(["git", "init", "--quiet", str(vault)], check=True)
    migrator.write_text(
        """'use strict';
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const result = spawnSync(
  'git',
  [
    '-c',
    'protocol.file.allow=always',
    'clone',
    '--bare',
    path.join(process.cwd(), '.git'),
    path.join(process.cwd(), '.dex', 'transport-proof.git'),
  ],
  { encoding: 'utf8' },
);
if (result.status !== 0) {
  process.stderr.write(result.stderr || result.stdout);
  process.exit(result.status || 1);
}
const network = spawnSync(
  'git',
  ['ls-remote', 'https://example.invalid/dex.git'],
  { encoding: 'utf8' },
);
if (
  network.status === 0
  || !String(network.stderr).includes("transport 'https' not allowed")
) {
  process.stderr.write(network.stderr || network.stdout || 'HTTPS was not blocked');
  process.exit(network.status || 1);
}
""",
        encoding="utf-8",
    )
    service = bridge._FoundationLifecycleService(
        service._service,
        engine,
        service._apply_update,
        service._source,
    )

    class RunningService:
        @staticmethod
        def build_and_preview_topology_migration(vault_root: Path):
            assert engine.topology_state(vault_root) == "combined"
            return engine._run_topology_migrator(vault_root, "--dry-run")

    service._service = RunningService()
    monkeypatch.setattr(bridge, "_supported_legacy_topology", lambda _root: True)
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "https")
    parent_environment = bridge._bridge_environment()
    parent_attempt = subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "clone",
            "--bare",
            str(vault / ".git"),
            str(vault / ".dex" / "parent-transport-proof.git"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=parent_environment,
    )

    assert parent_attempt.returncode != 0
    assert "transport 'file' not allowed" in parent_attempt.stderr
    assert parent_environment["GIT_ALLOW_PROTOCOL"] == "https"
    assert parent_environment["GIT_CONFIG_GLOBAL"] == os.devnull

    result = service.build_and_preview_topology_migration(vault)

    assert result.returncode == 0, result.stderr
    assert (vault / ".dex" / "transport-proof.git").is_dir()
    assert os.environ["GIT_ALLOW_PROTOCOL"] == "https"


def test_foundation_service_keeps_unknown_or_ambiguous_topology_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _engine, vault, _migrator = _foundation_topology_adapter(tmp_path)
    monkeypatch.setattr(bridge, "_supported_legacy_topology", lambda _root: False)
    monkeypatch.setattr(
        bridge,
        "_trusted_executable",
        lambda _name: pytest.fail("unknown topology must not select Node"),
    )

    assert service.build_and_preview_topology_migration(vault) == {
        "topology": "invalid-combined",
        "command": None,
    }


def test_foundation_service_does_not_bypass_an_unsafe_vault_migrator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _engine, vault, migrator = _foundation_topology_adapter(tmp_path)
    candidate = vault / bridge._TOPOLOGY_MIGRATOR_RELATIVE
    candidate.parent.mkdir(parents=True)
    candidate.symlink_to(migrator)
    monkeypatch.setattr(bridge, "_supported_legacy_topology", lambda _root: True)

    assert service.build_and_preview_topology_migration(vault) == {
        "topology": "invalid-combined",
        "command": None,
    }


def test_foundation_service_refuses_migrator_changed_after_verification(
    tmp_path: Path,
) -> None:
    service, _engine, vault, migrator = _foundation_topology_adapter(tmp_path)
    migrator.write_text("'use strict';\n// changed\n", encoding="utf-8")

    with pytest.raises(bridge.BridgeError, match="changed after verification"):
        service.build_and_preview_topology_migration(vault)


def test_legacy_preload_supplies_absent_read_only_inputs_without_vault_writes(
    tmp_path: Path,
) -> None:
    service, _engine, vault, _migrator = _foundation_topology_adapter(tmp_path)
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the compatibility preload test")
    (vault / "package.json").write_text(
        '{"name":"dex-pkm","version":"1.49.0"}\n',
        encoding="utf-8",
    )
    script = """
const fs = require('node:fs');
const path = require('node:path');
const root = process.cwd();
const policy = fs.readFileSync(path.join(root, 'core/migrations/tracked-ignored-policy.yaml'), 'utf8');
const transition = fs.readFileSync(path.join(root, 'System/.local-only-preservation-transition.json'), 'utf8');
process.stdout.write(JSON.stringify({policy, transition}));
"""

    result = subprocess.run(
        [node, "--require", str(service._preload), "--eval", script],
        cwd=vault,
        check=True,
        capture_output=True,
        text=True,
        env=bridge._bridge_environment(),
    )
    supplied = json.loads(result.stdout)

    assert supplied["policy"].encode() == bridge._LEGACY_TRACKED_IGNORE_POLICY
    assert json.loads(supplied["transition"]) == {
        "phase": "bootstrap-v1",
        "release_version": "1.49.0",
        "schema_version": 1,
    }
    assert not (vault / bridge._TRACKED_IGNORE_POLICY_RELATIVE).exists()
    assert not (vault / bridge._PRESERVATION_TRANSITION_RELATIVE).exists()


def test_legacy_preload_refuses_an_invalid_package_version(
    tmp_path: Path,
) -> None:
    service, _engine, vault, _migrator = _foundation_topology_adapter(tmp_path)
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the compatibility preload test")
    (vault / "package.json").write_text(
        '{"name":"dex-pkm","version":"../../changed"}\n',
        encoding="utf-8",
    )
    script = """
const fs = require('node:fs');
const path = require('node:path');
fs.readFileSync(
  path.join(process.cwd(), 'System/.local-only-preservation-transition.json'),
  'utf8',
);
"""

    result = subprocess.run(
        [node, "--require", str(service._preload), "--eval", script],
        cwd=vault,
        check=False,
        capture_output=True,
        text=True,
        env=bridge._bridge_environment(),
    )

    assert result.returncode != 0
    assert "Dex update bridge refused invalid legacy package version" in result.stderr
    assert not (vault / bridge._PRESERVATION_TRANSITION_RELATIVE).exists()


def test_legacy_preload_refuses_an_existing_or_symlinked_compatibility_input(
    tmp_path: Path,
) -> None:
    service, _engine, vault, _migrator = _foundation_topology_adapter(tmp_path)
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the compatibility preload test")
    policy = vault / bridge._TRACKED_IGNORE_POLICY_RELATIVE
    policy.parent.mkdir(parents=True)
    policy.symlink_to(vault / "attacker-policy.yaml")
    script = (
        "require('node:fs').readFileSync("
        "require('node:path').join(process.cwd(), "
        "'core/migrations/tracked-ignored-policy.yaml'), 'utf8')"
    )

    result = subprocess.run(
        [node, "--require", str(service._preload), "--eval", script],
        cwd=vault,
        check=False,
        capture_output=True,
        text=True,
        env=bridge._bridge_environment(),
    )

    assert result.returncode != 0
    assert "refused existing legacy compatibility input" in result.stderr


def test_legacy_preload_hides_only_the_exact_shipped_v1201_symlink(
    tmp_path: Path,
) -> None:
    service, _engine, vault, _migrator = _foundation_topology_adapter(tmp_path)
    target = vault / "pi-extensions" / "dex"
    target.mkdir(parents=True)
    shipped_link = vault / bridge._LEGACY_SHIPPED_SYMLINK_RELATIVE
    shipped_link.parent.mkdir(parents=True)
    shipped_link.symlink_to(bridge._LEGACY_SHIPPED_SYMLINK_TARGET)
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the compatibility preload test")
    script = """
const fs = require('node:fs');
const names = fs.readdirSync('.pi/agent/extensions', {withFileTypes: true})
  .map((entry) => entry.name);
process.stdout.write(JSON.stringify(names));
"""

    result = subprocess.run(
        [node, "--require", str(service._preload), "--eval", script],
        cwd=vault,
        check=True,
        capture_output=True,
        text=True,
        env=bridge._bridge_environment(),
    )

    assert json.loads(result.stdout) == []
    assert shipped_link.is_symlink()
    assert shipped_link.readlink() == Path(bridge._LEGACY_SHIPPED_SYMLINK_TARGET)


def test_legacy_preload_refuses_a_changed_release_symlink(
    tmp_path: Path,
) -> None:
    service, _engine, vault, _migrator = _foundation_topology_adapter(tmp_path)
    target = vault / "different-target"
    target.mkdir()
    shipped_link = vault / bridge._LEGACY_SHIPPED_SYMLINK_RELATIVE
    shipped_link.parent.mkdir(parents=True)
    shipped_link.symlink_to(target)
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the compatibility preload test")

    result = subprocess.run(
        [node, "--require", str(service._preload), "--eval", "'ok'"],
        cwd=vault,
        check=False,
        capture_output=True,
        text=True,
        env=bridge._bridge_environment(),
    )

    assert result.returncode != 0
    assert "refused changed legacy release symlink" in result.stderr


def test_foundation_service_refuses_compatibility_preload_changed_after_verification(
    tmp_path: Path,
) -> None:
    service, _engine, vault, _migrator = _foundation_topology_adapter(tmp_path)
    service._preload.chmod(0o600)
    service._preload.write_text("'use strict';\n// changed\n", encoding="utf-8")

    with pytest.raises(bridge.BridgeError, match="preload changed after verification"):
        service.build_and_preview_topology_migration(vault)


def test_foundation_service_exposes_release_delivery(tmp_path: Path) -> None:
    service, _engine, vault, _migrator = _foundation_topology_adapter(tmp_path)

    assert service.deliver_latest_release(vault) == {
        "status": "delivered",
        "vault": str(vault),
    }


def test_foundation_service_reports_missing_engine_path_as_bridge_error(
    tmp_path: Path,
) -> None:
    source = tmp_path / "foundation"
    migrator = source / bridge._TOPOLOGY_MIGRATOR_RELATIVE
    migrator.parent.mkdir(parents=True)
    migrator.write_text("'use strict';\n", encoding="utf-8")
    engine = ModuleType("missing_path_engine")
    apply_update = ModuleType("apply_update")

    with pytest.raises(bridge.BridgeError, match="migrator path changed"):
        bridge._FoundationLifecycleService(
            ModuleType("service"),
            engine,
            apply_update,
            source,
        )


def test_legacy_delivery_reader_accepts_only_the_pinned_pre_manifest_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _engine, vault, _migrator = _foundation_topology_adapter(tmp_path)
    apply_update = service._apply_update

    class ReleaseVerificationError(RuntimeError):
        pass

    class ContractViolation(RuntimeError):
        pass

    TreeEntry = namedtuple("TreeEntry", ("path", "mode", "object_id"))
    classified_oid = "1" * 40
    retired_oid = "2" * 40
    omission_a_oid = "3" * 40
    omission_b_oid = "4" * 40
    records = (
        f"100644 blob {classified_oid}\tCLAUDE.md\0"
        f"100644 blob {retired_oid}\tretired-release-path.txt\0"
        f"100644 blob {omission_a_oid}\tclosed-omission-a\0"
        f"100644 blob {omission_b_oid}\tclosed-omission-b\0"
        f"120000 blob {bridge._LEGACY_SHIPPED_SYMLINK_BLOB}\t"
        f"{bridge._LEGACY_SHIPPED_SYMLINK_RELATIVE.as_posix()}\0"
    ).encode()

    def brain_output(_root: Path, _brain: Path, *arguments: str) -> bytes:
        if arguments[:2] == ("ls-tree", "-r"):
            return records
        if arguments[:2] == ("cat-file", "blob"):
            return bridge._LEGACY_SHIPPED_SYMLINK_TARGET.encode()
        raise AssertionError(arguments)

    def resolve(path: str):
        if path == "retired-release-path.txt":
            raise ContractViolation(path)
        return object()

    apply_update.ReleaseVerificationError = ReleaseVerificationError
    apply_update.portable_contract.ContractViolation = ContractViolation
    apply_update.portable_contract.resolve = resolve
    apply_update.TreeEntry = TreeEntry
    apply_update._brain_output = brain_output
    original_omission_identity = bridge._manifestless_omission_identity
    omission_identities = {
        "closed-omission-a": "af78f3d480b78b5bb558d873b98638c91d532de98f84f8f50e73448a1404b37d",
        "closed-omission-b": "50a3e65dc2d65e6f6b28b30b630e06656d95ddd82f4a68a7152017119b110f90",
    }

    def omission_identity(relative: str, raw_mode: str, object_id: str) -> str:
        if relative in omission_identities:
            assert raw_mode == "100644"
            assert object_id in {omission_a_oid, omission_b_oid}
            return omission_identities[relative]
        return original_omission_identity(relative, raw_mode, object_id)

    monkeypatch.setattr(bridge, "_manifestless_omission_identity", omission_identity)

    def original_tree_entries(*_arguments):
        pytest.fail("exact legacy commit should use the compatibility reader")

    def original_verify_manifest(*_arguments):
        raise ReleaseVerificationError("legacy release has no manifest")

    apply_update._tree_entries = original_tree_entries
    apply_update._verify_manifest = original_verify_manifest
    brain = vault / ".dex" / "brain.git"

    class DeliveryService:
        @staticmethod
        def build_and_preview_delivered_release(_vault_root: Path, _release):
            entries = apply_update._tree_entries(
                vault,
                brain,
                bridge.LEGACY_TOPOLOGY_FOUNDATION.commit,
            )
            apply_update._verify_manifest(vault, brain, entries)
            return {"paths": [entry.path for entry in entries]}

        @staticmethod
        def execute_approved_delivered_release(
            _vault_root: Path,
            _preview,
            _approved_token: str,
        ):
            return {"executed": True}

    service._service = DeliveryService()
    pin = bridge.LEGACY_TOPOLOGY_FOUNDATION
    values = {
        ("rev-parse", "--verify", f"{pin.commit}^{{tree}}"): pin.tree,
        ("rev-parse", "--verify", "refs/dex/installed^{commit}"): pin.commit,
    }
    monkeypatch.setattr(
        bridge,
        "_run_git",
        lambda _root, *arguments: values[arguments],
    )

    assert service.build_and_preview_delivered_release(vault, {}) == {
        "paths": ["CLAUDE.md"]
    }
    assert apply_update._tree_entries is original_tree_entries
    assert apply_update._verify_manifest is original_verify_manifest


def test_legacy_delivery_reader_rejects_any_other_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _engine, vault, _migrator = _foundation_topology_adapter(tmp_path)
    apply_update = service._apply_update

    class ReleaseVerificationError(RuntimeError):
        pass

    class ContractViolation(RuntimeError):
        pass

    TreeEntry = namedtuple("TreeEntry", ("path", "mode", "object_id"))
    apply_update.ReleaseVerificationError = ReleaseVerificationError
    apply_update.portable_contract.ContractViolation = ContractViolation
    apply_update.portable_contract.resolve = lambda _path: object()
    apply_update.TreeEntry = TreeEntry
    apply_update._brain_output = lambda _root, _brain, *arguments: (
        b"120000 blob 0000000000000000000000000000000000000000\t"
        b"unexpected-link\0"
        if arguments[:2] == ("ls-tree", "-r")
        else b"unexpected"
    )
    apply_update._tree_entries = lambda *_arguments: ()
    apply_update._verify_manifest = lambda *_arguments: None

    class DeliveryService:
        @staticmethod
        def build_and_preview_delivered_release(_vault_root: Path, _release):
            return apply_update._tree_entries(
                vault,
                vault / ".dex" / "brain.git",
                bridge.LEGACY_TOPOLOGY_FOUNDATION.commit,
            )

    service._service = DeliveryService()
    pin = bridge.LEGACY_TOPOLOGY_FOUNDATION
    monkeypatch.setattr(
        bridge,
        "_run_git",
        lambda _root, *arguments: (
            pin.tree
            if arguments
            == ("rev-parse", "--verify", f"{pin.commit}^{{tree}}")
            else pytest.fail(f"unexpected Git call: {arguments}")
        ),
    )

    with pytest.raises(ReleaseVerificationError, match="unknown symlink"):
        service.build_and_preview_delivered_release(vault, {})


def test_bridge_success_copy_names_the_canonical_dex_update_command() -> None:
    source = Path(bridge.__file__).read_text(encoding="utf-8")
    assert "future updates use /dex-update." in source
    assert "Future updates use /dex update." not in source


def test_release_pin_rejects_a_mutable_or_incomplete_identity() -> None:
    with pytest.raises(bridge.BridgeError, match="immutable distribution"):
        bridge.ReleasePin("release", "a" * 40, "b" * 40, "c" * 40, "1.80.5")
    with pytest.raises(bridge.BridgeError, match="malformed"):
        bridge.ReleasePin("dist/release/v1.80.5-aaaaaaa", "not-a-hash", "b" * 40, "c" * 40, "1.80.5")


def test_bridge_requires_three_new_approvals_and_routes_writes_through_foundation_service(tmp_path: Path) -> None:
    service = _Service()
    answers = iter(("APPLY", "APPLY", "APPLY"))
    fetched: list[Path] = []
    vault = _vault(tmp_path)

    result = bridge.run_bridge(
        vault,
        service,
        fetch_foundation=lambda root, _pin: fetched.append(root),
        input_fn=lambda _prompt: next(answers),
        output_fn=lambda _line: None,
    )

    assert result["foundation"] == bridge.FOUNDATION.identity()
    assert service.calls == [
        "topology-preview",
        "topology-execute:topology-token",
        "release-preview",
        "release-execute:release-token",
        "mcp-preview",
        "mcp-execute:mcp-token",
    ]
    assert fetched == [vault]


def test_bridge_stops_before_any_release_fetch_when_topology_preview_is_not_approved(tmp_path: Path) -> None:
    service = _Service()

    with pytest.raises(bridge.BridgeError, match="no change"):
        bridge.run_bridge(
            _vault(tmp_path),
            service,
            fetch_foundation=lambda _vault, _pin: pytest.fail("release fetch must not happen"),
            input_fn=lambda _prompt: "no",
            output_fn=lambda _line: None,
        )

    assert service.calls == ["topology-preview"]


def test_bridge_rejects_a_symlinked_vault_before_calling_the_service_or_fetching(tmp_path: Path) -> None:
    service = _Service()
    target = _vault(tmp_path)
    linked = tmp_path / "linked-vault"
    linked.symlink_to(target, target_is_directory=True)

    with pytest.raises(bridge.BridgeError, match="contains a symlink"):
        bridge.run_bridge(
            linked,
            service,
            fetch_foundation=lambda _vault, _pin: pytest.fail("release fetch must not happen"),
            input_fn=lambda _prompt: pytest.fail("approval must not be requested"),
            output_fn=lambda _line: pytest.fail("preview must not be rendered"),
        )

    assert service.calls == []


@pytest.mark.parametrize("private_parent", (".venv", ".dex"))
def test_bridge_rejects_a_symlinked_private_parent_before_service_or_fetch(
    tmp_path: Path, private_parent: str
) -> None:
    service = _Service()
    vault = _vault(tmp_path)
    target = tmp_path / f"{private_parent.removeprefix('.')}target"
    private_path = vault / private_parent
    if private_path.exists():
        private_path.rename(target)
    else:
        target.mkdir()
    (vault / private_parent).symlink_to(target, target_is_directory=True)

    with pytest.raises(bridge.BridgeError, match=rf"{private_parent} must not be a symlink"):
        bridge.run_bridge(
            vault,
            service,
            fetch_foundation=lambda _vault, _pin: pytest.fail("release fetch must not happen"),
            input_fn=lambda _prompt: pytest.fail("approval must not be requested"),
            output_fn=lambda _line: pytest.fail("preview must not be rendered"),
        )

    assert service.calls == []


def test_normal_virtualenv_python_symlink_remains_accepted(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    venv = vault / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /synthetic\n", encoding="utf-8")
    (venv / "bin" / "python").symlink_to(Path(sys.executable))

    assert bridge._validate_vault(vault) == vault
    assert bridge._installed_python(vault) == venv / "bin" / "python"


def test_bridge_stops_before_delivered_release_execution_when_second_preview_is_not_approved(tmp_path: Path) -> None:
    service = _Service()
    answers = iter(("APPLY", "no"))

    with pytest.raises(bridge.BridgeError, match="no change"):
        bridge.run_bridge(
            _vault(tmp_path),
            service,
            fetch_foundation=lambda _vault, _pin: None,
            input_fn=lambda _prompt: next(answers),
            output_fn=lambda _line: None,
        )

    assert service.calls == ["topology-preview", "topology-execute:topology-token", "release-preview"]


def test_bridge_stops_before_mcp_registration_when_third_preview_is_not_approved(
    tmp_path: Path,
) -> None:
    service = _Service()
    answers = iter(("APPLY", "APPLY", "no"))

    with pytest.raises(bridge.BridgeError, match="no change"):
        bridge.run_bridge(
            _vault(tmp_path),
            service,
            fetch_foundation=lambda _vault, _pin: None,
            input_fn=lambda _prompt: next(answers),
            output_fn=lambda _line: None,
        )

    assert service.calls == [
        "topology-preview",
        "topology-execute:topology-token",
        "release-preview",
        "release-execute:release-token",
        "mcp-preview",
    ]


def test_bridge_does_not_request_mcp_approval_when_registration_is_current(
    tmp_path: Path,
) -> None:
    class CurrentMcpService(_Service):
        def build_and_preview_mcp_registration(self, vault_root: Path):
            self.calls.append("mcp-preview")
            return {
                "needed": False,
                "preview": None,
                "approval_token": None,
            }

    service = CurrentMcpService()
    answers = iter(("APPLY", "APPLY"))

    result = bridge.run_bridge(
        _vault(tmp_path),
        service,
        fetch_foundation=lambda _vault, _pin: None,
        input_fn=lambda _prompt: next(answers),
        output_fn=lambda _line: None,
    )

    assert result["mcp_registration_receipt"] == {
        "skipped": "mcp-already-registered"
    }
    assert service.calls == [
        "topology-preview",
        "topology-execute:topology-token",
        "release-preview",
        "release-execute:release-token",
        "mcp-preview",
    ]


def test_bridge_does_not_repeat_a_completed_topology_conversion(tmp_path: Path) -> None:
    service = _SplitService()
    vault = _vault(tmp_path)
    answers = iter(("APPLY", "APPLY"))

    result = bridge.run_bridge(
        vault,
        service,
        fetch_foundation=lambda _vault, _pin: None,
        input_fn=lambda _prompt: next(answers),
        output_fn=lambda _line: None,
    )

    assert result["topology_receipt"] == {"skipped": "already-brain-vault-split"}
    assert service.calls == [
        "topology-preview",
        "release-preview",
        "release-execute:release-token",
        "mcp-preview",
        "mcp-execute:mcp-token",
    ]


def test_bridge_resumes_offline_without_fetching_or_revalidating_an_advanced_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CurrentMcpService(_SplitService):
        def build_and_preview_mcp_registration(self, vault_root: Path):
            self.calls.append("mcp-preview")
            return {
                "needed": False,
                "preview": None,
                "approval_token": None,
            }

    service = CurrentMcpService()
    monkeypatch.setattr(bridge, "_foundation_is_installed", lambda _vault, _pin: True)

    result = bridge.run_bridge(
        _vault(tmp_path),
        service,
        fetch_foundation=lambda _vault, _pin: pytest.fail("completed bridge must not fetch"),
        input_fn=lambda _prompt: pytest.fail("already-installed bridge must not request approval"),
        output_fn=lambda _line: pytest.fail("already-installed bridge must not render a preview"),
    )

    assert result["topology_receipt"] == {"skipped": "foundation-already-installed"}
    assert result["delivery_receipt"] == {"skipped": "foundation-already-installed"}
    assert result["mcp_registration_receipt"] == {
        "skipped": "mcp-already-registered"
    }
    assert service.calls == ["mcp-preview"]


def test_bridge_retry_finishes_missing_mcp_registration_without_repeating_update_hops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _SplitService()
    monkeypatch.setattr(bridge, "_foundation_is_installed", lambda _vault, _pin: True)

    result = bridge.run_bridge(
        _vault(tmp_path),
        service,
        fetch_foundation=lambda _vault, _pin: pytest.fail("completed bridge must not fetch"),
        input_fn=lambda _prompt: "APPLY",
        output_fn=lambda _line: None,
    )

    assert result["topology_receipt"] == {"skipped": "foundation-already-installed"}
    assert result["delivery_receipt"] == {"skipped": "foundation-already-installed"}
    assert result["mcp_registration_receipt"] == {"receipt": "mcp-registration"}
    assert service.calls == ["mcp-preview", "mcp-execute:mcp-token"]


def test_completed_foundation_requires_all_durable_split_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _completed_vault(tmp_path)
    monkeypatch.setattr(bridge, "_run_git", lambda *_arguments: bridge.FOUNDATION.commit)

    assert bridge._foundation_is_installed(vault, bridge.FOUNDATION) is True

    topology = vault / "System" / ".dex" / "topology.json"
    topology.write_text('{"topology":"brain-vault-split"}\n', encoding="utf-8")
    with pytest.raises(bridge.BridgeError, match="markers do not agree"):
        bridge._foundation_is_installed(vault, bridge.FOUNDATION)


def test_main_resumes_completed_foundation_from_installed_service_without_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class CurrentMcpService(_SplitService):
        def build_and_preview_mcp_registration(self, vault_root: Path):
            self.calls.append("mcp-preview")
            return {
                "needed": False,
                "preview": None,
                "approval_token": None,
            }

    vault = _completed_vault(tmp_path)
    service = CurrentMcpService()
    reexec_calls: list[tuple[Path, list[str]]] = []
    monkeypatch.setattr(bridge, "_run_git", lambda *_arguments: bridge.FOUNDATION.commit)
    monkeypatch.setattr(
        bridge,
        "_reexec_in_installed_runtime",
        lambda root, arguments: reexec_calls.append((root, list(arguments))),
    )
    monkeypatch.setattr(
        bridge,
        "acquire_foundation_source",
        lambda: pytest.fail("completed bridge must not download source"),
    )
    monkeypatch.setattr(bridge, "_load_lifecycle_service", lambda source: service)

    assert bridge.main(["--vault", str(vault)]) == 0
    output = capsys.readouterr().out
    assert '"foundation-already-installed"' in output
    assert '"mcp-already-registered"' in output
    assert service.calls == ["mcp-preview"]
    assert reexec_calls == [(vault, ["--vault", str(vault)])]


def test_runtime_reexec_cleans_a_hostile_same_interpreter_and_preset_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_execve(interpreter: str, argv: list[str], environment: dict[str, str]) -> None:
        captured["interpreter"] = interpreter
        captured["argv"] = argv
        captured["environment"] = environment

    monkeypatch.setattr(bridge, "_installed_python", lambda _vault: Path(sys.executable))
    monkeypatch.setattr(bridge.os, "execve", fake_execve)
    monkeypatch.setenv(bridge._CLEAN_RUNTIME_MARKER, "1")
    monkeypatch.setenv("PATH", "/private/attacker-bin")
    monkeypatch.setenv("GIT_DIR", "/private/attacker-repository")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/private/attacker-config")
    monkeypatch.setenv("GIT_SSH_COMMAND", "attacker-command")
    monkeypatch.setenv("PYTHONPATH", "/private/attacker-python")
    monkeypatch.setenv("NODE_OPTIONS", "--require=/private/attacker-node")

    bridge._reexec_in_installed_runtime(_vault(tmp_path), ["--vault", "/safe/vault"])

    assert captured["interpreter"] == str(Path(sys.executable))
    assert captured["argv"] == [
        str(Path(sys.executable)),
        str(Path(bridge.__file__).resolve()),
        "--vault",
        "/safe/vault",
    ]
    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert environment[bridge._CLEAN_RUNTIME_MARKER] == "1"
    assert "/private/attacker-bin" not in environment["PATH"]
    assert environment["GIT_CONFIG_GLOBAL"] == os.devnull
    for name in ("GIT_DIR", "GIT_SSH_COMMAND", "PYTHONPATH", "NODE_OPTIONS"):
        assert name not in environment


def test_runtime_reexec_rejects_a_forged_exact_clean_environment_from_host_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    vault = _vault(tmp_path)
    selected_interpreter = vault / ".venv" / "bin" / "python"
    clean_environment = bridge._bridge_environment()
    clean_environment[bridge._CLEAN_RUNTIME_MARKER] = "1"

    def fake_execve(interpreter: str, argv: list[str], environment: dict[str, str]) -> None:
        captured["interpreter"] = interpreter
        captured["argv"] = argv
        captured["environment"] = environment

    monkeypatch.setattr(bridge, "_installed_python", lambda _vault: selected_interpreter)
    monkeypatch.setattr(bridge.os, "execve", fake_execve)
    monkeypatch.setattr(bridge.os, "environ", clean_environment)

    bridge._reexec_in_installed_runtime(vault, ["--vault", "/safe/vault"])

    assert captured["interpreter"] == str(selected_interpreter)
    assert captured["argv"] == [
        str(selected_interpreter),
        str(Path(bridge.__file__).resolve()),
        "--vault",
        "/safe/vault",
    ]
    assert captured["environment"] == clean_environment


def test_runtime_marker_accepts_only_the_selected_virtualenv_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    selected_interpreter = vault / ".venv" / "bin" / "python"
    selected_prefix = selected_interpreter.parent.parent
    clean_environment = bridge._bridge_environment()
    clean_environment[bridge._CLEAN_RUNTIME_MARKER] = "1"

    monkeypatch.setattr(bridge, "_installed_python", lambda _vault: selected_interpreter)
    monkeypatch.setattr(bridge.os, "environ", clean_environment)
    monkeypatch.setattr(bridge.sys, "executable", str(selected_interpreter))
    monkeypatch.setattr(bridge.sys, "prefix", str(selected_prefix))
    monkeypatch.setattr(bridge.sys, "exec_prefix", str(selected_prefix))
    monkeypatch.setattr(
        bridge.os,
        "execve",
        lambda *_arguments: pytest.fail("selected clean virtualenv must not re-exec"),
    )

    bridge._reexec_in_installed_runtime(vault, ["--vault", "/safe/vault"])


def test_runtime_refuses_to_fall_back_to_host_python_without_vault_virtualenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bridge, "_installed_python", lambda _vault: None)

    with pytest.raises(bridge.BridgeError, match="installed virtualenv"):
        bridge._reexec_in_installed_runtime(_vault(tmp_path), ["--vault", "/safe/vault"])


def test_trusted_executable_does_not_consult_caller_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attacker_git = tmp_path / "git"
    attacker_git.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    attacker_git.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(bridge, "_TRUSTED_EXECUTABLE_DIRECTORIES", (tmp_path / "system-bin",))

    assert bridge._trusted_executable("git") is None


def test_git_subprocess_environment_excludes_caller_git_and_credential_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(arguments, **kwargs):
        captured["arguments"] = arguments
        captured["environment"] = kwargs["env"]
        return subprocess.CompletedProcess(arguments, 0, stdout=b"ok\n", stderr=b"")

    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/private/attacker-config")
    monkeypatch.setenv("GIT_DIR", "/private/attacker-repository")
    monkeypatch.setenv("GIT_SSH_COMMAND", "attacker-command")
    monkeypatch.setenv("HOME", "/private/credential-home")
    monkeypatch.setenv("PATH", "/private/attacker-bin")
    monkeypatch.setenv("PYTHONPATH", "/private/attacker-python")
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    assert bridge._run_git(tmp_path, "rev-parse", "HEAD") == "ok"

    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert environment["GIT_CONFIG_GLOBAL"] == os.devnull
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert "/private/attacker-bin" not in environment["PATH"]
    assert "HOME" not in environment
    assert "PYTHONPATH" not in environment
    assert "GIT_DIR" not in environment
    assert "GIT_SSH_COMMAND" not in environment
    assert "credential.helper=" in captured["arguments"]
    assert "--no-replace-objects" in captured["arguments"]
