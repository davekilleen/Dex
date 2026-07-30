"""Fail-closed tests for macOS historic updater acceptance."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import stat
import subprocess
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
        _foundation_release(),
    )
    later = (
        _release("v1.81.0", "1.81.0", "3"),
        _release("dist/release/v1.81.1-4444444", "1.81.1", "4"),
    )

    manifest = acceptance.frozen_cohort_manifest(
        historic + later,
        foundation=_foundation(),
        expected_count=2,
    )
    parsed = acceptance.releases_from_frozen_cohort(
        json.dumps(manifest),
        current_releases=historic + later,
        foundation=_foundation(),
        expected_count=2,
    )

    assert parsed == historic
    assert manifest["case_count"] == 2
    assert manifest["foundation"] == _foundation()


def test_frozen_cohort_rejects_a_new_release_at_or_before_the_foundation() -> None:
    acceptance = _acceptance()
    historic = (
        _release("v1.20.1", "1.20.1", "1"),
        _foundation_release(),
    )
    manifest = acceptance.frozen_cohort_manifest(
        historic,
        foundation=_foundation(),
        expected_count=2,
    )
    unexpected = _release("dist/release/v1.79.0-5555555", "1.79.0", "5")

    with pytest.raises(release_fleet.FleetError, match="unexpected historical release"):
        acceptance.releases_from_frozen_cohort(
            json.dumps(manifest),
            current_releases=historic + (unexpected,),
            foundation=_foundation(),
            expected_count=2,
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
        expected_count=2,
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
            expected_count=2,
        )

    other_foundation = dict(_foundation(), tree="e" * 40)
    with pytest.raises(release_fleet.FleetError, match="foundation identity"):
        acceptance.releases_from_frozen_cohort(
            json.dumps(manifest),
            current_releases=historic,
            foundation=other_foundation,
            expected_count=2,
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
            expected_count=2,
        )


def test_real_repository_freezes_exactly_168_historic_trees() -> None:
    acceptance = _acceptance()
    repository = Path(__file__).resolve().parents[2]
    current = release_fleet.discover_distribution_releases(repository)

    manifest = acceptance.frozen_cohort_manifest(current)

    assert manifest["case_count"] == acceptance.EXPECTED_HISTORIC_CASES == 168
    assert manifest["foundation"]["tag"] == "dist/release/v1.80.5-9211053"


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
    acceptance = _acceptance()
    releases = tuple(
        _release(f"v1.0.{index}", f"1.0.{index}", f"{index % 10}")
        for index in range(1, acceptance.EXPECTED_HISTORIC_CASES + 1)
    )
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

    assert result == {
        "outcome": "HISTORIC_FLEET_EVIDENCE_AGGREGATED",
        "acceptance": False,
        "authority_complete": False,
        "platforms": ["darwin"],
        "case_count": 168,
        "journey_count": 168,
        "discovered": 168,
        "started": 168,
        "completed": 168,
        "passed": 168,
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


@pytest.mark.parametrize("mutation", ("167", "169", "substitution", "duplicate"))
def test_aggregation_requires_exactly_168_unique_final_starts_per_platform(
    mutation: str,
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    key, session, inputs = _signed_session(acceptance)
    darwin = _manifest_document(inputs=inputs, platform="darwin")
    cases = darwin["report"]["cases"]
    assert isinstance(cases, list)
    if mutation == "167":
        cases.pop()
    elif mutation == "169":
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


def test_platform_collector_retains_every_live_run_and_exact_counts(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    releases = (
        _release("v1.20.1", "1.20.1", "1"),
        _release("dist/release/v1.80.5-2222222", "1.80.5", "2"),
    )
    created: list[object] = []

    def journey_runner(
        _repo: Path,
        *,
        output: Path,
        starting_tag: str,
        foundation_tag: str,
        follow_up_tag: str,
    ) -> object:
        assert output == tmp_path
        assert foundation_tag == FOUNDATION.tag
        assert follow_up_tag == "dist/release/v1.81.1-3333333"
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


def test_platform_collector_stops_on_first_failure_with_honest_counts(
    tmp_path: Path,
) -> None:
    acceptance = _acceptance()
    releases = (
        _release("v1.20.1", "1.20.1", "1"),
        _release("dist/release/v1.80.5-2222222", "1.80.5", "2"),
    )

    def journey_runner(
        _repo: Path,
        *,
        output: Path,
        starting_tag: str,
        foundation_tag: str,
        follow_up_tag: str,
    ) -> object:
        del output, foundation_tag, follow_up_tag
        if starting_tag == releases[1].tag:
            raise release_fleet.FleetError("synthetic journey failed")
        return SimpleNamespace(case=_case_document(_case(starting_tag, "darwin")))

    with pytest.raises(acceptance.PlatformFleetFailure) as failure:
        acceptance.collect_platform_runs(
            tmp_path,
            output=tmp_path,
            releases=releases,
            foundation_tag=FOUNDATION.tag,
            follow_up_tag="dist/release/v1.81.1-3333333",
            running_platform="darwin",
            journey_runner=journey_runner,
        )

    assert failure.value.counts == {
        "discovered": 2,
        "started": 2,
        "completed": 1,
        "passed": 1,
        "failed": 1,
    }


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
    execution = acceptance.collect_platform_runs(
        tmp_path,
        output=tmp_path,
        releases=inputs.releases,
        foundation_tag=FOUNDATION.tag,
        follow_up_tag="dist/release/v1.81.1-3333333",
        running_platform=running_platform,
        journey_runner=lambda _repo, **kwargs: SimpleNamespace(
            case=_case_document(_case(str(kwargs["starting_tag"]), running_platform))
        ),
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
    releases = (
        _release("v1.20.1", "1.20.1", "1"),
        _release("dist/release/v1.80.5-2222222", "1.80.5", "2"),
    )
    execution = acceptance.collect_platform_runs(
        tmp_path,
        output=tmp_path,
        releases=releases,
        foundation_tag=FOUNDATION.tag,
        follow_up_tag="dist/release/v1.81.1-3333333",
        running_platform=running_platform,
        journey_runner=lambda _repo, **kwargs: SimpleNamespace(
            case=_case_document(_case(str(kwargs["starting_tag"]), running_platform))
        ),
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
            "discovered": 168,
            "started": 168,
            "completed": 168,
            "passed": 168,
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


def test_cohort_cli_writes_the_exact_168_tree_manifest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    acceptance = _acceptance()
    repository = Path(__file__).resolve().parents[2]
    output = tmp_path / "historic-through-v1.80.5.json"

    exit_code = acceptance.main(["cohort", "--repo", str(repository), "--output", str(output)])

    result = json.loads(capsys.readouterr().out)
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert result == {
        "acceptance": False,
        "case_count": 168,
        "foundation_tag": FOUNDATION.tag,
        "outcome": "HISTORIC_COHORT_FROZEN",
        "output": str(output),
    }
    assert manifest["case_count"] == 168


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
        for index in range(1, acceptance.EXPECTED_HISTORIC_CASES + 1)
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

    def collect(*args, running_platform: str, **kwargs):
        del args, kwargs
        return SimpleNamespace(
            report=SimpleNamespace(platforms=(running_platform,)),
            counts={
                "discovered": 168,
                "started": 168,
                "completed": 168,
                "passed": 168,
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
    assert result == {
        "acceptance": False,
        "authority_complete": False,
        "case_count": 168,
        "completed": 168,
        "discovered": 168,
        "failed": 0,
        "journey_count": 168,
        "outcome": "HISTORIC_FLEET_EVIDENCE_AGGREGATED",
        "passed": 168,
        "platforms": ["darwin"],
        "required_job_conclusions": {
            "darwin": "historic-fleet-darwin",
        },
        "session_id": session["payload"]["session_id"],
        "started": 168,
    }
