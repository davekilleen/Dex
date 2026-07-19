import hashlib
import json
import os
import stat
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.utils.history_hygiene import (
    HistoryPreview,
    apply_history_cleanup,
    delete_retention_candidates,
    prepare_history_cleanup,
    preview_retention,
    rewind_history_cleanup,
)

SECRET = b"synthetic-secret-history-value"


def _git(root: Path, *args: str, input_data: bytes | None = None) -> str:
    return (
        subprocess.run(["git", *args], cwd=root, input=input_data, check=True, capture_output=True)
        .stdout.decode()
        .strip()
    )


def _repo(root: Path) -> str:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "synthetic@example.invalid")
    _git(root, "config", "user.name", "Synthetic")
    (root / "leak.txt").write_bytes(b"before " + SECRET + b" after\n")
    _git(root, "add", "leak.txt")
    _git(root, "commit", "-qm", "fixture")
    return _git(root, "symbolic-ref", "HEAD")


def _tool(path: Path, *, fail: bool = False, mutate_remote: bool = False) -> Path:
    body = f"""#!/usr/bin/env python3
import pathlib, subprocess, sys
if '--version' in sys.argv:
    print('2.47.0')
    raise SystemExit(0)
args = sys.argv[1:]
replace = pathlib.Path(args[args.index('--replace-text') + 1]).read_bytes()
old, replacement = replace.split(b'==>', 1)
needle = old.removeprefix(b'literal:')
replacement = replacement.rstrip(b'\\n')
refs = args[args.index('--refs') + 1:]
def git(*parts, data=None):
    return subprocess.run(['git', *parts], input=data, check=True, capture_output=True).stdout.strip()
for ref in refs:
    content = git('show', ref + ':leak.txt').replace(needle, replacement)
    blob = git('hash-object', '-w', '--stdin', data=content).decode()
    mode = git('ls-tree', ref, 'leak.txt').decode().split()[0]
    tree = git('mktree', data=f'{{mode}} blob {{blob}}\\tleak.txt\\n'.encode()).decode()
    commit = git('commit-tree', tree, data=b'privacy rewrite\\n').decode()
    git('update-ref', ref, commit, git('rev-parse', ref).decode())
if {mutate_remote!r}:
    subprocess.run(['git', 'remote', 'remove', 'origin'], check=True)
if {fail!r}:
    raise SystemExit(9)
"""
    path.write_text(body)
    path.chmod(0o755)
    return path


def _prepare(root: Path, tool: Path, ref: str, **kwargs) -> HistoryPreview:
    return prepare_history_cleanup(
        root,
        security_state="remediated",
        explicit_choice=True,
        selected_refs=(ref,),
        credential_needles=(SECRET,),
        successful_release_activations=3,
        no_external_backup_acknowledged=True,
        filter_repo=tool,
        **kwargs,
    )


def test_absent_or_unsupported_tool_is_optional_guidance_without_writes(tmp_path):
    ref = _repo(tmp_path)
    absent = prepare_history_cleanup(
        tmp_path,
        security_state="remediated",
        explicit_choice=True,
        selected_refs=(ref,),
        credential_needles=(SECRET,),
        successful_release_activations=0,
        no_external_backup_acknowledged=True,
        filter_repo=tmp_path / "absent",
    )
    assert absent.state == "optional-tool-unavailable"
    assert "Security remains fixed" in absent.guidance
    assert not (tmp_path / "System/.dex").exists()
    unsupported = tmp_path / "unsupported"
    unsupported.write_text("#!/bin/sh\necho 1.0.0\n")
    unsupported.chmod(0o755)
    assert _prepare(tmp_path, unsupported, ref).state == "optional-tool-unavailable"
    symlink = tmp_path / "symlinked-tool"
    symlink.symlink_to(_tool(tmp_path / "real-tool"))
    assert _prepare(tmp_path, symlink, ref).state == "optional-tool-unavailable"


def test_preparation_requires_remediation_choice_and_backup_posture(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    with pytest.raises(PermissionError):
        prepare_history_cleanup(
            tmp_path,
            security_state="rotation-pending",
            explicit_choice=True,
            selected_refs=(ref,),
            credential_needles=(SECRET,),
            successful_release_activations=0,
            no_external_backup_acknowledged=True,
            filter_repo=tool,
        )
    with pytest.raises(ValueError, match="external-backup"):
        prepare_history_cleanup(
            tmp_path,
            security_state="remediated",
            explicit_choice=True,
            selected_refs=(ref,),
            credential_needles=(SECRET,),
            successful_release_activations=0,
            filter_repo=tool,
        )
    with pytest.raises(ValueError, match="SHA-256"):
        prepare_history_cleanup(
            tmp_path,
            security_state="remediated",
            explicit_choice=True,
            selected_refs=(ref,),
            credential_needles=(SECRET,),
            successful_release_activations=0,
            external_backup_evidence="not-verified-evidence",
            filter_repo=tool,
        )


def test_preparation_requires_exact_unique_local_ref_scopes(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    with pytest.raises(ValueError, match="unique selected refs"):
        prepare_history_cleanup(
            tmp_path,
            security_state="remediated",
            explicit_choice=True,
            selected_refs=(ref, ref),
            credential_needles=(SECRET,),
            successful_release_activations=0,
            no_external_backup_acknowledged=True,
            filter_repo=tool,
        )
    with pytest.raises(ValueError, match="unsupported selected ref"):
        prepare_history_cleanup(
            tmp_path,
            security_state="remediated",
            explicit_choice=True,
            selected_refs=("refs/remotes/origin/main",),
            credential_needles=(SECRET,),
            successful_release_activations=0,
            no_external_backup_acknowledged=True,
            filter_repo=tool,
        )
    with pytest.raises(ValueError, match="must be unique"):
        prepare_history_cleanup(
            tmp_path,
            security_state="remediated",
            explicit_choice=True,
            selected_refs=(ref,),
            credential_needles=(SECRET, SECRET),
            successful_release_activations=0,
            no_external_backup_acknowledged=True,
            filter_repo=tool,
        )


def test_prepare_creates_verified_restrictive_bundle_and_manifest(tmp_path):
    ref = _repo(tmp_path)
    before = _git(tmp_path, "rev-parse", ref)
    preview = _prepare(tmp_path, _tool(tmp_path / "git-filter-repo"), ref)
    transaction = tmp_path / "System/.dex/adoption/history-backups" / preview.transaction_id
    manifest = json.loads((transaction / "manifest.json").read_text())
    assert preview.state == "prepared"
    assert stat.S_IMODE(transaction.stat().st_mode) == 0o700
    assert stat.S_IMODE((transaction / "manifest.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((transaction / "history.bundle").stat().st_mode) == 0o600
    assert stat.S_IMODE((transaction / "objects.json").stat().st_mode) == 0o600
    assert manifest["selected_refs"] == {ref: before}
    assert manifest["bundle"]["verified"] is True
    assert manifest["before_object_evidence"]["sha256"]
    assert manifest["minimum_successful_release_activations_for_deletion"] == 5
    assert _git(tmp_path, "rev-parse", ref) == before


def test_preview_consent_manifest_bundle_and_ref_tamper_fail_closed(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    preview = _prepare(tmp_path, tool, ref)
    with pytest.raises(PermissionError):
        apply_history_cleanup(tmp_path, preview, typed_consent="yes", credential_needles=(SECRET,), filter_repo=tool)
    transaction = tmp_path / "System/.dex/adoption/history-backups" / preview.transaction_id
    manifest_path = transaction / "manifest.json"
    manifest_path.write_bytes(manifest_path.read_bytes().replace(b'"phase":"prepared"', b'"phase":"changed"'))
    with pytest.raises(ValueError, match="manifest changed"):
        apply_history_cleanup(
            tmp_path,
            preview,
            typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
            credential_needles=(SECRET,),
            filter_repo=tool,
        )


def test_selected_ref_mismatch_after_preview_is_refused(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    preview = _prepare(tmp_path, tool, ref)
    (tmp_path / "later.txt").write_text("later\n")
    _git(tmp_path, "add", "later.txt")
    _git(tmp_path, "commit", "-qm", "later")
    with pytest.raises(RuntimeError, match="refs changed"):
        apply_history_cleanup(
            tmp_path,
            preview,
            typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
            credential_needles=(SECRET,),
            filter_repo=tool,
        )


def test_tool_identity_mismatch_after_preview_is_refused(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    preview = _prepare(tmp_path, tool, ref)
    tool.write_text(tool.read_text() + "\n# changed after preview\n")
    with pytest.raises(RuntimeError, match="identity changed"):
        apply_history_cleanup(
            tmp_path,
            preview,
            typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
            credential_needles=(SECRET,),
            filter_repo=tool,
        )


def test_ambiguous_object_topology_refuses_preparation(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    alternates = tmp_path / ".git/objects/info/alternates"
    alternates.parent.mkdir(exist_ok=True)
    alternates.write_text(str(tmp_path / "other-objects") + "\n")
    with pytest.raises(RuntimeError, match="ambiguous Git object topology"):
        _prepare(tmp_path, tool, ref)


@pytest.mark.parametrize("mutation", ["corrupt", "mode"])
def test_bundle_corruption_and_permissions_are_refused(tmp_path, mutation):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    preview = _prepare(tmp_path, tool, ref)
    bundle = tmp_path / "System/.dex/adoption/history-backups" / preview.transaction_id / "history.bundle"
    if mutation == "corrupt":
        bundle.write_bytes(bundle.read_bytes() + b"corrupt")
    else:
        bundle.chmod(0o644)
    with pytest.raises(OSError, match="bundle identity"):
        apply_history_cleanup(
            tmp_path,
            preview,
            typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
            credential_needles=(SECRET,),
            filter_repo=tool,
        )


@pytest.mark.parametrize("mutation", ["corrupt", "mode"])
def test_object_evidence_corruption_and_permissions_are_refused(tmp_path, mutation):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    preview = _prepare(tmp_path, tool, ref)
    evidence = tmp_path / "System/.dex/adoption/history-backups" / preview.transaction_id / "objects.json"
    if mutation == "corrupt":
        evidence.write_bytes(evidence.read_bytes() + b"corrupt")
    else:
        evidence.chmod(0o644)
    with pytest.raises(OSError, match="object evidence identity"):
        apply_history_cleanup(
            tmp_path,
            preview,
            typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
            credential_needles=(SECRET,),
            filter_repo=tool,
        )


def test_git_bundle_verify_failure_is_refused_even_when_manifest_identity_matches(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    preview = _prepare(tmp_path, tool, ref)
    transaction = tmp_path / "System/.dex/adoption/history-backups" / preview.transaction_id
    bundle = transaction / "history.bundle"
    bundle.write_bytes(bundle.read_bytes().replace(b"# v2 git bundle", b"# xx git bundle", 1))
    manifest_path = transaction / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["bundle"]["size"] = bundle.stat().st_size
    manifest["bundle"]["sha256"] = hashlib.sha256(bundle.read_bytes()).hexdigest()
    manifest.pop("preview_sha256")
    preview_sha = hashlib.sha256(
        (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    manifest["preview_sha256"] = preview_sha
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(RuntimeError, match="Git operation failed"):
        apply_history_cleanup(
            tmp_path,
            replace(preview, preview_sha256=preview_sha),
            typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
            credential_needles=(SECRET,),
            filter_repo=tool,
        )


def test_verified_space_and_shared_cap_refuse_preparation(tmp_path, monkeypatch):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    usage = os.statvfs(tmp_path)
    disk = shutil_disk = type("Disk", (), {"total": usage.f_blocks, "used": 0, "free": 0})()
    monkeypatch.setattr("core.utils.history_hygiene.shutil.disk_usage", lambda _: disk)
    with pytest.raises(OSError, match="space"):
        _prepare(tmp_path, tool, ref)


def test_shared_recovery_cap_refuses_preparation(tmp_path, monkeypatch):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    monkeypatch.setattr("core.utils.history_hygiene._used_recovery_bytes", lambda _: 10 * 1024 * 1024 * 1024)
    with pytest.raises(OSError, match="space"):
        _prepare(tmp_path, tool, ref)


def test_cleanup_is_local_preserves_remotes_rescans_and_rewinds(tmp_path, monkeypatch):
    ref = _repo(tmp_path)
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare", "-q")
    _git(tmp_path, "remote", "add", "origin", str(remote))
    remote_before = (tmp_path / ".git/config").read_bytes()
    before = _git(tmp_path, "rev-parse", ref)
    tool = _tool(tmp_path / "git-filter-repo", mutate_remote=True)
    preview = _prepare(tmp_path, tool, ref)
    real_run = subprocess.run

    def no_push(command, **kwargs):
        assert "fetch" not in command and "push" not in command and "force-push" not in command
        return real_run(command, **kwargs)

    monkeypatch.setattr("core.utils.history_hygiene.subprocess.run", no_push)
    outcome = apply_history_cleanup(
        tmp_path,
        preview,
        typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
        credential_needles=(SECRET,),
        filter_repo=tool,
    )
    assert outcome.state == "history-clean"
    assert _git(tmp_path, "rev-parse", ref) != before
    assert SECRET not in _git(tmp_path, "show", f"{ref}:leak.txt").encode()
    assert (tmp_path / ".git/config").read_bytes() == remote_before
    assert rewind_history_cleanup(tmp_path, preview.transaction_id).state == "rewound"
    assert _git(tmp_path, "rev-parse", ref) == before
    assert SECRET in _git(tmp_path, "show", f"{ref}:leak.txt").encode()


def test_cleanup_interruption_preserves_verified_bundle_and_manual_guidance(tmp_path):
    ref = _repo(tmp_path)
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare", "-q")
    _git(tmp_path, "remote", "add", "origin", str(remote))
    config_before = (tmp_path / ".git/config").read_bytes()
    tool = _tool(tmp_path / "git-filter-repo", fail=True, mutate_remote=True)
    preview = _prepare(tmp_path, tool, ref)
    outcome = apply_history_cleanup(
        tmp_path,
        preview,
        typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
        credential_needles=(SECRET,),
        filter_repo=tool,
    )
    assert outcome.state == "recovery-required"
    assert "Do not push" in outcome.guidance
    assert "Provider rotation is not reversed" in outcome.guidance
    assert (tmp_path / ".git/config").read_bytes() == config_before
    bundle = tmp_path / "System/.dex/adoption/history-backups" / preview.transaction_id / "history.bundle"
    assert bundle.exists()
    assert json.loads((bundle.parent / "manifest.json").read_text())["phase"] == "recovery-required"
    assert rewind_history_cleanup(tmp_path, preview.transaction_id).state == "rewound"


def test_rewind_ref_mismatch_fails_closed_with_verified_bundle(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    preview = _prepare(tmp_path, tool, ref)
    outcome = apply_history_cleanup(
        tmp_path,
        preview,
        typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
        credential_needles=(SECRET,),
        filter_repo=tool,
    )
    assert outcome.state == "history-clean"
    (tmp_path / "later.txt").write_text("later\n")
    _git(tmp_path, "add", "later.txt")
    _git(tmp_path, "commit", "-qm", "later")
    rewind = rewind_history_cleanup(tmp_path, preview.transaction_id)
    assert rewind.state == "recovery-required"
    assert "recover from the verified history.bundle manually" in rewind.guidance


@pytest.mark.parametrize("scan_state", ["history-cleanup-pending", "history-scope-unknown"])
def test_rescan_pending_and_unknown_are_honest(tmp_path, monkeypatch, scan_state):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    preview = _prepare(tmp_path, tool, ref)
    monkeypatch.setattr("core.utils.history_hygiene._scan_selected_history", lambda *_: scan_state)
    outcome = apply_history_cleanup(
        tmp_path,
        preview,
        typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
        credential_needles=(SECRET,),
        filter_repo=tool,
    )
    assert outcome.state == scan_state
    assert outcome.uninspected_scopes == (("selected-refs",) if scan_state == "history-scope-unknown" else ())


def test_retention_requires_age_releases_exact_set_and_protects_final_bundle(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    old = datetime(2025, 1, 1, tzinfo=UTC)
    first = _prepare(tmp_path, tool, ref, now=lambda: old)
    second = _prepare(tmp_path, tool, ref, now=lambda: old + timedelta(days=1))
    preview = preview_retention(tmp_path, now=old + timedelta(days=100), successful_release_activations=5)
    assert preview.candidate_ids == (first.transaction_id,)
    assert preview.protected_final_id == second.transaction_id
    assert preview.candidate_bytes > 0
    with pytest.raises(PermissionError, match="exact-set"):
        delete_retention_candidates(
            tmp_path,
            preview,
            acknowledged_ids=(second.transaction_id,),
            exact_set_sha256=preview.exact_set_sha256,
        )
    assert delete_retention_candidates(
        tmp_path,
        preview,
        acknowledged_ids=preview.candidate_ids,
        exact_set_sha256=preview.exact_set_sha256,
    ) == (first.transaction_id,)
    assert not (tmp_path / "System/.dex/adoption/history-backups" / first.transaction_id).exists()
    assert (tmp_path / "System/.dex/adoption/history-backups" / second.transaction_id).exists()


def test_retention_candidate_drift_invalidates_acknowledgement(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    old = datetime(2025, 1, 1, tzinfo=UTC)
    first = _prepare(tmp_path, tool, ref, now=lambda: old)
    _prepare(tmp_path, tool, ref, now=lambda: old + timedelta(days=1))
    preview = preview_retention(tmp_path, now=old + timedelta(days=100), successful_release_activations=5)
    _prepare(tmp_path, tool, ref, now=lambda: old + timedelta(days=2))
    with pytest.raises(PermissionError, match="exact-set"):
        delete_retention_candidates(
            tmp_path,
            preview,
            acknowledged_ids=(first.transaction_id,),
            exact_set_sha256=preview.exact_set_sha256,
        )
