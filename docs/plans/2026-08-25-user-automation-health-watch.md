# Watching the person's own automations — implementation plan

**Status:** Implemented on `claude/user-automation-health-watch-1raksj`. All user-visible copy
in this document and in the changelog entry is DRAFT and carries no founder approval yet.

**Implementation notes** are marked *(as built)* where the finished code differs from the
plan as first written; §10 records every divergence from the specification.

**Date:** 2026-08-25

**Repository:** `dex-core`

**Builds on:** the health promise register (`core/health/promises.py`), the launch-agent
classification sweep (`core/utils/doctor.py`), the strict reporter contract
(`core/health/reporter.py`), immutable health snapshots (`core/health/snapshot.py`), the
lifecycle transaction boundary, and the Dex Solo automation-ownership contract.

**Working name:** learned automation watch

---

## The short version

A long-time user ran Dex for months while a daily job she had set up never fired, and
nothing told her. Dex already owns the answer to that class of failure — but only for the
five jobs Dex itself ships. Her own job got a disclaimer:

> `N launch agents referencing this vault (…) are checked for loading only, not freshness
> (no registered freshness receipt)` — `core/utils/doctor.py:2967-2971`

This build turns that sentence from the end of the story into the beginning. Each of the
person's vault-pointing scheduled jobs acquires a **learned promise** — an expected cadence
plus a receipt — held in a per-job JSON record beside the snapshot store. The existing
verdict vocabulary (`kept` / `never` / `broken`, `core/health/promises.py:113-117`) judges
them. A job that was due and left no trace is surfaced. A job that cannot be honestly
audited keeps today's disclaimer, unchanged.

Four founder rulings (25 Aug) bind the build: watch quietly and disclose at first speaking;
script reading is inside the Doctor's read-only remit; the Doctor never auto-heals a user
automation; all copy is drafted for approval.

---

## 1. What the repository already provides (verified 25 August 2026)

Every claim below was read in this tree at the line cited.

### 1.1 The shipped register and its law

`core/health/promises.py` holds `PROMISES`, a frozen 5-tuple of shipped jobs
(`:65-109`). `HealthPromise` (`:38-59`) already carries everything a learned promise needs
to express: `cadence`, `receipt_kind` (`json-timestamp` | `file-activity` | `daemon`,
`:35`), `receipt_path`, `receipt_key`, and `activity_only`. Its module docstring states the
two rules that keep it honest — **declared, not inferred** (`:13-19`) and **activity-only
receipts say so** (`:20-23`) — the second written after the v1.84.0 incident in which
meeting sync failed silently for six days while its log kept growing (`:3-5`).

`PromiseAudit` (`:112-135`) is the verdict record. `detail()` refuses the word
"successfully" for an `activity_only` promise, saying "ran" instead (`:122`).

`scripts/generate-health-promises.py` is the build gate. It scans tracked
`.plist`/`.plist.template`/`.sh` files for `com.dex.*` labels (`:50-64`), fails when a
shipped job has no registered promise (`:171-179`) or a registered promise has no shipped
declaration (`:180-186`), and verifies the bash mirror table in
`.claude/hooks/session-start.sh` still matches the register (`:67-107`), erroring on any
mirror row naming a job absent from the register (`:104-106`). CI runs it as the "Health
promise register gate" (`.github/workflows/ci.yml:96-99`).

### 1.2 Discovery already exists

`_installed_launch_agents` (`core/utils/doctor.py:2418`) enumerates every plist in
`~/Library/LaunchAgents`, and its docstring rules the boundary this build inherits: *"a
user's custom job under any label that points into this vault is this vault's business"*
(`:2423-2425`).

`_classify_launch_agents` (`:2640`) sorts each plist into `_OWNED` (`:2613`), `_OFFLOADED`
(`:2614`), `_STALE` (`:2615`), `_FOREIGN` (`:2616`), or `_UNREADABLE` (`:2617`), producing
`LaunchAgentRecord`s (`:2621-2630`). `_scan_launch_agents` (`:2745`) caches one
classification per `collect()` run inside a scan scope opened at `:1045`. Dex Solo's claim
is honoured first: an offloaded plist short-circuits to `_OFFLOADED` before any parsing
(`:2668-2677`), using `automation_ownership.valid_claims` (`core/utils/automation_ownership.py:349-366`).

`_launchctl_status` (`:2581-2600`) already reads `LastExitStatus` and PID.

`core/utils/launch_agents.py` holds the shared evidence helpers: boundary-aware path
matching (`:42`, `:63-65`), `iter_plist_strings` (`:68`), `stored_former_vault_root`
(`:86-117`), and `load_plist_payload` (`:120-132`), which treats every parse failure as
"no evidence" rather than raising.

### 1.3 The honest gap this build closes

`_probe_jobs_fresh` (`core/utils/doctor.py:2910`) maps each owned label onto a shipped
promise (`:2917-2926`). Labels with no promise land in `unregistered` (`:2950-2954`) and
produce the coverage note at `:2962-2971`, appended to every verdict by `_with_coverage_note`
(`:2973-2974`). Two tests pin that behaviour today
(`core/tests/test_doctor.py:2822-2851`).

### 1.4 Where durable health state is written

`core/health/snapshot.py:6-7`: *"All durable health files go through the existing lifecycle
transaction boundary."* `HealthStore` (`:482`) implements that through `_write_plan`
(`:537-544`), which previews and executes one lifecycle transaction; existing purposes are
`health-refresh-start` (`:588`), `health-refresh-finish` (`:652`), `health-snapshot-write`
(`:694`) and `health-snapshot-publish` (`:724`). Entry builders `_new_file_entry` (`:546`),
`_replace_file_entry` (`:549`) and `_delete_entry` (`:561`) carry the preconditions.

**Divergence from the spec, deliberate.** The spec asks for the learned-record operation to
be "allowlisted the way `automation-ownership` is (`core/transaction/engine.py:178`)". That
is not needed and this plan does not do it. `core/portable_contract.py:276-278` already
classifies the whole `System/.dex/health` directory as `generated`, and the ownership
verdict for a file beneath it is `allowed=True, action='regenerate',
rule_id='generated-health-state'` under the ordinary `update` operation — confirmed by
running `portable_contract.update_write_verdict('System/.dex/health/learned-promises/x.json',
exists=False, operation='update')` against this tree. `purpose` is a label;
`operation` is the authorization axis and defaults to `"update"`
(`core/lifecycle/service.py:230`). Adding a new operation would widen
`portable_contract.update_write_verdict`'s allowlist (`:591-602`) for no gain. The
`automation-ownership` operation exists because it needed a *narrower* grant plus a
bounded-read limit (`core/transaction/engine.py:177-187`); this build needs neither.

### 1.5 The reporter contract — the binding constraint on shape

`core/health/doctor_reporter.py:27-33` builds the reporter spec from
`doctor.QUICK_CHECKS` and `doctor.DEEP_CHECKS`. `normalize_report`
(`core/health/reporter.py:299`) marks any check id outside that spec `unrecognized-check`
(`:412-421`) and any registered check that returned nothing `missing-check-*`
(`:490-496`); either records an error, and errors set `accepted=False` (`:530`).
`_publish_health_snapshot` returns without publishing when `accepted` is false
(`core/utils/doctor.py:5819-5820`).

**So dynamic per-learned-job check ids cannot enter snapshots, and a check registered in
the spec must return a result on every run.** `MAX_DETAIL_LENGTH` is 512
(`core/health/reporter.py:32`) and `MAX_RESULTS` is 128 (`:35`). (The spec cited `:33` and
`:36`; the values are as described, the lines are off by one.)

### 1.6 Severity — a second binding constraint the spec did not anticipate

The spec asks that learned breakage "contributes to the snapshot at warning level at most".
There is no warning level. `VERDICTS` is `{OK, OFF, BROKEN, UNKNOWN}`
(`core/health/reporter.py:26`) and `_overall_status` (`core/health/snapshot.py:147-153`)
maps **any** `BROKEN` to `critical` and **any** `UNKNOWN` to `unknown`.

Therefore, structurally: **the `learned-automations` check returns `OK` or `OFF` and never
`BROKEN` or `UNKNOWN`.** Its verdict answers "is Dex's watch working", not "is the
person's job working" — the person's job is the subject of the check's `detail` and its
structured report section. This is what makes the spec's pulse arbitration true by
construction: `.claude/hooks/health-pulse.sh:77-81` fires only on `overall_status ==
"critical"`, which a learned job now cannot produce, so no learned alarm can outrun the
disclosure and the pulse's everyday silent path (two file reads, `:31` and `:74`) is
untouched.

**Cost of this choice, stated plainly for the founder.** A learned record that is corrupt
is a Dex-side failure, and Dex will report it as `unauditable` in the report body while the
check verdict stays `OK`. A genuine warning severity would mean extending `VERDICTS` and
`_overall_status`, which changes how Dex's *own* health is scored on every surface. That is
too much blast radius for v1 and is raised here rather than taken silently.

### 1.7 Where the finding must actually be rendered

`_result_json` (`core/utils/doctor.py:717-729`) does **not** emit per-check
`structured_detail`. The existing pattern for evidence-rich findings is a top-level report
key lifted from the probe's `structured_detail` — `report["customization_assessment"]`
(`:1167-1173`) and `report["customization_migration_status"]` (`:1174-1180`).

This matters because `.claude/skills/dex-doctor/SKILL.md:137-140` collapses every healthy
check into a single line ("✓ N checks healthy"). An `OK` verdict alone would **bury** a
broken user automation. So the learned findings ride a top-level `learned_automations`
report key with their own render step in the skill, exactly as the adoption and
customization sections do (`SKILL.md:152-161`, `:194-203`).

### 1.8 Session start reads only the overall status

`format_session_health` (`core/utils/health_session.py:86-117`) renders overall status and
a snapshot stamp — no per-check detail. Speaking learned findings there requires extending
that surface, which is more than the spec's phrasing implies. See §6.

### 1.9 Credential exclusion prior art

`is_reference_read_restricted_path` (`core/customization_migration/references.py:56-75`)
classifies credential-bearing sources *before* callers read their bytes. Its
`secret_adjacent` test (`:59-64`) walks path parts for `.env`, `.env.*`, and any part
containing `credential` — that generalizes to absolute paths unchanged. Its remaining rules
are vault-relative: two literal paths (`:66-69`) and a `System/integrations/` prefix rule
(`:70-73`) — **three**, not two as the spec says. §4.3 states exactly how they are carried
to absolute paths.

### 1.10 The Solo boundary

`docs/automation-ownership-contract.md` — a validly claimed job is ignored by Core while the
claim holds. Claims accept only `com.dex.*`/`com.claudesidian.*` labels
(`core/utils/automation_ownership.py:189-190`).

---

## 2. The claim

A person's own scheduled automations are watched the way Dex's shipped jobs are watched:
each acquires a learned promise, the existing verdict vocabulary judges it, and a job that
was due and left no trace is surfaced — instead of being discovered by accident months
later. Jobs that cannot be honestly audited keep today's disclaimer. Nothing is waved
through.

---

## 3. Lot 1 — the learned register beside the shipped one

**New module:** `core/health/learned.py`. **New state:**
`System/.dex/health/learned-promises/<slug>.json`, siblings of `snapshots/` and
`refreshes/`.

### 3.1 The record

One JSON object per job, contract `dex.health.learned-promise/v1`:

| field | meaning |
| --- | --- |
| `label` | the launchd `Label`, verbatim |
| `plist_relative_path` | home-relative plist path, as `LaunchAgentRecord` sees it |
| `schedule_source` | `StartCalendarInterval` \| `StartInterval` \| `observed` \| `none` |
| `schedule` | normalized due-time rule as read, or observed interval seconds |
| `receipt_kind` | `json-timestamp` \| `file-activity` \| `daemon` — the shipped vocabulary |
| `receipt_path` | absolute path of the receipt |
| `receipt_provenance` | `script-output` \| `launchd-stdout` \| `launchd-stderr` \| `none` — **how it was chosen** |
| `activity_only` | true for launchd-evidence receipts |
| `consecutive_misses` | derived each sweep, persisted so judgement survives restarts |
| `last_receipt_at` / `watch_since` / `last_evaluated_at` | timestamps |
| `observed_runs` | bounded ring (≤ 16) of run timestamps, for interval learning |
| `watch_state` | `watching` \| `stopped-by-user` |
| `program_path` | *(as built)* the shell script the job runs, when Dex could read one that was not credential-bearing — Lot 5's offer needs it, nothing else does |

Register-level state (`_register.json`, same directory): `disclosed_at`,
`disclosure_acknowledged_at`, contract version.

### 3.2 Filename safety

A launchd `Label` is arbitrary text and must never reach a path. The record filename is a
strict slug: `[a-z0-9][a-z0-9._-]{0,79}` of the lowercased label, plus the first 12 hex of
`sha256(label)` — so `../../evil` cannot address a file, and two labels differing only in
case or punctuation cannot collide. The label itself is stored inside the record.

### 3.3 Writes

Through `HealthStore._write_plan`'s pattern only — never plain `open()`. One transaction
per sweep carrying every changed record (`purpose="health-learned-sweep"`, operation
`update`), skipped entirely when nothing changed. §1.4 explains why no new operation is
introduced.

### 3.4 Hard rules

- `PROMISES` stays a frozen tuple and CI-gated. `core/health/learned.py` never imports into
  `scripts/generate-health-promises.py`, so a learned record cannot satisfy the shipped
  gate — the gate reads only tracked repo files and the `PROMISES` tuple
  (`scripts/generate-health-promises.py:161-189`). Acceptance test 2 pins it.
- A corrupt or unparseable record loads as `unauditable` — today's disclaimer — never as a
  verdict. The next sweep re-drafts it.
- A learned record whose label resolves to a shipped promise via
  `launch_agents.promise_label_candidates` (`core/utils/launch_agents.py:51-60`) is ignored;
  shipped jobs are the shipped register's business.

---

## 4. Lot 2 — discovery drafts the promise, riding the existing sweep

No new scheduler. `learned.sweep(context, scan)` is called once from `collect()`
(`core/utils/doctor.py:1045-1047`) inside the existing launch-agent scan scope, so it
re-uses the one classification pass and adds no plist parsing.

Enrolled: `_OWNED` records whose label is not shipped, not `_OFFLOADED`, and not already
learned. Not enrolled: `_FOREIGN` (no vault path evidence), `_OFFLOADED` (Solo's, while the
claim holds), `_UNREADABLE`, `_STALE`.

### 4.1 Cadence is read, not guessed

`StartCalendarInterval` (including a list of dicts) and `StartInterval` are read from the
parsed payload already on `LaunchAgentRecord.data`. A job with neither — `WatchPaths`,
`QueueDirectories`, event-driven — starts as `schedule_source: observed`: run evidence is
recorded, the typical interval is learned as the median of `observed_runs`, and **no audit
runs until a stable interval exists** (≥ 4 runs, median absolute deviation ≤ 25% of the
median). Until then the job sits in "watching, no rhythm yet" and is never alarmed.

### 4.2 Receipt, best first

**(a) The job's own outputs.** Read the program the plist runs to find the paths it writes.
No such utility exists in Core, so v1 is bounded hard and says so:

- shell scripts only (`#!` naming `sh`/`bash`/`zsh`, or a `.sh` suffix);
- ≤ 64 KiB, read once, never followed into `source`d or child files;
- only two shapes are accepted: a redirection target (`> path`, `>> path`) and the
  argument of `tee` or `touch`.  *(As built: `cp`/`mv`/`date` were dropped from the
  allowlist the plan first sketched — `cp`'s and `mv`'s final argument may be a directory
  rather than the file written, and `date` never names its target except through a
  redirection the first shape already catches.  A wrong receipt would make a dead job look
  alive, which is the exact failure this build exists to stop, so the reader refuses rather
  than widens.)*;
- anything with command substitution, a variable that is not `$HOME`, or a glob is
  **rejected**, not guessed.

Anything the reader cannot resolve falls to (b)/(c). A resolved output freshly touched
after a due time is a real receipt (`receipt_kind: file-activity`, `activity_only: False`,
`receipt_provenance: script-output`).

**(b) launchd evidence.** `StandardOutPath` / `StandardErrorPath` mtimes, plus
`_launchctl_status`'s `last_exit_status` (`core/utils/doctor.py:2581-2600`). Recorded
`activity_only=True` and reported in the register's existing activity-only voice
(`core/health/promises.py:122`, `:132-134`) — "ran", never "succeeded".

**(c) Neither.** The job stays honestly unauditable and becomes a Lot 5 candidate. It keeps
today's coverage-note wording.

### 4.3 Credential exclusion, before any read

A wrapper `learned.is_script_read_restricted(path: Path) -> bool` applies
`is_reference_read_restricted_path`'s discipline to an arbitrary absolute path:

- the `secret_adjacent` part-walk (`references.py:59-64`) is applied unchanged to every
  part of the absolute path — it is already path-part based;
- the three vault-relative rules (`:66-73`) are applied **as path-part matching**: a path
  is restricted when its parts end with `.claude/settings.json` or
  `.claude/settings.local.json`, or when it contains a `System/integrations/` pair followed
  by a `.yaml`/`.yml` file. This is the "path-part matching applied to absolute paths"
  the founder's ruling 2 calls for.

Restricted paths are excluded **before** any bytes are read. No excluded path, and no byte
of an excluded file, is written to a learned record, the Doctor report, or any log — the
record stores only `receipt_provenance: none`. Acceptance test 8 pins it.

### 4.4 Read-only

Discovery and audit never write outside `System/.dex/health/`. Lot 5's consented diff is
the only exception. Acceptance test 9 pins it.

---

## 5. Lot 3 — the audit: due, grace, two misses, recovery

`learned.audit_learned(record, now)` returns a `LearnedAudit` reusing the shipped state
names `kept` / `never` / `broken` (`core/health/promises.py:115`). *(As built, it also
carries four states that are honestly **not** judgements and never surface as an alarm:
`unauditable`, `no-rhythm-yet`, `pending`, and `stopped-by-user`.  Naming them separately
is what stops a job Dex cannot judge from being folded into `kept`.)* It is a
**new auditor, not the shipped `audit_promise`** — deliberately, and the divergence is
stated here rather than left to be read as an oversight.

The shipped `audit_promise` (`core/health/promises.py:164-182`) is a stateless
cadence-vs-receipt comparison that absorbs sleep/wake by padding the cadence: *"Cadence is
the promise, not the schedule: it includes slack for machines that sleep"* (`:62-64`). That
works because Dex declares its own cadences. A read schedule is not padded — a job set for
09:00 daily means 09:00 — so the learned auditor works from due times instead:

1. **Due times** are enumerated from the read schedule between `max(watch_since,
   last_receipt_at)` and `now`.
2. **Grace window** of 4 hours after each due time, sized for laptop life: a machine asleep
   at 09:00 coalesces the job to wake. A receipt inside the window counts as **kept**.
   Where the read schedule is coarse (`StartInterval`, or a learned observed interval), the
   grace is the larger of 4 hours and 25% of the interval — this is where the shipped
   cadence-padding idea is kept.
3. **One miss is quiet.** `consecutive_misses == 1` produces `kept` with a quiet note; no
   surfaced line.
4. **Two consecutive misses are broken.** `consecutive_misses >= 2` → `broken`.
5. **Recovery is never held back.** Any receipt after the newest counted miss resets
   `consecutive_misses` to 0 and the verdict to `kept`, in the same sweep.
6. **`never`** is its own verdict once two full periods have elapsed since `watch_since`
   with no receipt ever seen.

`consecutive_misses` is *derived* each sweep by counting due times since the last receipt —
so a Doctor that runs weekly still judges a daily job correctly — and then *persisted*, so
the count and its evidence survive restarts and can be shown to the person.

*(As built: the receipt is always read **live** from disk. The record's `last_receipt_at` is
history and evidence, never a substitute — trusting the stored stamp when the receipt file
is gone would be precisely the "activity is not health" mistake in a new costume. For the
same reason the rollup only says "on schedule" about jobs that actually left a receipt; a
watched job that has never been seen to run says so instead.)*

Nothing in this lot touches `.claude/hooks/health-pulse.sh`; the pulse keeps reading only
the latest-snapshot pointer.

---

## 6. Lot 4 — surfacing and the disclosure ruling

### 6.1 One composer, one structural guarantee

Every user-visible learned line — session start, Doctor report, any future surface — is
built by a single function, `learned.compose_surface(register, audits) -> LearnedSurface`.
Its first rule, before any verdict is consulted:

> if `register.disclosed_at is None`, the first line is the disclosure.

That makes "no learned-job alarm may appear before the disclosure" a property of one
function, testable directly (acceptance test 5) rather than a convention repeated across
surfaces.

`disclosed_at` is recorded by an explicit small transaction called by the Doctor CLI *after*
the report carrying the disclosure has been produced — the same seam as
`_publish_health_snapshot` (`core/utils/doctor.py:5799`, defined at `:5804`). If that write fails, the
disclosure repeats. The failure mode is a repeated disclosure, never a silent alarm.

### 6.2 Disclosure copy — DRAFT, founder approval required

> Dex noticed these scheduled jobs of yours and has been keeping an eye on them — reading
> only, on your Mac, so it can tell you when one stops running. Keep watching, or stop?

Per job: **Keep** / **Stop**.

### 6.3 Alarm copy — DRAFT

> `nightly-backup` was due Tuesday at 9:00am and has left no trace since 12 August.

Named in the person's terms (the label as they wrote it), with the evidence.

### 6.4 Stop is real

**Stop** sets `watch_state: stopped-by-user`. No further alarms. The job is listed in the
coverage note as **not watched, at your choice** — never silently unwatched, and visibly
distinct from "cannot be audited". Re-enabling resumes watching from a fresh `watch_since`.

### 6.5 Where it appears

- **Doctor report** — a new top-level `learned_automations` key (§1.7), plus a new render
  step in `.claude/skills/dex-doctor/SKILL.md` so an `OK` verdict cannot bury the finding.
- **`learned-automations` check** — registered in `QUICK_CHECKS` and therefore in the
  reporter spec. Verdict `OK`/`OFF` only. `detail` is the ≤512-char rollup:
  "3 of your automations watched; 1 needs attention: nightly-backup". The evidence-rich
  lines live in the report key and the records, not the snapshot.
- **Session start** — `format_session_health` (`core/utils/health_session.py:86-117`)
  gains one appended line, read from the latest snapshot's `learned-automations` result.
  It never changes the overall-status line above it. *(As built, the disclosure is folded
  into the check's `detail` by `compose_surface` itself, so every surface that reads the
  snapshot inherits the disclosure-before-alarm ordering without composing any copy of its
  own — session start simply repeats what the snapshot says.)*
- **Pulse** — untouched, by construction (§1.6).
- **`.claude/hooks/session-start.sh` mirror table** — untouched. The build gate errors on
  any mirror row absent from the shipped register
  (`scripts/generate-health-promises.py:104-106`), so learned jobs must never appear there.

### 6.6 The coverage note keeps its job

`_probe_jobs_fresh`'s note (`core/utils/doctor.py:2962-2971`) is narrowed to the jobs that
are genuinely still unauditable, and gains the two new honest categories: *not watched, at
your choice*, and *watching, no rhythm yet*. Its existing wording for the remainder is
unchanged, and both existing tests (`core/tests/test_doctor.py:2822-2851`) must still pass.

---

## 7. Lot 5 — offered instrumentation (small, last)

For receipt-poor jobs, offer to add one receipt line to the person's script:

```
date -u +%Y-%m-%dT%H:%M:%SZ > "$HOME/.dex/receipts/<slug>.receipt"   # added by Dex
```

Shown as an exact unified diff. Applied only on an explicit yes. On apply, the learned
record upgrades from `activity_only` to a real receipt with
`receipt_provenance: script-output`. **This is the build's only write to a user file and it
is always asked.** Refusal changes nothing and is not re-offered in the same session.

---

## 8. Adversarial acceptance tests

Test-first: each fails before its lot lands. New file `core/tests/test_learned_automations.py`,
plus additions to `core/tests/test_doctor.py`.

| # | Test | Pins |
| --- | --- | --- |
| 1 | daily user job made not to fire → quiet after one miss, `broken` after two; a later receipt clears it | Lot 3 — the reported incident, reproduced |
| 2 | a learned record claiming a shipped job's id does not satisfy the shipped gate: `generate-health-promises.py --check` still fails when a shipped declaration is removed | §3.4 |
| 3 | corrupt learned JSON → `unauditable`, never a false `kept`; the sweep re-drafts rather than crashing | §3.4 |
| 4 | growing `StandardErrorPath`, no due-time receipt → activity-only voice, never "succeeding" | Lot 2(b) |
| 5 | fresh vault, forced `broken` → `compose_surface`'s first line is the disclosure | §6.1 |
| 6 | after Stop: no alarm on a later miss; job listed as unwatched-by-choice; re-enable resumes | §6.4 |
| 7 | plist entirely outside the vault not enrolled; Solo-claimed not enrolled while valid; released → next sweep may enroll. **Fixture note:** claims accept only `com.dex.*`/`com.claudesidian.*` (`core/utils/automation_ownership.py:189-190`) and a released *shipped* label maps back to its shipped promise, so the released→enroll arm needs a user job deliberately labelled `com.dex.something-unshipped` | Lot 2 boundary |
| 8 | script referencing a credential path → excluded before read; no credential path or content in any record, report, or log | §4.3 |
| 9 | discovery/audit path performs zero writes outside `System/.dex/health/` | §4.4 |
| 10 | `.claude/hooks/health-pulse.sh` everyday silent path unchanged — still two file reads, no new forks | §1.6 |
| 11 | due time missed while asleep, receipt on wake → `kept` | Lot 3 grace |
| 12 | `learned-automations` never returns `BROKEN`/`UNKNOWN`; a broken learned job leaves `overall_status` unchanged | §1.6 |
| 13 | a label like `../../evil` cannot address a file outside the learned directory | §3.2 |

*(As built, `core/tests/test_learned_automations.py` carries 51 tests: the thirteen above,
plus Lot 5's consent tests, the session-start surface tests, and the rollup-honesty tests.
Two fixture corrections were made during the build rather than weakening the code they
tested: `_plist_owned_by_vault` (`core/utils/doctor.py:2488-2518`) deliberately refuses
`WorkingDirectory` and `StandardOutPath` as ownership evidence, so a fixture claiming a job
that way was wrong, not the rule; and pytest's `tmp_path` embeds the test's own name, which
made a credential-exclusion test pass for the wrong reason.)*

Governance: `docs/testing-governance.md` requires a regression test per behaviour change and
docs updated or explicitly exempted. This plan, the Doctor inventory section of
`docs/testing-governance.md`, `docs/architecture/DEX-CORE-MAP.md`, and
`.claude/skills/dex-doctor/SKILL.md` are the doc surface.

---

## 9. Non-claims and stop conditions

- **v1 is launchd (macOS).** cron and systemd are out of scope. The coverage note says so
  rather than half-supporting them.
- **No auto-heal of a user automation, ever.** Report only (founder ruling 3).
- **Event-driven jobs without receipts stay honestly unauditable.** No fabricated cadence to
  make coverage look complete.
- **No new severity level.** §1.6 states the cost and raises it rather than taking it.
- **Stop and raise to the founder** if watching cannot be made honest for a class of jobs.
  The disclaimer is the fallback; silence is not.

---

## 10. Divergences from the specification, recorded

Per the instruction that repository conventions win where they conflict with the spec:

1. **No new transaction operation** (§1.4). `System/.dex/health/**` is already writable
   under the ordinary `update` operation via `generated-health-state`
   (`core/portable_contract.py:276-278`), verified against this tree.
2. **No warning severity; `OK`/`OFF` only** (§1.6). The contract has no warning level and
   any `BROKEN` becomes `critical` (`core/health/snapshot.py:147-153`).
3. **Findings ride a top-level report key, not per-check `structured_detail`** (§1.7).
   `_result_json` does not emit it (`core/utils/doctor.py:717-729`), and the skill collapses
   `OK` checks (`.claude/skills/dex-doctor/SKILL.md:137-140`).
4. **Session start needs a surface extension** (§1.8). `format_session_health` renders only
   overall status today (`core/utils/health_session.py:86-117`).
5. **Three vault-relative rules, not two** (§1.9, `core/customization_migration/references.py:66-73`).
6. **Line-number corrections:** `MAX_DETAIL_LENGTH` is `core/health/reporter.py:32` (spec
   said `:33`); `MAX_RESULTS` is `:35` (spec said `:36`).
7. **Plan filename** follows the files actually in `docs/plans/`
   (`YYYY-MM-DD-<name>.md`), not the `-plan.md` form described in
   `.claude/plugins/compound-engineering/commands/workflows/plan.md:480`.
