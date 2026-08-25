"""Read-only latest proactive-health surface for SessionStart.

This module never refreshes Doctor, writes a marker, changes notification
preferences, or repairs a vault.  It only reads the latest complete snapshot
and its bounded history, so a failed or partial refresh cannot replace the
last known complete status.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from core.health.snapshot import HealthSnapshot, HealthStore, HealthStoreCorruption

STALE_AFTER_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class SessionHealthSurface:
    """The policy decision rendered by the SessionStart hook."""

    state: str
    snapshot: HealthSnapshot | None = None
    previous_snapshot: HealthSnapshot | None = None
    newly_critical: bool = False
    recovered: bool = False
    stale: bool = False
    reason: str | None = None


def _now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)


def read_session_health(
    vault_root: str | Path,
    *,
    now: datetime | None = None,
) -> SessionHealthSurface:
    """Read the latest complete state and apply the fixed v1 session policy."""

    store = HealthStore(vault_root)
    try:
        history = store.read_history(limit=2)
    except (HealthStoreCorruption, OSError, ValueError) as error:
        return SessionHealthSurface(
            state="unknown",
            reason=f"latest health snapshot could not be read: {error}",
        )

    if not history:
        # Quiet preparing state: the first complete snapshot has not landed.
        return SessionHealthSurface(state="preparing")

    latest = history[0]
    previous = history[1] if len(history) > 1 else None
    current = _now(now)
    completed = datetime.fromisoformat(latest.completed_at.replace("Z", "+00:00"))
    age_seconds = (current - completed).total_seconds()
    stale = age_seconds < 0 or age_seconds > STALE_AFTER_SECONDS
    newly_critical = latest.overall_status == "critical" and (
        previous is None or previous.overall_status != "critical"
    )
    recovered = latest.overall_status != "critical" and (
        previous is not None and previous.overall_status == "critical"
    )
    return SessionHealthSurface(
        state=latest.overall_status,
        snapshot=latest,
        previous_snapshot=previous,
        newly_critical=newly_critical,
        recovered=recovered,
        stale=stale,
    )


def _snapshot_stamp(snapshot: HealthSnapshot) -> str:
    return snapshot.completed_at


LEARNED_CHECK_ID = "doctor.core/learned-automations"


def learned_automations_line(snapshot: HealthSnapshot | None) -> str:
    """The one line session start may say about the person's own automations.

    Read straight from the snapshot the Doctor published — this surface never
    computes a verdict and never composes its own copy.  The disclosure is
    already folded into that detail by ``core/health/learned.compose_surface``,
    so an alarm cannot reach the person here without it.  Silence when there is
    nothing to watch, or when the check is absent from an older snapshot.
    """
    if snapshot is None:
        return ""
    for result in snapshot.report.results:
        if result.id != LEARNED_CHECK_ID:
            continue
        if result.verdict != "OK" or not result.detail.strip():
            return ""
        return f"🗂️ Your own automations: {result.detail}\n"
    return ""


def format_session_health(
    vault_root: str | Path,
    *,
    now: datetime | None = None,
) -> str:
    """Render the fixed v1 SessionStart surface; preparing remains silent."""

    surface = read_session_health(vault_root, now=now)
    if surface.state == "preparing":
        return ""
    if surface.snapshot is None:
        return "🩺 Dex health: unavailable — opening the general /dex-doctor flow is safe.\n"

    snapshot_stamp = _snapshot_stamp(surface.snapshot)
    # Learned findings are the person's own jobs, never Dex's health. They are
    # appended below the status line and can never change it.
    learned = learned_automations_line(surface.snapshot)
    if surface.state == "critical" and surface.newly_critical:
        return "\n".join(
            (
                "--- 🚨 Dex health: critical ---",
                f"Latest complete snapshot: {snapshot_stamp}",
                "Run /dex-doctor for diagnosis and the fix.",
                "---",
                "",
            )
        ) + learned
    if surface.state == "critical":
        return (
            "🩺 Dex health: critical (ongoing) — "
            f"latest complete snapshot {snapshot_stamp}; run /dex-doctor to investigate.\n"
        ) + learned
    if surface.state == "healthy" and surface.recovered:
        return (
            f"🩺 Dex health: healthy (recovered) — latest complete snapshot {snapshot_stamp}.\n"
        ) + learned
    return (
        f"🩺 Dex health: {surface.state} — latest complete snapshot {snapshot_stamp}.\n"
    ) + learned


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render Dex's read-only proactive health SessionStart surface.")
    parser.add_argument("--vault", type=Path, required=True)
    args = parser.parse_args(argv)
    print(format_session_health(args.vault), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
