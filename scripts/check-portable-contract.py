#!/usr/bin/env python3
"""CI gate for the portable-vault ownership contract.

Fails (exit 1) when any of these invariants breaks:

1. COMPLETENESS — every tracked path resolves to exactly one ownership class.
   Adding a new path to the repo requires a deliberate classification in
   ``core/portable_contract.py``.
2. RELEASE SAFETY — no tracked path classifies ``vault`` or is hard-denied:
   the public tree must never carry user content or secrets.
3. DRIFT — the committed ``packages/dex-contracts/dist`` view equals a fresh
   regeneration from the source of truth.
4. SCHEMA — the committed contract document validates against its schema
   (structural check; pure stdlib, no jsonschema dependency).

Exit 2 = the gate itself could not run (fail closed).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core import portable_contract
from core.utils.local_git import git_output

DIST = REPO_ROOT / "packages" / "dex-contracts" / "dist"


def _tracked_paths() -> list[str]:
    raw = git_output(REPO_ROOT, "ls-files", "-z", profile="read-only")
    return [path.decode("utf-8", errors="surrogateescape") for path in raw.split(b"\0") if path]


def _check_schema(document: dict, schema: dict) -> list[str]:
    """Minimal structural validation — enough to catch a malformed document.

    Belt-and-braces by design: the drift check (committed == regenerated)
    already guarantees structural validity for anything generated from source;
    this catches a hand-edited committed document on the path where drift
    detection itself is broken, and gives external consumers a checked shape.
    """
    problems: list[str] = []
    for key in schema.get("required", []):
        if key not in document:
            problems.append(f"contract document missing required key: {key}")
    if document.get("source") != "core/portable_contract.py":
        problems.append("contract document has a foreign source")
    classes = set(portable_contract.OWNERSHIP_CLASSES)
    rule_ids: set[str] = set()
    for rule in document.get("rules", []):
        missing = {"id", "path", "kind", "ownership"} - set(rule)
        if missing:
            problems.append(f"rule missing keys {sorted(missing)}: {rule}")
            continue
        if rule["ownership"] not in classes:
            problems.append(f"rule {rule['id']} has unknown class {rule['ownership']}")
        if rule["kind"] not in ("file", "dir"):
            problems.append(f"rule {rule['id']} has unknown kind {rule['kind']}")
        if rule["id"] in rule_ids:
            problems.append(f"duplicate rule id: {rule['id']}")
        rule_ids.add(rule["id"])
    for name, spec in document.get("capabilities", {}).items():
        if "default_enabled" not in spec or "folders" not in spec:
            problems.append(f"capability {name} missing default_enabled/folders")
    return problems


def main() -> int:
    failures: list[str] = []

    paths = _tracked_paths()

    # 1. Completeness.
    missing = portable_contract.unclassified(paths)
    for path in missing:
        failures.append(f"UNCLASSIFIED: {path}")

    # 2. Release safety.
    classifiable = [path for path in paths if path not in set(missing)]
    for path in portable_contract.release_forbidden(classifiable):
        failures.append(f"RELEASE-FORBIDDEN (vault/denied content in the public tree): {path}")

    # 3. Drift between source of truth and the committed dist view.
    committed_path = DIST / "portable-vault.contract.json"
    if not committed_path.is_file():
        failures.append(f"MISSING committed contract: {committed_path}")
        committed = None
    else:
        committed = json.loads(committed_path.read_text(encoding="utf-8"))
        fresh = portable_contract.build_contract_document()
        if committed != fresh:
            failures.append(
                "DRIFT: committed portable-vault.contract.json differs from "
                "core/portable_contract.py — run scripts/generate-portable-contract.py"
            )
    schema_path = DIST / "portable-vault.schema.json"
    if not schema_path.is_file():
        failures.append(f"MISSING committed schema: {schema_path}")
    elif json.loads(schema_path.read_text(encoding="utf-8")) != portable_contract.build_contract_schema():
        failures.append(
            "DRIFT: committed portable-vault.schema.json differs from the source "
            "of truth — run scripts/generate-portable-contract.py"
        )

    # 4. Structural schema validation of the committed document.
    if committed is not None:
        failures.extend(_check_schema(committed, portable_contract.build_contract_schema()))

    if failures:
        print("Portable-vault contract gate failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        f"✅ Portable-vault contract: {len(paths)} tracked paths classified, "
        "release-safe, dist in sync."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001 — the gate must fail closed, loudly.
        print(f"Portable-vault contract gate failed closed: {error}", file=sys.stderr)
        raise SystemExit(2) from None
