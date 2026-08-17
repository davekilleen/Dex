"""Closed runtime state for handing launchd jobs between Core and Dex Solo.

The sidecar is intentionally separate from the lifecycle ledger. Releases
predating this contract reject unknown ledger events, while this runtime file
can be ignored safely by old readers. Mutation remains owned by the lifecycle
service and transaction engine; this module only validates and models bytes.
"""

from __future__ import annotations

import hashlib
import json
import plistlib
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from core import portable_contract
from core.path_safety import unsafe_existing_parent

if TYPE_CHECKING:
    from core.transaction.engine import PlanEntry

SIDECAR_RELATIVE = portable_contract.AUTOMATION_OWNERSHIP_RELATIVE
SIDECAR_SCHEMA_VERSION = 1
SIDECAR_MAX_BYTES = portable_contract.AUTOMATION_OWNERSHIP_TRANSACTION_MAX_BYTES
OWNER_ID = "dex-solo"

_CLAIM_FIELDS = frozenset({"automation_id", "owner_id", "plist_relative_path", "plist_sha256"})
_CLAIM_REQUEST_FIELDS = _CLAIM_FIELDS | {"launchd_state"}
_RELEASE_REQUEST_FIELDS = frozenset({"automation_id", "owner_id", "scheduler_state"})
_ID = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AutomationOwnershipError(ValueError):
    """The sidecar request or evidence is unsafe or non-canonical."""


def _home_root() -> Path:
    return Path.home()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _canonical_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise AutomationOwnershipError(f"automation ownership {field} is not canonical")
    return value


def _owner(value: object) -> str:
    owner = _canonical_id(value, field="owner_id")
    if owner != OWNER_ID:
        raise AutomationOwnershipError("automation ownership is reserved for Dex Solo")
    return owner


def _plist_relative(value: object) -> str:
    if not isinstance(value, str):
        raise AutomationOwnershipError("automation plist path must be a canonical relative path")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or candidate.as_posix() != value
        or len(candidate.parts) != 3
        or candidate.parts[:2] != ("Library", "LaunchAgents")
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or not candidate.name.endswith(".plist")
        or _ID.fullmatch(candidate.name.removesuffix(".plist")) is None
    ):
        raise AutomationOwnershipError("automation plist path must be a canonical relative Library/LaunchAgents path")
    return value


def _sha256(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AutomationOwnershipError("automation plist sha256 must be lowercase hexadecimal")
    return value


def _claim(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _CLAIM_FIELDS:
        raise AutomationOwnershipError("automation claim has unsupported fields")
    return {
        "automation_id": _canonical_id(value.get("automation_id"), field="automation_id"),
        "owner_id": _owner(value.get("owner_id")),
        "plist_relative_path": _plist_relative(value.get("plist_relative_path")),
        "plist_sha256": _sha256(value.get("plist_sha256")),
    }


def _claim_request(value: object) -> tuple[dict[str, str], str]:
    if not isinstance(value, Mapping) or set(value) != _CLAIM_REQUEST_FIELDS:
        raise AutomationOwnershipError("automation claim request has unsupported fields")
    claim = _claim({field: value[field] for field in _CLAIM_FIELDS})
    state = value.get("launchd_state")
    if state != "unloaded":
        raise AutomationOwnershipError("launchd must be unloaded before Dex Solo records a claim")
    return claim, state


def _release_request(value: object) -> tuple[str, str, str]:
    if not isinstance(value, Mapping) or set(value) != _RELEASE_REQUEST_FIELDS:
        raise AutomationOwnershipError("automation release request has unsupported fields")
    automation_id = _canonical_id(value.get("automation_id"), field="automation_id")
    owner_id = _owner(value.get("owner_id"))
    scheduler_state = value.get("scheduler_state")
    if scheduler_state != "stopped":
        raise AutomationOwnershipError("Dex Solo scheduler must be stopped before release")
    return automation_id, owner_id, scheduler_state


def _state(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {"schema_version", "claims"}:
        raise AutomationOwnershipError("automation ownership sidecar has unsupported fields")
    if value.get("schema_version") != SIDECAR_SCHEMA_VERSION:
        raise AutomationOwnershipError("automation ownership sidecar schema version is unsupported")
    raw_claims = value.get("claims")
    if not isinstance(raw_claims, list):
        raise AutomationOwnershipError("automation ownership sidecar claims must be an array")
    claims = [_claim(item) for item in raw_claims]
    if claims != sorted(claims, key=lambda item: item["automation_id"]):
        raise AutomationOwnershipError("automation ownership claims are not in canonical order")
    ids = [item["automation_id"] for item in claims]
    paths = [item["plist_relative_path"] for item in claims]
    if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
        raise AutomationOwnershipError("automation ownership sidecar contains conflicting reuse")
    return {"schema_version": SIDECAR_SCHEMA_VERSION, "claims": claims}


def read_state(vault_root: str | Path) -> tuple[dict[str, object], str | None]:
    root = Path(vault_root)
    unsafe = unsafe_existing_parent(root, SIDECAR_RELATIVE)
    if unsafe is not None:
        raise AutomationOwnershipError(f"automation ownership sidecar: {unsafe}")
    target = root / SIDECAR_RELATIVE
    if not target.exists() and not target.is_symlink():
        return {"schema_version": SIDECAR_SCHEMA_VERSION, "claims": []}, None
    if target.is_symlink() or not target.is_file():
        raise AutomationOwnershipError("automation ownership sidecar must be a regular file")
    raw = target.read_bytes()
    if len(raw) > SIDECAR_MAX_BYTES:
        raise AutomationOwnershipError("automation ownership sidecar exceeds its size limit")
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AutomationOwnershipError("automation ownership sidecar is invalid JSON") from error
    state = _state(parsed)
    if raw != _canonical(state):
        raise AutomationOwnershipError("automation ownership sidecar is not canonical JSON")
    return state, hashlib.sha256(raw).hexdigest()


def _verified_plist(
    claim: Mapping[str, str],
    *,
    home_root: Path | None = None,
) -> None:
    home = home_root or _home_root()
    relative = claim["plist_relative_path"]
    unsafe = unsafe_existing_parent(home, relative)
    if unsafe is not None:
        raise AutomationOwnershipError(f"automation plist evidence is unsafe: {unsafe}")
    plist = home / relative
    if plist.is_symlink() or not plist.is_file():
        raise AutomationOwnershipError("automation plist evidence is missing or not a regular file")
    raw = plist.read_bytes()
    if hashlib.sha256(raw).hexdigest() != claim["plist_sha256"]:
        raise AutomationOwnershipError("automation plist evidence changed since preview")
    try:
        payload = plistlib.loads(raw)
    except Exception as error:  # plistlib exposes several parse error types
        raise AutomationOwnershipError("automation plist evidence is unreadable") from error
    if not isinstance(payload, Mapping) or payload.get("Label") != claim["automation_id"]:
        raise AutomationOwnershipError("automation plist Label does not match automation_id")
    if not claim["automation_id"].startswith(("com.dex.", "com.claudesidian.")):
        raise AutomationOwnershipError("automation claim is not for a shipped Dex launchd label")


def _sidecar_sha(state: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(state)).hexdigest()


def build_claim_preview(
    vault_root: str | Path,
    request: object,
) -> dict[str, object] | None:
    claim, launchd_state = _claim_request(request)
    state, current_sha = read_state(vault_root)
    claims = list(state["claims"])
    for existing in claims:
        if existing == claim:
            _verified_plist(claim)
            return None
        if (
            existing["automation_id"] == claim["automation_id"]
            or existing["plist_relative_path"] == claim["plist_relative_path"]
        ):
            raise AutomationOwnershipError("automation ownership claim has conflicting reuse")
    _verified_plist(claim)
    next_state = _state(
        {
            "schema_version": SIDECAR_SCHEMA_VERSION,
            "claims": sorted([*claims, claim], key=lambda item: item["automation_id"]),
        }
    )
    return {
        "automation_ownership_version": 1,
        "operation": "claim",
        "claim": claim,
        "launchd_state": launchd_state,
        "current_sidecar_sha256": current_sha,
        "next_sidecar_sha256": _sidecar_sha(next_state),
    }


def build_release_preview(
    vault_root: str | Path,
    request: object,
) -> dict[str, object] | None:
    automation_id, owner_id, scheduler_state = _release_request(request)
    state, current_sha = read_state(vault_root)
    claims = list(state["claims"])
    existing = next((item for item in claims if item["automation_id"] == automation_id), None)
    if existing is None:
        return None
    if existing["owner_id"] != owner_id:
        raise AutomationOwnershipError("automation ownership release names a foreign owner")
    _verified_plist(existing)
    next_state = _state(
        {
            "schema_version": SIDECAR_SCHEMA_VERSION,
            "claims": [item for item in claims if item["automation_id"] != automation_id],
        }
    )
    return {
        "automation_ownership_version": 1,
        "operation": "release",
        "claim": existing,
        "scheduler_state": scheduler_state,
        "current_sidecar_sha256": current_sha,
        "next_sidecar_sha256": _sidecar_sha(next_state),
    }


def _plan(
    vault_root: str | Path,
    preview: Mapping[str, object],
) -> tuple[PlanEntry | None, str]:
    from core.transaction.engine import PlanEntry

    if preview.get("automation_ownership_version") != 1:
        raise AutomationOwnershipError("automation ownership preview version is unsupported")
    operation = preview.get("operation")
    claim = preview.get("claim")
    if operation == "claim":
        if set(preview) != {
            "automation_ownership_version",
            "operation",
            "claim",
            "launchd_state",
            "current_sidecar_sha256",
            "next_sidecar_sha256",
        }:
            raise AutomationOwnershipError("automation claim preview has unsupported fields")
        rebuilt = build_claim_preview(
            vault_root,
            {**dict(_claim(claim)), "launchd_state": preview.get("launchd_state")},
        )
        if rebuilt is None:
            _state_now, current_sha = read_state(vault_root)
            if current_sha != preview.get("next_sidecar_sha256"):
                raise AutomationOwnershipError("automation ownership state changed since preview")
            return None, "already-claimed"
        status = "claimed"
    elif operation == "release":
        if set(preview) != {
            "automation_ownership_version",
            "operation",
            "claim",
            "scheduler_state",
            "current_sidecar_sha256",
            "next_sidecar_sha256",
        }:
            raise AutomationOwnershipError("automation release preview has unsupported fields")
        modeled = _claim(claim)
        rebuilt = build_release_preview(
            vault_root,
            {
                "automation_id": modeled["automation_id"],
                "owner_id": modeled["owner_id"],
                "scheduler_state": preview.get("scheduler_state"),
            },
        )
        if rebuilt is None:
            _state_now, current_sha = read_state(vault_root)
            if current_sha != preview.get("next_sidecar_sha256"):
                raise AutomationOwnershipError("automation ownership state changed since preview")
            return None, "already-released"
        status = "released"
    else:
        raise AutomationOwnershipError("automation ownership preview operation is invalid")
    if dict(preview) != rebuilt:
        raise AutomationOwnershipError("automation ownership state changed since preview")

    state, current_sha = read_state(vault_root)
    modeled_claim = _claim(claim)
    claims = list(state["claims"])
    next_claims = (
        sorted([*claims, modeled_claim], key=lambda item: item["automation_id"])
        if operation == "claim"
        else [item for item in claims if item["automation_id"] != modeled_claim["automation_id"]]
    )
    content = _canonical(_state({"schema_version": SIDECAR_SCHEMA_VERSION, "claims": next_claims}))
    return (
        PlanEntry(
            SIDECAR_RELATIVE,
            content,
            mode=0o600,
            expected_current_sha256=current_sha,
            expected_absent=current_sha is None,
        ),
        status,
    )


def execution_plan(
    vault_root: str | Path,
    preview: Mapping[str, object],
) -> tuple[PlanEntry | None, str]:
    if not isinstance(preview, Mapping):
        raise AutomationOwnershipError("automation ownership preview must be an object")
    return _plan(vault_root, preview)


def valid_claims(
    vault_root: str | Path,
    *,
    home_root: Path | None = None,
) -> tuple[dict[str, str], ...]:
    """Return only claims whose current plist still matches the sealed evidence."""
    try:
        state, _sha = read_state(vault_root)
    except AutomationOwnershipError:
        return ()
    valid: list[dict[str, str]] = []
    for claim in state["claims"]:
        try:
            _verified_plist(claim, home_root=home_root)
        except AutomationOwnershipError:
            continue
        valid.append(claim)
    return tuple(valid)


def is_plist_offloaded(
    vault_root: str | Path,
    plist_relative_path: str,
    *,
    home_root: Path | None = None,
) -> bool:
    try:
        relative = _plist_relative(plist_relative_path)
    except AutomationOwnershipError:
        return False
    return any(claim["plist_relative_path"] == relative for claim in valid_claims(vault_root, home_root=home_root))


__all__ = [
    "AutomationOwnershipError",
    "OWNER_ID",
    "SIDECAR_RELATIVE",
    "SIDECAR_SCHEMA_VERSION",
    "build_claim_preview",
    "build_release_preview",
    "execution_plan",
    "is_plist_offloaded",
    "read_state",
    "valid_claims",
]
