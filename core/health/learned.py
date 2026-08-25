"""Learned promises: the person's own scheduled jobs, watched the way Dex's are.

The shipped register (``core/health/promises.py``) answers "did Dex's own job
succeed?" for the five jobs Dex ships.  A user's own launchd job got only a
disclaimer — "checked for loading only, not freshness" — and a daily job that
silently stopped firing could go unnoticed for months.  That is the failure
this module closes.

Each vault-pointing job the person installed acquires a **learned promise**: a
cadence read from its plist (never guessed) and a receipt chosen best-first.
The shipped verdict vocabulary judges it — ``kept`` / ``never`` / ``broken`` —
and the states that are *not* judgements say so plainly rather than pretending
to one: ``unauditable``, ``no-rhythm-yet``, ``pending``, ``stopped-by-user``.

Four rules keep this honest, and none of them may be relaxed:

* **Declared beats inferred, still.**  A learned record can never satisfy the
  shipped build gate.  ``PROMISES`` stays frozen and CI-gated; this module is
  runtime state in the user's vault and the gate never reads it.
* **Activity is not health.**  A receipt that only proves the job *ran*
  carries ``activity_only=True`` and every line about it says "ran", never
  "succeeded" — the v1.84.0 lesson, applied to the person's jobs too.
* **Never fake a cadence.**  A job with no readable schedule stays in
  ``no-rhythm-yet`` until observed runs show a stable interval.  Coverage that
  looks complete but is invented is worse than a disclaimer.
* **Read-only.**  Discovery and audit write nothing outside
  ``System/.dex/health/``, and every write there goes through the lifecycle
  transaction boundary.  Credential-bearing files are excluded *before* their
  bytes are read.

Divergence from the shipped auditor, deliberate.  ``promises.audit_promise``
is a stateless cadence-vs-receipt check that absorbs sleep/wake by padding the
cadence ("Cadence is the promise, not the schedule", promises.py:62-64).  Dex
declares its own cadences and can pad them.  A schedule *read* from someone
else's plist cannot be padded — 09:00 daily means 09:00 — so this auditor works
from due times plus an explicit grace window instead.  Where the read schedule
is coarse the grace scales with the interval, which is the shipped padding idea
kept where it still applies.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from core.lifecycle import service
from core.transaction.engine import PlanEntry

RECORD_CONTRACT = "dex.health.learned-promise/v1"
REGISTER_CONTRACT = "dex.health.learned-register/v1"

HEALTH_RELATIVE = PurePosixPath("System/.dex/health")
LEARNED_RELATIVE = HEALTH_RELATIVE / "learned-promises"
REGISTER_FILENAME = "_register.json"

WATCH_STATES = frozenset({"watching", "stopped-by-user"})
SCHEDULE_SOURCES = frozenset(
    {"StartCalendarInterval", "StartInterval", "observed", "none"}
)
RECEIPT_PROVENANCES = frozenset(
    {"script-output", "launchd-stdout", "launchd-stderr", "none"}
)

#: Judgement states borrowed verbatim from the shipped register, plus the
#: honest non-judgements.  A non-judgement never surfaces as an alarm.
JUDGEMENTS = frozenset({"kept", "never", "broken"})
NON_JUDGEMENTS = frozenset(
    {"unauditable", "no-rhythm-yet", "pending", "stopped-by-user"}
)

#: Two consecutive misses is a dead job.  One is laptop life.
MISS_THRESHOLD = 2
#: Grace after a due time, sized for a machine that sleeps through 09:00 and
#: runs the coalesced job on wake.
BASE_GRACE = timedelta(hours=4)
#: Where the read schedule is coarse, grace scales with it instead.
COARSE_GRACE_FRACTION = 0.25
#: Bounds on the script reader.  Anything larger, or anything that is not
#: plainly a shell script, is not read at all.
MAX_SCRIPT_BYTES = 64 * 1024
#: Observed-history learning needs this many runs before it claims a rhythm.
MIN_OBSERVED_RUNS = 4
MAX_OBSERVED_RUNS = 16
#: A sweep never enumerates more due times than this, whatever the schedule.
MAX_DUE_TIMES = 512

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}-[0-9a-f]{12}$")
_SLUG_BODY_RE = re.compile(r"[^a-z0-9._-]+")

_SHELL_INTERPRETERS = ("sh", "bash", "zsh", "dash", "ksh")
_REDIRECT_RE = re.compile(r">>?\s*(\"[^\"]*\"|'[^']*'|[^\s;&|<>()]+)")
_WRITING_COMMAND_RE = re.compile(
    r"\b(?:tee|touch)\s+(?:-[A-Za-z]+\s+)*(\"[^\"]*\"|'[^']*'|[^\s;&|<>()]+)"
)
_UNSAFE_TOKEN = ("$(", "`", "*", "?", "[", "]", "{", "}")

DISCLOSURE_LINE = (
    "Dex noticed these scheduled jobs of yours and has been keeping an eye on "
    "them — reading only, on your Mac, so it can tell you when one stops "
    "running. Keep watching, or stop?"
)
SCOPE_NOTE = (
    "launchd (macOS) scheduled jobs only; cron and systemd jobs are not "
    "watched in v1"
)


# --------------------------------------------------------------------------- #
# time helpers
# --------------------------------------------------------------------------- #


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware(parsed)


def _stamp(value: datetime) -> str:
    return _aware(value).isoformat()


# --------------------------------------------------------------------------- #
# Lot 1 — the record
# --------------------------------------------------------------------------- #


def record_slug(label: str) -> str:
    """Return a filename that a hostile launchd Label can never escape.

    A ``Label`` is arbitrary text: ``../../evil`` is a legal one.  The slug is
    a bounded charset plus a hash of the exact label, so traversal is
    impossible and two labels differing only in case cannot collide.
    """
    text = str(label)
    digest = hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()[:12]
    body = _SLUG_BODY_RE.sub("-", text.lower()).strip("-.")[:79]
    if not body or not body[0].isalnum():
        body = f"job{body}" if body else "job"
        body = body[:79]
    return f"{body}-{digest}"


@dataclass(frozen=True)
class LearnedPromise:
    """One learned job's contract, as read — never as guessed."""

    label: str
    plist_relative_path: str
    schedule_source: str
    schedule: Mapping[str, Any] = field(default_factory=dict)
    receipt_kind: str = "file-activity"
    receipt_path: str | None = None
    receipt_provenance: str = "none"
    activity_only: bool = False
    consecutive_misses: int = 0
    last_receipt_at: str | None = None
    watch_since: str = ""
    last_evaluated_at: str | None = None
    observed_runs: tuple[str, ...] = ()
    watch_state: str = "watching"
    #: The shell script this job runs, when Dex could read one that was not
    #: credential-bearing.  Lot 5's offer needs it; nothing else does.
    program_path: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("a learned promise needs the job's launchd label")
        if self.schedule_source not in SCHEDULE_SOURCES:
            raise ValueError(f"unknown schedule source {self.schedule_source!r}")
        if self.receipt_provenance not in RECEIPT_PROVENANCES:
            raise ValueError(f"unknown receipt provenance {self.receipt_provenance!r}")
        if self.watch_state not in WATCH_STATES:
            raise ValueError(f"unknown watch state {self.watch_state!r}")
        if self.receipt_provenance == "none" and self.receipt_path is not None:
            raise ValueError("a job with no receipt must not carry a receipt path")
        if self.receipt_provenance != "none" and not self.receipt_path:
            raise ValueError("a chosen receipt must name its path")

    @property
    def slug(self) -> str:
        return record_slug(self.label)

    @property
    def display_name(self) -> str:
        """The job in the person's terms: their label, last segment first."""
        tail = self.label.rsplit(".", 1)[-1]
        return tail or self.label

    def replace(self, **changes: Any) -> "LearnedPromise":
        return replace(self, **changes)

    def is_auditable(self) -> bool:
        """Can this job be judged honestly at all?"""
        if self.receipt_provenance == "none":
            return False
        if self.schedule_source == "observed" and not self.schedule.get(
            "interval_seconds"
        ):
            return False
        return self.schedule_source != "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": RECORD_CONTRACT,
            "label": self.label,
            "plist_relative_path": self.plist_relative_path,
            "schedule_source": self.schedule_source,
            "schedule": dict(self.schedule),
            "receipt_kind": self.receipt_kind,
            "receipt_path": self.receipt_path,
            "receipt_provenance": self.receipt_provenance,
            "activity_only": self.activity_only,
            "consecutive_misses": self.consecutive_misses,
            "last_receipt_at": self.last_receipt_at,
            "watch_since": self.watch_since,
            "last_evaluated_at": self.last_evaluated_at,
            "observed_runs": list(self.observed_runs),
            "watch_state": self.watch_state,
            "program_path": self.program_path,
        }

    @classmethod
    def from_dict(cls, value: object) -> "LearnedPromise":
        if not isinstance(value, Mapping):
            raise ValueError("a learned record must be a JSON object")
        if value.get("contract") != RECORD_CONTRACT:
            raise ValueError("unsupported learned record contract")
        schedule = value.get("schedule")
        runs = value.get("observed_runs")
        return cls(
            label=value["label"],
            plist_relative_path=str(value.get("plist_relative_path") or ""),
            schedule_source=str(value.get("schedule_source") or "none"),
            schedule=dict(schedule) if isinstance(schedule, Mapping) else {},
            receipt_kind=str(value.get("receipt_kind") or "file-activity"),
            receipt_path=value.get("receipt_path"),
            receipt_provenance=str(value.get("receipt_provenance") or "none"),
            activity_only=bool(value.get("activity_only")),
            consecutive_misses=int(value.get("consecutive_misses") or 0),
            last_receipt_at=value.get("last_receipt_at"),
            watch_since=str(value.get("watch_since") or ""),
            last_evaluated_at=value.get("last_evaluated_at"),
            observed_runs=tuple(runs) if isinstance(runs, list) else (),
            watch_state=str(value.get("watch_state") or "watching"),
            program_path=value.get("program_path"),
        )


@dataclass(frozen=True)
class LearnedRegister:
    """Register-level state: whether the person has been told, and answered."""

    disclosed_at: str | None = None
    disclosure_acknowledged_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": REGISTER_CONTRACT,
            "disclosed_at": self.disclosed_at,
            "disclosure_acknowledged_at": self.disclosure_acknowledged_at,
        }

    @classmethod
    def from_dict(cls, value: object) -> "LearnedRegister":
        if not isinstance(value, Mapping) or value.get("contract") != REGISTER_CONTRACT:
            return cls()
        return cls(
            disclosed_at=value.get("disclosed_at"),
            disclosure_acknowledged_at=value.get("disclosure_acknowledged_at"),
        )


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


class LearnedStore:
    """Vault-local learned records, written only through the lifecycle boundary.

    ``System/.dex/health`` is already classified ``generated`` by the portable
    contract (``generated-health-state``), so these writes need no new
    transaction operation — the ordinary ``update`` operation authorizes them,
    exactly as it does the snapshot store next door.
    """

    def __init__(self, vault_root: str | Path) -> None:
        self.root = Path(vault_root).resolve()

    @property
    def records_dir(self) -> Path:
        return self.root / LEARNED_RELATIVE

    @property
    def register_path(self) -> Path:
        return self.records_dir / REGISTER_FILENAME

    def ensure_directory(self) -> None:
        self.records_dir.mkdir(parents=True, exist_ok=True)

    # -- reads ------------------------------------------------------------- #

    def load(
        self,
    ) -> tuple[LearnedRegister, tuple[LearnedPromise, ...], tuple[str, ...]]:
        """Return the register, the readable records, and the corrupt filenames.

        A corrupt record is *named*, never dropped and never guessed at.  The
        caller reports it as unauditable; the next sweep re-drafts it.
        """
        register = LearnedRegister()
        records: list[LearnedPromise] = []
        corrupt: list[str] = []
        if not self.records_dir.is_dir():
            return register, (), ()
        for path in sorted(self.records_dir.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                if path.name != REGISTER_FILENAME:
                    corrupt.append(path.name)
                continue
            if path.name == REGISTER_FILENAME:
                register = LearnedRegister.from_dict(payload)
                continue
            try:
                records.append(LearnedPromise.from_dict(payload))
            except (ValueError, KeyError, TypeError):
                corrupt.append(path.name)
        return register, tuple(records), tuple(corrupt)

    def get(self, label: str) -> LearnedPromise | None:
        for record in self.load()[1]:
            if record.label == label:
                return record
        return None

    # -- writes ------------------------------------------------------------ #

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _entry(self, path: Path, payload: Mapping[str, Any]) -> PlanEntry | None:
        content = _canonical(payload)
        relative = self._relative(path)
        if not path.exists():
            return PlanEntry(relative, content, mode=0o600, expected_absent=True)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"learned target is not a regular file: {relative}")
        current = path.read_bytes()
        if current == content:
            return None
        return PlanEntry(
            relative,
            content,
            mode=0o600,
            expected_current_sha256=hashlib.sha256(current).hexdigest(),
        )

    def _commit(self, plan: list[PlanEntry], *, purpose: str) -> None:
        if not plan:
            return
        self.ensure_directory()
        preview = service._preview_transaction(self.root, plan, purpose=purpose)
        service._execute_approved_transaction(
            self.root,
            plan,
            purpose=purpose,
            approved_token=preview["approval_token"],
        )

    def put(self, record: LearnedPromise) -> None:
        self.put_many([record])

    def put_many(
        self,
        records: Iterable[LearnedPromise],
        *,
        register: LearnedRegister | None = None,
    ) -> None:
        """One transaction for a whole sweep — never one per job."""
        self.ensure_directory()
        plan: list[PlanEntry] = []
        for record in records:
            entry = self._entry(
                self.records_dir / f"{record.slug}.json", record.to_dict()
            )
            if entry is not None:
                plan.append(entry)
        if register is not None:
            entry = self._entry(self.register_path, register.to_dict())
            if entry is not None:
                plan.append(entry)
        self._commit(plan, purpose="health-learned-sweep")

    def set_watch_state(self, label: str, state: str, *, now: datetime) -> None:
        """Keep or stop, at the person's word.  Stop is real; keep is a reset."""
        if state not in WATCH_STATES:
            raise ValueError(f"unknown watch state {state!r}")
        record = self.get(label)
        if record is None:
            raise KeyError(label)
        if state == "watching" and record.watch_state != "watching":
            record = record.replace(
                watch_state=state,
                watch_since=_stamp(now),
                consecutive_misses=0,
                last_evaluated_at=None,
            )
        else:
            record = record.replace(watch_state=state)
        register = self.load()[0]
        if register.disclosure_acknowledged_at is None:
            register = LearnedRegister(
                disclosed_at=register.disclosed_at or _stamp(now),
                disclosure_acknowledged_at=_stamp(now),
            )
        self.put_many([record], register=register)

    def record_disclosure_shown(self, *, now: datetime) -> None:
        """Stamp the disclosure only after a surface has actually carried it.

        If this write fails the disclosure repeats.  The failure mode is a
        repeated disclosure, never a silent alarm.
        """
        register = self.load()[0]
        if register.disclosed_at is not None:
            return
        self.put_many([], register=replace(register, disclosed_at=_stamp(now)))


# --------------------------------------------------------------------------- #
# Lot 2 — reading the schedule, and the receipt, without guessing
# --------------------------------------------------------------------------- #


def is_script_read_restricted(path: str | Path) -> bool:
    """Is this a credential-bearing file that must not be read at all?

    Carries ``core/customization_migration/references.py``'s discipline
    (``is_reference_read_restricted_path``, :56-75) to arbitrary absolute
    paths.  Its ``secret_adjacent`` part-walk already generalizes; its three
    vault-relative rules are applied here as path-part matching, which is what
    makes them meaningful for a path like ``~/bin/run.sh``.
    """
    parts = tuple(PurePosixPath(Path(path).as_posix()).parts)
    lowered = tuple(part.lower() for part in parts)
    if any(
        part == ".env" or part.startswith(".env.") or "credential" in part
        for part in lowered
    ):
        return True
    if len(lowered) >= 2 and lowered[-2] == ".claude" and lowered[-1] in {
        "settings.json",
        "settings.local.json",
    }:
        return True
    for index in range(len(lowered) - 2):
        if (
            lowered[index] == "system"
            and lowered[index + 1] == "integrations"
            and lowered[-1].endswith((".yaml", ".yml"))
        ):
            return True
    return False


def _looks_like_shell_script(path: Path, raw: bytes) -> bool:
    if path.suffix.lower() in {".sh", ".bash", ".zsh"}:
        return True
    if not raw.startswith(b"#!"):
        return False
    first = raw.split(b"\n", 1)[0].decode("utf-8", "replace").lower()
    return any(name in first for name in _SHELL_INTERPRETERS)


def _resolve_output_token(token: str, home: Path) -> str | None:
    """Resolve one redirection target, or refuse it.  Never guess."""
    text = token.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    if not text or any(marker in text for marker in _UNSAFE_TOKEN):
        return None
    if text.startswith("~/"):
        text = f"{home}/{text[2:]}"
    for form in ("${HOME}", "$HOME"):
        if text.startswith(form):
            text = f"{home}{text[len(form):]}"
            break
    if "$" in text:
        return None
    candidate = Path(text)
    if not candidate.is_absolute():
        return None
    if candidate.name in {"null", "stdout", "stderr"} and str(candidate).startswith(
        "/dev/"
    ):
        return None
    if is_script_read_restricted(candidate):
        return None
    return str(candidate)


def read_script_output_paths(script: str | Path, *, home: Path) -> tuple[str, ...]:
    """Find the paths a shell script plainly writes.  Bounded, hard.

    v1 accepts two shapes only — a redirection target, and the argument of
    ``tee``/``touch``.  Command substitution, an unknown variable, or a glob is
    *refused*, not guessed: a wrong receipt would make a dead job look alive,
    which is the exact failure this whole build exists to stop.  Sourced and
    child files are never followed.
    """
    path = Path(script)
    try:
        if path.is_symlink() or not path.is_file():
            return ()
        if path.stat().st_size > MAX_SCRIPT_BYTES:
            return ()
        raw = path.read_bytes()
    except OSError:
        return ()
    if not _looks_like_shell_script(path, raw):
        return ()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ()

    found: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for pattern in (_REDIRECT_RE, _WRITING_COMMAND_RE):
            for match in pattern.finditer(stripped):
                resolved = _resolve_output_token(match.group(1), home)
                if resolved is not None and resolved not in found:
                    found.append(resolved)
    return tuple(found)


def _program_script(data: Mapping[str, Any]) -> Path | None:
    """The file the job actually runs, when the plist plainly names one."""
    arguments = data.get("ProgramArguments")
    candidates: list[str] = []
    if isinstance(arguments, list):
        candidates.extend(str(item) for item in arguments if isinstance(item, str))
    program = data.get("Program")
    if isinstance(program, str):
        candidates.insert(0, program)
    for candidate in candidates:
        path = Path(candidate)
        if not path.is_absolute():
            continue
        if path.name in {"env", *(f"{name}" for name in _SHELL_INTERPRETERS)}:
            continue
        try:
            if path.is_file() and not path.is_symlink():
                return path
        except OSError:
            continue
    return None


def read_schedule(data: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Read the cadence from the plist.  Absent is ``observed``, never a guess."""
    calendar = data.get("StartCalendarInterval")
    specs: list[dict[str, int]] = []
    if isinstance(calendar, Mapping):
        calendar = [calendar]
    if isinstance(calendar, list):
        for entry in calendar:
            if not isinstance(entry, Mapping):
                continue
            spec = {
                key: int(entry[key])
                for key in ("Minute", "Hour", "Day", "Weekday", "Month")
                if isinstance(entry.get(key), int)
            }
            if spec:
                specs.append(spec)
    if specs:
        # An entry with no Hour fires every hour; that is an interval, not a
        # calendar time, and is recorded as the coarse thing it is.
        if all("Hour" not in spec for spec in specs):
            return "StartInterval", {"interval_seconds": 3600}
        return "StartCalendarInterval", {"calendar": specs}

    interval = data.get("StartInterval")
    if isinstance(interval, int) and interval > 0:
        return "StartInterval", {"interval_seconds": int(interval)}

    return "observed", {}


def learn_interval(runs: Sequence[str]) -> timedelta | None:
    """Learn a rhythm from observed runs, or admit there isn't one yet."""
    stamps = sorted(filter(None, (_parse(value) for value in runs)))
    if len(stamps) < MIN_OBSERVED_RUNS:
        return None
    gaps = [
        (later - earlier).total_seconds()
        for earlier, later in zip(stamps, stamps[1:])
        if later > earlier
    ]
    if len(gaps) < MIN_OBSERVED_RUNS - 1:
        return None
    median = statistics.median(gaps)
    if median <= 0:
        return None
    deviation = statistics.median([abs(gap - median) for gap in gaps])
    if deviation > median * 0.25:
        return None
    return timedelta(seconds=median)


def choose_receipt(
    data: Mapping[str, Any], *, home: Path
) -> tuple[str, str | None, bool]:
    """Pick the best honest receipt: the job's own output, then launchd, then none.

    Returns ``(provenance, path, activity_only)``.  Credential-bearing scripts
    are excluded before any read, and a script whose outputs cannot be resolved
    falls through to launchd evidence rather than being guessed at.
    """
    script = _program_script(data)
    if script is not None and not is_script_read_restricted(script):
        outputs = read_script_output_paths(script, home=home)
        if outputs:
            return "script-output", outputs[0], False

    for key, provenance in (
        ("StandardOutPath", "launchd-stdout"),
        ("StandardErrorPath", "launchd-stderr"),
    ):
        value = data.get(key)
        if isinstance(value, str) and value.strip() and not value.startswith("/dev/"):
            if is_script_read_restricted(value):
                continue
            # launchd evidence proves the job ran, never that it worked.
            return provenance, value, True

    return "none", None, False


# --------------------------------------------------------------------------- #
# Lot 3 — the audit: due, grace, two misses, recovery
# --------------------------------------------------------------------------- #


def _interval_of(record: LearnedPromise) -> timedelta | None:
    seconds = record.schedule.get("interval_seconds")
    if isinstance(seconds, (int, float)) and seconds > 0:
        return timedelta(seconds=float(seconds))
    return None


def grace_for(record: LearnedPromise) -> timedelta:
    """Grace sized for real laptop life; coarse schedules keep cadence padding."""
    interval = _interval_of(record)
    if interval is None:
        return BASE_GRACE
    return max(BASE_GRACE, interval * COARSE_GRACE_FRACTION)


def due_times(
    record: LearnedPromise, after: datetime, now: datetime
) -> tuple[datetime, ...]:
    """Enumerate the times this job was supposed to run, strictly after *after*.

    Calendar schedules are evaluated in local time because that is what launchd
    does: a job set for 09:00 means 09:00 where the person is.
    """
    after = _aware(after)
    now = _aware(now)
    if after is None or now is None or after >= now:
        return ()

    interval = _interval_of(record)
    if interval is not None:
        times: list[datetime] = []
        cursor = after + interval
        while cursor <= now and len(times) < MAX_DUE_TIMES:
            times.append(cursor)
            cursor += interval
        return tuple(times)

    specs = record.schedule.get("calendar")
    if not isinstance(specs, list) or not specs:
        return ()

    local_after = after.astimezone()
    local_now = now.astimezone()
    times = []
    day = local_after.date()
    limit = local_now.date()
    guard = 0
    while day <= limit and guard < MAX_DUE_TIMES:
        guard += 1
        for spec in specs:
            if not isinstance(spec, Mapping) or "Hour" not in spec:
                continue
            if "Month" in spec and spec["Month"] != day.month:
                continue
            if "Day" in spec and spec["Day"] != day.day:
                continue
            # launchd Weekday: 0 and 7 are Sunday; Python: Monday is 0.
            if "Weekday" in spec:
                launchd_weekday = (day.weekday() + 1) % 7
                if int(spec["Weekday"]) % 7 != launchd_weekday:
                    continue
            candidate = datetime(
                day.year,
                day.month,
                day.day,
                int(spec["Hour"]),
                int(spec.get("Minute", 0)),
                tzinfo=local_after.tzinfo,
            ).astimezone(timezone.utc)
            if after < candidate <= now:
                times.append(candidate)
        day += timedelta(days=1)
    return tuple(sorted(times))


@dataclass(frozen=True)
class LearnedAudit:
    """One learned job's verdict, in the shipped vocabulary where it applies."""

    label: str
    state: str
    display_name: str = ""
    activity_only: bool = False
    consecutive_misses: int = 0
    last_receipt_at: datetime | None = None
    last_due_at: datetime | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.state not in JUDGEMENTS | NON_JUDGEMENTS:
            raise ValueError(f"unknown learned verdict {self.state!r}")

    def surfaces(self) -> bool:
        """Only a real broken promise speaks. One miss stays quiet."""
        return self.state in {"broken", "never"}

    def detail(self) -> str:
        """The register's voice: activity-only receipts never say 'succeeded'."""
        name = self.display_name or self.label
        verb = "ran" if self.activity_only else "completed successfully"
        if self.state == "never":
            if self.activity_only:
                return f"{name} has not run since Dex started watching"
            return (
                f"{name} has never recorded a completed run since Dex started "
                "watching"
            )
        if self.state == "unauditable":
            return f"{name} leaves no trace Dex can check"
        if self.state == "no-rhythm-yet":
            return f"{name} has no regular schedule Dex can read yet"
        if self.state == "stopped-by-user":
            return f"{name} is not watched, at your choice"
        if self.state == "pending":
            return f"{name} is being watched; nothing has been due yet"
        if self.last_receipt_at is None:
            return f"{name} has no receipt Dex can read"
        stamp = self.last_receipt_at.date().isoformat()
        if self.state == "broken":
            suffix = "" if self.activity_only else " — it may still be running without succeeding"
            return f"{name} last {verb} on {stamp}{suffix}"
        return f"{name} last {verb} on {stamp}"

    def alarm_line(self) -> str:
        """The person's own words plus the evidence. DRAFT copy."""
        name = self.display_name or self.label
        if self.last_due_at is not None:
            local_due = self.last_due_at.astimezone()
            when = local_due.strftime("%A at %-I:%M%p").replace("AM", "am").replace(
                "PM", "pm"
            )
            due_text = f"was due {when}"
        else:
            due_text = "was due"
        if self.last_receipt_at is None:
            trace = "and has left no trace since Dex started watching"
        else:
            trace = (
                "and has left no trace since "
                f"{self.last_receipt_at.astimezone().strftime('%-d %B')}"
            )
        return f"{name} {due_text} {trace}."

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "name": self.display_name or self.label,
            "state": self.state,
            "activity_only": self.activity_only,
            "consecutive_misses": self.consecutive_misses,
            "last_receipt_at": _stamp(self.last_receipt_at)
            if self.last_receipt_at
            else None,
            "last_due_at": _stamp(self.last_due_at) if self.last_due_at else None,
            "detail": self.detail(),
            "evidence": self.alarm_line() if self.surfaces() else None,
        }


def unauditable_audit(name: str) -> LearnedAudit:
    """A record Dex cannot read is unauditable — never a false 'kept'."""
    return LearnedAudit(
        label=name,
        display_name=name,
        state="unauditable",
        reason="the learned record could not be read",
    )


def read_receipt_timestamp(record: LearnedPromise) -> datetime | None:
    """Read the live receipt. The stored stamp is history, never a substitute."""
    if not record.receipt_path:
        return None
    path = Path(record.receipt_path)
    try:
        if path.is_symlink() or not path.is_file():
            return None
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def audit_learned(
    record: LearnedPromise,
    *,
    now: datetime,
    receipt_at: datetime | None = None,
) -> LearnedAudit:
    """Judge one learned job: kept, never, broken — or honestly not judged.

    ``consecutive_misses`` is *derived* every time, by counting due times since
    the last receipt, so a Doctor that runs weekly still judges a daily job
    correctly.  It is then persisted so the count and its evidence survive a
    restart.
    """
    now = _aware(now)
    base = LearnedAudit(
        label=record.label,
        display_name=record.display_name,
        state="pending",
        activity_only=record.activity_only,
    )
    if record.watch_state == "stopped-by-user":
        return replace(base, state="stopped-by-user")
    if record.schedule_source == "observed" and _interval_of(record) is None:
        return replace(base, state="no-rhythm-yet")
    if not record.is_auditable():
        return replace(base, state="unauditable")

    observed = receipt_at if receipt_at is not None else read_receipt_timestamp(record)
    observed = _aware(observed)
    watch_since = _parse(record.watch_since) or now
    anchor = max(filter(None, (observed, watch_since))) if observed else watch_since

    grace = grace_for(record)
    missed = [due for due in due_times(record, anchor, now) if due + grace <= now]
    count = len(missed)
    last_due = missed[-1] if missed else None
    result = replace(
        base, consecutive_misses=count, last_receipt_at=observed, last_due_at=last_due
    )

    if observed is None:
        # Two full periods with nothing at all is its own verdict.
        if count >= MISS_THRESHOLD:
            return replace(result, state="never")
        return replace(result, state="pending")
    if count >= MISS_THRESHOLD:
        return replace(result, state="broken")
    # One miss stays quiet; recovery is never held back.
    return replace(result, state="kept")


# --------------------------------------------------------------------------- #
# Lot 4 — one composer owns every learned line
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LearnedSurface:
    """Everything any surface may say about learned jobs, built in one place."""

    lines: tuple[str, ...]
    coverage_lines: tuple[str, ...]
    choices: tuple[dict[str, Any], ...]
    disclosure_leading: bool
    rollup: str
    watched: int
    needs_attention: int
    #: What the snapshot carries, and therefore what every surface reading the
    #: snapshot says.  The disclosure is folded in here rather than left to each
    #: surface, so no reader can compose an alarm without it.
    snapshot_detail: str = ""


def compose_surface(
    register: LearnedRegister,
    audits: Sequence[LearnedAudit],
    *,
    now: datetime | None = None,
) -> LearnedSurface:
    """Build every learned-job line. The disclosure always comes first.

    This is the structural guarantee behind the founder's first ruling: no
    surface composes its own learned copy, so no learned alarm can reach the
    person before the disclosure has led at least once.
    """
    disclosure_leading = register.disclosed_at is None
    watched = [audit for audit in audits if audit.state != "stopped-by-user"]
    alarming = [audit for audit in audits if audit.surfaces()]

    lines: list[str] = []
    if disclosure_leading:
        lines.append(DISCLOSURE_LINE)
    lines.extend(audit.alarm_line() for audit in alarming)

    coverage: list[str] = []
    for audit in audits:
        if audit.state in {"stopped-by-user", "unauditable", "no-rhythm-yet"}:
            coverage.append(audit.detail())

    choices: tuple[dict[str, Any], ...] = ()
    if disclosure_leading:
        choices = tuple(
            {"label": audit.label, "name": audit.display_name, "options": ("keep", "stop")}
            for audit in audits
            if audit.state != "stopped-by-user"
        )

    # "On schedule" is a claim, so it is only made about jobs that actually
    # left a receipt.  A job Dex is watching but has never seen run says that
    # instead — the whole point of this build is not to call silence success.
    on_schedule = [audit for audit in watched if audit.state == "kept"]
    nothing_yet = [
        audit
        for audit in watched
        if audit.state in {"pending", "no-rhythm-yet", "unauditable"}
    ]
    if not audits:
        rollup = "No automations of your own found to watch"
    elif alarming:
        named = ", ".join(audit.display_name for audit in alarming[:3])
        more = "" if len(alarming) <= 3 else f" (+{len(alarming) - 3} more)"
        noun = "needs" if len(alarming) == 1 else "need"
        rollup = (
            f"{len(watched)} of your automations watched; "
            f"{len(alarming)} {noun} attention: {named}{more}"
        )
    elif on_schedule and not nothing_yet:
        rollup = f"{len(watched)} of your automations watched; all on schedule"
    elif on_schedule:
        rollup = (
            f"{len(watched)} of your automations watched; {len(on_schedule)} on "
            f"schedule, {len(nothing_yet)} with nothing to check yet"
        )
    else:
        rollup = (
            f"{len(watched)} of your automations watched; "
            "none has left a trace to check yet"
        )

    snapshot_detail = f"{DISCLOSURE_LINE} {rollup}" if disclosure_leading else rollup
    return LearnedSurface(
        lines=tuple(lines),
        coverage_lines=tuple(coverage),
        choices=choices,
        disclosure_leading=disclosure_leading,
        rollup=rollup,
        watched=len(watched),
        needs_attention=len(alarming),
        snapshot_detail=snapshot_detail,
    )


# --------------------------------------------------------------------------- #
# Lot 2 — the sweep, riding the Doctor's existing classification pass
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SweepResult:
    """What one sweep did, so a caller can report it without guessing."""

    enrolled: tuple[str, ...] = ()
    redrafted: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    skipped_shipped: tuple[str, ...] = ()


def _is_shipped(label: str) -> bool:
    from core.health import promises as health_promises
    from core.utils import launch_agents

    return any(
        health_promises.promise_by_id(candidate) is not None
        for candidate in launch_agents.promise_label_candidates(label)
    )


def sweep(context: Any, *, now: datetime, scan: Any | None = None) -> SweepResult:
    """Draft and refresh learned promises for the person's own launchd jobs.

    No new scheduler: this rides the classification pass the Doctor already
    performs (``_scan_launch_agents``), so it parses no plist twice.  Every
    changed record from one sweep lands in a single transaction.
    """
    from core.utils import doctor

    now = _aware(now)
    scan = scan if scan is not None else doctor._scan_launch_agents(context)
    store = LearnedStore(context.vault_root)
    _register, existing, corrupt = store.load()
    by_label = {record.label: record for record in existing}
    corrupt_slugs = {name[: -len(".json")] for name in corrupt}

    enrolled: list[str] = []
    redrafted: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    changed: list[LearnedPromise] = []
    seen: set[str] = set()

    for entry in scan.records:
        if entry.classification != doctor._OWNED or entry.data is None:
            continue
        label = entry.label
        if _is_shipped(label):
            skipped.append(label)
            continue
        seen.add(label)
        was_corrupt = record_slug(label) in corrupt_slugs
        previous = by_label.get(label)

        source, schedule = read_schedule(entry.data)
        provenance, receipt_path, activity_only = choose_receipt(
            entry.data, home=context.home
        )
        program = _program_script(entry.data)
        program_path = (
            str(program)
            if program is not None and not is_script_read_restricted(program)
            else None
        )
        try:
            plist_relative = entry.plist.relative_to(context.home).as_posix()
        except ValueError:
            plist_relative = entry.plist.name

        drafted = LearnedPromise(
            label=label,
            plist_relative_path=plist_relative,
            schedule_source=source,
            schedule=schedule,
            receipt_kind="file-activity",
            receipt_path=receipt_path,
            receipt_provenance=provenance,
            activity_only=activity_only,
            watch_since=_stamp(now),
            program_path=program_path,
        )
        if previous is not None:
            # The person's answer and their watch history are theirs; only the
            # read facts are re-drafted from the plist.
            drafted = drafted.replace(
                watch_state=previous.watch_state,
                watch_since=previous.watch_since or _stamp(now),
                observed_runs=previous.observed_runs,
            )
            if source == "observed" and not schedule:
                learnt = learn_interval(previous.observed_runs)
                if learnt is not None:
                    drafted = drafted.replace(
                        schedule={"interval_seconds": int(learnt.total_seconds())}
                    )

        audit = audit_learned(drafted, now=now)
        drafted = drafted.replace(
            consecutive_misses=audit.consecutive_misses,
            last_receipt_at=_stamp(audit.last_receipt_at)
            if audit.last_receipt_at
            else None,
            last_evaluated_at=_stamp(now),
        )
        if audit.last_receipt_at is not None:
            runs = tuple(
                sorted(set(drafted.observed_runs) | {_stamp(audit.last_receipt_at)})
            )[-MAX_OBSERVED_RUNS:]
            drafted = drafted.replace(observed_runs=runs)

        if was_corrupt:
            redrafted.append(label)
        elif previous is None:
            enrolled.append(label)
        elif previous.to_dict() != drafted.to_dict():
            updated.append(label)
        changed.append(drafted)

    # A record whose plist is gone stays as it is: the person may be between
    # edits, and deleting their watch history on a transient absence would be
    # its own quiet failure.
    if changed:
        store.put_many(changed)

    return SweepResult(
        enrolled=tuple(sorted(enrolled)),
        redrafted=tuple(sorted(redrafted)),
        updated=tuple(sorted(updated)),
        skipped_shipped=tuple(sorted(skipped)),
    )


def audit_all(
    vault_root: str | Path, *, now: datetime
) -> tuple[LearnedRegister, tuple[LearnedAudit, ...]]:
    """Every learned verdict for a vault, corrupt records included honestly."""
    store = LearnedStore(vault_root)
    register, records, corrupt = store.load()
    audits = [audit_learned(record, now=now) for record in records]
    audits.extend(unauditable_audit(name[: -len(".json")]) for name in corrupt)
    return register, tuple(audits)


# --------------------------------------------------------------------------- #
# Lot 5 — offered instrumentation: the build's only write to a user's file
# --------------------------------------------------------------------------- #


#: Where an offered receipt lands. Under the person's home, never in the vault:
#: it is their job's evidence, not Dex's data.
RECEIPT_DIR = ".dex/receipts"
_RECEIPT_MARKER = "# receipt line added by Dex"


@dataclass(frozen=True)
class ReceiptProposal:
    """An exact, hash-bound offer to add one receipt line to a user's script.

    Nothing here writes.  ``apply_receipt_proposal`` is the only function in
    this module that touches a file outside the health directory, and it
    refuses unless the person said yes *and* the script is byte-identical to
    the one this diff was computed from.
    """

    label: str
    script_path: str
    receipt_path: str
    line: str
    diff: str
    script_sha256: str


def propose_receipt_instrumentation(
    record: LearnedPromise, *, home: Path
) -> ReceiptProposal | None:
    """Offer to give a receipt-poor job a real receipt. Returns None, or an offer.

    Only for jobs whose receipt is weak or absent, whose program Dex can read
    as a shell script, and which do not already carry Dex's receipt line.
    """
    if record.receipt_provenance == "script-output":
        return None
    if not record.program_path:
        return None
    script = Path(record.program_path)
    if is_script_read_restricted(script):
        return None
    try:
        if script.is_symlink() or not script.is_file():
            return None
        if script.stat().st_size > MAX_SCRIPT_BYTES:
            return None
        raw = script.read_bytes()
    except OSError:
        return None
    if not _looks_like_shell_script(script, raw):
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if _RECEIPT_MARKER in text:
        return None

    receipt = f"{home}/{RECEIPT_DIR}/{record.slug}.receipt"
    line = (
        f'mkdir -p "$(dirname \'{receipt}\')" && '
        f"date -u +%Y-%m-%dT%H:%M:%SZ > '{receipt}'  {_RECEIPT_MARKER}"
    )
    tail = "" if text.endswith("\n") else "\n"
    diff = "\n".join(
        (
            f"--- {script}",
            f"+++ {script}",
            "@@ end of file @@",
            f"+{line}",
        )
    )
    return ReceiptProposal(
        label=record.label,
        script_path=str(script),
        receipt_path=receipt,
        line=line + tail,
        diff=diff,
        script_sha256=hashlib.sha256(raw).hexdigest(),
    )


def apply_receipt_proposal(
    vault_root: str | Path,
    proposal: ReceiptProposal,
    *,
    approved: bool,
    now: datetime,
) -> bool:
    """Apply an offer the person accepted. Refuses everything else.

    Two guards, both hard: an explicit ``approved`` (never a default), and the
    script's bytes still matching the diff the person was shown.  A script that
    changed since the offer needs a new offer, not a silent write.
    """
    if approved is not True:
        return False
    script = Path(proposal.script_path)
    if is_script_read_restricted(script):
        return False
    try:
        if script.is_symlink() or not script.is_file():
            return False
        raw = script.read_bytes()
    except OSError:
        return False
    if hashlib.sha256(raw).hexdigest() != proposal.script_sha256:
        return False

    separator = b"" if raw.endswith(b"\n") or not raw else b"\n"
    try:
        with script.open("ab") as handle:
            handle.write(separator + proposal.line.encode("utf-8"))
    except OSError:
        return False

    store = LearnedStore(vault_root)
    record = store.get(proposal.label)
    if record is not None:
        store.put(
            record.replace(
                receipt_kind="file-activity",
                receipt_path=proposal.receipt_path,
                receipt_provenance="script-output",
                activity_only=False,
                consecutive_misses=0,
                last_receipt_at=None,
                watch_since=_stamp(now),
            )
        )
    return True


__all__ = [
    "DISCLOSURE_LINE",
    "RECEIPT_DIR",
    "ReceiptProposal",
    "JUDGEMENTS",
    "LearnedAudit",
    "LearnedPromise",
    "LearnedRegister",
    "LearnedStore",
    "LearnedSurface",
    "MAX_SCRIPT_BYTES",
    "NON_JUDGEMENTS",
    "SCOPE_NOTE",
    "SweepResult",
    "audit_all",
    "audit_learned",
    "choose_receipt",
    "compose_surface",
    "due_times",
    "grace_for",
    "is_script_read_restricted",
    "apply_receipt_proposal",
    "learn_interval",
    "propose_receipt_instrumentation",
    "read_schedule",
    "read_script_output_paths",
    "record_slug",
    "sweep",
    "unauditable_audit",
]
