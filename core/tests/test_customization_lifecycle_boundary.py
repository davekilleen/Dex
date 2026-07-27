"""Load-bearing boundary coverage for customization rebuild mutations."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core.customization_migration import activation, cli
from core.customization_migration import service as migration_service
from core.lifecycle import service as lifecycle_service
from core.tests.test_customization_verification import _candidate_with_contract
from core.tests.vault_observed_writes import snapshot_vault
from core.transaction.engine import PlanRejected

REPO_ROOT = Path(__file__).resolve().parents[2]
_FORBIDDEN_IMPORTS = {
    "core.customization_migration.capsule": {
        "abandon_capsule",
        "create_capsule",
    },
    "core.customization_migration.staging": {"stage_candidate"},
    "core.customization_migration.verification": {
        "write_verification_report",
    },
    "core.customization_migration.activation": {"activate", "rewind"},
    "core.transaction.engine": {"Transaction"},
}


def _forbidden_mutator_references(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_aliases: dict[str, str] = {}
    direct_aliases: dict[str, tuple[str, str]] = {}
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _FORBIDDEN_IMPORTS:
                    module_aliases[alias.asname or alias.name.rsplit(".", 1)[-1]] = (
                        alias.name
                    )
        elif isinstance(node, ast.ImportFrom) and node.module in _FORBIDDEN_IMPORTS:
            for alias in node.names:
                if alias.name in _FORBIDDEN_IMPORTS[node.module]:
                    direct_aliases[alias.asname or alias.name] = (
                        node.module,
                        alias.name,
                    )
                    violations.append(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                imported_module = f"{node.module}.{alias.name}"
                if imported_module in _FORBIDDEN_IMPORTS:
                    module_aliases[alias.asname or alias.name] = imported_module

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in direct_aliases:
            module, name = direct_aliases[node.func.id]
            violations.append(f"{module}.{name}()")
        elif (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            module = module_aliases.get(node.args[0].id)
            name = node.args[1].value
            if module is not None and name in _FORBIDDEN_IMPORTS[module]:
                violations.append(f"{module}.{name}()")
        elif (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
        ):
            module = module_aliases.get(node.func.value.id)
            if (
                module is not None
                and node.func.attr in _FORBIDDEN_IMPORTS[module]
            ):
                violations.append(f"{module}.{node.func.attr}()")
            if node.func.value.id == "Transaction" and node.func.attr == "resume":
                violations.append("core.transaction.engine.Transaction.resume()")
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"begin", "resume"}
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "Transaction"
            and isinstance(node.func.value.value, ast.Name)
            and module_aliases.get(node.func.value.value.id)
            == "core.transaction.engine"
        ):
            violations.append(
                "core.transaction.engine.Transaction."
                f"{node.func.attr}()"
            )
    return sorted(set(violations))


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "\n".join(
                [
                    "from core.customization_migration import capsule",
                    "capsule.create_capsule(root, release)",
                ]
            ),
            {"core.customization_migration.capsule.create_capsule()"},
        ),
        (
            "\n".join(
                [
                    "from core.customization_migration import staging as module",
                    'getattr(module, "stage_candidate")(root, candidate)',
                ]
            ),
            {"core.customization_migration.staging.stage_candidate()"},
        ),
        (
            "\n".join(
                [
                    "from core.transaction import engine as e",
                    "e.Transaction.begin(root, plan)",
                    "e.Transaction.resume(root)",
                ]
            ),
            {
                "core.transaction.engine.Transaction.begin()",
                "core.transaction.engine.Transaction.resume()",
            },
        ),
    ],
    ids=(
        "submodule-import-attribute",
        "getattr-module-alias",
        "transaction-engine-alias",
    ),
)
def test_forbidden_mutator_guard_flags_module_alias_bypasses(
    tmp_path: Path,
    source: str,
    expected: set[str],
) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text(f"{source}\n", encoding="utf-8")

    assert expected <= set(_forbidden_mutator_references(candidate))


def test_rebuild_activation_derives_rewind_token_without_post_commit_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Receipt:
        def to_dict(self) -> dict[str, str]:
            return {"transaction_id": "tx-approved"}

    receipt = Receipt()
    derived_from: list[object] = []

    monkeypatch.setattr(
        activation,
        "activate",
        lambda root, preview, token: receipt,
    )
    monkeypatch.setattr(
        activation,
        "_rewind_acknowledgement_token",
        lambda value: derived_from.append(value) or "rewind-token",
    )

    def refuse_post_commit_preview(*args: object) -> None:
        raise AssertionError("activation must not read the filesystem after commit")

    monkeypatch.setattr(activation, "preview_rewind", refuse_post_commit_preview)

    result = lifecycle_service.execute_approved_rebuild_activation(
        tmp_path,
        object(),
        "approved-token",
    )

    assert result == {
        "api_version": lifecycle_service.api_version,
        "receipt": {"transaction_id": "tx-approved"},
        "rewind_acknowledgement_token": "rewind-token",
    }
    assert derived_from == [receipt]


def test_customization_mutation_adapters_import_only_lifecycle_door() -> None:
    service_path = REPO_ROOT / "core/customization_migration/service.py"
    cli_path = REPO_ROOT / "core/customization_migration/cli.py"

    assert _forbidden_mutator_references(service_path) == []
    assert _forbidden_mutator_references(cli_path) == []
    assert "from core.lifecycle import service as lifecycle_service" in (
        service_path.read_text(encoding="utf-8")
    )
    assert "from core.customization_migration import service as migration_service" in (
        cli_path.read_text(encoding="utf-8")
    )


def test_cli_stage_fails_closed_when_lifecycle_door_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_bytes(
        migration_service.canonical_json_bytes(candidate.to_dict())
    )
    preview = migration_service.preview_staging_to_dict(vault, candidate)
    before = snapshot_vault(vault)
    calls: list[tuple[object, ...]] = []

    def refuse(*args: object, **kwargs: object) -> None:
        calls.append((*args, kwargs))
        raise PlanRejected("lifecycle rebuild staging refused")

    monkeypatch.setattr(
        lifecycle_service,
        "execute_approved_rebuild_staging",
        refuse,
        raising=False,
    )
    monkeypatch.setenv("VAULT_PATH", str(vault))

    return_code = cli.run(
        [
            "stage",
            str(candidate_path),
            "--confirm-token",
            str(preview["preview_sha256"]),
        ]
    )
    captured = capsys.readouterr()

    assert return_code == 2
    assert calls
    assert captured.err == ""
    assert "could not complete safely" in captured.out
    assert snapshot_vault(vault) == before
