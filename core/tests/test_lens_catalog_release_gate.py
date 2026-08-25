"""The release gates that make the signed Lens catalogue load-bearing.

Two rules are enforced here, both stated in docs/dex-lens-catalog-release-contract.md:

1. A release must carry `dex-lens-catalog-v<version>.json`, and its signature must
   verify under the release key. heydex.ai pulls and verifies that asset within
   minutes of a release; a missing or unverifiable one strands every Lens user on
   the previous catalogue.
2. A registry entry whose content changes must move its `changed_in_release`
   stamp. A stamp nothing checks goes stale exactly the way the source pins did.

Every signature here is made with a key generated inside the test and discarded
with it. The release key exists only as a CI secret and is never used by tests.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts/generate-dex-lens-catalog.py"
ASSET_GATE = REPO_ROOT / "scripts/check-lens-catalog-release-asset.py"
STAMP_GATE = REPO_ROOT / "scripts/check-lens-catalog-change-stamps.py"
RELEASE_VERSION = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))["version"]
ASSET_NAME = f"dex-lens-catalog-v{RELEASE_VERSION}.json"
KEY_ENV = "DEX_LENS_TEST_KEY"


def _key_b64() -> str:
    private_pem = Ed25519PrivateKey.generate().private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    )
    return base64.b64encode(private_pem).decode("ascii")


def _sign_release_catalogue(output_dir: Path, key_b64: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(REPO_ROOT),
            "--output-dir",
            str(output_dir),
            "--issued-at",
            "2026-08-11T12:00:00Z",
            "--sign",
            "--signing-key-env",
            KEY_ENV,
            "--key-id",
            "dex-core-lens-1",
        ],
        cwd=REPO_ROOT,
        env={KEY_ENV: key_b64},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture(name="signing_key")
def _signing_key() -> str:
    return _key_b64()


@pytest.fixture(name="signed_dist")
def _signed_dist(tmp_path: Path, signing_key: str) -> Path:
    """The real registry, signed exactly as the release job signs it."""
    dist = tmp_path / "dist"
    _sign_release_catalogue(dist, signing_key)
    return dist


def _gate(dist: Path, key_b64: str | None, *, version: str = RELEASE_VERSION) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ASSET_GATE),
            "--version",
            version,
            "--dist",
            str(dist),
            "--signing-key-env",
            KEY_ENV,
        ],
        cwd=REPO_ROOT,
        env={KEY_ENV: key_b64} if key_b64 else {},
        capture_output=True,
        text=True,
    )


def _rewrite(dist: Path, envelope: dict, *, refresh_checksum: bool = True, canonical: bool = True) -> None:
    """Put an altered envelope back on disk the way a release would carry it."""
    import hashlib

    if canonical:
        text = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    else:
        text = json.dumps(envelope, indent=2) + "\n"
    data = text.encode("utf-8")
    (dist / ASSET_NAME).write_bytes(data)
    if refresh_checksum:
        (dist / f"{ASSET_NAME}.sha256").write_text(
            f"{hashlib.sha256(data).hexdigest()}  {ASSET_NAME}\n", encoding="utf-8"
        )


def _envelope(dist: Path) -> dict:
    return json.loads((dist / ASSET_NAME).read_text(encoding="utf-8"))


def test_a_correctly_signed_release_catalogue_passes_the_gate(signed_dist: Path, signing_key: str) -> None:
    """Positive control: without this, every refusal below could pass vacuously."""
    result = _gate(signed_dist, signing_key)

    assert result.returncode == 0, result.stderr
    assert "verifies under key dex-core-lens-1" in result.stdout


def test_a_release_without_the_catalogue_asset_is_refused(tmp_path: Path, signing_key: str) -> None:
    empty = tmp_path / "dist"
    empty.mkdir()

    result = _gate(empty, signing_key)

    assert result.returncode == 1
    assert "the signed Lens catalogue is missing" in result.stderr


def test_an_unsigned_catalogue_is_refused(signed_dist: Path, signing_key: str) -> None:
    """The producer writes an empty signature when --sign is not passed."""
    envelope = _envelope(signed_dist)
    envelope["signature"] = ""
    _rewrite(signed_dist, envelope)

    result = _gate(signed_dist, signing_key)

    assert result.returncode == 1
    assert "unsigned" in result.stderr


def test_a_catalogue_signed_by_another_key_is_refused(signed_dist: Path) -> None:
    result = _gate(signed_dist, _key_b64())

    assert result.returncode == 1
    assert "does not verify under the release signing key" in result.stderr


def test_a_catalogue_altered_after_signing_is_refused(signed_dist: Path, signing_key: str) -> None:
    """The exact attack the signature exists to stop: same key, edited content."""
    envelope = _envelope(signed_dist)
    envelope["catalogue"]["capabilities"][0]["value"] = "Something the publisher never said."
    _rewrite(signed_dist, envelope)

    result = _gate(signed_dist, signing_key)

    assert result.returncode == 1
    assert "does not verify under the release signing key" in result.stderr


def test_a_catalogue_that_lost_a_contract_field_is_refused(signed_dist: Path, signing_key: str) -> None:
    """The wire contract is checked before the signature, so the reason is the real one."""
    envelope = _envelope(signed_dist)
    del envelope["catalogue"]["capabilities"][0]["changed_in_release"]
    _rewrite(signed_dist, envelope)

    result = _gate(signed_dist, signing_key)

    assert result.returncode == 1
    assert "violates the vendored wire schema" in result.stderr
    assert "changed_in_release" in result.stderr


def test_a_catalogue_stamped_for_another_release_is_refused(signed_dist: Path, signing_key: str) -> None:
    envelope = _envelope(signed_dist)
    envelope["metadata"]["core_release"] = "v0.0.1"
    _rewrite(signed_dist, envelope)

    result = _gate(signed_dist, signing_key)

    assert result.returncode == 1
    assert "not this release" in result.stderr


def test_a_catalogue_that_does_not_match_its_checksum_is_refused(signed_dist: Path, signing_key: str) -> None:
    envelope = _envelope(signed_dist)
    envelope["catalogue"]["capabilities"][0]["value"] = "Edited without refreshing the sidecar."
    _rewrite(signed_dist, envelope, refresh_checksum=False)

    result = _gate(signed_dist, signing_key)

    assert result.returncode == 1
    assert "does not match" in result.stderr


def test_a_reserialised_catalogue_is_refused(signed_dist: Path, signing_key: str) -> None:
    """Pretty-printing the file keeps the same meaning and breaks the signature.

    Reported as rewritten bytes rather than as a signature failure, because that
    is the difference between "someone reformatted this" and "this is not ours".
    """
    _rewrite(signed_dist, _envelope(signed_dist), canonical=False)

    result = _gate(signed_dist, signing_key)

    assert result.returncode == 1
    assert "not the producer's canonical output" in result.stderr


def test_the_gate_fails_closed_when_no_verifying_key_is_available(signed_dist: Path) -> None:
    """A missing key must never read as a pass."""
    result = _gate(signed_dist, None)

    assert result.returncode == 1
    assert "no verifying key available" in result.stderr


# --------------------------------------------------------------------------- #
# The change-stamp gate
# --------------------------------------------------------------------------- #

CHANGELOG = "# Changelog\n\n## [1.96.9]\n\n## [1.96.8]\n\n## [1.80.0]\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _stamp_repo(tmp_path: Path) -> Path:
    """A miniature repository whose base branch already carries stamped entries."""
    repo = tmp_path / "repo"
    (repo / "core/lens-catalog").mkdir(parents=True)
    registry = {
        "registry_version": 1,
        "catalog_version": 1,
        "jobs": [{"job_id": "plan-my-day", "title": "Plan my day", "description": "One realistic plan."}],
        "entries": [
            {
                "id": "daily-plan",
                "value": "Helps a person choose what matters today.",
                "since_release": "1.80.0",
                "changed_in": [],
                "changed_in_release": "1.96.8",
            },
            {
                "id": "week-plan",
                "value": "Helps a person shape the week.",
                "since_release": "1.80.0",
                "changed_in": [],
                "changed_in_release": "1.96.8",
            },
        ],
    }
    (repo / "core/lens-catalog/registry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")
    (repo / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (repo / "package.json").write_text('{"version":"1.96.8"}\n', encoding="utf-8")
    _git(repo, "init", "--initial-branch", "main")
    _git(repo, "config", "user.email", "gate@example.com")
    _git(repo, "config", "user.name", "Gate Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "change")
    return repo


def _edit_registry(repo: Path, mutate) -> None:
    path = repo / "core/lens-catalog/registry.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    mutate(registry)
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def _stamp_gate(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(STAMP_GATE), "--base-ref", "main"],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def test_editing_an_entry_without_restamping_it_is_refused(tmp_path: Path) -> None:
    repo = _stamp_repo(tmp_path)
    _edit_registry(repo, lambda r: r["entries"][0].update(value="Rewritten value, same old stamp."))

    result = _stamp_gate(repo)

    assert result.returncode == 1
    assert "daily-plan: content changed but changed_in_release still says 1.96.8" in result.stderr
    assert "week-plan" not in result.stderr
    # The message names the release to use, so the fix needs no archaeology.
    assert '"changed_in_release": "1.96.9"' in result.stderr


def test_editing_an_entry_and_restamping_it_passes(tmp_path: Path) -> None:
    repo = _stamp_repo(tmp_path)

    def mutate(registry: dict) -> None:
        registry["entries"][0].update(value="Rewritten value.", changed_in_release="1.96.9")

    _edit_registry(repo, mutate)

    result = _stamp_gate(repo)

    assert result.returncode == 0, result.stderr
    assert "change stamps are current" in result.stdout


def test_restamping_alone_is_not_treated_as_a_content_change(tmp_path: Path) -> None:
    """Stamp fields are excluded from the comparison, so a restamp cannot loop."""
    repo = _stamp_repo(tmp_path)
    _edit_registry(repo, lambda r: r["entries"][0].update(changed_in_release="1.96.9"))

    result = _stamp_gate(repo)

    assert result.returncode == 0, result.stderr


def test_a_stamp_that_moves_backwards_is_refused(tmp_path: Path) -> None:
    repo = _stamp_repo(tmp_path)

    def mutate(registry: dict) -> None:
        registry["entries"][0].update(value="Rewritten value.", changed_in_release="1.80.0")

    _edit_registry(repo, mutate)

    result = _stamp_gate(repo)

    assert result.returncode == 1
    assert "moved backwards" in result.stderr


def test_a_new_entry_needs_no_prior_stamp(tmp_path: Path) -> None:
    repo = _stamp_repo(tmp_path)
    _edit_registry(
        repo,
        lambda r: r["entries"].append(
            {
                "id": "triage",
                "value": "Clears the inbox.",
                "since_release": "1.96.9",
                "changed_in": [],
                "changed_in_release": "1.96.9",
            }
        ),
    )

    result = _stamp_gate(repo)

    assert result.returncode == 0, result.stderr


def test_a_dropped_stamp_is_refused(tmp_path: Path) -> None:
    repo = _stamp_repo(tmp_path)
    _edit_registry(repo, lambda r: r["entries"][0].pop("changed_in_release"))

    result = _stamp_gate(repo)

    assert result.returncode == 1
    assert "changed_in_release is missing" in result.stderr


def test_the_shipped_registry_passes_its_own_stamp_gate() -> None:
    """The gate runs on this repository, not only on fixtures."""
    result = subprocess.run(
        [sys.executable, str(STAMP_GATE)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
