"""Contract tests for the split-topology no-merge updater."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time as real_time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import portable_contract
from core.lifecycle import service
from core.lifecycle.bridge import ACTIVATION_RELATIVE, activate_vault
from core.lifecycle.catalog import canonical_catalog_bytes, load_catalog
from core.lifecycle.inventory import build_inventory
from core.tests.lifecycle_test_helpers import (
    canonical_json_bytes,
    lifecycle_catalog_document,
    write_bridge_release,
)
from core.transaction.engine import PlanRejected
from core.update import apply_update
from core.utils import update_verifier
from core.utils.update_verifier import legacy_profile_bytes

REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(root: Path, relative: str, content: bytes, mode: int = 0o644) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    target.chmod(mode)


def _refresh_manifest(release: Path) -> None:
    manifest = release / "System/.installed-files.manifest"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_bytes(b"")
    paths = sorted(
        candidate.relative_to(release).as_posix()
        for candidate in release.rglob("*")
        if candidate.is_file() and ".git" not in candidate.relative_to(release).parts
    )
    manifest.write_text("".join(f"{relative}\n" for relative in paths), encoding="utf-8")


def _commit_release(release: Path, version: str) -> tuple[str, str, str, str]:
    package = release / "package.json"
    package.write_text(json.dumps({"name": "dex-test", "version": version}) + "\n")
    _refresh_manifest(release)
    _git(release, "add", "-A")
    _git(release, "commit", "--quiet", "-m", f"release {version}")
    commit = _git(release, "rev-parse", "HEAD")
    tree = _git(release, "rev-parse", "HEAD^{tree}")
    tag = f"dist/release/v{version}-{commit[:7]}"
    _git(release, "tag", "-a", tag, "-m", f"Dex {version}")
    tag_object = _git(release, "rev-parse", f"refs/tags/{tag}")
    return tag, tag_object, commit, tree


@pytest.fixture
def split_release_fixture(tmp_path: Path) -> dict[str, object]:
    release = tmp_path / "release"
    release.mkdir()
    _git(release, "init", "--quiet")
    _git(release, "config", "user.name", "Dex Update Tests")
    _git(release, "config", "user.email", "update@example.com")
    _write(release, "README.md", b"old brain\n")
    _write(
        release,
        "CLAUDE.md",
        b"# Old instructions\n\n## USER_EXTENSIONS_START\n## USER_EXTENSIONS_END\n\nOld footer.\n",
    )
    _write(release, "core/obsolete.py", b"OLD = True\n", 0o755)
    _write(release, "03-Tasks/Tasks.md", b"# shipped seed\n")
    _write(release, "04-Projects/private.md", b"release placeholder\n")
    _write(release, "System/.dex/release-runtime.json", b"{}\n")
    old_tag, old_tag_object, old_commit, old_tree = _commit_release(release, "1.63.0")

    _write(release, "README.md", b"new brain\n")
    _write(
        release,
        "CLAUDE.md",
        b"# New instructions\n\n## USER_EXTENSIONS_START trailing text\r\n"
        b"## USER_EXTENSIONS_END trailing text\r\n\r\nNew footer.\n",
    )
    _write(release, "core/new.py", b"NEW = True\n")
    _write(release, "03-Tasks/Tasks.md", b"# changed shipped seed\n")
    _write(release, "04-Projects/private.md", b"release tried to replace user notes\n")
    _write(release, "System/.dex/release-runtime.json", b'{"new":true}\n')
    (release / "core/obsolete.py").unlink()
    target_tag, target_tag_object, target_commit, target_tree = _commit_release(release, "1.64.0")

    vault = tmp_path / "vault"
    vault.mkdir()
    for relative in (
        "README.md",
        "CLAUDE.md",
        "core/obsolete.py",
        "03-Tasks/Tasks.md",
        "04-Projects/private.md",
        "System/.dex/release-runtime.json",
    ):
        raw = subprocess.run(
            ["git", "-C", str(release), "show", f"{old_commit}:{relative}"],
            check=True,
            capture_output=True,
        ).stdout
        _write(vault, relative, raw, 0o755 if relative == "core/obsolete.py" else 0o644)
    _write(vault, "03-Tasks/Tasks.md", b"# user's edited tasks\n")
    _write(vault, "04-Projects/private.md", b"private user bytes\n")
    _write(vault, "System/.dex/release-runtime.json", b'{"local":true}\n')
    _write(vault, "System/user-profile.yaml", b"updates:\n  channel: stable\n")

    brain = vault / ".dex/brain.git"
    brain.parent.mkdir(parents=True)
    _git(vault, "init", "--bare", "--quiet", str(brain))
    subprocess.run(
        [
            "git",
            f"--git-dir={brain}",
            "fetch",
            "--quiet",
            "--tags",
            str(release),
            f"+{old_commit}:refs/dex/installed",
            f"+{target_commit}:refs/remotes/upstream/release",
        ],
        check=True,
    )
    subprocess.run(
        ["git", f"--git-dir={brain}", "remote", "add", "origin", "https://github.com/davekilleen/Dex.git"],
        check=True,
    )
    _write(vault, ".git/dex-vault-v2", b'{"role":"vault"}\n')
    _write(
        vault,
        ".dex/brain.git/dex-brain-v2",
        (json.dumps({"role": "brain", "installed": old_commit}) + "\n").encode(),
    )
    _write(
        vault,
        "System/.dex/topology.json",
        (
            json.dumps(
                {
                    "topology": "brain-vault-split",
                    "vaultGitDir": ".git",
                    "brainGitDir": ".dex/brain.git",
                    "installedRelease": old_commit,
                    "environment": {"DEX_VAULT": str(vault.resolve())},
                }
            )
            + "\n"
        ).encode(),
    )
    return {
        "release": release,
        "vault": vault,
        "brain": brain,
        "old": (old_tag, old_tag_object, old_commit, old_tree),
        "target": (target_tag, target_tag_object, target_commit, target_tree),
    }


def _verified(fixture: dict[str, object]) -> apply_update.VerifiedReleaseRef:
    tag, tag_object, commit, tree = fixture["target"]
    return apply_update.verify_release_ref(
        fixture["vault"],
        tag=tag,
        tag_object=tag_object,
        commit=commit,
        tree=tree,
    )


class _ScriptedDeliveryFetch:
    def __init__(self, outcomes: tuple[BaseException | None, ...]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[Path, tuple[str, ...], dict[str, object]]] = []
        self.budgets: list[update_verifier.ExecutionBudget] = []

    def use_budget(self, budget: update_verifier.ExecutionBudget) -> None:
        self.budgets.append(budget)

    def run(self, git_dir: Path, *arguments: str, **kwargs: object) -> bytes:
        self.calls.append((git_dir, arguments, kwargs))
        outcome = self.outcomes[len(self.calls) - 1]
        if outcome is not None:
            raise outcome
        return b""


def _stub_latest_identity(
    fixture: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    tag, tag_object, commit, tree = fixture["target"]
    evidence = {
        "status": update_verifier.STATUS_IDENTITY,
        "tag": tag,
        "tag_object": tag_object,
        "commit": commit,
        "tree": tree,
    }
    monkeypatch.setattr(
        update_verifier,
        "prove_latest_release",
        lambda *_args, **_kwargs: evidence,
    )
    return evidence


def _visible_vault_content(root: Path) -> dict[str, bytes]:
    return {
        candidate.relative_to(root).as_posix(): candidate.read_bytes()
        for candidate in root.rglob("*")
        if candidate.is_file() and candidate.relative_to(root).parts[0] not in {".dex", ".git"}
    }


def _retarget_release(
    fixture: dict[str, object],
    relative: str,
    content: bytes,
    version: str = "1.65.0",
) -> None:
    release = fixture["release"]
    _write(release, relative, content)
    target = _commit_release(release, version)
    _, _, commit, _ = target
    _git(
        fixture["brain"],
        "fetch",
        "--quiet",
        "--tags",
        str(release),
        f"+{commit}:refs/remotes/upstream/release",
    )
    fixture["target"] = target


def test_verified_release_is_pinned_to_immutable_tag_and_channel(
    split_release_fixture: dict[str, object],
) -> None:
    release = _verified(split_release_fixture)

    assert release.tag.startswith("dist/release/v1.64.0-")
    assert release.channel == "stable"

    tag, tag_object, commit, tree = split_release_fixture["target"]
    with pytest.raises(apply_update.ReleaseVerificationError, match="tag object"):
        apply_update.verify_release_ref(
            split_release_fixture["vault"],
            tag=tag,
            tag_object="0" * len(tag_object),
            commit=commit,
            tree=tree,
        )


def test_apply_update_replaces_brain_prunes_unchanged_and_preserves_user_owned_paths(
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    release = _verified(split_release_fixture)

    result = apply_update.apply_verified_release(vault, release)

    assert result["committed"] is True
    assert (vault / "README.md").read_bytes() == b"new brain\n"
    assert (vault / "core/new.py").read_bytes() == b"NEW = True\n"
    assert not (vault / "core/obsolete.py").exists()
    assert (vault / "03-Tasks/Tasks.md").read_bytes() == b"# user's edited tasks\n"
    assert (vault / "04-Projects/private.md").read_bytes() == b"private user bytes\n"
    assert (vault / "System/.dex/release-runtime.json").read_bytes() == b'{"local":true}\n'
    _, _, target_commit, _ = split_release_fixture["target"]
    topology = json.loads((vault / "System/.dex/topology.json").read_text())
    marker = json.loads((vault / ".dex/brain.git/dex-brain-v2").read_text())
    assert topology["installedRelease"] == target_commit
    assert marker["installed"] == target_commit
    assert (
        subprocess.run(
            ["git", f"--git-dir={split_release_fixture['brain']}", "rev-parse", "refs/dex/installed"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == target_commit
    )


def test_delivery_previews_and_applies_only_the_exact_pinned_release(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = split_release_fixture["vault"]
    release = split_release_fixture["release"]
    brain = split_release_fixture["brain"]
    old_tag, _old_tag_object, old_commit, _old_tree = split_release_fixture["old"]
    del old_tag

    _write(release, "System/.release-evidence-profile.json", legacy_profile_bytes("1.65.0"))
    target_tag, target_tag_object, target_commit, target_tree = _commit_release(release, "1.65.0")
    del target_tag_object, target_tree
    _git(release, "branch", "-f", "release", target_commit)
    _write(vault, "package.json", b'{"name":"dex-test","version":"1.63.0"}\n')
    _write(vault, "System/.release-evidence-profile.json", legacy_profile_bytes("1.63.0"))
    _git(brain, "update-ref", "refs/remotes/upstream/release", old_commit)
    assert (
        subprocess.run(
            ["git", f"--git-dir={brain}", "rev-parse", "--verify", f"refs/tags/{target_tag}"],
            capture_output=True,
        ).returncode
        != 0
    )

    delivered = apply_update.deliver_latest_release(
        vault,
        state_root=tmp_path / "evidence-state",
        remote_url=str(release),
        allow_test_transport=True,
        wall_clock_seconds=60.0,
    )

    assert delivered["status"] == "delivered"
    assert delivered["release"]["tag"] == target_tag
    assert _git(brain, "rev-parse", f"refs/tags/{target_tag}")
    assert _git(brain, "rev-parse", "refs/dex/installed") == old_commit
    assert (vault / "README.md").read_bytes() == b"old brain\n"

    previewed = service.build_and_preview_delivered_release(vault, delivered["release"])
    assert previewed["preview"]["release"] == delivered["release"]
    assert {entry["path"] for entry in previewed["preview"]["writes"]} >= {"README.md", "core/obsolete.py"}

    def direct_apply_must_not_run(*_args, **_kwargs):
        raise AssertionError("delivery execution bypassed core.lifecycle.service")

    monkeypatch.setattr(apply_update, "apply_verified_release", direct_apply_must_not_run)
    executed = service.execute_approved_delivered_release(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )

    assert executed["release"] == delivered["release"]
    assert executed["receipt"]["transaction_id"]
    assert _git(brain, "rev-parse", "refs/dex/installed") == target_commit
    assert (vault / "README.md").read_bytes() == b"new brain\n"


def test_default_delivery_budget_remains_ten_seconds_and_evidence_failure_is_not_retried(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = split_release_fixture["vault"]
    calls: list[float] = []

    def prove_latest_release(
        *_args, wall_clock_seconds: float, **_kwargs
    ) -> dict[str, object]:
        calls.append(wall_clock_seconds)
        return {"status": "UNKNOWN", "reason": "evidence-invalid"}

    monkeypatch.setattr(update_verifier, "prove_latest_release", prove_latest_release)
    runner = _ScriptedDeliveryFetch(())

    assert apply_update.deliver_latest_release(
        vault,
        state_root=tmp_path / "evidence-state",
        git_runner=runner,
    ) == {
        "status": "not-delivered",
        "evidence": {"status": "UNKNOWN", "reason": "evidence-invalid"},
    }
    assert calls == [10.0]
    assert runner.calls == []
    assert runner.budgets == []


def test_pre_delivery_proof_retries_one_sanitized_http_429_within_original_deadline(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = split_release_fixture["vault"]
    tag, tag_object, commit, tree = split_release_fixture["target"]
    evidence = {
        "status": update_verifier.STATUS_IDENTITY,
        "tag": tag,
        "tag_object": tag_object,
        "commit": commit,
        "tree": tree,
    }
    proof_budgets: list[float] = []

    def prove_latest_release(
        *_args, wall_clock_seconds: float, **_kwargs
    ) -> dict[str, object]:
        proof_budgets.append(wall_clock_seconds)
        if len(proof_budgets) == 1:
            return {
                "status": "UNKNOWN",
                "reason": "transient-http-rejection",
                "diagnostic": {"classification": "http-429"},
            }
        return evidence

    moments = iter((100.0, 100.2, 100.3))
    monkeypatch.setattr(apply_update, "_monotonic", lambda: next(moments), raising=False)
    sleeps: list[float] = []
    monkeypatch.setattr(apply_update, "time", SimpleNamespace(sleep=sleeps.append))
    monkeypatch.setattr(update_verifier, "prove_latest_release", prove_latest_release)
    runner = _ScriptedDeliveryFetch((None,))

    result = apply_update.deliver_latest_release(
        vault,
        state_root=tmp_path / "evidence-state",
        git_runner=runner,
        wall_clock_seconds=10.0,
    )

    assert result["status"] == "delivered"
    assert result["release"]["tag_object"] == tag_object
    assert result["release"]["commit"] == commit
    assert result["release"]["tree"] == tree
    assert proof_budgets == [10.0, pytest.approx(9.7)]
    assert sleeps == [apply_update.PRE_DELIVERY_PROOF_RETRY_BACKOFF_SECONDS]
    assert len(runner.calls) == 1


def test_pre_delivery_proof_retries_one_sanitized_network_failure_within_original_deadline(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = split_release_fixture["vault"]
    tag, tag_object, commit, tree = split_release_fixture["target"]
    identity = {
        "status": update_verifier.STATUS_IDENTITY,
        "tag": tag,
        "tag_object": tag_object,
        "commit": commit,
        "tree": tree,
    }
    offline = {
        "status": update_verifier.STATUS_OFFLINE,
        "reason": "network-unavailable",
    }
    proof_budgets: list[float] = []

    def prove_latest_release(
        *_args, wall_clock_seconds: float, **_kwargs
    ) -> dict[str, object]:
        proof_budgets.append(wall_clock_seconds)
        return offline if len(proof_budgets) == 1 else identity

    moments = iter((100.0, 100.2, 100.3))
    monkeypatch.setattr(apply_update, "_monotonic", lambda: next(moments), raising=False)
    sleeps: list[float] = []
    monkeypatch.setattr(apply_update, "time", SimpleNamespace(sleep=sleeps.append))
    monkeypatch.setattr(update_verifier, "prove_latest_release", prove_latest_release)
    runner = _ScriptedDeliveryFetch((None,))

    result = apply_update.deliver_latest_release(
        vault,
        state_root=tmp_path / "evidence-state",
        git_runner=runner,
        wall_clock_seconds=10.0,
    )

    assert result["status"] == "delivered"
    assert result["release"]["tag_object"] == tag_object
    assert result["release"]["commit"] == commit
    assert result["release"]["tree"] == tree
    assert proof_budgets == [10.0, pytest.approx(9.7)]
    assert sleeps == [apply_update.PRE_DELIVERY_PROOF_RETRY_BACKOFF_SECONDS]
    assert len(runner.calls) == 1


def test_pre_delivery_proof_does_not_retry_when_429_exhausts_original_deadline(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof_budgets: list[float] = []
    transient = {
        "status": "UNKNOWN",
        "reason": "transient-http-rejection",
        "diagnostic": {"classification": "http-429"},
    }

    def prove_latest_release(
        *_args, wall_clock_seconds: float, **_kwargs
    ) -> dict[str, object]:
        proof_budgets.append(wall_clock_seconds)
        return transient

    moments = iter((100.0, 109.95))
    monkeypatch.setattr(apply_update, "_monotonic", lambda: next(moments), raising=False)
    sleeps: list[float] = []
    monkeypatch.setattr(apply_update, "time", SimpleNamespace(sleep=sleeps.append))
    monkeypatch.setattr(update_verifier, "prove_latest_release", prove_latest_release)

    assert apply_update.deliver_latest_release(
        split_release_fixture["vault"],
        state_root=tmp_path / "evidence-state",
        git_runner=_ScriptedDeliveryFetch(()),
        wall_clock_seconds=10.0,
    ) == {"status": "not-delivered", "evidence": transient}
    assert proof_budgets == [10.0]
    assert sleeps == []


def test_pre_delivery_proof_stops_after_two_http_429_results_without_mutation(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = split_release_fixture["vault"]
    before = _visible_vault_content(vault)
    state_root = tmp_path / "evidence-state"
    proof_budgets: list[float] = []
    transient = {
        "status": "UNKNOWN",
        "reason": "transient-http-rejection",
        "diagnostic": {"classification": "http-429"},
    }

    def prove_latest_release(
        *_args, wall_clock_seconds: float, **_kwargs
    ) -> dict[str, object]:
        proof_budgets.append(wall_clock_seconds)
        return transient

    moments = iter((100.0, 100.2, 100.3))
    monkeypatch.setattr(apply_update, "_monotonic", lambda: next(moments))
    sleeps: list[float] = []
    monkeypatch.setattr(apply_update, "time", SimpleNamespace(sleep=sleeps.append))
    monkeypatch.setattr(update_verifier, "prove_latest_release", prove_latest_release)
    runner = _ScriptedDeliveryFetch(())

    assert apply_update.deliver_latest_release(
        vault,
        state_root=state_root,
        git_runner=runner,
        wall_clock_seconds=10.0,
    ) == {"status": "not-delivered", "evidence": transient}
    assert proof_budgets == [10.0, pytest.approx(9.7)]
    assert sleeps == [apply_update.PRE_DELIVERY_PROOF_RETRY_BACKOFF_SECONDS]
    assert runner.calls == []
    assert _visible_vault_content(vault) == before
    assert not state_root.exists()


def test_pre_delivery_proof_does_not_retry_unclassified_http_5xx(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[float] = []
    evidence = {
        "status": "UNKNOWN",
        "reason": "evidence-invalid",
        "diagnostic": {"classification": "http-503"},
    }

    def prove_latest_release(
        *_args, wall_clock_seconds: float, **_kwargs
    ) -> dict[str, object]:
        calls.append(wall_clock_seconds)
        return evidence

    monkeypatch.setattr(update_verifier, "prove_latest_release", prove_latest_release)

    assert apply_update.deliver_latest_release(
        split_release_fixture["vault"],
        state_root=tmp_path / "evidence-state",
        git_runner=_ScriptedDeliveryFetch(()),
    ) == {"status": "not-delivered", "evidence": evidence}
    assert calls == [10.0]


def test_final_delivery_fetch_does_not_retry_http_429_classification(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = split_release_fixture["vault"]
    _stub_latest_identity(split_release_fixture, monkeypatch)
    before = _visible_vault_content(vault)
    sleeps: list[float] = []
    monkeypatch.setattr(apply_update, "time", SimpleNamespace(sleep=sleeps.append))
    runner = _ScriptedDeliveryFetch(
        (update_verifier.TransientHttpRejectionError(),)
    )

    with pytest.raises(update_verifier.TransientHttpRejectionError):
        apply_update.deliver_latest_release(
            vault,
            state_root=tmp_path / "evidence-state",
            git_runner=runner,
        )

    assert len(runner.calls) == 1
    assert len(runner.budgets) == 1
    assert sleeps == []
    assert _visible_vault_content(vault) == before


def test_final_delivery_fetch_retries_one_transient_offline_failure_with_fresh_budget(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _stub_latest_identity(split_release_fixture, monkeypatch)
    runner = _ScriptedDeliveryFetch(
        (update_verifier.OfflineError("temporary network loss"), None)
    )

    result = apply_update.deliver_latest_release(
        split_release_fixture["vault"],
        state_root=tmp_path / "evidence-state",
        git_runner=runner,
    )

    assert result["status"] == "delivered"
    assert result["release"] == {
        "tag": evidence["tag"],
        "tag_object": evidence["tag_object"],
        "commit": evidence["commit"],
        "tree": evidence["tree"],
        "version": "1.64.0",
        "channel": "stable",
    }
    assert len(runner.calls) == 2
    assert runner.calls[0] == runner.calls[1]
    assert runner.calls[0][1][-2:] == (
        f"refs/tags/{evidence['tag']}:refs/tags/{evidence['tag']}",
        "+refs/heads/release:refs/remotes/upstream/release",
    )
    assert runner.calls[0][2] == {"network": True, "max_output_bytes": 1024}
    assert len(runner.budgets) == 2
    assert runner.budgets[0] is not runner.budgets[1]


def test_final_delivery_fetch_stops_after_two_offline_attempts_without_vault_mutation(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = split_release_fixture["vault"]
    _stub_latest_identity(split_release_fixture, monkeypatch)
    before = _visible_vault_content(vault)
    sleeps: list[float] = []
    monkeypatch.setattr(apply_update, "time", SimpleNamespace(sleep=sleeps.append))
    runner = _ScriptedDeliveryFetch(
        (
            update_verifier.OfflineError("first untrusted detail"),
            update_verifier.OfflineError("second untrusted detail"),
        )
    )

    with pytest.raises(
        update_verifier.OfflineError,
        match="^final release delivery fetch was unavailable after attempt 2$",
    ):
        apply_update.deliver_latest_release(
            vault,
            state_root=tmp_path / "evidence-state",
            git_runner=runner,
            wall_clock_seconds=60.0,
        )

    assert len(runner.calls) == 2
    assert runner.calls[0] == runner.calls[1]
    assert len(runner.budgets) == 2
    assert runner.budgets[0] is not runner.budgets[1]
    assert runner.budgets[1].deadline > runner.budgets[0].deadline
    assert all(
        0
        < budget.deadline - real_time.monotonic()
        <= apply_update.FINAL_FETCH_ATTEMPT_BUDGET_SECONDS
        for budget in runner.budgets
    )
    assert sleeps == [apply_update.FINAL_FETCH_RETRY_BACKOFF_SECONDS]
    assert _visible_vault_content(vault) == before


def test_final_delivery_fetch_does_not_retry_evidence_failure(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_latest_identity(split_release_fixture, monkeypatch)
    sleeps: list[float] = []
    monkeypatch.setattr(apply_update, "time", SimpleNamespace(sleep=sleeps.append))
    runner = _ScriptedDeliveryFetch(
        (update_verifier.EvidenceError("release identity contradicted"),)
    )

    with pytest.raises(update_verifier.EvidenceError, match="release identity contradicted"):
        apply_update.deliver_latest_release(
            split_release_fixture["vault"],
            state_root=tmp_path / "evidence-state",
            git_runner=runner,
        )

    assert len(runner.calls) == 1
    assert len(runner.budgets) == 1
    assert sleeps == []


def test_final_delivery_does_not_fetch_when_origin_verification_fails(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_latest_identity(split_release_fixture, monkeypatch)
    _git(
        split_release_fixture["brain"],
        "remote",
        "set-url",
        "origin",
        "https://example.com/not-dex.git",
    )
    runner = _ScriptedDeliveryFetch((None,))

    with pytest.raises(apply_update.ReleaseVerificationError, match="official Dex repository"):
        apply_update.deliver_latest_release(
            split_release_fixture["vault"],
            state_root=tmp_path / "evidence-state",
            git_runner=runner,
        )

    assert runner.calls == []
    assert runner.budgets == []


def test_final_delivery_does_not_fetch_when_topology_verification_fails(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = split_release_fixture["vault"]
    _stub_latest_identity(split_release_fixture, monkeypatch)
    _write(vault, "System/.dex/topology.json", b"{}\n")
    runner = _ScriptedDeliveryFetch((None,))

    with pytest.raises(apply_update.UpdateError, match="topology is incomplete"):
        apply_update.deliver_latest_release(
            vault,
            state_root=tmp_path / "evidence-state",
            git_runner=runner,
        )

    assert runner.calls == []
    assert runner.budgets == []


def test_final_delivery_does_not_retry_post_fetch_identity_failure(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _stub_latest_identity(split_release_fixture, monkeypatch)
    evidence["tag_object"] = "0" * 40
    sleeps: list[float] = []
    monkeypatch.setattr(apply_update, "time", SimpleNamespace(sleep=sleeps.append))
    runner = _ScriptedDeliveryFetch((None,))

    with pytest.raises(apply_update.ReleaseVerificationError, match="tag object"):
        apply_update.deliver_latest_release(
            split_release_fixture["vault"],
            state_root=tmp_path / "evidence-state",
            git_runner=runner,
        )

    assert len(runner.calls) == 1
    assert len(runner.budgets) == 1
    assert sleeps == []


def test_delivered_release_refuses_any_preview_drift_before_writing(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
) -> None:
    vault = split_release_fixture["vault"]
    release = split_release_fixture["release"]
    brain = split_release_fixture["brain"]
    old_tag, _old_tag_object, old_commit, _old_tree = split_release_fixture["old"]
    del old_tag

    _write(release, "System/.release-evidence-profile.json", legacy_profile_bytes("1.65.0"))
    target_tag, _target_tag_object, target_commit, _target_tree = _commit_release(release, "1.65.0")
    _git(release, "branch", "-f", "release", target_commit)
    _write(vault, "package.json", b'{"name":"dex-test","version":"1.63.0"}\n')
    _write(vault, "System/.release-evidence-profile.json", legacy_profile_bytes("1.63.0"))
    _git(brain, "update-ref", "refs/remotes/upstream/release", old_commit)

    delivered = apply_update.deliver_latest_release(
        vault,
        state_root=tmp_path / "evidence-state",
        remote_url=str(release),
        allow_test_transport=True,
        wall_clock_seconds=60.0,
    )
    assert delivered["status"] == "delivered"
    assert delivered["release"]["tag"] == target_tag
    previewed = service.build_and_preview_delivered_release(vault, delivered["release"])
    _write(vault, "README.md", b"user changed this after preview\n")

    with pytest.raises(PlanRejected, match="approval does not match"):
        service.execute_approved_delivered_release(
            vault,
            previewed["preview"],
            previewed["approval_token"],
        )

    assert (vault / "README.md").read_bytes() == b"user changed this after preview\n"
    assert _git(brain, "rev-parse", "refs/dex/installed") == old_commit


def _equip_with_lifecycle_state(root: Path, version: str) -> None:
    """Give one tree (vault or release) an installed bridge + bound catalog.

    Uses the same ``_refresh_manifest`` the release fixture commits with, so a
    later ``_commit_release`` regenerates byte-identical manifest content and
    the catalog binding stays exact.
    """
    write_bridge_release(root, release_version=version)
    _write(root, "System/.release-catalog.json", b"{}\n")
    _refresh_manifest(root)
    manifest_bytes = (root / "System/.installed-files.manifest").read_bytes()
    document = lifecycle_catalog_document(version, manifest_bytes)
    _write(root, "System/.release-catalog.json", canonical_catalog_bytes(document))


def _deliver_and_preview_equipped_release(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    *,
    vault_version: str = "1.63.0",
    release_version: str = "1.65.0",
    equip_release: bool = True,
) -> tuple[dict[str, object], dict[str, object]]:
    """Deliver and preview a release over a vault with installed lifecycle state."""
    vault = split_release_fixture["vault"]
    release = split_release_fixture["release"]
    brain = split_release_fixture["brain"]
    _old_tag, _old_tag_object, old_commit, _old_tree = split_release_fixture["old"]

    _write(
        release,
        "System/.release-evidence-profile.json",
        legacy_profile_bytes(release_version),
    )
    if equip_release:
        _equip_with_lifecycle_state(release, release_version)
    target = _commit_release(release, release_version)
    split_release_fixture["target"] = target
    _target_tag, _target_tag_object, target_commit, _target_tree = target
    _git(release, "branch", "-f", "release", target_commit)
    _write(
        vault,
        "package.json",
        json.dumps({"name": "dex-test", "version": vault_version}).encode() + b"\n",
    )
    _write(
        vault,
        "System/.release-evidence-profile.json",
        legacy_profile_bytes(vault_version),
    )
    _git(brain, "update-ref", "refs/remotes/upstream/release", old_commit)

    delivered = apply_update.deliver_latest_release(
        vault,
        state_root=tmp_path / "evidence-state",
        remote_url=str(release),
        allow_test_transport=True,
        wall_clock_seconds=60.0,
    )
    assert delivered["status"] == "delivered"
    previewed = service.build_and_preview_delivered_release(vault, delivered["release"])
    return delivered, previewed


def test_delivered_release_clears_superseded_activation_and_next_plan_read_succeeds(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
) -> None:
    """Issue #433: after an update commits, the previous release's activation
    record must not keep refusing gated operations.  The committed apply
    removes the superseded record (declared in the receipt); the next gated
    operation re-records against the newly installed release, stamping the
    running code's own api_version."""
    vault = split_release_fixture["vault"]
    brain = split_release_fixture["brain"]

    _equip_with_lifecycle_state(vault, "1.63.0")
    activation_path = vault / ACTIVATION_RELATIVE
    stale = activate_vault(vault)
    assert stale["bridge_release_version"] == "1.63.0"

    delivered, previewed = _deliver_and_preview_equipped_release(
        split_release_fixture, tmp_path
    )
    target_tag, _target_tag_object, target_commit, _target_tree = split_release_fixture["target"]
    assert delivered["release"]["tag"] == target_tag

    executed = service.execute_approved_delivered_release(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )

    assert executed["receipt"]["transaction_id"]
    assert _git(brain, "rev-parse", "refs/dex/installed") == target_commit

    # The pre-fix #433 failure shape: immediately after the apply the record
    # still named 1.63.0 and every gated operation raised "existing activation
    # belongs to another bridge release".  The committed apply now removes the
    # superseded record and declares that removal in its receipt.
    assert not activation_path.exists() and not activation_path.is_symlink()
    assert ACTIVATION_RELATIVE.as_posix() in executed["receipt"]["declared_paths"]

    # The reported symptom cannot recur: the next gated read succeeds, and the
    # newly installed code records its own activation for the new release.
    plan = service.build_inventory_and_plan(vault)
    assert "plan" in plan
    refreshed = json.loads(activation_path.read_text(encoding="utf-8"))
    assert refreshed["bridge_release_version"] == "1.65.0"
    assert refreshed["activation_version"] == 1
    assert refreshed["api_version"] == service.api_version


def test_delivered_release_commits_even_when_new_release_declarations_are_unreadable(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
) -> None:
    """The engine executing an update is the previous release's code.  It must
    never veto a byte-verified update because it cannot interpret the new
    release's declarations (a future bridge contract, journal schema, or
    activation API); tidy-up reads only the old record's own format."""
    vault = split_release_fixture["vault"]
    release = split_release_fixture["release"]

    _equip_with_lifecycle_state(vault, "1.63.0")
    activation_path = vault / ACTIVATION_RELATIVE
    activate_vault(vault)

    # The new release ships a declaration this engine cannot parse.
    _write(
        release,
        "core/lifecycle/catalog/bridge-release.json",
        b'{"bridge_contract_version": 2, "release_version": "1.65.0", "future_field": true}\n',
    )
    _delivered, previewed = _deliver_and_preview_equipped_release(
        split_release_fixture, tmp_path, equip_release=False
    )

    executed = service.execute_approved_delivered_release(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )

    assert executed["receipt"]["transaction_id"]
    assert (vault / "README.md").read_bytes() == b"new brain\n"
    # The superseded record is still cleared: removal never reads the newly
    # installed release's files.
    assert not activation_path.exists()


def test_delivered_release_commits_when_activation_record_is_corrupt(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
) -> None:
    """A pre-existing corrupt record must not block an update.  It is left in
    place as fail-closed evidence for activation and Doctor to judge."""
    vault = split_release_fixture["vault"]

    _equip_with_lifecycle_state(vault, "1.63.0")
    activation_path = vault / ACTIVATION_RELATIVE
    activation_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt = b'{"activation_version":999}\n'
    activation_path.write_bytes(corrupt)

    _delivered, previewed = _deliver_and_preview_equipped_release(
        split_release_fixture, tmp_path
    )
    executed = service.execute_approved_delivered_release(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )

    assert executed["receipt"]["transaction_id"]
    assert (vault / "README.md").read_bytes() == b"new brain\n"
    assert activation_path.read_bytes() == corrupt
    assert ACTIVATION_RELATIVE.as_posix() not in executed["receipt"]["declared_paths"]
    # Gated operations still fail closed on the corrupt record afterwards.
    with pytest.raises(PlanRejected, match="run /dex-doctor"):
        service.build_inventory_and_plan(vault)


@pytest.mark.parametrize(
    ("failing_seam", "record_survives"),
    [
        # Failure before anything is judged: the record is untouched.
        ("_well_formed_activation", True),
        # Failure after the unlink: the removal itself already happened.
        ("fsync_directory", False),
    ],
)
def test_delivered_release_commits_when_activation_removal_fails(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_seam: str,
    record_survives: bool,
) -> None:
    """Removal is tidy-up, never a gate: any failure inside it must neither
    fail nor roll back the committed update, and must keep the receipt honest."""
    from core.lifecycle import bridge as bridge_module

    vault = split_release_fixture["vault"]

    _equip_with_lifecycle_state(vault, "1.63.0")
    activation_path = vault / ACTIVATION_RELATIVE
    activate_vault(vault)

    _delivered, previewed = _deliver_and_preview_equipped_release(
        split_release_fixture, tmp_path
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated failure during activation tidy-up")

    monkeypatch.setattr(bridge_module, failing_seam, fail)
    executed = service.execute_approved_delivered_release(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )

    assert executed["receipt"]["transaction_id"]
    assert (vault / "README.md").read_bytes() == b"new brain\n"
    assert activation_path.exists() is record_survives
    assert ACTIVATION_RELATIVE.as_posix() not in executed["receipt"]["declared_paths"]


def test_delivered_release_retry_after_finalize_failure_keeps_no_stale_state(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A finalize failure rolls the attempt back without touching the record;
    the retried apply removes it, and the record the next gated operation
    writes reflects the committed vault — never a mid-attempt baseline."""
    vault = split_release_fixture["vault"]

    _equip_with_lifecycle_state(vault, "1.63.0")
    activation_path = vault / ACTIVATION_RELATIVE
    activate_vault(vault)
    record_before = activation_path.read_bytes()

    _delivered, previewed = _deliver_and_preview_equipped_release(
        split_release_fixture, tmp_path
    )

    real_finalize = apply_update._finalize_release_metadata

    def fail_finalize(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated release pin failure")

    monkeypatch.setattr(apply_update, "_finalize_release_metadata", fail_finalize)
    with pytest.raises(RuntimeError, match="simulated release pin failure"):
        service.execute_approved_delivered_release(
            vault,
            previewed["preview"],
            previewed["approval_token"],
        )
    assert activation_path.read_bytes() == record_before

    monkeypatch.setattr(apply_update, "_finalize_release_metadata", real_finalize)
    executed = service.execute_approved_delivered_release(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )
    assert executed["receipt"]["transaction_id"]
    assert not activation_path.exists()

    expected_catalog = load_catalog(
        vault / "System/.release-catalog.json", release_root=vault
    )
    expected_hash = build_inventory(vault, catalog=expected_catalog).to_dict()[
        "inventory_sha256"
    ]
    plan = service.build_inventory_and_plan(vault)
    assert "plan" in plan
    refreshed = json.loads(activation_path.read_text(encoding="utf-8"))
    assert refreshed["bridge_release_version"] == "1.65.0"
    assert refreshed["baseline_inventory_sha256"] == expected_hash


def test_apply_verified_release_clears_superseded_activation(
    split_release_fixture: dict[str, object],
) -> None:
    """The direct apply route shares the post-commit tidy-up, so any future
    caller of apply_verified_release cannot reproduce issue #433."""
    vault = split_release_fixture["vault"]
    activation_path = vault / ACTIVATION_RELATIVE
    activation_path.parent.mkdir(parents=True, exist_ok=True)
    activation_path.write_bytes(
        canonical_json_bytes(
            {
                "activation_version": 1,
                "api_version": service.api_version,
                "bridge_release_version": "1.63.0",
                "baseline_inventory_sha256": "0" * 64,
            }
        )
    )

    result = apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    assert result["committed"] is True
    assert not activation_path.exists()


def test_apply_update_keeps_personal_instructions_when_release_template_changes(
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    custom = b"Always explain decisions plainly."
    _write(vault, "CLAUDE-custom.md", custom)
    _write(
        vault,
        "CLAUDE.md",
        b"# Old instructions\n\nAlways explain decisions plainly.\n\nOld footer.\n",
    )

    result = apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    assert result["committed"] is True
    assert (vault / "CLAUDE.md").read_bytes() == (
        b"# New instructions\n\nAlways explain decisions plainly.\n\r\nNew footer.\n"
    )
    assert "CLAUDE.md" in result["regenerated"]


@pytest.mark.parametrize(
    "malformed_template",
    [
        b"# Broken release\n\nNo markers.\n",
        b"# Broken release\n\n## USER_EXTENSIONS_END\n## USER_EXTENSIONS_START\n",
        (
            b"## USER_EXTENSIONS_START\n## USER_EXTENSIONS_END\n"
            b"## USER_EXTENSIONS_START\n## USER_EXTENSIONS_END\n"
        ),
    ],
)
def test_malformed_claude_template_is_kept_and_current_file_is_untouched(
    split_release_fixture: dict[str, object],
    malformed_template: bytes,
) -> None:
    vault = split_release_fixture["vault"]
    current = b"# Current instructions\n\nNever lose this personal block.\n"
    _write(vault, "CLAUDE-custom.md", b"Never lose this personal block.\n")
    _write(vault, "CLAUDE.md", current)
    _retarget_release(
        split_release_fixture,
        "CLAUDE.md",
        malformed_template,
    )

    result = apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    assert (vault / "CLAUDE.md").read_bytes() == current
    assert "CLAUDE.md" in result["kept"]
    assert "marker" in result["kept_reasons"]["CLAUDE.md"].lower()


def test_update_plan_compares_current_claude_against_composed_bytes(
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    custom = b"Personal instruction without a trailing newline."
    _write(vault, "CLAUDE-custom.md", custom)
    release = _verified(split_release_fixture)
    release_entry = next(entry for entry in release.entries if entry.path == "CLAUDE.md")
    release_blob = apply_update._blob(vault, release.brain_git, release_entry.object_id)
    _write(vault, "CLAUDE.md", apply_update._regenerate_claude(release_blob, custom))

    plan = apply_update.build_update_plan(vault, release)

    assert "CLAUDE.md" not in {entry.relative for entry in plan.entries}
    assert "CLAUDE.md" not in plan.regenerated
    assert "CLAUDE.md" in plan.untouched


@pytest.mark.parametrize("empty_custom_file", [False, True])
def test_absent_or_empty_custom_instructions_use_release_template_as_is(
    split_release_fixture: dict[str, object],
    empty_custom_file: bool,
) -> None:
    vault = split_release_fixture["vault"]
    if empty_custom_file:
        _write(vault, "CLAUDE-custom.md", b"")
    release = _verified(split_release_fixture)
    release_entry = next(entry for entry in release.entries if entry.path == "CLAUDE.md")
    release_blob = apply_update._blob(vault, release.brain_git, release_entry.object_id)

    apply_update.apply_verified_release(vault, release)

    assert (vault / "CLAUDE.md").read_bytes() == release_blob


@pytest.mark.parametrize("unsafe_custom", ["directory", "symlink"])
def test_non_regular_custom_instructions_keep_current_claude_file(
    split_release_fixture: dict[str, object],
    unsafe_custom: str,
) -> None:
    vault = split_release_fixture["vault"]
    current = (vault / "CLAUDE.md").read_bytes()
    custom = vault / "CLAUDE-custom.md"
    if unsafe_custom == "directory":
        custom.mkdir()
    else:
        _write(vault, "custom-target.md", b"must not be followed\n")
        custom.symlink_to(vault / "custom-target.md")

    result = apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    assert (vault / "CLAUDE.md").read_bytes() == current
    assert result["kept_reasons"]["CLAUDE.md"] == (
        "CLAUDE-custom.md is not a regular file"
    )


def test_unreadable_custom_instructions_keep_current_claude_file(
    monkeypatch: pytest.MonkeyPatch,
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    current = (vault / "CLAUDE.md").read_bytes()
    custom = vault / "CLAUDE-custom.md"
    _write(vault, "CLAUDE-custom.md", b"private instructions\n")
    original_read_bytes = Path.read_bytes

    def unreadable(path: Path) -> bytes:
        if path == custom:
            raise PermissionError("simulated unreadable custom file")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", unreadable)

    result = apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    assert (vault / "CLAUDE.md").read_bytes() == current
    assert result["kept_reasons"]["CLAUDE.md"] == "CLAUDE-custom.md is unreadable"


@pytest.mark.parametrize(
    ("template", "custom"),
    [
        (
            b"# Dex\n\n## USER_EXTENSIONS_START\n## USER_EXTENSIONS_END\nAfter.\n",
            b"",
        ),
        (
            b"# Dex\n\n## USER_EXTENSIONS_START trailing\n## USER_EXTENSIONS_END\nAfter.\n",
            b"Personal instruction.",
        ),
        (
            b"# Dex\r\n\r\n## USER_EXTENSIONS_START\r\n## USER_EXTENSIONS_END\r\nAfter.\r\n",
            b"First.\r\nSecond.\r\n",
        ),
        (
            b"# Dex\n## USER_EXTENSIONS_START\n## USER_EXTENSIONS_END\nAfter.\n",
            b"Text that looks like a marker:\n## USER_EXTENSIONS_END\nKeep it.\n",
        ),
    ],
)
def test_python_claude_regeneration_is_byte_identical_to_cjs(
    template: bytes,
    custom: bytes,
) -> None:
    script = """
const fs = require('fs');
const migrator = require('./core/migrations/v1-to-v2-brain-vault-split.cjs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const template = Buffer.from(input.template, 'base64').toString('utf8');
const custom = Buffer.from(input.custom, 'base64').toString('utf8');
process.stdout.write(Buffer.from(migrator.regenerateClaude(template, custom), 'utf8'));
"""
    payload = json.dumps(
        {
            "template": base64.b64encode(template).decode("ascii"),
            "custom": base64.b64encode(custom).decode("ascii"),
        }
    ).encode()
    expected = subprocess.run(
        ["node", "-e", script],
        cwd=REPO_ROOT,
        input=payload,
        check=True,
        capture_output=True,
    ).stdout

    assert apply_update._regenerate_claude(template, custom) == expected


_PROFILE_TEMPLATE = (
    b"# Dex\n\n"
    b"## User Profile\n\n"
    b"<!-- Updated during onboarding -->\n"
    b"**Name:** Not yet configured\n"
    b"**Role:** Not yet configured\n"
    b"**Company Size:** Not yet configured\n"
    b"**Working Style:** Not yet configured\n"
    b"**Pillars:**\n"
    b"- Not yet configured\n\n"
    b"---\n\n"
    b"## USER_EXTENSIONS_START\n"
    b"## USER_EXTENSIONS_END\n\n"
    b"After.\n"
)
_POPULATED_PROFILE = (
    "name: Maya Chen\n"
    "role: Head of Product\n"
    "company_size: scaling (100-1000)\n"
    "working_style: Plain words. Skip the pep talk.\n"
    "communication:\n"
    "  formality: professional_casual\n"
    "pillars:\n"
    "  - name: Revenue\n"
    "  - name: Product\n"
)
_TEMPLATE_DEFAULT_PROFILE = (
    "name: \"\"\n"
    "role: \"\"\n"
    "company_size: \"\"\n"
    "working_style: \"\"\n"
    "communication:\n"
    "  formality: professional_casual\n"
    "pillars: []\n"
)


def _write_profile(vault: Path, content: str) -> None:
    _write(vault, "System/user-profile.yaml", content.encode("utf-8"))


def test_compose_claude_rewrites_user_profile_on_the_shipped_template(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_profile(vault, _POPULATED_PROFILE)

    composed = apply_update._compose_claude(
        (REPO_ROOT / "CLAUDE.md").read_bytes(),
        vault,
    ).decode("utf-8")

    assert "**Name:** Maya Chen" in composed
    assert "**Name:** Not yet configured" not in composed
    assert "## USER_EXTENSIONS_START" in composed


def test_compose_claude_rewrites_user_profile_from_populated_yaml(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_profile(vault, _POPULATED_PROFILE)

    composed = apply_update._compose_claude(_PROFILE_TEMPLATE, vault).decode("utf-8")

    assert "**Name:** Maya Chen" in composed
    assert "**Role:** Head of Product" in composed
    assert "**Company Size:** scaling (100-1000)" in composed
    assert "**Working Style:** Plain words. Skip the pep talk." in composed
    assert "- Revenue\n- Product\n" in composed
    assert "Not yet configured" not in composed
    assert "## USER_EXTENSIONS_START" in composed
    assert "After." in composed


@pytest.mark.parametrize(
    "profile_bytes",
    [
        None,
        b"",
        _TEMPLATE_DEFAULT_PROFILE.encode("utf-8"),
        b"updates:\n  channel: stable\n",
    ],
    ids=["missing", "empty-file", "template-defaults", "channel-only"],
)
def test_compose_claude_keeps_placeholders_when_profile_is_unconfigured(
    tmp_path: Path,
    profile_bytes: bytes | None,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    if profile_bytes is not None:
        _write(vault, "System/user-profile.yaml", profile_bytes)

    composed = apply_update._compose_claude(_PROFILE_TEMPLATE, vault)

    assert composed == _PROFILE_TEMPLATE


def test_compose_claude_splices_custom_block_and_populated_profile(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_profile(vault, _POPULATED_PROFILE)
    _write(vault, "CLAUDE-custom.md", b"Always explain decisions plainly.\n")

    composed = apply_update._compose_claude(_PROFILE_TEMPLATE, vault).decode("utf-8")

    assert "**Name:** Maya Chen" in composed
    assert "Always explain decisions plainly." in composed
    assert "USER_EXTENSIONS_START" not in composed
    assert composed.endswith("After.\n")


def test_compose_claude_does_not_rewrite_user_profile_heading_inside_custom_block(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_profile(vault, _POPULATED_PROFILE)
    _write(
        vault,
        "CLAUDE-custom.md",
        b"## User Profile\n\nThis is mine. Leave it.\n",
    )

    composed = apply_update._compose_claude(_PROFILE_TEMPLATE, vault).decode("utf-8")

    assert composed.count("## User Profile") == 2
    assert "**Name:** Maya Chen" in composed
    assert "This is mine. Leave it." in composed


def test_compose_claude_uses_formality_when_working_style_is_blank(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_profile(
        vault,
        "name: Maya Chen\n"
        "working_style: \"\"\n"
        "communication:\n"
        "  formality: casual\n",
    )

    composed = apply_update._compose_claude(_PROFILE_TEMPLATE, vault).decode("utf-8")

    assert "**Name:** Maya Chen" in composed
    assert "**Working Style:** casual" in composed


def test_apply_update_keeps_populated_user_profile_when_release_template_resets_it(
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    _write_profile(vault, _POPULATED_PROFILE)
    _write(vault, "CLAUDE-custom.md", b"<!-- Add your personal customizations here. -->\n")
    _retarget_release(split_release_fixture, "CLAUDE.md", _PROFILE_TEMPLATE)
    current = (
        b"# Old instructions\n\n"
        b"## User Profile\n\n"
        b"**Name:** Maya Chen\n"
        b"**Role:** Head of Product\n\n"
        b"---\n"
    )
    _write(vault, "CLAUDE.md", current)

    result = apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    composed = (vault / "CLAUDE.md").read_text(encoding="utf-8")
    assert result["committed"] is True
    assert "**Name:** Maya Chen" in composed
    assert "**Role:** Head of Product" in composed
    assert "Not yet configured" not in composed
    assert "<!-- Add your personal customizations here. -->" in composed
    assert "CLAUDE.md" in result["regenerated"]


def test_apply_update_keeps_placeholders_for_unconfigured_profile(
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    _write_profile(vault, _TEMPLATE_DEFAULT_PROFILE)
    _retarget_release(split_release_fixture, "CLAUDE.md", _PROFILE_TEMPLATE)

    result = apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    assert result["committed"] is True
    assert (vault / "CLAUDE.md").read_bytes() == apply_update._compose_claude(
        _PROFILE_TEMPLATE, vault
    )
    assert b"**Name:** Not yet configured" in (vault / "CLAUDE.md").read_bytes()


@pytest.mark.parametrize(
    ("unsafe_profile", "reason"),
    [
        ("directory", "System/user-profile.yaml is not a regular file"),
        ("symlink", "System/user-profile.yaml is not a regular file"),
        ("invalid-yaml", "System/user-profile.yaml is not valid YAML"),
    ],
)
def test_unsafe_user_profile_keeps_current_claude_file(
    split_release_fixture: dict[str, object],
    unsafe_profile: str,
    reason: str,
) -> None:
    vault = split_release_fixture["vault"]
    current = (
        b"# Current instructions\n\n"
        b"## User Profile\n\n"
        b"**Name:** Maya Chen\n\n"
        b"---\n"
    )
    _write(vault, "CLAUDE.md", current)
    _retarget_release(split_release_fixture, "CLAUDE.md", _PROFILE_TEMPLATE)
    profile = vault / "System/user-profile.yaml"
    profile.unlink(missing_ok=True)
    if unsafe_profile == "directory":
        profile.mkdir()
    elif unsafe_profile == "symlink":
        _write(vault, "System/profile-target.yaml", b"name: must-not-follow\n")
        profile.symlink_to(vault / "System/profile-target.yaml")
    else:
        _write(vault, "System/user-profile.yaml", b"name: [unterminated\n")

    result = apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    assert (vault / "CLAUDE.md").read_bytes() == current
    assert result["kept_reasons"]["CLAUDE.md"] == reason


def test_apply_update_verification_failure_restores_every_release_file(
    monkeypatch: pytest.MonkeyPatch,
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    before = {
        relative: (vault / relative).read_bytes()
        for relative in (
            "README.md",
            "core/obsolete.py",
            "03-Tasks/Tasks.md",
            "04-Projects/private.md",
            "System/.dex/release-runtime.json",
        )
    }
    original_verify = apply_update.Transaction._verify_phase

    def fail_after_verify(transaction: apply_update.Transaction) -> None:
        original_verify(transaction)
        raise RuntimeError("simulated final verification failure")

    monkeypatch.setattr(apply_update.Transaction, "_verify_phase", fail_after_verify)

    with pytest.raises(RuntimeError, match="simulated final verification"):
        apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    for relative, content in before.items():
        assert (vault / relative).read_bytes() == content
    assert not (vault / "core/new.py").exists()
    _, _, old_commit, _ = split_release_fixture["old"]
    assert json.loads((vault / "System/.dex/topology.json").read_text())["installedRelease"] == old_commit


def test_release_pinning_failure_rolls_back_file_transaction_under_lock(
    monkeypatch: pytest.MonkeyPatch,
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    before_readme = (vault / "README.md").read_bytes()
    before_obsolete = (vault / "core/obsolete.py").read_bytes()
    lock = vault / "System/.dex/mutation.lock"

    def fail_release_pin(*_args: object, **_kwargs: object) -> None:
        assert lock.is_file(), "release identity finalization must run under the transaction lock"
        raise RuntimeError("simulated release pin failure")

    monkeypatch.setattr(apply_update, "_finalize_release_metadata", fail_release_pin)

    with pytest.raises(RuntimeError, match="simulated release pin failure"):
        apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    assert (vault / "README.md").read_bytes() == before_readme
    assert (vault / "core/obsolete.py").read_bytes() == before_obsolete
    assert not (vault / "core/new.py").exists()


def test_crash_between_apply_and_release_identity_finalize_converges(
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    tag, tag_object, target_commit, tree = split_release_fixture["target"]
    _, _, old_commit, _ = split_release_fixture["old"]
    before = {relative: (vault / relative).read_bytes() for relative in ("README.md", "core/obsolete.py")}
    worker = """
import sys
from pathlib import Path
from core.update.apply_update import apply_verified_release, verify_release_ref
vault = Path(sys.argv[1])
release = verify_release_ref(
    vault,
    tag=sys.argv[2],
    tag_object=sys.argv[3],
    commit=sys.argv[4],
    tree=sys.argv[5],
)
apply_verified_release(vault, release)
"""
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            worker,
            str(vault),
            tag,
            tag_object,
            target_commit,
            tree,
        ],
        cwd=REPO_ROOT,
        env=dict(os.environ, DEX_TX_TEST_STOP_AFTER="before-finalize"),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert process.returncode == 137, process.stderr[-500:]
    outcomes = apply_update.Transaction.resume(vault)

    assert len(outcomes) == 1 and outcomes[0]["resumed"] is True
    assert (vault / "README.md").read_bytes() == before["README.md"]
    assert (vault / "core/obsolete.py").read_bytes() == before["core/obsolete.py"]
    assert not (vault / "core/new.py").exists()
    assert json.loads((vault / "System/.dex/topology.json").read_text())["installedRelease"] == old_commit
    assert json.loads((vault / ".dex/brain.git/dex-brain-v2").read_text())["installed"] == old_commit
    assert _git(vault / ".dex/brain.git", "rev-parse", "refs/dex/installed") == old_commit


def test_update_plan_skips_release_entries_that_already_match_bytes_and_mode(
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    release = _verified(split_release_fixture)
    (vault / "README.md").write_bytes(b"new brain\n")
    (vault / "README.md").chmod(0o644)

    plan = apply_update.build_update_plan(vault, release)

    assert "README.md" not in {entry.relative for entry in plan.entries}
    assert "README.md" not in plan.replaced


def test_apply_update_can_finalize_when_every_release_mutation_already_matches(
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    release = _verified(split_release_fixture)
    for entry in release.entries:
        target = vault / entry.path
        verdict = apply_update.portable_contract.update_write_verdict(
            entry.path,
            exists=target.exists(),
        )
        if not verdict.allowed:
            continue
        content = subprocess.run(
            ["git", f"--git-dir={release.brain_git}", "show", f"{release.commit}:{entry.path}"],
            check=True,
            capture_output=True,
        ).stdout
        _write(vault, entry.path, content, entry.mode)
    (vault / "core/obsolete.py").unlink()

    result = apply_update.apply_verified_release(vault, release)

    assert result["committed"] is True
    assert result["targets"] == []
    assert _git(vault / ".dex/brain.git", "rev-parse", "refs/dex/installed") == release.commit


def _edit_topology(vault: Path, **fields: object) -> None:
    path = vault / "System/.dex/topology.json"
    value = json.loads(path.read_text())
    value.update(fields)
    path.write_text(json.dumps(value, indent=2) + "\n")


def test_relocated_split_is_accepted_and_its_recorded_path_is_re_recorded(
    split_release_fixture: dict[str, object],
) -> None:
    """A moved vault updates, and the install puts its recorded location right.

    The recorded path is an absolute path in local runtime state, so a vault
    that was moved or renamed records somewhere else. Nothing here reads it as a
    path, so it can only ever be a consistency note — and this is the one place
    that legitimately rewrites the marker, so it is where the note is corrected.
    """
    vault: Path = split_release_fixture["vault"]
    _edit_topology(vault, environment={"DEX_VAULT": str(vault.parent / "somewhere-else")})

    # Accepted despite the stale record: the layout itself is sound.
    brain_git, topology, _marker = apply_update._topology(vault)
    assert brain_git == vault / ".dex/brain.git"
    assert topology["environment"]["DEX_VAULT"] != str(vault.resolve())

    release = _verified(split_release_fixture)
    result = apply_update.apply_verified_release(vault, release)

    assert result["committed"] is True
    _, _, target_commit, _ = split_release_fixture["target"]
    rewritten = json.loads((vault / "System/.dex/topology.json").read_text())
    assert rewritten["environment"]["DEX_VAULT"] == str(vault.resolve())
    assert rewritten["installedRelease"] == target_commit
    # Only that one field moved; nothing else in the marker was rewritten.
    assert rewritten["vaultGitDir"] == ".git"
    assert rewritten["brainGitDir"] == ".dex/brain.git"


def test_copied_split_vault_is_accepted_by_the_release_planner(
    split_release_fixture: dict[str, object],
    tmp_path: Path,
) -> None:
    """The duplicate-vault rehearsal: a copy is relocated, not inconsistent."""
    original: Path = split_release_fixture["vault"]
    duplicate = tmp_path / "Documents" / "Dex"
    duplicate.parent.mkdir(parents=True)
    shutil.copytree(original, duplicate, symlinks=True)

    recorded = json.loads((duplicate / "System/.dex/topology.json").read_text())
    assert Path(recorded["environment"]["DEX_VAULT"]) == original.resolve()

    brain_git, _topology, marker = apply_update._topology(duplicate)
    assert brain_git == duplicate / ".dex/brain.git"
    assert marker["role"] == "brain"


def test_an_unmoved_vault_keeps_its_recorded_path_byte_for_byte(
    split_release_fixture: dict[str, object],
) -> None:
    vault: Path = split_release_fixture["vault"]
    release = _verified(split_release_fixture)

    apply_update.apply_verified_release(vault, release)

    rewritten = json.loads((vault / "System/.dex/topology.json").read_text())
    assert rewritten["environment"] == {"DEX_VAULT": str(vault.resolve())}


_PLANNER_BREAKS: tuple[tuple[str, object, str], ...] = (
    (
        "not-a-split",
        lambda vault: _edit_topology(vault, topology="combined"),
        "does not record a brain/vault split",
    ),
    (
        "wrong-vault-git-dir",
        lambda vault: _edit_topology(vault, vaultGitDir=".vault.git"),
        "records vaultGitDir '.vault.git' instead of '.git'",
    ),
    (
        "wrong-brain-git-dir",
        lambda vault: _edit_topology(vault, brainGitDir=".dex/other.git"),
        "records brainGitDir '.dex/other.git' instead of '.dex/brain.git'",
    ),
    (
        "no-recorded-vault-path",
        lambda vault: _edit_topology(vault, environment={}),
        "records no environment.DEX_VAULT path",
    ),
    (
        "non-string-recorded-vault-path",
        lambda vault: _edit_topology(vault, environment={"DEX_VAULT": 7}),
        "records no environment.DEX_VAULT path",
    ),
    (
        "wrong-vault-marker-role",
        lambda vault: _write(vault, ".git/dex-vault-v2", b'{"role":"brain"}\n'),
        "records role 'brain' instead of 'vault'",
    ),
    (
        "wrong-brain-marker-role",
        lambda vault: _write(
            vault,
            ".dex/brain.git/dex-brain-v2",
            b'{"role":"vault","installed":"x"}\n',
        ),
        "records role 'vault' instead of 'brain'",
    ),
    (
        "missing-brain-git",
        lambda vault: (
            (vault / ".dex/brain.git/dex-brain-v2").rename(
                vault / ".dex/dex-brain-v2"
            ),
            shutil.rmtree(vault / ".dex/brain.git"),
            (vault / ".dex/brain.git").mkdir(),
            (vault / ".dex/dex-brain-v2").rename(
                vault / ".dex/brain.git/dex-brain-v2"
            ),
            (vault / ".dex/brain.git").rename(vault / ".dex/brain.git.moved"),
            (vault / ".dex/brain.git").symlink_to(vault / ".dex/brain.git.moved"),
        ),
        "split update refuses a symlinked .dex/brain.git",
    ),
)


@pytest.mark.parametrize(
    ("label", "break_layout", "expected_clause"),
    _PLANNER_BREAKS,
    ids=[entry[0] for entry in _PLANNER_BREAKS],
)
def test_each_broken_split_is_still_refused_by_the_planner_and_names_itself(
    split_release_fixture: dict[str, object],
    label: str,
    break_layout: object,
    expected_clause: str,
) -> None:
    """Only the recorded-path value became tolerable; nothing structural did."""
    vault: Path = split_release_fixture["vault"]
    break_layout(vault)

    with pytest.raises(apply_update.UpdateError) as refusal:
        apply_update._topology(vault)
    assert expected_clause in str(refusal.value)


# --- .gitignore vault-mode composition -------------------------------------


def test_composed_gitignore_appends_contract_derived_vault_section() -> None:
    release_blob = b"# distribution rules\n!core/\n!docs/\n"

    composed = apply_update._compose_gitignore(release_blob, Path("/unused")).decode()

    assert composed.startswith("# distribution rules\n")
    section = composed.split(apply_update.GITIGNORE_SECTION_BEGIN, 1)[1]
    assert apply_update.GITIGNORE_SECTION_END in section
    for expected in ("/docs/", "/scripts/", "/CHANGELOG.md", "/README.md", "/LICENSE"):
        assert f"\n{expected}\n" in section
    # brain dirs with vault-owned children switch to /*-plus-negation form
    assert "\n/core/*\n" in section
    assert "\n!/core/mcp-custom/\n" in section
    assert "\n!/core/mcp-premium/\n" in section
    assert "\n/.claude/*\n" in section
    assert "\n!/.claude/skills-custom/\n" in section
    # a plain dir ignore for core/.claude would make the negations dead rules
    assert "\n/core/\n" not in section
    assert "\n/.claude/\n" not in section


def test_applied_shipped_gitignore_saves_user_files_and_excludes_product_files(
    split_release_fixture: dict[str, object],
) -> None:
    """Install the shipped rules, commit real files, and inspect Git history."""
    release = split_release_fixture["release"]
    vault = split_release_fixture["vault"]
    brain = split_release_fixture["brain"]

    _write(release, ".gitignore", (REPO_ROOT / ".gitignore").read_bytes())
    target = _commit_release(release, "1.65.0")
    split_release_fixture["target"] = target
    _target_tag, _target_tag_object, target_commit, _target_tree = target
    subprocess.run(
        [
            "git",
            f"--git-dir={brain}",
            "fetch",
            "--quiet",
            "--tags",
            str(release),
            f"+{target_commit}:refs/remotes/upstream/release",
        ],
        check=True,
    )

    result = apply_update.apply_verified_release(vault, _verified(split_release_fixture))
    assert result["committed"] is True
    assert ".gitignore" in result["replaced"]

    _git(vault, "init", "--quiet")
    _git(vault, "config", "user.name", "Dex Vault Test")
    _git(vault, "config", "user.email", "vault@example.com")

    user_files = {
        f"{region}/user-note.md" for region in portable_contract.VAULT_REGIONS
    }
    for relative in user_files:
        _write(vault, relative, b"user-owned\n")

    product_files = set(portable_contract.brain_paths_inside_vault_regions())
    assert product_files
    product_files.add("README.md")
    customization = ".claude/skills-custom/mine/SKILL.md"
    secret = ".env"
    for relative in product_files:
        _write(vault, relative, b"release-owned\n")
    _write(vault, customization, b"user customization\n")
    _write(vault, secret, b"API_KEY=never-stage\n")

    _git(vault, "add", "-A", "--", *portable_contract.VAULT_REGIONS)
    _git(vault, "add", "-A", "--", customization)
    _git(vault, "commit", "--quiet", "-m", "save user work")
    committed = set(_git(vault, "show", "--format=", "--name-only", "HEAD").splitlines())

    assert user_files <= committed
    assert customization in committed
    assert product_files.isdisjoint(committed)
    assert secret not in committed

    ignored = set(
        _git(vault, "check-ignore", "--", *sorted(product_files), secret).splitlines()
    )
    assert product_files <= ignored
    assert secret in ignored


def test_composed_gitignore_reincludes_every_vault_region() -> None:
    """The distribution file ignores the PARA folders; a vault must track them.

    Without this the failure is not cosmetic: `git add 04-Projects/` refuses
    outright, so every pathspec-based staging path (the vault-autocommit hook)
    stops committing the user's own work, silently.
    """
    release_blob = b"# distribution rules\n00-Inbox/\n03-Tasks/\n04-Projects/\n"

    composed = apply_update._compose_gitignore(release_blob, Path("/unused")).decode()
    section = composed.split(apply_update.GITIGNORE_SECTION_BEGIN, 1)[1]

    for region in portable_contract.VAULT_REGIONS:
        assert f"\n!/{region}/\n" in section, region

    # the negations must come after the distribution's ignore rules, or they
    # are dead letters: last match wins
    assert composed.index("04-Projects/") < composed.index("!/04-Projects/")


def test_composed_gitignore_reignores_product_files_inside_vault_regions() -> None:
    """The release delivers reference docs into 06-Resources, a vault region.

    Tracking them would put product churn in the user's private history and
    re-dirty the working tree on every update. The re-ignore must come AFTER
    the region negation or last-match keeps them tracked.
    """
    composed = apply_update._compose_gitignore(b"# rules\n", Path("/unused")).decode()
    section = composed.split(apply_update.GITIGNORE_SECTION_BEGIN, 1)[1]

    brain_paths = portable_contract.brain_paths_inside_vault_regions()
    assert brain_paths, "expected product files inside a vault region"

    for path in brain_paths:
        assert f"\n/{path}\n" in section, path
        region = path.split("/", 1)[0]
        # ordering is the whole point: the negation first, the re-ignore after
        assert section.index(f"!/{region}/") < section.index(f"/{path}")


def test_composed_gitignore_leaves_user_files_in_a_vault_region_tracked() -> None:
    """Per-file, not per-directory: a note the user writes stays theirs."""
    composed = apply_update._compose_gitignore(b"# rules\n", Path("/unused")).decode()
    section = composed.split(apply_update.GITIGNORE_SECTION_BEGIN, 1)[1]

    # a blanket directory ignore would sweep up anything the user put alongside
    assert "\n/06-Resources/Dex_System/\n" not in section


def test_composed_gitignore_vault_regions_track_the_contract() -> None:
    """Derived from the contract, so a new region cannot be forgotten here."""
    composed = apply_update._compose_gitignore(b"# rules\n", Path("/unused")).decode()
    section = composed.split(apply_update.GITIGNORE_SECTION_BEGIN, 1)[1]

    emitted = {
        line[2:].rstrip("/")
        for line in section.splitlines()
        if line.startswith("!/") and "/" not in line[2:].rstrip("/")
    }
    assert set(portable_contract.VAULT_REGIONS) <= emitted


def test_composed_gitignore_is_idempotent_and_replaces_stale_section() -> None:
    release_blob = b"# rules\n"
    once = apply_update._compose_gitignore(release_blob, Path("/unused"))
    twice = apply_update._compose_gitignore(once, Path("/unused"))

    assert once == twice
    assert once.decode().count(apply_update.GITIGNORE_SECTION_BEGIN) == 1

    stale = (
        b"# rules\n\n"
        + apply_update.GITIGNORE_SECTION_BEGIN.encode()
        + b"\nstale-entry/\n"
        + apply_update.GITIGNORE_SECTION_END.encode()
        + b"\n"
    )
    recomposed = apply_update._compose_gitignore(stale, Path("/unused")).decode()
    assert "stale-entry/" not in recomposed
    assert recomposed.count(apply_update.GITIGNORE_SECTION_BEGIN) == 1


def test_composed_gitignore_refuses_non_utf8_release_bytes() -> None:
    with pytest.raises(apply_update.CompositionError):
        apply_update._compose_gitignore(b"\xff\xfe", Path("/unused"))


def test_vault_section_assumes_direct_child_exceptions_only() -> None:
    """Guard the contract shape the generator relies on.

    Every vault-owned path nested under a top-level brain directory must be a
    direct child: gitignore cannot re-include a file whose parent directory is
    excluded, so a deeper nesting would need recursive /*-negation chains the
    generator deliberately does not emit. If this fails, extend
    _vault_mode_gitignore_section before changing the contract.
    """
    tops = {
        rule.path
        for rule in portable_contract.RULES
        if rule.ownership == "brain" and "/" not in rule.path
    }
    for rule in portable_contract.RULES:
        if rule.ownership != "vault" or "/" not in rule.path:
            continue
        root = rule.path.split("/", 1)[0]
        if root in tops:
            assert rule.path.count("/") == 1, rule.path
