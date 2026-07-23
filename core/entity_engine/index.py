"""Disposable SQLite projection of Dex person and company pages."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

from core.entity_engine.contract import parse_entity_page
from core.lifecycle.inventory import load_folder_map
from core.paths import COMPANIES_DIR, PEOPLE_DIR, VAULT_ROOT
from core.utils.company_domains import registrable_domain

# Vault-relative PARA roots derived from the canonical core.paths constants
# (POSIX strings, computed at import time). Using these instead of raw PARA path
# literals keeps the path-contract gate satisfied while staying folder-map aware.
_PEOPLE_INTERNAL_REL = (PEOPLE_DIR / "Internal").relative_to(VAULT_ROOT).as_posix()
_PEOPLE_EXTERNAL_REL = (PEOPLE_DIR / "External").relative_to(VAULT_ROOT).as_posix()
_PEOPLE_CPO_REL = (PEOPLE_DIR / "CPO_Network").relative_to(VAULT_ROOT).as_posix()
_COMPANIES_REL = COMPANIES_DIR.relative_to(VAULT_ROOT).as_posix()

SCHEMA_VERSION = "1"
DEFAULT_DEBOUNCE_SECONDS = 0.25
_DATABASE_RELATIVE_PATH = Path("System/.dex/entity-index/database.sqlite3")
_PEOPLE_EXPORT_RELATIVE_PATH = Path("System/People_Index.json")
_COMPANY_EXPORT_RELATIVE_PATH = Path("System/Company_Index.json")
_GOES_BY_RE = re.compile(
    r"^\s*(?:\*\*)?Goes by(?::\*\*|\*\*\s*:|\s+)(?:\s*)(.+?)\s*$",
    re.IGNORECASE,
)
_INVERSE_EDGE_LABELS = {
    "works_at": "employs",
    "part_of": "contains",
}
_T = TypeVar("_T")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_files (
    path TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    entity_type TEXT,
    quarantined INTEGER NOT NULL DEFAULT 0,
    indexed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT,
    role TEXT,
    company TEXT,
    status TEXT,
    location TEXT,
    last_interaction TEXT,
    fields_json TEXT NOT NULL,
    source_path TEXT NOT NULL REFERENCES source_files(path) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_company ON nodes(company);

CREATE TABLE IF NOT EXISTS node_keys (
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (node_id, kind, value)
);
CREATE INDEX IF NOT EXISTS idx_node_keys_value ON node_keys(kind, value);

CREATE TABLE IF NOT EXISTS edges (
    src_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    dst_id TEXT,
    dst_ref TEXT,
    source_path TEXT NOT NULL REFERENCES source_files(path) ON DELETE CASCADE,
    PRIMARY KEY (src_id, edge_type, dst_id, dst_ref)
);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id, edge_type);

CREATE TABLE IF NOT EXISTS touches (
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    touch_type TEXT NOT NULL,
    direction TEXT,
    source TEXT,
    nature TEXT,
    source_path TEXT NOT NULL REFERENCES source_files(path) ON DELETE CASCADE,
    PRIMARY KEY (node_id, ts, touch_type, source)
);
CREATE INDEX IF NOT EXISTS idx_touches_node ON touches(node_id, ts);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class _FailedQuickCheck(sqlite3.DatabaseError):
    pass


@dataclass(frozen=True)
class _Source:
    path: Path
    relative_path: str
    entity_type: str
    people_type: str | None
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class _PreparedSource:
    source: _Source
    content: bytes
    fingerprint: str
    parsed: dict[str, Any]


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    signature: tuple[tuple[str, int, int], ...]


_RECONCILE_CACHE: dict[Path, _CacheEntry] = {}


def database_path(vault_root: str | Path) -> Path:
    return Path(vault_root) / _DATABASE_RELATIVE_PATH


def clear_reconcile_cache() -> None:
    """Clear the short-lived process cache, primarily for run boundaries and tests."""
    _RECONCILE_CACHE.clear()


def remove_database(path: str | Path) -> None:
    """Remove the disposable database and both SQLite sidecars as one rebuild unit."""
    db_path = Path(path)
    for candidate in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        candidate.unlink(missing_ok=True)
    _RECONCILE_CACHE.pop(db_path.resolve(), None)


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a configured connection and reject a database that fails quick_check."""
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=5.0)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        quick_check = connection.execute("PRAGMA quick_check").fetchall()
        if quick_check != [("ok",)]:
            raise _FailedQuickCheck(f"SQLite quick_check failed: {quick_check!r}")
        return connection
    except BaseException:
        connection.close()
        raise


def _is_corruption(error: BaseException) -> bool:
    if isinstance(error, _FailedQuickCheck):
        return True
    if not isinstance(error, sqlite3.Error):
        return False
    error_code = getattr(error, "sqlite_errorcode", None)
    if error_code is not None and error_code & 0xFF in {
        sqlite3.SQLITE_CORRUPT,
        sqlite3.SQLITE_NOTADB,
    }:
        return True
    message = str(error).casefold()
    return (
        "database disk image is malformed" in message
        or "file is not a database" in message
    )


def _is_busy(error: BaseException) -> bool:
    if not isinstance(error, sqlite3.OperationalError):
        return False
    error_code = getattr(error, "sqlite_errorcode", None)
    if error_code is not None and error_code & 0xFF == sqlite3.SQLITE_BUSY:
        return True
    message = str(error).casefold()
    return "database is locked" in message or "database is busy" in message


def _safe_relative(path: Path, vault_root: Path) -> str:
    return path.resolve().relative_to(vault_root.resolve()).as_posix()


def _scan_root(
    vault_root: Path,
    root: Path,
    entity_type: str,
    *,
    people_type: str | None = None,
    recursive: bool,
) -> Iterable[_Source]:
    if not root.exists():
        return
    paths = root.rglob("*.md") if recursive else root.glob("*.md")
    for path in sorted(paths):
        if path.name == "README.md":
            continue
        stat = path.stat()
        yield _Source(
            path=path,
            relative_path=_safe_relative(path, vault_root),
            entity_type=entity_type,
            people_type=people_type,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )


def _scan_sources(
    vault_root: Path,
    *,
    people_dir: str | Path | None,
    companies_dir: str | Path | None,
) -> dict[str, _Source]:
    sources: dict[str, _Source] = {}
    if people_dir is not None:
        people_root = Path(people_dir)
        roots = [
            (people_root / "Internal", "person", "internal", False),
            (people_root / "External", "person", "external", False),
            (people_root / "CPO_Network", "person", "cpo_network", False),
        ]
    else:
        folder_map = load_folder_map(vault_root)
        roots = [
            (
                vault_root / folder_map.materialize(_PEOPLE_INTERNAL_REL),
                "person",
                "internal",
                False,
            ),
            (
                vault_root / folder_map.materialize(_PEOPLE_EXTERNAL_REL),
                "person",
                "external",
                False,
            ),
            (
                vault_root / _PEOPLE_CPO_REL,
                "person",
                "cpo_network",
                False,
            ),
        ]
    if companies_dir is not None:
        roots.append((Path(companies_dir), "company", None, True))
    else:
        folder_map = load_folder_map(vault_root)
        roots.append(
            (
                vault_root / folder_map.materialize(_COMPANIES_REL),
                "company",
                None,
                True,
            )
        )
    for root, entity_type, people_type, recursive in roots:
        for source in _scan_root(
            vault_root,
            root,
            entity_type,
            people_type=people_type,
            recursive=recursive,
        ):
            sources[source.relative_path] = source
    return sources


def _fingerprint(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _person_compatibility_entry(
    source: _Source,
    parsed: dict[str, Any],
    content: str,
) -> dict[str, Any]:
    aliases = list(parsed.get("aliases") or [])
    folded_aliases = {value.casefold() for value in aliases}
    for line in content.splitlines():
        match = _GOES_BY_RE.match(line)
        if not match:
            continue
        alias = match.group(1).strip()
        if alias and alias.casefold() not in folded_aliases:
            aliases.append(alias)
            folded_aliases.add(alias.casefold())

    tags: list[str] = []
    for line in content.splitlines():
        if "**Tags**" in line and "|" in line:
            parts = line.split("|")
            if len(parts) >= 3:
                tags = [tag.strip() for tag in parts[2].strip().split(",") if tag.strip()]
            break

    name = parsed.get("name") or source.path.stem.replace("_", " ")
    has_content = bool(
        parsed.get("role")
        or parsed.get("emails")
        or "## Meeting" in content
        or "## Notes" in content
    )
    return {
        "name": name,
        "company": parsed.get("company"),
        "role": parsed.get("role"),
        "email": (parsed.get("emails") or [None])[0],
        "emails": parsed.get("emails") or [],
        "aliases": aliases,
        "first_name": name.split()[0].lower() if name.split() else "",
        "type": source.people_type or "external",
        "path": source.relative_path,
        "last_interaction": parsed.get("last_interaction"),
        "tags": tags,
        "status": "populated" if has_content else "stub",
    }


def _company_compatibility_entry(
    source: _Source,
    parsed: dict[str, Any],
) -> dict[str, Any]:
    return {
        "name": parsed.get("name") or source.path.stem.replace("_", " "),
        "path": source.relative_path,
        "domains": parsed.get("domains") or [],
        "website": parsed.get("website"),
        "status": parsed.get("status"),
    }


def _project_source(
    connection: sqlite3.Connection,
    prepared: _PreparedSource,
    *,
    indexed_at: str,
) -> None:
    source = prepared.source
    parsed = prepared.parsed
    quarantined = bool(parsed.get("quarantined"))
    connection.execute("DELETE FROM source_files WHERE path = ?", (source.relative_path,))
    connection.execute(
        """
        INSERT INTO source_files(
            path, fingerprint, size, mtime_ns, entity_type, quarantined, indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source.relative_path,
            prepared.fingerprint,
            source.size,
            source.mtime_ns,
            source.entity_type,
            int(quarantined),
            indexed_at,
        ),
    )
    if quarantined:
        name = source.path.stem.replace("_", " ")
        if source.entity_type == "person":
            first_name = name.split()[0].lower() if name.split() else ""
            compatibility = {
                "name": name,
                "company": None,
                "role": None,
                "email": None,
                "emails": [],
                "aliases": [],
                "first_name": first_name,
                "type": source.people_type or "external",
                "path": source.relative_path,
                "last_interaction": None,
                "tags": [],
                "status": "quarantined",
            }
        else:
            compatibility = {
                "name": name,
                "path": source.relative_path,
                "domains": [],
                "website": None,
                "status": "quarantined",
            }
        fields = {
            "name": name,
            "status": "quarantined",
            "_compat": compatibility,
        }
    else:
        decoded = prepared.content.decode("utf-8-sig")
        compatibility = (
            _person_compatibility_entry(source, parsed, decoded)
            if source.entity_type == "person"
            else _company_compatibility_entry(source, parsed)
        )
        fields = {**parsed, "_compat": compatibility}
    connection.execute(
        """
        INSERT INTO nodes(
            id, type, name, role, company, status, location, last_interaction,
            fields_json, source_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source.relative_path,
            source.entity_type,
            compatibility.get("name"),
            None if quarantined else parsed.get("role"),
            None if quarantined else parsed.get("company"),
            "quarantined" if quarantined else parsed.get("status"),
            None if quarantined else parsed.get("location"),
            None if quarantined else parsed.get("last_interaction"),
            json.dumps(fields, ensure_ascii=False, sort_keys=True),
            source.relative_path,
        ),
    )
    if quarantined:
        return

    keys: list[tuple[str, str]] = []
    if source.entity_type == "person":
        keys.extend(("email", value.casefold()) for value in compatibility["emails"])
        keys.extend(("alias", value.casefold()) for value in compatibility["aliases"])
    else:
        keys.extend(("domain", value.casefold()) for value in compatibility["domains"])
    connection.executemany(
        "INSERT OR IGNORE INTO node_keys(node_id, kind, value) VALUES (?, ?, ?)",
        [(source.relative_path, kind, value) for kind, value in keys],
    )


def _initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(_SCHEMA)
    connection.execute(
        """
        INSERT INTO meta(key, value) VALUES ('schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (SCHEMA_VERSION,),
    )


def _compatibility_rows(
    connection: sqlite3.Connection,
    entity_type: str,
) -> list[dict[str, Any]]:
    rows = []
    for (fields_json,) in connection.execute(
        "SELECT fields_json FROM nodes WHERE type = ?",
        (entity_type,),
    ):
        fields = json.loads(fields_json)
        rows.append(fields["_compat"])
    if entity_type == "person":
        type_order = {"internal": 0, "external": 1, "cpo_network": 2}
        rows.sort(
            key=lambda item: (
                type_order.get(item["type"], 3),
                item["path"].casefold(),
            )
        )
    else:
        rows.sort(key=lambda item: (item["name"].casefold(), item["path"]))
    return rows


def _built_at(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT value FROM meta WHERE key = 'built_at'"
    ).fetchone()
    return row[0] if row else datetime.now().isoformat()


def _views(connection: sqlite3.Connection) -> tuple[dict[str, Any], dict[str, Any]]:
    built_at = _built_at(connection)
    people = _compatibility_rows(connection, "person")
    companies = _compatibility_rows(connection, "company")
    people_view = {
        "version": 2,
        "built_at": built_at,
        "total": len(people),
        "by_type": {
            "internal": sum(item["type"] == "internal" for item in people),
            "external": sum(item["type"] == "external" for item in people),
            "cpo_network": sum(item["type"] == "cpo_network" for item in people),
        },
        "people": people,
    }
    company_view = {
        "version": 1,
        "built_at": built_at,
        "total": len(companies),
        "companies": companies,
    }
    return people_view, company_view


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def dump_json_views(
    connection: sqlite3.Connection,
    vault_root: str | Path,
    *,
    people_index_path: str | Path | None = None,
    company_index_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Export compatibility JSON views from the reconciled SQLite projection."""
    root = Path(vault_root)
    people_view, company_view = _views(connection)
    _write_json(
        Path(people_index_path)
        if people_index_path is not None
        else root / _PEOPLE_EXPORT_RELATIVE_PATH,
        people_view,
    )
    _write_json(
        Path(company_index_path)
        if company_index_path is not None
        else root / _COMPANY_EXPORT_RELATIVE_PATH,
        company_view,
    )
    return people_view, company_view


def _reconcile_open_database(
    connection: sqlite3.Connection,
    vault_root: Path,
    sources: dict[str, _Source],
    *,
    people_index_path: str | Path | None,
    company_index_path: str | Path | None,
) -> dict[str, int]:
    with connection:
        _initialize_schema(connection)
    indexed = {
        row[0]: (row[1], row[2], row[3])
        for row in connection.execute(
            "SELECT path, fingerprint, size, mtime_ns FROM source_files"
        )
    }
    current_paths = set(sources)
    indexed_paths = set(indexed)
    removed = indexed_paths - current_paths
    added = current_paths - indexed_paths
    present = current_paths & indexed_paths
    changed = 0
    indexed_at = datetime.now().isoformat()
    prepared: dict[str, _PreparedSource] = {}

    for relative_path in sorted(added):
        source = sources[relative_path]
        content = source.path.read_bytes()
        prepared[relative_path] = _PreparedSource(
            source=source,
            content=content,
            fingerprint=_fingerprint(content),
            parsed=parse_entity_page(source.path),
        )
    for relative_path in sorted(present):
        source = sources[relative_path]
        _old_fingerprint, old_size, old_mtime_ns = indexed[relative_path]
        # Accepted risk: unchanged size and mtime skip re-hashing on normal filesystems.
        if (source.size, source.mtime_ns) == (old_size, old_mtime_ns):
            continue
        content = source.path.read_bytes()
        prepared[relative_path] = _PreparedSource(
            source=source,
            content=content,
            fingerprint=_fingerprint(content),
            parsed=parse_entity_page(source.path),
        )

    with connection:
        connection.executemany(
            "DELETE FROM source_files WHERE path = ?",
            [(path,) for path in sorted(removed)],
        )
        for relative_path in sorted(added):
            _project_source(
                connection,
                prepared[relative_path],
                indexed_at=indexed_at,
            )
        for relative_path in sorted(present):
            candidate = prepared.get(relative_path)
            if candidate is None:
                continue
            source = candidate.source
            old_fingerprint, old_size, old_mtime_ns = indexed[relative_path]
            if candidate.fingerprint == old_fingerprint:
                connection.execute(
                    """
                    UPDATE source_files
                    SET size = ?, mtime_ns = ?, indexed_at = ?
                    WHERE path = ?
                    """,
                    (
                        source.size,
                        source.mtime_ns,
                        indexed_at,
                        relative_path,
                    ),
                )
                continue
            _project_source(
                connection,
                candidate,
                indexed_at=indexed_at,
            )
            changed += 1
        connection.execute(
            """
            INSERT INTO meta(key, value) VALUES ('built_at', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (indexed_at,),
        )

    dump_json_views(
        connection,
        vault_root,
        people_index_path=people_index_path,
        company_index_path=company_index_path,
    )
    return {"added": len(added), "changed": changed, "removed": len(removed)}


def reconcile(
    vault_root: str | Path,
    *,
    people_dir: str | Path | None = None,
    companies_dir: str | Path | None = None,
    people_index_path: str | Path | None = None,
    company_index_path: str | Path | None = None,
    force: bool = False,
    debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
) -> dict[str, int]:
    """Reconcile the materialized view using a complete path-set diff."""
    root = Path(vault_root)
    db_path = database_path(root)
    sources = _scan_sources(
        root,
        people_dir=people_dir,
        companies_dir=companies_dir,
    )
    signature = tuple(
        (path, source.size, source.mtime_ns)
        for path, source in sorted(sources.items())
    )
    cache_key = db_path.resolve()
    cached = _RECONCILE_CACHE.get(cache_key)
    if (
        not force
        and db_path.exists()
        and cached is not None
        and cached.expires_at >= time.monotonic()
        and cached.signature == signature
    ):
        return {"added": 0, "changed": 0, "removed": 0}

    try:
        with closing(connect(db_path)) as connection:
            result = _reconcile_open_database(
                connection,
                root,
                sources,
                people_index_path=people_index_path,
                company_index_path=company_index_path,
            )
    except sqlite3.Error as error:
        if not _is_corruption(error):
            raise
        remove_database(db_path)
        with closing(connect(db_path)) as connection:
            result = _reconcile_open_database(
                connection,
                root,
                sources,
                people_index_path=people_index_path,
                company_index_path=company_index_path,
            )

    _RECONCILE_CACHE[cache_key] = _CacheEntry(
        expires_at=time.monotonic() + debounce_seconds,
        signature=signature,
    )
    return result


def build_from_vault(
    vault_root: str | Path,
    *,
    people_dir: str | Path | None = None,
    companies_dir: str | Path | None = None,
    people_index_path: str | Path | None = None,
    company_index_path: str | Path | None = None,
) -> dict[str, int]:
    """Delete any prior projection and rebuild it entirely from entity pages."""
    remove_database(database_path(vault_root))
    return reconcile(
        vault_root,
        people_dir=people_dir,
        companies_dir=companies_dir,
        people_index_path=people_index_path,
        company_index_path=company_index_path,
        force=True,
    )


def _read_after_reconcile(
    vault_root: str | Path,
    reconcile_kwargs: dict[str, Any],
    reader: Callable[[sqlite3.Connection], _T],
) -> _T:
    db_path = database_path(vault_root)
    try:
        with closing(connect(db_path)) as connection:
            return reader(connection)
    except sqlite3.Error as error:
        if not _is_corruption(error):
            raise
        remove_database(db_path)
        reconcile(vault_root, force=True, **reconcile_kwargs)
        with closing(connect(db_path)) as connection:
            return reader(connection)


def people_index_data(
    vault_root: str | Path,
    *,
    people_dir: str | Path | None = None,
    companies_dir: str | Path | None = None,
    people_index_path: str | Path | None = None,
    company_index_path: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    reconcile_kwargs = {
        "people_dir": people_dir,
        "companies_dir": companies_dir,
        "people_index_path": people_index_path,
        "company_index_path": company_index_path,
    }
    try:
        reconcile(
            vault_root,
            **reconcile_kwargs,
            force=force,
        )
        return _read_after_reconcile(
            vault_root,
            reconcile_kwargs,
            lambda connection: _views(connection)[0],
        )
    except sqlite3.Error as error:
        if not _is_busy(error):
            raise
        export_path = (
            Path(people_index_path)
            if people_index_path is not None
            else Path(vault_root) / _PEOPLE_EXPORT_RELATIVE_PATH
        )
        try:
            return json.loads(export_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise error


def company_index_data(
    vault_root: str | Path,
    *,
    people_dir: str | Path | None = None,
    companies_dir: str | Path | None = None,
    people_index_path: str | Path | None = None,
    company_index_path: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    reconcile_kwargs = {
        "people_dir": people_dir,
        "companies_dir": companies_dir,
        "people_index_path": people_index_path,
        "company_index_path": company_index_path,
    }
    try:
        reconcile(
            vault_root,
            **reconcile_kwargs,
            force=force,
        )
        return _read_after_reconcile(
            vault_root,
            reconcile_kwargs,
            lambda connection: _views(connection)[1],
        )
    except sqlite3.Error as error:
        if not _is_busy(error):
            raise
        export_path = (
            Path(company_index_path)
            if company_index_path is not None
            else Path(vault_root) / _COMPANY_EXPORT_RELATIVE_PATH
        )
        try:
            return json.loads(export_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise error


def lookup_person(
    vault_root: str | Path,
    name: str,
    company: str | None = None,
    **reconcile_kwargs: Any,
) -> dict[str, Any]:
    """Return the legacy Work-MCP lookup shape from reconciled SQLite rows."""
    index = people_index_data(vault_root, **reconcile_kwargs)
    people = index["people"]
    if company:
        company_lower = company.lower()
        people = [
            person
            for person in people
            if company_lower in (person.get("company") or "").lower()
        ]

    query = name.strip()
    query_lower = query.casefold()
    ambiguous = False

    def scored(candidates: list[dict[str, Any]], score: float) -> list[dict[str, Any]]:
        return [{**person, "_score": score} for person in candidates]

    matches: list[dict[str, Any]] = []
    if "@" in query:
        matches = scored(
            [
                person
                for person in people
                if query_lower
                in {email.casefold() for email in person.get("emails", [])}
            ],
            1.0,
        )
    if not matches:
        matches = scored(
            [
                person
                for person in people
                if query_lower
                in {alias.casefold() for alias in person.get("aliases", [])}
            ],
            1.0,
        )
    if not matches:
        matches = scored(
            [
                person
                for person in people
                if query_lower == (person.get("name") or "").casefold()
            ],
            1.0,
        )
    if not matches:
        first_name_matches = [
            person
            for person in people
            if query_lower == (person.get("first_name") or "").casefold()
        ]
        if first_name_matches:
            matches = scored(first_name_matches, 0.9)
            ambiguous = len(first_name_matches) > 1
    if not matches:
        fuzzy_matches = []
        for person in people:
            person_name = (person.get("name") or "").casefold()
            if query_lower in person_name or person_name in query_lower:
                score = 0.8
            else:
                score = SequenceMatcher(None, query_lower, person_name).ratio()
            if score >= 0.5:
                fuzzy_matches.append((score, person))
        fuzzy_matches.sort(key=lambda item: item[0], reverse=True)
        if (
            len(fuzzy_matches) >= 2
            and fuzzy_matches[0][0] - fuzzy_matches[1][0] <= 0.05
        ):
            ambiguous = True
        matches = [
            {**person, "_score": round(score, 2)}
            for score, person in fuzzy_matches
        ]

    result: dict[str, Any] = {
        "query": name,
        "company_filter": company,
        "matches": matches[:10],
        "total_matches": len(matches),
        "index_age": index["built_at"],
    }
    if ambiguous:
        result["ambiguous"] = True
    return result


def find_company_by_domain(
    vault_root: str | Path,
    domain: str,
    **reconcile_kwargs: Any,
) -> dict[str, Any] | None:
    """Find a company by registrable domain from the reconciled projection."""
    index = company_index_data(vault_root, **reconcile_kwargs)
    target = registrable_domain(domain)
    for company in index["companies"]:
        if target in {
            registrable_domain(value) for value in company.get("domains", [])
        }:
            return company
    return None


def neighbors(
    vault_root: str | Path,
    node_id: str,
    **reconcile_kwargs: Any,
) -> list[dict[str, str | None]]:
    """Return stored outgoing edges and query-derived inverse edges."""
    people_index_data(vault_root, **reconcile_kwargs)

    def read(connection: sqlite3.Connection) -> list[dict[str, str | None]]:
        result = [
            {
                "other": dst_id or dst_ref,
                "edge_type": edge_type,
                "direction": "out",
                "label": edge_type,
            }
            for edge_type, dst_id, dst_ref in connection.execute(
                """
                SELECT edge_type, dst_id, dst_ref
                FROM edges
                WHERE src_id = ?
                ORDER BY edge_type, COALESCE(dst_id, dst_ref)
                """,
                (node_id,),
            )
        ]
        result.extend(
            {
                "other": src_id,
                "edge_type": edge_type,
                "direction": "in",
                "label": _INVERSE_EDGE_LABELS.get(edge_type, edge_type),
            }
            for edge_type, src_id in connection.execute(
                """
                SELECT edge_type, src_id
                FROM edges
                WHERE dst_id = ?
                ORDER BY edge_type, src_id
                """,
                (node_id,),
            )
        )
        return result

    return _read_after_reconcile(vault_root, reconcile_kwargs, read)
