"""Read-only-first verification for privately staged regeneration candidates.

Staged bytes are parsed and compared but never imported, invoked, registered,
or run against the real vault or network. The optional fixture and
read-only-live rungs remain explicit seams; when no safe runner or consent
token exists they collapse to ``unsafe-unverified`` rather than being
silently promoted. Model-proposed provenance can therefore never become
``verified`` (A3).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from core import portable_contract
from core.customization_migration.behaviour import (
    BehaviouralContract,
    ContractProvenance,
    ReportedVerification,
    VerificationClass,
    VerificationOutcome,
    derive_reported_status,
)
from core.customization_migration.capsule import CAPSULE_ROOT
from core.customization_migration.model import SHA256
from core.customization_migration.planning import (
    CandidateFile,
    Disposition,
    RegenerationCandidate,
)
from core.customization_migration.staging import (
    STAGING_SUBDIR,
    StagingError,
    _append_event,
    _assessment_from_capsule,
    _open_directory_beneath,
    _read_event_records_beneath,
    _read_regular_beneath,
    _sha256,
    _validate_candidate_against_capsule,
    load_staged_candidate,
    read_staging_status,
    validate_staging,
)
from core.customization_migration.state import (
    MigrationEvent,
    MigrationState,
)
from core.transaction.engine import PlanEntry, Transaction

_OUTCOMES = frozenset({"pass", "fail", "unknown"})
_REPORT_VERDICTS = frozenset({"OK", "BLOCKED", "UNKNOWN"})
_REGISTERED_STATIC_STATEMENT = (
    "The required static verification ladder proves the staged candidate's "
    "schema, paths, bytes, modes, dependency closure, syntax, release "
    "compatibility, trust requirements, and capsule isolation."
)
_MAX_LIVE_INODE_SCAN_ENTRIES = 100_000
_REQUIRED_STATIC_CHECKS = (
    "schema",
    "canonical-path",
    "ownership-authorization",
    "content-digest",
    "mode",
    "dependency-closure",
    "syntax",
    "target-release-compatibility",
    "trust-permission-delta",
    "private-staging",
)


class VerificationError(RuntimeError):
    """A staged verification or report write refused to proceed safely."""


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _closed_object(
    value: object,
    *,
    keys: frozenset[str],
    context: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or frozenset(value) != keys:
        raise VerificationError(f"{context} is not a closed object")
    return value


def _closed_list(value: object, *, context: str) -> list[object]:
    if not isinstance(value, list):
        raise VerificationError(f"{context} must be a list")
    return value


@dataclass(frozen=True)
class VerificationCheckOutcome:
    name: str
    verification_class: VerificationClass
    outcome: str
    detail: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or not self.name
            or len(self.name) > 128
            or "\x00" in self.name
        ):
            raise ValueError("verification check name is invalid")
        if not isinstance(self.verification_class, VerificationClass):
            raise TypeError("verification_class must reuse VerificationClass")
        if self.outcome not in _OUTCOMES:
            raise ValueError("verification check outcome is invalid")
        if (
            not isinstance(self.detail, str)
            or not self.detail
            or len(self.detail) > 2000
            or "\x00" in self.detail
        ):
            raise ValueError("verification check detail is invalid")

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "verification_class": self.verification_class.value,
            "outcome": self.outcome,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class StaticFileResult:
    target_path: str
    staged_path: str
    checks: tuple[VerificationCheckOutcome, ...]
    status: str

    def __post_init__(self) -> None:
        for name, value in (
            ("target_path", self.target_path),
            ("staged_path", self.staged_path),
        ):
            if not isinstance(value, str) or not value or "\x00" in value:
                raise ValueError(f"static result {name} is invalid")
        if not isinstance(self.checks, tuple) or any(
            type(item) is not VerificationCheckOutcome for item in self.checks
        ):
            raise TypeError("static result checks must be VerificationCheckOutcome")
        if len({item.name for item in self.checks}) != len(self.checks):
            raise ValueError("static result check names must be unique")
        expected = (
            "BLOCKED"
            if any(item.outcome == "fail" for item in self.checks)
            else "UNKNOWN"
            if any(item.outcome == "unknown" for item in self.checks)
            else "OK"
        )
        if self.status != expected:
            raise ValueError("static result status contradicts its checks")

    def to_dict(self) -> dict[str, object]:
        return {
            "target_path": self.target_path,
            "staged_path": self.staged_path,
            "checks": [item.to_dict() for item in self.checks],
            "status": self.status,
        }


@dataclass(frozen=True)
class VerificationAttempt:
    """Closed result shape for optional fixture/live/manual runner seams."""

    requested_class: VerificationClass
    effective_class: VerificationClass
    outcome: str
    executed: bool
    evidence_note: str

    def __post_init__(self) -> None:
        if not isinstance(self.requested_class, VerificationClass):
            raise TypeError("requested_class must reuse VerificationClass")
        if not isinstance(self.effective_class, VerificationClass):
            raise TypeError("effective_class must reuse VerificationClass")
        if self.outcome not in _OUTCOMES:
            raise ValueError("verification attempt outcome is invalid")
        if type(self.executed) is not bool:
            raise TypeError("verification attempt executed must be boolean")
        if (
            not isinstance(self.evidence_note, str)
            or not self.evidence_note
            or len(self.evidence_note) > 2000
            or "\x00" in self.evidence_note
        ):
            raise ValueError("verification attempt evidence_note is invalid")
        if (
            not self.executed
            and self.effective_class is not VerificationClass.UNSAFE_UNVERIFIED
        ):
            raise ValueError(
                "an unexercised attempt must remain unsafe-unverified"
            )


@dataclass(frozen=True)
class VerificationReport:
    schema_version: int
    staging_id: str
    capsule_id: str
    proposal_id: str
    candidate_sha256: str
    static_results: tuple[StaticFileResult, ...]
    reported_verifications: tuple[ReportedVerification, ...]
    verdict: str
    staged_paths_private: bool
    writes_confined_to_capsule: bool
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != 0:
            raise ValueError("unsupported verification report schema_version")
        if self.staging_id != self.proposal_id:
            raise ValueError("v0 staging_id must be the proposal id")
        if (
            not isinstance(self.capsule_id, str)
            or not self.capsule_id.startswith("cap-")
            or "/" in self.capsule_id
            or not isinstance(self.proposal_id, str)
            or not self.proposal_id.startswith("prop-")
            or "/" in self.proposal_id
        ):
            raise ValueError("verification report identity is invalid")
        if (
            not isinstance(self.candidate_sha256, str)
            or SHA256.fullmatch(self.candidate_sha256) is None
        ):
            raise ValueError("candidate_sha256 must be canonical")
        if not isinstance(self.static_results, tuple) or any(
            type(item) is not StaticFileResult for item in self.static_results
        ):
            raise TypeError("static_results must be StaticFileResult records")
        if tuple(
            sorted(self.static_results, key=lambda item: item.target_path)
        ) != self.static_results:
            raise ValueError("static_results must be sorted")
        if not isinstance(self.reported_verifications, tuple) or any(
            type(item) is not ReportedVerification
            for item in self.reported_verifications
        ):
            raise TypeError(
                "reported_verifications must be ReportedVerification records"
            )
        if tuple(
            sorted(
                self.reported_verifications,
                key=lambda item: item.contract.contract_id,
            )
        ) != self.reported_verifications:
            raise ValueError("reported_verifications must be sorted")
        if self.verdict not in _REPORT_VERDICTS:
            raise ValueError("verification report verdict is invalid")
        if type(self.staged_paths_private) is not bool:
            raise TypeError("staged_paths_private must be boolean")
        if type(self.writes_confined_to_capsule) is not bool:
            raise TypeError("writes_confined_to_capsule must be boolean")
        if (
            not isinstance(self.notes, tuple)
            or tuple(sorted(set(self.notes))) != self.notes
            or any(not isinstance(item, str) or not item for item in self.notes)
        ):
            raise ValueError("verification report notes must be sorted unique text")
        if self.verdict == "OK" and (
            not self.staged_paths_private
            or not self.writes_confined_to_capsule
            or any(item.status != "OK" for item in self.static_results)
            or any(
                item.status != "verified"
                for item in self.reported_verifications
            )
        ):
            raise ValueError("OK verification report contradicts its evidence")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "staging_id": self.staging_id,
            "capsule_id": self.capsule_id,
            "proposal_id": self.proposal_id,
            "candidate_sha256": self.candidate_sha256,
            "static_results": [item.to_dict() for item in self.static_results],
            "reported_verifications": [
                item.to_dict() for item in self.reported_verifications
            ],
            "verdict": self.verdict,
            "staged_paths_private": self.staged_paths_private,
            "writes_confined_to_capsule": self.writes_confined_to_capsule,
            "notes": list(self.notes),
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.to_dict())


def _contract_from_report(value: object) -> BehaviouralContract:
    item = _closed_object(
        value,
        keys=frozenset(
            {
                "contract_id",
                "customization_id",
                "statement",
                "provenance",
                "verification_class",
            }
        ),
        context="reported contract",
    )
    try:
        return BehaviouralContract(
            item["contract_id"],
            item["customization_id"],
            item["statement"],
            ContractProvenance(item["provenance"]),
            VerificationClass(item["verification_class"]),
        )
    except (TypeError, ValueError) as error:
        raise VerificationError("reported contract is invalid") from error


def verification_report_from_bytes(raw: bytes) -> VerificationReport:
    """Parse one canonical, schema-closed persisted report."""
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError("verification report is not JSON") from error
    if _canonical_json(value) != raw:
        raise VerificationError("verification report is not canonical")
    item = _closed_object(
        value,
        keys=frozenset(
            {
                "schema_version",
                "staging_id",
                "capsule_id",
                "proposal_id",
                "candidate_sha256",
                "static_results",
                "reported_verifications",
                "verdict",
                "staged_paths_private",
                "writes_confined_to_capsule",
                "notes",
            }
        ),
        context="verification report",
    )
    static_results: list[StaticFileResult] = []
    for raw_result in _closed_list(
        item["static_results"],
        context="static_results",
    ):
        result = _closed_object(
            raw_result,
            keys=frozenset(
                {"target_path", "staged_path", "checks", "status"}
            ),
            context="static result",
        )
        checks: list[VerificationCheckOutcome] = []
        for raw_check in _closed_list(
            result["checks"],
            context="static checks",
        ):
            check = _closed_object(
                raw_check,
                keys=frozenset(
                    {"name", "verification_class", "outcome", "detail"}
                ),
                context="static check",
            )
            try:
                checks.append(
                    VerificationCheckOutcome(
                        check["name"],
                        VerificationClass(check["verification_class"]),
                        check["outcome"],
                        check["detail"],
                    )
                )
            except (TypeError, ValueError) as error:
                raise VerificationError("static check is invalid") from error
        try:
            static_results.append(
                StaticFileResult(
                    result["target_path"],
                    result["staged_path"],
                    tuple(checks),
                    result["status"],
                )
            )
        except (TypeError, ValueError) as error:
            raise VerificationError("static result is invalid") from error

    reported: list[ReportedVerification] = []
    for raw_reported in _closed_list(
        item["reported_verifications"],
        context="reported_verifications",
    ):
        reported_item = _closed_object(
            raw_reported,
            keys=frozenset({"contract", "outcome", "status"}),
            context="reported verification",
        )
        contract = _contract_from_report(reported_item["contract"])
        outcome_item = _closed_object(
            reported_item["outcome"],
            keys=frozenset({"contract_id", "outcome", "evidence_note"}),
            context="reported outcome",
        )
        try:
            outcome = VerificationOutcome(
                outcome_item["contract_id"],
                outcome_item["outcome"],
                outcome_item["evidence_note"],
            )
            reported.append(
                ReportedVerification(
                    contract,
                    outcome,
                    reported_item["status"],
                )
            )
        except (TypeError, ValueError) as error:
            raise VerificationError(
                "reported verification is invalid"
            ) from error
    try:
        report = VerificationReport(
            item["schema_version"],
            item["staging_id"],
            item["capsule_id"],
            item["proposal_id"],
            item["candidate_sha256"],
            tuple(static_results),
            tuple(reported),
            item["verdict"],
            item["staged_paths_private"],
            item["writes_confined_to_capsule"],
            tuple(
                _closed_list(
                    item["notes"],
                    context="verification notes",
                )
            ),
        )
    except (TypeError, ValueError) as error:
        raise VerificationError("verification report is invalid") from error
    if report.canonical_bytes() != raw:
        raise VerificationError("verification report did not round-trip")
    return report


@dataclass(frozen=True)
class VerificationWriteReceipt:
    schema_version: int
    capsule_id: str
    staging_id: str
    report_path: str
    report_sha256: str
    transaction_id: str

    def __post_init__(self) -> None:
        if self.schema_version != 0:
            raise ValueError("unsupported verification receipt schema_version")
        if not self.report_path.startswith(
            f"{CAPSULE_ROOT}/{self.capsule_id}/verification/"
        ):
            raise ValueError("verification receipt report path escapes capsule")
        if not isinstance(self.report_sha256, str) or SHA256.fullmatch(
            self.report_sha256
        ) is None:
            raise ValueError("verification receipt report_sha256 is invalid")
        if (
            not isinstance(self.transaction_id, str)
            or not self.transaction_id
            or "/" in self.transaction_id
            or "\x00" in self.transaction_id
        ):
            raise ValueError("verification receipt transaction_id is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capsule_id": self.capsule_id,
            "staging_id": self.staging_id,
            "report_path": self.report_path,
            "report_sha256": self.report_sha256,
            "transaction_id": self.transaction_id,
        }


@dataclass(frozen=True)
class _StaticContext:
    root: Path
    staging: Path
    capsule_dir: Path
    candidate: RegenerationCandidate
    candidate_file: CandidateFile
    staged_path: Path
    staged_relative: str
    staging_integrity_error: str | None
    dependency_error: str | None


def _check(
    name: str,
    passed: bool,
    success: str,
    failure: str,
) -> VerificationCheckOutcome:
    return VerificationCheckOutcome(
        name,
        VerificationClass.STATIC,
        "pass" if passed else "fail",
        success if passed else failure,
    )


def _schema_check(context: _StaticContext) -> VerificationCheckOutcome:
    return _check(
        "schema",
        type(context.candidate) is RegenerationCandidate
        and type(context.candidate_file) is CandidateFile
        and context.staging_integrity_error is None,
        "The canonical v0 candidate schema was reconstructed.",
        context.staging_integrity_error
        or "The staged candidate schema is not the closed v0 shape.",
    )


def _canonical_path_check(context: _StaticContext) -> VerificationCheckOutcome:
    target = context.candidate_file.target_path
    path = PurePosixPath(target)
    canonical = (
        not path.is_absolute()
        and path.as_posix() == target
        and all(part not in {"", ".", ".."} for part in path.parts)
    )
    return _check(
        "canonical-path",
        canonical,
        "The eventual target is canonical and vault-relative.",
        f"The eventual target is not canonical: {target}",
    )


def _ownership_check(context: _StaticContext) -> VerificationCheckOutcome:
    target = context.root / context.candidate_file.target_path
    if target.is_symlink():
        return _check(
            "ownership-authorization",
            False,
            "",
            "The eventual target is a symlink and cannot receive migration bytes.",
        )
    verdict = portable_contract.update_write_verdict(
        context.candidate_file.target_path,
        exists=target.exists(),
        operation="customization-migration",
    )
    return _check(
        "ownership-authorization",
        verdict.allowed,
        "The single customization-migration write authority allows the target.",
        "The ownership contract refuses the eventual target: "
        f"{context.candidate_file.target_path} [{verdict.action}]",
    )


def _content_check(context: _StaticContext) -> VerificationCheckOutcome:
    try:
        raw = _read_regular_beneath(
            context.root,
            context.staged_relative,
            len(context.candidate_file.content),
        )
    except (OSError, StagingError):
        return _check(
            "content-digest",
            False,
            "",
            f"The staged blob is missing or unreadable: {context.staged_path.name}",
        )
    passed = (
        raw == context.candidate_file.content
        and _sha256(raw) == context.candidate_file.sha256
    )
    return _check(
        "content-digest",
        passed,
        "The staged bytes exactly match the candidate digest.",
        f"The staged bytes do not match: {context.staged_path.name}",
    )


def _mode_check(context: _StaticContext) -> VerificationCheckOutcome:
    try:
        parent_relative = PurePosixPath(
            context.staged_relative
        ).parent.as_posix()
        parent = _open_directory_beneath(context.root, parent_relative)
        try:
            descriptor = os.open(
                PurePosixPath(context.staged_relative).name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent,
            )
        finally:
            os.close(parent)
        try:
            metadata = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        passed = (
            stat.S_ISREG(metadata.st_mode)
            and not stat.S_ISLNK(metadata.st_mode)
            and stat.S_IMODE(metadata.st_mode) == 0o600
        )
    except OSError:
        passed = False
    return _check(
        "mode",
        passed,
        "The staged blob remains a regular 0600 file.",
        f"The staged blob is not a regular 0600 file: {context.staged_path.name}",
    )


def _dependency_check(context: _StaticContext) -> VerificationCheckOutcome:
    return _check(
        "dependency-closure",
        context.dependency_error is None,
        "The candidate remains closed over the capsule's frozen dependencies.",
        context.dependency_error or "The frozen dependency check failed.",
    )


def _syntax_check(context: _StaticContext) -> VerificationCheckOutcome:
    target = context.candidate_file.target_path
    suffix = PurePosixPath(target).suffix.lower()
    try:
        raw = _read_regular_beneath(
            context.root,
            context.staged_relative,
            len(context.candidate_file.content),
        )
        if suffix == ".py":
            compile(raw.decode("utf-8"), target, "exec", dont_inherit=True)
        elif suffix == ".json":
            json.loads(raw.decode("utf-8"))
        elif suffix in {".yaml", ".yml"}:
            yaml.safe_load(raw.decode("utf-8"))
    except (OSError, StagingError, SyntaxError, UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError):
        return _check(
            "syntax",
            False,
            "",
            f"The staged bytes fail static {suffix or 'text'} parsing: {target}",
        )
    return _check(
        "syntax",
        True,
        "Relevant Python, JSON, or YAML syntax parses without execution.",
        "",
    )


def _release_check(context: _StaticContext) -> VerificationCheckOutcome:
    verdict = portable_contract.update_write_verdict(
        context.candidate_file.target_path,
        exists=False,
        operation="customization-migration",
    )
    return _check(
        "target-release-compatibility",
        verdict.allowed,
        "The target path still classifies in the current release contract.",
        "The target path no longer classifies for customization migration.",
    )


def _trust_permission_check(
    context: _StaticContext,
) -> VerificationCheckOutcome:
    requirements = tuple(
        requirement
        for requirement in context.candidate.declared_requirements
        if set(requirement.customization_ids)
        & set(context.candidate_file.customization_ids)
    )
    return _check(
        "trust-permission-delta",
        not requirements,
        "No new trust or permission requirement is declared for this file.",
        "The candidate declares a new trust or permission requirement: "
        + ", ".join(item.description for item in requirements),
    )


def _private_staging_check(context: _StaticContext) -> VerificationCheckOutcome:
    try:
        capsule_relative = context.capsule_dir.relative_to(
            context.root
        ).as_posix()
        private = context.staged_relative.startswith(
            capsule_relative + "/"
        )
        parent = _open_directory_beneath(
            context.root,
            PurePosixPath(context.staged_relative).parent.as_posix(),
        )
        try:
            descriptor = os.open(
                PurePosixPath(context.staged_relative).name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent,
            )
        finally:
            os.close(parent)
        try:
            staged_metadata = os.fstat(descriptor)
            private = private and stat.S_ISREG(staged_metadata.st_mode)
        finally:
            os.close(descriptor)
    except (OSError, ValueError, StagingError):
        private = False
    live_target = context.root / context.candidate_file.target_path
    try:
        live_metadata = live_target.lstat()
        private = private and (
            not stat.S_ISLNK(live_metadata.st_mode)
            and (
                staged_metadata.st_dev != live_metadata.st_dev
                or staged_metadata.st_ino != live_metadata.st_ino
            )
        )
    except FileNotFoundError:
        private = private and not live_target.is_symlink()
    except OSError:
        private = False
    return _check(
        "private-staging",
        private,
        "The staged blob is capsule-private and is not its live target path.",
        "A staged blob aliases or escapes to a live vault path.",
    )


_STATIC_CHECK_RUNNERS = {
    "schema": _schema_check,
    "canonical-path": _canonical_path_check,
    "ownership-authorization": _ownership_check,
    "content-digest": _content_check,
    "mode": _mode_check,
    "dependency-closure": _dependency_check,
    "syntax": _syntax_check,
    "target-release-compatibility": _release_check,
    "trust-permission-delta": _trust_permission_check,
    "private-staging": _private_staging_check,
}


def _static_results(
    root: Path,
    staging: Path,
    candidate: RegenerationCandidate,
) -> tuple[StaticFileResult, ...]:
    try:
        _validate_candidate_against_capsule(root, candidate.capsule_id, candidate)
    except (OSError, StagingError) as error:
        dependency_error = f"Frozen candidate validation failed: {error}"
    else:
        dependency_error = None
    try:
        assessment, _digest = _assessment_from_capsule(
            root,
            candidate.capsule_id,
        )
    except (OSError, StagingError) as error:
        dependency_error = (
            dependency_error
            or f"Frozen assessment reconstruction failed: {error}"
        )
    else:
        blocked_ids = {
            item.customization_id
            for item in assessment.groups
            if item.group.value == "blocked"
        }
        generated_ids = {
            item.customization_id
            for item in candidate.dispositions
            if item.disposition
            in {Disposition.REWRITE, Disposition.COMPATIBILITY_SHIM}
        }
        blocked_generated = tuple(sorted(blocked_ids & generated_ids))
        if blocked_generated:
            dependency_error = (
                "Frozen capsule evidence classified generated customization "
                "as blocked: "
                + ", ".join(blocked_generated)
            )
    staging_validation = validate_staging(
        root,
        candidate.capsule_id,
        candidate.proposal_id,
    )
    staging_integrity_error = (
        None
        if staging_validation.status == "OK"
        else (
            "Private staging integrity is "
            f"{staging_validation.status}: "
            + ", ".join(staging_validation.mismatches)
        )
    )
    capsule_dir = root / CAPSULE_ROOT / candidate.capsule_id
    results: list[StaticFileResult] = []
    for candidate_file in candidate.files:
        staged_path = staging / "files" / candidate_file.sha256
        staged_relative = staged_path.relative_to(root).as_posix()
        context = _StaticContext(
            root,
            staging,
            capsule_dir,
            candidate,
            candidate_file,
            staged_path,
            staged_relative,
            staging_integrity_error,
            dependency_error,
        )
        checks: list[VerificationCheckOutcome] = []
        for name in _REQUIRED_STATIC_CHECKS:
            runner = _STATIC_CHECK_RUNNERS.get(name)
            if runner is None:
                checks.append(
                    VerificationCheckOutcome(
                        name,
                        VerificationClass.STATIC,
                        "fail",
                        f"Required static check is disabled: {name}",
                    )
                )
                continue
            try:
                checks.append(runner(context))
            except Exception as error:  # noqa: BLE001 - fail closed per check
                checks.append(
                    VerificationCheckOutcome(
                        name,
                        VerificationClass.STATIC,
                        "fail",
                        f"Required static check failed closed: {type(error).__name__}",
                    )
                )
        ordered = tuple(checks)
        status = (
            "BLOCKED"
            if any(item.outcome == "fail" for item in ordered)
            else "UNKNOWN"
            if any(item.outcome == "unknown" for item in ordered)
            else "OK"
        )
        results.append(
            StaticFileResult(
                candidate_file.target_path,
                (
                    STAGING_SUBDIR.format(proposal_id=candidate.proposal_id)
                    + f"/files/{candidate_file.sha256}"
                ),
                ordered,
                status,
            )
        )
    return tuple(sorted(results, key=lambda item: item.target_path))


def _run_isolated_fixture(
    contract: BehaviouralContract,
    candidate: RegenerationCandidate,
    staging: Path,
) -> VerificationAttempt:
    """Optional v0 runner seam; no candidate code is run without a safe harness."""
    del contract, candidate, staging
    return VerificationAttempt(
        VerificationClass.ISOLATED_FIXTURE,
        VerificationClass.UNSAFE_UNVERIFIED,
        "unknown",
        False,
        (
            "unsafe-unverified: no closed synthetic fixture harness exists "
            "for this customization kind."
        ),
    )


def _unexercised_attempt(
    requested: VerificationClass,
    note: str,
) -> VerificationAttempt:
    return VerificationAttempt(
        requested,
        VerificationClass.UNSAFE_UNVERIFIED,
        "unknown",
        False,
        f"unsafe-unverified: {note}",
    )


def _attempt_for_contract(
    contract: BehaviouralContract,
    candidate: RegenerationCandidate,
    staging: Path,
    static_results: tuple[StaticFileResult, ...],
) -> VerificationAttempt:
    if contract.verification_class is VerificationClass.STATIC:
        static_passed = bool(static_results) and all(
            item.status == "OK" for item in static_results
        )
        return VerificationAttempt(
            VerificationClass.STATIC,
            VerificationClass.STATIC,
            "pass" if static_passed else "fail",
            True,
            (
                "All required deterministic static checks passed."
                if static_passed
                else "One or more required deterministic static checks failed."
            ),
        )
    if contract.verification_class is VerificationClass.ISOLATED_FIXTURE:
        return _run_isolated_fixture(contract, candidate, staging)
    if contract.verification_class is VerificationClass.READ_ONLY_LIVE:
        return _unexercised_attempt(
            VerificationClass.READ_ONLY_LIVE,
            "read-only-live verification requires a fresh explicit consent token.",
        )
    if contract.verification_class is VerificationClass.MANUAL:
        return _unexercised_attempt(
            VerificationClass.MANUAL,
            "manual verification was recorded but cannot be auto-promoted.",
        )
    return _unexercised_attempt(
        VerificationClass.UNSAFE_UNVERIFIED,
        "the declared behaviour cannot be exercised safely in v0.",
    )


def _trusted_contract(
    candidate_contract: BehaviouralContract,
) -> BehaviouralContract:
    registered = BehaviouralContract.create(
        candidate_contract.customization_id,
        _REGISTERED_STATIC_STATEMENT,
        ContractProvenance.DETERMINISTIC,
        VerificationClass.STATIC,
    )
    if candidate_contract == registered:
        return candidate_contract
    return BehaviouralContract.create(
        candidate_contract.customization_id,
        candidate_contract.statement,
        ContractProvenance.MODEL_PROPOSED,
        candidate_contract.verification_class,
    )


def _reported_verifications(
    candidate: RegenerationCandidate,
    staging: Path,
    static_results: tuple[StaticFileResult, ...],
) -> tuple[tuple[ReportedVerification, ...], tuple[VerificationAttempt, ...]]:
    reported: list[ReportedVerification] = []
    attempts: list[VerificationAttempt] = []
    for candidate_contract in candidate.behaviour_contracts:
        contract = _trusted_contract(candidate_contract)
        attempt = _attempt_for_contract(
            contract,
            candidate,
            staging,
            static_results,
        )
        outcome = VerificationOutcome(
            contract.contract_id,
            attempt.outcome,
            attempt.evidence_note,
        )
        reported.append(
            ReportedVerification(
                contract,
                outcome,
                derive_reported_status(contract, outcome),
            )
        )
        attempts.append(attempt)
    return (
        tuple(sorted(reported, key=lambda item: item.contract.contract_id)),
        tuple(attempts),
    )


def validate_persisted_verification_report(
    raw: bytes,
    candidate: RegenerationCandidate,
    event: str,
) -> VerificationReport:
    """Validate the full persisted report seal against its staged candidate."""
    report = verification_report_from_bytes(raw)
    if (
        report.capsule_id != candidate.capsule_id
        or report.proposal_id != candidate.proposal_id
        or report.staging_id != candidate.proposal_id
        or report.candidate_sha256 != candidate.candidate_sha256
    ):
        raise VerificationError(
            "verification report identity does not match staging"
        )
    expected_targets = tuple(item.target_path for item in candidate.files)
    if tuple(item.target_path for item in report.static_results) != expected_targets:
        raise VerificationError(
            "verification report static results do not cover candidate files"
        )
    for result in report.static_results:
        if tuple(check.name for check in result.checks) != _REQUIRED_STATIC_CHECKS:
            raise VerificationError(
                "verification report static ladder is incomplete"
            )
        if any(
            check.verification_class is not VerificationClass.STATIC
            for check in result.checks
        ):
            raise VerificationError(
                "verification report static ladder has the wrong class"
            )
    expected_contracts = tuple(
        sorted(
            (
                _trusted_contract(contract)
                for contract in candidate.behaviour_contracts
            ),
            key=lambda contract: contract.contract_id,
        )
    )
    if tuple(
        item.contract for item in report.reported_verifications
    ) != expected_contracts:
        raise VerificationError(
            "verification report contracts do not match trusted semantics"
        )
    expected_event = (
        MigrationEvent.VERIFICATION_PASSED.value
        if report.verdict == "OK"
        else MigrationEvent.VERIFICATION_BLOCKED.value
    )
    if event != expected_event:
        raise VerificationError(
            "verification report verdict contradicts its journal event"
        )
    return report


def _unknown_report(capsule_id: str, proposal_id: str, note: str) -> VerificationReport:
    return VerificationReport(
        0,
        proposal_id,
        capsule_id,
        proposal_id,
        "0" * 64,
        (),
        (),
        "UNKNOWN",
        False,
        True,
        (note,),
    )


def _staged_paths_are_private(
    root: Path,
    capsule_dir: Path,
    staging: Path,
    candidate: RegenerationCandidate,
) -> bool:
    del capsule_dir
    staged_inodes: set[tuple[int, int]] = set()
    for item in candidate.files:
        staged = staging / "files" / item.sha256
        try:
            relative = staged.relative_to(root).as_posix()
            parent = _open_directory_beneath(
                root,
                PurePosixPath(relative).parent.as_posix(),
            )
            try:
                descriptor = os.open(
                    PurePosixPath(relative).name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent,
                )
            finally:
                os.close(parent)
            try:
                metadata = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                return False
            staged_inodes.add((metadata.st_dev, metadata.st_ino))
        except (OSError, ValueError, StagingError):
            return False
    if not staged_inodes:
        return True

    excluded_roots = {
        CAPSULE_ROOT,
        "System/.dex/tx",
    }
    scanned = 0

    def scan_directory(descriptor: int, prefix: str) -> bool:
        nonlocal scanned
        try:
            names = sorted(os.listdir(descriptor))
        except OSError:
            return False
        for name in names:
            scanned += 1
            if scanned > _MAX_LIVE_INODE_SCAN_ENTRIES:
                return False
            relative = f"{prefix}/{name}" if prefix else name
            try:
                metadata = os.stat(
                    name,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
            except OSError:
                return False
            if stat.S_ISREG(metadata.st_mode):
                if (metadata.st_dev, metadata.st_ino) in staged_inodes:
                    return False
                continue
            if not stat.S_ISDIR(metadata.st_mode):
                continue
            if relative in excluded_roots:
                continue
            try:
                child = os.open(
                    name,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
            except OSError:
                return False
            try:
                if not scan_directory(child, relative):
                    return False
            finally:
                os.close(child)
        return True

    root_descriptor = os.open(
        root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        return scan_directory(root_descriptor, "")
    finally:
        os.close(root_descriptor)


def verify_staging(
    vault_root: Path,
    capsule_id: str,
    proposal_id: str,
) -> VerificationReport:
    """Run the ordered safe ladder without writing any vault path."""
    root = Path(vault_root).resolve()
    status = read_staging_status(root, capsule_id)
    state = next(
        (
            item.state
            for item in status.proposals
            if item.proposal_id == proposal_id
        ),
        MigrationState.UNKNOWN,
    )
    if state not in {
        MigrationState.REGENERATION_STAGED,
        MigrationState.VERIFICATION_PASSED,
        MigrationState.VERIFICATION_BLOCKED,
    }:
        return _unknown_report(
            capsule_id,
            proposal_id,
            f"Private staging state is not regeneration-staged: {state.value}",
        )
    try:
        candidate, _receipt, staging = load_staged_candidate(
            root,
            capsule_id,
            proposal_id,
        )
    except (OSError, StagingError) as error:
        return _unknown_report(
            capsule_id,
            proposal_id,
            f"Private staging is missing or unreadable: {type(error).__name__}",
        )
    static_results = _static_results(root, staging, candidate)
    reported, attempts = _reported_verifications(
        candidate,
        staging,
        static_results,
    )
    capsule_dir = root / CAPSULE_ROOT / capsule_id
    staged_paths_private = _staged_paths_are_private(
        root,
        capsule_dir,
        staging,
        candidate,
    )
    notes: set[str] = set()
    if candidate.declared_requirements:
        notes.add("Declared trust or permission requirements remain pending.")
    if candidate.unresolved_questions:
        notes.add("Candidate questions remain unresolved.")
    unsafe_equivalence = any(
        attempt.effective_class is VerificationClass.UNSAFE_UNVERIFIED
        for attempt in attempts
    )
    if unsafe_equivalence:
        notes.add(
            "Claimed behavioural equivalence remains unsafe-unverified."
        )
    plans_by_id = {
        item.customization_id: item for item in candidate.dispositions
    }
    generated_or_native = {
        item.customization_id
        for item in candidate.dispositions
        if item.disposition
        in {
            Disposition.REWRITE,
            Disposition.COMPATIBILITY_SHIM,
            Disposition.NATIVE_REPLACEMENT,
        }
    }
    missing_contract_coverage = any(
        not plans_by_id[customization_id].behaviour_contract_ids
        for customization_id in generated_or_native
    )
    if missing_contract_coverage:
        notes.add(
            "Generated or native dispositions lack complete "
            "behavioural-contract coverage."
        )
    native_without_confirmation = any(
        item.disposition is Disposition.NATIVE_REPLACEMENT
        for item in candidate.dispositions
    )
    if native_without_confirmation:
        notes.add(
            "Native replacement lacks authenticated user-confirmation evidence."
        )
    manual_or_blocked = any(
        item.disposition in {Disposition.MANUAL_REVIEW, Disposition.BLOCKED}
        for item in candidate.dispositions
    )
    if manual_or_blocked:
        notes.add("One or more dispositions remain manual or blocked.")
    static_blocked = any(item.status == "BLOCKED" for item in static_results)
    has_generated_files = bool(candidate.files)
    static_unknown = (has_generated_files and not static_results) or any(
        item.status == "UNKNOWN" for item in static_results
    )
    failed_contract = any(item.status == "failed" for item in reported)
    unknown_contract = any(item.status == "unknown" for item in reported)
    non_verified_contract = any(
        item.status != "verified" for item in reported
    )
    if (
        static_blocked
        or failed_contract
        or unsafe_equivalence
        or candidate.declared_requirements
        or candidate.unresolved_questions
        or not staged_paths_private
        or missing_contract_coverage
        or native_without_confirmation
        or manual_or_blocked
        or non_verified_contract
    ):
        verdict = "BLOCKED"
    elif static_unknown or unknown_contract:
        verdict = "UNKNOWN"
    else:
        verdict = "OK"
    return VerificationReport(
        0,
        proposal_id,
        capsule_id,
        proposal_id,
        candidate.candidate_sha256,
        static_results,
        reported,
        verdict,
        staged_paths_private,
        staged_paths_private,
        tuple(sorted(notes)),
    )


def _transaction_id() -> str:
    return time.strftime("%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:8]


def _verification_stop_seam(name: str) -> None:
    if os.environ.get("DEX_TX_TEST_STOP_AFTER") == name:
        os._exit(137)


def write_verification_report(
    vault_root: Path,
    capsule_id: str,
    proposal_id: str,
    report: VerificationReport,
) -> VerificationWriteReceipt:
    """Persist one fresh report and journal transition in a sealed transaction."""
    if type(report) is not VerificationReport:
        raise TypeError("report must be VerificationReport")
    if report.capsule_id != capsule_id or report.proposal_id != proposal_id:
        raise VerificationError("verification report identity does not match")
    root = Path(vault_root).resolve()
    refreshed = verify_staging(root, capsule_id, proposal_id)
    if refreshed.canonical_bytes() != report.canonical_bytes():
        raise VerificationError("verification report drifted before persistence")
    status = read_staging_status(root, capsule_id)
    state = next(
        (
            item.state
            for item in status.proposals
            if item.proposal_id == proposal_id
        ),
        MigrationState.UNKNOWN,
    )
    if state is not MigrationState.REGENERATION_STAGED:
        raise VerificationError(
            f"staging is not ready for report persistence: {state.value}"
        )

    capsule_dir = root / CAPSULE_ROOT / capsule_id
    staging = capsule_dir / STAGING_SUBDIR.format(proposal_id=proposal_id)
    staging_relative = (
        f"{CAPSULE_ROOT}/{capsule_id}/"
        + STAGING_SUBDIR.format(proposal_id=proposal_id)
    )
    journal_path = staging / "journal.jsonl"
    try:
        journal_before = _read_regular_beneath(
            root,
            f"{staging_relative}/journal.jsonl",
        )
        journal_records = _read_event_records_beneath(
            root,
            f"{staging_relative}/journal.jsonl",
        )
        if tuple(record["event"] for record in journal_records) != (
            MigrationEvent.REGENERATION_PROPOSED.value,
            MigrationEvent.REGENERATION_STAGED.value,
        ):
            raise VerificationError("staging journal is not regeneration-staged")
    except (OSError, StagingError) as error:
        raise VerificationError("staging journal is unreadable") from error
    event = (
        MigrationEvent.VERIFICATION_PASSED
        if report.verdict == "OK"
        else MigrationEvent.VERIFICATION_BLOCKED
    )
    report_relative = (
        f"{CAPSULE_ROOT}/{capsule_id}/verification/{report.staging_id}.json"
    )
    report_raw = report.canonical_bytes()
    report_sha256 = hashlib.sha256(report_raw).hexdigest()
    report_path = root / report_relative
    if report_path.exists() or report_path.is_symlink():
        raise VerificationError("verification report already exists")
    journal_relative = journal_path.relative_to(root).as_posix()
    transaction_id = _transaction_id()
    transaction = Transaction._begin_with_id(
        root,
        [
            PlanEntry(
                report_relative,
                report_raw,
                mode=0o600,
            ),
            PlanEntry(
                journal_relative,
                journal_before,
                mode=0o600,
                expected_current_sha256=hashlib.sha256(journal_before).hexdigest(),
            ),
        ],
        allow_empty=False,
        operation="customization-migration",
        tx_id=transaction_id,
    )

    def assert_verification_fresh() -> None:
        final_report = verify_staging(root, capsule_id, proposal_id)
        if final_report.canonical_bytes() != report.canonical_bytes():
            raise VerificationError(
                "verification report drifted during persistence"
            )

    def finalize_verification() -> None:
        verification_dir = capsule_dir / "verification"
        descriptor = _open_directory_beneath(
            root,
            verification_dir.relative_to(root).as_posix(),
        )
        try:
            os.fchmod(descriptor, 0o700)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _verification_stop_seam("verification-after-layout")
        assert_verification_fresh()
        _append_event(
            journal_path,
            event,
            candidate_sha256=report.candidate_sha256,
            report_path=report_relative,
            report_sha256=report_sha256,
        )
        _verification_stop_seam("verification-mid-finalize")

    transaction.run(before_commit=finalize_verification)
    return VerificationWriteReceipt(
        0,
        capsule_id,
        report.staging_id,
        report_relative,
        report_sha256,
        transaction_id,
    )


__all__ = [
    "StaticFileResult",
    "VerificationAttempt",
    "VerificationCheckOutcome",
    "VerificationError",
    "VerificationReport",
    "VerificationWriteReceipt",
    "verify_staging",
    "write_verification_report",
]
