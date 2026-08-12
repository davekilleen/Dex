"""Dex Lens catalog producer gates."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts/generate-dex-lens-catalog.py"
REAL_REGISTRY = REPO_ROOT / "core/lens-catalog/registry.json"


def _signed_payload(envelope: dict) -> str:
    return json.dumps(
        {"metadata": envelope["metadata"], "catalogue": envelope["catalogue"]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _skill(root: Path, skill_id: str, description: str = "Use when planning a day.") -> bytes:
    content = f"---\nname: {skill_id}\ndescription: {description}\n---\n\n# {skill_id}\n"
    path = root / ".claude/skills" / skill_id / "SKILL.md"
    _write(path, content)
    return content.encode("utf-8")


def _registry(root: Path) -> None:
    skill_bytes = _skill(root, "daily-plan")
    schema_source = REPO_ROOT / "core/lens-catalog/schemas/dex-lens-catalogue-v2.schema.json"
    _write(
        root / "core/lens-catalog/schemas/dex-lens-catalogue-v2.schema.json",
        schema_source.read_text(encoding="utf-8"),
    )
    _write(
        root / "CHANGELOG.md",
        "# Changelog\n\n## [1.94.0] - Test release\n\n## [1.80.0] - Older release\n",
    )
    _write(root / "package.json", '{"version":"1.94.0"}\n')
    _write(
        root / "core/lens-catalog/registry.json",
        json.dumps(
            {
                "registry_version": 1,
                "catalog_version": 7,
                "jobs": [
                    {
                        "job_id": "plan-my-day",
                        "title": "Plan my day",
                        "description": "Turn calendar and tasks into one realistic daily plan.",
                    }
                ],
                "entries": [
                    {
                        "id": "daily-plan",
                        "source": {
                            "kind": "skill",
                            "path": ".claude/skills/daily-plan/SKILL.md",
                            "sha256": hashlib.sha256(skill_bytes).hexdigest(),
                            "byte_size": len(skill_bytes),
                        },
                        "value": "Helps a person choose what matters today before work scatters.",
                        "jobs_served": ["plan-my-day"],
                        "foundation_capabilities": [
                            "context-orientation",
                            "scoped-agency-human-control",
                        ],
                        "prerequisites": ["A task list or calendar the host can inspect."],
                        "trade_offs": ["The plan is only as current as the source material."],
                        "evidence": [
                            {
                                "kind": "test",
                                "reference": "core/tests/test_commitments_skill.py",
                                "summary": "Daily planning skill coverage exercises task creation boundaries.",
                            }
                        ],
                        "brief": {
                            "goal": "Create a daily planning routine that combines commitments and calendar shape.",
                            "method_outline": [
                                "Read today's meetings and open tasks.",
                                "Choose a short focus list that fits the available time.",
                            ],
                            "verification_checklist": [
                                "The output names a bounded set of actions for today."
                            ],
                            "rollback_advice": "Remove the routine or disable the command; it does not need to touch user content.",
                        },
                        "compatibility": {
                            "host_requirements": ["skills-directory"],
                            "needs_hooks": False,
                            "needs_mcp": True,
                            "platforms": ["macos", "linux", "windows"],
                        },
                        "docs_url": "https://github.com/davekilleen/Dex",
                        "since_release": "1.80.0",
                        "changed_in": [],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
    )


def _generate(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(root),
            "--output-dir",
            str(root / "dist"),
            "--issued-at",
            "2026-08-11T12:00:00Z",
            *extra,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_generates_canonical_unsigned_lens_catalog_payload(tmp_path: Path) -> None:
    _registry(tmp_path)

    result = _generate(tmp_path)

    assert result.returncode == 0, result.stderr
    envelope = json.loads((tmp_path / "dist/dex-lens-catalog-v1.94.0.json").read_text())
    assert set(envelope) == {"metadata", "catalogue", "signature"}
    assert envelope["signature"] == ""
    assert envelope["metadata"]["contract_version"] == "dex-lens-catalogue-v2"
    assert envelope["metadata"]["catalog_version"] == 7
    assert envelope["metadata"]["producer"] == "Dex Core release pipeline v1.94.0"
    assert envelope["metadata"]["core_release"] == "v1.94.0"
    assert envelope["metadata"]["key_id"] == "dex-core-lens-1"
    assert envelope["catalogue"]["jobs_taxonomy"][0]["job_id"] == "plan-my-day"
    assert envelope["catalogue"]["jobs_taxonomy"][0]["label"] == "Plan my day"
    capability = envelope["catalogue"]["capabilities"][0]
    assert capability["capability_id"] == "daily-plan"
    assert capability["title"] == "Daily Plan"
    assert capability["summary"] == "Use when planning a day."
    assert capability["value"] == "Helps a person choose what matters today before work scatters."
    assert capability["summary"] != capability["value"]
    assert capability["prerequisites"] == ["A task list or calendar the host can inspect."]
    assert capability["trade_offs"] == ["The plan is only as current as the source material."]
    assert capability["docs_url"] == "https://github.com/davekilleen/Dex"
    assert capability["since_release"] == "1.80.0"
    assert capability["changed_in"] == []
    assert capability["release_provenance"] == "core-release"
    assert capability["evidence"][0]["level"] == "verified"
    assert capability["compatibility"]["minimum_lens_contract"] == "0.1.0"
    assert capability["compatibility"]["platforms"] == ["macos", "linux", "windows"]
    assert capability["compatibility"]["needs_hooks"] is False
    assert capability["compatibility"]["needs_mcp"] is True
    assert capability["compatibility"]["host_requirements"] == ["skills-directory"]
    assert "Needs hooks" not in " ".join(capability["compatibility"]["limitations"])
    assert capability["portable_brief"]["goal"].startswith(
        "Create a daily planning routine"
    )
    assert "adaptation_notes" not in capability["portable_brief"]
    assert capability["portable_brief"]["method_outline"] == [
        "Read today's meetings and open tasks.",
        "Choose a short focus list that fits the available time.",
    ]
    assert capability["portable_brief"]["verification_checklist"] == [
        "The output names a bounded set of actions for today."
    ]
    assert capability["portable_brief"]["rollback_advice"].startswith("Remove the routine")
    assert envelope["catalogue"]["portable_brief"]["format"] == "markdown"
    assert (tmp_path / "dist/dex-lens-catalog-latest.json").read_text() == json.dumps(
        envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) + "\n"
    assert (tmp_path / "dist/dex-lens-catalog-v1.94.0.json.sha256").read_text().strip()


def test_generator_rejects_unknown_fields_in_registry(tmp_path: Path) -> None:
    _registry(tmp_path)
    data = json.loads((tmp_path / "core/lens-catalog/registry.json").read_text())
    data["entries"][0]["capabilities"] = []
    _write(tmp_path / "core/lens-catalog/registry.json", json.dumps(data))

    result = _generate(tmp_path)

    assert result.returncode == 1
    assert "unknown capabilities" in result.stderr


def test_generator_rejects_unknown_job_and_foundation_references(tmp_path: Path) -> None:
    _registry(tmp_path)
    data = json.loads((tmp_path / "core/lens-catalog/registry.json").read_text())
    data["entries"][0]["jobs_served"] = ["missing-job"]
    data["entries"][0]["foundation_capabilities"] = ["invented-foundation"]
    _write(tmp_path / "core/lens-catalog/registry.json", json.dumps(data))

    result = _generate(tmp_path)

    assert result.returncode == 1
    assert "unknown job reference" in result.stderr


def test_generator_rejects_unshipped_or_stale_source(tmp_path: Path) -> None:
    _registry(tmp_path)
    data = json.loads((tmp_path / "core/lens-catalog/registry.json").read_text())
    data["entries"][0]["source"]["path"] = ".claude/skills/missing/SKILL.md"
    _write(tmp_path / "core/lens-catalog/registry.json", json.dumps(data))

    missing = _generate(tmp_path)
    assert missing.returncode == 1
    assert "missing or not a regular file" in missing.stderr

    _registry(tmp_path)
    data = json.loads((tmp_path / "core/lens-catalog/registry.json").read_text())
    data["entries"][0]["source"]["sha256"] = "0" * 64
    _write(tmp_path / "core/lens-catalog/registry.json", json.dumps(data))

    stale = _generate(tmp_path)
    assert stale.returncode == 1
    assert "does not match its declared sha256 or byte_size" in stale.stderr


def test_generator_rejects_vendored_third_party_skill_sources(tmp_path: Path) -> None:
    _registry(tmp_path)
    vendored_bytes = _skill(tmp_path, "anthropic-pdf")
    data = json.loads((tmp_path / "core/lens-catalog/registry.json").read_text())
    data["entries"][0]["source"] = {
        "kind": "skill",
        "path": ".claude/skills/anthropic-pdf/SKILL.md",
        "sha256": hashlib.sha256(vendored_bytes).hexdigest(),
        "byte_size": len(vendored_bytes),
    }
    _write(tmp_path / "core/lens-catalog/registry.json", json.dumps(data))

    result = _generate(tmp_path)

    assert result.returncode == 1
    assert "must not be a vendored third-party skill" in result.stderr


def test_signing_requires_environment_secret_and_never_generates_a_key(tmp_path: Path) -> None:
    _registry(tmp_path)

    missing = _generate(tmp_path, "--sign", "--signing-key-env", "DEX_LENS_TEST_KEY")
    assert missing.returncode == 1
    assert "environment secret DEX_LENS_TEST_KEY is not set" in missing.stderr

    key = base64.b64encode(b"test-only-not-a-real-ed25519-private-key").decode("ascii")
    signed = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "dist"),
            "--issued-at",
            "2026-08-11T12:00:00Z",
            "--sign",
            "--signing-key-env",
            "DEX_LENS_TEST_KEY",
            "--key-id",
            "test-key",
            "--test-deterministic-signature",
        ],
        cwd=REPO_ROOT,
        env={"DEX_LENS_TEST_KEY": key},
        capture_output=True,
        text=True,
    )
    assert signed.returncode == 0, signed.stderr
    envelope = json.loads((tmp_path / "dist/dex-lens-catalog-v1.94.0.json").read_text())
    assert envelope["metadata"]["key_id"] == "test-key"
    assert len(base64.b64decode(envelope["signature"], validate=True)) == 64


def test_deterministic_test_signature_is_unreachable_in_ci(tmp_path: Path) -> None:
    _registry(tmp_path)
    key = base64.b64encode(b"test-only-not-a-real-ed25519-private-key").decode("ascii")

    signed = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "dist"),
            "--issued-at",
            "2026-08-11T12:00:00Z",
            "--sign",
            "--signing-key-env",
            "DEX_LENS_TEST_KEY",
            "--key-id",
            "test-key",
            "--test-deterministic-signature",
        ],
        cwd=REPO_ROOT,
        env={"DEX_LENS_TEST_KEY": key, "GITHUB_ACTIONS": "true"},
        capture_output=True,
        text=True,
    )

    assert signed.returncode == 1
    assert "deterministic test signature mode is disabled in CI" in signed.stderr


def test_real_ed25519_signing_hook_uses_only_environment_key(tmp_path: Path) -> None:
    _registry(tmp_path)
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    )

    signed = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "dist"),
            "--issued-at",
            "2026-08-11T12:00:00Z",
            "--sign",
            "--signing-key-env",
            "DEX_LENS_TEST_KEY",
            "--key-id",
            "ed25519-test-key",
        ],
        cwd=REPO_ROOT,
        env={"DEX_LENS_TEST_KEY": base64.b64encode(private_pem).decode("ascii")},
        capture_output=True,
        text=True,
    )
    assert signed.returncode == 0, signed.stderr
    envelope = json.loads((tmp_path / "dist/dex-lens-catalog-v1.94.0.json").read_text())
    signature = base64.b64decode(envelope["signature"])
    private_key.public_key().verify(signature, _signed_payload(envelope).encode("utf-8"))


def _corrupt_dropped_required_field(data: dict) -> str:
    del data["entries"][0]["value"]
    return "missing value"


def _corrupt_wrong_schema_shape(data: dict) -> str:
    data["entries"][0]["prerequisites"] = "a single string, not an array"
    return "prerequisites must be a non-empty array"


def _corrupt_stale_source_sha256(data: dict) -> str:
    data["entries"][0]["source"]["sha256"] = "1" * 64
    return "does not match its declared sha256 or byte_size"


def _corrupt_stale_source_byte_size(data: dict) -> str:
    data["entries"][0]["source"]["byte_size"] = 999999
    return "does not match its declared sha256 or byte_size"


def _corrupt_unknown_job_reference(data: dict) -> str:
    data["entries"][0]["jobs_served"] = ["job-that-does-not-exist"]
    return "unknown job reference"


def _corrupt_unknown_foundation_reference(data: dict) -> str:
    data["entries"][0]["foundation_capabilities"] = ["foundation-that-does-not-exist"]
    return "unknown foundation reference"


def _corrupt_unreleased_since_version(data: dict) -> str:
    data["entries"][0]["since_release"] = "99.0.0"
    return "since_release has no shipped source in CHANGELOG.md"


def _lens_artifacts(root: Path) -> list[str]:
    """Every file the release workflow would publish for the Lens catalogue."""
    dist = root / "dist"
    if not dist.exists():
        return []
    return sorted(path.name for path in dist.iterdir() if path.name.startswith("dex-lens-catalog"))


def _generate_signed(root: Path, key_b64: str) -> subprocess.CompletedProcess[str]:
    """Run the producer exactly as the release job does: --sign with a usable key present."""
    return subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(root),
            "--output-dir",
            str(root / "dist"),
            "--issued-at",
            "2026-08-11T12:00:00Z",
            "--sign",
            "--signing-key-env",
            "DEX_LENS_TEST_KEY",
            "--key-id",
            "dex-core-lens-1",
        ],
        cwd=REPO_ROOT,
        env={"DEX_LENS_TEST_KEY": key_b64},
        capture_output=True,
        text=True,
    )


@pytest.fixture(name="signing_key_b64")
def _signing_key_b64() -> str:
    private_pem = Ed25519PrivateKey.generate().private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    )
    return base64.b64encode(private_pem).decode("ascii")


def test_signed_release_path_publishes_when_the_registry_is_sound(
    tmp_path: Path, signing_key_b64: str
) -> None:
    """Positive control: without this, the fail-closed test below could pass vacuously."""
    _registry(tmp_path)

    result = _generate_signed(tmp_path, signing_key_b64)

    assert result.returncode == 0, result.stderr
    assert _lens_artifacts(tmp_path) == [
        "dex-lens-catalog-latest.json",
        "dex-lens-catalog-latest.json.sha256",
        "dex-lens-catalog-v1.94.0.json",
        "dex-lens-catalog-v1.94.0.json.sha256",
    ]
    assert json.loads((tmp_path / "dist/dex-lens-catalog-v1.94.0.json").read_text())["signature"]


@pytest.mark.parametrize(
    ("corrupt", "label"),
    [
        (_corrupt_dropped_required_field, "dropped-required-field"),
        (_corrupt_wrong_schema_shape, "wrong-schema-shape"),
        (_corrupt_stale_source_sha256, "stale-source-sha256"),
        (_corrupt_stale_source_byte_size, "stale-source-byte-size"),
        (_corrupt_unknown_job_reference, "unknown-job-reference"),
        (_corrupt_unknown_foundation_reference, "unknown-foundation-reference"),
        (_corrupt_unreleased_since_version, "unreleased-since-version"),
    ],
)
def test_broken_registry_entry_fails_closed_before_signing_or_publication(
    tmp_path: Path, signing_key_b64: str, corrupt, label: str
) -> None:
    """A broken registry entry must stop the release producer before it signs or writes.

    The unsigned rejection tests above prove the generator complains. This proves the
    property the release job actually depends on: with a usable signing key present and
    --sign requested, a broken entry still refuses, and leaves nothing behind for the
    'Upload Dex Lens catalog' steps to publish.
    """
    _registry(tmp_path)
    registry_path = tmp_path / "core/lens-catalog/registry.json"
    data = json.loads(registry_path.read_text())
    expected_error = corrupt(data)
    _write(registry_path, json.dumps(data))

    result = _generate_signed(tmp_path, signing_key_b64)

    assert result.returncode == 1, f"{label}: expected refusal, got {result.returncode}"
    assert "Dex Lens catalog generation failed" in result.stderr
    assert expected_error in result.stderr, f"{label}: unexpected reason: {result.stderr}"
    # Fails closed: no signed envelope, no digest sidecar, nothing to upload or serve.
    assert _lens_artifacts(tmp_path) == [], f"{label}: producer left publishable output behind"


def test_broken_registry_refusal_is_not_a_signing_failure(
    tmp_path: Path, signing_key_b64: str
) -> None:
    """The refusal must come from registry validation, not from the signing step.

    If validation ever moved after signing, the error text would change and this
    would catch it -- the producer must never reach the key for a broken registry.
    """
    _registry(tmp_path)
    registry_path = tmp_path / "core/lens-catalog/registry.json"
    data = json.loads(registry_path.read_text())
    _corrupt_stale_source_sha256(data)
    _write(registry_path, json.dumps(data))

    result = _generate_signed(tmp_path, signing_key_b64)

    assert result.returncode == 1
    assert "does not match its declared sha256 or byte_size" in result.stderr
    for signing_error in (
        "environment secret",
        "is not base64",
        "Ed25519 signing failed",
        "is not an Ed25519 private key",
        "cryptography>=42 is required",
    ):
        assert signing_error not in result.stderr


# --- The registry Dex actually ships ---------------------------------------
#
# Every test above builds a synthetic release tree. That proves the producer's
# logic, but it cannot see the registry Dex actually ships, so the whole file
# stays green while the real catalogue refuses to build. That happened: a skill
# was edited after its pin was written, and the first place it could have
# surfaced was the release job itself, with the release already in motion.
#
# These two tests read core/lens-catalog/registry.json against the real release
# root, so pin drift fails on the pull request that causes it.


def _registry_source_pin_drifts(registry_path: Path, release_root: Path) -> list[str]:
    entries = json.loads(registry_path.read_text(encoding="utf-8"))["entries"]
    assert entries, "the shipped registry declares no entries to check"

    drifted = []
    for index, entry in enumerate(entries):
        source = entry["source"]
        skill = release_root / source["path"]
        if not skill.is_file():
            drifted.append(f"entry {index} ({entry['id']}): {source['path']} is missing")
            continue
        content = skill.read_bytes()
        actual_sha = hashlib.sha256(content).hexdigest()
        if actual_sha != source["sha256"] or len(content) != source["byte_size"]:
            drifted.append(
                f"entry {index} ({entry['id']}): {source['path']} changed after its pin was"
                f" written -- declared sha256={source['sha256']} byte_size={source['byte_size']},"
                f" actual sha256={actual_sha} byte_size={len(content)}"
            )
    return drifted


def test_real_registry_source_pins_match_the_shipped_skills() -> None:
    """Every pinned skill must still hash to the digest and size the registry declares.

    This is the narrow, fast gate: it needs no signing key and no release
    metadata, so it reports pin drift as pin drift rather than as some later
    failure, and it names the corrected values so the fix is mechanical.
    """
    drifted = _registry_source_pin_drifts(REAL_REGISTRY, REPO_ROOT)
    assert not drifted, (
        "core/lens-catalog/registry.json source pins are stale, so the release job's Lens"
        " catalogue generation will refuse. Update the declared sha256 and byte_size for:\n  "
        + "\n  ".join(drifted)
    )


def test_real_registry_pin_check_fails_on_a_deliberately_drifted_pin(tmp_path: Path) -> None:
    registry = json.loads(REAL_REGISTRY.read_text(encoding="utf-8"))
    registry["entries"][0]["source"]["sha256"] = "0" * 64
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    drifted = _registry_source_pin_drifts(registry_path, REPO_ROOT)

    assert drifted
    assert "changed after its pin was written" in drifted[0]


def test_shipped_registry_builds_the_release_catalogue(tmp_path: Path, signing_key_b64: str) -> None:
    """The real registry must produce a signed catalogue, invoked as the release job does.

    Broader than the pin check above: this exercises the whole producer against
    the real release root -- release version against CHANGELOG, job and
    foundation references, skill frontmatter, the vendored schema -- so any
    registry change that would only fail during a release fails here instead.
    Output goes to a temporary directory; the repository is never written to.
    """
    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(REPO_ROOT),
            "--output-dir",
            str(tmp_path / "dist"),
            "--issued-at",
            "2026-08-11T12:00:00Z",
            "--sign",
            "--signing-key-env",
            "DEX_LENS_TEST_KEY",
            "--key-id",
            "dex-core-lens-1",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "DEX_LENS_TEST_KEY": signing_key_b64},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "the shipped Lens registry no longer builds, so the next release would fail to"
        f" produce its catalogue: {result.stderr}"
    )

    version = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    assert _lens_artifacts(tmp_path) == [
        "dex-lens-catalog-latest.json",
        "dex-lens-catalog-latest.json.sha256",
        f"dex-lens-catalog-v{version}.json",
        f"dex-lens-catalog-v{version}.json.sha256",
    ]

    envelope = json.loads((tmp_path / f"dist/dex-lens-catalog-v{version}.json").read_text())
    assert envelope["signature"], "the real catalogue was written without a signature"
    assert envelope["metadata"]["core_release"] == f"v{version}"
    registry = json.loads(REAL_REGISTRY.read_text(encoding="utf-8"))
    assert [capability["capability_id"] for capability in envelope["catalogue"]["capabilities"]] == [
        entry["id"] for entry in registry["entries"]
    ]
