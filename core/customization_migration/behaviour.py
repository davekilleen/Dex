"""Closed behavioural-contract and verification records."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum

from core.customization_migration.model import CUSTOMIZATION_ID

BEHAVIOUR_ID = re.compile(r"^beh-[0-9a-f]{12}$")
OUTCOMES = frozenset({"pass", "fail", "unknown"})
REPORTED_STATUSES = frozenset(
    {"verified", "model-claimed-pass", "failed", "unknown"}
)
MAX_TEXT_CHARS = 2000


class ContractProvenance(str, Enum):
    DETERMINISTIC = "deterministic"
    USER_CONFIRMED = "user-confirmed"
    MODEL_PROPOSED = "model-proposed"


class VerificationClass(str, Enum):
    STATIC = "static"
    ISOLATED_FIXTURE = "isolated-fixture"
    READ_ONLY_LIVE = "read-only-live"
    MANUAL = "manual"
    UNSAFE_UNVERIFIED = "unsafe-unverified"


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "\0".join(parts).encode("utf-8")
    return f"{prefix}{hashlib.sha256(payload).hexdigest()[:12]}"


def _bounded_text(value: str, *, name: str, allow_empty: bool) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (not allow_empty and not value) or len(value) > MAX_TEXT_CHARS or "\x00" in value:
        qualifier = "possibly empty" if allow_empty else "non-empty"
        raise ValueError(
            f"{name} must be a {qualifier} string of at most "
            f"{MAX_TEXT_CHARS} characters without NUL"
        )


@dataclass(frozen=True)
class BehaviouralContract:
    contract_id: str
    customization_id: str
    statement: str
    provenance: ContractProvenance
    verification_class: VerificationClass

    def __post_init__(self) -> None:
        if (
            not isinstance(self.customization_id, str)
            or CUSTOMIZATION_ID.fullmatch(self.customization_id) is None
        ):
            raise ValueError("customization_id is not canonical")
        _bounded_text(self.statement, name="statement", allow_empty=False)
        if not isinstance(self.provenance, ContractProvenance):
            raise TypeError("provenance must be ContractProvenance")
        if not isinstance(self.verification_class, VerificationClass):
            raise TypeError("verification_class must be VerificationClass")
        expected_id = _stable_id(
            "beh-",
            self.customization_id,
            self.statement,
            self.provenance.value,
            self.verification_class.value,
        )
        if (
            not isinstance(self.contract_id, str)
            or BEHAVIOUR_ID.fullmatch(self.contract_id) is None
            or self.contract_id != expected_id
        ):
            raise ValueError(
                "contract_id does not match the behavioural contract fields"
            )

    @classmethod
    def create(
        cls,
        customization_id: str,
        statement: str,
        provenance: ContractProvenance,
        verification_class: VerificationClass,
    ) -> BehaviouralContract:
        return cls(
            _stable_id(
                "beh-",
                customization_id,
                statement,
                provenance.value,
                verification_class.value,
            ),
            customization_id,
            statement,
            provenance,
            verification_class,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "contract_id": self.contract_id,
            "customization_id": self.customization_id,
            "statement": self.statement,
            "provenance": self.provenance.value,
            "verification_class": self.verification_class.value,
        }


@dataclass(frozen=True)
class VerificationOutcome:
    contract_id: str
    outcome: str
    evidence_note: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.contract_id, str)
            or BEHAVIOUR_ID.fullmatch(self.contract_id) is None
        ):
            raise ValueError("contract_id is not canonical")
        if self.outcome not in OUTCOMES:
            raise ValueError("outcome must be pass, fail, or unknown")
        _bounded_text(
            self.evidence_note,
            name="evidence_note",
            allow_empty=True,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "contract_id": self.contract_id,
            "outcome": self.outcome,
            "evidence_note": self.evidence_note,
        }


def derive_reported_status(
    contract: BehaviouralContract,
    outcome: VerificationOutcome,
) -> str:
    """Return the only legal status for a contract and its outcome."""
    if type(contract) is not BehaviouralContract:
        raise TypeError("contract must be BehaviouralContract")
    if type(outcome) is not VerificationOutcome:
        raise TypeError("outcome must be VerificationOutcome")
    if contract.contract_id != outcome.contract_id:
        raise ValueError("verification outcome does not bind to the contract")
    if outcome.outcome == "fail":
        return "failed"
    if outcome.outcome == "unknown":
        return "unknown"
    if contract.provenance is ContractProvenance.MODEL_PROPOSED:
        return "model-claimed-pass"
    return "verified"


@dataclass(frozen=True)
class ReportedVerification:
    contract: BehaviouralContract
    outcome: VerificationOutcome
    status: str

    def __post_init__(self) -> None:
        if self.status not in REPORTED_STATUSES:
            raise ValueError("reported status is not in the closed vocabulary")
        expected = derive_reported_status(self.contract, self.outcome)
        if self.status != expected:
            raise ValueError(
                f"only legal reported status is {expected!r} for this evidence"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "contract": self.contract.to_dict(),
            "outcome": self.outcome.to_dict(),
            "status": self.status,
        }


__all__ = [
    "BehaviouralContract",
    "ContractProvenance",
    "ReportedVerification",
    "VerificationClass",
    "VerificationOutcome",
    "derive_reported_status",
]
