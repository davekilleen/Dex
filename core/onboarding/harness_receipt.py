"""Build and validate the non-secret receipt for Dex harness capabilities.

This module deliberately has no write function. Onboarding hands the canonical bytes to
the sanctioned provision transaction so every vault mutation still uses the one safe door.
"""

from __future__ import annotations

import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

SCHEMA_VERSION = 1
RECEIPT_RELATIVE_PATH = Path("System/.dex/harness-profile.json")
DELIVERY_MODES = frozenset({"automatic", "on_demand", "guided", "unavailable"})
SOURCES = frozenset({"user-confirmed", "detected", "migrated"})
TOP_LEVEL_FIELDS = frozenset(
    {"schema_version", "generated_at", "source", "selected", "detected", "profiles"}
)
PROFILE_FIELDS = frozenset({"id", "display_name", "capabilities"})
CAPABILITY_FIELDS = frozenset({"id", "mode"})


class HarnessReceiptError(ValueError):
    """The saved harness receipt is unsafe, malformed, or unsupported."""


def _identifier(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise HarnessReceiptError(f"{label} must be a non-empty string")
    if not all(
        character.islower() or character.isdigit() or character in {"-", "_"}
        for character in value
    ):
        raise HarnessReceiptError(
            f"{label} must use lowercase letters, digits, hyphens, and underscores"
        )
    return value


def _timestamp(value: datetime | str | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise HarnessReceiptError("generated_at must be an ISO-8601 timestamp") from error
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise HarnessReceiptError("generated_at must be a datetime or ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HarnessReceiptError("generated_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _normalise_profile(profile: Mapping[str, object]) -> dict[str, object]:
    profile_id = _identifier(profile.get("id"), label="profile id")
    display_name = profile.get("display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        raise HarnessReceiptError(f"profile {profile_id} needs a display_name")
    raw_capabilities = profile.get("capabilities")
    if not isinstance(raw_capabilities, Sequence) or isinstance(raw_capabilities, (str, bytes)):
        raise HarnessReceiptError(f"profile {profile_id} capabilities must be a list")
    capabilities: list[dict[str, str]] = []
    seen_capabilities: set[str] = set()
    for raw in raw_capabilities:
        if not isinstance(raw, Mapping):
            raise HarnessReceiptError(f"profile {profile_id} has a malformed capability")
        capability_id = _identifier(raw.get("id"), label="capability id")
        if capability_id in seen_capabilities:
            raise HarnessReceiptError(
                f"profile {profile_id} has duplicate capability {capability_id}"
            )
        seen_capabilities.add(capability_id)
        mode = raw.get("mode")
        if mode not in DELIVERY_MODES:
            raise HarnessReceiptError(
                f"profile {profile_id} capability {capability_id} has unsupported mode {mode!r}"
            )
        capabilities.append({"id": capability_id, "mode": str(mode)})
    if not capabilities:
        raise HarnessReceiptError(f"profile {profile_id} must declare capabilities")
    return {
        "id": profile_id,
        "display_name": display_name.strip(),
        "capabilities": sorted(capabilities, key=lambda item: item["id"]),
    }


def build_receipt(
    profiles: Sequence[Mapping[str, object]],
    *,
    detected_ids: Sequence[str],
    source: str,
    generated_at: datetime | str | None = None,
) -> dict[str, object]:
    """Return a canonical, non-secret receipt for selected harness profiles."""
    if source not in SOURCES:
        raise HarnessReceiptError(f"unsupported receipt source {source!r}")
    normalised = [_normalise_profile(profile) for profile in profiles]
    profile_ids = [str(profile["id"]) for profile in normalised]
    if not profile_ids:
        raise HarnessReceiptError("at least one harness profile must be selected")
    if len(profile_ids) != len(set(profile_ids)):
        raise HarnessReceiptError("harness receipt contains a duplicate profile")
    detected = [_identifier(value, label="detected harness id") for value in detected_ids]
    if len(detected) != len(set(detected)):
        raise HarnessReceiptError("harness receipt contains a duplicate detected id")
    ordered_profiles = sorted(normalised, key=lambda profile: str(profile["id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _timestamp(generated_at),
        "source": source,
        "selected": sorted(profile_ids),
        "detected": sorted(detected),
        "profiles": ordered_profiles,
    }


def canonical_receipt_bytes(receipt: Mapping[str, object]) -> bytes:
    """Serialize a validated receipt in stable, reviewable JSON."""
    validated = _validate_receipt(receipt)
    return (json.dumps(validated, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _unexpected_fields(value: Mapping[str, object], expected: frozenset[str]) -> set[str]:
    return set(value) - expected


def _validate_receipt(receipt: Mapping[str, object]) -> dict[str, object]:
    unexpected = _unexpected_fields(receipt, TOP_LEVEL_FIELDS)
    if unexpected:
        raise HarnessReceiptError(f"harness receipt has unexpected fields: {sorted(unexpected)}")
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise HarnessReceiptError("unsupported harness receipt schema_version")
    profiles = receipt.get("profiles")
    if not isinstance(profiles, list):
        raise HarnessReceiptError("harness receipt profiles must be a list")
    for profile in profiles:
        if not isinstance(profile, Mapping):
            raise HarnessReceiptError("harness receipt has a malformed profile")
        unexpected_profile = _unexpected_fields(profile, PROFILE_FIELDS)
        if unexpected_profile:
            raise HarnessReceiptError(
                f"harness profile has unexpected fields: {sorted(unexpected_profile)}"
            )
        capabilities = profile.get("capabilities")
        if isinstance(capabilities, list):
            for capability in capabilities:
                if not isinstance(capability, Mapping):
                    raise HarnessReceiptError("harness receipt has a malformed capability")
                unexpected_capability = _unexpected_fields(capability, CAPABILITY_FIELDS)
                if unexpected_capability:
                    raise HarnessReceiptError(
                        "harness capability has unexpected fields: "
                        f"{sorted(unexpected_capability)}"
                    )
    rebuilt = build_receipt(
        profiles,
        detected_ids=receipt.get("detected", []),  # type: ignore[arg-type]
        source=str(receipt.get("source", "")),
        generated_at=receipt.get("generated_at"),  # type: ignore[arg-type]
    )
    if receipt.get("selected") != rebuilt["selected"]:
        raise HarnessReceiptError("selected harness ids do not match the saved profiles")
    return rebuilt


def _refuse_symlinked_path(vault_root: Path, target: Path) -> None:
    cursor = vault_root
    for part in target.relative_to(vault_root).parts:
        cursor /= part
        if cursor.is_symlink():
            raise HarnessReceiptError(f"harness receipt path is symlinked: {cursor}")


def read_receipt(vault_root: Path) -> dict[str, object] | None:
    """Read the local receipt without following a symlink out of the vault."""
    root = Path(vault_root)
    target = root / RECEIPT_RELATIVE_PATH
    _refuse_symlinked_path(root, target)
    if not target.exists():
        return None
    if not target.is_file():
        raise HarnessReceiptError("harness receipt is not a regular file")
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HarnessReceiptError("harness receipt is not valid JSON") from error
    if not isinstance(parsed, Mapping):
        raise HarnessReceiptError("harness receipt must contain a JSON object")
    return _validate_receipt(parsed)


def summarize_receipt(receipt: Mapping[str, object]) -> dict[str, object]:
    """Summarize delivery modes without turning guided/advisory work automatic."""
    validated = _validate_receipt(receipt)
    modes = {mode: 0 for mode in sorted(DELIVERY_MODES)}
    for profile in validated["profiles"]:  # type: ignore[assignment]
        for capability in profile["capabilities"]:
            modes[capability["mode"]] += 1
    return {
        "selected": list(validated["selected"]),
        "modes": modes,
        "fully_automatic": modes["guided"] == 0 and modes["unavailable"] == 0,
    }


def build_receipt_for_ids(
    selected_ids: Sequence[str],
    *,
    detected_ids: Sequence[str],
    source: str,
    generated_at: datetime | str | None = None,
) -> dict[str, object]:
    """Resolve selected ids through the authoritative harness registry."""
    from core.harnesses import registry

    profiles: list[Mapping[str, object]] = []
    for profile_id in selected_ids:
        try:
            profile = registry.get_profile(profile_id)
        except KeyError as error:
            raise HarnessReceiptError(f"unknown harness profile: {profile_id}") from error
        payload = profile.to_dict()
        payload = {
            "id": payload["id"],
            "display_name": getattr(
                profile,
                "display_name",
                payload.get("display_name", payload.get("name", payload["id"])),
            ),
            "capabilities": profile.capability_rows(),
        }
        profiles.append(payload)
    known_ids = {profile.id for profile in registry.list_profiles()}
    unknown_detected = sorted(set(detected_ids) - known_ids)
    if unknown_detected:
        raise HarnessReceiptError(
            f"unknown detected harness profile: {unknown_detected[0]}"
        )
    return build_receipt(
        profiles,
        detected_ids=detected_ids,
        source=source,
        generated_at=generated_at,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selected-json", required=True)
    parser.add_argument("--detected-json", default="[]")
    parser.add_argument("--source", choices=sorted(SOURCES), required=True)
    args = parser.parse_args(argv)
    try:
        selected = json.loads(args.selected_json)
        detected = json.loads(args.detected_json)
        if not isinstance(selected, list) or not isinstance(detected, list):
            raise HarnessReceiptError("selected and detected values must be JSON arrays")
        receipt = build_receipt_for_ids(
            selected,
            detected_ids=detected,
            source=args.source,
        )
    except (json.JSONDecodeError, HarnessReceiptError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2
    print(canonical_receipt_bytes(receipt).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
