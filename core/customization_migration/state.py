"""Pure v0 customization-migration state projection."""

from __future__ import annotations

from enum import Enum
from typing import Iterable


class MigrationState(str, Enum):
    NOT_ASSESSED = "not-assessed"
    ASSESSMENT_READY = "assessment-ready"
    CAPSULE_PREVIEWED = "capsule-previewed"
    CAPSULE_CREATED = "capsule-created"
    TARGET_READY = "target-ready"
    REGENERATION_PROPOSED = "regeneration-proposed"
    REGENERATION_STAGED = "regeneration-staged"
    VERIFICATION_PASSED = "verification-passed"
    VERIFICATION_BLOCKED = "verification-blocked"
    ACTIVATION_PREVIEWED = "activation-previewed"
    ACTIVATED = "activated"
    REWOUND = "rewound"
    ABANDONED = "abandoned"
    RECOVERY_REQUIRED = "recovery-required"
    UNKNOWN = "unknown"


ALLOWED_TRANSITIONS = frozenset(
    {
        (MigrationState.NOT_ASSESSED, MigrationState.ASSESSMENT_READY),
        (MigrationState.ASSESSMENT_READY, MigrationState.CAPSULE_PREVIEWED),
        (MigrationState.CAPSULE_PREVIEWED, MigrationState.CAPSULE_CREATED),
        (MigrationState.CAPSULE_CREATED, MigrationState.TARGET_READY),
        (MigrationState.TARGET_READY, MigrationState.REGENERATION_PROPOSED),
        (
            MigrationState.REGENERATION_PROPOSED,
            MigrationState.REGENERATION_STAGED,
        ),
        (
            MigrationState.REGENERATION_STAGED,
            MigrationState.VERIFICATION_PASSED,
        ),
        (
            MigrationState.REGENERATION_STAGED,
            MigrationState.VERIFICATION_BLOCKED,
        ),
        (
            MigrationState.VERIFICATION_BLOCKED,
            MigrationState.REGENERATION_PROPOSED,
        ),
        (
            MigrationState.VERIFICATION_PASSED,
            MigrationState.ACTIVATION_PREVIEWED,
        ),
        (MigrationState.ACTIVATION_PREVIEWED, MigrationState.ACTIVATED),
        (MigrationState.ACTIVATED, MigrationState.REWOUND),
        (MigrationState.ASSESSMENT_READY, MigrationState.ABANDONED),
        (MigrationState.CAPSULE_CREATED, MigrationState.ABANDONED),
    }
)


def is_allowed_transition(
    current: MigrationState,
    target: MigrationState,
) -> bool:
    return (current, target) in ALLOWED_TRANSITIONS


def validate_transition(
    current: MigrationState,
    target: MigrationState,
) -> None:
    if not isinstance(current, MigrationState):
        raise TypeError("current must be MigrationState")
    if not isinstance(target, MigrationState):
        raise TypeError("target must be MigrationState")
    if not is_allowed_transition(current, target):
        raise ValueError(
            f"migration transition is not allowed: {current.value} -> {target.value}"
        )


class MigrationEvent(str, Enum):
    ASSESSED = "assessed"
    CAPSULE_PREVIEWED = "capsule-previewed"
    CAPSULE_CREATED = "capsule-created"
    TARGET_VERIFIED = "target-verified"
    REGENERATION_PROPOSED = "regeneration-proposed"
    REGENERATION_STAGED = "regeneration-staged"
    VERIFICATION_PASSED = "verification-passed"
    VERIFICATION_BLOCKED = "verification-blocked"
    ACTIVATION_PREVIEWED = "activation-previewed"
    ACTIVATED = "activated"
    REWOUND = "rewound"
    ABANDONED = "abandoned"


_EVENT_TARGETS = {
    MigrationEvent.ASSESSED: MigrationState.ASSESSMENT_READY,
    MigrationEvent.CAPSULE_PREVIEWED: MigrationState.CAPSULE_PREVIEWED,
    MigrationEvent.CAPSULE_CREATED: MigrationState.CAPSULE_CREATED,
    MigrationEvent.TARGET_VERIFIED: MigrationState.TARGET_READY,
    MigrationEvent.REGENERATION_PROPOSED: MigrationState.REGENERATION_PROPOSED,
    MigrationEvent.REGENERATION_STAGED: MigrationState.REGENERATION_STAGED,
    MigrationEvent.VERIFICATION_PASSED: MigrationState.VERIFICATION_PASSED,
    MigrationEvent.VERIFICATION_BLOCKED: MigrationState.VERIFICATION_BLOCKED,
    MigrationEvent.ACTIVATION_PREVIEWED: MigrationState.ACTIVATION_PREVIEWED,
    MigrationEvent.ACTIVATED: MigrationState.ACTIVATED,
    MigrationEvent.REWOUND: MigrationState.REWOUND,
    MigrationEvent.ABANDONED: MigrationState.ABANDONED,
}


def project_state(events: Iterable[str]) -> MigrationState:
    """Project journal evidence without raising or resetting corrupt evidence."""
    state = MigrationState.NOT_ASSESSED
    try:
        for raw_event in events:
            event = MigrationEvent(raw_event)
            target = _EVENT_TARGETS[event]
            if not is_allowed_transition(state, target):
                return MigrationState.RECOVERY_REQUIRED
            state = target
    except (TypeError, ValueError):
        return MigrationState.RECOVERY_REQUIRED
    return state


__all__ = [
    "ALLOWED_TRANSITIONS",
    "MigrationEvent",
    "MigrationState",
    "is_allowed_transition",
    "project_state",
    "validate_transition",
]
