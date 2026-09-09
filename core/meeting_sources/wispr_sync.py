"""Fetch new Wispr captures into the landing zone. Runs with no host present.

This is the whole reason the credential is Dex-held. A scheduled job imports
this module, and captures are in the vault before the user opens a session.

The paging rule is the trap worth stating: Wispr's ``since``/``until`` filters
select on when a capture was last **modified**, not when the meeting happened.
They answer "what changed", so they cannot build a catch-up window. This pages
newest-first and stops on its own terms instead.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.meeting_sources import attribution, calendar_lookup, wispr_adapter, wispr_client
from core.meeting_sources.landing_zone import existing_source_ids, write
from core.meeting_sources.wispr_auth import WisprAuthError, WisprNotConnected

logger = logging.getLogger(__name__)

PAGE_SIZE = 25
MAX_PAGES = 20


@dataclass
class SyncResult:
    """What a sweep did. ``unavailable`` is never the same as ``written == 0``."""

    written: int = 0
    skipped: int = 0
    failed: int = 0
    pages: int = 0
    attributed: int = 0
    unavailable: str | None = None
    calendar_unavailable: bool = False
    paths: tuple[Path, ...] = ()

    @property
    def ok(self) -> bool:
        return self.unavailable is None

    def summary(self) -> str:
        if self.unavailable:
            return f"Wispr could not be reached: {self.unavailable}"
        if not self.written:
            return f"No new Wispr captures ({self.skipped} already in the vault)"
        noun = "capture" if self.written == 1 else "captures"
        line = f"{self.written} new Wispr {noun} written ({self.skipped} already present)"
        if self.calendar_unavailable:
            # Never let this read as "these meetings had no attendees".
            return f"{line}; attendance not checked because the calendar could not be read"
        if self.attributed < self.written:
            unresolved = self.written - self.attributed
            return f"{line}; {unresolved} without a matching calendar entry, so attendance is unconfirmed"
        return line


def sync(
    vault_root: Path,
    *,
    days_back: int = 7,
    include_unfinalized: bool = False,
    page_size: int = PAGE_SIZE,
    calendar_events: list[dict] | None = None,
    resolve_attendance: bool = True,
) -> SyncResult:
    """Pull captures newer than ``days_back`` into the landing zone.

    Captures from this source arrive without attendees, so each one is matched
    against the calendar to find out who was actually there. A capture that
    cannot be matched is written anyway and says so: an unmatched capture means
    attendance is unconfirmed, never that the meeting was empty.
    """
    result = SyncResult()

    events = calendar_events
    if resolve_attendance and events is None:
        events = calendar_lookup.events_around(
            vault_root, start_offset_days=-days_back, end_offset_days=1
        )
        if events is None:
            result.calendar_unavailable = True
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    try:
        seen = existing_source_ids(vault_root, wispr_adapter.SOURCE)
    except OSError as error:
        return SyncResult(unavailable=f"the meetings folder could not be read: {error}")

    cursor: str | None = None
    try:
        for _page in range(MAX_PAGES):
            payload = wispr_client.search_meetings(vault_root, limit=page_size, cursor=cursor)
            result.pages += 1
            meetings = payload.get("meetings") or []
            if not meetings:
                break

            reached_cutoff = False
            for item in meetings:
                start = wispr_adapter.parse_timestamp(item.get("start"))
                if start and start < cutoff:
                    # Newest-first, so everything after this is older too.
                    reached_cutoff = True
                    break
                identifier = str(item.get("id") or "")
                if not identifier:
                    result.failed += 1
                    continue
                if identifier in seen:
                    result.skipped += 1
                    continue
                if not include_unfinalized and not item.get("finalized", True):
                    # Still being written. Fetching now would store a partial
                    # note that nothing would ever come back to correct.
                    result.skipped += 1
                    continue
                try:
                    detail = wispr_client.get_meeting(vault_root, identifier)
                    record = wispr_adapter.to_record(detail if isinstance(detail, dict) else item)
                    if resolve_attendance and events:
                        record = attribution.resolve(record, events)
                    path = write(vault_root, record)
                except (wispr_client.WisprUnavailable, WisprAuthError):
                    raise
                except Exception as error:  # noqa: BLE001 - one bad capture must not end the sweep
                    logger.warning("Wispr capture %s could not be written: %s", identifier, error)
                    result.failed += 1
                    continue
                if path is None:
                    result.skipped += 1
                else:
                    result.written += 1
                    if record.attribution_is_reliable:
                        result.attributed += 1
                    result.paths = (*result.paths, path)
                    seen.add(identifier)

            if reached_cutoff or not payload.get("has_more"):
                break
            cursor = payload.get("next_cursor")
            if not cursor:
                break
    except WisprNotConnected as error:
        return SyncResult(unavailable=str(error))
    except (wispr_client.WisprUnavailable, WisprAuthError) as error:
        # Preserve anything already written; report the failure honestly rather
        # than letting a partial sweep look like a quiet week.
        result.unavailable = str(error)

    return result


def main() -> int:
    """Entry point for a scheduled job."""
    import os

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    vault = Path(os.environ.get("VAULT_PATH") or os.environ.get("DEX_VAULT") or ".").resolve()
    outcome = sync(vault)
    print(outcome.summary())
    return 0 if outcome.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
