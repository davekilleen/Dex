"""Read captured learnings, cluster them, and propose where each should go.

Written as a starting point for the routing step described in #503 by
@joshm-simril, against the shape @davekilleen specified there. The routing table
below is Josh's, not mine.

**What this module deliberately does not do: apply anything.** The requirement
that Dex never silently rewrites its own instructions means the edit must be
shown and confirmed before it lands, and confirmation belongs in the skill that
can hold a conversation. Everything here is analysis and bookkeeping: parse the
entries, group the ones that share a cause, propose a destination, and record
the outcome once a human has decided.

The split matters. Clustering and destination-proposal are mechanical and
testable; deciding whether a proposed edit is right is judgement. Mixing them
would put an unreviewable decision inside a function that looks like a helper.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

LEARNINGS_RELATIVE = Path("System") / "Session_Learnings"

PENDING = "pending"
IMPLEMENTED = "implemented"
DROPPED = "dropped"

_HEADING = re.compile(r"^##\s+\[?(?P<time>\d{1,2}:\d{2})\]?\s*[-–]\s*(?P<title>.+?)\s*$")
_STATUS = re.compile(r"^\*\*Status:\*\*\s*(?P<status>\w+)", re.IGNORECASE)
_DAY_FILE = re.compile(r"^(?P<day>\d{4}-\d{2}-\d{2})\.md$")

# Josh's routing table from #503, kept as data so it can be edited without
# touching code -- which was one of his own open questions.
DESTINATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "behavioural",
        ("stop ", "don't", "do not", "always", "never", "you keep", "instead of",
         "prefer", "correction", "over-infer", "assume", "check first", "verify"),
    ),
    (
        "skill-defect",
        ("skill", "/daily-plan", "/daily-review", "/week-plan", "/week-review",
         "/process-meetings", "/meeting-prep", "step ", "the flow"),
    ),
    (
        "environment-fact",
        ("mcp", "hook", "launchd", "permission", "index", "timezone", "macos",
         "path", "environment", "tenant"),
    ),
    (
        "code-defect",
        ("traceback", "exit code", "returns", "crash", "exception", "silently",
         "regex", "parser", "null", "none"),
    ),
)

DESTINATION_TARGETS = {
    "behavioural": "CLAUDE-custom.md user-extensions block, and/or a memory file with its index line",
    "skill-defect": "that skill's SKILL.md, as a real numbered step rather than prose",
    "environment-fact": "the matching file in .claude/reference/",
    "code-defect": "fix directly if small and safe, otherwise capture as a backlog idea",
    "unclassified": "needs a human read; no destination proposed",
}


@dataclass
class Entry:
    """One captured learning, with enough location to rewrite its status."""

    day: date
    time: str
    title: str
    body: str
    status: str
    source_file: Path
    line_number: int

    @property
    def is_pending(self) -> bool:
        return self.status.lower() == PENDING

    def age_days(self, today: date | None = None) -> int:
        return ((today or date.today()) - self.day).days

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}"


@dataclass
class Cluster:
    """Entries that appear to share a cause, and where they should go.

    Clusters are the point. Josh's observation was that eight related entries
    about silent failure became one rule, not eight edits, and that the value
    is in the grouping rather than the volume.
    """

    kind: str
    entries: list[Entry] = field(default_factory=list)

    @property
    def destination(self) -> str:
        return DESTINATION_TARGETS[self.kind]

    @property
    def oldest_days(self) -> int:
        return max((e.age_days() for e in self.entries), default=0)


def _classify(text: str) -> str:
    lowered = text.lower()
    best, score = "unclassified", 0
    for kind, needles in DESTINATIONS:
        hits = sum(1 for n in needles if n in lowered)
        if hits > score:
            best, score = kind, hits
    return best


def parse_file(path: Path) -> list[Entry]:
    """Entries in one day file. A malformed file yields nothing, never raises."""
    match = _DAY_FILE.match(path.name)
    if not match:
        return []
    try:
        day = datetime.strptime(match.group("day"), "%Y-%m-%d").date()
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError, UnicodeDecodeError):
        return []

    entries: list[Entry] = []
    current: dict | None = None
    body: list[str] = []

    def flush() -> None:
        if current is None:
            return
        entries.append(
            Entry(
                day=day,
                time=current["time"],
                title=current["title"],
                body="\n".join(body).strip(),
                status=current["status"],
                source_file=path,
                line_number=current["line"],
            )
        )

    for index, line in enumerate(lines, start=1):
        heading = _HEADING.match(line)
        if heading:
            flush()
            body = []
            current = {
                "time": heading.group("time"),
                "title": heading.group("title"),
                "status": PENDING,
                "line": index,
            }
            continue
        if current is None:
            continue
        status = _STATUS.match(line.strip())
        if status:
            current["status"] = status.group("status").lower()
            continue
        body.append(line)
    flush()
    return entries


def read_all(vault_root: Path) -> list[Entry]:
    folder = vault_root / LEARNINGS_RELATIVE
    if not folder.is_dir():
        return []
    entries: list[Entry] = []
    for path in sorted(folder.glob("*.md")):
        entries.extend(parse_file(path))
    return entries


def pending(entries: list[Entry]) -> list[Entry]:
    return [e for e in entries if e.is_pending]


def cluster(entries: list[Entry]) -> list[Cluster]:
    """Group pending entries by proposed destination, oldest cluster first.

    Grouping is by destination rather than by topic similarity on purpose: two
    entries that belong in the same file are worth reviewing together even when
    they read differently, and one that belongs somewhere else is not made
    easier to handle by sitting next to them.
    """
    buckets: dict[str, Cluster] = {}
    for entry in pending(entries):
        kind = _classify(entry.text)
        buckets.setdefault(kind, Cluster(kind=kind)).entries.append(entry)
    return sorted(buckets.values(), key=lambda c: c.oldest_days, reverse=True)


def should_review(
    entries: list[Entry], *, min_count: int = 10, max_age_days: int = 14, today: date | None = None
) -> tuple[bool, str]:
    """Whether a review is due, and the reason to show the user.

    Volume or age, per @davekilleen's spec. Age matters independently because a
    single correction left for a fortnight is a worse signal than ten from this
    morning, and a count-only trigger never fires on a slow, steady leak.
    """
    outstanding = pending(entries)
    if not outstanding:
        return False, "nothing pending"
    oldest = max(e.age_days(today) for e in outstanding)
    if len(outstanding) >= min_count:
        return True, f"{len(outstanding)} learnings pending"
    if oldest >= max_age_days:
        return True, f"oldest pending learning is {oldest} days old"
    return False, f"{len(outstanding)} pending, oldest {oldest} days"


def set_status(entry: Entry, status: str, detail: str, *, today: date | None = None) -> bool:
    """Record an outcome against one entry, in place. Returns whether it changed.

    Only ever called after a human has confirmed the edit. The status line
    carries where it went or why it was dropped, so a falling count means
    something was installed rather than something aged out of view.
    """
    if status not in (IMPLEMENTED, DROPPED):
        raise ValueError(f"status must be {IMPLEMENTED!r} or {DROPPED!r}, not {status!r}")
    stamp = (today or date.today()).isoformat()
    replacement = f"**Status:** {status} ({stamp} — {detail})"

    try:
        lines = entry.source_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False

    # Search forward from the heading for this entry's own status line, so two
    # entries in one file can never have their statuses crossed.
    for index in range(entry.line_number, len(lines)):
        if _HEADING.match(lines[index]):
            break
        if _STATUS.match(lines[index].strip()):
            lines[index] = replacement
            try:
                entry.source_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except OSError:
                return False
            entry.status = status
            return True
    return False
