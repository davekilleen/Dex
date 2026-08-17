"""Read-only Apple Mail search health adapter.

The community MCP server can list and read mail without its local FTS5 index,
which makes search failures unusually easy to hide.  This module keeps the
integration-specific config, SQLite, freshness, and privacy checks out of the
Doctor orchestrator.
"""

from __future__ import annotations

import json
import os
import shlex
import sqlite3
import stat
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping

APPLE_MAIL_CONFIG_VERSION = 1
APPLE_MAIL_DEFAULT_STALENESS_HOURS = 24.0
APPLE_MAIL_MCP_SUPPORTED_VERSION = "0.4.3"
APPLE_MAIL_MCP_INSTALL = f"pipx install 'apple-mail-mcp=={APPLE_MAIL_MCP_SUPPORTED_VERSION}'"
APPLE_MAIL_CONFIG_SCHEMA: dict[str, dict[str, tuple[type, ...]]] = {
    "defaults": {"account": (str,), "mailbox": (str,)},
    "index": {
        "path": (str,),
        "max_emails": (int,),
        "staleness_hours": (int, float),
        "exclude_mailboxes": (list,),
        "exclude_accounts": (list,),
        "include_mailboxes": (list,),
    },
    "server": {"read_only": (bool,), "lock_retry_seconds": (int, float)},
}
REQUIRED_EMAIL_COLUMNS = {
    "rowid",
    "message_id",
    "account",
    "mailbox",
    "subject",
    "sender",
    "content",
    "date_received",
    "emlx_path",
}
REQUIRED_SYNC_COLUMNS = {"account", "mailbox", "last_sync", "message_count"}
REQUIRED_FTS_TRIGGERS = {"emails_ai", "emails_ad", "emails_au"}


def setup_action(command: str) -> str:
    """Return the exact index command plus the Full Disk Access prerequisite."""
    operation = "rebuilding" if command == "rebuild" else "building"
    return (
        f"Run `umask 077; apple-mail-mcp {command} --verbose` from a terminal app "
        "granted Full Disk Access: System Settings > Privacy & Security > "
        "Full Disk Access. Quit and reopen that terminal before "
        f"{operation}. The app that launches the Mail server (Dex, Claude, or Cursor) "
        "also needs Full Disk Access — background sync reads ~/Library/Mail, and a "
        "fresh-looking index can still be frozen if that grant is missing."
    )


APPLE_MAIL_INDEX_BUILD_FIX = setup_action("index")
APPLE_MAIL_INDEX_REBUILD_FIX = setup_action("rebuild")
APPLE_MAIL_SERVING_FDA_FIX = (
    "Grant Full Disk Access to the app that launches the Mail server (Dex, Claude, or Cursor), "
    "not only the terminal that ran `apple-mail-mcp index`: System Settings > Privacy & Security > "
    "Full Disk Access. Quit and reopen that app, then run /apple-mail-setup. "
    "Background sync reads ~/Library/Mail; without that grant it can report a fresh sync after reading nothing."
)
APPLE_MAIL_STORE_RELATIVE = Path("Library") / "Mail"


@dataclass(frozen=True)
class Context:
    home: Path
    vault_root: Path
    now: datetime
    user_config_path: Path
    project_config_path: Path
    environment: Mapping[str, str]
    macos: bool
    cli_present: bool


@dataclass(frozen=True)
class IndexSettings:
    path: Path
    stale_after: timedelta


@dataclass(frozen=True)
class Result:
    verdict: str
    detail: str
    action: str | None = None
    feature_status: str | None = None
    user_message: str | None = None


# Keys a silent-empty search would use. Email-aware flows must never treat a
# missing or unusable index as "no matching mail."
_SEARCH_RESULT_KEYS = ("emails", "results", "messages", "matches")
EMAIL_CONTEXT_OMITTED_PREFIX = "Email context omitted"


def omission_line(result: Result) -> str:
    """Return the one visible line a daily plan / week review must show."""
    message = result.user_message or result.detail
    return f"{EMAIL_CONTEXT_OMITTED_PREFIX} — {message}"


def flow_status(context: Context) -> dict[str, object]:
    """Fail-closed readiness for email-aware flows.

    A missing or unusable index is a visible broken state, never an empty
    search result. Only ``feature_status: ok`` allows the existing Mail MCP
    search path to run.
    """
    result = probe(context)
    status = result.feature_status or "unknown"
    usable = status == "ok"
    payload: dict[str, object] = {
        "feature_status": status,
        "verdict": result.verdict,
        "usable": usable,
        "search": "allowed" if usable else "blocked",
        "detail": result.detail,
    }
    if result.user_message:
        payload["user_message"] = result.user_message
    if result.action:
        payload["action"] = result.action
    if not usable and status != "off":
        payload["visible"] = omission_line(result)
    return payload


def _one_line(error: BaseException) -> str:
    return " ".join(str(error).split())


def _read_servers(path: Path, *, servers_optional: bool) -> dict[str, object]:
    try:
        loaded = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise ValueError(f"{path} could not be read: {_one_line(error)}") from error
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    if "mcpServers" not in loaded and servers_optional:
        return {}
    servers = loaded.get("mcpServers")
    if not isinstance(servers, dict):
        raise ValueError(f"{path} must contain an mcpServers object")
    return servers


def _registration(context: Context) -> dict[str, object] | None:
    entries = _read_servers(context.user_config_path, servers_optional=True)
    entries.update(_read_servers(context.project_config_path, servers_optional=False))
    for name, entry in entries.items():
        if "apple-mail" in name.lower().replace("_", "-"):
            if not isinstance(entry, dict):
                raise ValueError(f"Apple Mail MCP registration {name!r} must be an object")
            return entry
        if not isinstance(entry, dict):
            continue
        tokens = [str(entry.get("command", ""))]
        args = entry.get("args", [])
        if isinstance(args, list):
            tokens.extend(str(argument) for argument in args if isinstance(argument, str))
        if any("apple-mail-mcp" in token for token in tokens):
            return entry
    return None


def _validate_config(data: dict[str, object], path: Path) -> None:
    version = data.get("config_version")
    if version != APPLE_MAIL_CONFIG_VERSION:
        raise ValueError(f"{path} must set config_version = {APPLE_MAIL_CONFIG_VERSION}; got {version!r}")
    allowed_top = {"config_version", *APPLE_MAIL_CONFIG_SCHEMA}
    unknown_top = sorted(set(data) - allowed_top)
    if unknown_top:
        raise ValueError(f"{path} has unknown top-level key {unknown_top[0]!r}")
    for section, allowed in APPLE_MAIL_CONFIG_SCHEMA.items():
        section_data = data.get(section)
        if section_data is None:
            continue
        if not isinstance(section_data, dict):
            raise ValueError(f"{path} [{section}] must be a TOML table")
        for key, value in section_data.items():
            if key not in allowed:
                raise ValueError(f"{path} has unknown [{section}] key {key!r}")
            expected = allowed[key]
            bool_in_number_slot = isinstance(value, bool) and bool not in expected and int in expected
            if bool_in_number_slot or not isinstance(value, expected):
                names = " or ".join(item.__name__ for item in expected)
                raise ValueError(f"{path} [{section}] {key} must be {names}")
            if isinstance(value, list) and any(not isinstance(item, str) for item in value):
                raise ValueError(f"{path} [{section}] {key} must contain only strings")
    index = data.get("index", {})
    if isinstance(index, dict):
        if "max_emails" in index and index["max_emails"] < 0:
            raise ValueError(f"{path} [index] max_emails must be zero or greater")
        if "staleness_hours" in index and index["staleness_hours"] < 0:
            raise ValueError(f"{path} [index] staleness_hours must be zero or greater")
    server = data.get("server", {})
    if isinstance(server, dict) and "lock_retry_seconds" in server and server["lock_retry_seconds"] < 1:
        raise ValueError(f"{path} [server] lock_retry_seconds must be at least 1")


def _config(context: Context) -> dict[str, object]:
    path = context.home / ".apple-mail-mcp" / "config.toml"
    try:
        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"Apple Mail config could not be read: {_one_line(error)}") from error
    if not isinstance(loaded, dict):
        raise ValueError("Apple Mail config must contain a TOML object")
    _validate_config(loaded, path)
    return loaded


def _expand_path(raw: object, context: Context) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ValueError("Apple Mail index path must be a non-empty string")
    rendered = raw.replace("${HOME}", str(context.home)).replace("$HOME", str(context.home))
    if rendered == "~":
        return context.home
    if rendered.startswith("~/"):
        return context.home / rendered[2:]
    path = Path(rendered)
    # apple-mail-mcp uses Path(...).expanduser(), so a relative value is resolved
    # from the server process cwd. Dex launches the project MCP from the vault.
    return path if path.is_absolute() else context.vault_root / path


def _settings(context: Context, registration: dict[str, object]) -> IndexSettings:
    config = _config(context)
    index_config = config.get("index", {})
    if not isinstance(index_config, dict):
        raise ValueError("Apple Mail config [index] must be a TOML table")
    registered_environment = registration.get("env", {})
    if not isinstance(registered_environment, dict):
        raise ValueError("Apple Mail MCP registration env must be an object")
    environment = {
        str(key): str(value)
        for key, value in registered_environment.items()
        if isinstance(key, str) and isinstance(value, (str, int, float))
    }
    # Match the server contract: the process environment overrides TOML.  The
    # registration env is the process environment Claude will give the server;
    # an actual process override wins when Doctor is run in that same runtime.
    environment.update({key: value for key, value in context.environment.items() if key.startswith("APPLE_MAIL_")})
    raw_path = environment.get("APPLE_MAIL_INDEX_PATH") or index_config.get("path")
    path = _expand_path(raw_path, context) if raw_path else context.home / ".apple-mail-mcp" / "index.db"
    raw_staleness: object = environment.get("APPLE_MAIL_INDEX_STALENESS_HOURS", "")
    if raw_staleness in (None, ""):
        raw_staleness = index_config.get("staleness_hours", APPLE_MAIL_DEFAULT_STALENESS_HOURS)
    try:
        staleness_hours = float(raw_staleness)
    except (TypeError, ValueError) as error:
        raise ValueError("Apple Mail index staleness_hours must be a number") from error
    if staleness_hours < 0:
        raise ValueError("Apple Mail index staleness_hours must be zero or greater")
    return IndexSettings(path=path, stale_after=timedelta(hours=staleness_hours))


def _private_files(index: Path) -> list[Path]:
    bases = {index, index.resolve()}
    candidates = {path for base in bases for path in (base, Path(f"{base}-wal"), Path(f"{base}-shm"))}
    return sorted(path for path in candidates if path.exists())


def _permissions_result(index: Path) -> Result | None:
    exposed = [path for path in _private_files(index) if stat.S_IMODE(path.stat().st_mode) != 0o600]
    if not exposed:
        return None
    names = ", ".join(str(path) for path in exposed)
    command = "chmod 600 " + " ".join(shlex.quote(str(path)) for path in exposed)
    return Result(
        "BROKEN",
        f"Apple Mail's local full-text index files do not have the required 0600 permissions: {names}",
        action=f"Make the index private with `{command}`.",
        feature_status="broken",
        user_message=(
            "Mail search's local index contains message subjects, senders, bodies, file paths, "
            f"and attachment metadata. Make it private with `{command}`."
        ),
    )


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _index_state(index: Path) -> tuple[int, tuple[str, ...]]:
    uri = index.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=2) as connection:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if not quick_check or quick_check[0] != "ok":
            raise sqlite3.DatabaseError(f"SQLite quick check returned {quick_check!r}")
        objects = {
            str(row[0]): (str(row[1]), str(row[2] or ""))
            for row in connection.execute(
                "SELECT name, type, sql FROM sqlite_master WHERE type IN ('table', 'view', 'trigger')"
            )
        }
        required = {"schema_version", "emails", "emails_fts", "sync_state"}
        missing = sorted(required - set(objects))
        if missing:
            raise sqlite3.DatabaseError(f"missing required tables: {', '.join(missing)}")
        fts_sql = objects["emails_fts"][1].upper()
        if "VIRTUAL TABLE" not in fts_sql or "USING FTS5" not in fts_sql:
            raise sqlite3.DatabaseError("emails_fts is not an FTS5 virtual table")
        missing_triggers = sorted(REQUIRED_FTS_TRIGGERS - set(objects))
        if missing_triggers:
            raise sqlite3.DatabaseError(f"missing FTS maintenance triggers: {', '.join(missing_triggers)}")
        missing_email_columns = sorted(REQUIRED_EMAIL_COLUMNS - _columns(connection, "emails"))
        if missing_email_columns:
            raise sqlite3.DatabaseError(f"emails is missing columns: {', '.join(missing_email_columns)}")
        missing_sync_columns = sorted(REQUIRED_SYNC_COLUMNS - _columns(connection, "sync_state"))
        if missing_sync_columns:
            raise sqlite3.DatabaseError(f"sync_state is missing columns: {', '.join(missing_sync_columns)}")
        version_row = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        if not version_row or not isinstance(version_row[0], int) or version_row[0] < 1:
            raise sqlite3.DatabaseError("schema_version has no supported version")
        email_count = int(connection.execute("SELECT COUNT(*) FROM emails").fetchone()[0])
        # The FTS5 docsize shadow table proves that each base row has a searchable
        # document without reading any subject, sender, or body text.
        indexed_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM emails e JOIN emails_fts_docsize fts ON fts.id = e.rowid"
            ).fetchone()[0]
        )
        if indexed_count != email_count:
            raise sqlite3.DatabaseError(f"FTS5 contains {indexed_count} searchable rows for {email_count} messages")
        connection.execute("CREATE VIRTUAL TABLE temp.apple_mail_health_vocab USING fts5vocab(main, emails_fts, 'row')")
        searchable_terms = int(connection.execute("SELECT COUNT(*) FROM temp.apple_mail_health_vocab").fetchone()[0])
        if email_count and searchable_terms == 0:
            raise sqlite3.DatabaseError("FTS5 contains no searchable terms")
        required_syncs = connection.execute(
            """
            SELECT state.last_sync
            FROM (SELECT DISTINCT account, mailbox FROM emails) AS indexed
            LEFT JOIN sync_state AS state
              ON state.account = indexed.account
             AND state.mailbox = indexed.mailbox
            """
        ).fetchall()
    if email_count and (not required_syncs or any(row[0] is None for row in required_syncs)):
        raise sqlite3.DatabaseError("one or more indexed mailboxes has no successful sync")
    return email_count, tuple(str(row[0]) for row in required_syncs)


def _sync_age(now: datetime, raw_timestamp: str) -> timedelta:
    try:
        synced = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid last-sync timestamp: {raw_timestamp}") from error
    comparable_now = now.astimezone().replace(tzinfo=None) if synced.tzinfo is None else now.astimezone(synced.tzinfo)
    return max(comparable_now - synced, timedelta())


def _describe_age(age: timedelta) -> str:
    if age.days >= 1:
        return f"{age.days} day{'s' if age.days != 1 else ''} ago"
    hours = int(age.total_seconds() // 3600)
    if hours >= 1:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    return "in the last hour"


def mail_store_path(home: Path) -> Path:
    return home / APPLE_MAIL_STORE_RELATIVE


def read_mail_store(home: Path) -> None:
    """List the Mail store. Raises if this process cannot read it.

    Full Disk Access at sync time belongs to the process that launches the
    server (the MCP client), not the terminal that built the index. Listing
    is the macOS TCC seam: exists() can lie when the grant is missing, and a
    successful empty listing is also not proof — denied access often returns
    no entries and no error.
    """
    store = mail_store_path(home)
    with os.scandir(store) as entries:
        first = next(entries, None)
    if first is None:
        raise OSError(f"{store} listed no files; Full Disk Access may be hiding the Mail store from this process")
    os.stat(first.path)


def _mail_store_result(home: Path) -> Result | None:
    store = mail_store_path(home)
    try:
        read_mail_store(home)
    except FileNotFoundError:
        return Result(
            "BROKEN",
            f"The serving process cannot see the Mail store at {store}, so a fresh-looking index can still be frozen",
            action=APPLE_MAIL_SERVING_FDA_FIX,
            feature_status="broken",
            user_message=(
                "Mail search's index looks current, but this process cannot read your Mail "
                "folder. The app that launches the Mail server needs Full Disk Access, not "
                "only the terminal that built the index. " + APPLE_MAIL_SERVING_FDA_FIX
            ),
        )
    except OSError as error:
        return Result(
            "BROKEN",
            f"The serving process cannot read the Mail store at {store}: {_one_line(error)}",
            action=APPLE_MAIL_SERVING_FDA_FIX,
            feature_status="broken",
            user_message=(
                "Mail search's index looks current, but this process cannot read your Mail "
                "folder. The app that launches the Mail server needs Full Disk Access, not "
                "only the terminal that built the index. " + APPLE_MAIL_SERVING_FDA_FIX
            ),
        )
    return None


def probe(context: Context) -> Result:
    """Prove the configured local FTS index can truthfully answer searches."""
    try:
        registration = _registration(context)
    except ValueError as error:
        detail = _one_line(error)
        return Result(
            "BROKEN",
            detail,
            action="Fix the malformed MCP JSON, then run /dex-doctor again.",
            feature_status="broken",
            user_message=f"Mail search configuration cannot be verified. {detail}",
        )
    if registration is None:
        return Result("OFF", "Apple Mail search is not connected, so it stays opt-in", feature_status="off")
    if not context.macos:
        return Result(
            "UNKNOWN",
            "An Apple Mail server is registered but its index can only be checked on macOS",
            feature_status="unknown",
        )
    if not context.cli_present:
        return Result(
            "BROKEN",
            "An Apple Mail server is registered but the apple-mail-mcp command is not installed, "
            "so mail search cannot work",
            action=f"Install the supported server with `{APPLE_MAIL_MCP_INSTALL}`, then run /apple-mail-setup.",
            feature_status="broken",
            user_message=(
                "Mail search is registered but the apple-mail-mcp command is missing. "
                f"Install the tested community release with `{APPLE_MAIL_MCP_INSTALL}`, "
                "then run /apple-mail-setup."
            ),
        )
    try:
        settings = _settings(context, registration)
    except ValueError as error:
        detail = _one_line(error)
        return Result(
            "BROKEN",
            detail,
            action="Fix ~/.apple-mail-mcp/config.toml or the Apple Mail MCP environment, then run /dex-doctor again.",
            feature_status="broken",
            user_message=detail,
        )
    index = settings.path
    try:
        index_stat = index.stat()
        with index.open("rb") as handle:
            handle.read(1)
    except FileNotFoundError:
        return Result(
            "BROKEN",
            f"Apple Mail search has no index, so every mail search returns nothing (expected {index})",
            action=APPLE_MAIL_INDEX_BUILD_FIX,
            feature_status="broken",
            user_message="Mail search has never been built, so it silently returns nothing. "
            + APPLE_MAIL_INDEX_BUILD_FIX,
        )
    except OSError as error:
        detail = _one_line(error)
        return Result(
            "BROKEN",
            f"The Apple Mail search index at {index} could not be read: {detail}",
            action=APPLE_MAIL_INDEX_BUILD_FIX,
            feature_status="broken",
            user_message=("Mail search's index exists but this process cannot read it. " + APPLE_MAIL_INDEX_BUILD_FIX),
        )
    if index_stat.st_size == 0:
        return Result(
            "BROKEN",
            f"The Apple Mail search index at {index} is empty, so every mail search returns nothing",
            action=APPLE_MAIL_INDEX_BUILD_FIX,
            feature_status="broken",
            user_message="Mail search's index is empty, so it returns nothing. " + APPLE_MAIL_INDEX_BUILD_FIX,
        )
    permissions = _permissions_result(index)
    if permissions:
        return permissions
    try:
        email_count, required_syncs = _index_state(index)
    except (OSError, sqlite3.DatabaseError, ValueError) as error:
        detail = _one_line(error)
        return Result(
            "BROKEN",
            f"The Apple Mail search index at {index} is not usable: {detail}",
            action=APPLE_MAIL_INDEX_REBUILD_FIX,
            feature_status="broken",
            user_message="Mail search's local index is not usable. " + APPLE_MAIL_INDEX_REBUILD_FIX,
        )
    permissions = _permissions_result(index)
    if permissions:
        return permissions
    if email_count == 0:
        return Result(
            "BROKEN",
            f"The Apple Mail search index at {index} has its schema but contains no messages",
            action=APPLE_MAIL_INDEX_REBUILD_FIX,
            feature_status="broken",
            user_message="Mail search's local index contains no messages. " + APPLE_MAIL_INDEX_REBUILD_FIX,
        )
    try:
        age = max(_sync_age(context.now, last_sync) for last_sync in required_syncs)
    except ValueError as error:
        detail = _one_line(error)
        return Result(
            "BROKEN",
            f"The Apple Mail search index at {index} is not usable: {detail}",
            action=APPLE_MAIL_INDEX_REBUILD_FIX,
            feature_status="broken",
            user_message="Mail search's local index is not usable. " + APPLE_MAIL_INDEX_REBUILD_FIX,
        )
    if age > settings.stale_after:
        allowed_hours = settings.stale_after.total_seconds() / 3600
        described_age = _describe_age(age)
        return Result(
            "BROKEN",
            f"The Apple Mail search index at {index} last synced {described_age}, beyond its configured {allowed_hours:g}-hour freshness limit",
            action=APPLE_MAIL_INDEX_BUILD_FIX,
            feature_status="broken",
            user_message=f"Mail search is running on an index last synced {described_age}, so recent mail may be invisible. "
            + APPLE_MAIL_INDEX_BUILD_FIX,
        )
    mail_store = _mail_store_result(context.home)
    if mail_store:
        return mail_store
    return Result(
        "OK",
        f"Apple Mail search is using {index} with {email_count} indexed message{'s' if email_count != 1 else ''}, last synced {_describe_age(age)}",
        feature_status="ok",
    )
