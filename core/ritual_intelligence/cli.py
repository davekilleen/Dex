"""Minimal CLI for the local Ritual Intelligence runtime."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .service import RitualIntelligenceService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m core.ritual_intelligence")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh = subparsers.add_parser("refresh-calendar", help="Reconcile the configured work calendar")
    refresh.add_argument("--start-offset-days", type=int, default=-28)
    refresh.add_argument("--end-offset-days", type=int, default=14)
    refresh.add_argument("--calendar-name")

    preview = subparsers.add_parser("preview-suggestions", help="Preview ritual suggestions")
    preview.add_argument("--json", action="store_true")

    list_occurrences = subparsers.add_parser("list-occurrences", help="List reconciled meeting occurrences")
    list_occurrences.add_argument("--limit", type=int, default=50)

    for name in ("confirm-ritual", "reject-ritual", "dont-track-series"):
        cmd = subparsers.add_parser(name)
        cmd.add_argument("series_id")

    one_off = subparsers.add_parser("one-off-prep")
    one_off.add_argument("occurrence_id")

    keep_log = subparsers.add_parser("keep-activity-log")
    keep_log.add_argument("occurrence_id")

    ingest_granola = subparsers.add_parser("ingest-granola")
    ingest_granola.add_argument("--days-back", type=int, default=30)

    import_transcript = subparsers.add_parser("import-transcript")
    import_transcript.add_argument("file_path")
    import_transcript.add_argument("--title", required=True)
    import_transcript.add_argument("--started-at")
    import_transcript.add_argument("--ended-at")
    import_transcript.add_argument("--source-event-id")

    subparsers.add_parser("reconcile-transcripts")
    subparsers.add_parser("review-transcripts")

    transcript_not_same = subparsers.add_parser("transcript-not-same")
    transcript_not_same.add_argument("transcript_id")
    transcript_not_same.add_argument("occurrence_id")

    reassign = subparsers.add_parser("reassign-transcript")
    reassign.add_argument("transcript_id")
    reassign.add_argument("occurrence_id")

    create_page = subparsers.add_parser("create-contact-page")
    create_page.add_argument("contact_id")

    not_now = subparsers.add_parser("not-now-contact")
    not_now.add_argument("contact_id")
    not_now.add_argument("occurrence_id")

    never_suggest = subparsers.add_parser("never-suggest-contact")
    never_suggest.add_argument("contact_id")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    service = RitualIntelligenceService()

    if args.command == "refresh-calendar":
        result = service.refresh_calendar(
            start_offset_days=args.start_offset_days,
            end_offset_days=args.end_offset_days,
            calendar_name=args.calendar_name,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "preview-suggestions":
        suggestions = service.list_ritual_suggestions()
        print(json.dumps(suggestions, indent=2, sort_keys=True) if args.json else json.dumps(suggestions, indent=2))
        return 0

    if args.command == "list-occurrences":
        print(json.dumps(service.list_occurrences(limit=args.limit), indent=2, sort_keys=True))
        return 0

    if args.command == "confirm-ritual":
        print(json.dumps(service.confirm_ritual(args.series_id), indent=2, sort_keys=True))
        return 0

    if args.command == "reject-ritual":
        print(json.dumps(service.reject_ritual(args.series_id), indent=2, sort_keys=True))
        return 0

    if args.command == "dont-track-series":
        print(json.dumps(service.disable_series_tracking(args.series_id), indent=2, sort_keys=True))
        return 0

    if args.command == "one-off-prep":
        print(json.dumps(service.generate_one_off_prep(args.occurrence_id), indent=2, sort_keys=True))
        return 0

    if args.command == "keep-activity-log":
        print(json.dumps(service.set_occurrence_activity_log(args.occurrence_id), indent=2, sort_keys=True))
        return 0

    if args.command == "ingest-granola":
        print(json.dumps(service.ingest_granola_local(days_back=args.days_back), indent=2, sort_keys=True))
        return 0

    if args.command == "import-transcript":
        print(
            json.dumps(
                service.import_manual_transcript(
                    file_path=Path(args.file_path),
                    title=args.title,
                    started_at=datetime.fromisoformat(args.started_at) if args.started_at else None,
                    ended_at=datetime.fromisoformat(args.ended_at) if args.ended_at else None,
                    source_event_id=args.source_event_id,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "reconcile-transcripts":
        print(json.dumps(service.reconcile_unmatched_transcripts(), indent=2, sort_keys=True))
        return 0

    if args.command == "review-transcripts":
        print(json.dumps(service.list_unmatched_transcripts(), indent=2, sort_keys=True))
        return 0

    if args.command == "transcript-not-same":
        print(
            json.dumps(
                service.mark_transcript_not_same_meeting(args.transcript_id, args.occurrence_id),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "reassign-transcript":
        print(
            json.dumps(
                service.reassign_transcript_to_occurrence(args.transcript_id, args.occurrence_id),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "create-contact-page":
        print(json.dumps(service.create_contact_page(args.contact_id), indent=2, sort_keys=True))
        return 0

    if args.command == "not-now-contact":
        print(json.dumps(service.dismiss_contact_suggestion(args.contact_id, args.occurrence_id), indent=2, sort_keys=True))
        return 0

    if args.command == "never-suggest-contact":
        print(json.dumps(service.suppress_contact_suggestion(args.contact_id), indent=2, sort_keys=True))
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")
