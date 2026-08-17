"""Fail-closed tests for macOS historic updater acceptance."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import stat
import subprocess
import urllib.error
from collections.abc import Sequence
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import release_fleet
from scripts.dex_update_bridge import FOUNDATION


def _acceptance():
    try:
        return importlib.import_module("scripts.release_fleet_acceptance")
    except ModuleNotFoundError:
        pytest.fail("release_fleet_acceptance is not implemented")


def _release(tag: str, version: str, suffix: str) -> release_fleet.DistributionRelease:
    return release_fleet.DistributionRelease(
        tag=tag,
        version=version,
        commit=(suffix * 40)[:40],
        tree=((chr(ord(suffix) + 1)) * 40)[:40],
    )


def _foundation() -> dict[str, str]:
    return FOUNDATION.identity()


def _foundation_release() -> release_fleet.DistributionRelease:
    identity = FOUNDATION.identity()
    return release_fleet.DistributionRelease(
        tag=identity["tag"],
        version=identity["version"],
        commit=identity["commit"],
        tree=identity["tree"],
    )


def test_frozen_cohort_excludes_later_control_and_follow_up_releases() -> None:
    acceptance = _acceptance()
    historic = (
        _release("v1.20.1", "1.20.1", "1"),
        _release("v1.81.16", "1.81.16", "3"),
        _foundation_release(),
    )
    later = (
        _release("v1.81.17", "1.81.17", "4"),
        _release("dist/release/v1.81.18-5555555", "1.81.18", "5"),
    )

    manifest = acceptance.frozen_cohort_manifest(
        historic + later,
        foundation=_foundation(),
    )
    parsed = acceptance.releases_from_frozen_cohort(
        json.dumps(manifest),
        current_releases=historic + later,
        foundation=_foundation(),
    )

    assert parsed == historic
    assert manifest["case_count"] == 3
    assert manifest["foundation"] == _foundation()


def test_frozen_cohort_derives_and_binds_its_current_public_case_count() -> None:
    acceptance = _acceptance()
    historic = (
        _release("v1.20.1", "1.20.1", "1"),
        _foundation_release(),
    )

    manifest = acceptance.frozen_cohort_manifest(historic)
    parsed = acceptance.releases_from_frozen_cohort(
        json.dumps(manifest),
        current_releases=historic,
    )
    session = acceptance.create_acceptance_session(
        cohort_sha256="a" * 64,
        foundation=_foundation(),
        follow_up_tag="dist/release/v1.81.7-3333333",
        source_commit="c" * 40,
        acceptance_source_sha256="d" * 64,
        protocol_platforms=("darwin",),
        case_count=len(parsed),
        key=bytes(range(32)),
        session_id="e" * 64,
    )

    assert manifest["case_count"] == session["payload"]["case_count"] == 2
    assert session["payload"]["journey_count"] == 2


def test_frozen_cohort_rejects_a_new_release_at_or_before_the_foundation() -> None:
    acceptance = _acceptance()
    historic = (
        _release("v1.20.1", "1.20.1", "1"),
        _foundation_release(),
    )
    manifest = acceptance.frozen_cohort_manifest(
        historic,
        foundation=_foundation(),
    )
    unexpected = _release("dist/release/v1.79.0-5555555", "1.79.0", "5")

    with pytest.raises(release_fleet.FleetError, match="unexpected historical release"):
        acceptance.releases_from_frozen_cohort(
            json.dumps(manifest),
            current_releases=historic + (unexpected,),
            foundation=_foundation(),
        )


def test_frozen_cohort_rejects_missing_duplicate_and_miscounted_starts() -> None:
    acceptance = _acceptance()
    historic = (
        _release("v1.20.1", "1.20.1", "1"),
        _foundation_release(),
    )
    manifest = acceptance.frozen_cohort_manifest(historic)

    with pytest.raises(release_fleet.FleetError, match="identity drift"):
        acceptance.releases_from_frozen_cohort(
            json.dumps(manifest),
            current_releases=historic[1:],
        )

    duplicate = release_fleet.DistributionRelease(
        tag=historic[0].tag,
        version=historic[0].version,
        commit="9" * 40,
        tree="8" * 40,
    )
    with pytest.raises(release_fleet.FleetError, match="repeats a release tag"):
        acceptance.frozen_cohort_manifest(historic + (duplicate,))

    miscounted = dict(manifest, case_count=3)
    with pytest.raises(release_fleet.FleetError, match="invalid case count"):
        acceptance.releases_from_frozen_cohort(
            json.dumps(miscounted),
            current_releases=historic,
        )


def test_frozen_cohort_rejects_identity_drift_and_wrong_foundation() -> None:
    acceptance = _acceptance()
    historic = (
        _release("v1.20.1", "1.20.1", "1"),
        _foundation_release(),
    )
    manifest = acceptance.frozen_cohort_manifest(
        historic,
        foundation=_foundation(),
    )
    changed = release_fleet.DistributionRelease(
        tag=historic[0].tag,
        version=historic[0].version,
        commit="9" * 40,
        tree=historic[0].tree,
    )

    with pytest.raises(release_fleet.FleetError, match="historic cohort identity drift"):
        acceptance.releases_from_frozen_cohort(
            json.dumps(manifest),
            current_releases=(changed, historic[1]),
            foundation=_foundation(),
        )

    other_foundation = dict(_foundation(), tree="e" * 40)
    with pytest.raises(release_fleet.FleetError, match="foundation identity"):
        acceptance.releases_from_frozen_cohort(
            json.dumps(manifest),
            current_releases=historic,
            foundation=other_foundation,
        )


def test_frozen_cohort_requires_the_exact_foundation_release() -> None:
    acceptance = _acceptance()
    without_foundation = (
        _release("v1.20.1", "1.20.1", "1"),
        _release("dist/release/v1.80.5-2222222", "1.80.5", "2"),
    )

    with pytest.raises(release_fleet.FleetError, match="foundation release"):
        acceptance.frozen_cohort_manifest(
            without_foundation,
            foundation=_foundation(),
        )


def test_real_repository_derives_the_current_historic_tree_count() -> None:
    acceptance = _acceptance()
    repository = Path(__file__).resolve().parents[2]
    current = release_fleet.discover_distribution_releases(repository)

    manifest = acceptance.frozen_cohort_manifest(current)
    parsed = acceptance.releases_from_frozen_cohort(
        json.dumps(manifest),
        current_releases=current,
    )

    assert manifest["case_count"] == len(manifest["cases"]) == len(parsed)
    assert manifest["case_count"] > 0
    assert manifest["foundation"]["tag"] == "dist/release/v1.81.16-281202d"

    designated = acceptance.bridge_process_entry_release(parsed)
    assert designated is not None
    assert designated.tag != FOUNDATION.tag
    assert designated.commit != FOUNDATION.commit
    assert designated.tree != FOUNDATION.tree
    assert designated.tag != "v1.51.0"


def _case(tag: str, platform: str) -> release_fleet.CaseResult:
    hashes = {"00-Inbox/keep.md": "a" * 64}
    return release_fleet.CaseResult(
        starting_tag=tag,
        reached_foundation=True,
        reached_follow_up=True,
        foundation_doctor_healthy=True,
        follow_up_doctor_healthy=True,
        user_hashes_before=hashes,
        user_hashes_after_foundation=hashes,
        user_hashes_after_follow_up=hashes,
        transcript_path=f"{tag}.evidence/transcript.json",
        foundation_receipt_path=f"{tag}.evidence/foundation.json",
        follow_up_receipt_path=f"{tag}.evidence/follow-up.json",
        foundation_doctor_path=f"{tag}.evidence/foundation-doctor.json",
        follow_up_doctor_path=f"{tag}.evidence/follow-up-doctor.json",
        follow_up_smoke_path=f"{tag}.evidence/smoke.json",
        platform=platform,
        evidence_manifest_path=f"{tag}.evidence/manifest.json",
        evidence_manifest_sha256="b" * 64,
    )


def test_platform_report_is_bound_to_one_real_protocol_platform() -> None:
    acceptance = _acceptance()
    tags = {"v1.20.1", "dist/release/v1.80.5-2222222"}
    protocol = SimpleNamespace(platforms=("darwin",))
    report = release_fleet.AcceptanceReport(
        foundation_tag=FOUNDATION.tag,
        follow_up_tag="dist/release/v1.81.1-3333333",
        cases=tuple(_case(tag, "darwin") for tag in sorted(tags)),
        platforms=("darwin",),
    )

    acceptance.assert_platform_report_bound(
        report,
        protocol=protocol,
        running_platform="darwin",
        expected_start_tags=tags,
    )

    with pytest.raises(release_fleet.FleetError, match="running platform"):
        acceptance.assert_platform_report_bound(
            report,
            protocol=protocol,
            running_platform="linux",
            expected_start_tags=tags,
        )

    broad_report = release_fleet.AcceptanceReport(
        report.foundation_tag,
        report.follow_up_tag,
        report.cases,
        ("darwin", "linux"),
    )
    with pytest.raises(release_fleet.FleetError, match="exactly one"):
        acceptance.assert_platform_report_bound(
            broad_report,
            protocol=protocol,
            running_platform="darwin",
            expected_start_tags=tags,
        )


def test_platform_report_rejects_a_protocol_platform_superset() -> None:
    acceptance = _acceptance()
    report = release_fleet.AcceptanceReport(
        foundation_tag=FOUNDATION.tag,
        follow_up_tag="dist/release/v1.81.1-3333333",
        cases=(_case("v1.20.1", "darwin"),),
        platforms=("darwin",),
    )

    with pytest.raises(release_fleet.FleetError, match="protocol platforms"):
        acceptance.assert_platform_report_bound(
            report,
            protocol=SimpleNamespace(platforms=("darwin", "linux")),
            running_platform="darwin",
            expected_start_tags={"v1.20.1"},
        )


def _fleet_inputs() -> tuple[object, tuple[release_fleet.DistributionRelease, ...]]:
    releases = tuple(
        _release(f"v1.0.{index}", f"1.0.{index}", f"{index % 10}")
        for index in range(1, 4)
    )
    acceptance = _acceptance()
    return (
        acceptance.FleetInputs(
            releases=releases,
            foundation=_immutable_foundation(),
            follow_up=_immutable_follow_up(),
            protocol=SimpleNamespace(platforms=("darwin",)),
            source_commit="c" * 40,
            acceptance_source_sha256="d" * 64,
            cohort_sha256="a" * 64,
        ),
        releases,
    )


def _signed_session(acceptance):
    inputs, _releases = _fleet_inputs()
    key = bytes(range(32))
    session = acceptance.create_acceptance_session(
        cohort_sha256=inputs.cohort_sha256,
        foundation=inputs.foundation.identity(),
        follow_up_tag=inputs.follow_up.tag,
        source_commit=inputs.source_commit,
        acceptance_source_sha256=inputs.acceptance_source_sha256,
        protocol_platforms=inputs.protocol.platforms,
        case_count=len(inputs.releases),
        key=key,
        session_id="e" * 64,
    )
    return key, session, inputs


def _manifest_document(
    *,
    inputs: object,
    platform: str,
    session_id: str = "e" * 64,
    cases: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    acceptance = _acceptance()
    if cases is None:
        cases = [
            _case_document(_case(release.tag, platform))
            for release in inputs.releases
        ]
    return {
        "schema_version": acceptance.PLATFORM_MANIFEST_SCHEMA_VERSION,
        "outcome": "HISTORIC_PLATFORM_EVIDENCE",
        "acceptance": False,
        "session_id": session_id,
        "platform": platform,
        "cohort_sha256": inputs.cohort_sha256,
        "foundation": inputs.foundation.identity(),
        "follow_up_tag": inputs.follow_up.tag,
        "source_commit": inputs.source_commit,
        "acceptance_source_sha256": inputs.acceptance_source_sha256,
        "report": {
            "foundation_tag": inputs.foundation.tag,
            "follow_up_tag": inputs.follow_up.tag,
            "platforms": [platform],
            "cases": cases,
        },
    }


def _write_authored_platform_evidence(
    acceptance,
    root: Path,
    *,
    session: object,
    key: bytes,
    inputs: object,
    platform: str,
    manifest: dict[str, object] | None = None,
) -> tuple[Path, dict[str, object]]:
    document = (
        _manifest_document(inputs=inputs, platform=platform)
        if manifest is None
        else manifest
    )
    manifest_path = root / f"{platform}.manifest.json"
    manifest_bytes = acceptance._json_bytes(document)
    manifest_path.write_bytes(manifest_bytes)
    manifest_path.chmod(0o444)
    session_id = session["payload"]["session_id"]
    receipt = acceptance._sign(
        {
            "schema_version": 1,
            "session_id": session_id,
            "platform": platform,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
        key,
    )
    return manifest_path, receipt


def test_serialized_platform_evidence_is_never_an_acceptance_authority(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    key, session, inputs = _signed_session(acceptance)
    evidence = [
        _write_authored_platform_evidence(
            acceptance,
            tmp_path,
            session=session,
            key=key,
            inputs=inputs,
            platform=platform,
        )
        for platform in ("darwin",)
    ]

    result = acceptance.aggregate_platform_evidence(
        session,
        [receipt for _manifest, receipt in evidence],
        [manifest for manifest, _receipt in evidence],
        key=key,
        inputs=inputs,
    )
    case_count = len(inputs.releases)

    assert result == {
        "outcome": "HISTORIC_FLEET_EVIDENCE_AGGREGATED",
        "acceptance": False,
        "authority_complete": False,
        "platforms": ["darwin"],
        "case_count": case_count,
        "journey_count": case_count,
        "discovered": case_count,
        "started": case_count,
        "completed": case_count,
        "passed": case_count,
        "failed": 0,
        "session_id": "e" * 64,
        "required_job_conclusions": {
            "darwin": "historic-fleet-darwin",
        },
    }
    assert not hasattr(acceptance, "sign_platform_receipt")
    source = Path(acceptance.__file__).read_text(encoding="utf-8")
    assert '"acceptance": True' not in source
    assert "HISTORIC_FLEET_ACCEPTED" not in source


def test_possession_of_the_shared_key_cannot_sign_an_accepted_receipt(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    key, session, inputs = _signed_session(acceptance)
    evidence = [
        _write_authored_platform_evidence(
            acceptance,
            tmp_path,
            session=session,
            key=key,
            inputs=inputs,
            platform=platform,
        )
        for platform in ("darwin",)
    ]

    result = acceptance.aggregate_platform_evidence(
        session,
        [receipt for _manifest, receipt in evidence],
        [manifest for manifest, _receipt in evidence],
        key=key,
        inputs=inputs,
    )

    assert result["acceptance"] is False
    assert result["authority_complete"] is False


def test_aggregation_requires_exact_darwin_evidence(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    key, session, inputs = _signed_session(acceptance)
    darwin = _write_authored_platform_evidence(
        acceptance,
        tmp_path,
        session=session,
        key=key,
        inputs=inputs,
        platform="darwin",
    )
    linux = _write_authored_platform_evidence(
        acceptance,
        tmp_path,
        session=session,
        key=key,
        inputs=inputs,
        platform="linux",
    )

    with pytest.raises(release_fleet.FleetError, match="exact protocol platforms"):
        acceptance.aggregate_platform_evidence(
            session,
            [],
            [],
            key=key,
            inputs=inputs,
        )

    with pytest.raises(release_fleet.FleetError, match="exact protocol platforms"):
        acceptance.aggregate_platform_evidence(
            session,
            [darwin[1], linux[1]],
            [darwin[0], linux[0]],
            key=key,
            inputs=inputs,
        )


def test_receipts_reject_caller_supplied_counts_and_case_digests(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    key, session, inputs = _signed_session(acceptance)
    evidence = [
        _write_authored_platform_evidence(
            acceptance,
            tmp_path,
            session=session,
            key=key,
            inputs=inputs,
            platform=platform,
        )
        for platform in ("darwin",)
    ]
    forged_receipts = [json.loads(json.dumps(receipt)) for _path, receipt in evidence]
    forged_receipts[0]["payload"]["started"] = 168
    forged_receipts[0]["payload"]["case_result_sha256"] = "f" * 64
    forged_receipts[0] = acceptance._sign(forged_receipts[0]["payload"], key)

    with pytest.raises(release_fleet.FleetError, match="signed shape"):
        acceptance.aggregate_platform_evidence(
            session,
            forged_receipts,
            [path for path, _receipt in evidence],
            key=key,
            inputs=inputs,
        )


def test_aggregation_reopens_and_hashes_the_immutable_manifest(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    key, session, inputs = _signed_session(acceptance)
    evidence = [
        _write_authored_platform_evidence(
            acceptance,
            tmp_path,
            session=session,
            key=key,
            inputs=inputs,
            platform=platform,
        )
        for platform in ("darwin",)
    ]
    evidence[0][0].chmod(0o644)
    document = json.loads(evidence[0][0].read_text(encoding="utf-8"))
    document["session_id"] = "f" * 64
    evidence[0][0].write_text(json.dumps(document), encoding="utf-8")
    evidence[0][0].chmod(0o444)

    with pytest.raises(release_fleet.FleetError, match="manifest hash"):
        acceptance.aggregate_platform_evidence(
            session,
            [receipt for _path, receipt in evidence],
            [path for path, _receipt in evidence],
            key=key,
            inputs=inputs,
        )


@pytest.mark.parametrize("mutation", ("missing", "extra", "substitution", "duplicate"))
def test_aggregation_requires_the_frozen_unique_final_starts_per_platform(
    mutation: str,
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    key, session, inputs = _signed_session(acceptance)
    darwin = _manifest_document(inputs=inputs, platform="darwin")
    cases = darwin["report"]["cases"]
    assert isinstance(cases, list)
    if mutation == "missing":
        cases.pop()
    elif mutation == "extra":
        cases.append(_case_document(_case("v9.9.9", "darwin")))
    elif mutation == "substitution":
        cases[0] = _case_document(_case("v9.9.9", "darwin"))
    else:
        cases[0] = dict(cases[1])
    evidence = [
        _write_authored_platform_evidence(
            acceptance,
            tmp_path,
            session=session,
            key=key,
            inputs=inputs,
            platform="darwin",
            manifest=darwin,
        )
    ]

    with pytest.raises(release_fleet.FleetError, match="historic release|case count"):
        acceptance.aggregate_platform_evidence(
            session,
            [receipt for _path, receipt in evidence],
            [path for path, _receipt in evidence],
            key=key,
            inputs=inputs,
        )


def test_aggregation_rejects_mixed_sessions_and_platform_spoofing(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    key, session, inputs = _signed_session(acceptance)
    wrong_session = _manifest_document(
        inputs=inputs,
        platform="darwin",
        session_id="f" * 64,
    )
    spoofed = _manifest_document(inputs=inputs, platform="darwin")
    spoofed_report = spoofed["report"]
    assert isinstance(spoofed_report, dict)
    spoofed_report["platforms"] = ["linux"]
    wrong_session_root = tmp_path / "wrong-session"
    wrong_session_root.mkdir()
    wrong_session_evidence = _write_authored_platform_evidence(
        acceptance,
        wrong_session_root,
        session=session,
        key=key,
        inputs=inputs,
        platform="darwin",
        manifest=wrong_session,
    )

    with pytest.raises(release_fleet.FleetError, match="session"):
        acceptance.aggregate_platform_evidence(
            session,
            [wrong_session_evidence[1]],
            [wrong_session_evidence[0]],
            key=key,
            inputs=inputs,
        )

    spoofed_root = tmp_path / "spoofed-platform"
    spoofed_root.mkdir()
    spoofed_evidence = _write_authored_platform_evidence(
        acceptance,
        spoofed_root,
        session=session,
        key=key,
        inputs=inputs,
        platform="darwin",
        manifest=spoofed,
    )
    with pytest.raises(release_fleet.FleetError, match="running platform"):
        acceptance.aggregate_platform_evidence(
            session,
            [spoofed_evidence[1]],
            [spoofed_evidence[0]],
            key=key,
            inputs=inputs,
        )


def test_aggregation_rejects_preflight_authored_symlink_and_writable_manifests(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    key, session, inputs = _signed_session(acceptance)
    preflight = _manifest_document(inputs=inputs, platform="darwin")
    preflight["authoritative_executor_run"] = False
    evidence = [
        _write_authored_platform_evidence(
            acceptance,
            tmp_path,
            session=session,
            key=key,
            inputs=inputs,
            platform="darwin",
            manifest=preflight,
        )
    ]

    with pytest.raises(release_fleet.FleetError, match="manifest shape"):
        acceptance.aggregate_platform_evidence(
            session,
            [receipt for _path, receipt in evidence],
            [path for path, _receipt in evidence],
            key=key,
            inputs=inputs,
        )

    real = evidence[0][0]
    link = tmp_path / "linked.manifest.json"
    link.symlink_to(real)
    with pytest.raises(release_fleet.FleetError, match="immutable"):
        acceptance.aggregate_platform_evidence(
            session,
            [receipt for _path, receipt in evidence],
            [link],
            key=key,
            inputs=inputs,
        )

    real.chmod(0o644)
    with pytest.raises(release_fleet.FleetError, match="immutable"):
        acceptance.aggregate_platform_evidence(
            session,
            [receipt for _path, receipt in evidence],
            [real],
            key=key,
            inputs=inputs,
        )


def _case_document(case: release_fleet.CaseResult) -> dict[str, object]:
    return {field.name: getattr(case, field.name) for field in fields(case)}


def _write_process_entry_evidence(
    output: Path,
    starting_tag: str,
    releases: Sequence[release_fleet.DistributionRelease],
) -> None:
    """Leave the evidence a real journey's process probe leaves behind.

    The floor in `collect_platform_runs` reads the artifact rather than the
    intention, so a stand-in journey has to produce the artifact or it is not
    standing in for anything.
    """

    matched = [release for release in releases if release.tag == starting_tag]
    assert len(matched) == 1, f"unknown test release: {starting_tag}"
    root = (
        output
        / f"{release_fleet.safe_case_name(matched[0])}"
        f"{release_fleet.BRIDGE_PROCESS_ENTRY_SUFFIX}"
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / "bridge-process-entry.json").write_text("{}\n", encoding="utf-8")


def _bridge_pair(root: Path) -> tuple[Path, Path]:
    asset = root / "dex-update-bridge-v1.81.1.py"
    checksum = root / f"{asset.name}.sha256"
    asset.write_bytes(b"released bridge bytes\n")
    checksum.write_text(
        f"{hashlib.sha256(asset.read_bytes()).hexdigest()}  {asset.name}\n",
        encoding="utf-8",
    )
    return asset, checksum


def test_platform_collector_retains_every_live_run_and_exact_counts(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    releases = (
        _release("v1.20.1", "1.20.1", "1"),
        _release("dist/release/v1.80.5-2222222", "1.80.5", "2"),
    )
    created: list[object] = []
    probed: list[tuple[str, bool]] = []
    asset_path, checksum_path = _bridge_pair(tmp_path)

    def journey_runner(
        _repo: Path,
        *,
        output: Path,
        starting_tag: str,
        foundation_tag: str,
        follow_up_tag: str,
        bridge_asset: Path,
        bridge_checksum: Path,
        controlled_approvals: bool,
        bridge_process_entry: bool = False,
    ) -> object:
        assert output == tmp_path
        assert foundation_tag == FOUNDATION.tag
        assert follow_up_tag == "dist/release/v1.81.1-3333333"
        assert bridge_asset == asset_path
        assert bridge_checksum == checksum_path
        assert controlled_approvals is True
        probed.append((starting_tag, bridge_process_entry))
        if bridge_process_entry:
            _write_process_entry_evidence(output, starting_tag, releases)
        run = SimpleNamespace(case=_case_document(_case(starting_tag, "darwin")))
        created.append(run)
        return run

    execution = acceptance.collect_platform_runs(
        tmp_path,
        output=tmp_path,
        releases=releases,
        foundation_tag=FOUNDATION.tag,
        follow_up_tag="dist/release/v1.81.1-3333333",
        running_platform="darwin",
        bridge_asset=asset_path,
        bridge_checksum=checksum_path,
        journey_runner=journey_runner,
    )

    assert execution.executor_runs == tuple(created)
    assert [case.starting_tag for case in execution.report.cases] == [release.tag for release in releases]
    assert execution.report.platforms == ("darwin",)
    assert execution.counts == {
        "discovered": 2,
        "started": 2,
        "completed": 2,
        "passed": 2,
        "failed": 0,
    }


def test_the_formal_fleet_probes_the_newest_release_not_the_canary_s_oldest() -> None:
    """The two gates must not be correlated.

    The PR canary probes the oldest of its fixed starts. If the formal fleet
    inherited that choice, both would exercise the same vault shape and neither
    would cover what the other misses: an old pre-split vault stops first at the
    topology approval, while an already-split vault skips it entirely and stops
    at the delivered-release approval instead. Probing only the oldest means no
    gate ever watches the bridge reach the second one as a real process.
    """

    acceptance = _acceptance()
    releases = (
        _release("v1.51.0", "1.51.0", "1"),
        _release("dist/release/v1.80.5-2222222", "1.80.5", "2"),
        _release("v1.81.1", "1.81.1", "3"),
    )

    designated = acceptance.bridge_process_entry_release(releases)

    assert designated is not None
    assert designated.tag == "v1.81.1"
    assert designated.tag != releases[0].tag, "must not inherit the canary's oldest"
    assert acceptance.bridge_process_entry_release(()) is None


def test_the_formal_fleet_does_not_probe_the_pinned_foundation() -> None:
    """Newest can be the foundation itself. That start is the wrong shape.

    The historic cohort is required to contain the exact pinned foundation.
    Its installer fixture already has refs/dex/installed and the split markers
    equal to the bridge pin, so run_bridge takes _foundation_is_installed and
    skips both topology and delivered-release. The process probe would then
    never watch the APPLY gate this change exists to cover.
    """

    acceptance = _acceptance()
    already_split = _release("dist/release/v1.81.15-aaaaaaaa", "1.81.15", "a")
    releases = (
        _release("v1.51.0", "1.51.0", "1"),
        already_split,
        _foundation_release(),
    )

    designated = acceptance.bridge_process_entry_release(releases)

    assert designated is not None
    assert designated.tag == already_split.tag
    assert designated.tag != FOUNDATION.tag
    assert designated.commit != FOUNDATION.commit


def test_a_distinct_same_version_sibling_of_the_foundation_is_still_eligible() -> None:
    """Live newest is semantic v1.81.16, a different tree from the dist pin.

    Installing that sibling does not set refs/dex/installed to the pin, so it
    is the delivered-release shape this gate wants. Excluding every 1.81.16
    identity would skip it for no reason.
    """

    acceptance = _acceptance()
    sibling = _release("v1.81.16", "1.81.16", "s")
    releases = (
        _release("v1.51.0", "1.51.0", "1"),
        _foundation_release(),
        sibling,
    )

    designated = acceptance.bridge_process_entry_release(releases)

    assert designated is not None
    assert designated.tag == sibling.tag
    assert designated.commit != FOUNDATION.commit


def test_a_cohort_that_is_only_the_foundation_has_no_process_probe() -> None:
    acceptance = _acceptance()

    assert acceptance.bridge_process_entry_release((_foundation_release(),)) is None


def test_the_platform_floor_fails_when_only_the_foundation_is_eligible(
    tmp_path: Path,
) -> None:
    """A one-row historic set is legal. It must not look like an empty cohort.

    frozen_cohort_manifest accepts case_count >= 1 as long as the exact pin is
    present. If that row is the pin, designated is None. The floor must still
    fail closed, and the message must name that cause -- treating None as
    "empty, so skip the probe" would go green with zero process starts.
    """

    acceptance = _acceptance()
    releases = (_foundation_release(),)
    asset_path, checksum_path = _bridge_pair(tmp_path)

    def journey_runner(
        _repo: Path,
        *,
        output: Path,
        starting_tag: str,
        foundation_tag: str,
        follow_up_tag: str,
        bridge_asset: Path,
        bridge_checksum: Path,
        controlled_approvals: bool,
        bridge_process_entry: bool = False,
    ) -> object:
        del output, foundation_tag, follow_up_tag, bridge_asset, bridge_checksum
        del controlled_approvals, bridge_process_entry
        return SimpleNamespace(case=_case_document(_case(starting_tag, "darwin")))

    with pytest.raises(acceptance.PlatformFleetFailure) as failure:
        acceptance.collect_platform_runs(
            tmp_path,
            output=tmp_path,
            releases=releases,
            foundation_tag=FOUNDATION.tag,
            follow_up_tag="dist/release/v1.81.17-3333333",
            running_platform="darwin",
            bridge_asset=asset_path,
            bridge_checksum=checksum_path,
            journey_runner=journey_runner,
        )

    assert "no historic start other than the pinned foundation" in str(failure.value)
    assert failure.value.counts["discovered"] == 1


def test_platform_collector_requests_the_process_probe_for_exactly_one_release(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    releases = (
        _release("v1.51.0", "1.51.0", "1"),
        _release("dist/release/v1.80.5-2222222", "1.80.5", "2"),
    )
    asset_path, checksum_path = _bridge_pair(tmp_path)
    requested: list[tuple[str, bool]] = []

    def journey_runner(
        _repo: Path,
        *,
        output: Path,
        starting_tag: str,
        foundation_tag: str,
        follow_up_tag: str,
        bridge_asset: Path,
        bridge_checksum: Path,
        controlled_approvals: bool,
        bridge_process_entry: bool = False,
    ) -> object:
        del foundation_tag, follow_up_tag, bridge_asset, bridge_checksum
        del controlled_approvals
        requested.append((starting_tag, bridge_process_entry))
        if bridge_process_entry:
            _write_process_entry_evidence(output, starting_tag, releases)
        return SimpleNamespace(case=_case_document(_case(starting_tag, "darwin")))

    acceptance.collect_platform_runs(
        tmp_path,
        output=tmp_path,
        releases=releases,
        foundation_tag=FOUNDATION.tag,
        follow_up_tag="dist/release/v1.81.1-3333333",
        running_platform="darwin",
        bridge_asset=asset_path,
        bridge_checksum=checksum_path,
        journey_runner=journey_runner,
    )

    assert requested == [
        ("v1.51.0", False),
        ("dist/release/v1.80.5-2222222", True),
    ]


def test_platform_collector_skips_the_pinned_foundation_when_it_is_newest(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    already_split = _release("dist/release/v1.81.15-aaaaaaaa", "1.81.15", "a")
    foundation = _foundation_release()
    releases = (
        _release("v1.51.0", "1.51.0", "1"),
        already_split,
        foundation,
    )
    asset_path, checksum_path = _bridge_pair(tmp_path)
    requested: list[tuple[str, bool]] = []

    def journey_runner(
        _repo: Path,
        *,
        output: Path,
        starting_tag: str,
        foundation_tag: str,
        follow_up_tag: str,
        bridge_asset: Path,
        bridge_checksum: Path,
        controlled_approvals: bool,
        bridge_process_entry: bool = False,
    ) -> object:
        del foundation_tag, follow_up_tag, bridge_asset, bridge_checksum
        del controlled_approvals
        requested.append((starting_tag, bridge_process_entry))
        if bridge_process_entry:
            _write_process_entry_evidence(output, starting_tag, releases)
        return SimpleNamespace(case=_case_document(_case(starting_tag, "darwin")))

    acceptance.collect_platform_runs(
        tmp_path,
        output=tmp_path,
        releases=releases,
        foundation_tag=FOUNDATION.tag,
        follow_up_tag="dist/release/v1.81.17-3333333",
        running_platform="darwin",
        bridge_asset=asset_path,
        bridge_checksum=checksum_path,
        journey_runner=journey_runner,
    )

    assert requested == [
        ("v1.51.0", False),
        (already_split.tag, True),
        (foundation.tag, False),
    ]


def test_the_platform_floor_fails_a_run_whose_probe_never_executed(
    tmp_path: Path,
) -> None:
    """The load-bearing half: a gate that can silently not run is not a gate.

    This is the exact regression that would occur if the single boolean wiring
    the probe were dropped -- every journey still passes, and without this floor
    the platform run would be green having never started the bridge.
    """

    acceptance = _acceptance()
    releases = (
        _release("v1.51.0", "1.51.0", "1"),
        _release("dist/release/v1.80.5-2222222", "1.80.5", "2"),
    )
    asset_path, checksum_path = _bridge_pair(tmp_path)

    def journey_runner(
        _repo: Path,
        *,
        output: Path,
        starting_tag: str,
        foundation_tag: str,
        follow_up_tag: str,
        bridge_asset: Path,
        bridge_checksum: Path,
        controlled_approvals: bool,
        bridge_process_entry: bool = False,
    ) -> object:
        del output, foundation_tag, follow_up_tag, bridge_asset, bridge_checksum
        del controlled_approvals
        # Exactly the shape of the wiring being deleted: asked for, never done.
        del bridge_process_entry
        return SimpleNamespace(case=_case_document(_case(starting_tag, "darwin")))

    with pytest.raises(acceptance.PlatformFleetFailure) as failure:
        acceptance.collect_platform_runs(
            tmp_path,
            output=tmp_path,
            releases=releases,
            foundation_tag=FOUNDATION.tag,
            follow_up_tag="dist/release/v1.81.1-3333333",
            running_platform="darwin",
            bridge_asset=asset_path,
            bridge_checksum=checksum_path,
            journey_runner=journey_runner,
        )

    assert "no release started the bridge as a top-level process" in str(failure.value)


def test_the_platform_floor_rejects_evidence_from_the_wrong_release(
    tmp_path: Path,
) -> None:
    """Evidence has to belong to the release the fleet designated."""

    acceptance = _acceptance()
    releases = (
        _release("v1.51.0", "1.51.0", "1"),
        _release("dist/release/v1.80.5-2222222", "1.80.5", "2"),
    )
    asset_path, checksum_path = _bridge_pair(tmp_path)

    def journey_runner(
        _repo: Path,
        *,
        output: Path,
        starting_tag: str,
        foundation_tag: str,
        follow_up_tag: str,
        bridge_asset: Path,
        bridge_checksum: Path,
        controlled_approvals: bool,
        bridge_process_entry: bool = False,
    ) -> object:
        del foundation_tag, follow_up_tag, bridge_asset, bridge_checksum
        del controlled_approvals, bridge_process_entry
        # The oldest probes instead of the designated newest.
        if starting_tag == releases[0].tag:
            _write_process_entry_evidence(output, starting_tag, releases)
        return SimpleNamespace(case=_case_document(_case(starting_tag, "darwin")))

    with pytest.raises(acceptance.PlatformFleetFailure) as failure:
        acceptance.collect_platform_runs(
            tmp_path,
            output=tmp_path,
            releases=releases,
            foundation_tag=FOUNDATION.tag,
            follow_up_tag="dist/release/v1.81.1-3333333",
            running_platform="darwin",
            bridge_asset=asset_path,
            bridge_checksum=checksum_path,
            journey_runner=journey_runner,
        )

    assert "does not match the designated release" in str(failure.value)


def test_platform_collector_collects_every_case_failure_before_failing_closed(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    releases = (
        _release("v1.20.1", "1.20.1", "1"),
        _release("dist/release/v1.80.5-2222222", "1.80.5", "2"),
        _release("v1.81.1", "1.81.1", "3"),
    )
    bridge_asset, bridge_checksum = _bridge_pair(tmp_path)
    attempted: list[str] = []

    def journey_runner(
        _repo: Path,
        *,
        output: Path,
        starting_tag: str,
        foundation_tag: str,
        follow_up_tag: str,
        bridge_asset: Path,
        bridge_checksum: Path,
        controlled_approvals: bool,
        bridge_process_entry: bool = False,
    ) -> object:
        del output, foundation_tag, follow_up_tag, bridge_asset, bridge_checksum
        del bridge_process_entry
        assert controlled_approvals is True
        attempted.append(starting_tag)
        if starting_tag in {releases[0].tag, releases[2].tag}:
            raise release_fleet.CaseJourneyFailure(
                starting_tag,
                "synthetic journey failed",
            )
        return SimpleNamespace(case=_case_document(_case(starting_tag, "darwin")))

    with pytest.raises(acceptance.PlatformFleetFailure) as failure:
        acceptance.collect_platform_runs(
            tmp_path,
            output=tmp_path,
            releases=releases,
            foundation_tag=FOUNDATION.tag,
            follow_up_tag="dist/release/v1.81.1-3333333",
            running_platform="darwin",
            bridge_asset=bridge_asset,
            bridge_checksum=bridge_checksum,
            journey_runner=journey_runner,
        )

    assert failure.value.counts == {
        "discovered": 3,
        "started": 3,
        "completed": 1,
        "passed": 1,
        "failed": 2,
    }
    assert attempted == [release.tag for release in releases]
    assert [item.starting_tag for item in failure.value.failures] == [
        releases[0].tag,
        releases[2].tag,
    ]
    diagnostic = json.loads((tmp_path / "platform-failures.json").read_text(encoding="utf-8"))
    assert diagnostic["acceptance"] is False
    assert diagnostic["counts"] == failure.value.counts
    assert diagnostic["groups"] == [
        {
            "count": 2,
            "error_type": "CaseJourneyFailure",
            "signature": failure.value.failures[0].signature,
            "starting_tags": [releases[0].tag, releases[2].tag],
        }
    ]


def test_platform_collector_stops_immediately_on_infrastructure_or_integrity_failure(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    releases = (
        _release("v1.20.1", "1.20.1", "1"),
        _release("dist/release/v1.80.5-2222222", "1.80.5", "2"),
        _release("v1.81.1", "1.81.1", "3"),
    )
    bridge_asset, bridge_checksum = _bridge_pair(tmp_path)
    attempted: list[str] = []

    def journey_runner(_repo: Path, *, starting_tag: str, **_kwargs) -> object:
        attempted.append(starting_tag)
        if starting_tag == releases[1].tag:
            raise release_fleet.FleetError("shared protocol identity changed")
        return SimpleNamespace(case=_case_document(_case(starting_tag, "darwin")))

    with pytest.raises(
        acceptance.PlatformFleetFailure,
        match="infrastructure or integrity failure",
    ) as failure:
        acceptance.collect_platform_runs(
            tmp_path,
            output=tmp_path,
            releases=releases,
            foundation_tag=FOUNDATION.tag,
            follow_up_tag="dist/release/v1.81.1-3333333",
            running_platform="darwin",
            bridge_asset=bridge_asset,
            bridge_checksum=bridge_checksum,
            journey_runner=journey_runner,
        )

    assert attempted == [releases[0].tag, releases[1].tag]
    assert failure.value.counts == {
        "discovered": 3,
        "started": 2,
        "completed": 1,
        "passed": 1,
        "failed": 1,
    }
    assert failure.value.failures == ()
    assert not (tmp_path / "platform-failures.json").exists()


def test_platform_collector_stops_immediately_on_public_route_drift(
    tmp_path: Path,
) -> None:
    from scripts import release_fleet_executor

    acceptance = _acceptance()
    releases = (
        _release("v1.20.1", "1.20.1", "1"),
        _release("dist/release/v1.80.5-2222222", "1.80.5", "2"),
        _release("v1.81.1", "1.81.1", "3"),
    )
    bridge_asset, bridge_checksum = _bridge_pair(tmp_path)
    attempted: list[str] = []
    expected = {
        "tag": "dist/release/v1.81.17-aaaaaaa",
        "tag_object": "b" * 40,
        "commit": "a" * 40,
        "tree": "c" * 40,
        "version": "1.81.17",
        "channel": "stable",
    }
    delivered = {
        "tag": "dist/release/v1.81.18-ddddddd",
        "tag_object": "e" * 40,
        "commit": "d" * 40,
        "tree": "f" * 40,
        "version": "1.81.18",
        "channel": "stable",
    }

    def journey_runner(_repo: Path, *, starting_tag: str, **_kwargs) -> object:
        attempted.append(starting_tag)
        if starting_tag == releases[1].tag:
            raise release_fleet_executor.PublicRouteDriftError(expected, delivered)
        return SimpleNamespace(case=_case_document(_case(starting_tag, "darwin")))

    with pytest.raises(
        acceptance.PlatformFleetFailure,
        match="public release route drifted",
    ) as failure:
        acceptance.collect_platform_runs(
            tmp_path,
            output=tmp_path,
            releases=releases,
            foundation_tag=FOUNDATION.tag,
            follow_up_tag=expected["tag"],
            running_platform="darwin",
            bridge_asset=bridge_asset,
            bridge_checksum=bridge_checksum,
            journey_runner=journey_runner,
        )

    assert attempted == [releases[0].tag, releases[1].tag]
    assert failure.value.counts == {
        "discovered": 3,
        "started": 2,
        "completed": 1,
        "passed": 1,
        "failed": 1,
    }
    assert failure.value.failures == ()
    assert not (tmp_path / "platform-failures.json").exists()


def _immutable_foundation() -> release_fleet.ImmutableRelease:
    identity = FOUNDATION.identity()
    return release_fleet.ImmutableRelease(
        identity["tag"],
        identity["tag_object"],
        identity["commit"],
        identity["tree"],
        identity["version"],
    )


def _immutable_follow_up() -> release_fleet.ImmutableRelease:
    return release_fleet.ImmutableRelease(
        "dist/release/v1.81.1-3333333",
        "3" * 40,
        "3333333" + "4" * 33,
        "5" * 40,
        "1.81.1",
    )


def test_forged_executor_runs_cannot_mint_a_platform_receipt(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    key, session, inputs = _signed_session(acceptance)
    running_platform = acceptance._running_platform()
    bridge_asset, bridge_checksum = _bridge_pair(tmp_path)

    def journey_runner(
        _repo: Path,
        *,
        output: Path,
        starting_tag: str,
        bridge_process_entry: bool = False,
        **_kwargs: object,
    ) -> object:
        if bridge_process_entry:
            _write_process_entry_evidence(output, starting_tag, inputs.releases)
        return SimpleNamespace(
            case=_case_document(_case(starting_tag, running_platform))
        )

    execution = acceptance.collect_platform_runs(
        tmp_path,
        output=tmp_path,
        releases=inputs.releases,
        foundation_tag=FOUNDATION.tag,
        follow_up_tag="dist/release/v1.81.1-3333333",
        running_platform=running_platform,
        bridge_asset=bridge_asset,
        bridge_checksum=bridge_checksum,
        journey_runner=journey_runner,
    )

    with pytest.raises(release_fleet.FleetError, match="executor authority"):
        acceptance.finalize_live_platform_execution(
            execution,
            repo=tmp_path,
            evidence_root=tmp_path,
            inputs=inputs,
            session=session,
            key=key,
        )
    assert not (tmp_path / "platform-manifest.json").exists()
    assert not (tmp_path / "platform-receipt.json").exists()


def test_live_finalizer_does_not_accept_caller_counts_digests_or_start_tags() -> None:
    acceptance = _acceptance()

    assert set(inspect.signature(acceptance.finalize_live_platform_execution).parameters) == {
        "execution",
        "repo",
        "evidence_root",
        "inputs",
        "session",
        "key",
    }


def test_changed_evidence_validator_cannot_mint_a_platform_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    key, session, inputs = _signed_session(acceptance)
    running_platform = acceptance._running_platform()
    bridge_asset, bridge_checksum = _bridge_pair(tmp_path)
    releases = (
        _release("v1.20.1", "1.20.1", "1"),
        _release("dist/release/v1.80.5-2222222", "1.80.5", "2"),
    )

    def journey_runner(
        _repo: Path,
        *,
        output: Path,
        starting_tag: str,
        bridge_process_entry: bool = False,
        **_kwargs: object,
    ) -> object:
        if bridge_process_entry:
            _write_process_entry_evidence(output, starting_tag, releases)
        return SimpleNamespace(
            case=_case_document(_case(starting_tag, running_platform))
        )

    execution = acceptance.collect_platform_runs(
        tmp_path,
        output=tmp_path,
        releases=releases,
        foundation_tag=FOUNDATION.tag,
        follow_up_tag="dist/release/v1.81.1-3333333",
        running_platform=running_platform,
        bridge_asset=bridge_asset,
        bridge_checksum=bridge_checksum,
        journey_runner=journey_runner,
    )
    monkeypatch.setattr(release_fleet, "assert_evidence_bound", lambda *args, **kwargs: None)

    with pytest.raises(release_fleet.FleetError, match="validator changed"):
        acceptance.finalize_live_platform_execution(
            execution,
            repo=tmp_path,
            evidence_root=tmp_path,
            inputs=inputs,
            session=session,
            key=key,
        )


def test_live_finalization_rejects_a_spoofed_host_platform(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    key, session, inputs = _signed_session(acceptance)
    running_platform = acceptance._running_platform()
    spoofed_platform = "linux" if running_platform == "darwin" else "darwin"
    tag = "v1.20.1"
    execution = acceptance.PlatformExecution(
        release_fleet.AcceptanceReport(
            foundation_tag=FOUNDATION.tag,
            follow_up_tag="dist/release/v1.81.1-3333333",
            cases=(_case(tag, spoofed_platform),),
            platforms=(spoofed_platform,),
        ),
        (),
        {
            "discovered": len(inputs.releases),
            "started": len(inputs.releases),
            "completed": len(inputs.releases),
            "passed": len(inputs.releases),
            "failed": 0,
        },
    )

    with pytest.raises(release_fleet.FleetError, match="running platform"):
        acceptance.finalize_live_platform_execution(
            execution,
            repo=tmp_path,
            evidence_root=tmp_path,
            inputs=inputs,
            session=session,
            key=key,
        )
    assert not (tmp_path / "platform-manifest.json").exists()
    assert not (tmp_path / "platform-receipt.json").exists()


def test_platform_controller_creates_one_private_non_resumable_run_root(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    root = tmp_path / "run"

    acceptance._create_private_run_root(root)

    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    with pytest.raises(release_fleet.FleetError, match="already exists"):
        acceptance._create_private_run_root(root)

    unsafe_parent = tmp_path / "linked-parent"
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    unsafe_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(release_fleet.FleetError, match="parent is unsafe"):
        acceptance._create_private_run_root(unsafe_parent / "run")


def _platform_cli_arguments(
    root: Path,
    *,
    foundation: release_fleet.ImmutableRelease,
    follow_up: release_fleet.ImmutableRelease,
    session_path: Path,
    key_path: Path,
    output: Path,
) -> list[str]:
    return [
        "platform",
        "--repo",
        str(root),
        "--cohort",
        str(root / "cohort.json"),
        "--foundation-tag",
        foundation.tag,
        "--follow-up-tag",
        follow_up.tag,
        "--session",
        str(session_path),
        "--key",
        str(key_path),
        "--output",
        str(output),
    ]


def _write_platform_session(
    root: Path,
    *,
    acceptance,
) -> tuple[Path, Path, object]:
    key, session, inputs = _signed_session(acceptance)
    session_path = root / "session.json"
    key_path = root / "session.key"
    session_path.write_bytes(acceptance._json_bytes(session))
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    return session_path, key_path, inputs


def test_platform_cli_requires_a_bridge_asset_and_checksum(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    session_path, key_path, inputs = _write_platform_session(tmp_path, acceptance=acceptance)
    monkeypatch.setattr(acceptance, "load_fleet_inputs", lambda *args, **kwargs: inputs)

    with pytest.raises(SystemExit):
        acceptance.main(
            _platform_cli_arguments(
                tmp_path,
                foundation=inputs.foundation,
                follow_up=inputs.follow_up,
                session_path=session_path,
                key_path=key_path,
                output=tmp_path / "run",
            )
        )


def test_platform_cli_rejects_a_tampered_bridge_pair_before_starting_a_journey(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    session_path, key_path, inputs = _write_platform_session(tmp_path, acceptance=acceptance)
    bridge_asset, bridge_checksum = _bridge_pair(tmp_path)
    run_root = tmp_path / "run"
    monkeypatch.setattr(acceptance, "load_fleet_inputs", lambda *args, **kwargs: inputs)
    monkeypatch.setattr(acceptance, "_running_platform", lambda: "darwin")
    monkeypatch.setattr(acceptance, "_verify_public_follow_up_release", lambda _release: None, raising=False)
    monkeypatch.setattr(
        release_fleet,
        "_verify_standalone_bridge_asset",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            release_fleet.FleetError("standalone released bridge checksum is invalid")
        ),
    )
    monkeypatch.setattr(
        acceptance,
        "collect_platform_runs",
        lambda *args, **kwargs: pytest.fail("journey collector must not start"),
    )

    with pytest.raises(release_fleet.FleetError, match="checksum is invalid"):
        acceptance.main(
            _platform_cli_arguments(
                tmp_path,
                foundation=inputs.foundation,
                follow_up=inputs.follow_up,
                session_path=session_path,
                key_path=key_path,
                output=run_root,
            )
            + [
                "--bridge-asset",
                str(bridge_asset),
                "--bridge-checksum",
                str(bridge_checksum),
            ]
        )

    assert not run_root.exists()


def test_platform_cli_rejects_a_follow_up_not_advertised_by_the_public_remote(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    session_path, key_path, inputs = _write_platform_session(tmp_path, acceptance=acceptance)
    bridge_asset, bridge_checksum = _bridge_pair(tmp_path)
    monkeypatch.setattr(acceptance, "load_fleet_inputs", lambda *args, **kwargs: inputs)
    monkeypatch.setattr(acceptance, "_running_platform", lambda: "darwin")
    monkeypatch.setattr(release_fleet, "_verify_standalone_bridge_asset", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        acceptance,
        "_verify_public_follow_up_release",
        lambda _release: (_ for _ in ()).throw(
            release_fleet.FleetError("follow-up release is not advertised by the public stable remote")
        ),
        raising=False,
    )

    with pytest.raises(release_fleet.FleetError, match="not advertised"):
        acceptance.main(
            _platform_cli_arguments(
                tmp_path,
                foundation=inputs.foundation,
                follow_up=inputs.follow_up,
                session_path=session_path,
                key_path=key_path,
                output=tmp_path / "run",
            )
            + ["--bridge-asset", str(bridge_asset), "--bridge-checksum", str(bridge_checksum)]
        )
    assert not (tmp_path / "run").exists()


def test_platform_cli_rejects_a_bridge_pair_not_matching_the_public_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    session_path, key_path, inputs = _write_platform_session(tmp_path, acceptance=acceptance)
    bridge_asset, bridge_checksum = _bridge_pair(tmp_path)
    run_root = tmp_path / "run"
    monkeypatch.setattr(acceptance, "load_fleet_inputs", lambda *args, **kwargs: inputs)
    monkeypatch.setattr(acceptance, "_running_platform", lambda: "darwin")
    monkeypatch.setattr(acceptance, "_verify_public_follow_up_release", lambda _release: None, raising=False)
    monkeypatch.setattr(release_fleet, "_verify_standalone_bridge_asset", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        acceptance,
        "_verify_public_bridge_release_asset",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            release_fleet.FleetError("bridge asset does not match the public GitHub release")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        acceptance,
        "collect_platform_runs",
        lambda *args, **kwargs: pytest.fail("journey collector must not start"),
    )

    with pytest.raises(release_fleet.FleetError, match="public GitHub release"):
        acceptance.main(
            _platform_cli_arguments(
                tmp_path,
                foundation=inputs.foundation,
                follow_up=inputs.follow_up,
                session_path=session_path,
                key_path=key_path,
                output=run_root,
            )
            + ["--bridge-asset", str(bridge_asset), "--bridge-checksum", str(bridge_checksum)]
        )

    assert not run_root.exists()


def test_public_follow_up_release_requires_the_exact_canonical_remote_tag_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acceptance = _acceptance()
    release = _immutable_follow_up()
    calls: list[list[str]] = []

    def advertised(arguments, **_kwargs):
        calls.append(arguments)
        return SimpleNamespace(
            returncode=0,
            stdout=f"{release.tag_object}\trefs/tags/{release.tag}\n",
        )

    monkeypatch.setattr(acceptance.subprocess, "run", advertised)
    acceptance._verify_public_follow_up_release(release)

    assert calls == [
        [
            "git",
            "-c",
            "credential.helper=",
            "-c",
            "protocol.file.allow=never",
            "ls-remote",
            "--refs",
            "--tags",
            acceptance.CANONICAL_PUBLIC_REMOTE,
            f"refs/tags/{release.tag}",
        ]
    ]

    monkeypatch.setattr(
        acceptance.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=f"{'0' * 40}\trefs/tags/{release.tag}\n"),
    )
    with pytest.raises(release_fleet.FleetError, match="not advertised"):
        acceptance._verify_public_follow_up_release(release)


def test_public_bridge_assets_must_match_the_public_stable_release_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    release = _immutable_follow_up()
    bridge_asset, bridge_checksum = _bridge_pair(tmp_path)
    public_assets = {
        bridge_asset.name: bridge_asset.read_bytes(),
        bridge_checksum.name: bridge_checksum.read_bytes(),
    }
    stable_releases: list[release_fleet.ImmutableRelease] = []

    def public_bytes(url: str, **_kwargs) -> bytes:
        for name, content in public_assets.items():
            if url.endswith(name):
                return content
        pytest.fail(f"unexpected public URL: {url}")

    monkeypatch.setattr(acceptance, "_verify_public_stable_release", stable_releases.append)
    monkeypatch.setattr(acceptance, "_read_public_bytes", public_bytes)
    acceptance._verify_public_bridge_release_asset(
        release,
        bridge_asset=bridge_asset,
        bridge_checksum=bridge_checksum,
    )

    assert stable_releases == [release]
    bridge_asset.write_bytes(b"tampered controller copy\n")
    with pytest.raises(release_fleet.FleetError, match="public GitHub release"):
        acceptance._verify_public_bridge_release_asset(
            release,
            bridge_asset=bridge_asset,
            bridge_checksum=bridge_checksum,
        )



def test_public_stable_release_requires_the_exact_latest_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acceptance = _acceptance()
    release = _immutable_follow_up()

    class PublicResponse:
        def __init__(self, final_url: str, status: int = 200) -> None:
            self._final_url = final_url
            self._status = status

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def geturl(self) -> str:
            return self._final_url

        def getcode(self) -> int:
            return self._status

    class PublicOpener:
        def __init__(
            self,
            handler,
            *,
            redirects: tuple[str, ...],
            final_url: str,
            status: int = 200,
        ) -> None:
            self._handler = handler
            self._redirects = redirects
            self._final_url = final_url
            self._status = status

        def open(self, request, **_kwargs):
            current = request
            for redirect in self._redirects:
                current = self._handler.redirect_request(
                    current,
                    None,
                    302,
                    "Found",
                    {},
                    redirect,
                )
            return PublicResponse(self._final_url, self._status)

    expected = acceptance.CANONICAL_PUBLIC_RELEASE_PAGE.format(version=release.version)
    monkeypatch.setattr(
        acceptance.urllib.request,
        "build_opener",
        lambda handler: PublicOpener(handler, redirects=(expected,), final_url=expected),
    )
    acceptance._verify_public_stable_release(release)

    hostile_urls = (
        acceptance.CANONICAL_PUBLIC_LATEST_RELEASE,
        acceptance.CANONICAL_PUBLIC_RELEASE_PAGE.format(version="1.81.0"),
        f"https://example.com/davekilleen/Dex/releases/tag/v{release.version}",
        f"http://github.com/davekilleen/Dex/releases/tag/v{release.version}",
        f"https://github.com:443/davekilleen/Dex/releases/tag/v{release.version}",
        f"https://user:@github.com/davekilleen/Dex/releases/tag/v{release.version}",
        f"https://github.com/DaveKilleen/Dex/releases/tag/v{release.version}",
        f"https://github.com/davekilleen/dex/releases/tag/v{release.version}",
        f"https://github.com/davekilleen/Dex/releases/tag/v{release.version}/",
        f"https://github.com/davekilleen/Dex/releases/tag/v{release.version}?stable=true",
        f"https://github.com/davekilleen/Dex/releases/tag/v{release.version}#release",
        "https://github.com/davekilleen/Dex/releases/tag/v%31.81.1",
        f"https://github.com/davekilleen/Dex/releases/tag/prefix-v{release.version}",
        f"https://github.com/davekilleen/Dex/releases/tag/v{release.version}-suffix",
        f"https://github.com/davekilleen/Dex/other/tag/v{release.version}",
    )
    for hostile_url in hostile_urls:
        monkeypatch.setattr(
            acceptance.urllib.request,
            "build_opener",
            lambda handler, _url=hostile_url: PublicOpener(
                handler,
                redirects=(_url,),
                final_url=_url,
            ),
        )
        with pytest.raises(release_fleet.FleetError, match="latest public stable"):
            acceptance._verify_public_stable_release(release)

    monkeypatch.setattr(
        acceptance.urllib.request,
        "build_opener",
        lambda handler: PublicOpener(handler, redirects=(), final_url=expected),
    )
    with pytest.raises(release_fleet.FleetError, match="latest public stable"):
        acceptance._verify_public_stable_release(release)

    monkeypatch.setattr(
        acceptance.urllib.request,
        "build_opener",
        lambda handler: PublicOpener(
            handler,
            redirects=(expected, expected),
            final_url=expected,
        ),
    )
    with pytest.raises(release_fleet.FleetError, match="latest public stable"):
        acceptance._verify_public_stable_release(release)

    monkeypatch.setattr(
        acceptance.urllib.request,
        "build_opener",
        lambda handler: PublicOpener(
            handler,
            redirects=(expected,),
            final_url=expected,
            status=204,
        ),
    )
    with pytest.raises(release_fleet.FleetError, match="latest public stable"):
        acceptance._verify_public_stable_release(release)

    class UnavailableOpener:
        def open(self, request, **_kwargs):
            raise urllib.error.HTTPError(
                request.full_url,
                403,
                "forbidden",
                {},
                None,
            )

    monkeypatch.setattr(
        acceptance.urllib.request,
        "build_opener",
        lambda _handler: UnavailableOpener(),
        )
    with pytest.raises(release_fleet.FleetError, match="public stable GitHub release is unavailable"):
        acceptance._verify_public_stable_release(release)


def test_public_bridge_verification_does_not_depend_on_rate_limited_release_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    release = _immutable_follow_up()
    bridge_asset, bridge_checksum = _bridge_pair(tmp_path)
    public_assets = {
        bridge_asset.name: bridge_asset.read_bytes(),
        bridge_checksum.name: bridge_checksum.read_bytes(),
    }
    calls: list[str] = []

    class PublicResponse:
        def __init__(self, *, url: str, content: bytes = b"") -> None:
            self._url = url
            self._content = content

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def geturl(self) -> str:
            return self._url

        def getcode(self) -> int:
            return 200

        def read(self, _limit: int) -> bytes:
            return self._content

    def public_urlopen(request, **_kwargs):
        url = request.full_url
        calls.append(url)
        if url.startswith("https://api.github.com/"):
            raise urllib.error.HTTPError(url, 403, "rate limit exceeded", {}, None)
        if url == acceptance.CANONICAL_PUBLIC_LATEST_RELEASE:
            return PublicResponse(
                url=f"https://github.com/davekilleen/Dex/releases/tag/v{release.version}"
            )
        for name, content in public_assets.items():
            if url.endswith(name):
                return PublicResponse(url=url, content=content)
        pytest.fail(f"unexpected public URL: {url}")

    class PublicOpener:
        def __init__(self, handler) -> None:
            self._handler = handler

        def open(self, request, **_kwargs):
            calls.append(request.full_url)
            expected = acceptance.CANONICAL_PUBLIC_RELEASE_PAGE.format(version=release.version)
            self._handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                expected,
            )
            return PublicResponse(url=expected)

    monkeypatch.setattr(
        acceptance.urllib.request,
        "build_opener",
        lambda handler: PublicOpener(handler),
    )
    monkeypatch.setattr(acceptance.urllib.request, "urlopen", public_urlopen)
    acceptance._verify_public_bridge_release_asset(
        release,
        bridge_asset=bridge_asset,
        bridge_checksum=bridge_checksum,
    )

    assert not any(url.startswith("https://api.github.com/") for url in calls)


def test_platform_cli_preverifies_and_passes_the_bridge_pair_to_every_journey(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    session_path, key_path, inputs = _write_platform_session(tmp_path, acceptance=acceptance)
    bridge_asset, bridge_checksum = _bridge_pair(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(acceptance, "load_fleet_inputs", lambda *args, **kwargs: inputs)
    monkeypatch.setattr(acceptance, "_running_platform", lambda: "darwin")
    monkeypatch.setattr(acceptance, "_verify_public_follow_up_release", lambda _release: None, raising=False)
    monkeypatch.setattr(
        acceptance,
        "_verify_public_bridge_release_asset",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    def verify_asset(*args, **kwargs):
        captured["verified"] = (args, kwargs)
        return {"source": "released-standalone-asset"}

    def collect(*args, **kwargs):
        captured["collect"] = (args, kwargs)
        case_count = len(inputs.releases)
        return SimpleNamespace(
            report=SimpleNamespace(platforms=("darwin",)),
            counts={
                "discovered": case_count,
                "started": case_count,
                "completed": case_count,
                "passed": case_count,
                "failed": 0,
            },
        )

    monkeypatch.setattr(release_fleet, "_verify_standalone_bridge_asset", verify_asset)
    monkeypatch.setattr(acceptance, "collect_platform_runs", collect)
    monkeypatch.setattr(
        acceptance,
        "finalize_live_platform_execution",
        lambda *_args, **_kwargs: {
            "manifest_output": "platform-manifest.json",
            "receipt_output": "platform-receipt.json",
            "manifest_sha256": "a" * 64,
        },
    )

    assert (
        acceptance.main(
            _platform_cli_arguments(
                tmp_path,
                foundation=inputs.foundation,
                follow_up=inputs.follow_up,
                session_path=session_path,
                key_path=key_path,
                output=tmp_path / "run",
            )
            + [
                "--bridge-asset",
                str(bridge_asset),
                "--bridge-checksum",
                str(bridge_checksum),
            ]
        )
        == 0
    )
    assert captured["verified"][1] == {
        "source_commit": inputs.source_commit,
        "follow_up": inputs.follow_up,
        "protocol": inputs.protocol,
        "bridge_asset": bridge_asset,
        "bridge_checksum": bridge_checksum,
    }
    assert captured["collect"][1]["bridge_asset"] == bridge_asset
    assert captured["collect"][1]["bridge_checksum"] == bridge_checksum


def test_session_key_file_is_private_and_rejects_symlinks(tmp_path: Path) -> None:
    acceptance = _acceptance()
    key_path = tmp_path / "acceptance.key"
    key = bytes(range(32))

    acceptance.write_session_key(key_path, key=key)

    assert acceptance.read_session_key(key_path) == key
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    with pytest.raises(release_fleet.FleetError, match="already exists"):
        acceptance.write_session_key(key_path, key=key)

    key_path.unlink()
    target = tmp_path / "target.key"
    target.write_bytes(key)
    key_path.symlink_to(target)
    with pytest.raises(release_fleet.FleetError, match="unsafe"):
        acceptance.read_session_key(key_path)


def test_cohort_cli_writes_the_current_public_tree_manifest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    acceptance = _acceptance()
    repository = Path(__file__).resolve().parents[2]
    output = tmp_path / "historic-through-v1.81.0.json"

    exit_code = acceptance.main(["cohort", "--repo", str(repository), "--output", str(output)])

    result = json.loads(capsys.readouterr().out)
    manifest = json.loads(output.read_text(encoding="utf-8"))
    case_count = len(manifest["cases"])
    assert exit_code == 0
    assert result == {
        "acceptance": False,
        "case_count": case_count,
        "foundation_tag": FOUNDATION.tag,
        "outcome": "HISTORIC_COHORT_FROZEN",
        "output": str(output),
    }
    assert manifest["case_count"] == case_count


def test_acceptance_source_is_bound_to_exact_publisher_commit_bytes(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    repository = tmp_path / "publisher"
    source = repository / "scripts" / "release_fleet_acceptance.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(Path(acceptance.__file__).read_bytes())
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Dex Fleet Test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "config",
            "user.email",
            "fleet@example.com",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(repository), "add", str(source)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "exact publisher source"],
        check=True,
    )
    exact_commit = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    digest = acceptance.verify_acceptance_source_bound(repository, exact_commit)

    assert digest == hashlib.sha256(source.read_bytes()).hexdigest()
    source.write_text("# changed publisher source\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", str(source)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "changed publisher source"],
        check=True,
    )
    changed_commit = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with pytest.raises(release_fleet.FleetError, match="acceptance orchestrator bytes"):
        acceptance.verify_acceptance_source_bound(repository, changed_commit)


def test_full_command_surface_aggregates_evidence_without_minting_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    acceptance = _acceptance()
    releases = tuple(
        _release(f"v1.0.{index}", f"1.0.{index}", f"{index % 10}")
        for index in range(1, 4)
    )
    foundation = _immutable_foundation()
    follow_up = _immutable_follow_up()
    protocol = SimpleNamespace(platforms=("darwin",))
    inputs = acceptance.FleetInputs(
        releases=releases,
        foundation=foundation,
        follow_up=follow_up,
        protocol=protocol,
        source_commit="c" * 40,
        acceptance_source_sha256="d" * 64,
        cohort_sha256="a" * 64,
    )
    monkeypatch.setattr(acceptance, "load_fleet_inputs", lambda *args, **kwargs: inputs)
    session_path = tmp_path / "session.json"
    key_path = tmp_path / "session.key"

    assert (
        acceptance.main(
            [
                "session",
                "--repo",
                str(tmp_path),
                "--cohort",
                str(tmp_path / "cohort.json"),
                "--foundation-tag",
                foundation.tag,
                "--follow-up-tag",
                follow_up.tag,
                "--session-output",
                str(session_path),
                "--key-output",
                str(key_path),
            ]
        )
        == 0
    )
    session = json.loads(session_path.read_text(encoding="utf-8"))
    capsys.readouterr()
    bridge_asset, bridge_checksum = _bridge_pair(tmp_path)

    def collect(*args, running_platform: str, **kwargs):
        del args, kwargs
        case_count = len(inputs.releases)
        return SimpleNamespace(
            report=SimpleNamespace(platforms=(running_platform,)),
            counts={
                "discovered": case_count,
                "started": case_count,
                "completed": case_count,
                "passed": case_count,
                "failed": 0,
            },
        )

    def finalize(execution, **kwargs):
        platform = execution.report.platforms[0]
        manifest = _manifest_document(
            inputs=inputs,
            platform=platform,
            session_id=kwargs["session"]["payload"]["session_id"],
        )
        manifest_bytes = acceptance._json_bytes(manifest)
        manifest_output = kwargs["evidence_root"] / acceptance.PLATFORM_MANIFEST_NAME
        receipt_output = kwargs["evidence_root"] / acceptance.PLATFORM_RECEIPT_NAME
        manifest_output.write_bytes(manifest_bytes)
        manifest_output.chmod(0o444)
        receipt = acceptance._sign(
            {
                "schema_version": 1,
                "session_id": kwargs["session"]["payload"]["session_id"],
                "platform": platform,
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            },
            kwargs["key"],
        )
        receipt_output.write_bytes(acceptance._json_bytes(receipt))
        receipt_output.chmod(0o444)
        return {
            "acceptance": False,
            "platform": platform,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "manifest_output": str(manifest_output),
            "receipt_output": str(receipt_output),
        }

    monkeypatch.setattr(acceptance, "collect_platform_runs", collect)
    monkeypatch.setattr(acceptance, "finalize_live_platform_execution", finalize)
    monkeypatch.setattr(
        release_fleet,
        "_verify_standalone_bridge_asset",
        lambda *args, **kwargs: {"source": "released-standalone-asset"},
    )
    monkeypatch.setattr(acceptance, "_verify_public_follow_up_release", lambda _release: None, raising=False)
    monkeypatch.setattr(
        acceptance,
        "_verify_public_bridge_release_asset",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    receipt_paths: list[Path] = []
    manifest_paths: list[Path] = []
    for platform in ("darwin",):
        monkeypatch.setattr(acceptance, "_running_platform", lambda value=platform: value)
        platform_root = tmp_path / platform
        receipt_path = platform_root / acceptance.PLATFORM_RECEIPT_NAME
        manifest_path = platform_root / acceptance.PLATFORM_MANIFEST_NAME
        receipt_paths.append(receipt_path)
        manifest_paths.append(manifest_path)
        assert (
            acceptance.main(
                [
                    "platform",
                    "--repo",
                    str(tmp_path),
                    "--cohort",
                    str(tmp_path / "cohort.json"),
                    "--foundation-tag",
                    foundation.tag,
                    "--follow-up-tag",
                    follow_up.tag,
                    "--session",
                    str(session_path),
                    "--key",
                    str(key_path),
                    "--bridge-asset",
                    str(bridge_asset),
                    "--bridge-checksum",
                    str(bridge_checksum),
                    "--output",
                    str(platform_root),
                ]
            )
            == 0
        )
        capsys.readouterr()

    aggregate_path = tmp_path / "aggregate.json"
    assert (
        acceptance.main(
            [
                "aggregate",
                "--repo",
                str(tmp_path),
                "--cohort",
                str(tmp_path / "cohort.json"),
                "--foundation-tag",
                foundation.tag,
                "--follow-up-tag",
                follow_up.tag,
                "--session",
                str(session_path),
                "--key",
                str(key_path),
                "--receipt",
                str(receipt_paths[0]),
                "--manifest",
                str(manifest_paths[0]),
                "--output",
                str(aggregate_path),
            ]
        )
        == 0
    )
    result = json.loads(aggregate_path.read_text(encoding="utf-8"))
    case_count = len(inputs.releases)
    assert result == {
        "acceptance": False,
        "authority_complete": False,
        "case_count": case_count,
        "completed": case_count,
        "discovered": case_count,
        "failed": 0,
        "journey_count": case_count,
        "outcome": "HISTORIC_FLEET_EVIDENCE_AGGREGATED",
        "passed": case_count,
        "platforms": ["darwin"],
        "required_job_conclusions": {
            "darwin": "historic-fleet-darwin",
        },
        "session_id": session["payload"]["session_id"],
        "started": case_count,
    }
