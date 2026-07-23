"""Tests for the portable-vault ownership contract and its CI gate.

The gate invariants each carry a red-when-removed style proof: we show the
gate FAILS when the invariant it protects is violated, not just that it
passes on the healthy tree.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core import portable_contract

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tracked_paths() -> list[str]:
    output = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in output.splitlines() if line]


# ---------------------------------------------------------------------------
# Resolution semantics
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("path", "ownership", "denied"),
    [
        # brain
        ("core/utils/doctor.py", "brain", False),
        (".claude/skills/daily-plan/SKILL.md", "brain", False),
        ("CLAUDE.md", "generated", False),
        ("06-Resources/Dex_System/Dex_System_Guide.md", "brain", False),
        # seed: exact starters only
        ("03-Tasks/Tasks.md", "seed", False),
        ("04-Projects/README.md", "seed", False),
        ("System/Templates/Person_Page.md", "seed", False),
        ("System/integrations/config.yaml", "seed", False),
        ("System/user-profile.yaml", "seed", False),
        # vault: user content, regions, values, extensions
        ("04-Projects/My_Project/notes.md", "vault", False),
        ("01-Quarter_Goals/my-goals-2027.md", "vault", False),
        ("06-Resources/my-research/notes.md", "vault", False),
        (".claude/skills-custom/mine/SKILL.md", "vault", False),
        ("CLAUDE-custom.md", "vault", False),
        (".mcp.json", "vault", False),
        ("System/folder-paths.yaml", "vault", False),
        # secrets: vault AND hard-denied
        (".env", "vault", True),
        (".env.local", "vault", True),
        ("System/credentials/token.json", "vault", True),
        ("some/dir/private.pem", "vault", True),
        ("integrations/service-token.json", "vault", True),
        # generated / runtime
        ("System/.installed-files.manifest", "generated", False),
        ("packages/dex-contracts/dist/paths.contract.json", "generated", False),
        ("System/.dex/gardener.json", "runtime", False),
        ("System/.onboarding-session.json", "runtime", False),
        ("System/Session_Learnings/2026-05-01.md", "runtime", False),
    ],
)
def test_resolution_semantics(path: str, ownership: str, denied: bool) -> None:
    resolution = portable_contract.resolve(path)
    assert resolution.ownership == ownership
    assert resolution.denied is denied


def test_exact_seed_beats_region_and_specificity_orders_directories() -> None:
    # Exact starter file wins over its vault region.
    assert portable_contract.resolve("03-Tasks/Tasks.md").rule_id == "seed-tasks-file"
    # Shipped system docs are enumerated file-by-file as brain…
    assert (
        portable_contract.resolve("06-Resources/Dex_System/README.md").rule_id
        == "brain-doc-dex-system-readme"
    )


def test_user_file_next_to_shipped_docs_is_vault_not_brain() -> None:
    """Review finding #1: a user's own note under 06-Resources/Dex_System/
    must fall through to the vault region — an update may never clobber it."""
    resolution = portable_contract.resolve("06-Resources/Dex_System/my-notes.md")
    assert resolution.ownership == "vault"
    assert resolution.rule_id == "vault-resources"
    verdict = portable_contract.update_write_verdict(
        "06-Resources/Dex_System/my-notes.md", exists=True
    )
    assert verdict.allowed is False


def test_deny_check_is_case_folded_for_macos() -> None:
    """Review finding #4: APFS is case-insensitive; odd-case secrets must deny."""
    for path in ("secret.PEM", ".ENV", "System/Credentials/x.json", "a/B.KEY"):
        assert portable_contract.is_denied(path), path
        assert portable_contract.resolve(path).denied is True, path


def test_mutation_policy_travels_in_the_document() -> None:
    document = portable_contract.build_contract_document()
    assert document["mutation_policy"] == {
        "brain": "replace",
        "generated": "regenerate",
        "runtime": "never",
        "seed": "write-if-absent",
        "vault": "never",
    }


@pytest.mark.parametrize(
    ("path", "exists", "allowed", "action"),
    [
        ("core/utils/doctor.py", True, True, "replace"),
        ("03-Tasks/Tasks.md", False, True, "write-if-absent"),
        ("03-Tasks/Tasks.md", True, False, "write-if-absent"),  # user file wins
        ("System/.installed-files.manifest", True, True, "regenerate"),
        ("04-Projects/My_Project/notes.md", True, False, "never"),
        ("System/Session_Learnings/2026-05-01.md", False, False, "never"),
        ("System/.onboarding-session.json", False, False, "never"),
        (".env", False, False, "deny"),
        ("totally/unknown/path.xyz", False, False, "unclassified-never-write"),
    ],
)
def test_update_write_verdict(path: str, exists: bool, allowed: bool, action: str) -> None:
    verdict = portable_contract.update_write_verdict(path, exists=exists)
    assert verdict.allowed is allowed
    assert verdict.action == action


def test_legacy_shipped_runtime_surfaces_the_baseline_debt() -> None:
    debt = portable_contract.legacy_shipped_runtime(_tracked_paths())
    # Runtime debt still exists, but untrack-v1 no longer ships personal
    # Session_Learnings entries.
    assert "System/usage_log.md" in debt
    assert not any(path.startswith("System/Session_Learnings/") for path in debt)


def test_traversal_and_empty_paths_are_rejected() -> None:
    with pytest.raises(portable_contract.ContractViolation):
        portable_contract.resolve("../outside")
    with pytest.raises(portable_contract.ContractViolation):
        portable_contract.resolve("")


def test_unknown_path_raises_and_unclassified_reports_it() -> None:
    with pytest.raises(portable_contract.ContractViolation):
        portable_contract.resolve("totally/unknown/path.xyz")
    assert portable_contract.unclassified(["totally/unknown/path.xyz"]) == [
        "totally/unknown/path.xyz"
    ]


# ---------------------------------------------------------------------------
# Whole-tree invariants (the gate's substance, asserted directly)
# ---------------------------------------------------------------------------

def test_every_tracked_path_classifies() -> None:
    missing = portable_contract.unclassified(_tracked_paths())
    assert missing == []


def test_no_tracked_path_is_release_forbidden() -> None:
    assert portable_contract.release_forbidden(_tracked_paths()) == []


def test_release_forbidden_flags_vault_and_denied_content() -> None:
    forbidden = portable_contract.release_forbidden(
        ["04-Projects/private-notes.md", ".env", "core/utils/doctor.py"]
    )
    assert "04-Projects/private-notes.md" in forbidden
    assert ".env" in forbidden
    assert "core/utils/doctor.py" not in forbidden


def test_capability_rooms_cover_gated_regions() -> None:
    capabilities = portable_contract.CAPABILITIES
    assert set(capabilities) == {"career", "companies", "quarter_goals"}
    gated_folders = {
        folder for spec in capabilities.values() for folder in spec["folders"]
    }
    assert gated_folders == {
        "05-Areas/Career",
        "05-Areas/Companies",
        "01-Quarter_Goals",
    }
    # The spine is not a capability by design.
    assert "meetings" not in capabilities
    assert "people" not in capabilities
    assert "tasks" not in capabilities
    # Rooms default OFF: a fresh spine-only install is the baseline.
    assert all(spec["default_enabled"] is False for spec in capabilities.values())


def test_committed_dist_matches_source_of_truth() -> None:
    committed = json.loads(
        (REPO_ROOT / "packages/dex-contracts/dist/portable-vault.contract.json")
        .read_text(encoding="utf-8")
    )
    assert committed == portable_contract.build_contract_document()
    committed_schema = json.loads(
        (REPO_ROOT / "packages/dex-contracts/dist/portable-vault.schema.json")
        .read_text(encoding="utf-8")
    )
    assert committed_schema == portable_contract.build_contract_schema()


def test_rule_ids_are_unique_and_document_is_deterministic() -> None:
    ids = [rule.rule_id for rule in portable_contract.RULES]
    assert len(ids) == len(set(ids))
    assert portable_contract.build_contract_document() == (
        portable_contract.build_contract_document()
    )


def test_sync_folder_marker_data_is_explicitly_release_owned() -> None:
    resolution = portable_contract.resolve("core/data/sync-folder-markers.json")

    assert resolution is not None
    assert resolution.rule_id == "brain-sync-folder-markers"
    assert resolution.ownership == "brain"


# ---------------------------------------------------------------------------
# The gate script: red-when-removed proofs in an isolated fixture repo
# ---------------------------------------------------------------------------

def _gate_fixture(tmp_path: Path) -> Path:
    """A minimal repo the real gate script runs against."""
    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for relative in (
        "scripts/check-portable-contract.py",
        "scripts/check-portable-contract.sh",
        "scripts/generate-portable-contract.py",
        "core/portable_contract.py",
        "core/utils/local_git.py",
        "core/__init__.py",
        "core/utils/__init__.py",
    ):
        source = REPO_ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    dist = root / "packages/dex-contracts/dist"
    dist.mkdir(parents=True)
    for name in ("portable-vault.contract.json", "portable-vault.schema.json"):
        (dist / name).write_bytes(
            (REPO_ROOT / "packages/dex-contracts/dist" / name).read_bytes()
        )
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True, capture_output=True
    )
    return root


def _run_gate(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/check-portable-contract.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_gate_passes_on_healthy_fixture(tmp_path: Path) -> None:
    root = _gate_fixture(tmp_path)
    result = _run_gate(root)
    assert result.returncode == 0, result.stdout + result.stderr


def test_gate_red_on_unclassified_path(tmp_path: Path) -> None:
    root = _gate_fixture(tmp_path)
    stray = root / "totally-new-toplevel" / "thing.txt"
    stray.parent.mkdir()
    stray.write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)

    result = _run_gate(root)

    assert result.returncode == 1
    assert "UNCLASSIFIED" in result.stdout


def test_gate_red_on_vault_content_in_tree(tmp_path: Path) -> None:
    root = _gate_fixture(tmp_path)
    leaked = root / "04-Projects" / "Private_Client" / "notes.md"
    leaked.parent.mkdir(parents=True)
    leaked.write_text("user content that must never ship\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)

    result = _run_gate(root)

    assert result.returncode == 1
    assert "RELEASE-FORBIDDEN" in result.stdout


def test_gate_red_on_dist_drift(tmp_path: Path) -> None:
    root = _gate_fixture(tmp_path)
    contract_path = root / "packages/dex-contracts/dist/portable-vault.contract.json"
    document = json.loads(contract_path.read_text(encoding="utf-8"))
    document["rules"] = document["rules"][:-1]  # drop one rule -> drift
    contract_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    result = _run_gate(root)

    assert result.returncode == 1
    assert "DRIFT" in result.stdout
