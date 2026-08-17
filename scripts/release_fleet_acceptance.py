#!/usr/bin/env python3
"""Fail-closed orchestration for the macOS historic updater fleet."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.update.journey_protocol import (
    SUPPORTED_PLATFORMS,
    JourneyProtocolError,
    load_update_journey_protocol,
)
from scripts import release_fleet
from scripts.dex_update_bridge import FOUNDATION

COHORT_SCHEMA_VERSION = 1
PLATFORM_MANIFEST_SCHEMA_VERSION = 1
ACCEPTANCE_SOURCE = "scripts/release_fleet_acceptance.py"
FIRST_PARTY_PLATFORM_JOBS = {
    "darwin": "historic-fleet-darwin",
}
MAX_PLATFORM_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_PUBLIC_RELEASE_ASSET_BYTES = 16 * 1024 * 1024
PLATFORM_MANIFEST_NAME = "platform-manifest.json"
PLATFORM_RECEIPT_NAME = "platform-receipt.json"
PLATFORM_FAILURES_NAME = "platform-failures.json"
CANONICAL_PUBLIC_REMOTE = "https://github.com/davekilleen/Dex.git"
CANONICAL_PUBLIC_LATEST_RELEASE = "https://github.com/davekilleen/Dex/releases/latest"
CANONICAL_PUBLIC_RELEASE_PAGE = "https://github.com/davekilleen/Dex/releases/tag/v{version}"
CANONICAL_PUBLIC_RELEASE_DOWNLOAD = (
    "https://github.com/davekilleen/Dex/releases/download/v{version}/{name}"
)
_COHORT_FIELDS = frozenset({"schema_version", "foundation", "case_count", "cases"})
_RELEASE_FIELDS = frozenset({"tag", "version", "commit", "tree"})
_SEMVER = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)$"
)
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_SIGNED_FIELDS = frozenset({"payload", "signature"})
_SESSION_FIELDS = frozenset(
    {
        "schema_version",
        "session_id",
        "cohort_sha256",
        "foundation",
        "follow_up_tag",
        "source_commit",
        "acceptance_source_sha256",
        "platforms",
        "case_count",
        "journey_count",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "session_id",
        "platform",
        "manifest_sha256",
    }
)
_PLATFORM_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "outcome",
        "acceptance",
        "session_id",
        "platform",
        "cohort_sha256",
        "foundation",
        "follow_up_tag",
        "source_commit",
        "acceptance_source_sha256",
        "report",
    }
)


@dataclass(frozen=True)
class PlatformExecution:
    """One process's in-memory report and still-live executor capabilities."""

    report: release_fleet.AcceptanceReport
    executor_runs: tuple[object, ...]
    counts: dict[str, int]


@dataclass(frozen=True)
class PlatformCaseFailure:
    """One case-local failure retained for grouping and targeted repair."""

    starting_tag: str
    error_type: str
    detail: str
    signature: str

    def document(self) -> dict[str, str]:
        return {
            "starting_tag": self.starting_tag,
            "error_type": self.error_type,
            "detail": self.detail,
            "signature": self.signature,
        }


@dataclass(frozen=True)
class FleetInputs:
    """All immutable identities shared by one acceptance session."""

    releases: tuple[release_fleet.DistributionRelease, ...]
    foundation: release_fleet.ImmutableRelease
    follow_up: release_fleet.ImmutableRelease
    protocol: object
    source_commit: str
    acceptance_source_sha256: str
    cohort_sha256: str


class PlatformFleetFailure(release_fleet.FleetError):
    """One platform stopped before its complete live verdict."""

    def __init__(
        self,
        message: str,
        counts: Mapping[str, int],
        failures: Sequence[PlatformCaseFailure] = (),
    ) -> None:
        super().__init__(message)
        self.counts = dict(counts)
        self.failures = tuple(failures)


def _fleet_case_count(inputs: FleetInputs) -> int:
    """Return the frozen cohort count only when every starting tag is unique."""

    count = len(inputs.releases)
    if count < 1 or len({release.tag for release in inputs.releases}) != count:
        raise release_fleet.FleetError("fleet inputs do not contain the exact historic cohort")
    return count


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(value)
    if match is None:
        raise release_fleet.FleetError(f"historic release has invalid version: {value}")
    return tuple(int(match[name]) for name in ("major", "minor", "patch"))


def _release_document(release: release_fleet.DistributionRelease) -> dict[str, str]:
    return {
        "tag": release.tag,
        "version": release.version,
        "commit": release.commit,
        "tree": release.tree,
    }


def _foundation_document(foundation: Mapping[str, str] | None) -> dict[str, str]:
    expected = FOUNDATION.identity()
    supplied = dict(foundation) if foundation is not None else expected
    if supplied != expected:
        raise release_fleet.FleetError("historic cohort foundation identity does not match the pinned bridge")
    return expected


def _historic_releases(
    releases: Sequence[release_fleet.DistributionRelease],
    *,
    foundation: Mapping[str, str],
) -> tuple[release_fleet.DistributionRelease, ...]:
    boundary = _version_tuple(foundation["version"])
    historic = tuple(release for release in releases if _version_tuple(release.version) <= boundary)
    expected_foundation = {field: foundation[field] for field in ("tag", "version", "commit", "tree")}
    if sum(_release_document(release) == expected_foundation for release in historic) != 1:
        raise release_fleet.FleetError("historic cohort does not contain the exact pinned foundation release")
    return historic


def frozen_cohort_manifest(
    releases: Sequence[release_fleet.DistributionRelease],
    *,
    foundation: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Freeze the accepted historic trees through the immutable foundation."""

    foundation_identity = _foundation_document(foundation)
    historic = _historic_releases(releases, foundation=foundation_identity)
    if len({release.tag for release in historic}) != len(historic):
        raise release_fleet.FleetError("historic cohort repeats a release tag")
    return {
        "schema_version": COHORT_SCHEMA_VERSION,
        "foundation": foundation_identity,
        "case_count": len(historic),
        "cases": [_release_document(release) for release in historic],
    }


def releases_from_frozen_cohort(
    source: str,
    *,
    current_releases: Sequence[release_fleet.DistributionRelease],
    foundation: Mapping[str, str] | None = None,
) -> tuple[release_fleet.DistributionRelease, ...]:
    """Validate a frozen cohort while allowing only post-foundation releases."""

    foundation_identity = _foundation_document(foundation)
    try:
        document = json.loads(source)
    except json.JSONDecodeError as error:
        raise release_fleet.FleetError("historic cohort manifest is not valid JSON") from error
    if (
        not isinstance(document, Mapping)
        or set(document) != _COHORT_FIELDS
        or document.get("schema_version") != COHORT_SCHEMA_VERSION
        or document.get("foundation") != foundation_identity
    ):
        raise release_fleet.FleetError("historic cohort manifest has an invalid foundation identity or shape")
    cases = document.get("cases")
    count = document.get("case_count")
    if (
        not isinstance(cases, list)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 1
        or count != len(cases)
    ):
        raise release_fleet.FleetError("historic cohort manifest has an invalid case count")

    parsed: list[release_fleet.DistributionRelease] = []
    for index, case in enumerate(cases, start=1):
        if (
            not isinstance(case, Mapping)
            or set(case) != _RELEASE_FIELDS
            or any(not isinstance(case[field], str) or not case[field] for field in _RELEASE_FIELDS)
        ):
            raise release_fleet.FleetError(f"historic cohort manifest case {index} is invalid")
        parsed.append(
            release_fleet.DistributionRelease(
                tag=str(case["tag"]),
                version=str(case["version"]),
                commit=str(case["commit"]),
                tree=str(case["tree"]),
            )
        )
    if len({release.tag for release in parsed}) != len(parsed):
        raise release_fleet.FleetError("historic cohort manifest repeats a release tag")

    current_historic = _historic_releases(
        current_releases,
        foundation=foundation_identity,
    )
    parsed_by_tag = {release.tag: release for release in parsed}
    current_by_tag = {release.tag: release for release in current_historic}
    unexpected = sorted(current_by_tag.keys() - parsed_by_tag.keys())
    if unexpected:
        raise release_fleet.FleetError(
            "unexpected historical release appeared at or before the foundation: " + ", ".join(unexpected)
        )
    if parsed_by_tag != current_by_tag or tuple(parsed) != current_historic:
        raise release_fleet.FleetError("historic cohort identity drift")
    return tuple(parsed)


def assert_platform_report_bound(
    report: release_fleet.AcceptanceReport,
    *,
    protocol: object,
    running_platform: str,
    expected_start_tags: set[str],
) -> None:
    """Bind one live-process report to one member of the exact protocol set."""

    protocol_platforms = tuple(getattr(protocol, "platforms", ()))
    if protocol_platforms != SUPPORTED_PLATFORMS:
        raise release_fleet.FleetError("released journey protocol platforms are not the exact supported set")
    if running_platform not in protocol_platforms:
        raise release_fleet.FleetError("running platform is not declared by the protocol")
    if report.platforms != (running_platform,):
        raise release_fleet.FleetError("a live platform report must declare exactly one running platform")
    release_fleet.assert_complete(report, expected_start_tags)


def verify_acceptance_source_bound(repo: Path, source_commit: str) -> str:
    """Require this running orchestrator to equal its publisher-commit bytes."""

    if _HEX_40.fullmatch(source_commit) is None:
        raise release_fleet.FleetError("acceptance orchestrator source commit is invalid")
    try:
        released = release_fleet._tag_file(repo, source_commit, ACCEPTANCE_SOURCE)
    except release_fleet.FleetError as error:
        raise release_fleet.FleetError("released acceptance orchestrator source is unavailable") from error
    running = Path(__file__).resolve().read_bytes()
    if running != released:
        raise release_fleet.FleetError("running acceptance orchestrator bytes do not match the publisher commit")
    return hashlib.sha256(running).hexdigest()


def load_fleet_inputs(
    repo: Path,
    cohort_path: Path,
    *,
    foundation_tag: str,
    follow_up_tag: str,
) -> FleetInputs:
    """Resolve and bind every immutable input before any journey can start."""

    try:
        cohort_bytes = cohort_path.read_bytes()
    except OSError as error:
        raise release_fleet.FleetError("historic cohort manifest is unavailable") from error
    try:
        cohort_source = cohort_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise release_fleet.FleetError("historic cohort manifest is not valid UTF-8") from error
    releases = releases_from_frozen_cohort(
        cohort_source,
        current_releases=release_fleet.discover_distribution_releases(repo),
    )
    foundation = release_fleet.resolve_immutable_release(repo, foundation_tag)
    follow_up = release_fleet.resolve_immutable_release(repo, follow_up_tag)
    if foundation.identity() != FOUNDATION.identity():
        raise release_fleet.FleetError("fleet acceptance foundation is not the pinned bridge identity")
    if foundation.tag == follow_up.tag or foundation.commit == follow_up.commit:
        raise release_fleet.FleetError("foundation and follow-up must be different immutable releases")
    try:
        protocol = load_update_journey_protocol(
            release_fleet._tag_file(
                repo,
                follow_up.tag,
                release_fleet.UPDATE_JOURNEY_RELATIVE,
            )
        )
    except (release_fleet.FleetError, JourneyProtocolError) as error:
        raise release_fleet.FleetError("follow-up released journey protocol is unavailable or invalid") from error
    _require_protocol_platforms(protocol.platforms)
    if protocol.foundation != foundation.identity():
        raise release_fleet.FleetError("released journey protocol names a different foundation")
    source_commit = release_fleet._verify_released_protocol_artifacts(
        repo,
        follow_up,
        protocol,
    )
    acceptance_source_sha256 = verify_acceptance_source_bound(repo, source_commit)
    return FleetInputs(
        releases=releases,
        foundation=foundation,
        follow_up=follow_up,
        protocol=protocol,
        source_commit=source_commit,
        acceptance_source_sha256=acceptance_source_sha256,
        cohort_sha256=hashlib.sha256(cohort_bytes).hexdigest(),
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sign(payload: Mapping[str, object], key: bytes) -> dict[str, object]:
    if not isinstance(key, bytes) or len(key) != 32:
        raise release_fleet.FleetError("fleet acceptance session key must be exactly 32 bytes")
    return {
        "payload": dict(payload),
        "signature": hmac.new(
            key,
            _canonical_bytes(payload),
            hashlib.sha256,
        ).hexdigest(),
    }


def _verified_payload(
    signed: object,
    *,
    key: bytes,
    fields: frozenset[str],
    context: str,
) -> dict[str, object]:
    if not isinstance(signed, Mapping) or set(signed) != _SIGNED_FIELDS:
        raise release_fleet.FleetError(f"{context} has an invalid signed shape")
    payload = signed.get("payload")
    signature = signed.get("signature")
    if (
        not isinstance(payload, Mapping)
        or set(payload) != fields
        or not isinstance(signature, str)
        or _HEX_64.fullmatch(signature) is None
    ):
        raise release_fleet.FleetError(f"{context} has an invalid signed shape")
    expected = _sign(dict(payload), key)["signature"]
    assert isinstance(expected, str)
    if not hmac.compare_digest(signature, expected):
        raise release_fleet.FleetError(f"{context} signature is invalid")
    return dict(payload)


def _require_protocol_platforms(platforms: Sequence[str]) -> tuple[str, ...]:
    value = tuple(platforms)
    if value != SUPPORTED_PLATFORMS:
        raise release_fleet.FleetError("fleet acceptance protocol platforms are not exactly darwin")
    return value


def create_acceptance_session(
    *,
    cohort_sha256: str,
    foundation: Mapping[str, str] | None,
    follow_up_tag: str,
    source_commit: str,
    acceptance_source_sha256: str,
    protocol_platforms: Sequence[str],
    case_count: int,
    key: bytes,
    session_id: str,
) -> dict[str, object]:
    """Create one authenticated session shared by both platform processes."""

    platforms = _require_protocol_platforms(protocol_platforms)
    foundation_identity = _foundation_document(foundation)
    if (
        _HEX_64.fullmatch(cohort_sha256) is None
        or _HEX_64.fullmatch(acceptance_source_sha256) is None
        or _HEX_64.fullmatch(session_id) is None
        or _HEX_40.fullmatch(source_commit) is None
        or release_fleet.RELEASE_TAG.fullmatch(follow_up_tag) is None
        or not isinstance(case_count, int)
        or isinstance(case_count, bool)
        or case_count < 1
    ):
        raise release_fleet.FleetError("fleet acceptance session identity is invalid")
    return _sign(
        {
            "schema_version": 1,
            "session_id": session_id,
            "cohort_sha256": cohort_sha256,
            "foundation": foundation_identity,
            "follow_up_tag": follow_up_tag,
            "source_commit": source_commit,
            "acceptance_source_sha256": acceptance_source_sha256,
            "platforms": list(platforms),
            "case_count": case_count,
            "journey_count": case_count * len(platforms),
        },
        key,
    )


def _immutable_manifest_bytes(path: Path) -> bytes:
    """Reopen one write-closed regular file without following aliases."""

    try:
        metadata = path.lstat()
    except OSError as error:
        raise release_fleet.FleetError("platform fleet manifest is not immutable") from error
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o222
        or metadata.st_nlink != 1
        or metadata.st_size < 1
        or metadata.st_size > MAX_PLATFORM_MANIFEST_BYTES
    ):
        raise release_fleet.FleetError("platform fleet manifest is not immutable")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise release_fleet.FleetError("platform fleet manifest is not immutable") from error
    identity = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    if (
        any(getattr(metadata, field) != getattr(before, field) for field in identity)
        or stat.S_IMODE(before.st_mode) & 0o222
        or len(content) != before.st_size
        or any(getattr(before, field) != getattr(after, field) for field in identity)
    ):
        raise release_fleet.FleetError("platform fleet manifest changed while it was read")
    return content


def _parse_platform_manifest(
    path: Path,
) -> tuple[bytes, dict[str, object], release_fleet.AcceptanceReport]:
    content = _immutable_manifest_bytes(path)
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise release_fleet.FleetError("platform fleet manifest is invalid") from error
    if (
        not isinstance(document, Mapping)
        or set(document) != _PLATFORM_MANIFEST_FIELDS
        or document.get("schema_version") != PLATFORM_MANIFEST_SCHEMA_VERSION
        or document.get("outcome") != "HISTORIC_PLATFORM_EVIDENCE"
        or document.get("acceptance") is not False
        or not isinstance(document.get("report"), Mapping)
    ):
        raise release_fleet.FleetError("platform fleet manifest shape is invalid")
    report = release_fleet.acceptance_report_from_json(
        json.dumps(
            document["report"],
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return content, dict(document), report


def aggregate_platform_evidence(
    session: object,
    receipts: Sequence[object],
    manifest_paths: Sequence[Path],
    *,
    key: bytes,
    inputs: FleetInputs,
) -> dict[str, object]:
    """Validate serialized evidence while refusing to treat it as execution authority."""

    platforms = _require_protocol_platforms(inputs.protocol.platforms)
    session_payload = _assert_session_matches_inputs(
        session,
        key=key,
        inputs=inputs,
    )
    case_count = _fleet_case_count(inputs)
    expected_tags = {release.tag for release in inputs.releases}

    receipts_by_platform: dict[str, dict[str, object]] = {}
    for signed in receipts:
        receipt = _verified_payload(
            signed,
            key=key,
            fields=_RECEIPT_FIELDS,
            context="platform fleet receipt",
        )
        platform = receipt.get("platform")
        if not isinstance(platform, str) or platform in receipts_by_platform:
            raise release_fleet.FleetError("platform evidence does not cover the exact protocol platforms")
        receipts_by_platform[platform] = receipt

    manifests_by_platform: dict[str, tuple[bytes, dict[str, object], release_fleet.AcceptanceReport]] = {}
    for path in manifest_paths:
        content, manifest, report = _parse_platform_manifest(path)
        platform = manifest.get("platform")
        if not isinstance(platform, str) or platform in manifests_by_platform:
            raise release_fleet.FleetError("platform evidence does not cover the exact protocol platforms")
        manifests_by_platform[platform] = (content, manifest, report)

    if (
        set(receipts_by_platform) != set(platforms)
        or set(manifests_by_platform) != set(platforms)
        or len(receipts_by_platform) != len(platforms)
        or len(manifests_by_platform) != len(platforms)
    ):
        raise release_fleet.FleetError("platform evidence does not cover the exact protocol platforms")

    for platform in platforms:
        receipt = receipts_by_platform[platform]
        content, manifest, report = manifests_by_platform[platform]
        if (
            receipt.get("schema_version") != 1
            or receipt.get("session_id") != session_payload["session_id"]
            or receipt.get("manifest_sha256") != hashlib.sha256(content).hexdigest()
        ):
            raise release_fleet.FleetError(f"{platform}: platform manifest hash is not bound to its receipt")
        if (
            manifest.get("session_id") != session_payload["session_id"]
            or manifest.get("platform") != platform
            or manifest.get("cohort_sha256") != inputs.cohort_sha256
            or manifest.get("foundation") != inputs.foundation.identity()
            or manifest.get("follow_up_tag") != inputs.follow_up.tag
            or manifest.get("source_commit") != inputs.source_commit
            or manifest.get("acceptance_source_sha256") != inputs.acceptance_source_sha256
        ):
            raise release_fleet.FleetError(f"{platform}: platform manifest is not bound to the session")
        assert_platform_report_bound(
            report,
            protocol=inputs.protocol,
            running_platform=platform,
            expected_start_tags=expected_tags,
        )
        if len(report.cases) != case_count:
            raise release_fleet.FleetError(f"{platform}: platform manifest has an invalid case count")

    total = case_count * len(platforms)
    return {
        "outcome": "HISTORIC_FLEET_EVIDENCE_AGGREGATED",
        "acceptance": False,
        "authority_complete": False,
        "platforms": list(platforms),
        "case_count": case_count,
        "journey_count": total,
        "discovered": case_count,
        "started": total,
        "completed": total,
        "passed": total,
        "failed": 0,
        "session_id": session_payload["session_id"],
        "required_job_conclusions": dict(FIRST_PARTY_PLATFORM_JOBS),
    }


def _platform_case_failure(
    release: release_fleet.DistributionRelease,
    error: release_fleet.CaseJourneyFailure,
    *,
    output: Path,
) -> PlatformCaseFailure:
    detail = error.detail.replace(str(output), "<fleet-output>")
    error_type = type(error).__name__
    signature = hashlib.sha256(f"{error_type}\0{detail}".encode("utf-8")).hexdigest()
    return PlatformCaseFailure(release.tag, error_type, detail, signature)


def _write_platform_failure_summary(
    output: Path,
    counts: Mapping[str, int],
    failures: Sequence[PlatformCaseFailure],
) -> Path:
    grouped: dict[tuple[str, str], list[str]] = {}
    for failure in failures:
        grouped.setdefault((failure.error_type, failure.signature), []).append(
            failure.starting_tag
        )
    groups = [
        {
            "count": len(starting_tags),
            "error_type": error_type,
            "signature": signature,
            "starting_tags": sorted(starting_tags),
        }
        for (error_type, signature), starting_tags in sorted(grouped.items())
    ]
    path = output / PLATFORM_FAILURES_NAME
    _write_exclusive(
        path,
        _json_bytes(
            {
                "schema_version": 1,
                "outcome": "HISTORIC_FLEET_CASE_FAILURES",
                "acceptance": False,
                "counts": dict(counts),
                "groups": groups,
                "failures": [failure.document() for failure in failures],
            }
        ),
        mode=0o600,
    )
    return path


def bridge_process_entry_release(
    releases: Sequence[release_fleet.DistributionRelease],
) -> release_fleet.DistributionRelease | None:
    """Choose the one release that also starts the bridge as a process.

    Deliberately the **newest historic start that is not already the pinned
    foundation**, where the PR canary probes the **oldest** of its fixed starts.
    Inheriting the canary's choice would leave the two gates correlated, and
    they would then miss the same thing.

    They are not interchangeable, because the two vault shapes take different
    paths through the bridge. An old pre-split vault stops first at the topology
    approval -- "Dex will first separate its code from your notes." A vault that
    is already brain/vault split skips that entirely (``run_bridge`` records
    ``already-brain-vault-split`` and asks for no token), so its first approval
    gate is the delivered-release one. Probing only the oldest start would mean
    no gate ever watched the bridge reach the second of those as a real process.

    The pinned foundation itself is the wrong newest. The historic cohort is
    required to contain it, and its installer fixture already has
    ``refs/dex/installed`` and the split markers equal to the bridge pin. Then
    ``run_bridge`` takes ``_foundation_is_installed`` and skips both topology
    and delivered-release, so the process probe would never watch the APPLY
    gate this exists to cover. A distinct same-version sibling (a semantic tag
    with a different commit) is still eligible: installing it does not set the
    pin, so it is the delivered-release shape.

    ``discover_distribution_releases`` sorts ascending by semantic version, so
    the newest eligible start is the last remaining entry.
    """

    pin = FOUNDATION.identity()
    candidates = tuple(
        release
        for release in releases
        if (
            release.tag != pin["tag"]
            and release.commit != pin["commit"]
            and release.tree != pin["tree"]
        )
    )
    return candidates[-1] if candidates else None


def _assert_bridge_process_entry_ran(
    output: Path,
    designated: release_fleet.DistributionRelease | None,
    counts: Mapping[str, int],
) -> None:
    """Refuse a platform run in which the process probe never actually ran.

    The probe is wired in by a single boolean, and a gate that can silently
    stop running is the failure this whole line of work exists to retire. So
    the evidence the probe leaves behind is checked here rather than the
    intention that it was requested: an empty observation is not a result.
    """

    if designated is None:
        if counts.get("discovered", 0) == 0:
            raise PlatformFleetFailure(
                "platform cohort was empty, so nothing started the bridge as a process",
                dict(counts),
            )
        raise PlatformFleetFailure(
            "no historic start other than the pinned foundation can start "
            "the bridge as a process: discovered "
            f"{counts.get('discovered', 0)}",
            dict(counts),
        )
    expected = (
        output
        / f"{release_fleet.safe_case_name(designated)}"
        f"{release_fleet.BRIDGE_PROCESS_ENTRY_SUFFIX}"
        / "bridge-process-entry.json"
    )
    observed = sorted(
        output.glob(f"*{release_fleet.BRIDGE_PROCESS_ENTRY_SUFFIX}/bridge-process-entry.json")
    )
    if not observed:
        raise PlatformFleetFailure(
            "no release started the bridge as a top-level process: expected "
            f"evidence at {expected}",
            dict(counts),
        )
    if len(observed) != 1 or observed[0] != expected:
        raise PlatformFleetFailure(
            "bridge process-entry evidence does not match the designated release "
            f"{designated.tag}: expected exactly {expected}, observed "
            + ", ".join(str(path) for path in observed),
            dict(counts),
        )


def collect_platform_runs(
    repo: Path,
    *,
    output: Path,
    releases: Sequence[release_fleet.DistributionRelease],
    foundation_tag: str,
    follow_up_tag: str,
    running_platform: str,
    bridge_asset: Path,
    bridge_checksum: Path,
    journey_runner: Callable[..., object] = release_fleet.run_journey,
) -> PlatformExecution:
    """Run one platform sequentially and retain every live executor result."""

    counts = {
        "discovered": len(releases),
        "started": 0,
        "completed": 0,
        "passed": 0,
        "failed": 0,
    }
    executor_runs: list[object] = []
    case_documents: list[dict[str, object]] = []
    case_failures: list[PlatformCaseFailure] = []
    designated = bridge_process_entry_release(releases)
    for release in releases:
        counts["started"] += 1
        try:
            run = journey_runner(
                repo,
                output=output,
                starting_tag=release.tag,
                foundation_tag=foundation_tag,
                follow_up_tag=follow_up_tag,
                bridge_asset=bridge_asset,
                bridge_checksum=bridge_checksum,
                controlled_approvals=True,
                bridge_process_entry=(
                    designated is not None and release.tag == designated.tag
                ),
            )
            case = getattr(run, "case", None)
            if not isinstance(case, Mapping):
                raise release_fleet.FleetError(f"{release.tag}: journey returned no live case evidence")
            case_documents.append(dict(case))
            executor_runs.append(run)
            counts["completed"] += 1
            counts["passed"] += 1
        except release_fleet.CaseJourneyFailure as error:
            counts["failed"] += 1
            failure = _platform_case_failure(release, error, output=output)
            case_failures.append(failure)
            print(
                json.dumps(
                    {"fleet_case_failure": failure.document()},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
                flush=True,
            )
        except Exception as error:
            counts["failed"] += 1
            raise PlatformFleetFailure(
                f"{release.tag}: platform infrastructure or integrity failure: {error}",
                counts,
                case_failures,
            ) from error

    if case_failures:
        summary = _write_platform_failure_summary(output, counts, case_failures)
        raise PlatformFleetFailure(
            f"{len(case_failures)} case-local journey failures; summary: {summary}",
            counts,
            case_failures,
        )

    _assert_bridge_process_entry_ran(output, designated, counts)

    try:
        report = release_fleet.acceptance_report_from_json(
            json.dumps(
                {
                    "foundation_tag": foundation_tag,
                    "follow_up_tag": follow_up_tag,
                    "platforms": [running_platform],
                    "cases": case_documents,
                },
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    except Exception as error:
        counts["failed"] += 1
        raise PlatformFleetFailure(
            f"platform journey report is malformed: {error}",
            counts,
        ) from error
    return PlatformExecution(report, tuple(executor_runs), counts)


def _platform_receipt_boundary():
    evidence_validator = release_fleet.assert_evidence_bound
    complete_validator = release_fleet.assert_complete
    platform_validator = assert_platform_report_bound
    if sys.platform == "darwin":
        host_platform = "darwin"
    else:
        host_platform = ""

    def finalize_live_platform_execution(
        execution: PlatformExecution,
        *,
        repo: Path,
        evidence_root: Path,
        inputs: FleetInputs,
        session: object,
        key: bytes,
    ) -> dict[str, object]:
        """Validate live authority, then write one immutable evidence pair."""

        if (
            release_fleet.assert_evidence_bound is not evidence_validator
            or release_fleet.assert_complete is not complete_validator
            or globals().get("assert_platform_report_bound") is not platform_validator
        ):
            raise release_fleet.FleetError("fleet acceptance validator changed during the live process")
        case_count = _fleet_case_count(inputs)
        expected_start_tags = {release.tag for release in inputs.releases}
        platform_validator(
            execution.report,
            protocol=inputs.protocol,
            running_platform=host_platform,
            expected_start_tags=expected_start_tags,
        )
        evidence_validator(
            execution.report,
            repo=repo,
            evidence_root=evidence_root,
            foundation=inputs.foundation,
            follow_up=inputs.follow_up,
            executor_runs=execution.executor_runs,
        )

        counts = execution.counts
        if counts != {
            "discovered": case_count,
            "started": case_count,
            "completed": case_count,
            "passed": case_count,
            "failed": 0,
        }:
            raise release_fleet.FleetError("live platform execution is incomplete or failed")
        session_payload = _assert_session_matches_inputs(
            session,
            key=key,
            inputs=inputs,
        )
        if (
            execution.report.foundation_tag != inputs.foundation.tag
            or execution.report.follow_up_tag != inputs.follow_up.tag
        ):
            raise release_fleet.FleetError("live platform execution is not bound to the immutable releases")
        if len(execution.report.cases) != case_count:
            raise release_fleet.FleetError(
                f"live platform execution does not have exactly {case_count} final starts"
            )
        cases: list[dict[str, object]] = [
            {field: getattr(case, field) for field in sorted(release_fleet.CASE_RESULT_KEYS)}
            for case in execution.report.cases
        ]
        manifest = {
            "schema_version": PLATFORM_MANIFEST_SCHEMA_VERSION,
            "outcome": "HISTORIC_PLATFORM_EVIDENCE",
            "acceptance": False,
            "session_id": session_payload["session_id"],
            "platform": host_platform,
            "cohort_sha256": inputs.cohort_sha256,
            "foundation": inputs.foundation.identity(),
            "follow_up_tag": inputs.follow_up.tag,
            "source_commit": inputs.source_commit,
            "acceptance_source_sha256": inputs.acceptance_source_sha256,
            "report": {
                "foundation_tag": execution.report.foundation_tag,
                "follow_up_tag": execution.report.follow_up_tag,
                "platforms": list(execution.report.platforms),
                "cases": cases,
            },
        }
        try:
            root_metadata = evidence_root.lstat()
        except OSError as error:
            raise release_fleet.FleetError("platform fleet output is unsafe") from error
        if (
            evidence_root.is_symlink()
            or not stat.S_ISDIR(root_metadata.st_mode)
            or stat.S_IMODE(root_metadata.st_mode) != 0o700
        ):
            raise release_fleet.FleetError("platform fleet output is unsafe")
        manifest_output = evidence_root / PLATFORM_MANIFEST_NAME
        receipt_output = evidence_root / PLATFORM_RECEIPT_NAME
        manifest_bytes = _json_bytes(manifest)
        for output in (manifest_output, receipt_output):
            if output.exists() or output.is_symlink():
                raise release_fleet.FleetError(f"acceptance output already exists: {output}")
        _write_exclusive(manifest_output, manifest_bytes, mode=0o444)
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        receipt = _sign(
            {
                "schema_version": 1,
                "session_id": session_payload["session_id"],
                "platform": host_platform,
                "manifest_sha256": manifest_sha256,
            },
            key,
        )
        _write_exclusive(receipt_output, _json_bytes(receipt), mode=0o444)
        return {
            "acceptance": False,
            "platform": host_platform,
            "manifest_sha256": manifest_sha256,
            "manifest_output": str(manifest_output),
            "receipt_output": str(receipt_output),
        }

    return finalize_live_platform_execution


finalize_live_platform_execution = _platform_receipt_boundary()
del _platform_receipt_boundary


def _write_exclusive(path: Path, content: bytes, *, mode: int) -> None:
    if not path.parent.is_dir():
        raise release_fleet.FleetError(f"acceptance output parent does not exist: {path.parent}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, mode)
    except FileExistsError as error:
        raise release_fleet.FleetError(f"acceptance output already exists: {path}") from error
    try:
        view = memoryview(content)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def write_session_key(path: Path, *, key: bytes | None = None) -> bytes:
    """Create one private, non-reusable acceptance-session key."""

    value = secrets.token_bytes(32) if key is None else key
    if not isinstance(value, bytes) or len(value) != 32:
        raise release_fleet.FleetError("fleet acceptance session key must be exactly 32 bytes")
    _write_exclusive(path, value, mode=0o600)
    return value


def read_session_key(path: Path) -> bytes:
    """Open one private key without following links or accepting loose modes."""

    try:
        metadata = path.lstat()
    except OSError as error:
        raise release_fleet.FleetError("fleet acceptance session key is missing") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or path.is_symlink()
        or metadata.st_size != 32
    ):
        raise release_fleet.FleetError("fleet acceptance session key is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            value = os.read(descriptor, 33)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise release_fleet.FleetError("fleet acceptance session key is unsafe") from error
    if len(value) != 32:
        raise release_fleet.FleetError("fleet acceptance session key is unsafe")
    return value


def _read_json(path: Path, *, context: str) -> object:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise OSError("not a regular file")
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise release_fleet.FleetError(f"{context} is unavailable or invalid") from error


def _create_private_run_root(path: Path) -> None:
    """Create the controller-owned root that may contain disposable fixtures."""

    if path.exists() or path.is_symlink():
        raise release_fleet.FleetError(f"platform fleet output already exists: {path}")
    parent = path.parent
    try:
        parent_metadata = parent.lstat()
    except OSError as error:
        raise release_fleet.FleetError(f"platform fleet output parent is unavailable: {parent}") from error
    if parent.is_symlink() or not stat.S_ISDIR(parent_metadata.st_mode):
        raise release_fleet.FleetError(f"platform fleet output parent is unsafe: {parent}")
    try:
        path.mkdir(mode=0o700)
        path.chmod(0o700)
        metadata = path.lstat()
    except OSError as error:
        raise release_fleet.FleetError(f"platform fleet output cannot be created: {path}") from error
    if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise release_fleet.FleetError(f"platform fleet output is unsafe: {path}")


def _assert_session_matches_inputs(
    session: object,
    *,
    key: bytes,
    inputs: FleetInputs,
) -> dict[str, object]:
    case_count = _fleet_case_count(inputs)
    payload = _verified_payload(
        session,
        key=key,
        fields=_SESSION_FIELDS,
        context="fleet acceptance session",
    )
    expected = {
        "schema_version": 1,
        "cohort_sha256": inputs.cohort_sha256,
        "foundation": inputs.foundation.identity(),
        "follow_up_tag": inputs.follow_up.tag,
        "source_commit": inputs.source_commit,
        "acceptance_source_sha256": inputs.acceptance_source_sha256,
        "platforms": list(_require_protocol_platforms(inputs.protocol.platforms)),
        "case_count": case_count,
        "journey_count": case_count * len(SUPPORTED_PLATFORMS),
    }
    if any(payload.get(field) != value for field, value in expected.items()):
        raise release_fleet.FleetError("fleet acceptance session does not match the immutable fleet inputs")
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or _HEX_64.fullmatch(session_id) is None:
        raise release_fleet.FleetError("fleet acceptance session identity is invalid")
    return payload


def _running_platform() -> str:
    if sys.platform == "darwin":
        return "darwin"
    raise release_fleet.FleetError("historic fleet acceptance supports macOS only")


def _read_public_bytes(url: str, *, limit: int, context: str) -> bytes:
    """Read one bounded canonical GitHub response or fail the acceptance closed."""

    request = urllib.request.Request(url, headers={"User-Agent": "dex-release-fleet-acceptance"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read(limit + 1)
    except (OSError, urllib.error.URLError) as error:
        raise release_fleet.FleetError(f"public {context} is unavailable") from error
    if len(content) > limit:
        raise release_fleet.FleetError(f"public {context} is too large")
    return content


def _verify_public_follow_up_release(release: release_fleet.ImmutableRelease) -> None:
    """Prove the immutable release tag is advertised by the canonical remote."""

    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "credential.helper=",
                "-c",
                "protocol.file.allow=never",
                "ls-remote",
                "--refs",
                "--tags",
                CANONICAL_PUBLIC_REMOTE,
                f"refs/tags/{release.tag}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise release_fleet.FleetError(
            "follow-up release cannot be verified against the public stable remote"
        ) from error
    expected = f"{release.tag_object}\trefs/tags/{release.tag}"
    if result.returncode != 0 or result.stdout.strip() != expected:
        raise release_fleet.FleetError(
            "follow-up release is not advertised by the public stable remote"
        )


class _ExactStableReleaseRedirect(urllib.request.HTTPRedirectHandler):
    """Allow exactly one canonical redirect to the expected stable tag page."""

    def __init__(self, expected_url: str) -> None:
        super().__init__()
        self.expected_url = expected_url
        self.redirects: list[str] = []

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        if (
            request.full_url != CANONICAL_PUBLIC_LATEST_RELEASE
            or self.redirects
            or new_url != self.expected_url
        ):
            raise release_fleet.FleetError(
                "follow-up is not the latest public stable GitHub release"
            )
        self.redirects.append(new_url)
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def _verify_public_stable_release(release: release_fleet.ImmutableRelease) -> None:
    """Prove the public latest-stable route resolves to this exact release."""

    expected_url = CANONICAL_PUBLIC_RELEASE_PAGE.format(version=release.version)
    redirect_handler = _ExactStableReleaseRedirect(expected_url)
    opener = urllib.request.build_opener(redirect_handler)
    request = urllib.request.Request(
        CANONICAL_PUBLIC_LATEST_RELEASE,
        headers={"User-Agent": "dex-release-fleet-acceptance"},
    )
    try:
        with opener.open(request, timeout=30) as response:
            final_url = response.geturl()
            status = response.getcode()
    except (OSError, urllib.error.URLError) as error:
        raise release_fleet.FleetError("public stable GitHub release is unavailable") from error

    if redirect_handler.redirects != [expected_url] or final_url != expected_url or status != 200:
        raise release_fleet.FleetError(
            "follow-up is not the latest public stable GitHub release"
        )


def _verify_public_bridge_release_asset(
    release: release_fleet.ImmutableRelease,
    *,
    bridge_asset: Path,
    bridge_checksum: Path,
) -> None:
    """Require the submitted pair to be byte-identical public stable release assets."""

    _verify_public_stable_release(release)

    for path in (bridge_asset, bridge_checksum):
        public_bytes = _read_public_bytes(
            CANONICAL_PUBLIC_RELEASE_DOWNLOAD.format(version=release.version, name=path.name),
            limit=MAX_PUBLIC_RELEASE_ASSET_BYTES,
            context="stable GitHub release bridge asset",
        )
        try:
            supplied_bytes = path.read_bytes()
        except OSError as error:
            raise release_fleet.FleetError("submitted bridge asset is unavailable") from error
        if public_bytes != supplied_bytes:
            raise release_fleet.FleetError("bridge asset does not match the public GitHub release")


def _add_bound_input_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--foundation-tag", required=True)
    parser.add_argument("--follow-up-tag", required=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Freeze, execute, or aggregate the formal historic release fleet."""

    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    cohort = subcommands.add_parser(
        "cohort",
        help="freeze all immutable historic trees through the pinned foundation",
    )
    cohort.add_argument("--repo", type=Path, required=True)
    cohort.add_argument("--output", type=Path, required=True)
    session = subcommands.add_parser(
        "session",
        help="bind one authenticated acceptance session to immutable release inputs",
    )
    _add_bound_input_arguments(session)
    session.add_argument("--session-output", type=Path, required=True)
    session.add_argument("--key-output", type=Path, required=True)
    platform = subcommands.add_parser(
        "platform",
        help="run all frozen starts in one process and write live-validated platform evidence",
    )
    _add_bound_input_arguments(platform)
    platform.add_argument("--session", type=Path, required=True)
    platform.add_argument("--key", type=Path, required=True)
    platform.add_argument("--bridge-asset", type=Path, required=True)
    platform.add_argument("--bridge-checksum", type=Path, required=True)
    platform.add_argument("--output", type=Path, required=True)
    aggregate = subcommands.add_parser(
        "aggregate",
        help="validate serialized Darwin evidence without minting acceptance",
    )
    _add_bound_input_arguments(aggregate)
    aggregate.add_argument("--session", type=Path, required=True)
    aggregate.add_argument("--key", type=Path, required=True)
    aggregate.add_argument(
        "--receipt",
        action="append",
        type=Path,
        required=True,
        help="signed Darwin platform receipt; provide exactly once",
    )
    aggregate.add_argument(
        "--manifest",
        action="append",
        type=Path,
        required=True,
        help="immutable Darwin platform manifest; provide exactly once",
    )
    aggregate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "cohort":
        manifest = frozen_cohort_manifest(release_fleet.discover_distribution_releases(args.repo))
        _write_exclusive(args.output, _json_bytes(manifest), mode=0o644)
        print(
            json.dumps(
                {
                    "outcome": "HISTORIC_COHORT_FROZEN",
                    "acceptance": False,
                    "foundation_tag": FOUNDATION.tag,
                    "case_count": manifest["case_count"],
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    inputs = load_fleet_inputs(
        args.repo,
        args.cohort,
        foundation_tag=args.foundation_tag,
        follow_up_tag=args.follow_up_tag,
    )
    if args.command == "session":
        for output in (args.session_output, args.key_output):
            if output.exists() or output.is_symlink():
                raise release_fleet.FleetError(f"acceptance output already exists: {output}")
        key = write_session_key(args.key_output)
        signed_session = create_acceptance_session(
            cohort_sha256=inputs.cohort_sha256,
            foundation=inputs.foundation.identity(),
            follow_up_tag=inputs.follow_up.tag,
            source_commit=inputs.source_commit,
            acceptance_source_sha256=inputs.acceptance_source_sha256,
            protocol_platforms=inputs.protocol.platforms,
            case_count=_fleet_case_count(inputs),
            key=key,
            session_id=secrets.token_hex(32),
        )
        _write_exclusive(
            args.session_output,
            _json_bytes(signed_session),
            mode=0o644,
        )
        print(
            json.dumps(
                {
                    "outcome": "HISTORIC_FLEET_SESSION_CREATED",
                    "acceptance": False,
                    "discovered": len(inputs.releases),
                    "started": 0,
                    "completed": 0,
                    "passed": 0,
                    "failed": 0,
                    "session_output": str(args.session_output),
                    "key_output": str(args.key_output),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    key = read_session_key(args.key)
    signed_session = _read_json(
        args.session,
        context="fleet acceptance session",
    )
    _assert_session_matches_inputs(signed_session, key=key, inputs=inputs)

    if args.command == "platform":
        _verify_public_follow_up_release(inputs.follow_up)
        release_fleet._verify_standalone_bridge_asset(
            args.repo,
            source_commit=inputs.source_commit,
            follow_up=inputs.follow_up,
            protocol=inputs.protocol,
            bridge_asset=args.bridge_asset,
            bridge_checksum=args.bridge_checksum,
        )
        _verify_public_bridge_release_asset(
            inputs.follow_up,
            bridge_asset=args.bridge_asset,
            bridge_checksum=args.bridge_checksum,
        )
        _create_private_run_root(args.output)
        running_platform = _running_platform()
        execution = collect_platform_runs(
            args.repo,
            output=args.output,
            releases=inputs.releases,
            foundation_tag=inputs.foundation.tag,
            follow_up_tag=inputs.follow_up.tag,
            running_platform=running_platform,
            bridge_asset=args.bridge_asset,
            bridge_checksum=args.bridge_checksum,
        )
        finalized = finalize_live_platform_execution(
            execution,
            repo=args.repo,
            evidence_root=args.output.resolve(),
            inputs=inputs,
            session=signed_session,
            key=key,
        )
        print(
            json.dumps(
                {
                    "outcome": "HISTORIC_PLATFORM_EVIDENCE",
                    "acceptance": False,
                    "platform": running_platform,
                    **execution.counts,
                    "manifest_output": finalized["manifest_output"],
                    "receipt_output": finalized["receipt_output"],
                    "manifest_sha256": finalized["manifest_sha256"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    receipts = [_read_json(path, context=f"platform fleet receipt {path}") for path in args.receipt]
    result = aggregate_platform_evidence(
        signed_session,
        receipts,
        args.manifest,
        key=key,
        inputs=inputs,
    )
    _write_exclusive(args.output, _json_bytes(result), mode=0o444)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except release_fleet.FleetError as error:
        raise SystemExit(f"FAIL: {error}") from error
