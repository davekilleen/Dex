import subprocess
import zipfile
from pathlib import Path

from core.utils.credential_scanner import scan_credentials


def _git(root: Path, *args: str):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_scanner_redacts_paths_values_and_reports_scopes(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "synthetic@example.invalid")
    _git(tmp_path, "config", "user.name", "Synthetic")
    secret = b"synthetic-secret-credential"
    (tmp_path / "tracked.txt").write_bytes(b"prefix " + secret)
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-qm", "fixture")
    (tmp_path / "untracked.txt").write_bytes(secret)
    archive = tmp_path / "selected.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("nested/private.txt", secret)
    report = scan_credentials(tmp_path, (secret,), (archive,))
    serialized = repr(report)
    assert len(report.findings) >= 4
    assert "synthetic-secret" not in serialized
    assert "tracked.txt" not in serialized
    assert "selected-archives" in report.inspected_scopes
    assert not report.uninspected_scopes


def test_unselected_archives_are_explicitly_uninspected(tmp_path):
    _git(tmp_path, "init", "-q")
    report = scan_credentials(tmp_path, (b"synthetic-value",))
    assert "selected-archives" in report.uninspected_scopes


def test_ignored_active_mcp_config_is_scanned_but_never_identified(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text(".mcp.json\n")
    secret = b"synthetic-active-residual"
    mcp = tmp_path / ".mcp.json"
    mcp.write_bytes(b'{"env":{"TOKEN":"' + secret + b'"}}')
    before = mcp.read_bytes()
    report = scan_credentials(tmp_path, (secret,))
    assert any(f.scope == "worktree" for f in report.findings)
    assert ".mcp.json" not in repr(report)
    assert mcp.read_bytes() == before
