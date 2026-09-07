"""Dex Doctor integration for the deep-only customization assessment."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from core.customization_migration.service import assess
from core.lifecycle.catalog import canonical_catalog_bytes, with_catalog_identity
from core.lifecycle.release_anchor import (
    RELEASE_ANCHOR_PATH,
    build_release_anchor_document,
    canonical_anchor_bytes,
)
from core.tests.lifecycle_test_helpers import SOURCE_COMMIT, write_file, write_manifest
from core.tests.test_customization_assessment import (
    SHIPPED_BYTES,
    SHIPPED_SKILL,
    _install_verified_catalog,
)
from core.utils import doctor

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)

ANCHORED_ENGINE = b"engine release bytes\n"
ANCHORED_ENGINE_PATH = "core/engine.py"


def _install_anchorable_vault(vault: Path) -> tuple[bytes, str]:
    """A verified catalog plus one brain file only an anchor can prove.

    Returns the installed manifest bytes and the installed catalog's
    canonical identity, so tests can bind (or deliberately mis-bind) anchors.
    """
    write_file(vault, SHIPPED_SKILL, SHIPPED_BYTES)
    write_file(vault, ANCHORED_ENGINE_PATH, ANCHORED_ENGINE)
    manifest = write_manifest(vault, [SHIPPED_SKILL, ANCHORED_ENGINE_PATH])
    document = with_catalog_identity(
        {
            "catalog_version": 2,
            "release": {
                "version": "1.73.0",
                "channel": "release",
                "immutable_distribution_tag_pattern": "dist/release/v1.73.0-<release-commit-prefix>",
                "source_commit": SOURCE_COMMIT,
                "manifest": {
                    "path": "System/.installed-files.manifest",
                    "sha256": hashlib.sha256(manifest).hexdigest(),
                },
            },
            "items": [
                {
                    "id": "daily-plan",
                    "kind": "skill",
                    "version": "1.0.0",
                    "files": [
                        {
                            "path": SHIPPED_SKILL,
                            "sha256": hashlib.sha256(SHIPPED_BYTES).hexdigest(),
                            "ownership_class": "brain",
                        }
                    ],
                    "dependencies": [],
                    "capabilities": [],
                    "rewind": {
                        "acknowledgement_required": True,
                        "token": "rewind:daily-plan@1.0.0",
                    },
                }
            ],
            "integrity": {"catalog_sha256": "0" * 64, "signatures": []},
        }
    )
    write_file(vault, "System/.release-catalog.json", canonical_catalog_bytes(document))
    catalog_sha256 = json.loads(
        (vault / "System/.release-catalog.json").read_text(encoding="utf-8")
    )["integrity"]["catalog_sha256"]
    return manifest, catalog_sha256


def _context(tmp_path: Path) -> doctor.DoctorContext:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir(parents=True)
    return doctor.DoctorContext(vault_root=vault, repo_root=vault, home=home, now=NOW)


def _stub_probes(monkeypatch) -> None:
    for definition in (*doctor.QUICK_CHECKS, *doctor.DEEP_CHECKS):
        if definition.id in {"doctor.self", "customizations.assessment"}:
            continue
        monkeypatch.setattr(
            doctor,
            definition.probe,
            lambda _context: doctor.ProbeResult("OK", "Stub probe completed."),
        )
    monkeypatch.setattr(doctor, "_write_last_run", lambda _report, _context: None)


def test_deep_collect_includes_assessment_section_but_quick_does_not(
    monkeypatch,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _install_verified_catalog(context.vault_root)
    _stub_probes(monkeypatch)

    quick = doctor.collect(context=context)
    deep = doctor.collect(deep=True, context=context)

    assert "customization_assessment" not in quick
    assert deep["customization_assessment"]["schema_version"] == 0
    assert deep["customization_assessment"]["verdict"] == "OK"
    assert any(
        check["id"] == "customizations.assessment"
        for check in deep["checks"]
    )


def test_probe_maps_verified_missing_and_ambiguous_catalog_states(
    tmp_path: Path,
) -> None:
    verified = _context(tmp_path / "verified")
    _install_verified_catalog(verified.vault_root)
    assert doctor._probe_customization_assessment(verified).verdict == "OK"

    older = _context(tmp_path / "older")
    older_assessment = assess(older.vault_root)
    assert older_assessment.verdict == "UNKNOWN"
    assert doctor._probe_customization_assessment(older).verdict == "UNKNOWN"

    ambiguous = _context(tmp_path / "ambiguous")
    _install_verified_catalog(ambiguous.vault_root)
    second_catalog = ambiguous.vault_root / "core/lifecycle/catalog/release.json"
    second_catalog.parent.mkdir(parents=True)
    second_catalog.write_bytes(
        (ambiguous.vault_root / "System/.release-catalog.json").read_bytes()
    )
    assert doctor._probe_customization_assessment(ambiguous).verdict == "UNKNOWN"


def test_probe_maps_invalid_catalog_to_broken(tmp_path: Path) -> None:
    context = _context(tmp_path)
    path = context.vault_root / "System/.release-catalog.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    result = doctor._probe_customization_assessment(context)

    assert result.verdict == "BROKEN"
    assert result.structured_detail is not None


def test_manifest_only_probe_is_unknown_without_counts_or_records(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    write_file(
        context.vault_root,
        SHIPPED_SKILL,
        b"locally modified without hash authority\n",
    )
    write_manifest(context.vault_root, [SHIPPED_SKILL])

    result = doctor._probe_customization_assessment(context)
    encoded = json.dumps(result.structured_detail, sort_keys=True)

    assert result.verdict == "UNKNOWN"
    assert result.detail == (
        "I couldn't verify which Dex version is installed, so I can't tell you "
        "what you've changed."
    )
    assert result.structured_detail is not None
    assert result.structured_detail["incomplete_reasons"] == [
        "baseline-not-verified"
    ]
    assert "records" not in result.structured_detail
    assert "counts" not in result.structured_detail
    assert "customization_count" not in encoded
    assert result.structured_detail["records_truncated"] is False


def test_probe_persistence_detail_caps_record_listing_at_25(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _install_verified_catalog(context.vault_root)
    for index in range(26):
        write_file(
            context.vault_root,
            f".scripts/custom-{index:02d}.py",
            f"VALUE = {index}\n".encode(),
        )

    result = doctor._probe_customization_assessment(context)

    assert result.verdict == "OK"
    assert result.structured_detail is not None
    assert result.structured_detail["counts"]["total"] == 26
    assert result.structured_detail["records_total"] == 26
    assert result.structured_detail["records_truncated"] is True
    assert len(result.structured_detail["records"]) == 25


def test_probe_summary_leads_with_blocked_customizations(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _install_verified_catalog(context.vault_root)
    write_file(
        context.vault_root,
        ".scripts/custom.py",
        b'TARGET = "missing/helper.py"\n',
    )

    result = doctor._probe_customization_assessment(context)

    assert result.verdict == "OK"
    assert result.detail == "Customization assessment completed: 1 customization, 1 blocked"
    assert result.structured_detail["blocked_count"] == 1
    assert result.structured_detail["needs_interpretation_count"] == 0


def test_probe_summary_without_blocked_customizations(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _install_verified_catalog(context.vault_root)

    result = doctor._probe_customization_assessment(context)

    assert result.verdict == "OK"
    assert result.detail == "Customization assessment completed: 0 customizations"
    assert result.structured_detail["blocked_count"] == 0
    assert result.structured_detail["needs_interpretation_count"] == 0


def test_probe_reports_a_verified_release_anchor(tmp_path: Path) -> None:
    context = _context(tmp_path)
    manifest, catalog_sha256 = _install_anchorable_vault(context.vault_root)
    unproved = doctor._probe_customization_assessment(context)
    assert unproved.verdict == "UNKNOWN"

    anchor = build_release_anchor_document(
        release_version="1.73.0",
        tag=f"dist/release/v1.73.0-{SOURCE_COMMIT[:7]}",
        tag_object="a" * 40,
        commit=SOURCE_COMMIT,
        tree="f" * 40,
        manifest_sha256=hashlib.sha256(manifest).hexdigest(),
        catalog_sha256=catalog_sha256,
        files={ANCHORED_ENGINE_PATH: hashlib.sha256(ANCHORED_ENGINE).hexdigest()},
    )
    write_file(context.vault_root, RELEASE_ANCHOR_PATH, canonical_anchor_bytes(anchor))

    result = doctor._probe_customization_assessment(context)

    assert result.verdict == "OK"
    assert "A saved proof record vouches for" in result.detail
    assert result.structured_detail is not None
    baseline = result.structured_detail["release_baseline"]
    assert baseline["anchor_state"] == "verified"
    assert baseline["identity_state"] == "VERIFIED"
    assert baseline["errors"] == []


def test_probe_warns_about_a_rejected_release_anchor_naming_the_error(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _install_anchorable_vault(context.vault_root)
    write_file(context.vault_root, RELEASE_ANCHOR_PATH, b"{}\n")

    result = doctor._probe_customization_assessment(context)

    # Fail closed to today's behavior: the vault stays UNKNOWN, and the
    # warning names the fail-closed consumer's exact error.
    assert result.verdict == "UNKNOWN"
    assert "Warning: a proof record is present but couldn't be trusted" in result.detail
    assert "release anchor has an unsupported shape" in result.detail
    assert "guided repair" in result.detail
    baseline = result.structured_detail["release_baseline"]
    assert baseline["anchor_state"] == "rejected"
    assert any("release anchor" in error for error in baseline["errors"])


def test_probe_says_nothing_about_an_absent_anchor(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _install_verified_catalog(context.vault_root)

    result = doctor._probe_customization_assessment(context)

    assert result.verdict == "OK"
    assert "anchor" not in result.detail
    assert result.structured_detail["release_baseline"]["anchor_state"] == "absent"


def test_doctor_skill_offers_the_reanchor_flow_without_running_it() -> None:
    skill = (
        Path(__file__).resolve().parents[2]
        / ".claude/skills/dex-doctor/SKILL.md"
    ).read_text(encoding="utf-8")
    section = skill.split("#### Offering the release re-anchoring repair", 1)[1].split(
        "### Step 3c:", 1
    )[0]

    # The flow is offered as a command the PERSON runs in their own terminal
    # (its consent gates are TTY reads, so the model cannot answer them), and
    # the wording is flagged as founder copy pending approval.
    assert "python3 -m core.update.reanchor_cli" in section
    assert "Never attempt to run it through Bash" in section
    assert "FOUNDER COPY - DRAFT PENDING APPROVAL" in section
    assert "`rejected`" in section and "`verified`" in section


def test_doctor_skill_requires_blocked_count_in_first_summary_sentence() -> None:
    skill = (
        Path(__file__).resolve().parents[2]
        / ".claude/skills/dex-doctor/SKILL.md"
    ).read_text(encoding="utf-8")
    section = skill.split("### Step 3b: Render the customization assessment", 1)[1].split(
        "### Step 3c:", 1
    )[0]

    assert (
        "When `blocked_count` is greater than zero, the first summary sentence must "
        "state that blocked count."
    ) in section
