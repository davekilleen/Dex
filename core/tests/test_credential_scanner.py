import stat
import subprocess
import zipfile
from pathlib import Path

from core.utils.credential_scanner import scan_credentials


def _git(root: Path, *args: str):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_scanner_redacts_paths_values_and_reports_scopes(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "tests@example.com")
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
    assert report.uninspected_scopes == ("primary-object-db",)


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


def test_reflog_only_secret_and_packed_refs_are_in_approved_reachable_scope(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "tests@example.com")
    _git(tmp_path, "config", "user.name", "Synthetic")
    (tmp_path / "base.txt").write_text("base\n")
    _git(tmp_path, "add", "base.txt")
    _git(tmp_path, "commit", "-qm", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True).stdout.strip()
    secret = b"reflog-only-secret"
    (tmp_path / "secret.txt").write_bytes(secret)
    _git(tmp_path, "add", "secret.txt")
    _git(tmp_path, "commit", "-qm", "secret")
    _git(tmp_path, "tag", "packed-tag")
    _git(tmp_path, "pack-refs", "--all")
    _git(tmp_path, "reset", "--hard", base.decode())
    report = scan_credentials(tmp_path, (secret,))
    assert any(finding.scope == "reachable-refs" for finding in report.findings)
    assert "reachable-refs" in report.inspected_scopes
    assert "git-common-dir" in report.inspected_scopes


def test_oversized_archive_and_symlink_make_scopes_uninspected(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    target = tmp_path / "target.txt"
    target.write_text("safe")
    (tmp_path / "linked.txt").symlink_to(target)
    archive = tmp_path / "oversized.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("large.bin", b"oversized-secret" + b"x" * 32)
    monkeypatch.setattr("core.utils.credential_scanner.MAX_ARCHIVE_MEMBER", 16)
    report = scan_credentials(tmp_path, (b"oversized-secret",), (archive,))
    assert "worktree" in report.uninspected_scopes
    assert "selected-archives" in report.uninspected_scopes
    assert any(reason.startswith("selected-archives:") for reason in report.uninspected_reasons)


def test_object_bound_prevents_false_clean_scope(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "tests@example.com")
    _git(tmp_path, "config", "user.name", "Synthetic")
    (tmp_path / "one").write_text("one")
    _git(tmp_path, "add", "one")
    _git(tmp_path, "commit", "-qm", "one")
    monkeypatch.setattr("core.utils.credential_scanner.MAX_OBJECTS", 0)
    report = scan_credentials(tmp_path, (b"never",))
    assert "reachable-refs" in report.uninspected_scopes
    assert "primary-object-db" in report.uninspected_scopes


def test_zip_symlink_makes_archive_scope_uninspected(tmp_path):
    _git(tmp_path, "init", "-q")
    archive = tmp_path / "selected.zip"
    info = zipfile.ZipInfo("credential-link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(info, "credential.txt")

    report = scan_credentials(tmp_path, (b"synthetic-secret",), (archive,))

    assert "selected-archives" in report.uninspected_scopes
    assert "selected-archives:archive-input-member-or-bound" in report.uninspected_reasons


def test_git_metadata_file_bound_makes_git_scopes_uninspected(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    logs = tmp_path / common / "logs" / "extra"
    logs.mkdir(parents=True)
    (logs / "one").write_text("metadata")
    monkeypatch.setattr("core.utils.credential_scanner.MAX_GIT_METADATA_FILES", 0)

    report = scan_credentials(tmp_path, (b"synthetic-secret",))

    assert "git-common-dir" in report.uninspected_scopes
    assert "git-common-dir:git-metadata-object-or-bound" in report.uninspected_reasons


def test_unreachable_loose_blob_keeps_primary_object_database_uninspected(tmp_path):
    _git(tmp_path, "init", "-q")
    secret = b"unreachable-loose-secret"
    subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=tmp_path, input=secret, check=True, capture_output=True)

    report = scan_credentials(tmp_path, (secret,))

    assert not report.findings
    assert "primary-object-db" in report.uninspected_scopes
    assert "primary-object-db:unreachable-objects-not-inspected" in report.uninspected_reasons


def test_reachable_blob_is_found_while_primary_object_database_remains_uninspected(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "tests@example.com")
    _git(tmp_path, "config", "user.name", "Synthetic")
    secret = b"reachable-secret"
    (tmp_path / "secret.txt").write_bytes(secret)
    _git(tmp_path, "add", "secret.txt")
    _git(tmp_path, "commit", "-qm", "reachable")

    report = scan_credentials(tmp_path, (secret,))

    assert any(finding.scope == "reachable-refs" for finding in report.findings)
    assert "reachable-refs" in report.inspected_scopes
    assert "primary-object-db" in report.uninspected_scopes


def test_git_common_config_is_scanned_under_bounded_redacted_scope(tmp_path):
    _git(tmp_path, "init", "-q")
    secret = b"synthetic-common-config-secret"
    config = tmp_path / ".git/config"
    config.write_bytes(config.read_bytes() + b"\n# " + secret + b"\n")

    report = scan_credentials(tmp_path, (secret,))

    assert any(finding.scope == "git-common-dir" for finding in report.findings)
    assert "git-common-dir" in report.inspected_scopes
    assert secret.decode() not in repr(report)


def test_tag_and_stash_findings_have_exact_attribution_with_overlap(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "tests@example.com")
    _git(tmp_path, "config", "user.name", "Synthetic")
    (tmp_path / "base.txt").write_text("base\n")
    _git(tmp_path, "add", "base.txt")
    _git(tmp_path, "commit", "-qm", "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    secret = b"synthetic-tag-stash-secret"
    (tmp_path / "tag-only.txt").write_bytes(secret)
    _git(tmp_path, "add", "tag-only.txt")
    _git(tmp_path, "commit", "-qm", "tag")
    _git(tmp_path, "tag", "synthetic-tag")
    _git(tmp_path, "reset", "--hard", base)
    (tmp_path / "base.txt").write_bytes(secret)
    _git(tmp_path, "stash", "push", "-qm", "synthetic stash")

    report = scan_credentials(tmp_path, (secret,))
    scopes = {finding.scope for finding in report.findings}

    assert {"tags", "stashes"} <= scopes
    assert {"tags", "stashes", "reachable-refs"} <= set(report.inspected_scopes)


def test_overlapping_object_scopes_share_one_distinct_byte_budget(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "tests@example.com")
    _git(tmp_path, "config", "user.name", "Synthetic")
    base = b"base\n"
    secret = b"shared-object-secret"
    (tmp_path / "value.txt").write_bytes(base)
    _git(tmp_path, "add", "value.txt")
    _git(tmp_path, "commit", "-qm", "base")
    (tmp_path / "value.txt").write_bytes(secret)
    _git(tmp_path, "add", "value.txt")
    _git(tmp_path, "commit", "-qm", "shared")
    _git(tmp_path, "tag", "shared-tag")
    monkeypatch.setattr("core.utils.credential_scanner.MAX_OBJECT_BYTES", len(base) + len(secret))

    report = scan_credentials(tmp_path, (secret,))

    assert {"reachable-refs", "tags", "stashes"} <= set(report.inspected_scopes)
    assert {finding.scope for finding in report.findings} >= {"reachable-refs", "tags"}


def test_replace_refs_make_object_attribution_explicitly_unknown(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "tests@example.com")
    _git(tmp_path, "config", "user.name", "Synthetic")
    (tmp_path / "one").write_text("one")
    _git(tmp_path, "add", "one")
    _git(tmp_path, "commit", "-qm", "one")
    original = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    (tmp_path / "two").write_text("two")
    _git(tmp_path, "add", "two")
    _git(tmp_path, "commit", "-qm", "two")
    replacement = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    _git(tmp_path, "reset", "--hard", original)
    _git(tmp_path, "replace", original, replacement)

    report = scan_credentials(tmp_path, (b"never-present",))

    assert {"reachable-refs", "tags", "stashes"} <= set(report.uninspected_scopes)
    assert "reachable-refs:replace-ref-topology-unsupported" in report.uninspected_reasons
