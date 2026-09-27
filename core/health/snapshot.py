"""Immutable proactive-health snapshots and refresh lifecycle.

The store is deliberately small and boring: a complete normalized reporter
envelope is written once, an atomic pointer names the newest snapshot, and a
separate refresh record describes the attempt that produced (or failed to
produce) it.  Reads never repair or publish state.  All durable health files
go through the existing lifecycle transaction boundary.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from core.health.reporter import NormalizationResult, ReporterEnvelope, normalize_report
from core.lifecycle import service
from core.transaction.engine import PlanEntry
from core.transaction.fsync import fchmod
from core.utils.os_flags import binary_write_flags

SNAPSHOT_CONTRACT = "dex.health.snapshot/v1"
POINTER_CONTRACT = "dex.health.latest/v1"
REFRESH_CONTRACT = "dex.health.refresh/v1"

REFRESH_STATES = frozenset({"running", "complete", "failed", "inconclusive"})
OVERALL_STATUSES = frozenset({"healthy", "unknown", "critical"})
DEFAULT_RETENTION = 5

HEALTH_RELATIVE = Path("System") / ".dex" / "health"
SNAPSHOTS_RELATIVE = HEALTH_RELATIVE / "snapshots"
REFRESHES_RELATIVE = HEALTH_RELATIVE / "refreshes"
LATEST_RELATIVE = HEALTH_RELATIVE / "latest.json"
_REFRESH_LOCK_PREFIX = "dex-health-refresh-"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_DETAIL_LENGTH = 512
_SNAPSHOT_KEYS = frozenset(
    {
        "contract",
        "snapshot_id",
        "refresh_id",
        "generated_at",
        "completed_at",
        "overall_status",
        "report",
    }
)
_POINTER_KEYS = frozenset({"contract", "snapshot_id", "path", "published_at"})
_REFRESH_KEYS = frozenset(
    {
        "contract",
        "refresh_id",
        "state",
        "started_at",
        "updated_at",
        "completed_at",
        "snapshot_id",
        "detail",
    }
)


class HealthStoreError(RuntimeError):
    """Base error for unsafe or invalid health lifecycle operations."""


class HealthStoreCorruption(HealthStoreError):
    """A durable health record is malformed or no longer self-consistent."""


class HealthRefreshBusyError(HealthStoreError):
    """Another refresh currently owns the single refresh writer lock."""


class HealthRefreshAlreadyExists(HealthStoreError):
    """A refresh identity has already been used."""


class IncompleteHealthReport(HealthStoreError):
    """A report did not pass strict normalization/completeness validation."""


class SnapshotAlreadyExists(HealthStoreError):
    """A caller attempted to overwrite an immutable snapshot identity."""


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _now_timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if not isinstance(value, datetime):
        raise TypeError("health clock must return datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _valid_identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER_RE.fullmatch(value) is not None


def _coordination_lock_path(root: Path) -> Path:
    identity = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:32]
    return Path(tempfile.gettempdir()) / f"{_REFRESH_LOCK_PREFIX}{identity}.lock"


def _bounded_detail(value: object) -> str:
    text = value if isinstance(value, str) else str(value)
    text = " ".join(text.split())
    if not text:
        return "unknown"
    if len(text) <= _MAX_DETAIL_LENGTH:
        return text
    return text[: _MAX_DETAIL_LENGTH - 1].rstrip() + "…"


def _overall_status(report: ReporterEnvelope) -> str:
    verdicts = {result.verdict for result in report.results}
    if "BROKEN" in verdicts:
        return "critical"
    if "UNKNOWN" in verdicts:
        return "unknown"
    return "healthy"


def _read_json(path: Path, *, kind: str) -> Mapping[str, object]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as error:
        raise FileNotFoundError(path) from error
    except OSError as error:
        raise HealthStoreCorruption(f"could not read {kind}: {path}") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HealthStoreCorruption(f"{kind} is not valid JSON: {path}") from error
    if not isinstance(value, Mapping):
        raise HealthStoreCorruption(f"{kind} must be a JSON object: {path}")
    return value


def _require_keys(value: Mapping[str, object], expected: frozenset[str], *, kind: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise HealthStoreCorruption(
            f"{kind} fields do not match the v1 contract (missing={missing}, extra={extra})"
        )


@dataclass(frozen=True)
class HealthSnapshot:
    """One complete, immutable, normalized health result."""

    snapshot_id: str
    refresh_id: str
    generated_at: str
    completed_at: str
    overall_status: str
    report: ReporterEnvelope

    def __post_init__(self) -> None:
        if not _valid_identifier(self.snapshot_id):
            raise ValueError("snapshot_id must be a bounded opaque identifier")
        if not _valid_identifier(self.refresh_id):
            raise ValueError("refresh_id must be a bounded opaque identifier")
        if not _timestamp(self.generated_at) or not _timestamp(self.completed_at):
            raise ValueError("snapshot timestamps must be timezone-aware ISO-8601")
        if self.overall_status not in OVERALL_STATUSES:
            raise ValueError(f"invalid overall health status: {self.overall_status!r}")
        if type(self.report) is not ReporterEnvelope:
            raise TypeError("snapshot report must be a ReporterEnvelope")
        if self.report.refresh_id != self.refresh_id:
            raise ValueError("snapshot refresh_id must match the reporter envelope")
        if self.report.generated_at != self.generated_at:
            raise ValueError("snapshot generated_at must match the reporter envelope")
        if self.overall_status != _overall_status(self.report):
            raise ValueError("snapshot overall_status does not match its factual results")

    @classmethod
    def from_normalized(
        cls,
        normalized: NormalizationResult,
        *,
        snapshot_id: str,
        completed_at: str,
    ) -> "HealthSnapshot":
        if type(normalized) is not NormalizationResult:
            raise TypeError("snapshot publication requires a NormalizationResult")
        if not normalized.accepted:
            raise IncompleteHealthReport(
                "health snapshot requires an accepted complete reporter envelope: "
                + "; ".join(normalized.errors)
            )
        report = normalized.report
        return cls(
            snapshot_id=snapshot_id,
            refresh_id=report.refresh_id,
            generated_at=report.generated_at,
            completed_at=completed_at,
            overall_status=_overall_status(report),
            report=report,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "HealthSnapshot":
        _require_keys(value, _SNAPSHOT_KEYS, kind="health snapshot")
        if value.get("contract") != SNAPSHOT_CONTRACT:
            raise HealthStoreCorruption("unsupported health snapshot contract")
        raw_report = value.get("report")
        normalized = normalize_report(raw_report)
        if not normalized.accepted:
            raise HealthStoreCorruption(
                "health snapshot contains an invalid reporter envelope: "
                + "; ".join(normalized.errors)
            )
        try:
            return cls(
                snapshot_id=value["snapshot_id"],  # type: ignore[arg-type]
                refresh_id=value["refresh_id"],  # type: ignore[arg-type]
                generated_at=value["generated_at"],  # type: ignore[arg-type]
                completed_at=value["completed_at"],  # type: ignore[arg-type]
                overall_status=value["overall_status"],  # type: ignore[arg-type]
                report=normalized.report,
            )
        except (TypeError, ValueError) as error:
            raise HealthStoreCorruption("health snapshot fields are invalid") from error

    def to_dict(self) -> dict[str, object]:
        return {
            "contract": SNAPSHOT_CONTRACT,
            "snapshot_id": self.snapshot_id,
            "refresh_id": self.refresh_id,
            "generated_at": self.generated_at,
            "completed_at": self.completed_at,
            "overall_status": self.overall_status,
            "report": self.report.to_dict(),
        }


@dataclass(frozen=True)
class HealthRefresh:
    """Durable outcome for one refresh attempt, separate from latest state."""

    refresh_id: str
    state: str
    started_at: str
    updated_at: str
    completed_at: str | None = None
    snapshot_id: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not _valid_identifier(self.refresh_id):
            raise ValueError("refresh_id must be a bounded opaque identifier")
        if self.state not in REFRESH_STATES:
            raise ValueError(f"invalid refresh state: {self.state!r}")
        if not _timestamp(self.started_at) or not _timestamp(self.updated_at):
            raise ValueError("refresh timestamps must be timezone-aware ISO-8601")
        if self.completed_at is not None and not _timestamp(self.completed_at):
            raise ValueError("completed_at must be timezone-aware ISO-8601 or null")
        if self.state == "running" and self.completed_at is not None:
            raise ValueError("running refreshes cannot have completed_at")
        if self.state == "complete":
            if self.completed_at is None or not _valid_identifier(self.snapshot_id):
                raise ValueError("complete refreshes require completion and snapshot identity")
        elif self.snapshot_id is not None:
            raise ValueError("non-complete refreshes cannot reference a snapshot")
        if self.detail is not None and len(self.detail) > _MAX_DETAIL_LENGTH:
            raise ValueError("refresh detail exceeds the bounded limit")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "HealthRefresh":
        _require_keys(value, _REFRESH_KEYS, kind="health refresh")
        if value.get("contract") != REFRESH_CONTRACT:
            raise HealthStoreCorruption("unsupported health refresh contract")
        try:
            return cls(
                refresh_id=value["refresh_id"],  # type: ignore[arg-type]
                state=value["state"],  # type: ignore[arg-type]
                started_at=value["started_at"],  # type: ignore[arg-type]
                updated_at=value["updated_at"],  # type: ignore[arg-type]
                completed_at=value["completed_at"],  # type: ignore[arg-type]
                snapshot_id=value["snapshot_id"],  # type: ignore[arg-type]
                detail=value["detail"],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as error:
            raise HealthStoreCorruption("health refresh fields are invalid") from error

    def to_dict(self) -> dict[str, object]:
        return {
            "contract": REFRESH_CONTRACT,
            "refresh_id": self.refresh_id,
            "state": self.state,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "snapshot_id": self.snapshot_id,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class LatestPointer:
    """The small atomically replaced record naming the latest snapshot."""

    snapshot_id: str
    published_at: str

    def __post_init__(self) -> None:
        if not _valid_identifier(self.snapshot_id):
            raise ValueError("pointer snapshot_id must be a bounded opaque identifier")
        if not _timestamp(self.published_at):
            raise ValueError("pointer published_at must be timezone-aware ISO-8601")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "LatestPointer":
        _require_keys(value, _POINTER_KEYS, kind="health latest pointer")
        if value.get("contract") != POINTER_CONTRACT:
            raise HealthStoreCorruption("unsupported health latest pointer contract")
        snapshot_id = value.get("snapshot_id")
        expected_path = (SNAPSHOTS_RELATIVE / f"{snapshot_id}.json").as_posix()
        if value.get("path") != expected_path:
            raise HealthStoreCorruption("health latest pointer path is inconsistent")
        try:
            return cls(snapshot_id=snapshot_id, published_at=value["published_at"])  # type: ignore[arg-type]
        except (TypeError, ValueError) as error:
            raise HealthStoreCorruption("health latest pointer fields are invalid") from error

    def to_dict(self) -> dict[str, str]:
        return {
            "contract": POINTER_CONTRACT,
            "snapshot_id": self.snapshot_id,
            "path": (SNAPSHOTS_RELATIVE / f"{self.snapshot_id}.json").as_posix(),
            "published_at": self.published_at,
        }


class _RefreshCoordinator:
    """POSIX advisory lock with kernel-recoverable stale ownership."""

    def __init__(self, root: Path, refresh_id: str, started_at: str) -> None:
        self.path = _coordination_lock_path(root)
        self.refresh_id = refresh_id
        self.started_at = started_at
        self._descriptor: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(
            self.path, binary_write_flags(os.O_RDWR | os.O_CREAT), 0o600
        )
        fchmod(descriptor, 0o600, path=self.path)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN):
                os.close(descriptor)
                raise
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                owner = os.read(descriptor, 512).decode("utf-8", errors="replace").strip()
            finally:
                os.close(descriptor)
            raise HealthRefreshBusyError(
                "another health refresh is already running" + (f": {owner}" if owner else "")
            ) from None

        body = _canonical(
            {
                "pid": os.getpid(),
                "refresh_id": self.refresh_id,
                "started_at": self.started_at,
            }
        )
        try:
            os.ftruncate(descriptor, 0)
            os.write(descriptor, body)
            os.fsync(descriptor)
        except BaseException:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            raise
        self._descriptor = descriptor

    def release(self) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is None:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


class HealthRefreshSession:
    """A single-writer refresh attempt held open across reporter collection."""

    def __init__(self, store: "HealthStore", record: HealthRefresh) -> None:
        self._store = store
        self._record = record

    @property
    def record(self) -> HealthRefresh:
        return self._record

    @property
    def state(self) -> str:
        return self._record.state

    def publish(
        self,
        normalized: NormalizationResult,
        *,
        snapshot_id: str | None = None,
        completed_at: str | None = None,
    ) -> HealthSnapshot:
        if self._record.state != "running":
            raise HealthStoreError("a terminal refresh cannot publish another snapshot")
        try:
            snapshot, record = self._store._publish(
                self._record,
                normalized,
                snapshot_id=snapshot_id,
                completed_at=completed_at,
            )
        except IncompleteHealthReport as error:
            self._record = self._store._finish(
                self._record,
                "inconclusive",
                str(error),
            )
            raise
        except Exception as error:
            self._record = self._store._finish(
                self._record,
                "failed",
                str(error),
            )
            raise
        self._record = record
        return snapshot

    def inconclusive(self, detail: object) -> HealthRefresh:
        self._record = self._store._finish(self._record, "inconclusive", detail)
        return self._record

    def failed(self, detail: object) -> HealthRefresh:
        self._record = self._store._finish(self._record, "failed", detail)
        return self._record


class HealthStore:
    """Vault-local health state with immutable snapshots and atomic latest."""

    def __init__(
        self,
        vault_root: str | Path,
        *,
        retention: int = DEFAULT_RETENTION,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(retention) is not int or retention < 1:
            raise ValueError("health snapshot retention must be a positive integer")
        self.root = Path(vault_root).resolve()
        self.retention = retention
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def snapshots_dir(self) -> Path:
        return self.root / SNAPSHOTS_RELATIVE

    @property
    def refreshes_dir(self) -> Path:
        return self.root / REFRESHES_RELATIVE

    @property
    def latest_path(self) -> Path:
        return self.root / LATEST_RELATIVE

    @property
    def coordination_lock_path(self) -> Path:
        """Host-local coordination path; durable health state stays in the vault."""

        return _coordination_lock_path(self.root)

    def _timestamp(self) -> str:
        return _now_timestamp(self._clock)

    @staticmethod
    def _validate_refresh_id(refresh_id: str) -> None:
        if not _valid_identifier(refresh_id):
            raise ValueError("refresh_id must be a bounded opaque identifier")

    @staticmethod
    def _validate_snapshot_id(snapshot_id: str) -> None:
        if not _valid_identifier(snapshot_id):
            raise ValueError("snapshot_id must be a bounded opaque identifier")

    def _refresh_relative(self, refresh_id: str) -> str:
        self._validate_refresh_id(refresh_id)
        return (REFRESHES_RELATIVE / f"{refresh_id}.json").as_posix()

    def _snapshot_relative(self, snapshot_id: str) -> str:
        self._validate_snapshot_id(snapshot_id)
        return (SNAPSHOTS_RELATIVE / f"{snapshot_id}.json").as_posix()

    def _write_plan(self, plan: list[PlanEntry], *, purpose: str) -> None:
        preview = service._preview_transaction(self.root, plan, purpose=purpose)
        service._execute_approved_transaction(
            self.root,
            plan,
            purpose=purpose,
            approved_token=preview["approval_token"],
        )

    def _new_file_entry(self, relative: str, content: bytes) -> PlanEntry:
        return PlanEntry(relative, content, mode=0o600, expected_absent=True)

    def _replace_file_entry(self, relative: str, content: bytes) -> PlanEntry:
        target = self.root / relative
        if not target.exists():
            return PlanEntry(relative, content, mode=0o600, expected_absent=True)
        if target.is_symlink() or not target.is_file():
            raise HealthStoreCorruption(f"health target is not a regular file: {relative}")
        return PlanEntry(
            relative,
            content,
            mode=0o600,
            expected_current_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        )

    def _delete_entry(self, path: Path) -> PlanEntry | None:
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            return None
        relative = path.relative_to(self.root).as_posix()
        return PlanEntry(
            relative,
            None,
            mode=path.stat().st_mode & 0o777,
            expected_current_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def _start(self, refresh_id: str, started_at: str) -> HealthRefresh:
        self._validate_refresh_id(refresh_id)
        if not _timestamp(started_at):
            raise ValueError("started_at must be timezone-aware ISO-8601")
        record = HealthRefresh(
            refresh_id=refresh_id,
            state="running",
            started_at=started_at,
            updated_at=started_at,
        )
        try:
            self._write_plan(
                [self._new_file_entry(self._refresh_relative(refresh_id), _canonical(record.to_dict()))],
                purpose="health-refresh-start",
            )
        except Exception as error:
            if (self.root / self._refresh_relative(refresh_id)).exists():
                raise HealthRefreshAlreadyExists(refresh_id) from error
            raise
        return record

    @contextmanager
    def refresh(self, refresh_id: str, *, started_at: str | None = None) -> Iterator[HealthRefreshSession]:
        """Run one refresh under the recoverable single-writer coordinator."""

        self._validate_refresh_id(refresh_id)
        start = self._timestamp() if started_at is None else started_at
        coordinator = _RefreshCoordinator(self.root, refresh_id, start)
        coordinator.acquire()
        session: HealthRefreshSession | None = None
        try:
            session = HealthRefreshSession(self, self._start(refresh_id, start))
            try:
                yield session
            except BaseException as error:
                if session.state == "running":
                    state = "inconclusive" if isinstance(error, IncompleteHealthReport) else "failed"
                    try:
                        session._record = self._finish(
                            session._record,
                            state,
                            "refresh raised before a complete snapshot was published",
                        )
                    except Exception:
                        # Preserve the original reporter/refresh error. The
                        # stale running record remains diagnosable and can be
                        # reconciled by a later lifecycle pass.
                        pass
                raise
            else:
                if session.state == "running":
                    session._record = self._finish(
                        session._record,
                        "inconclusive",
                        "refresh ended without a complete snapshot",
                    )
        finally:
            coordinator.release()

    def _finish(self, current: HealthRefresh, state: str, detail: object) -> HealthRefresh:
        if current.state != "running":
            raise HealthStoreError("only a running refresh can transition to a terminal state")
        if state not in {"failed", "inconclusive"}:
            raise ValueError("terminal failure state must be failed or inconclusive")
        finished_at = self._timestamp()
        record = replace(
            current,
            state=state,
            updated_at=finished_at,
            completed_at=finished_at,
            detail=_bounded_detail(detail),
        )
        relative = self._refresh_relative(current.refresh_id)
        if not (self.root / relative).is_file():
            raise HealthStoreCorruption("running refresh record disappeared before completion")
        self._write_plan(
            [self._replace_file_entry(relative, _canonical(record.to_dict()))],
            purpose="health-refresh-finish",
        )
        return record

    def _publish(
        self,
        current: HealthRefresh,
        normalized: NormalizationResult,
        *,
        snapshot_id: str | None,
        completed_at: str | None,
    ) -> tuple[HealthSnapshot, HealthRefresh]:
        if current.state != "running":
            raise HealthStoreError("only a running refresh can publish a snapshot")
        if not isinstance(normalized, NormalizationResult):
            raise TypeError("refresh publication requires a NormalizationResult")
        if normalized.report.refresh_id != current.refresh_id:
            raise IncompleteHealthReport("report refresh_id does not match the active refresh")
        if not normalized.accepted:
            raise IncompleteHealthReport(
                "health snapshot requires an accepted complete reporter envelope: "
                + "; ".join(normalized.errors)
            )
        snapshot_identity = (
            f"snapshot-{uuid.uuid4().hex}" if snapshot_id is None else snapshot_id
        )
        self._validate_snapshot_id(snapshot_identity)
        completed = self._timestamp() if completed_at is None else completed_at
        if not _timestamp(completed):
            raise ValueError("completed_at must be timezone-aware ISO-8601")
        snapshot = HealthSnapshot.from_normalized(
            normalized,
            snapshot_id=snapshot_identity,
            completed_at=completed,
        )

        # The immutable blob is committed before any pointer can name it. A
        # collision fails closed; existing snapshots are never overwritten.
        snapshot_relative = self._snapshot_relative(snapshot.snapshot_id)
        try:
            self._write_plan(
                [self._new_file_entry(snapshot_relative, _canonical(snapshot.to_dict()))],
                purpose="health-snapshot-write",
            )
        except Exception as error:
            target = self.root / snapshot_relative
            if target.exists():
                raise SnapshotAlreadyExists(snapshot.snapshot_id) from error
            raise

        pointer = LatestPointer(snapshot_id=snapshot.snapshot_id, published_at=completed)
        complete = replace(
            current,
            state="complete",
            updated_at=completed,
            completed_at=completed,
            snapshot_id=snapshot.snapshot_id,
            detail=None,
        )
        refresh_relative = self._refresh_relative(current.refresh_id)
        refresh_target = self.root / refresh_relative
        if not refresh_target.is_file():
            raise HealthStoreCorruption("running refresh record disappeared before publication")

        # Deletions are placed after the new pointer and terminal refresh state
        # in the same transaction. Transaction rollback therefore preserves the
        # previous pointer if any guarded prune cannot be completed.
        plan = [
            self._replace_file_entry(LATEST_RELATIVE.as_posix(), _canonical(pointer.to_dict())),
            self._replace_file_entry(refresh_relative, _canonical(complete.to_dict())),
        ]
        plan.extend(self._retention_deletions(snapshot.snapshot_id))
        self._write_plan(plan, purpose="health-snapshot-publish")
        return snapshot, complete

    def _retention_deletions(self, current_snapshot_id: str) -> list[PlanEntry]:
        snapshots: list[HealthSnapshot] = []
        if self.snapshots_dir.exists():
            for path in sorted(self.snapshots_dir.glob("*.json")):
                try:
                    snapshots.append(HealthSnapshot.from_mapping(_read_json(path, kind="health snapshot")))
                except (HealthStoreCorruption, OSError):
                    # Do not destroy an unreadable artifact while pruning. It
                    # remains available for diagnosis and is outside the valid
                    # snapshot set used for bounded retention.
                    continue
        snapshots.sort(key=lambda item: (item.completed_at, item.snapshot_id), reverse=True)
        keep = {item.snapshot_id for item in snapshots[: self.retention]}
        keep.add(current_snapshot_id)
        entries: list[PlanEntry] = []
        for snapshot in snapshots:
            if snapshot.snapshot_id in keep:
                continue
            entry = self._delete_entry(self.root / self._snapshot_relative(snapshot.snapshot_id))
            if entry is not None:
                entries.append(entry)
        return entries

    def read_latest(self) -> HealthSnapshot | None:
        """Read the latest complete snapshot without creating or mutating state."""

        try:
            pointer = LatestPointer.from_mapping(_read_json(self.latest_path, kind="health latest pointer"))
        except FileNotFoundError:
            return None
        snapshot_path = self.root / self._snapshot_relative(pointer.snapshot_id)
        try:
            snapshot = HealthSnapshot.from_mapping(_read_json(snapshot_path, kind="health snapshot"))
        except FileNotFoundError as error:
            raise HealthStoreCorruption("latest pointer names a missing snapshot") from error
        if snapshot.snapshot_id != pointer.snapshot_id:
            raise HealthStoreCorruption("latest pointer and snapshot identities differ")
        return snapshot

    def read_history(self, *, limit: int = 2) -> tuple[HealthSnapshot, ...]:
        """Read the newest complete snapshots without changing health state."""

        if type(limit) is not int or limit < 1:
            raise ValueError("health history limit must be a positive integer")
        latest = self.read_latest()
        if latest is None:
            return ()

        snapshots: dict[str, HealthSnapshot] = {latest.snapshot_id: latest}
        if self.snapshots_dir.exists():
            for path in sorted(self.snapshots_dir.glob("*.json")):
                try:
                    snapshot = HealthSnapshot.from_mapping(
                        _read_json(path, kind="health snapshot")
                    )
                except (HealthStoreCorruption, OSError):
                    continue
                snapshots[snapshot.snapshot_id] = snapshot
        ordered = sorted(
            snapshots.values(),
            key=lambda item: (item.completed_at, item.snapshot_id),
            reverse=True,
        )
        # The pointer is authoritative even if a clock moved backwards between
        # refreshes; never let an older timestamp displace the current pointer.
        ordered.remove(latest)
        ordered.insert(0, latest)
        return tuple(ordered[:limit])

    def read_refresh(self, refresh_id: str) -> HealthRefresh | None:
        relative = self._refresh_relative(refresh_id)
        try:
            record = HealthRefresh.from_mapping(
                _read_json(self.root / relative, kind="health refresh")
            )
        except FileNotFoundError:
            return None
        if record.refresh_id != refresh_id:
            raise HealthStoreCorruption("health refresh path and identity differ")
        return record


__all__ = [
    "DEFAULT_RETENTION",
    "HEALTH_RELATIVE",
    "HealthRefresh",
    "HealthRefreshAlreadyExists",
    "HealthRefreshBusyError",
    "HealthRefreshSession",
    "HealthSnapshot",
    "HealthStore",
    "HealthStoreError",
    "HealthStoreCorruption",
    "IncompleteHealthReport",
    "LatestPointer",
    "REFRESH_STATES",
    "SNAPSHOT_CONTRACT",
    "SnapshotAlreadyExists",
]
