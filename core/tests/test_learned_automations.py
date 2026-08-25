"""The learned automation watch: a person's own scheduled jobs, judged honestly.

The reported incident: a daily job the user set up herself never fired for
months and nothing told her.  Dex's shipped jobs have had a promise register
since the v1.84.0 silent-sync failure; her own job got a disclaimer.  These
tests pin the behaviour that closes that gap without weakening a single
existing honesty rule.
"""

from __future__ import annotations

import json
import plistlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.health import learned
from core.utils import doctor

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "System").mkdir(parents=True)
    return root


@pytest.fixture
def context(tmp_path):
    vault_root = tmp_path / "vault"
    (vault_root / "System").mkdir(parents=True)
    (vault_root / "core").mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return doctor.DoctorContext(
        vault_root=vault_root, repo_root=vault_root, home=home, now=NOW
    )


def _write_user_plist(context, label, payload=None):
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    script = context.vault_root / ".scripts" / f"{label}.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        f'#!/bin/bash\ndate -u >> "$HOME/receipts/{label}.log"\n', encoding="utf-8"
    )
    script.chmod(0o755)
    body = {
        "Label": label,
        "ProgramArguments": ["/bin/bash", str(script)],
        "StartCalendarInterval": {"Hour": 9, "Minute": 0},
    }
    body.update(payload or {})
    plist = agents / f"{label}.plist"
    with plist.open("wb") as handle:
        plistlib.dump(body, handle)
    return plist


def _opaque_vault_job(context, label, extra=None):
    """A job that points into the vault through a shell string, as launchd jobs do,
    but whose program Dex cannot read for outputs."""
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    body = {
        "Label": label,
        "ProgramArguments": [
            "/bin/bash",
            "-c",
            f"cd {context.vault_root}; exec /usr/bin/true",
        ],
        "StartCalendarInterval": {"Hour": 9, "Minute": 0},
    }
    body.update(extra or {})
    plist = agents / f"{label}.plist"
    with plist.open("wb") as handle:
        plistlib.dump(body, handle)
    return plist


def _daily_record(vault_root, label="com.alice.nightly-backup", **overrides):
    record = learned.LearnedPromise(
        label=label,
        plist_relative_path=f"Library/LaunchAgents/{label}.plist",
        schedule_source="StartCalendarInterval",
        schedule={"calendar": [{"Hour": 9, "Minute": 0}]},
        receipt_kind="file-activity",
        receipt_path=str(vault_root / "receipts" / "backup.log"),
        receipt_provenance="script-output",
        activity_only=False,
        watch_since=(NOW - timedelta(days=10)).isoformat(),
    )
    return record.replace(**overrides) if overrides else record


# --------------------------------------------------------------------------- #
# 1. the reported incident, reproduced
# --------------------------------------------------------------------------- #


def test_daily_job_is_quiet_after_one_miss_and_broken_after_two(vault):
    """One miss is laptop life. Two consecutive misses is a dead job."""
    record = _daily_record(vault)

    # Receipt from yesterday morning: today's 09:00 has not come round yet.
    kept = learned.audit_learned(
        record, now=NOW, receipt_at=NOW - timedelta(hours=27)
    )
    assert kept.state == "kept"
    assert kept.consecutive_misses == 0

    # One due time (yesterday 09:00) passed with nothing after it.
    one_miss = learned.audit_learned(
        record, now=NOW, receipt_at=NOW - timedelta(days=2, hours=3)
    )
    assert one_miss.state == "kept", "a single miss must not alarm"
    assert one_miss.consecutive_misses == 1
    assert not one_miss.surfaces()

    # Two consecutive due times with no trace.
    two_misses = learned.audit_learned(
        record, now=NOW, receipt_at=NOW - timedelta(days=3, hours=3)
    )
    assert two_misses.state == "broken"
    assert two_misses.consecutive_misses >= 2
    assert two_misses.surfaces()

    # Recovery is never held back.
    recovered = learned.audit_learned(
        record.replace(consecutive_misses=5),
        now=NOW,
        receipt_at=NOW - timedelta(hours=2),
    )
    assert recovered.state == "kept"
    assert recovered.consecutive_misses == 0


def test_never_ran_since_watching_began_is_its_own_verdict(vault):
    record = _daily_record(vault, watch_since=(NOW - timedelta(days=4)).isoformat())
    audit = learned.audit_learned(record, now=NOW, receipt_at=None)
    assert audit.state == "never"
    assert "never" in audit.detail().lower()


def test_never_waits_two_full_periods_before_it_speaks(vault):
    record = _daily_record(vault, watch_since=(NOW - timedelta(hours=20)).isoformat())
    audit = learned.audit_learned(record, now=NOW, receipt_at=None)
    assert audit.state != "never"
    assert not audit.surfaces()


# --------------------------------------------------------------------------- #
# 11. sleep/wake
# --------------------------------------------------------------------------- #


def test_receipt_shortly_after_wake_counts_as_kept(vault):
    """A machine asleep at 09:00 runs the job on wake. That is not a miss."""
    record = _daily_record(vault)
    due = NOW.replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=1)
    audit = learned.audit_learned(
        record, now=NOW, receipt_at=due + timedelta(hours=3)
    )
    assert audit.state == "kept"
    assert audit.consecutive_misses == 0


def test_coarse_interval_schedules_keep_cadence_padding(vault):
    """Where the read schedule is coarse, grace scales with the interval."""
    record = _daily_record(
        vault,
        schedule_source="StartInterval",
        schedule={"interval_seconds": int(timedelta(days=7).total_seconds())},
        watch_since=(NOW - timedelta(days=40)).isoformat(),
    )
    # 7d + 4h would be a miss on a fixed grace; 25% of a week is not.
    audit = learned.audit_learned(
        record, now=NOW, receipt_at=NOW - timedelta(days=7, hours=6)
    )
    assert audit.state == "kept"


# --------------------------------------------------------------------------- #
# 4. activity is not health
# --------------------------------------------------------------------------- #


def test_growing_stderr_is_reported_as_activity_never_as_success(vault):
    record = _daily_record(
        vault,
        receipt_provenance="launchd-stderr",
        activity_only=True,
        receipt_path=str(vault / "err.log"),
    )
    broken = learned.audit_learned(
        record, now=NOW, receipt_at=NOW - timedelta(days=3, hours=3)
    )
    assert broken.state == "broken"
    detail = broken.detail()
    assert "succe" not in detail.lower(), detail
    assert "ran" in detail.lower()

    kept = learned.audit_learned(record, now=NOW, receipt_at=NOW - timedelta(hours=2))
    assert "succe" not in kept.detail().lower()


# --------------------------------------------------------------------------- #
# 3. corrupt records
# --------------------------------------------------------------------------- #


def test_corrupt_learned_json_reads_as_unauditable_never_as_kept(vault):
    store = learned.LearnedStore(vault)
    store.ensure_directory()
    (store.records_dir / "com.alice.broken--0123456789ab.json").write_text(
        "{not json at all", encoding="utf-8"
    )
    register, records, corrupt = store.load()
    assert records == ()
    assert corrupt, "a corrupt record must be reported, not silently dropped"
    audits = [learned.unauditable_audit(name) for name in corrupt]
    assert all(audit.state == "unauditable" for audit in audits)
    assert all(audit.state != "kept" for audit in audits)


def test_sweep_redrafts_a_corrupt_record_instead_of_crashing(context):
    _write_user_plist(context, "com.alice.nightly-backup")
    store = learned.LearnedStore(context.vault_root)
    store.ensure_directory()
    slug = learned.record_slug("com.alice.nightly-backup")
    (store.records_dir / f"{slug}.json").write_text("{corrupt", encoding="utf-8")

    result = learned.sweep(context, now=NOW)

    assert "com.alice.nightly-backup" in result.redrafted
    _register, records, corrupt = store.load()
    assert corrupt == ()
    assert [record.label for record in records] == ["com.alice.nightly-backup"]


# --------------------------------------------------------------------------- #
# 13. a label is never a path
# --------------------------------------------------------------------------- #


def test_a_hostile_label_can_never_address_a_file_outside_the_learned_directory():
    for label in ("../../evil", "/etc/passwd", "..", "a/b/c", "com.dex.ok"):
        slug = learned.record_slug(label)
        assert "/" not in slug and ".." not in slug, slug
        assert learned._SLUG_RE.fullmatch(slug), slug
    assert learned.record_slug("Com.Alice.Job") != learned.record_slug("com.alice.job")


# --------------------------------------------------------------------------- #
# 8. secrets never reach a record, a report, or a log
# --------------------------------------------------------------------------- #


def test_credential_paths_are_excluded_before_any_read():
    home = Path("/Users/alice")
    restricted = [
        home / ".env",
        home / ".env.production",
        home / "my-credentials" / "run.sh",
        home / "aws_credentials.sh",
        home / ".claude" / "settings.local.json",
        home / ".claude" / "settings.json",
        home / "Dex" / "System" / "integrations" / "config.yaml",
        home / "bin" / ".env.local" / "run.sh",
    ]
    for path in restricted:
        assert learned.is_script_read_restricted(path), path
    for allowed in (
        home / "bin" / "backup.sh",
        home / "Dex" / ".scripts" / "nightly.sh",
        home / "Dex" / "System" / "integrations" / "README.md",
    ):
        assert not learned.is_script_read_restricted(allowed), allowed


def test_a_script_naming_a_credential_file_leaks_nothing(context, tmp_path):
    secret = context.home / ".env"
    secret.write_text("API_KEY=sk-super-secret-value\n", encoding="utf-8")
    script = context.vault_root / ".scripts" / "backup.sh"
    script.parent.mkdir(parents=True)
    script.write_text(
        "#!/bin/bash\nsource $HOME/.env\ndate > $HOME/backup.receipt\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    plist = _write_user_plist(context, "com.alice.backup")
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.alice.backup",
                "ProgramArguments": ["/bin/bash", str(script)],
                "StartCalendarInterval": {"Hour": 9, "Minute": 0},
            },
            handle,
        )

    learned.sweep(context, now=NOW)
    blob = json.dumps(
        [record.to_dict() for record in learned.LearnedStore(context.vault_root).load()[1]]
    )
    assert "sk-super-secret-value" not in blob
    assert ".env" not in blob
    # The sourced file is never followed, so its own writes are never a receipt.
    assert "API_KEY" not in blob


def test_the_script_reader_refuses_everything_it_cannot_resolve(tmp_path):
    script = tmp_path / "run.sh"
    script.write_text(
        "#!/bin/bash\n"
        "date > $HOME/good.receipt\n"
        'echo x > "$(mktemp)"\n'
        "echo y > $UNKNOWN_VAR/out\n"
        "echo z > /tmp/*.log\n"
        "source /other/script.sh\n",
        encoding="utf-8",
    )
    found = learned.read_script_output_paths(script, home=tmp_path)
    assert found == (str(tmp_path / "good.receipt"),)


def test_the_script_reader_is_bounded(tmp_path):
    script = tmp_path / "huge.sh"
    script.write_text("#!/bin/bash\n" + ("# padding\n" * 40000), encoding="utf-8")
    assert script.stat().st_size > learned.MAX_SCRIPT_BYTES
    assert learned.read_script_output_paths(script, home=tmp_path) == ()

    binary = tmp_path / "prog"
    binary.write_bytes(b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 64)
    assert learned.read_script_output_paths(binary, home=tmp_path) == ()


# --------------------------------------------------------------------------- #
# 5. disclosure before alarm — structural
# --------------------------------------------------------------------------- #


def test_no_learned_alarm_can_appear_before_the_disclosure(vault):
    """One composer owns every learned line, so this is a property, not a habit."""
    record = _daily_record(vault)
    broken = learned.audit_learned(
        record, now=NOW, receipt_at=NOW - timedelta(days=4)
    )
    assert broken.state == "broken"

    undisclosed = learned.compose_surface(
        learned.LearnedRegister(), [broken], now=NOW
    )
    assert undisclosed.disclosure_leading is True
    assert undisclosed.lines[0] == learned.DISCLOSURE_LINE
    assert learned.DISCLOSURE_LINE in undisclosed.lines[0]
    for line in undisclosed.lines[1:]:
        assert line != learned.DISCLOSURE_LINE

    disclosed = learned.compose_surface(
        learned.LearnedRegister(disclosed_at=NOW.isoformat()), [broken], now=NOW
    )
    assert disclosed.disclosure_leading is False
    assert disclosed.lines[0] != learned.DISCLOSURE_LINE
    assert "nightly-backup" in disclosed.lines[0]


def test_the_composer_offers_keep_or_stop_per_job_at_disclosure(vault):
    record = _daily_record(vault)
    audit = learned.audit_learned(record, now=NOW, receipt_at=NOW - timedelta(hours=1))
    surface = learned.compose_surface(learned.LearnedRegister(), [audit], now=NOW)
    assert surface.choices
    assert surface.choices[0]["label"] == record.label
    assert set(surface.choices[0]["options"]) == {"keep", "stop"}


def test_disclosure_is_recorded_only_after_a_surface_has_carried_it(vault):
    store = learned.LearnedStore(vault)
    store.ensure_directory()
    assert store.load()[0].disclosed_at is None
    store.record_disclosure_shown(now=NOW)
    assert store.load()[0].disclosed_at == NOW.isoformat()
    # Idempotent: a second run must not move the stamp.
    store.record_disclosure_shown(now=NOW + timedelta(days=1))
    assert store.load()[0].disclosed_at == NOW.isoformat()


# --------------------------------------------------------------------------- #
# 6. stop is real
# --------------------------------------------------------------------------- #


def test_stop_silences_alarms_and_lists_the_job_as_unwatched_by_choice(vault):
    store = learned.LearnedStore(vault)
    store.ensure_directory()
    store.put(_daily_record(vault))
    store.set_watch_state("com.alice.nightly-backup", "stopped-by-user", now=NOW)

    _register, records, _corrupt = store.load()
    stopped = records[0]
    assert stopped.watch_state == "stopped-by-user"

    audit = learned.audit_learned(
        stopped, now=NOW, receipt_at=NOW - timedelta(days=9)
    )
    assert audit.state == "stopped-by-user"
    assert not audit.surfaces(), "a stopped job must never alarm again"

    surface = learned.compose_surface(
        learned.LearnedRegister(disclosed_at=NOW.isoformat()), [audit], now=NOW
    )
    assert any("your choice" in line for line in surface.coverage_lines)
    assert not any("was due" in line for line in surface.lines)


def test_re_enabling_resumes_watching_from_a_fresh_start(vault):
    store = learned.LearnedStore(vault)
    store.ensure_directory()
    store.put(_daily_record(vault))
    store.set_watch_state("com.alice.nightly-backup", "stopped-by-user", now=NOW)
    later = NOW + timedelta(days=3)
    store.set_watch_state("com.alice.nightly-backup", "watching", now=later)

    record = store.load()[1][0]
    assert record.watch_state == "watching"
    assert record.watch_since == later.isoformat()
    assert record.consecutive_misses == 0


def test_a_sweep_never_resurrects_a_stopped_job(context):
    _write_user_plist(context, "com.alice.nightly-backup")
    learned.sweep(context, now=NOW)
    store = learned.LearnedStore(context.vault_root)
    store.set_watch_state("com.alice.nightly-backup", "stopped-by-user", now=NOW)

    learned.sweep(context, now=NOW + timedelta(days=2))

    assert store.load()[1][0].watch_state == "stopped-by-user"


# --------------------------------------------------------------------------- #
# 7. boundaries
# --------------------------------------------------------------------------- #


def test_a_plist_pointing_entirely_outside_the_vault_is_not_enrolled(context):
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    with (agents / "com.other.tool.plist").open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.other.tool",
                "ProgramArguments": ["/bin/bash", "/usr/local/bin/other-tool.sh"],
                "StartInterval": 3600,
                # Merely logging into the vault never claims ownership.
                "StandardOutPath": str(context.vault_root / "other.log"),
            },
            handle,
        )

    learned.sweep(context, now=NOW)

    assert learned.LearnedStore(context.vault_root).load()[1] == ()


def test_a_shipped_job_is_never_learned(context):
    _write_user_plist(context, "com.dex.meeting-intel")
    learned.sweep(context, now=NOW)
    assert learned.LearnedStore(context.vault_root).load()[1] == ()


def test_a_solo_claimed_job_is_not_enrolled_and_enrolls_once_released(context):
    """Fixture note: claims accept only com.dex.*/com.claudesidian.* labels
    (core/utils/automation_ownership.py:189-190), and a released *shipped*
    label maps straight back to its shipped promise.  So the released->enroll
    arm needs a user job deliberately labelled com.dex.something-unshipped."""
    from core.tests.test_doctor import _write_solo_automation_claim

    label = "com.dex.something-unshipped"
    plist = _write_user_plist(context, label)
    _write_solo_automation_claim(context, plist, label)

    learned.sweep(context, now=NOW)
    assert learned.LearnedStore(context.vault_root).load()[1] == ()

    (context.vault_root / "System" / ".dex" / "automation-ownership.json").unlink()

    learned.sweep(context, now=NOW)
    assert [r.label for r in learned.LearnedStore(context.vault_root).load()[1]] == [label]


# --------------------------------------------------------------------------- #
# 2. the shipped gate is untouched
# --------------------------------------------------------------------------- #


def test_a_learned_record_cannot_satisfy_the_shipped_build_gate(tmp_path):
    """Removing a shipped declaration must still fail --check, learned or not."""
    gate = REPO_ROOT / "scripts" / "generate-health-promises.py"
    baseline = subprocess.run(
        [sys.executable, str(gate), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert baseline.returncode == 0, baseline.stderr

    register = REPO_ROOT / "core" / "health" / "promises.py"
    original = register.read_text(encoding="utf-8")
    victim = '    HealthPromise(\n        id="com.dex.learning-review",'
    assert victim in original
    start = original.index(victim)
    end = original.index("    HealthPromise(\n        id=\"com.dex.obsidian-sync\"")
    try:
        register.write_text(original[:start] + original[end:], encoding="utf-8")
        broken = subprocess.run(
            [sys.executable, str(gate), "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
    finally:
        register.write_text(original, encoding="utf-8")
    assert broken.returncode == 1
    assert "com.dex.learning-review" in broken.stderr


def test_the_shipped_register_is_still_a_frozen_tuple_of_five():
    from core.health import promises

    assert isinstance(promises.PROMISES, tuple)
    assert len(promises.PROMISES) == 5
    with pytest.raises((AttributeError, TypeError)):
        promises.PROMISES[0].cadence = timedelta(days=1)


def test_the_session_start_mirror_table_never_names_a_learned_job(context):
    mirror = (REPO_ROOT / ".claude" / "hooks" / "session-start.sh").read_text(
        encoding="utf-8"
    )
    _write_user_plist(context, "com.alice.nightly-backup")
    learned.sweep(context, now=NOW)
    for record in learned.LearnedStore(context.vault_root).load()[1]:
        assert record.label not in mirror


# --------------------------------------------------------------------------- #
# 9. read-only invariant
# --------------------------------------------------------------------------- #


def test_discovery_and_audit_write_nothing_outside_the_health_directory(context):
    _write_user_plist(context, "com.alice.nightly-backup")
    _write_user_plist(context, "com.alice.report", {"StartInterval": 3600})

    def snapshot(root):
        return {
            path.relative_to(root).as_posix(): path.stat().st_mtime_ns
            for path in root.rglob("*")
            if path.is_file()
        }

    health_dir = "System/.dex/health"
    before_vault = snapshot(context.vault_root)
    before_home = snapshot(context.home)

    learned.sweep(context, now=NOW)
    store = learned.LearnedStore(context.vault_root)
    for record in store.load()[1]:
        learned.audit_learned(record, now=NOW)

    after_vault = snapshot(context.vault_root)
    after_home = snapshot(context.home)

    assert after_home == before_home, "the user's home must never be written"
    changed = {
        path
        for path in set(before_vault) | set(after_vault)
        if before_vault.get(path) != after_vault.get(path)
    }
    infrastructure = ("System/.dex/tx", "System/.dex/mutation.lock")
    stray = {
        path
        for path in changed
        if not path.startswith(health_dir) and not path.startswith(infrastructure)
    }
    assert stray == set(), stray


# --------------------------------------------------------------------------- #
# 12. severity — learned breakage never scores Dex's own health as critical
# --------------------------------------------------------------------------- #


def test_the_learned_check_never_returns_broken_or_unknown(context):
    _write_user_plist(context, "com.alice.nightly-backup")
    learned.sweep(context, now=NOW)
    store = learned.LearnedStore(context.vault_root)
    record = store.load()[1][0]
    store.put(
        record.replace(
            consecutive_misses=9,
            last_receipt_at=(NOW - timedelta(days=30)).isoformat(),
            watch_since=(NOW - timedelta(days=40)).isoformat(),
        )
    )

    result = doctor._probe_learned_automations(context)

    assert result.verdict in {"OK", "OFF"}
    assert result.structured_detail is not None
    assert result.structured_detail["needs_attention"] >= 1


def test_a_broken_learned_job_never_makes_dexs_own_health_critical(context):
    from core.health.doctor_reporter import from_doctor_report
    from core.health.snapshot import _overall_status

    _write_user_plist(context, "com.alice.nightly-backup")
    learned.sweep(context, now=NOW)
    store = learned.LearnedStore(context.vault_root)
    record = store.load()[1][0]
    store.put(
        record.replace(
            consecutive_misses=9,
            last_receipt_at=(NOW - timedelta(days=30)).isoformat(),
            watch_since=(NOW - timedelta(days=40)).isoformat(),
        )
    )

    report = {
        "generated_at": NOW.isoformat(),
        "checks": [
            {
                "id": definition.id,
                "feature": definition.feature,
                "verdict": "OK",
                "detail": "Stub probe completed.",
            }
            for definition in (*doctor.QUICK_CHECKS, *doctor.DEEP_CHECKS)
        ],
    }
    learned_check = next(
        check for check in report["checks"] if check["id"] == "learned-automations"
    )
    learned_check["verdict"] = doctor._probe_learned_automations(context).verdict
    learned_check["detail"] = doctor._probe_learned_automations(context).detail

    normalized = from_doctor_report(report, refresh_id="test-refresh")
    assert normalized.accepted, normalized.errors
    assert _overall_status(normalized.report) != "critical"


def test_the_learned_check_is_registered_in_the_reporter_spec():
    from core.health.doctor_reporter import DOCTOR_REPORTER_SPEC

    assert "learned-automations" in DOCTOR_REPORTER_SPEC.check_versions


def test_the_snapshot_detail_stays_a_bounded_rollup(context):
    from core.health.reporter import MAX_DETAIL_LENGTH

    for index in range(12):
        _write_user_plist(context, f"com.alice.job-{index}")
    learned.sweep(context, now=NOW)
    store = learned.LearnedStore(context.vault_root)
    for record in store.load()[1]:
        store.put(
            record.replace(
                consecutive_misses=4,
                watch_since=(NOW - timedelta(days=40)).isoformat(),
                last_receipt_at=(NOW - timedelta(days=30)).isoformat(),
            )
        )

    result = doctor._probe_learned_automations(context)

    assert len(result.detail) <= MAX_DETAIL_LENGTH
    # The evidence-rich lines live in the report body, not the snapshot.
    assert len(result.structured_detail["findings"]) >= 1


# --------------------------------------------------------------------------- #
# 10. the pulse's silent path is untouched by construction
# --------------------------------------------------------------------------- #


def test_the_mid_session_pulse_is_untouched_by_this_build():
    pulse = (REPO_ROOT / ".claude" / "hooks" / "health-pulse.sh").read_text(
        encoding="utf-8"
    )
    assert "learned" not in pulse.lower()
    # The everyday silent path is still exactly two bash-builtin file reads.
    assert pulse.count('"$(<"') == 2
    # Every fork in the whole script is dedup-gated, so it can only run on a
    # path where the pulse is about to speak — never on the silent one.
    for number, line in enumerate(pulse.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        for fork in ("grep ", "sed ", "awk ", "$(cat", "python"):
            if fork in line:
                assert "DEDUP_FILE" in line, f"line {number}: {line}"


# --------------------------------------------------------------------------- #
# receipt selection, best first
# --------------------------------------------------------------------------- #


def test_receipt_prefers_the_scripts_own_output_over_launchd_evidence(context):
    script = context.vault_root / ".scripts" / "backup.sh"
    script.parent.mkdir(parents=True)
    script.write_text(
        '#!/bin/bash\ndate -u > "$HOME/backup.receipt"\n', encoding="utf-8"
    )
    script.chmod(0o755)
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    with (agents / "com.alice.backup.plist").open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.alice.backup",
                "ProgramArguments": ["/bin/bash", str(script)],
                "StartCalendarInterval": {"Hour": 9, "Minute": 0},
                "StandardErrorPath": str(context.home / "backup.err"),
            },
            handle,
        )

    learned.sweep(context, now=NOW)

    record = learned.LearnedStore(context.vault_root).load()[1][0]
    assert record.receipt_provenance == "script-output"
    assert record.receipt_path == str(context.home / "backup.receipt")
    assert record.activity_only is False


def test_launchd_evidence_is_recorded_as_activity_only(context):
    _opaque_vault_job(
        context,
        "com.alice.opaque",
        {"StandardErrorPath": str(context.home / "opaque.err")},
    )

    learned.sweep(context, now=NOW)

    record = learned.LearnedStore(context.vault_root).load()[1][0]
    assert record.receipt_provenance == "launchd-stderr"
    assert record.activity_only is True


def test_a_receipt_poor_job_stays_honestly_unauditable(context):
    _opaque_vault_job(context, "com.alice.bare")

    learned.sweep(context, now=NOW)

    record = learned.LearnedStore(context.vault_root).load()[1][0]
    assert record.receipt_provenance == "none"
    audit = learned.audit_learned(record, now=NOW)
    assert audit.state == "unauditable"
    assert not audit.surfaces()


# --------------------------------------------------------------------------- #
# event-driven jobs: no fabricated cadence
# --------------------------------------------------------------------------- #


def test_an_event_driven_job_is_watched_without_a_rhythm_and_never_alarmed(context):
    plist = _opaque_vault_job(
        context,
        "com.alice.watcher",
        {"StandardOutPath": str(context.home / "watcher.log")},
    )
    payload = plistlib.loads(plist.read_bytes())
    del payload["StartCalendarInterval"]
    payload["WatchPaths"] = [str(context.vault_root / "inbox")]
    with plist.open("wb") as handle:
        plistlib.dump(payload, handle)

    learned.sweep(context, now=NOW)

    record = learned.LearnedStore(context.vault_root).load()[1][0]
    assert record.schedule_source == "observed"
    audit = learned.audit_learned(record, now=NOW)
    assert audit.state == "no-rhythm-yet"
    assert not audit.surfaces()


def test_an_observed_interval_is_learned_only_once_it_is_stable():
    runs = [(NOW - timedelta(days=n)).isoformat() for n in range(6, 0, -1)]
    assert learned.learn_interval(runs[:3]) is None
    steady = learned.learn_interval(runs)
    assert steady == timedelta(days=1)

    jittery = [
        (NOW - timedelta(days=20)).isoformat(),
        (NOW - timedelta(days=19)).isoformat(),
        (NOW - timedelta(days=5)).isoformat(),
        (NOW - timedelta(hours=2)).isoformat(),
    ]
    assert learned.learn_interval(jittery) is None


# --------------------------------------------------------------------------- #
# the coverage note keeps its job
# --------------------------------------------------------------------------- #


def test_jobs_fresh_still_names_jobs_it_genuinely_cannot_audit(context):
    """The existing #253 disclaimer must survive, narrowed to the honest set."""
    _opaque_vault_job(context, "com.alice.bare")
    learned.sweep(context, now=NOW)

    result = doctor._probe_jobs_fresh(context)

    assert "com.alice.bare" in result.detail
    assert "not freshness" in result.detail


def test_v1_says_plainly_that_it_only_understands_launchd(context):
    _write_user_plist(context, "com.alice.nightly-backup")
    learned.sweep(context, now=NOW)
    result = doctor._probe_learned_automations(context)
    assert "launchd" in json.dumps(result.structured_detail).lower() or (
        "scheduled jobs on this Mac" in json.dumps(result.structured_detail)
    )


# --------------------------------------------------------------------------- #
# Lot 5 — the build's only write to a user file, and it is always asked
# --------------------------------------------------------------------------- #


def _receipt_poor_job(context, label="com.alice.opaque"):
    script = context.vault_root / ".scripts" / "opaque.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/bash\n/usr/bin/rsync -a ~/Documents /backup\n")
    script.chmod(0o755)
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    with (agents / f"{label}.plist").open("wb") as handle:
        plistlib.dump(
            {
                "Label": label,
                "ProgramArguments": ["/bin/bash", str(script)],
                "StartCalendarInterval": {"Hour": 9, "Minute": 0},
            },
            handle,
        )
    learned.sweep(context, now=NOW)
    return script, learned.LearnedStore(context.vault_root).get(label)


def test_a_receipt_poor_job_is_offered_an_exact_diff_and_nothing_is_written(context):
    script, record = _receipt_poor_job(context)
    assert record.receipt_provenance == "none"
    before = script.read_bytes()

    proposal = learned.propose_receipt_instrumentation(record, home=context.home)

    assert proposal is not None
    added = [
        line
        for line in proposal.diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    assert len(added) == 1, "exactly one added line, shown exactly"
    assert added[0][1:] == proposal.line.rstrip("\n")
    assert proposal.receipt_path.startswith(str(context.home))
    assert script.read_bytes() == before, "an offer must never write"


def test_the_receipt_line_is_applied_only_on_an_explicit_yes(context):
    script, record = _receipt_poor_job(context)
    proposal = learned.propose_receipt_instrumentation(record, home=context.home)
    before = script.read_bytes()

    for refusal in (False, None, 0, "yes"):
        assert (
            learned.apply_receipt_proposal(
                context.vault_root, proposal, approved=refusal, now=NOW
            )
            is False
        )
        assert script.read_bytes() == before

    assert learned.apply_receipt_proposal(
        context.vault_root, proposal, approved=True, now=NOW
    )
    after = script.read_text()
    assert after.startswith(before.decode())
    assert after.count("added by Dex") == 1

    upgraded = learned.LearnedStore(context.vault_root).get(record.label)
    assert upgraded.receipt_provenance == "script-output"
    assert upgraded.activity_only is False
    assert upgraded.receipt_path == proposal.receipt_path


def test_a_script_that_changed_since_the_offer_needs_a_new_offer(context):
    script, record = _receipt_poor_job(context)
    proposal = learned.propose_receipt_instrumentation(record, home=context.home)
    script.write_text("#!/bin/bash\n# the user edited this in the meantime\n")

    assert (
        learned.apply_receipt_proposal(
            context.vault_root, proposal, approved=True, now=NOW
        )
        is False
    )
    assert "added by Dex" not in script.read_text()


def test_instrumentation_is_never_offered_twice_or_for_a_job_that_has_a_receipt(context):
    script, record = _receipt_poor_job(context)
    proposal = learned.propose_receipt_instrumentation(record, home=context.home)
    learned.apply_receipt_proposal(
        context.vault_root, proposal, approved=True, now=NOW
    )
    upgraded = learned.LearnedStore(context.vault_root).get(record.label)

    assert learned.propose_receipt_instrumentation(upgraded, home=context.home) is None
    assert (
        learned.propose_receipt_instrumentation(
            upgraded.replace(
                receipt_provenance="launchd-stderr",
                receipt_path=str(context.home / "err.log"),
                activity_only=True,
            ),
            home=context.home,
        )
        is None
    ), "the marker in the script must stop a second offer too"


def test_instrumentation_is_never_offered_for_a_credential_bearing_script(context):
    script, record = _receipt_poor_job(context)
    secret = context.vault_root / ".scripts" / "credentials-refresh.sh"
    secret.write_text("#!/bin/bash\necho refresh\n")
    assert (
        learned.propose_receipt_instrumentation(
            record.replace(program_path=str(secret)), home=context.home
        )
        is None
    )


def test_the_applied_receipt_makes_the_job_genuinely_auditable(context):
    script, record = _receipt_poor_job(context)
    assert learned.audit_learned(record, now=NOW).state == "unauditable"

    proposal = learned.propose_receipt_instrumentation(record, home=context.home)
    learned.apply_receipt_proposal(
        context.vault_root, proposal, approved=True, now=NOW
    )
    upgraded = learned.LearnedStore(context.vault_root).get(record.label)

    assert upgraded.is_auditable()
    # The receipt does not exist yet: honest "nothing due yet", not a fake pass.
    assert learned.audit_learned(upgraded, now=NOW).state == "pending"
    receipt = Path(upgraded.receipt_path)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text("2026-08-25T09:00:00Z\n")
    assert learned.audit_learned(upgraded, now=NOW + timedelta(hours=1)).state == "kept"


# --------------------------------------------------------------------------- #
# session start speaks through the snapshot, and only through it
# --------------------------------------------------------------------------- #


def _snapshot_with_learned(detail, verdict="OK"):
    from core.health.reporter import CheckResult, ReporterEnvelope
    from core.health.snapshot import HealthSnapshot
    from core.health.doctor_reporter import DOCTOR_REPORTER_IDENTITY

    envelope = ReporterEnvelope(
        contract="dex.health.reporter/v1",
        reporter=DOCTOR_REPORTER_IDENTITY,
        refresh_id="refresh-001",
        generated_at=NOW.isoformat(),
        results=(
            CheckResult(
                id="doctor.core/vault.structure",
                check_version="1.0.0",
                verdict="OK",
                detail="All standard PARA directories exist",
            ),
            CheckResult(
                id="doctor.core/learned-automations",
                check_version="1.0.0",
                verdict=verdict,
                detail=detail,
            ),
        ),
    )
    from core.health.snapshot import _overall_status

    return HealthSnapshot(
        snapshot_id="snap-001",
        refresh_id="refresh-001",
        generated_at=NOW.isoformat(),
        completed_at=NOW.isoformat(),
        overall_status=_overall_status(envelope),
        report=envelope,
    )


def test_session_start_repeats_the_snapshots_learned_line_verbatim():
    from core.utils import health_session

    surface = learned.compose_surface(
        learned.LearnedRegister(disclosed_at=NOW.isoformat()),
        [
            learned.LearnedAudit(
                label="com.alice.nightly-backup",
                display_name="nightly-backup",
                state="broken",
                consecutive_misses=2,
            )
        ],
        now=NOW,
    )
    line = health_session.learned_automations_line(
        _snapshot_with_learned(surface.snapshot_detail)
    )
    assert surface.rollup in line
    assert "nightly-backup" in line


def test_session_start_cannot_show_a_learned_alarm_without_the_disclosure():
    """The disclosure is folded into the snapshot detail, so every reader gets it."""
    from core.utils import health_session

    surface = learned.compose_surface(
        learned.LearnedRegister(),
        [
            learned.LearnedAudit(
                label="com.alice.nightly-backup",
                display_name="nightly-backup",
                state="broken",
                consecutive_misses=2,
            )
        ],
        now=NOW,
    )
    line = health_session.learned_automations_line(
        _snapshot_with_learned(surface.snapshot_detail)
    )
    assert line.index(learned.DISCLOSURE_LINE) < line.index("nightly-backup")


def test_session_start_says_nothing_when_there_is_nothing_to_watch():
    from core.utils import health_session

    assert health_session.learned_automations_line(None) == ""
    assert (
        health_session.learned_automations_line(
            _snapshot_with_learned("No automations", verdict="OFF")
        )
        == ""
    )


def test_a_snapshot_from_before_this_build_is_read_without_complaint():
    """An older snapshot has no learned check at all. That is silence, not a fault."""
    from core.health.reporter import CheckResult, ReporterEnvelope
    from core.health.snapshot import HealthSnapshot
    from core.health.doctor_reporter import DOCTOR_REPORTER_IDENTITY
    from core.utils import health_session

    envelope = ReporterEnvelope(
        contract="dex.health.reporter/v1",
        reporter=DOCTOR_REPORTER_IDENTITY,
        refresh_id="refresh-old",
        generated_at=NOW.isoformat(),
        results=(
            CheckResult(
                id="doctor.core/vault.structure",
                check_version="1.0.0",
                verdict="OK",
                detail="All standard PARA directories exist",
            ),
        ),
    )
    from core.health.snapshot import _overall_status

    snapshot = HealthSnapshot(
        snapshot_id="snap-old",
        refresh_id="refresh-old",
        generated_at=NOW.isoformat(),
        completed_at=NOW.isoformat(),
        overall_status=_overall_status(envelope),
        report=envelope,
    )
    assert health_session.learned_automations_line(snapshot) == ""


def test_the_learned_line_never_changes_dexs_own_status_line(tmp_path):
    from core.utils import health_session

    snapshot = _snapshot_with_learned(
        f"{learned.DISCLOSURE_LINE} 1 of your automations watched; 1 needs attention: backup"
    )
    line = health_session.learned_automations_line(snapshot)
    assert not line.startswith("🩺")
    assert "Dex health" not in line


def test_the_rollup_never_calls_silence_success(vault):
    """A watched job that has never left a trace is not "on schedule"."""
    disclosed = learned.LearnedRegister(disclosed_at=NOW.isoformat())
    pending = learned.LearnedAudit(
        label="com.alice.backup", display_name="backup", state="pending"
    )
    kept = learned.LearnedAudit(
        label="com.alice.report",
        display_name="report",
        state="kept",
        last_receipt_at=NOW - timedelta(hours=1),
    )

    only_pending = learned.compose_surface(disclosed, [pending], now=NOW)
    assert "on schedule" not in only_pending.rollup
    assert "trace" in only_pending.rollup

    mixed = learned.compose_surface(disclosed, [pending, kept], now=NOW)
    assert "1 on schedule" in mixed.rollup
    assert "1 with nothing to check yet" in mixed.rollup

    all_kept = learned.compose_surface(disclosed, [kept], now=NOW)
    assert all_kept.rollup.endswith("all on schedule")


def test_one_broken_job_reads_as_singular(vault):
    surface = learned.compose_surface(
        learned.LearnedRegister(disclosed_at=NOW.isoformat()),
        [
            learned.LearnedAudit(
                label="com.alice.backup", display_name="backup", state="broken"
            )
        ],
        now=NOW,
    )
    assert "1 needs attention" in surface.rollup
