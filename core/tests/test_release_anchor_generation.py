"""Anchor generation from locally verified tags + the consented write seam.

Red-when-removed coverage for the adversarial-review conditions owned by the
generation lane: C4 (the installed ref is a hint, never a proof root), C5
(one parameterized verification variant, one test per retained check), C6
(generation-time row filtering), C8 (this lane's half: no MCP reach, the
operation is a literal), C9 (preview-bound write discipline + crash
convergence), C10 (receipt rides the same transaction, audit-only), C11
(paths and hashes only — the leak test), and C12 (the release to prove is
derived, never supplied).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from core.lifecycle.customizations import load_release_baseline
from core.lifecycle.inventory import build_inventory
from core.lifecycle.release_anchor import (
    RELEASE_ANCHOR_PATH,
    RELEASE_ANCHOR_RECEIPT_PATH,
)
from core.tests.lifecycle_test_helpers import (
    canonical_json_bytes,
    lifecycle_catalog_document,
)
from core.transaction.engine import PlanRejected, Transaction
from core.update import anchor_generation
from core.update.anchor_generation import (
    AnchorGenerationError,
    generate_release_anchor,
    verify_local_release_tag,
    write_release_anchor,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

FAKE_SECRET = "sk-FAKE-PLANTED-KEY-0123456789abcdef"

BRAIN_FILES = {
    "core/feature.py": b"release feature bytes\n",
    "core/engine.py": b"engine release bytes\n",
    ".claude/hooks/guard.cjs": (
        f'// hook with a planted credential: "{FAKE_SECRET}"\n'.encode()
    ),
}
SEED_FILE = ("03-Tasks/Tasks.md", b"# shipped seed tasks\n")
RUNTIME_FILE = ("System/usage_log.md", b"# shipped usage starter\n")


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


def _release_repo(
    tmp_path: Path,
    *,
    tag_version: str = "1.64.0",
    package_version: str | None = None,
) -> dict[str, object]:
    release = tmp_path / "release"
    release.mkdir()
    _git(release, "init", "--quiet")
    _git(release, "config", "user.name", "Anchor Tests")
    _git(release, "config", "user.email", "anchor@example.com")
    for relative, content in BRAIN_FILES.items():
        _write(release, relative, content)
    _write(release, *SEED_FILE)
    _write(release, *RUNTIME_FILE)
    (release / "package.json").write_text(
        json.dumps({"name": "dex-test", "version": package_version or tag_version}) + "\n"
    )
    _refresh_manifest(release)
    _git(release, "add", "-A")
    _git(release, "commit", "--quiet", "-m", f"release {tag_version}")
    commit = _git(release, "rev-parse", "HEAD")
    tree = _git(release, "rev-parse", "HEAD^{tree}")
    tag = f"dist/release/v{tag_version}-{commit[:7]}"
    _git(release, "tag", "-a", tag, "-m", f"Dex {tag_version}")
    tag_object = _git(release, "rev-parse", f"refs/tags/{tag}")
    manifest_bytes = (release / "System/.installed-files.manifest").read_bytes()
    return {
        "release": release,
        "tag": tag,
        "tag_object": tag_object,
        "commit": commit,
        "tree": tree,
        "manifest_bytes": manifest_bytes,
    }


def _vault_with_brain(
    tmp_path: Path,
    fixture: dict[str, object],
    *,
    claimed_version: str = "1.64.0",
) -> Path:
    release = fixture["release"]
    commit = fixture["commit"]
    vault = tmp_path / "vault"
    vault.mkdir()
    manifest_bytes = fixture["manifest_bytes"]
    for line in manifest_bytes.decode("utf-8").splitlines():
        raw = subprocess.run(
            ["git", "-C", str(release), "show", f"{commit}:{line}"],
            check=True,
            capture_output=True,
        ).stdout
        _write(vault, line, raw)
    _write(
        vault,
        "System/.release-catalog.json",
        canonical_json_bytes(lifecycle_catalog_document(claimed_version, manifest_bytes)),
    )
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
            f"+{commit}:refs/dex/installed",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            f"--git-dir={brain}",
            "remote",
            "add",
            "origin",
            "https://github.com/davekilleen/Dex.git",
        ],
        check=True,
    )
    _write(vault, ".git/dex-vault-v2", b'{"role":"vault"}\n')
    _write(
        vault,
        ".dex/brain.git/dex-brain-v2",
        (json.dumps({"role": "brain", "installed": commit}) + "\n").encode(),
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
                    "installedRelease": commit,
                    "environment": {"DEX_VAULT": str(vault.resolve())},
                }
            )
            + "\n"
        ).encode(),
    )
    return vault


@pytest.fixture
def anchored(tmp_path: Path) -> dict[str, object]:
    fixture = _release_repo(tmp_path)
    fixture["vault"] = _vault_with_brain(tmp_path, fixture)
    fixture["brain"] = fixture["vault"] / ".dex/brain.git"
    return fixture


# ---------------------------------------------------------------------------
# Generation: rows come only from the tag-verified tree, brain paths only.
# ---------------------------------------------------------------------------


def test_generation_proves_brain_rows_and_skips_seed_and_runtime(anchored) -> None:
    generation = generate_release_anchor(anchored["vault"])

    assert generation.tag == anchored["tag"]
    assert generation.tag_object == anchored["tag_object"]
    assert generation.commit == anchored["commit"]
    assert generation.tree == anchored["tree"]
    files = generation.document["files"]
    for relative, content in BRAIN_FILES.items():
        assert files[relative] == hashlib.sha256(content).hexdigest()
    assert "package.json" in files  # brain-classified shipped file
    # C6, generation-time half: the user's living seed and runtime paths are
    # never hashed into rows. Deleting the ownership filter turns this red.
    assert SEED_FILE[0] not in files
    assert RUNTIME_FILE[0] not in files
    assert "System/.installed-files.manifest" not in files  # generated-class
    assert generation.row_count == len(files)
    assert generation.skipped_non_brain > 0
    assert (
        hashlib.sha256(generation.canonical_bytes).hexdigest() == generation.document_sha256
    )
    # Generation writes nothing.
    assert not (anchored["vault"] / RELEASE_ANCHOR_PATH).exists()


def test_generated_and_written_anchor_verifies_end_to_end(anchored) -> None:
    vault = anchored["vault"]
    generation = generate_release_anchor(vault)

    result = write_release_anchor(
        vault, generation, previewed_sha256=generation.document_sha256
    )

    assert result["committed"] is True
    anchor_target = vault / RELEASE_ANCHOR_PATH
    receipt_target = vault / RELEASE_ANCHOR_RECEIPT_PATH
    assert anchor_target.read_bytes() == generation.canonical_bytes
    assert stat.S_IMODE(anchor_target.stat().st_mode) == 0o600
    assert stat.S_IMODE(receipt_target.stat().st_mode) == 0o600

    baseline = load_release_baseline(vault)
    assert baseline.identity_state == "VERIFIED"
    assert baseline.anchor_state == "verified"
    assert baseline.errors == ()
    entries = {entry.actual_path: entry for entry in build_inventory(vault).entries}
    assert entries["core/engine.py"].release_state == "stock-unmodified"
    assert entries[".claude/hooks/guard.cjs"].release_state == "stock-unmodified"
    assert entries[SEED_FILE[0]].release_state == "canonical-customization"
    assert entries[RUNTIME_FILE[0]].release_state == "durable-state"

    # A local modification of an anchor-proved file is a divergence.
    _write(vault, "core/engine.py", b"locally changed\n")
    modified = {entry.actual_path: entry for entry in build_inventory(vault).entries}
    assert modified["core/engine.py"].release_state == "stock-modified"


def test_regeneration_carries_expected_current_and_succeeds(anchored) -> None:
    vault = anchored["vault"]
    first = generate_release_anchor(vault)
    write_release_anchor(vault, first, previewed_sha256=first.document_sha256)

    second = generate_release_anchor(vault)
    assert second.replaces_sha256 == hashlib.sha256(first.canonical_bytes).hexdigest()
    assert second.replaces_receipt_sha256 is not None
    write_release_anchor(vault, second, previewed_sha256=second.document_sha256)

    assert (vault / RELEASE_ANCHOR_PATH).read_bytes() == second.canonical_bytes


# ---------------------------------------------------------------------------
# C4 — refs/dex/installed is a HINT, never a proof root.
# ---------------------------------------------------------------------------


def _craft_tampered_installed_ref(anchored) -> str:
    """Commit a tree with the SAME manifest blob but tampered brain bytes,
    repoint refs/dex/installed at it, and never tag it."""
    release = anchored["release"]
    brain = anchored["brain"]
    _write(release, "core/engine.py", b"TAMPERED = True\n")
    # The manifest lists paths only, so it is unchanged — exactly the F1
    # attack shape from review §2.4.
    _git(release, "add", "-A")
    _git(release, "commit", "--quiet", "-m", "crafted local commit")
    crafted = _git(release, "rev-parse", "HEAD")
    subprocess.run(
        [
            "git",
            f"--git-dir={brain}",
            "fetch",
            "--quiet",
            str(release),
            f"+{crafted}:refs/dex/installed",
        ],
        check=True,
    )
    return crafted


def test_crafted_installed_ref_with_official_tag_never_blesses_tampered_bytes(
    anchored,
) -> None:
    _craft_tampered_installed_ref(anchored)

    generation = generate_release_anchor(anchored["vault"])

    # Rows come from the TAG-verified tree: the tamper is not blessed.
    assert generation.commit == anchored["commit"]
    assert generation.document["files"]["core/engine.py"] == hashlib.sha256(
        BRAIN_FILES["core/engine.py"]
    ).hexdigest()


def test_crafted_installed_ref_without_official_tag_produces_no_anchor(
    anchored,
) -> None:
    _craft_tampered_installed_ref(anchored)
    subprocess.run(
        [
            "git",
            f"--git-dir={anchored['brain']}",
            "update-ref",
            "-d",
            f"refs/tags/{anchored['tag']}",
        ],
        check=True,
    )

    with pytest.raises(AnchorGenerationError, match="no local source verifies"):
        generate_release_anchor(anchored["vault"])

    assert not (anchored["vault"] / RELEASE_ANCHOR_PATH).exists()


# ---------------------------------------------------------------------------
# C5 — one red-when-removed test per retained check of the variant.
# ---------------------------------------------------------------------------


def _verify(anchored, **overrides):
    arguments = {
        "git_dir": anchored["brain"],
        "tag": anchored["tag"],
        "claimed_version": "1.64.0",
        "installed_manifest_bytes": anchored["manifest_bytes"],
    }
    arguments.update(overrides)
    return verify_local_release_tag(anchored["vault"], **arguments)


def test_variant_verifies_the_real_local_tag(anchored) -> None:
    source = _verify(anchored)

    assert source.commit == anchored["commit"]
    assert source.tree == anchored["tree"]
    assert source.version == "1.64.0"


def test_variant_refuses_a_non_official_origin(anchored) -> None:
    subprocess.run(
        [
            "git",
            f"--git-dir={anchored['brain']}",
            "remote",
            "set-url",
            "origin",
            "https://github.com/evil/Dex.git",
        ],
        check=True,
    )

    with pytest.raises(AnchorGenerationError, match="official Dex repository"):
        _verify(anchored)
    with pytest.raises(AnchorGenerationError, match="no local source verifies"):
        generate_release_anchor(anchored["vault"])


def test_variant_refuses_a_non_dist_release_tag_name(anchored) -> None:
    with pytest.raises(AnchorGenerationError, match="immutable dist/release"):
        _verify(anchored, tag="release-v1.64.0")


def test_variant_refuses_a_tag_that_does_not_carry_the_claimed_version(
    anchored,
) -> None:
    # The REPLACED check: version-equality against the installed catalog's
    # claim (instead of channel-head equality). Deleting it would let the
    # 1.64.0 tag verify for a vault claiming 1.63.0.
    with pytest.raises(AnchorGenerationError, match="claimed version"):
        _verify(anchored, claimed_version="1.63.0")


def test_variant_refuses_a_lightweight_tag(anchored) -> None:
    subprocess.run(
        [
            "git",
            f"--git-dir={anchored['brain']}",
            "update-ref",
            f"refs/tags/{anchored['tag']}",
            anchored["commit"],
        ],
        check=True,
    )

    with pytest.raises(AnchorGenerationError, match="not annotated"):
        _verify(anchored)


def test_variant_refuses_a_tag_object_contradicting_its_own_headers(anchored) -> None:
    payload = (
        f"object {anchored['commit']}\n"
        "type commit\n"
        "tag dist/release/v9.9.9-0000000\n"
        "tagger Anchor Tests <anchor@example.com> 1750000000 +0000\n"
        "\n"
        "crafted\n"
    )
    crafted = subprocess.run(
        ["git", f"--git-dir={anchored['brain']}", "hash-object", "-t", "tag", "-w", "--stdin"],
        input=payload,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            f"--git-dir={anchored['brain']}",
            "update-ref",
            f"refs/tags/{anchored['tag']}",
            crafted,
        ],
        check=True,
    )

    with pytest.raises(AnchorGenerationError, match="contradicts its own headers"):
        _verify(anchored)


def test_variant_refuses_a_tag_suffix_that_does_not_pin_the_commit(anchored) -> None:
    release = anchored["release"]
    bad_short = "0000000" if not anchored["commit"].startswith("0000000") else "1111111"
    bad_tag = f"dist/release/v1.64.0-{bad_short}"
    _git(release, "tag", "-a", bad_tag, "-m", "bad suffix", anchored["commit"])
    subprocess.run(
        [
            "git",
            f"--git-dir={anchored['brain']}",
            "fetch",
            "--quiet",
            "--tags",
            str(release),
        ],
        check=True,
    )

    with pytest.raises(AnchorGenerationError, match="does not pin the full release commit"):
        _verify(anchored, tag=bad_tag)


def test_variant_refuses_a_tree_that_does_not_reproduce_the_installed_manifest(
    anchored,
) -> None:
    # One byte of installed-manifest drift and the tag proves nothing.
    drifted = anchored["manifest_bytes"] + b"zzz/extra.md\n"

    with pytest.raises(AnchorGenerationError, match="installed manifest"):
        _verify(anchored, installed_manifest_bytes=drifted)


def test_variant_refuses_a_tree_whose_manifest_contradicts_the_tree(
    tmp_path: Path,
) -> None:
    fixture = _release_repo(tmp_path)
    release = fixture["release"]
    # Craft a second release whose manifest omits a tree file.
    manifest = release / "System/.installed-files.manifest"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    broken = "".join(f"{line}\n" for line in lines if line != "core/engine.py")
    manifest.write_text(broken, encoding="utf-8")
    _git(release, "add", "-A")
    _git(release, "commit", "--quiet", "-m", "broken manifest")
    commit = _git(release, "rev-parse", "HEAD")
    tag = f"dist/release/v1.64.0-{commit[:7]}"
    _git(release, "tag", "-a", tag, "-m", "broken")
    fixture.update(
        {
            "commit": commit,
            "tree": _git(release, "rev-parse", "HEAD^{tree}"),
            "tag": tag,
            "manifest_bytes": broken.encode(),
        }
    )
    fixture["vault"] = _vault_with_brain(tmp_path, fixture)
    fixture["brain"] = fixture["vault"] / ".dex/brain.git"

    with pytest.raises(AnchorGenerationError, match="release tree does not verify"):
        _verify(fixture)


def test_variant_refuses_a_package_version_contradicting_the_tag(tmp_path: Path) -> None:
    fixture = _release_repo(tmp_path, tag_version="1.64.0", package_version="1.99.0")
    fixture["vault"] = _vault_with_brain(tmp_path, fixture)
    fixture["brain"] = fixture["vault"] / ".dex/brain.git"

    with pytest.raises(AnchorGenerationError, match="package version contradicts"):
        _verify(fixture)
    with pytest.raises(AnchorGenerationError, match="no local source verifies"):
        generate_release_anchor(fixture["vault"])


# ---------------------------------------------------------------------------
# C12 — the release to prove is derived, never supplied.
# ---------------------------------------------------------------------------


def test_generation_accepts_no_version_or_tag_argument() -> None:
    import inspect

    parameters = inspect.signature(generate_release_anchor).parameters

    assert list(parameters) == ["vault_root"]


def test_claim_mismatch_yields_no_anchor(tmp_path: Path) -> None:
    fixture = _release_repo(tmp_path)
    vault = _vault_with_brain(tmp_path, fixture, claimed_version="1.63.0")

    # The installed catalog claims 1.63.0; only an official 1.64.0 tag exists
    # locally. Nothing substitutes the claim, so no anchor is generated.
    with pytest.raises(AnchorGenerationError, match="v1.63.0"):
        generate_release_anchor(vault)


# ---------------------------------------------------------------------------
# C9 — write discipline: preview-bound digest, preview-time preconditions,
# and crash convergence at every seam.
# ---------------------------------------------------------------------------


def test_write_refuses_bytes_that_do_not_match_the_previewed_digest(anchored) -> None:
    vault = anchored["vault"]
    generation = generate_release_anchor(vault)

    with pytest.raises(AnchorGenerationError, match="previewed digest"):
        write_release_anchor(vault, generation, previewed_sha256="7" * 64)

    assert not (vault / RELEASE_ANCHOR_PATH).exists()
    assert not (vault / RELEASE_ANCHOR_RECEIPT_PATH).exists()


def test_anchor_appearing_between_preview_and_write_aborts(anchored) -> None:
    vault = anchored["vault"]
    generation = generate_release_anchor(vault)
    _write(vault, RELEASE_ANCHOR_PATH, b"{} appeared after the preview\n")

    with pytest.raises(PlanRejected):
        write_release_anchor(vault, generation, previewed_sha256=generation.document_sha256)

    # The existing file wins, byte-identical.
    assert (vault / RELEASE_ANCHOR_PATH).read_bytes() == b"{} appeared after the preview\n"
    assert not (vault / RELEASE_ANCHOR_RECEIPT_PATH).exists()


def test_anchor_changing_between_preview_and_write_aborts(anchored) -> None:
    vault = anchored["vault"]
    first = generate_release_anchor(vault)
    write_release_anchor(vault, first, previewed_sha256=first.document_sha256)
    second = generate_release_anchor(vault)
    _write(vault, RELEASE_ANCHOR_PATH, b"{} changed after the preview\n", 0o600)

    with pytest.raises(PlanRejected):
        write_release_anchor(vault, second, previewed_sha256=second.document_sha256)

    assert (vault / RELEASE_ANCHOR_PATH).read_bytes() == b"{} changed after the preview\n"


@pytest.mark.parametrize(
    "seam",
    (
        "after-begin",
        "after-snapshot",
        "mid-apply:0",
        "mid-apply:1",
        "after-apply",
        "after-verify",
        "after-commit-record",
    ),
)
def test_write_fault_injection_converges_anchor_and_receipt_together(
    seam: str, anchored
) -> None:
    vault = anchored["vault"]
    expected = generate_release_anchor(vault).canonical_bytes
    script = (
        "from pathlib import Path\n"
        "import sys\n"
        "from core.update.anchor_generation import (\n"
        "    generate_release_anchor, write_release_anchor)\n"
        "vault = Path(sys.argv[1])\n"
        "generation = generate_release_anchor(vault)\n"
        "write_release_anchor(vault, generation,\n"
        "    previewed_sha256=generation.document_sha256,\n"
        "    clock=lambda: 1750000000)\n"
    )
    environment = os.environ.copy()
    environment["DEX_TX_TEST_STOP_AFTER"] = seam
    environment["PYTHONPATH"] = str(REPO_ROOT)

    child = subprocess.run(
        [sys.executable, "-c", script, str(vault)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert child.returncode == 137, child.stderr

    Transaction.resume(vault)

    anchor_target = vault / RELEASE_ANCHOR_PATH
    receipt_target = vault / RELEASE_ANCHOR_RECEIPT_PATH
    presence = (anchor_target.exists(), receipt_target.exists())
    assert presence in {(True, True), (False, False)}
    if presence == (True, True):
        assert anchor_target.read_bytes() == expected
        receipt = json.loads(receipt_target.read_text(encoding="utf-8"))
        assert receipt["document_sha256"] == hashlib.sha256(expected).hexdigest()


# ---------------------------------------------------------------------------
# C11 — the leak test: a planted credential appears in no anchor or receipt.
# ---------------------------------------------------------------------------


def test_planted_secret_never_reaches_anchor_or_receipt(anchored) -> None:
    vault = anchored["vault"]
    generation = generate_release_anchor(vault)
    write_release_anchor(vault, generation, previewed_sha256=generation.document_sha256)

    secret = FAKE_SECRET.encode()
    assert secret in (vault / ".claude/hooks/guard.cjs").read_bytes()
    assert secret not in generation.canonical_bytes
    assert secret not in (vault / RELEASE_ANCHOR_PATH).read_bytes()
    assert secret not in (vault / RELEASE_ANCHOR_RECEIPT_PATH).read_bytes()


# ---------------------------------------------------------------------------
# C8, this lane's half — no MCP reach; the operation value is a literal that
# no argument, plan file, or anchor content can supply.
# ---------------------------------------------------------------------------


def test_no_mcp_server_references_the_anchor_write_or_generation_path() -> None:
    forbidden = (
        "anchor_generation",
        "generate_release_anchor",
        "write_release_anchor",
        "release_anchor",
        "release-anchor",
        "reanchor",
        "reanchor_cli",
    )
    for source_file in sorted((REPO_ROOT / "core/mcp").glob("*.py")):
        source = source_file.read_text(encoding="utf-8")
        hits = [name for name in forbidden if name in source]
        assert not hits, f"{source_file.name} references {hits}"


def test_operation_value_is_a_hardcoded_literal_not_an_argument() -> None:
    import inspect

    source = Path(anchor_generation.__file__).read_text(encoding="utf-8")
    assert 'operation="release-anchor"' in source

    write_parameters = inspect.signature(write_release_anchor).parameters
    generate_parameters = inspect.signature(generate_release_anchor).parameters
    assert "operation" not in write_parameters
    assert "operation" not in generate_parameters
