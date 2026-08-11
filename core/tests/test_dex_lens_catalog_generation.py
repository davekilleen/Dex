"""Dex Lens catalog producer gates."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts/generate-dex-lens-catalog.py"


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
