"""Real macOS seams for the optional apple-mail-mcp runtime.

The portable health logic has deterministic Linux coverage.  These tests run
only on the repository's macOS CI runner and prove the pinned upstream CLI can
read a real FTS5 index and emits its actionable Full Disk Access failure.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="apple-mail-mcp runtime and Full Disk Access are macOS-only",
)


def _runtime_environment(home: Path, index: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "APPLE_MAIL_INDEX_PATH": str(index),
            "APPLE_MAIL_INDEX_STALENESS_HOURS": "24",
        }
    )
    return environment


def test_real_apple_mail_status_and_full_disk_access_denial(tmp_path):
    cli = shutil.which("apple-mail-mcp")
    assert cli is not None, "requirements-dev.txt must install the pinned Apple Mail runtime"

    home = tmp_path / "home"
    home.mkdir()
    index = home / ".apple-mail-mcp" / "index.db"
    environment = _runtime_environment(home, index)
    create = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from apple_mail_mcp.config import get_index_path; "
                "from apple_mail_mcp.index.schema import init_database; "
                "db=init_database(get_index_path()); "
                'db.execute("INSERT INTO emails '
                "(message_id,account,mailbox,subject,sender,content,date_received,emlx_path) "
                "VALUES (1,'Fixture','INBOX','Runtime proof','fixture@example.com',"
                "'searchable body','2026-08-13T10:00:00','fixture.emlx')\"); "
                'db.execute("INSERT INTO sync_state '
                "(account,mailbox,last_sync,message_count) "
                # Pinned upstream 0.4.3 writes/parses last_sync as naive local ISO.
                "VALUES ('Fixture','INBOX','2026-08-13T10:00:00',1)\"); "
                "db.commit(); db.close()"
            ),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert create.returncode == 0, create.stderr

    status = subprocess.run(
        [cli, "status"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert status.returncode == 0, status.stderr
    assert f"Location:     {index}" in status.stdout
    assert "Emails:       1" in status.stdout

    denied_home = tmp_path / "denied-home"
    denied_mail = denied_home / "Library" / "Mail" / "V10"
    denied_mail.mkdir(parents=True)
    denied_mail.chmod(0o000)
    try:
        denied = subprocess.run(
            [cli, "index"],
            env=_runtime_environment(
                denied_home,
                denied_home / ".apple-mail-mcp" / "index.db",
            ),
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        denied_mail.chmod(0o700)

    assert denied.returncode != 0
    assert "Full Disk Access" in denied.stderr
