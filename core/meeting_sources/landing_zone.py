"""Write meeting records into the vault's meeting landing zone.

`00-Inbox/Meetings/` is where every fetcher delivers, whatever it fetched from.
Session-start detection and `/process-meetings` already watch this folder, so a
source that writes here needs no detection path of its own. That contract is
the reason a new provider is additive rather than invasive.

Two things this module refuses to do:

**It will not invent attribution.** When a record's provider could not say who
was present, the note says so in terms a reader and a model both act on, rather
than presenting speaker labels as though they were people. A summary that says
"(Speaker 1) will chase the credit" becomes a commitment attached to a real
person two steps downstream, and nobody notices the invention.

**It will not rewrite a note it has already written.** Dedup is on the
`source`/`<source>_id` pair, which is also what the person-page touch tracking
keys on. Re-writing would resurrect notes the user has since edited or marked
processed.
"""
from __future__ import annotations

import re
from pathlib import Path

from core import paths
from core.meeting_sources.record import MeetingRecord

# Derived from the path contract rather than written out, so a vault that moves
# its folders moves this too. Kept relative so callers can pass any root, which
# is what makes the writer testable and lets a sweep target a scratch vault.
MEETINGS_RELATIVE = paths.MEETINGS_DIR.relative_to(paths.VAULT_ROOT)
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_FRONTMATTER = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*\n", re.DOTALL)


def meetings_dir(vault_root: Path) -> Path:
    return vault_root / MEETINGS_RELATIVE


def _slug(title: str) -> str:
    cleaned = _UNSAFE.sub("", title).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:60].strip() or "Meeting"


def note_path(vault_root: Path, record: MeetingRecord) -> Path:
    return meetings_dir(vault_root) / f"{record.local_date} - {_slug(record.title or 'Meeting')}.md"


def existing_source_ids(vault_root: Path, source: str) -> set[str]:
    """Every `<source>_id` already present in the landing zone.

    Reads frontmatter only, and tolerates notes that have none: hand-dropped
    files are valid here and must not break a sweep.
    """
    key = f"{source}_id"
    found: set[str] = set()
    folder = meetings_dir(vault_root)
    if not folder.is_dir():
        return found
    for path in folder.rglob("*.md"):
        try:
            head = path.read_text(encoding="utf-8")[:2000]
        except (OSError, UnicodeDecodeError):
            continue
        match = _FRONTMATTER.match(head)
        if not match:
            continue
        for line in match.group("body").splitlines():
            name, _, value = line.partition(":")
            if name.strip() == key and value.strip():
                found.add(value.strip().strip("\"'"))
    return found


def render(record: MeetingRecord) -> str:
    """The note as it lands in the vault."""
    lines = [
        "---",
        f"date: {record.local_date}",
        "type: meeting",
        # Two separate keys, exactly these names. Upstream dedup and person-page
        # touch tracking run on `source` plus `<source>_id`; folding the id into
        # the source line makes the note look new on every sweep.
        f"source: {record.source}",
        f"{record.source}_id: {record.source_id}",
        f"start: {record.start.isoformat()}",
    ]
    if record.end:
        lines.append(f"end: {record.end.isoformat()}")
    if record.attendees:
        lines.append("attendees:")
        for person in record.attendees:
            label = person.email or person.name
            lines.append(f"  - {label}")
    lines.append(f"has_transcript: {str(record.has_transcript).lower()}")
    lines.append(f"attribution_resolved: {str(record.attribution_is_reliable).lower()}")
    if record.extra.get("title_was_derived"):
        lines.append("title_derived: true")
    lines.append("ai_analyzed: false")
    lines.append("---")
    lines.append("")
    lines.append(f"# {record.title}")
    lines.append("")

    if not record.attribution_is_reliable:
        lines += [
            "> **Attendance unresolved.** This capture arrived without attendee names, so any",
            "> speaker labels below identify turns in the recording, not people. Do not assign",
            "> an action, a decision or a quote to anyone on the strength of this note alone.",
            "> Match it against the calendar entry for this time first.",
            "",
        ]
    if record.extra.get("title_was_derived"):
        lines += [
            "> Title derived from the summary, because this source supplied none.",
            "",
        ]

    lines.append(record.body if record.body else "_This capture has no summary._")
    lines.append("")

    if record.action_items:
        lines.append("### For Me")
        lines.append("")
        for item in record.action_items:
            lines.append(f"- [ ] {item}")
        lines.append("")
    return "\n".join(lines)


def write(vault_root: Path, record: MeetingRecord, *, overwrite: bool = False) -> Path | None:
    """Write one record. Returns the path, or None when it was already there."""
    folder = meetings_dir(vault_root)
    folder.mkdir(parents=True, exist_ok=True)
    if not overwrite and record.source_id in existing_source_ids(vault_root, record.source):
        return None

    path = note_path(vault_root, record)
    if path.exists() and not overwrite:
        # Same day, same derived title, different capture. Keep both rather
        # than silently dropping one.
        path = path.with_name(f"{path.stem} ({record.source_id[:8]}){path.suffix}")

    tmp = path.with_suffix(".tmp")
    tmp.write_text(render(record), encoding="utf-8")
    tmp.replace(path)
    return path
