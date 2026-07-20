import hashlib
import importlib
import json
import os
import stat
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.utils import history_hygiene
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
    _git(root, "config", "user.email", "tests@example.com")
    _git(root, "config", "user.name", "Synthetic")
    (root / "leak.txt").write_bytes(b"before " + SECRET + b" after\n")
    _git(root, "add", "leak.txt")
    _git(root, "commit", "-qm", "fixture")
    return _git(root, "symbolic-ref", "HEAD")


def _tool(
    path: Path,
    *,
    fail: bool = False,
    mutate_remote: bool = False,
    mutate_unselected_ref: bool = False,
    collateral_ref: str = "refs/tags/collateral-tag",
    mutate_worktree: bool = False,
    mutate_index: bool = False,
) -> Path:
    if (path.parent / ".git").is_dir():
        path = path.parent.parent / f"{path.parent.name}-{path.name}"
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
if {mutate_unselected_ref!r}:
    git('update-ref', {collateral_ref!r}, git('rev-parse', refs[0]).decode())
if {mutate_worktree!r}:
    pathlib.Path('collateral-worktree.txt').write_text('changed by tool')
if {mutate_index!r}:
    pathlib.Path('collateral-index.txt').write_text('changed by tool')
    git('add', 'collateral-index.txt')
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


def _mark_retention_eligible(root: Path, preview: HistoryPreview) -> None:
    tree = _git(root, "write-tree")
    rewritten = _git(root, "commit-tree", tree, input_data=b"synthetic verified rewrite\n")
    with history_hygiene._acquire_history_lifecycle_lock(root, create=False) as lifecycle_lock:
        with history_hygiene._load_manifest(
            lifecycle_lock.backup_descriptor,
            preview.transaction_id,
        ) as loaded:
            manifest = loaded.manifest
            assert manifest is not None
            after_refs = {ref: rewritten for ref in manifest["selected_refs"]}
            after_all_refs = {**manifest["all_refs"], **after_refs}
            manifest = manifest.begin_apply().record_applied(
                after_refs,
                after_all_refs,
                "history-clean",
            )
            history_hygiene._store_manifest(loaded.path, manifest)


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
    assert "install git-filter-repo yourself" in absent.guidance
    assert "Manual advanced path" in absent.guidance
    assert "force-push" not in absent.guidance
    assert not (tmp_path / "System/.dex").exists()
    unsupported = tmp_path / "unsupported"
    unsupported.write_text("#!/bin/sh\necho 1.0.0\n")
    unsupported.chmod(0o755)
    assert _prepare(tmp_path, unsupported, ref).state == "optional-tool-unavailable"
    symlink = tmp_path / "symlinked-tool"
    symlink.symlink_to(_tool(tmp_path / "real-tool"))
    assert _prepare(tmp_path, symlink, ref).state == "optional-tool-unavailable"


def test_unsupported_directory_fd_platform_degrades_without_writes(tmp_path, monkeypatch):
    # A platform whose directory-fd substrate cannot be reopened by derived path
    # (e.g. macOS /dev/fd/<n> for a directory -> ENOTDIR) must refuse up front with an
    # honest state instead of crashing mid-transaction. Forced via the probe hook so the
    # test is deterministic on macOS AND Linux. Any use of _fd_path below the gate would
    # raise here, proving the gate short-circuits before the crashing substrate is touched.
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    monkeypatch.setattr(
        history_hygiene,
        "_fd_path",
        lambda _descriptor: (_ for _ in ()).throw(AssertionError("gate must precede _fd_path")),
    )

    preview = _prepare(tmp_path, tool, ref, substrate_probe=lambda: False)

    assert preview.state == "optional-platform-unsupported"
    assert preview.transaction_id is None
    assert preview.preview_sha256 is None
    assert "Security remains fixed" in preview.guidance
    assert "Manual advanced path" in preview.guidance
    assert "did not install, run, or change anything" in preview.guidance
    # No lock, transaction, or recovery-dir state may exist after an unsupported refusal.
    assert not (tmp_path / "System/.dex").exists()


def test_supported_substrate_override_reaches_deep_engine(tmp_path):
    # The explicit override hook lets a supported substrate proceed past the gate; on a
    # real /proc host this prepares, and the point here is only that the gate itself does
    # not block when the probe reports support.
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    if not history_hygiene._directory_fd_substrate_available():
        pytest.skip("host lacks the directory-fd substrate the deep engine requires")
    assert _prepare(tmp_path, tool, ref, substrate_probe=lambda: True).state == "prepared"


def test_directory_fd_substrate_probe_returns_bool_without_writes(tmp_path):
    before = sorted(tmp_path.iterdir())
    result = history_hygiene._directory_fd_substrate_available()
    assert isinstance(result, bool)
    assert sorted(tmp_path.iterdir()) == before


def test_symlinked_recovery_ancestor_refuses_without_outside_bundle_write(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    outside = tmp_path.parent / "outside-history"
    outside.mkdir()
    dex = tmp_path / "System/.dex"
    dex.parent.mkdir()
    dex.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        _prepare(tmp_path, tool, ref)

    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    "dirty_state",
    ["staged", "unstaged", "untracked", "intent-to-add", "odd-filename"],
)
def test_preparation_requires_complete_clean_repository_state(tmp_path, dirty_state):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    if dirty_state == "staged":
        (tmp_path / "leak.txt").write_text("staged\n")
        _git(tmp_path, "add", "leak.txt")
    elif dirty_state == "unstaged":
        (tmp_path / "leak.txt").write_text("unstaged\n")
    elif dirty_state == "intent-to-add":
        (tmp_path / "intent.txt").write_text("intent\n")
        _git(tmp_path, "add", "-N", "intent.txt")
    else:
        name = "line\nname.txt" if dirty_state == "odd-filename" else "untracked.txt"
        (tmp_path / name).write_text("untracked\n")

    with pytest.raises(PermissionError, match="clean index and worktree"):
        _prepare(tmp_path, tool, ref)

    assert not (tmp_path / "System/.dex").exists()


def test_removing_quiescence_guard_reproduces_dirty_preparation(tmp_path, monkeypatch):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    (tmp_path / "untracked.txt").write_text("dirty\n")
    monkeypatch.setattr(history_hygiene, "_require_repository_quiescence", lambda _root: None)

    assert _prepare(tmp_path, tool, ref).state == "prepared"


def test_apply_revalidates_quiescence_immediately_before_rewrite(tmp_path, monkeypatch):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    preview = _prepare(tmp_path, tool, ref)
    before = _git(tmp_path, "rev-parse", ref)
    original = history_hygiene._require_repository_quiescence
    calls = 0

    def create_race_after_first_check(root):
        nonlocal calls
        original(root)
        calls += 1
        if calls == 1:
            (tmp_path / "race\nfile.txt").write_text("race\n")

    monkeypatch.setattr(history_hygiene, "_require_repository_quiescence", create_race_after_first_check)

    outcome = apply_history_cleanup(
        tmp_path,
        preview,
        typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
        credential_needles=(SECRET,),
        filter_repo=tool,
    )

    assert outcome.state == "recovery-required"
    assert _git(tmp_path, "rev-parse", ref) == before


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
    assert not any(path.name.startswith(".incomplete-") for path in transaction.parent.iterdir())


def test_prepare_publishes_only_after_manifest_is_durable(tmp_path, monkeypatch):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    original = history_hygiene._write_restrictive
    manifest_parent = None

    def observe_manifest(path, data):
        nonlocal manifest_parent
        original(path, data)
        if path.name == "manifest.json":
            manifest_parent = path.parent.resolve().name

    monkeypatch.setattr(history_hygiene, "_write_restrictive", observe_manifest)
    preview = _prepare(tmp_path, tool, ref)
    backup = tmp_path / "System/.dex/adoption/history-backups"

    assert manifest_parent == f".incomplete-{preview.transaction_id}"
    assert (backup / preview.transaction_id / "manifest.json").is_file()
    assert not (backup / manifest_parent).exists()


def test_loaded_transaction_context_closes_descriptor(tmp_path):
    ref = _repo(tmp_path)
    preview = _prepare(tmp_path, _tool(tmp_path / "git-filter-repo"), ref)

    with history_hygiene._acquire_history_lifecycle_lock(tmp_path, create=False) as lifecycle_lock:
        with history_hygiene._load_manifest(lifecycle_lock.backup_descriptor, preview.transaction_id) as transaction:
            descriptor = transaction.descriptor
            assert os.fstat(descriptor)

    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_pinned_backup_descriptor_survives_recovery_ancestor_rename_and_replacement(tmp_path):
    ref = _repo(tmp_path)
    preview = _prepare(tmp_path, _tool(tmp_path / "git-filter-repo"), ref)
    outside = tmp_path.parent / "outside-pinned-history"
    outside.mkdir()

    with history_hygiene._acquire_history_lifecycle_lock(tmp_path, create=False) as lifecycle_lock:
        dex = tmp_path / "System/.dex"
        preserved = tmp_path / "System/.dex-preserved"
        dex.rename(preserved)
        dex.symlink_to(outside, target_is_directory=True)

        with history_hygiene._load_manifest(
            lifecycle_lock.backup_descriptor,
            preview.transaction_id,
        ) as transaction:
            assert transaction.manifest["transaction_id"] == preview.transaction_id
            assert str(transaction.path.resolve()).startswith(str(preserved.resolve()))

    assert list(outside.iterdir()) == []


def test_pinned_manifest_load_refuses_transaction_unlink_and_replacement(tmp_path):
    ref = _repo(tmp_path)
    preview = _prepare(tmp_path, _tool(tmp_path / "git-filter-repo"), ref)
    backup = tmp_path / "System/.dex/adoption/history-backups"
    transaction = backup / preview.transaction_id
    preserved = backup / (preview.transaction_id + "-preserved")
    outside = tmp_path.parent / "outside-transaction-replacement"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("preserve")

    with history_hygiene._acquire_history_lifecycle_lock(tmp_path, create=False) as lifecycle_lock:
        transaction.rename(preserved)
        transaction.symlink_to(outside, target_is_directory=True)
        with pytest.raises(OSError):
            history_hygiene._load_manifest(
                lifecycle_lock.backup_descriptor,
                preview.transaction_id,
            )

    assert sentinel.read_text() == "preserve"
    assert list(outside.iterdir()) == [sentinel]


def test_path_reopen_mutation_loses_pinned_backup_authority(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    root.mkdir()
    pinned = root / "System/.dex/adoption/history-backups"
    pinned.mkdir(parents=True, mode=0o700)
    pinned_inode = pinned.stat().st_ino
    outside = tmp_path / "replacement-vault"
    replacement = outside / "System/.dex/adoption/history-backups"
    replacement.mkdir(parents=True, mode=0o700)
    replacement_inode = replacement.stat().st_ino
    root_descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        root.rename(tmp_path / "vault-preserved")
        outside.rename(root)
        monkeypatch.setattr(
            history_hygiene,
            "_open_backup_root_at",
            lambda _descriptor, *, create=False: history_hygiene._open_directory_chain(
                root,
                ("System", ".dex", "adoption", "history-backups"),
                create=create,
            ),
        )

        descriptor = history_hygiene._open_backup_root_at(root_descriptor)
        try:
            assert os.fstat(descriptor).st_ino == replacement_inode
            assert os.fstat(descriptor).st_ino != pinned_inode
        finally:
            os.close(descriptor)
    finally:
        os.close(root_descriptor)


def test_prepare_apply_and_rewind_survive_module_restart(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    preview = _prepare(tmp_path, tool, ref)

    restarted = importlib.reload(history_hygiene)
    outcome = restarted.apply_history_cleanup(
        tmp_path,
        restarted.HistoryPreview(preview.state, preview.transaction_id, preview.preview_sha256, preview.guidance),
        typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
        credential_needles=(SECRET,),
        filter_repo=tool,
    )
    assert outcome.state == "history-clean"

    restarted = importlib.reload(history_hygiene)
    rewind = restarted.rewind_history_cleanup(tmp_path, preview.transaction_id)
    assert rewind.state == "rewound"
    assert SECRET in subprocess.run(
        ["git", "show", f"{ref}:leak.txt"], cwd=tmp_path, check=True, capture_output=True
    ).stdout


def test_apply_rebinds_only_the_prepared_credential_set(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    preview = _prepare(tmp_path, tool, ref)

    with pytest.raises(ValueError, match="credential set changed"):
        apply_history_cleanup(
            tmp_path,
            preview,
            typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
            credential_needles=(b"different-secret",),
            filter_repo=tool,
        )


def test_apply_rebinds_exact_occurrence_coordinates_not_same_sized_history_secret(tmp_path):
    secret_a = b"same-size-secret-A"
    secret_b = b"same-size-secret-B"
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "tests@example.com")
    _git(tmp_path, "config", "user.name", "Synthetic")
    (tmp_path / "leak.txt").write_bytes(secret_a + b"\n" + secret_b + b"\n")
    _git(tmp_path, "add", "leak.txt")
    _git(tmp_path, "commit", "-qm", "two secrets")
    ref = _git(tmp_path, "symbolic-ref", "HEAD")
    tool = _tool(tmp_path / "git-filter-repo")
    preview = prepare_history_cleanup(
        tmp_path,
        security_state="remediated",
        explicit_choice=True,
        selected_refs=(ref,),
        credential_needles=(secret_a,),
        successful_release_activations=0,
        no_external_backup_acknowledged=True,
        filter_repo=tool,
    )

    with pytest.raises(ValueError, match="credential set changed"):
        apply_history_cleanup(
            tmp_path,
            preview,
            typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
            credential_needles=(secret_b,),
            filter_repo=tool,
        )

    outcome = apply_history_cleanup(
        tmp_path,
        preview,
        typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
        credential_needles=(secret_a,),
        filter_repo=tool,
    )
    assert outcome.state == "history-clean"
    rewritten = subprocess.run(
        ["git", "show", f"{ref}:leak.txt"], cwd=tmp_path, check=True, capture_output=True
    ).stdout
    assert secret_a not in rewritten
    assert secret_b in rewritten


@pytest.mark.parametrize(
    ("prepared_secret", "substitute_secret"),
    [
        (b"prefix-secret", b"prefix-secret-longer"),
        (b"prefix-secret-longer", b"prefix-secret"),
    ],
)
def test_apply_rejects_prefix_related_credential_substitution(tmp_path, prepared_secret, substitute_secret):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "tests@example.com")
    _git(tmp_path, "config", "user.name", "Synthetic")
    (tmp_path / "leak.txt").write_bytes(b"prefix-secret-longer\n")
    _git(tmp_path, "add", "leak.txt")
    _git(tmp_path, "commit", "-qm", "prefix secrets")
    ref = _git(tmp_path, "symbolic-ref", "HEAD")
    tool = _tool(tmp_path / "git-filter-repo")
    preview = prepare_history_cleanup(
        tmp_path,
        security_state="remediated",
        explicit_choice=True,
        selected_refs=(ref,),
        credential_needles=(prepared_secret,),
        successful_release_activations=0,
        no_external_backup_acknowledged=True,
        filter_repo=tool,
    )

    with pytest.raises(ValueError, match="credential set changed"):
        apply_history_cleanup(
            tmp_path,
            preview,
            typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
            credential_needles=(substitute_secret,),
            filter_repo=tool,
        )

    manifest = json.loads(
        (tmp_path / "System/.dex/adoption/history-backups" / preview.transaction_id / "manifest.json").read_text()
    )
    spans = manifest["credential_occurrences"][0]
    assert all(end - start == len(prepared_secret) for _, start, end in spans)


def _descriptor_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def _recovery_transactions(backup: Path) -> list[Path]:
    return sorted(backup.iterdir())


def test_prepare_fd_path_failure_closes_descriptors_and_removes_orphan(tmp_path, monkeypatch):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    before = _descriptor_count()
    monkeypatch.setattr(history_hygiene, "_fd_path", lambda _descriptor: (_ for _ in ()).throw(OSError("fd path")))

    # Bypass the up-front platform gate (whose default probe also calls _fd_path and would
    # swallow this OSError) so the DEEP post-lock _fd_path-failure branch is exercised: it must
    # raise, close every descriptor, and remove the orphaned incomplete transaction.
    for _ in range(5):
        with pytest.raises(OSError, match="fd path"):
            _prepare(tmp_path, tool, ref, substrate_probe=lambda: True)

    assert _descriptor_count() == before
    backup = tmp_path / "System/.dex/adoption/history-backups"
    assert not backup.exists() or _recovery_transactions(backup) == []


@pytest.mark.parametrize("failure", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("boundary", ["fd-path", "bundle-created"])
def test_prepare_cancellation_removes_incomplete_transaction(tmp_path, monkeypatch, failure, boundary):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    before = _descriptor_count()

    if boundary == "fd-path":
        original_fd_path = history_hygiene._fd_path

        def interrupt_fd_path(descriptor):
            path = original_fd_path(descriptor)
            if path.resolve().name.startswith(".incomplete-"):
                raise failure("cancelled")
            return path

        monkeypatch.setattr(history_hygiene, "_fd_path", interrupt_fd_path)
    else:
        original_git = history_hygiene._git

        def interrupt_after_bundle(root, *args, **kwargs):
            result = original_git(root, *args, **kwargs)
            if args[:2] == ("bundle", "create"):
                raise failure("cancelled")
            return result

        monkeypatch.setattr(history_hygiene, "_git", interrupt_after_bundle)

    with pytest.raises(failure, match="cancelled"):
        _prepare(tmp_path, tool, ref)

    backup = tmp_path / "System/.dex/adoption/history-backups"
    assert _descriptor_count() == before
    assert not backup.exists() or _recovery_transactions(backup) == []


@pytest.mark.skipif(not hasattr(os, "fork"), reason="process-death fault injection requires fork")
@pytest.mark.parametrize("boundary", ["fd-path", "bundle-created"])
def test_restart_prunes_process_death_during_incomplete_preparation(tmp_path, boundary):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    original_git = history_hygiene._git
    child = os.fork()
    if child == 0:
        if boundary == "fd-path":
            original_fd_path = history_hygiene._fd_path

            def die_at_transaction_fd(descriptor):
                path = original_fd_path(descriptor)
                if path.resolve().name.startswith(".incomplete-"):
                    os._exit(71)
                return path

            history_hygiene._fd_path = die_at_transaction_fd
        else:
            def die_after_bundle(root, *args, **kwargs):
                result = original_git(root, *args, **kwargs)
                if args[:2] == ("bundle", "create"):
                    os._exit(72)
                return result

            history_hygiene._git = die_after_bundle
        _prepare(tmp_path, tool, ref)
        os._exit(73)

    _, status = os.waitpid(child, 0)
    assert os.WEXITSTATUS(status) in {71, 72}
    backup = tmp_path / "System/.dex/adoption/history-backups"
    incomplete = list(backup.glob(".incomplete-*"))
    assert len(incomplete) == 1
    assert list(incomplete[0].iterdir()) == ([] if boundary == "fd-path" else [incomplete[0] / "history.bundle"])

    restarted = importlib.reload(history_hygiene)
    retention = restarted.preview_retention(
        tmp_path,
        now=datetime.now(UTC),
        successful_release_activations=0,
    )

    assert retention.candidate_ids == ()
    assert retention.protected_final_id is None
    assert _recovery_transactions(backup) == []


def _pause_first_bundle(monkeypatch):
    reached = threading.Event()
    release = threading.Event()
    original_git = history_hygiene._git
    guard = threading.Lock()
    paused = False

    def pause(root, *args, **kwargs):
        nonlocal paused
        result = original_git(root, *args, **kwargs)
        if args[:2] == ("bundle", "create"):
            with guard:
                should_pause = not paused
                paused = True
            if should_pause:
                reached.set()
                assert release.wait(10)
        return result

    monkeypatch.setattr(history_hygiene, "_git", pause)
    return reached, release


def test_concurrent_retention_waits_for_active_preparation(tmp_path, monkeypatch):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    reached, release = _pause_first_bundle(monkeypatch)

    with ThreadPoolExecutor(max_workers=2) as executor:
        preparing = executor.submit(_prepare, tmp_path, tool, ref)
        assert reached.wait(10)
        retaining = executor.submit(
            preview_retention,
            tmp_path,
            now=datetime.now(UTC),
            successful_release_activations=3,
        )
        time.sleep(0.1)
        assert not retaining.done()
        release.set()
        prepared = preparing.result(timeout=10)
        retention = retaining.result(timeout=10)

    assert retention.protected_final_id == prepared.transaction_id
    assert retention.retained_ids == (prepared.transaction_id,)


def test_concurrent_preparations_are_serialized(tmp_path, monkeypatch):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    reached, release = _pause_first_bundle(monkeypatch)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_prepare, tmp_path, tool, ref)
        assert reached.wait(10)
        second = executor.submit(_prepare, tmp_path, tool, ref)
        time.sleep(0.1)
        assert not second.done()
        backup = tmp_path / "System/.dex/adoption/history-backups"
        assert len(list(backup.glob(".incomplete-*"))) == 1
        release.set()
        previews = (first.result(timeout=10), second.result(timeout=10))

    assert len({preview.transaction_id for preview in previews}) == 2
    assert not list(backup.glob(".incomplete-*"))


def test_removing_lifecycle_serialization_reproduces_active_prune(tmp_path, monkeypatch):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    reached, release = _pause_first_bundle(monkeypatch)

    class Unlocked:
        def __init__(self, root, create):
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            self.root_descriptor = os.open(root, flags)
            try:
                self.backup_descriptor = history_hygiene._open_backup_root_at(
                    self.root_descriptor,
                    create=create,
                )
            except BaseException:
                os.close(self.root_descriptor)
                self.root_descriptor = -1
                raise

        def __enter__(self):
            return self

        def __exit__(self, _type, _value, _traceback):
            self.close()

        def close(self):
            if self.backup_descriptor >= 0:
                os.close(self.backup_descriptor)
                self.backup_descriptor = -1
            if self.root_descriptor >= 0:
                os.close(self.root_descriptor)
                self.root_descriptor = -1

    monkeypatch.setattr(
        history_hygiene,
        "_acquire_history_lifecycle_lock",
        lambda root, *, create: Unlocked(root, create),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        preparing = executor.submit(_prepare, tmp_path, tool, ref)
        assert reached.wait(10)
        retention = executor.submit(
            preview_retention,
            tmp_path,
            now=datetime.now(UTC),
            successful_release_activations=0,
        )
        retention.result(timeout=10)
        release.set()
        with pytest.raises(OSError):
            preparing.result(timeout=10)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="process-death fault injection requires fork")
def test_process_death_releases_lifecycle_lock_for_restart(tmp_path):
    backup = tmp_path / "System/.dex/adoption/history-backups"
    child = os.fork()
    if child == 0:
        held = history_hygiene._acquire_history_lifecycle_lock(tmp_path, create=True)
        assert held.root_descriptor >= 0
        os._exit(81)

    _, status = os.waitpid(child, 0)
    assert os.WEXITSTATUS(status) == 81
    assert backup.is_dir()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700

    restarted = importlib.reload(history_hygiene)
    preview = restarted.preview_retention(
        tmp_path,
        now=datetime.now(UTC),
        successful_release_activations=0,
    )
    assert preview.retained_ids == ()


def test_replacing_named_lock_file_cannot_split_directory_lock(tmp_path):
    decoy_name = ".history-lifecycle.lock"
    first = history_hygiene._acquire_history_lifecycle_lock(tmp_path, create=True)
    backup = tmp_path / "System/.dex/adoption/history-backups"
    decoy = backup / decoy_name
    decoy.write_bytes(b"old")
    held_decoy = os.open(decoy, os.O_RDONLY)
    replacement = backup / ".replacement-lock"
    replacement.write_bytes(b"new")
    os.replace(replacement, decoy)
    assert decoy.stat().st_ino != os.fstat(held_decoy).st_ino

    def run_second_lifecycle_operation():
        return preview_retention(
            tmp_path,
            now=datetime.now(UTC),
            successful_release_activations=0,
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        waiting = executor.submit(run_second_lifecycle_operation)
        time.sleep(0.1)
        assert not waiting.done()
        first.close()
        assert waiting.result(timeout=10).protected_final_id is None
    os.close(held_decoy)


def test_hostile_backup_directory_mode_fails_closed(tmp_path):
    backup = tmp_path / "System/.dex/adoption/history-backups"
    backup.mkdir(parents=True)
    backup.chmod(0o755)

    with pytest.raises(OSError):
        preview_retention(tmp_path, now=datetime.now(UTC), successful_release_activations=0)


def test_descriptor_traversal_uses_the_canonical_history_backup_parts():
    from core import paths

    assert history_hygiene.HISTORY_BACKUPS_RELATIVE_PARTS is paths.HISTORY_BACKUPS_RELATIVE_PARTS


def test_restart_pruning_preserves_published_recovery_and_retention_accounting(tmp_path):
    ref = _repo(tmp_path)
    preview = _prepare(tmp_path, _tool(tmp_path / "git-filter-repo"), ref)
    backup = tmp_path / "System/.dex/adoption/history-backups"
    incomplete = backup / (".incomplete-" + "f" * 32)
    incomplete.mkdir(mode=0o700)
    (incomplete / "history.bundle").write_bytes(b"partial")

    restarted = importlib.reload(history_hygiene)
    retention = restarted.preview_retention(
        tmp_path,
        now=datetime.now(UTC),
        successful_release_activations=3,
    )

    assert not incomplete.exists()
    assert retention.protected_final_id == preview.transaction_id
    assert retention.retained_ids == (preview.transaction_id,)
    assert (backup / preview.transaction_id / "history.bundle").is_file()


@pytest.mark.parametrize("artifact", [None, "history.bundle"])
def test_restart_refuses_manifestless_published_transaction_without_deletion(tmp_path, artifact):
    backup = tmp_path / "System/.dex/adoption/history-backups"
    backup.mkdir(parents=True)
    backup.chmod(0o700)
    orphan = backup / ("d" * 32)
    orphan.mkdir(mode=0o700)
    if artifact:
        (orphan / artifact).write_bytes(b"partial bundle")

    restarted = importlib.reload(history_hygiene)
    with pytest.raises(OSError, match="missing its manifest"):
        restarted.preview_retention(
            tmp_path,
            now=datetime.now(UTC),
            successful_release_activations=0,
        )

    assert orphan.exists()


def test_restart_pruning_refuses_symlinked_incomplete_transaction(tmp_path):
    outside = tmp_path.parent / "outside-incomplete-history"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("preserve")
    backup = tmp_path / "System/.dex/adoption/history-backups"
    backup.mkdir(parents=True)
    backup.chmod(0o700)
    (backup / (".incomplete-" + "e" * 32)).symlink_to(outside, target_is_directory=True)

    restarted = importlib.reload(history_hygiene)
    with pytest.raises(OSError):
        restarted.preview_retention(
            tmp_path,
            now=datetime.now(UTC),
            successful_release_activations=0,
        )

    assert sentinel.read_text() == "preserve"
    assert list(outside.iterdir()) == [sentinel]


def test_load_fd_path_failure_closes_descriptor_repeatedly(tmp_path, monkeypatch):
    ref = _repo(tmp_path)
    preview = _prepare(tmp_path, _tool(tmp_path / "git-filter-repo"), ref)
    before = _descriptor_count()
    monkeypatch.setattr(history_hygiene, "_fd_path", lambda _descriptor: (_ for _ in ()).throw(OSError("fd path")))

    for _ in range(5):
        with history_hygiene._acquire_history_lifecycle_lock(tmp_path, create=False) as lifecycle_lock:
            with pytest.raises(OSError, match="fd path"):
                history_hygiene._load_manifest(lifecycle_lock.backup_descriptor, preview.transaction_id)

    assert _descriptor_count() == before


def test_retention_symlinked_ancestor_preserves_containment_error(tmp_path):
    outside = tmp_path.parent / "outside-retention"
    outside.mkdir()
    dex = tmp_path / "System/.dex"
    dex.parent.mkdir()
    dex.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        preview_retention(tmp_path, now=datetime.now(UTC), successful_release_activations=0)

    assert list(outside.iterdir()) == []


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


@pytest.mark.parametrize("name", ["git-config.bin", "index.bin"])
def test_restrictive_recovery_artifact_corruption_is_refused(tmp_path, name):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    preview = _prepare(tmp_path, tool, ref)
    artifact = tmp_path / "System/.dex/adoption/history-backups" / preview.transaction_id / name
    artifact.write_bytes(artifact.read_bytes() + b"corrupt")

    with pytest.raises(OSError, match="recovery artifact identity"):
        apply_history_cleanup(
            tmp_path,
            preview,
            typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
            credential_needles=(SECRET,),
            filter_repo=tool,
        )


def test_apply_refuses_recovery_ancestor_swapped_after_prepare(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    preview = _prepare(tmp_path, tool, ref)
    dex = tmp_path / "System/.dex"
    dex.rename(tmp_path / "System/.dex-preserved")
    outside = tmp_path.parent / "outside-history-apply"
    outside.mkdir()
    dex.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        apply_history_cleanup(
            tmp_path,
            preview,
            typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
            credential_needles=(SECRET,),
            filter_repo=tool,
        )

    assert list(outside.iterdir()) == []


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
    remote = tmp_path.parent / f"{tmp_path.name}-remote.git"
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
    remote = tmp_path.parent / f"{tmp_path.name}-remote.git"
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


@pytest.mark.parametrize("interrupted", [False, True])
@pytest.mark.parametrize(
    "collateral_ref",
    [
        "refs/tags/collateral-tag",
        "refs/remotes/origin/collateral",
        "refs/replace/1111111111111111111111111111111111111111",
        "refs/notes/collateral",
        "refs/backup/collateral",
    ],
)
def test_collateral_unselected_ref_mutation_never_reports_clean_and_is_rewound(tmp_path, interrupted, collateral_ref):
    ref = _repo(tmp_path)
    original = _git(tmp_path, "rev-parse", ref)
    _git(tmp_path, "tag", "preserved-tag")
    tool = _tool(
        tmp_path / "git-filter-repo",
        fail=interrupted,
        mutate_unselected_ref=True,
        collateral_ref=collateral_ref,
    )
    preview = _prepare(tmp_path, tool, ref)
    outcome = apply_history_cleanup(
        tmp_path,
        preview,
        typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
        credential_needles=(SECRET,),
        filter_repo=tool,
    )
    assert outcome.state == "recovery-required"
    assert rewind_history_cleanup(tmp_path, preview.transaction_id).state == "rewound"
    assert _git(tmp_path, "rev-parse", ref) == original
    assert _git(tmp_path, "rev-parse", "refs/tags/preserved-tag") == original
    assert subprocess.run(["git", "show-ref", "--verify", "--quiet", collateral_ref], cwd=tmp_path).returncode


def test_history_metadata_contains_no_raw_credential_or_direct_fingerprint(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    preview = _prepare(tmp_path, tool, ref)
    transaction = tmp_path / "System/.dex/adoption/history-backups" / preview.transaction_id
    forbidden = {SECRET, hashlib.sha256(SECRET).hexdigest().encode(), hashlib.sha1(SECRET).hexdigest().encode()}
    for artifact in (transaction / "manifest.json", transaction / "objects.json"):
        data = artifact.read_bytes()
        assert not any(value in data for value in forbidden)
    assert "credential_sha256" not in (transaction / "manifest.json").read_text()


@pytest.mark.parametrize("surface", ["worktree", "index"])
def test_collateral_worktree_or_index_mutation_fails_closed(tmp_path, surface):
    ref = _repo(tmp_path)
    tool = _tool(
        tmp_path / "git-filter-repo",
        mutate_worktree=surface == "worktree",
        mutate_index=surface == "index",
    )
    preview = _prepare(tmp_path, tool, ref)
    outcome = apply_history_cleanup(
        tmp_path,
        preview,
        typed_consent=f"CLEAN OPTIONAL HISTORY {preview.transaction_id}",
        credential_needles=(SECRET,),
        filter_repo=tool,
    )
    assert outcome.state == "recovery-required"
    rewind = rewind_history_cleanup(tmp_path, preview.transaction_id)
    assert rewind.state == "recovery-required"
    assert "Do not push" in rewind.guidance


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
    _mark_retention_eligible(tmp_path, first)
    _mark_retention_eligible(tmp_path, second)
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


def test_prepared_only_history_transactions_are_never_deletion_candidates(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    old = datetime(2025, 1, 1, tzinfo=UTC)
    first = _prepare(tmp_path, tool, ref, now=lambda: old)
    second = _prepare(tmp_path, tool, ref, now=lambda: old + timedelta(days=1))

    preview = preview_retention(
        tmp_path,
        now=old + timedelta(days=100),
        successful_release_activations=5,
    )

    assert preview.candidate_ids == ()
    assert preview.protected_final_id == second.transaction_id
    assert preview.retained_ids == tuple(sorted((first.transaction_id, second.transaction_id)))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phase", "prepared"),
        ("post_cleanup_scan_state", "history-cleanup-pending"),
        ("post_cleanup_scan_state", "history-scope-unknown"),
        ("post_cleanup_uninspected_scopes", ["selected-refs"]),
        ("after_refs", {}),
        ("external_backup", {}),
    ],
)
def test_retention_requires_terminal_verified_cleanup_evidence(tmp_path, field, value):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    old = datetime(2025, 1, 1, tzinfo=UTC)
    candidate = _prepare(tmp_path, tool, ref, now=lambda: old)
    final = _prepare(tmp_path, tool, ref, now=lambda: old + timedelta(days=1))
    _mark_retention_eligible(tmp_path, candidate)
    _mark_retention_eligible(tmp_path, final)
    with history_hygiene._acquire_history_lifecycle_lock(tmp_path, create=False) as lifecycle_lock:
        with history_hygiene._load_manifest(
            lifecycle_lock.backup_descriptor,
            candidate.transaction_id,
        ) as loaded:
            assert loaded.manifest is not None
            payload = loaded.manifest.to_dict()
            payload[field] = value
            unsigned = {key: item for key, item in payload.items() if key != "preview_sha256"}
            payload["preview_sha256"] = history_hygiene._sha(history_hygiene._json_bytes(unsigned))
            history_hygiene._atomic_replace(
                loaded.path / "manifest.json",
                history_hygiene._json_bytes(payload),
                0o600,
                "test manifest mutation failed",
            )

    preview = preview_retention(
        tmp_path,
        now=old + timedelta(days=100),
        successful_release_activations=5,
    )

    assert preview.candidate_ids == ()
    if field in {"phase", "external_backup"}:
        assert candidate.transaction_id not in preview.retained_ids
    else:
        assert candidate.transaction_id in preview.retained_ids


def test_retention_candidate_drift_invalidates_acknowledgement(tmp_path):
    ref = _repo(tmp_path)
    tool = _tool(tmp_path / "git-filter-repo")
    old = datetime(2025, 1, 1, tzinfo=UTC)
    first = _prepare(tmp_path, tool, ref, now=lambda: old)
    second = _prepare(tmp_path, tool, ref, now=lambda: old + timedelta(days=1))
    _mark_retention_eligible(tmp_path, first)
    _mark_retention_eligible(tmp_path, second)
    preview = preview_retention(tmp_path, now=old + timedelta(days=100), successful_release_activations=5)
    third = _prepare(tmp_path, tool, ref, now=lambda: old + timedelta(days=2))
    _mark_retention_eligible(tmp_path, third)
    with pytest.raises(PermissionError, match="exact-set"):
        delete_retention_candidates(
            tmp_path,
            preview,
            acknowledged_ids=(first.transaction_id,),
            exact_set_sha256=preview.exact_set_sha256,
        )
