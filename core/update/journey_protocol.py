"""Closed, release-owned protocol for historic updater fleet journeys.

The protocol is data, not a command language.  Version 1 names two reviewed
adapters and the exact lifecycle service calls they are allowed to make.  Any
new adapter, operation, approval shape, or evidence sequence requires a new
reviewed protocol version.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Mapping

PROTOCOL_RELATIVE = "core/update/journey-protocol-v1.json"
PROTOCOL_VERSION = 1
CONTROLLER = "release-fleet-v1"
SUPPORTED_PLATFORMS = ("darwin",)
BRIDGE_ADAPTER = "pinned-foundation-bridge-v1"
BRIDGE_SOURCE = "scripts/dex_update_bridge.py"
RUNNER_SOURCE = "scripts/release_fleet.py"
EXECUTOR_SOURCE = "scripts/release_fleet_executor.py"
FOLLOW_UP_ADAPTER = "lifecycle-delivered-release-v1"
FOLLOW_UP_OPERATIONS = (
    "deliver_latest_release",
    "build_and_preview_delivered_release",
    "execute_approved_delivered_release",
)
REQUIRED_EVIDENCE = (
    "historic-update-surface",
    "historic-route-refusal",
    "bridge-foundation",
    "foundation-update-surface",
    "foundation-preview",
    "foundation-approval",
    "foundation-receipt",
    "follow-up-installed",
    "follow-up-doctor",
    "follow-up-smoke",
)

_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "controller",
        "platforms",
        "runner",
        "executor",
        "historic_to_foundation",
        "foundation_to_follow_up",
        "evidence",
    }
)
_ARTIFACT_FIELDS = frozenset({"source_path", "sha256"})
_BRIDGE_FIELDS = frozenset({"adapter", "artifact", "foundation", "approval"})
_FOLLOW_UP_FIELDS = frozenset({"adapter", "operations", "approval"})
_APPROVAL_FIELDS = frozenset({"word", "count"})
_IDENTITY_FIELDS = frozenset(
    {"tag", "tag_object", "commit", "tree", "version", "channel"}
)
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_TAG = re.compile(
    r"^dist/release/v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)-"
    r"(?P<short>[0-9a-f]{7,40})$"
)


class JourneyProtocolError(ValueError):
    """A released journey protocol is not closed or machine-safe."""


@dataclass(frozen=True)
class ProtocolArtifact:
    """One source-commit artifact whose exact bytes are protocol authority."""

    source_path: str
    sha256: str


@dataclass(frozen=True)
class BridgeHop:
    """The only permitted historic-to-foundation adapter."""

    adapter: str
    artifact: ProtocolArtifact
    foundation: dict[str, str]
    approval_word: str
    approval_count: int


@dataclass(frozen=True)
class FollowUpHop:
    """The only permitted foundation-to-follow-up lifecycle route."""

    adapter: str
    operations: tuple[str, ...]
    approval_word: str
    approval_count: int


@dataclass(frozen=True)
class UpdateJourneyProtocol:
    """Validated release-owned instructions for the two-hop fleet runner."""

    schema_version: int
    controller: str
    platforms: tuple[str, ...]
    runner: ProtocolArtifact
    executor: ProtocolArtifact
    bridge: BridgeHop
    follow_up: FollowUpHop
    evidence: tuple[str, ...]

    @property
    def foundation(self) -> dict[str, str]:
        return dict(self.bridge.foundation)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise JourneyProtocolError(f"journey protocol repeats field {key!r}")
        result[key] = value
    return result


def _object(value: object, fields: frozenset[str], context: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise JourneyProtocolError(f"{context} has an invalid shape")
    if not all(isinstance(key, str) for key in value):
        raise JourneyProtocolError(f"{context} has an invalid field name")
    return dict(value)


def _artifact(value: object, *, source_path: str, context: str) -> ProtocolArtifact:
    document = _object(value, _ARTIFACT_FIELDS, context)
    if document["source_path"] != source_path:
        raise JourneyProtocolError(f"{context} names an unsupported source artifact")
    digest = document["sha256"]
    if not isinstance(digest, str) or _HEX_64.fullmatch(digest) is None:
        raise JourneyProtocolError(f"{context} has an invalid SHA-256")
    return ProtocolArtifact(source_path, digest)


def _approval(
    value: object,
    *,
    expected_count: int,
    context: str,
) -> tuple[str, int]:
    document = _object(value, _APPROVAL_FIELDS, context)
    if document != {"word": "APPLY", "count": expected_count}:
        raise JourneyProtocolError(f"{context} is not the reviewed approval boundary")
    return "APPLY", expected_count


def _foundation_identity(value: object) -> dict[str, str]:
    document = _object(value, _IDENTITY_FIELDS, "journey protocol foundation")
    if not all(isinstance(document[key], str) for key in _IDENTITY_FIELDS):
        raise JourneyProtocolError("journey protocol foundation identity is malformed")
    identity = {key: str(document[key]) for key in _IDENTITY_FIELDS}
    match = _TAG.fullmatch(identity["tag"])
    if (
        match is None
        or identity["version"] != match.group("version")
        or identity["channel"] != "stable"
        or any(
            _HEX_40.fullmatch(identity[key]) is None
            for key in ("tag_object", "commit", "tree")
        )
        or not identity["commit"].startswith(match.group("short"))
    ):
        raise JourneyProtocolError("journey protocol foundation identity is malformed")
    return identity


def _string_array(value: object, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise JourneyProtocolError(f"{context} must be an array of strings")
    return tuple(value)


def load_update_journey_protocol(source: bytes | str) -> UpdateJourneyProtocol:
    """Parse protocol v1 and reject every unreviewed extension."""

    try:
        value = json.loads(source, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise JourneyProtocolError("journey protocol is not valid JSON") from error
    document = _object(value, _TOP_LEVEL_FIELDS, "journey protocol")
    if document["schema_version"] != PROTOCOL_VERSION:
        raise JourneyProtocolError("journey protocol version is unsupported")
    if document["controller"] != CONTROLLER:
        raise JourneyProtocolError("journey protocol controller is unsupported")
    if (
        _string_array(document["platforms"], context="journey protocol platforms")
        != SUPPORTED_PLATFORMS
    ):
        raise JourneyProtocolError("journey protocol platforms are unsupported")
    if (
        _string_array(document["evidence"], context="journey protocol evidence")
        != REQUIRED_EVIDENCE
    ):
        raise JourneyProtocolError("journey protocol evidence sequence is unsupported")

    runner = _artifact(
        document["runner"],
        source_path=RUNNER_SOURCE,
        context="journey protocol runner",
    )
    executor = _artifact(
        document["executor"],
        source_path=EXECUTOR_SOURCE,
        context="journey protocol executor",
    )
    bridge_document = _object(
        document["historic_to_foundation"],
        _BRIDGE_FIELDS,
        "journey protocol historic hop",
    )
    if bridge_document["adapter"] != BRIDGE_ADAPTER:
        raise JourneyProtocolError("journey protocol historic hop uses an unsupported adapter")
    bridge_word, bridge_count = _approval(
        bridge_document["approval"],
        expected_count=2,
        context="journey protocol historic approval",
    )
    bridge = BridgeHop(
        adapter=BRIDGE_ADAPTER,
        artifact=_artifact(
            bridge_document["artifact"],
            source_path=BRIDGE_SOURCE,
            context="journey protocol bridge artifact",
        ),
        foundation=_foundation_identity(bridge_document["foundation"]),
        approval_word=bridge_word,
        approval_count=bridge_count,
    )

    follow_document = _object(
        document["foundation_to_follow_up"],
        _FOLLOW_UP_FIELDS,
        "journey protocol follow-up hop",
    )
    if follow_document["adapter"] != FOLLOW_UP_ADAPTER:
        raise JourneyProtocolError("journey protocol follow-up hop uses an unsupported adapter")
    if (
        _string_array(
            follow_document["operations"],
            context="journey protocol follow-up operations",
        )
        != FOLLOW_UP_OPERATIONS
    ):
        raise JourneyProtocolError("journey protocol follow-up operations are unsupported")
    follow_word, follow_count = _approval(
        follow_document["approval"],
        expected_count=1,
        context="journey protocol follow-up approval",
    )
    return UpdateJourneyProtocol(
        schema_version=PROTOCOL_VERSION,
        controller=CONTROLLER,
        platforms=SUPPORTED_PLATFORMS,
        runner=runner,
        executor=executor,
        bridge=bridge,
        follow_up=FollowUpHop(
            adapter=FOLLOW_UP_ADAPTER,
            operations=FOLLOW_UP_OPERATIONS,
            approval_word=follow_word,
            approval_count=follow_count,
        ),
        evidence=REQUIRED_EVIDENCE,
    )


__all__ = [
    "BRIDGE_ADAPTER",
    "BRIDGE_SOURCE",
    "CONTROLLER",
    "EXECUTOR_SOURCE",
    "FOLLOW_UP_ADAPTER",
    "FOLLOW_UP_OPERATIONS",
    "JourneyProtocolError",
    "PROTOCOL_RELATIVE",
    "PROTOCOL_VERSION",
    "REQUIRED_EVIDENCE",
    "RUNNER_SOURCE",
    "SUPPORTED_PLATFORMS",
    "UpdateJourneyProtocol",
    "load_update_journey_protocol",
]
