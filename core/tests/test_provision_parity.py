"""Parity guard between the canonical Node provisioner and onboarding seeds."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from core import capabilities
from core.lifecycle import service
from core.lifecycle.catalog import canonical_catalog_bytes
from core.tests.lifecycle_test_helpers import (
    write_bridge_release,
    write_file,
    write_manifest,
)
from core.tests.test_adoption_transaction import _document

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "packages/dex-contracts/dist/portable-vault.contract.json"


def _prepare_provision_vault(
    tmp_path: Path,
    *,
    profile_text: str | None = None,
    companies_default: bool | None = None,
) -> Path:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "core").mkdir()
    (vault / ".scripts").mkdir()
    shutil.copy(REPO_ROOT / "System/.mcp.json.example", vault / "System/.mcp.json.example")
    shutil.copy(
        REPO_ROOT / "System/user-profile-template.yaml",
        vault / "System/user-profile-template.yaml",
    )
    if companies_default is not None:
        template_path = vault / "System/user-profile-template.yaml"
        template = yaml.safe_load(template_path.read_text(encoding="utf-8"))
        template["capabilities"]["companies"]["enabled"] = companies_default
        template_path.write_text(
            yaml.safe_dump(template, sort_keys=False),
            encoding="utf-8",
        )
    shutil.copy(REPO_ROOT / "core/paths.py", vault / "core/paths.py")
    shutil.copy(REPO_ROOT / "package.json", vault / "package.json")
    shutil.copy(REPO_ROOT / "CLAUDE.md", vault / "CLAUDE.md")
    if profile_text is not None:
        (vault / "System/user-profile.yaml").write_text(
            profile_text,
            encoding="utf-8",
        )
    return vault


def _invoke_provision(
    vault: Path,
    *options: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "node",
            str(REPO_ROOT / "core/provision.cjs"),
            "--path",
            str(vault),
            *options,
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_provision(vault: Path, *options: str) -> dict:
    completed = _invoke_provision(vault, *options)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _snapshot_tree(root: Path) -> dict[str, tuple[str, bytes | str]]:
    snapshot: dict[str, tuple[str, bytes | str]] = {}
    for candidate in sorted(root.rglob("*")):
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            snapshot[relative] = ("symlink", os.readlink(candidate))
        elif candidate.is_file():
            snapshot[relative] = ("file", candidate.read_bytes())
        elif candidate.is_dir():
            snapshot[relative] = ("directory", "")
    return snapshot


def _install_adoptable_lifecycle_fixture(vault: Path) -> None:
    payloads = {
        "alpha": {
            ".claude/skills/alpha/SKILL.md": b"# alpha\n",
        }
    }
    manifest = write_manifest(
        vault,
        [path for files in payloads.values() for path in files],
    )
    document = _document(manifest, payloads)
    write_file(
        vault,
        "System/.release-catalog.json",
        canonical_catalog_bytes(document),
    )
    for relative, content in payloads["alpha"].items():
        write_file(vault, relative, content)
    write_bridge_release(vault)


def test_installer_routes_bootstrap_config_to_sanctioned_provision_contract() -> None:
    installer = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")

    assert "--install-config-only" in installer
    assert "System/.mcp.json.example > .mcp.json" not in installer
    assert "mcp_path.write_text" not in installer


def test_install_config_preflight_needs_no_global_pyyaml(tmp_path: Path) -> None:
    """The pre-venv installer seam must run on the standard library alone."""
    vault = tmp_path / "vault"
    vault.mkdir()
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            str(REPO_ROOT / "core/capabilities.py"),
            "--preflight-mutation-targets",
            "--vault",
            str(vault),
            "--contract",
            str(CONTRACT_PATH),
            "--mutation-targets-json",
            '[{"path":".mcp.json","kind":"file"}]',
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "mutation_targets": [{"kind": "file", "path": ".mcp.json"}],
        "preflight": "passed",
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_adopt_preserves_existing_content_while_routing_lifecycle(tmp_path: Path) -> None:
    vault = _prepare_provision_vault(
        tmp_path,
        profile_text="name: Existing User\ncustom: keep\n",
    )
    (vault / "03-Tasks").mkdir()
    tasks = vault / "03-Tasks/Tasks.md"
    tasks.write_text("# My tasks\n", encoding="utf-8")

    summary = _run_provision(vault, "--adopt")

    assert summary["lifecycle_executor"]["api_version"] == service.api_version
    assert summary["lifecycle_executor"]["skipped"] == "no-release-catalog"
    assert "name: Existing User" in (vault / "System/user-profile.yaml").read_text()
    assert "custom: keep" in (vault / "System/user-profile.yaml").read_text()
    assert tasks.read_text(encoding="utf-8") == "# My tasks\n"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_fresh_provision_enables_companies_and_creates_its_room(tmp_path: Path) -> None:
    vault = _prepare_provision_vault(tmp_path)

    _run_provision(vault)

    profile_path = vault / "System/user-profile.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert profile["capabilities"]["companies"]["enabled"] is True
    assert capabilities.enabled(
        "companies",
        profile_path=profile_path,
        contract_path=CONTRACT_PATH,
    ) is True
    assert (vault / "05-Areas/Companies").is_dir()


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_onboarding_dry_run_then_saves_confirmed_harness_receipt_transactionally(
    tmp_path: Path,
) -> None:
    vault = _prepare_provision_vault(tmp_path)
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "name": "Portable User",
                "pillars": [{"name": "Build"}],
                "harnesses": ["codex", "cowork"],
                "harness_detected": ["codex"],
                "harness_source": "user-confirmed",
            }
        ),
        encoding="utf-8",
    )
    receipt_path = vault / "System/.dex/harness-profile.json"

    preview = _invoke_provision(
        vault,
        "--onboard",
        "--profile",
        str(profile),
        "--dry-run",
    )

    assert preview.returncode == 0, preview.stderr
    preview_summary = json.loads(preview.stdout)
    assert "System/.dex/harness-profile.json" in set(
        preview_summary["mutation_receipt"]["declared_paths"]
    )
    assert not receipt_path.exists()

    applied = _invoke_provision(
        vault,
        "--onboard",
        "--profile",
        str(profile),
    )

    assert applied.returncode == 0, applied.stderr or applied.stdout
    applied_summary = json.loads(applied.stdout)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == 1
    assert receipt["source"] == "user-confirmed"
    assert receipt["selected"] == ["codex", "cowork"]
    assert receipt["detected"] == ["codex"]
    assert {profile["id"] for profile in receipt["profiles"]} == {
        "codex",
        "cowork",
    }
    assert "System/.dex/harness-profile.json" in set(
        applied_summary["mutation_receipt"]["declared_paths"]
    )
    saved_profile = yaml.safe_load(
        (vault / "System/user-profile.yaml").read_text(encoding="utf-8")
    )
    assert "harnesses" not in saved_profile
    assert "harness_detected" not in saved_profile
    assert "harness_source" not in saved_profile


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_onboarding_rejects_unknown_harness_before_any_vault_mutation(
    tmp_path: Path,
) -> None:
    vault = _prepare_provision_vault(tmp_path)
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "name": "Portable User",
                "harnesses": ["imaginary-harness"],
                "harness_source": "user-confirmed",
            }
        ),
        encoding="utf-8",
    )
    before = _snapshot_tree(vault)

    completed = _invoke_provision(
        vault,
        "--onboard",
        "--profile",
        str(profile),
    )

    assert completed.returncode != 0
    errors = " ".join(json.loads(completed.stdout)["errors"]).lower()
    assert "unknown harness" in errors
    assert _snapshot_tree(vault) == before


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_onboarding_refuses_room_source_drift_before_any_vault_mutation(
    tmp_path: Path,
) -> None:
    vault = _prepare_provision_vault(tmp_path)
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["capabilities"]["career"]["skill_sources"][0]["sha256"] = "0" * 64
    drifted = tmp_path / "drifted-contract.json"
    drifted.write_text(json.dumps(contract), encoding="utf-8")
    before = _snapshot_tree(vault)

    completed = _invoke_provision(
        vault,
        "--onboard",
        env={
            **os.environ,
            "DEX_CAPABILITY_CONTRACT_PATH": str(drifted),
        },
    )

    assert completed.returncode != 0
    errors = " ".join(json.loads(completed.stdout)["errors"]).lower()
    assert "identity" in errors or "sha256" in errors
    assert _snapshot_tree(vault) == before


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_onboarding_fails_closed_when_lifecycle_authority_cannot_start(
    tmp_path: Path,
) -> None:
    vault = _prepare_provision_vault(tmp_path)
    before = _snapshot_tree(vault)

    completed = _invoke_provision(
        vault,
        "--onboard",
        env={**os.environ, "DEX_LIFECYCLE_PYTHON": "/bin/false"},
    )

    assert completed.returncode != 0
    summary = json.loads(completed.stdout)
    assert summary["ok"] is False
    assert "lifecycle" in " ".join(summary["errors"]).lower()
    assert "fallback" not in json.dumps(summary).lower()
    assert _snapshot_tree(vault) == before


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_onboarding_rolls_back_every_write_when_a_late_target_fails(
    tmp_path: Path,
) -> None:
    vault = _prepare_provision_vault(tmp_path)
    core_directory = vault / "core"
    original_mode = core_directory.stat().st_mode & 0o777
    core_directory.chmod(0o500)
    before = _snapshot_tree(vault)

    try:
        completed = _invoke_provision(vault, "--onboard")
        after = _snapshot_tree(vault)
    finally:
        core_directory.chmod(original_mode)

    assert completed.returncode != 0
    summary = json.loads(completed.stdout)
    assert summary["ok"] is False
    assert summary.get("rolled_back") is True
    assert summary["created"] == []
    assert summary["removed"] == []
    failed = summary["provision_transaction_failure"]
    assert failed["terminal"] is True
    assert failed["transaction_ids"]
    declared = set(summary["mutation_receipt"]["declared_paths"])
    changed = {
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    }
    assert changed
    assert changed <= declared
    assert all(path == "System/.dex" or path.startswith("System/.dex/tx") for path in changed)
    assert {
        path: value
        for path, value in after.items()
        if not path.startswith("System/.dex")
    } == {
        path: value
        for path, value in before.items()
        if not path.startswith("System/.dex")
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize(
    "crash_seam",
    (
        "after-begin",
        "after-snapshot",
        "mid-apply:0",
        "after-apply",
        "after-verify",
        "after-commit-record",
    ),
)
def test_real_onboarding_recovers_every_direct_transaction_crash_seam(
    tmp_path: Path,
    crash_seam: str,
) -> None:
    vault = _prepare_provision_vault(tmp_path)
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps({"name": "Crash Test", "pillars": [{"name": "Recover"}]}),
        encoding="utf-8",
    )
    session = vault / "System/.onboarding-session.json"
    session_bytes = b'{"step":"finalize"}\n'
    session.write_bytes(session_bytes)
    protected = vault / "05-Areas/Do-Not-Touch/sentinel.md"
    protected.parent.mkdir(parents=True)
    protected.write_bytes(b"user-owned\n")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside-owned\n")
    custom_link = vault / "user-owned-link"
    custom_link.symlink_to(outside)

    interrupted = _invoke_provision(
        vault,
        "--onboard",
        "--profile",
        str(profile),
        "--session-file",
        str(session),
        env={**os.environ, "DEX_TX_TEST_STOP_AFTER": crash_seam},
    )

    assert interrupted.returncode != 0
    marker = vault / "System/.onboarding-complete"
    assert marker.exists() or session.exists()
    if not marker.exists():
        assert session.read_bytes() == session_bytes
    assert protected.read_bytes() == b"user-owned\n"
    assert custom_link.is_symlink() and custom_link.resolve() == outside
    assert outside.read_bytes() == b"outside-owned\n"

    provision_plans: list[list[dict[str, object]]] = []
    for journal in sorted((vault / "System/.dex/tx").glob("*/journal.jsonl")):
        records = [json.loads(line) for line in journal.read_text().splitlines()]
        begin = next((record for record in records if record["event"] == "BEGIN"), None)
        if begin and begin["payload"].get("operation") == "onboarding-provision":
            provision_plans.append(begin["payload"]["plan"])
    assert provision_plans
    plan_paths = [entry["relative"] for entry in provision_plans[-1]]
    marker_index = plan_paths.index("System/.onboarding-complete")
    session_index = plan_paths.index("System/.onboarding-session.json")
    assert all(
        index < marker_index
        for index, relative in enumerate(plan_paths)
        if relative not in {
            "System/.onboarding-complete",
            "System/.onboarding-session.json",
        }
    )
    assert marker_index < session_index

    recovered = _invoke_provision(
        vault,
        "--onboard",
        "--profile",
        str(profile),
        "--session-file",
        str(session),
    )
    assert recovered.returncode == 0, recovered.stderr
    recovered_summary = json.loads(recovered.stdout)
    assert recovered_summary["ok"] is True
    assert marker.is_file()
    assert not session.exists()
    assert protected.read_bytes() == b"user-owned\n"
    assert custom_link.is_symlink() and custom_link.resolve() == outside
    assert outside.read_bytes() == b"outside-owned\n"

    committed: set[str] = set()
    for journal in sorted((vault / "System/.dex/tx").glob("*/journal.jsonl")):
        events = {
            json.loads(line)["event"]
            for line in journal.read_text(encoding="utf-8").splitlines()
        }
        assert len(events & {"COMMITTED", "ROLLED-BACK"}) == 1
        if "COMMITTED" in events:
            committed.add(journal.parent.name)
    assert committed <= set(recovered_summary["mutation_receipt"]["transaction_ids"])

    settled = _snapshot_tree(vault)
    repeated = _invoke_provision(
        vault,
        "--onboard",
        "--profile",
        str(profile),
        "--session-file",
        str(session),
    )
    assert repeated.returncode == 0, repeated.stderr
    repeated_summary = json.loads(repeated.stdout)
    assert repeated_summary["created"] == []
    assert repeated_summary["removed"] == []
    assert _snapshot_tree(vault) == settled
    assert committed <= set(repeated_summary["mutation_receipt"]["transaction_ids"])


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_real_adopt_recovers_a_lifecycle_commit_after_its_receipt_is_lost(
    tmp_path: Path,
) -> None:
    vault = _prepare_provision_vault(
        tmp_path,
        profile_text="name: Existing User\ncustom: keep\n",
        companies_default=True,
    )
    session = vault / "System/.onboarding-session.json"
    session_bytes = b'{"step":"finalize"}\n'
    session.write_bytes(session_bytes)

    interrupted = _invoke_provision(
        vault,
        "--adopt",
        "--session-file",
        str(session),
        env={**os.environ, "DEX_TX_TEST_STOP_AFTER": "after-commit-record"},
    )

    assert interrupted.returncode != 0
    assert not (vault / "System/.onboarding-complete").exists()
    assert session.read_bytes() == session_bytes
    committed = {
        journal.parent.name
        for journal in (vault / "System/.dex/tx").glob("*/journal.jsonl")
        if '"event":"COMMITTED"' in journal.read_text(encoding="utf-8")
    }
    assert len(committed) == 1

    recovered = _invoke_provision(
        vault,
        "--adopt",
        "--session-file",
        str(session),
    )
    assert recovered.returncode == 0, recovered.stderr
    summary = json.loads(recovered.stdout)
    assert summary["ok"] is True
    assert (vault / "System/.onboarding-complete").is_file()
    assert not session.exists()
    profile = yaml.safe_load(
        (vault / "System/user-profile.yaml").read_text(encoding="utf-8")
    )
    assert profile["capabilities"]["companies"]["enabled"] is True
    assert committed <= set(summary["mutation_receipt"]["transaction_ids"])


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize(
    ("transaction_seam", "adoption_seam"),
    (
        ("after-commit-record", None),
        (None, "after-receipt"),
        (None, "after-ledger"),
    ),
)
def test_child_provisioner_recovers_catalogue_adoption_finalization_boundaries(
    tmp_path: Path,
    transaction_seam: str | None,
    adoption_seam: str | None,
) -> None:
    vault = _prepare_provision_vault(
        tmp_path,
        profile_text=(
            "name: Existing User\n"
            "custom: keep\n"
            "capabilities:\n"
            "  career:\n"
            "    enabled: true\n"
            "  companies:\n"
            "    enabled: true\n"
            "  quarter_goals:\n"
            "    enabled: true\n"
        ),
    )
    _install_adoptable_lifecycle_fixture(vault)
    session = vault / "System/.onboarding-session.json"
    session_bytes = b'{"step":"finalize"}\n'
    session.write_bytes(session_bytes)
    environment = dict(os.environ)
    if transaction_seam is not None:
        environment["DEX_TX_TEST_STOP_AFTER"] = transaction_seam
    if adoption_seam is not None:
        environment["DEX_ADOPTION_TEST_STOP_AFTER"] = adoption_seam

    interrupted = _invoke_provision(
        vault,
        "--adopt",
        "--session-file",
        str(session),
        env=environment,
    )

    assert interrupted.returncode != 0
    assert not (vault / "System/.onboarding-complete").exists()
    assert session.read_bytes() == session_bytes
    adoption_journals = []
    for journal in (vault / "System/.dex/tx").glob("*/journal.jsonl"):
        records = [json.loads(line) for line in journal.read_text().splitlines()]
        if any(record["event"] == "ADOPTION-INTENT" for record in records):
            adoption_journals.append((journal, records))
    assert len(adoption_journals) == 1
    journal, records = adoption_journals[0]
    assert sum(record["event"] == "COMMITTED" for record in records) == 1
    transaction_id = journal.parent.name

    recovered = _invoke_provision(
        vault,
        "--adopt",
        "--session-file",
        str(session),
    )

    assert recovered.returncode == 0, recovered.stderr
    summary = json.loads(recovered.stdout)
    assert summary["ok"] is True
    assert (vault / "System/.onboarding-complete").is_file()
    assert not session.exists()
    receipt = vault / f"System/.dex/adoptions/{transaction_id}.receipt.json"
    assert receipt.is_file()
    assert transaction_id in summary["mutation_receipt"]["transaction_ids"]

    settled = _snapshot_tree(vault)
    repeated = _invoke_provision(
        vault,
        "--adopt",
        "--session-file",
        str(session),
    )
    assert repeated.returncode == 0, repeated.stderr
    repeated_summary = json.loads(repeated.stdout)
    assert repeated_summary["created"] == []
    assert repeated_summary["removed"] == []
    assert _snapshot_tree(vault) == settled
    assert transaction_id in repeated_summary["mutation_receipt"]["transaction_ids"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("unsafe_kind", ("symlink", "custom-bytes"))
def test_onboarding_refuses_unsafe_active_skill_before_any_vault_mutation(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    vault = _prepare_provision_vault(tmp_path)
    target = vault / ".claude/skills/resume-builder"
    target.parent.mkdir(parents=True, exist_ok=True)
    if unsafe_kind == "symlink":
        protected = vault / "05-Areas/Do-Not-Touch"
        protected.mkdir(parents=True)
        (protected / "sentinel.md").write_text("preserve\n", encoding="utf-8")
        target.symlink_to(protected, target_is_directory=True)
    else:
        target.mkdir()
        (target / "SKILL.md").write_text("user-owned custom skill\n", encoding="utf-8")
    before = _snapshot_tree(vault)

    completed = _invoke_provision(vault, "--onboard")

    assert completed.returncode != 0
    errors = " ".join(json.loads(completed.stdout)["errors"]).lower()
    assert "target" in errors or "symlink" in errors
    assert _snapshot_tree(vault) == before


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_onboarding_refuses_non_directory_skill_ancestor_before_any_vault_mutation(
    tmp_path: Path,
) -> None:
    vault = _prepare_provision_vault(tmp_path)
    claude = vault / ".claude"
    claude.mkdir(exist_ok=True)
    (claude / "skills").write_text("not a directory\n", encoding="utf-8")
    before = _snapshot_tree(vault)

    completed = _invoke_provision(vault, "--onboard")

    assert completed.returncode != 0
    errors = " ".join(json.loads(completed.stdout)["errors"]).lower()
    assert "ancestor" in errors or "directory" in errors or "target" in errors
    assert _snapshot_tree(vault) == before


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize(
    ("unsafe_target", "target_kind"),
    (
        ("System", "directory"),
        ("core", "directory"),
        ("CLAUDE.md", "file"),
        (".mcp.json", "file"),
    ),
)
def test_onboarding_refuses_symlinked_mutation_targets_before_any_write(
    tmp_path: Path,
    unsafe_target: str,
    target_kind: str,
) -> None:
    vault = _prepare_provision_vault(tmp_path)
    outside = tmp_path / f"outside-{unsafe_target.replace('/', '-') }"
    target = vault / unsafe_target
    if target_kind == "directory":
        target.rename(outside)
        target.symlink_to(outside, target_is_directory=True)
    else:
        outside.write_text(
            '{"mcpServers": {}}\n' if unsafe_target == ".mcp.json" else "outside bytes\n",
            encoding="utf-8",
        )
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(outside)
    before_vault = _snapshot_tree(vault)
    before_outside = _snapshot_tree(outside) if outside.is_dir() else outside.read_bytes()

    completed = _invoke_provision(vault, "--onboard")

    assert completed.returncode != 0
    errors = " ".join(json.loads(completed.stdout)["errors"]).lower()
    assert "symlink" in errors or "unsafe" in errors
    assert _snapshot_tree(vault) == before_vault
    after_outside = _snapshot_tree(outside) if outside.is_dir() else outside.read_bytes()
    assert after_outside == before_outside


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_onboarding_rejects_outside_session_file_before_any_write(tmp_path: Path) -> None:
    vault = _prepare_provision_vault(tmp_path)
    outside_session = tmp_path / "outside-session.json"
    outside_session.write_text('{"private": true}\n', encoding="utf-8")
    before_vault = _snapshot_tree(vault)
    before_session = outside_session.read_bytes()

    completed = _invoke_provision(
        vault,
        "--onboard",
        "--session-file",
        str(outside_session),
    )

    assert completed.returncode != 0
    errors = " ".join(json.loads(completed.stdout)["errors"]).lower()
    assert "session" in errors and "inside the vault" in errors
    assert _snapshot_tree(vault) == before_vault
    assert outside_session.read_bytes() == before_session


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_onboarding_rejects_an_adjacent_in_vault_session_before_any_write(
    tmp_path: Path,
) -> None:
    vault = _prepare_provision_vault(tmp_path)
    adjacent_session = vault / "System/.onboarding/other.json"
    adjacent_session.parent.mkdir(parents=True)
    adjacent_session.write_text('{"private": true}\n', encoding="utf-8")
    before = _snapshot_tree(vault)

    completed = _invoke_provision(
        vault,
        "--onboard",
        "--session-file",
        str(adjacent_session),
    )

    assert completed.returncode != 0
    errors = " ".join(json.loads(completed.stdout)["errors"])
    assert "System/.onboarding-session.json" in errors
    assert _snapshot_tree(vault) == before


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_onboarding_dry_run_and_apply_upgrade_one_known_prior_room_payload(
    tmp_path: Path,
) -> None:
    vault = _prepare_provision_vault(tmp_path)
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    pin = contract["capabilities"]["career"]["skill_sources"][0]
    previous = b"---\nname: career-setup\ndescription: Published fixture release.\n---\n"
    pin["previous_payloads"].append(
        {
            "release": "v1.95.0",
            "sha256": hashlib.sha256(previous).hexdigest(),
            "byte_size": len(previous),
        }
    )
    fixture_contract = tmp_path / "previous-room-payload-contract.json"
    fixture_contract.write_text(json.dumps(contract), encoding="utf-8")
    target = vault / pin["target_path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(previous)
    environment = {
        **os.environ,
        "DEX_CAPABILITY_CONTRACT_PATH": str(fixture_contract),
    }

    preview = _invoke_provision(vault, "--onboard", "--dry-run", env=environment)

    assert preview.returncode == 0, preview.stderr
    preview_summary = json.loads(preview.stdout)
    assert pin["target_path"] in preview_summary["created"]
    assert target.read_bytes() == previous

    applied = _invoke_provision(vault, "--onboard", env=environment)

    assert applied.returncode == 0, applied.stderr
    assert target.read_bytes() == (REPO_ROOT / pin["source_path"]).read_bytes()


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_adopt_gives_an_existing_vault_without_a_company_opinion_the_room_idempotently(
    tmp_path: Path,
) -> None:
    """A vault that never expressed a choice gets Companies, like Career and
    Quarter Goals. It was previously withheld, which no user could explain."""
    vault = _prepare_provision_vault(
        tmp_path,
        profile_text="name: Existing User\ncustom: keep\n",
        companies_default=True,
    )
    profile_path = vault / "System/user-profile.yaml"

    _run_provision(vault, "--adopt")

    first = profile_path.read_text(encoding="utf-8")
    profile = yaml.safe_load(first)
    assert profile["capabilities"]["companies"]["enabled"] is True
    assert capabilities.enabled(
        "companies",
        profile_path=profile_path,
        contract_path=CONTRACT_PATH,
    ) is True
    assert (vault / "05-Areas/Companies").exists()

    _run_provision(vault, "--adopt")

    assert profile_path.read_text(encoding="utf-8") == first


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_lifecycle_only_update_pins_markerless_existing_vault_transactionally(
    tmp_path: Path,
) -> None:
    original = "# keep this comment\nname: Existing User\ncustom: keep\n"
    vault = _prepare_provision_vault(tmp_path, profile_text=original)
    profile_path = vault / "System/user-profile.yaml"

    first_summary = _run_provision(vault, "--adopt", "--lifecycle-only")

    first = profile_path.read_text(encoding="utf-8")
    profile = yaml.safe_load(first)
    assert first.startswith(original)
    assert profile["capabilities"]["career"]["enabled"] is True
    assert profile["capabilities"]["companies"]["enabled"] is True
    assert profile["capabilities"]["quarter_goals"]["enabled"] is True
    assert first_summary["compatibility_pins"] == ["companies"]
    assert first_summary["mutation_receipt"]["executor"] == "lifecycle-service"
    assert first_summary["mutation_receipt"]["lifecycle_transaction_id"]
    transaction_directories = sorted((vault / "System/.dex/tx").iterdir())

    second_summary = _run_provision(vault, "--adopt", "--lifecycle-only")

    assert profile_path.read_text(encoding="utf-8") == first
    assert second_summary["compatibility_pins"] == []
    assert sorted((vault / "System/.dex/tx").iterdir()) == transaction_directories


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_lifecycle_only_dry_run_previews_the_exact_compatibility_pin(
    tmp_path: Path,
) -> None:
    original = "# keep this comment\nname: Existing User\n"
    vault = _prepare_provision_vault(tmp_path, profile_text=original)

    summary = _run_provision(
        vault,
        "--adopt",
        "--lifecycle-only",
        "--dry-run",
    )

    assert (vault / "System/user-profile.yaml").read_text(encoding="utf-8") == original
    assert not (vault / "System/.dex/tx").exists()
    assert summary["compatibility_pins"] == ["companies"]
    assert summary["lifecycle_executor"]["compatibility_states"] == {
        "career": True,
        "companies": True,
        "quarter_goals": True,
    }
    assert summary["mutation_receipt"]["declared_paths"] == [
        "System/user-profile.yaml"
    ]
    assert summary["mutation_receipt"]["lifecycle_transaction_ids"] == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_full_adopt_dry_run_uses_the_transaction_previewed_room_states(
    tmp_path: Path,
) -> None:
    original = "name: Existing User\n"
    vault = _prepare_provision_vault(tmp_path, profile_text=original)

    summary = _run_provision(vault, "--adopt", "--dry-run")

    assert (vault / "System/user-profile.yaml").read_text(encoding="utf-8") == original
    assert "05-Areas/Companies" in summary["created"]
    assert "05-Areas/Career" in summary["created"]
    assert "01-Quarter_Goals" in summary["created"]
    assert summary["lifecycle_executor"]["compatibility_states"] == {
        "career": True,
        "companies": True,
        "quarter_goals": True,
    }


def test_compatibility_pin_recovers_before_inspecting_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _prepare_provision_vault(
        tmp_path,
        profile_text="capabilities:\n  companies:\n    enabled: false\n",
    )
    profile_path = vault / "System/user-profile.yaml"
    calls: list[Path] = []

    def recover(root: Path) -> list[dict]:
        calls.append(Path(root))
        profile_path.write_text("name: Rolled Back\n", encoding="utf-8")
        return []

    monkeypatch.setattr(service.Transaction, "resume", staticmethod(recover))

    result = service._pin_missing_companies_default(vault)

    assert calls == [vault]
    assert result["pinned"] is True
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert profile["capabilities"]["companies"]["enabled"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_lifecycle_only_update_adds_only_companies_to_a_partial_capability_map(
    tmp_path: Path,
) -> None:
    vault = _prepare_provision_vault(
        tmp_path,
        profile_text="capabilities:\n  career:\n    enabled: false\n",
    )

    _run_provision(vault, "--adopt", "--lifecycle-only")

    profile = yaml.safe_load(
        (vault / "System/user-profile.yaml").read_text(encoding="utf-8")
    )
    assert profile["capabilities"] == {
        # Companies is added because this vault never said otherwise; the
        # explicit career: false above is a real choice and is preserved.
        "companies": {"enabled": True},
        "career": {"enabled": False},
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("company_enabled", [True, False])
def test_adopt_preserves_an_existing_explicit_company_choice(
    tmp_path: Path,
    company_enabled: bool,
) -> None:
    vault = _prepare_provision_vault(
        tmp_path,
        profile_text=yaml.safe_dump(
            {
                "name": "Existing User",
                "capabilities": {
                    "companies": {
                        "enabled": company_enabled,
                        "custom": "keep",
                    }
                },
            },
            sort_keys=False,
        ),
        companies_default=True,
    )

    _run_provision(vault, "--adopt")

    profile = yaml.safe_load(
        (vault / "System/user-profile.yaml").read_text(encoding="utf-8")
    )
    assert profile["capabilities"]["companies"] == {
        "enabled": company_enabled,
        "custom": "keep",
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("company_enabled", [True, False])
def test_lifecycle_only_update_preserves_an_explicit_company_choice(
    tmp_path: Path,
    company_enabled: bool,
) -> None:
    original = (
        "# keep this comment\n"
        "capabilities:\n"
        "  companies:\n"
        f"    enabled: {'true' if company_enabled else 'false'}\n"
        "    custom: keep\n"
    )
    vault = _prepare_provision_vault(tmp_path, profile_text=original)

    summary = _run_provision(vault, "--adopt", "--lifecycle-only")

    assert (vault / "System/user-profile.yaml").read_text(encoding="utf-8") == original
    assert summary["compatibility_pins"] == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_adopt_preserves_a_legacy_capability_opinion(tmp_path: Path) -> None:
    vault = _prepare_provision_vault(
        tmp_path,
        profile_text=(
            "name: Existing User\n"
            "quarterly_planning:\n"
            "  enabled: true\n"
            "  q1_start_month: 4\n"
        ),
        companies_default=True,
    )

    _run_provision(vault, "--adopt")

    profile = yaml.safe_load(
        (vault / "System/user-profile.yaml").read_text(encoding="utf-8")
    )
    assert profile["capabilities"]["companies"]["enabled"] is True
    assert profile["capabilities"]["quarter_goals"]["enabled"] is True
    assert profile["quarterly_planning"]["enabled"] is True
    assert profile["quarterly_planning"]["q1_start_month"] == 4
