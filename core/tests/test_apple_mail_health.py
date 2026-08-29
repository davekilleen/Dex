"""Behavior contract for the community Apple Mail full-text index adapter."""

import json
import os
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.utils import apple_mail_health

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


def _grant_serving_process_mail_store(home: Path) -> Path:
    store = home / "Library" / "Mail"
    store.mkdir(parents=True, exist_ok=True)
    (store / ".keep").write_text("readable")
    return store


@pytest.fixture
def context(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    _grant_serving_process_mail_store(home)
    return apple_mail_health.Context(
        home=home,
        vault_root=vault,
        now=NOW,
        user_config_path=home / ".claude.json",
        project_config_path=vault / ".mcp.json",
        environment=os.environ,
        macos=True,
        cli_present=True,
    )


def _register_apple_mail_user_scope(context, name="user-apple-mail", *, env=None):
    entry = {"command": "apple-mail-mcp", "args": ["serve"]}
    if env is not None:
        entry["env"] = env
    (context.home / ".claude.json").write_text(json.dumps({"mcpServers": {name: entry}}))


def _write_apple_mail_index(context, *, age_days=0.0, size=4096):
    index = context.home / ".apple-mail-mcp" / "index.db"
    if size == 0:
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_bytes(b"")
        index.chmod(0o600)
        return index
    last_sync = (context.now - timedelta(days=age_days)).isoformat()
    _write_real_apple_mail_index(index, last_sync=last_sync)
    return index


def _write_real_apple_mail_index(
    path,
    *,
    last_sync="2026-07-11T11:00:00+00:00",
    email_count=1,
    fts_searchable=True,
):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
        INSERT INTO schema_version VALUES (5);
        CREATE TABLE emails (
            rowid INTEGER PRIMARY KEY,
            message_id INTEGER NOT NULL,
            account TEXT NOT NULL,
            mailbox TEXT NOT NULL,
            subject TEXT,
            sender TEXT,
            content TEXT,
            date_received TEXT,
            emlx_path TEXT,
            attachment_count INTEGER DEFAULT 0,
            indexed_at TEXT DEFAULT (datetime('now'))
        );
        CREATE VIRTUAL TABLE emails_fts USING fts5(
            subject, sender, content, content='emails', content_rowid='rowid'
        );
        CREATE TRIGGER emails_ai AFTER INSERT ON emails BEGIN
            INSERT INTO emails_fts(rowid, subject, sender, content)
            VALUES (new.rowid, new.subject, new.sender, new.content);
        END;
        CREATE TRIGGER emails_ad AFTER DELETE ON emails BEGIN
            INSERT INTO emails_fts(emails_fts, rowid, subject, sender, content)
            VALUES ('delete', old.rowid, old.subject, old.sender, old.content);
        END;
        CREATE TRIGGER emails_au AFTER UPDATE ON emails BEGIN
            INSERT INTO emails_fts(emails_fts, rowid, subject, sender, content)
            VALUES ('delete', old.rowid, old.subject, old.sender, old.content);
            INSERT INTO emails_fts(rowid, subject, sender, content)
            VALUES (new.rowid, new.subject, new.sender, new.content);
        END;
        CREATE TABLE sync_state (
            account TEXT NOT NULL,
            mailbox TEXT NOT NULL,
            last_sync TEXT,
            message_count INTEGER DEFAULT 0,
            PRIMARY KEY(account, mailbox)
        );
        """
    )
    for rowid in range(1, email_count + 1):
        connection.execute(
            "INSERT INTO emails "
            "(rowid, message_id, account, mailbox, subject, sender, content) "
            "VALUES (?, ?, 'Fixture', 'INBOX', 'Fixture subject', "
            "'fixture@example.com', 'Fixture body')",
            (rowid, rowid),
        )
    connection.execute(
        "INSERT INTO sync_state VALUES ('Fixture', 'INBOX', ?, ?)",
        (last_sync, email_count),
    )
    if not fts_searchable:
        connection.execute("INSERT INTO emails_fts(emails_fts) VALUES ('delete-all')")
    connection.commit()
    connection.close()
    path.chmod(0o600)
    return path


def _add_indexed_mailbox(path, *, account, mailbox, last_sync):
    with sqlite3.connect(path) as connection:
        rowid = int(connection.execute("SELECT MAX(rowid) FROM emails").fetchone()[0]) + 1
        connection.execute(
            "INSERT INTO emails "
            "(rowid, message_id, account, mailbox, subject, sender, content) "
            "VALUES (?, ?, ?, ?, 'Second mailbox', 'fixture@example.com', 'Searchable body')",
            (rowid, rowid, account, mailbox),
        )
        connection.execute(
            "INSERT INTO sync_state (account, mailbox, last_sync, message_count) "
            "VALUES (?, ?, ?, 1)",
            (account, mailbox, last_sync),
        )


def test_apple_mail_search_is_off_when_no_server_is_registered(context):
    result = apple_mail_health.probe(context)

    assert result.verdict == "OFF"
    assert result.feature_status == "off"
    assert result.action is None


def test_apple_mail_search_detects_registration_at_either_scope(monkeypatch, context):
    context = replace(context, macos=False)
    _register_apple_mail_user_scope(context)
    assert apple_mail_health.probe(context).verdict == "UNKNOWN"

    (context.home / ".claude.json").unlink()
    assert apple_mail_health.probe(context).verdict == "OFF"

    (context.vault_root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"mail": {"command": "pipx", "args": ["run", "apple-mail-mcp"]}}})
    )
    assert apple_mail_health.probe(context).verdict == "UNKNOWN"


def test_apple_mail_search_is_unknown_off_macos(monkeypatch, context):
    _register_apple_mail_user_scope(context)
    context = replace(context, macos=False)

    result = apple_mail_health.probe(context)

    assert result.verdict == "UNKNOWN"
    assert result.feature_status == "unknown"


def test_apple_mail_search_is_broken_when_the_command_is_missing(monkeypatch, context):
    _register_apple_mail_user_scope(context)
    context = replace(context, cli_present=False)

    result = apple_mail_health.probe(context)

    assert result.verdict == "BROKEN"
    assert result.feature_status == "broken"
    assert "pipx install 'apple-mail-mcp==0.4.3'" in result.action


def test_apple_mail_search_is_broken_when_the_index_was_never_built(monkeypatch, context):
    """The silent failure from #446: list/read work, so search looks healthy while returning nothing."""
    _register_apple_mail_user_scope(context)

    result = apple_mail_health.probe(context)

    assert result.verdict == "BROKEN"
    assert result.feature_status == "broken"
    assert "apple-mail-mcp index" in result.action
    assert "Full Disk Access" in result.action
    assert "returns nothing" in result.user_message


def test_apple_mail_search_is_broken_when_the_index_is_empty(monkeypatch, context):
    _register_apple_mail_user_scope(context)
    _write_apple_mail_index(context, size=0)

    result = apple_mail_health.probe(context)

    assert result.verdict == "BROKEN"
    assert "empty" in result.detail


def test_apple_mail_search_is_broken_when_the_index_has_gone_stale(monkeypatch, context):
    """Startup sync silently no-ops without Full Disk Access, so a built index quietly stales."""
    _register_apple_mail_user_scope(context)
    _write_apple_mail_index(context, age_days=30)

    result = apple_mail_health.probe(context)

    assert result.verdict == "BROKEN"
    assert "30 days ago" in result.detail
    assert "apple-mail-mcp index" in result.action


def test_apple_mail_search_is_ok_with_a_fresh_index(monkeypatch, context):
    _register_apple_mail_user_scope(context)
    _write_apple_mail_index(context, age_days=1)

    result = apple_mail_health.probe(context)

    assert result.verdict == "OK"
    assert result.feature_status == "ok"
    assert result.action is None


def test_apple_mail_search_is_broken_when_the_index_cannot_be_read(monkeypatch, context):
    _register_apple_mail_user_scope(context)
    index = _write_apple_mail_index(context, age_days=1)
    original_stat = Path.stat

    def refuse_index_stat(self, *args, **kwargs):
        if Path(self) == index:
            raise PermissionError("Operation not permitted")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", refuse_index_stat)

    result = apple_mail_health.probe(context)

    assert result.verdict == "BROKEN"
    assert result.feature_status == "broken"
    assert "could not be read" in result.detail
    assert "Full Disk Access" in result.action
    assert "apple-mail-mcp index" in result.action


def test_apple_mail_search_freshness_alone_does_not_pass_when_mail_store_is_missing(
    monkeypatch,
    context,
):
    _register_apple_mail_user_scope(context)
    _write_apple_mail_index(context, age_days=0)
    store = apple_mail_health.mail_store_path(context.home)
    for child in store.iterdir():
        child.unlink()
    store.rmdir()

    result = apple_mail_health.probe(context)

    assert result.verdict == "UNKNOWN"
    assert result.feature_status == "unknown"
    assert "Mail store" in result.detail
    assert "could not be determined" in result.detail
    assert "Full Disk Access" in result.action
    assert "Dex, Claude, or Cursor" in result.action
    assert "not only the terminal" in result.action


def test_apple_mail_search_freshness_alone_does_not_pass_when_mail_store_lists_empty(
    monkeypatch,
    context,
):
    _register_apple_mail_user_scope(context)
    _write_apple_mail_index(context, age_days=0)
    store = apple_mail_health.mail_store_path(context.home)
    for child in store.iterdir():
        child.unlink()

    result = apple_mail_health.probe(context)

    assert result.verdict == "UNKNOWN"
    assert result.feature_status == "unknown"
    assert "listed no files" in result.detail
    assert "Full Disk Access" in result.action
    assert "not only the terminal" in result.action


def test_apple_mail_search_freshness_alone_does_not_pass_when_mail_store_is_unreadable(
    monkeypatch,
    context,
):
    _register_apple_mail_user_scope(context)
    _write_apple_mail_index(context, age_days=0)

    def refuse_mail_store(_home):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(apple_mail_health, "read_mail_store", refuse_mail_store)

    result = apple_mail_health.probe(context)

    assert result.verdict == "UNKNOWN"
    assert result.feature_status == "unknown"
    assert "cannot read the Mail store" in result.detail
    assert "Full Disk Access" in result.action
    assert "not only the terminal" in result.user_message


def test_apple_mail_setup_action_names_serving_process_full_disk_access():
    action = apple_mail_health.setup_action("index")

    assert "apple-mail-mcp index" in action
    assert "Full Disk Access" in action
    assert "Dex, Claude, or Cursor" in action
    assert "does not need this permission" not in action


def test_apple_mail_setup_action_closes_live_sessions_before_refresh():
    index_action = apple_mail_health.setup_action("index")
    rebuild_action = apple_mail_health.setup_action("rebuild")

    for action in (index_action, rebuild_action):
        assert "Quit every Dex, Claude, or Cursor session that is using Mail search" in action
        assert "holds the search-index lock" in action
        assert "apple-mail-mcp" in action


def test_apple_mail_search_uses_custom_path_and_real_sqlite_state(monkeypatch, context):
    _register_apple_mail_user_scope(context)
    custom_index = context.home / "private-mail" / "search.sqlite"
    _write_real_apple_mail_index(custom_index)
    config_dir = context.home / ".apple-mail-mcp"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        f'config_version = 1\n[index]\npath = "{custom_index}"\nstaleness_hours = 24\n'
    )

    result = apple_mail_health.probe(context)

    assert result.verdict == "OK"
    assert str(custom_index) in result.detail
    assert "1 indexed message" in result.detail


def test_apple_mail_search_mcp_environment_overrides_toml_settings(monkeypatch, context):
    custom_index = context.home / "client-specific" / "index.db"
    _register_apple_mail_user_scope(
        context,
        env={
            "APPLE_MAIL_INDEX_PATH": str(custom_index),
            "APPLE_MAIL_INDEX_STALENESS_HOURS": "48",
        },
    )
    _write_real_apple_mail_index(
        custom_index,
        last_sync="2026-07-10T11:00:00+00:00",
    )
    config_dir = context.home / ".apple-mail-mcp"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        'config_version = 1\n[index]\npath = "/wrong/index.db"\nstaleness_hours = 1\n'
    )

    result = apple_mail_health.probe(context)

    assert result.verdict == "OK"
    assert str(custom_index) in result.detail


def test_apple_mail_search_reports_invalid_config_as_broken(monkeypatch, context):
    _register_apple_mail_user_scope(context)
    config_dir = context.home / ".apple-mail-mcp"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("config_version = [not valid TOML")

    result = apple_mail_health.probe(context)

    assert result.verdict == "BROKEN"
    assert "config" in result.detail.lower()
    assert "config.toml" in result.action


def test_apple_mail_search_reports_semantically_invalid_config_as_broken(
    monkeypatch,
    context,
):
    _register_apple_mail_user_scope(context)
    config_dir = context.home / ".apple-mail-mcp"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("[index]\nstaleness_hours = 24\n")

    result = apple_mail_health.probe(context)

    assert result.verdict == "BROKEN"
    assert "config_version = 1" in result.detail
    assert "config.toml" in result.action


def test_apple_mail_search_reports_empty_existing_config_as_broken(
    monkeypatch,
    context,
):
    _register_apple_mail_user_scope(context)
    config_dir = context.home / ".apple-mail-mcp"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("")

    result = apple_mail_health.probe(context)

    assert result.verdict == "BROKEN"
    assert "config_version = 1" in result.detail


def test_apple_mail_search_reports_malformed_registration_as_broken(
    monkeypatch,
    context,
):
    (context.home / ".claude.json").write_text('{"mcpServers": {"apple-mail": ')

    result = apple_mail_health.probe(context)

    assert result.verdict == "BROKEN"
    assert result.feature_status == "broken"
    assert "could not be read" in result.detail
    assert "MCP JSON" in result.action


def test_apple_mail_search_reports_null_registration_container_as_broken(
    monkeypatch,
    context,
):
    (context.home / ".claude.json").write_text('{"mcpServers": null}')

    result = apple_mail_health.probe(context)

    assert result.verdict == "BROKEN"
    assert result.feature_status == "broken"
    assert "must contain an mcpServers object" in result.detail
    assert "MCP JSON" in result.action


@pytest.mark.parametrize(
    "broken_shape",
    ["fake", "missing-schema", "empty-data", "empty-fts"],
)
def test_apple_mail_search_rejects_files_that_cannot_answer_searches(
    monkeypatch,
    context,
    broken_shape,
):
    _register_apple_mail_user_scope(context)
    index = context.home / ".apple-mail-mcp" / "index.db"
    index.parent.mkdir(parents=True, exist_ok=True)
    if broken_shape == "fake":
        index.write_bytes(b"not a sqlite database")
    elif broken_shape == "missing-schema":
        with sqlite3.connect(index) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
    elif broken_shape == "empty-data":
        _write_real_apple_mail_index(index, email_count=0)
    else:
        _write_real_apple_mail_index(index, fts_searchable=False)
    index.chmod(0o600)

    result = apple_mail_health.probe(context)

    assert result.verdict == "BROKEN"
    assert result.feature_status == "broken"
    assert "rebuild" in result.action


def test_apple_mail_search_process_environment_overrides_registration_and_toml(
    monkeypatch,
    context,
):
    registered_index = context.home / "registered" / "index.db"
    process_index = context.home / "runtime" / "index.db"
    _register_apple_mail_user_scope(
        context,
        env={
            "APPLE_MAIL_INDEX_PATH": str(registered_index),
            "APPLE_MAIL_INDEX_STALENESS_HOURS": "1",
        },
    )
    monkeypatch.setenv("APPLE_MAIL_INDEX_PATH", str(process_index))
    monkeypatch.setenv("APPLE_MAIL_INDEX_STALENESS_HOURS", "48")
    _write_real_apple_mail_index(
        process_index,
        last_sync="2026-07-10T11:00:00+00:00",
    )
    config_dir = context.home / ".apple-mail-mcp"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        f'config_version = 1\n[index]\npath = "{context.home / "toml" / "index.db"}"\nstaleness_hours = 1\n'
    )

    result = apple_mail_health.probe(context)

    assert result.verdict == "OK"
    assert str(process_index) in result.detail


def test_apple_mail_search_resolves_relative_path_from_server_vault(
    monkeypatch,
    context,
):
    _register_apple_mail_user_scope(
        context,
        env={"APPLE_MAIL_INDEX_PATH": "runtime/mail-index.db"},
    )
    relative_index = context.vault_root / "runtime" / "mail-index.db"
    _write_real_apple_mail_index(relative_index)

    result = apple_mail_health.probe(context)

    assert result.verdict == "OK"
    assert str(relative_index) in result.detail


def test_apple_mail_search_default_freshness_is_24_hours(monkeypatch, context):
    _register_apple_mail_user_scope(context)
    index = context.home / ".apple-mail-mcp" / "index.db"
    _write_real_apple_mail_index(
        index,
        last_sync=(context.now - timedelta(hours=25)).isoformat(),
    )

    result = apple_mail_health.probe(context)

    assert result.verdict == "BROKEN"
    assert "configured 24-hour freshness limit" in result.detail


def test_apple_mail_search_uses_configured_sync_freshness_not_file_mtime(
    monkeypatch,
    context,
):
    _register_apple_mail_user_scope(context)
    index = _write_real_apple_mail_index(
        context.home / ".apple-mail-mcp" / "index.db",
        last_sync="2026-07-10T11:00:00+00:00",
    )
    os.utime(index, (context.now.timestamp(), context.now.timestamp()))
    (index.parent / "config.toml").write_text("config_version = 1\n[index]\nstaleness_hours = 24\n")

    stale = apple_mail_health.probe(context)
    assert stale.verdict == "BROKEN"
    assert "configured 24-hour freshness limit" in stale.detail

    (index.parent / "config.toml").write_text("config_version = 1\n[index]\nstaleness_hours = 48\n")
    fresh_by_policy = apple_mail_health.probe(context)
    assert fresh_by_policy.verdict == "OK"


@pytest.mark.parametrize(
    ("second_sync", "expected_detail"),
    [
        pytest.param(
            (NOW - timedelta(hours=48)).isoformat(),
            "configured 24-hour freshness limit",
            id="mixed-fresh-and-stale",
        ),
        pytest.param(None, "has no successful sync", id="mixed-fresh-and-missing"),
    ],
)
def test_apple_mail_search_checks_every_indexed_mailbox_sync(
    context,
    second_sync,
    expected_detail,
):
    _register_apple_mail_user_scope(context)
    index = _write_real_apple_mail_index(
        context.home / ".apple-mail-mcp" / "index.db",
        last_sync=(NOW - timedelta(hours=1)).isoformat(),
    )
    _add_indexed_mailbox(
        index,
        account="Second",
        mailbox="Archive",
        last_sync=second_sync,
    )

    result = apple_mail_health.probe(context)

    assert result.verdict == "BROKEN"
    assert expected_detail in result.detail


@pytest.mark.parametrize(
    "last_sync",
    [
        pytest.param("2026-07-11T11:00:00", id="upstream-naive-local-iso"),
        pytest.param("2026-07-11T12:00:00+01:00", id="offset-aware-iso"),
    ],
)
def test_apple_mail_search_accepts_upstream_and_offset_sync_timestamps(
    monkeypatch,
    context,
    last_sync,
):
    _register_apple_mail_user_scope(context)
    _write_real_apple_mail_index(
        context.home / ".apple-mail-mcp" / "index.db",
        last_sync=last_sync,
    )

    result = apple_mail_health.probe(context)

    assert result.verdict == "OK"
    assert "last synced 1 hour ago" in result.detail


@pytest.mark.parametrize(
    ("sidecar", "mode"),
    [("", 0o644), ("-wal", 0o644), ("-shm", 0o644), ("", 0o700)],
)
def test_apple_mail_search_rejects_non_private_index_files(
    monkeypatch,
    context,
    sidecar,
    mode,
):
    _register_apple_mail_user_scope(context)
    index = _write_real_apple_mail_index(context.home / ".apple-mail-mcp" / "index.db")
    exposed = Path(f"{index}{sidecar}")
    if sidecar:
        exposed.write_bytes(b"fixture sidecar")
    exposed.chmod(mode)

    result = apple_mail_health.probe(context)

    assert result.verdict == "BROKEN"
    assert "chmod 600" in result.action
    assert str(exposed) in result.detail
    assert "subjects, senders, bodies, file paths, and attachment metadata" in result.user_message
