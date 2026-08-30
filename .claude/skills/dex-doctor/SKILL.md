---
name: dex-doctor
description: "Whole-system checkup: verifies every Dex feature honestly (working/off/broken/couldn't-check), self-heals what's provably safe, guides the rest. Use when the user says 'is Dex healthy', 'something's broken', 'check my setup', 'run diagnostics'. Not for discovering unused *features*; use `dex-level-up`. Not for applying an update; use `dex-update`."
---

# /dex-doctor — Full System Checkup

Diagnose everything, heal what's safe, guide the user through the rest.

## Purpose

One honest answer to "is my Dex actually working?" Built against the failure modes found
in the July 2026 audit: checks that never ran, checks that probed an easier path than the
real feature, "off" reported as "broken", and background jobs that died silently for
months.

## When to Run

- User asks "is everything working?", "what's broken?", "check my setup"
- Something feels off — features silently not happening
- After an update, migration, or machine change
- User invokes `/dex-doctor` directly

## Cardinal rules

1. **Never report "off" as a problem.** A feature the user never enabled is healthy.
   List it under "Off — that's fine", once, without nagging.
2. **Never hide "couldn't check".** If a probe failed to run, say so prominently. An
   unknown presented as a pass is how watchdogs go blind.
3. **Never claim a heal worked without re-checking it.**
4. **Heal conservatively.** Tier 1 only automatically. Tier 2 only after an explicit yes,
   one item at a time. Tier 3 is always the user's hands. Never delete or overwrite user
   data; never touch credentials.

### Credential scan mode

Credential scanning is local and read-only. Inspect the worktree, index, approved Git
common directory and primary object database, reachable refs, stashes, tags, and only
archives the user explicitly selects. Report opaque redacted finding IDs plus explicit
inspected and uninspected scope categories; never print paths or matched values. Existing
`.mcp.json` is scan/report-only and remains byte-identical.

Render migration, security, active `.mcp.json` residual, and optional history hygiene as
separate deterministic states using `render_credential_status`; do not paraphrase it.
Provider revoke/rotate is always user-driven. Replacement health is read-only and runs
only after the user explicitly chooses a remediation check. History cleanup is optional
privacy hygiene, never a current-danger warning or prerequisite. Use only a preinstalled
`git-filter-repo`, after verified restrictive bundle backup and typed consent; never
install it, push, or force-push. If migration capability fails, scanning and guidance
remain available and Doctor names the failed capability with manual move/validation/rewind steps.

For an optional cleanup request, use the in-process contracts in
`core.utils.history_hygiene`; never interpolate revoked values into a shell command. Run
`prepare_history_cleanup` only when security is `remediated`, after the user explicitly chooses
the exact `refs/heads/*`, `refs/tags/*`, or `refs/stash/*` refs and confirms either verified
external-backup evidence or no-external-backup acknowledgement. Show the returned opaque
transaction ID, selected refs, recovery-bundle evidence, and this exact consent string:

`CLEAN OPTIONAL HISTORY <transaction-id>`

If `prepare_history_cleanup` returns `optional-tool-unavailable` or
`optional-platform-unsupported`, surface its `guidance` verbatim and stop; both are calm honest
states, never a current-danger warning. `optional-platform-unsupported` means this operating
system lacks the directory file-descriptor substrate the guided path needs (it runs on Linux,
including WSL2 or a Linux container; macOS is not supported). No recovery state was created; offer
the manual advanced path and note that history cleanup is optional privacy hygiene.

Call `apply_history_cleanup` only after the user types that string exactly. Preparation must have
already produced and verified the mode-`0700` transaction directory and mode-`0600`
`history.bundle`, `objects.json`, and `manifest.json` under
`System/.dex/adoption/history-backups/<transaction-id>/`, while passing the 10 GiB shared-cap and
1 MiB free-space margin checks. Apply must preserve Git remote configuration and never fetch,
push, force-push, install software, or call a provider.

The verified bundle and manifest cover every restorable ref, not only selected refs, and include
restrictive config/index recovery artifacts plus opaque HEAD/index/tracked-worktree/remote state
authority. Apply still passes only the explicitly selected refs to `git-filter-repo`. Any changed
unselected branch, tag, stash, remote-tracking, replace, notes, backup, or other ref—or any HEAD,
index, tracked-worktree, or remote-config collateral—must return `recovery-required`, never a
clean result. Credential equality is memory-only; no value-derived digest or replacement file may
be persisted.

Render the post-cleanup rescan result exactly as `history-clean`,
`history-cleanup-pending`, or `history-scope-unknown`. If apply is interrupted or reports
`recovery-required`, lead with “Do not push.” Preserve the bundle and call
`rewind_history_cleanup` only through its exact-ref guard. If that guard refuses, give the
returned manual verified-bundle recovery guidance; do not improvise ref updates. Always state
that history rewind does not reverse provider rotation.

Retention is a separate explicit operation. `preview_retention` protects the newest history
bundle and selects only verified bundles older than 90 days with two later successful release
activations and valid backup posture. Call `delete_retention_candidates` only with the unchanged
candidate tuple and exact-set SHA-256 that the user acknowledged. Never auto-delete or upload a
recovery bundle.

## Execution

### Step 1: Run the collector (quick mode + safe auto-heals)

```bash
cd "$VAULT_PATH" && .venv/bin/python core/utils/doctor.py --heal \
  || python3 core/utils/doctor.py --heal
```

This returns JSON on stdout: every check with a verdict (`OK` / `OFF` / `BROKEN` / `UNKNOWN`), any
Tier-1 heals already applied, and an `instruments` block saying whether the doctor itself
ran completely. While it runs, stderr prints `Apply safe Tier-1 repairs before checking.`
then `Checking this Dex install (read-only)...`.

**If the collector itself fails to run:** that IS the finding. Report it first, with the
error, and continue with whatever manual checks you can do — do not present a partial
picture as a full one.

### Step 1a: Offer anonymous health telemetry once

Read `System/usage_log.md`. Make this offer only when `**Health telemetry:** pending` or the line is missing:

> "Want to help catch bad releases early? Dex can send anonymous nightly health counts — no names, notes, or file contents, ever. Share them? (y/N)"

If the user explicitly says yes, replace the line with `**Health telemetry:** opted-in` (or add it under a
`## Health Telemetry Consent` heading when missing). If the user says no, skips, or accepts the default,
record `**Health telemetry:** opted-out`. Once either decision is recorded, do not offer again.
Never read or change the separate analytics consent while handling this choice.

### Step 2: Offer the deep scan

Quick mode checks configuration, wiring, and background-job freshness. Deep mode
additionally contacts live services (Granola API, Calendar via the configured
source, enabled integrations). Ask:

> "Quick check done. Want the deep scan too? It contacts your connected services
> (Granola, Calendar) to prove the real query paths work — takes ~30 seconds."

If yes: run with `--deep` and merge results.

### Step 3: Render the report

Order: **instruments first if anything failed**, then BROKEN, then UNKNOWN, then OFF
(one compact line each, labelled "off — that's fine"), then healthy collapsed to a single
line ("✓ N checks healthy"). Fill every displayed count from the collector JSON — use
the current report's `summary` values and `checks` array rather than a hardcoded quick or
deep total, because the check registry can change.

For each BROKEN item: what it means for the user in one plain sentence (what stopped
working, since when if known), then the fix path.

For **Agent harness capabilities**, use the saved receipt as the authority. Name every
selected harness and keep the collector's four delivery labels exact: `automatic`,
`on_demand`, `guided`, and `unavailable`. Explain `on_demand` as "available when asked".
Never describe a guided MCP safety check as an automatic block; only a verified pre-tool
interceptor earns that claim. Name every written door from the collector detail, one
sentence each, in the order given — confirmed doors, written doors never opened,
walked doors, and doors that were left. Then the notes panel sentence. Then the sentence that a confirmed door is not the same as a walked one.
Keep those sentences verbatim, including any leftover sentence that proves a leave.
A confirmed door is not a leave. If the notes panel files are there but the panel is
not switched on, keep that sentence verbatim, including the named switch. Do not flip
the switch. If the collector's detail
ends with a sentence that the personal Work copy is behind this folder, show that
sentence last and unchanged. If that sentence is absent, stay silent — a missing copy is
not a grant, and a current copy is not news. Never invent a folder grant or a
`granted=true` signal. If the check is OFF, calmly offer `/setup` to detect or choose
harnesses, then still name every written door from the collector detail. If it is
BROKEN, do not guess from installed commands—use the returned repair, and still name
every written door.

For the **Entity engine** check, keep the rendering short and plain: say whether entity
creation is working, off, or needs attention, include the contact/observation counts,
and call out unresolved verification results or quarantined pages. Mention stale
verification or a stale/missing People index as a follow-up signal.

### Step 3a: Render the adoption section

Read the collector's top-level `adoption` object and render its `groups` in the exact
order returned. It always contains these five groups: `new-and-safe`,
`needs-your-review`, `preserved-for-now`, `continue-or-recover`, and
`receipts-and-rewind`.

Authority fields are not prose. Render every item id, item version, action, status,
verdict, count, transaction id, reason, path, and `rewindable` boolean verbatim. Never
change an action or verdict, combine authority records, infer a missing record, or hide
a zero count. The collector's `surface` line is the only field that may be rephrased.
Keep that rephrasing to one plain-English line per group in this register:
"Here's exactly what this changes for you" and, for recovery, "I found an interrupted
update — resume or undo?"

`needs-your-review` normally contains `conflict` actions. If the deterministic planner
returns `action: unknown`, keep that item and its reasons in this group verbatim, render
the group's `UNKNOWN` verdict, and say the evidence needs rechecking; never silently
drop it or translate it into a conflict.

If `adoption.verdict` is `OFF`, say calmly that adoption reporting is off because no
release catalog is installed. If it is `UNKNOWN`, say what could not be verified and
do not turn empty authority arrays into proposed actions. For ledger recovery, reproduce
`continue-or-recover.ledger.repair_command` exactly; this is the existing
`python3 -m core.lifecycle.cli --vault-root <vault> rebuild-state` command, not a prompt
to improvise ledger repair.

Never offer an action the engine does not expose. An interrupted transaction may be
described only from its returned transaction authority; do not call `Transaction.resume`
while rendering Doctor. A receipt is rewindable only when the collector says
`rewindable: true` and `rewind_verdict: OK`. Rewind only through the existing
receipt-backed lifecycle flow:
load that exact receipt, derive its exact acknowledgement with the
rewind-acknowledgement helper in the Python lifecycle engine
(core/lifecycle/engine.py), then perform the rewind through that same engine
module's receipt-backed rewind function. There is no lifecycle rewind
shell command, so do not invent one. If `rewindable: false` with `rewind_verdict: OK`,
say the retained snapshot was pruned. If `rewind_verdict: UNKNOWN`, say the receipt,
current bytes, committed journal, or snapshot could not be verified. In both cases, do
not offer rewind.

### Step 3b: Render the customization assessment

Deep reports include a top-level `customization_assessment` object. Render its four groups
in the exact order returned: `update-replaceable-location`,
`update-untouched-location`, `needs-interpretation`, and `blocked`.

This section follows the same authority/surface split as adoption. Reproduce every
customization id, count, kind, group, verdict, path, release state, edge count, edge kind,
confidence, completeness value, and exclusion verbatim. Do not merge records, hide zero
counts, or promote an inferred edge to proved. Only each group's `surface` line may be
rephrased, in plain English: "lives in a location Dex updates can replace" or "lives in a
location updates leave alone."

If completeness is `UNKNOWN` with `partial: true`, the installed baseline was still
verified. Render the observed count and record list explicitly as partial, followed
by every exclusion path, reason, and guidance line. Never present the observed count
as the complete total, and do not offer a Capsule write until completeness is `OK`.
If completeness is `UNKNOWN` without `partial: true`, render only the verdict and
each `incomplete_reasons` code; do not state or infer a customization count.
When `blocked_count` is greater than zero, the first summary sentence must state that blocked count.

Example register:

> I found 3 customizations. One lives in a location Dex updates can replace, one lives in a
> location updates leave alone, and one is blocked by a missing folder reference.
>
> `cust-a1b2c3d4e5f6` · `custom-script` · `.scripts/custom-plan.py` ·
> `update-untouched-location` · `canonical-customization`
>
> Nothing has changed — this is an inventory only.

Always close this section with the exact line:

`Nothing has changed — this is an inventory only.`

### Step 3c: Render the customization migration status

Deep reports include a top-level `customization_migration_status` object. Render every
`capsule_id`, `state`, `validation.status`, `validation.mismatches`, `pending`, and
`truncated` value verbatim. For each canonical Capsule, also render
`staging.proposals`, every proposal's `verification_verdict`, the
`verification_verdicts` summary, `pending_rebuild`, `activation.state`,
`activation.reason`, `activation_receipt_present`, and `rewindable` verbatim. These are
authority fields; only a short consequence or surface line may be rephrased.
When present, also render every `recovery_actions` record's `phase`, `capsule_id`,
`proposal_id`, and exact `action` verbatim. The action is already bound to
`recovery_token`; never shorten, rebuild, or improvise it.

When `pending` is true, render this guidance exactly:

> Continue via the registered Customization Migration MCP status tool / `/dex-update`; never edit capsule files directly.

When any `validation.status` is not `OK`, say plainly: "The preserved evidence cannot be
verified." Route the user to `/dex-update` guidance and reproduce the returned mismatch
authority. Do not invent a repair, search for capsule files, or edit them directly.

When `pending_rebuild` is true, say the protected rebuild is waiting to continue through
`/dex-update`. A `BLOCKED` verification verdict stays blocked and an `UNKNOWN` verdict stays
unknown. Say activation is receipt-backed only when `activation_receipt_present` is true, and
say rewind is available only when `rewindable` is true. A `recovery-required` staging or
activation state is a stop condition, not permission to repair Capsule files directly.
For interrupted staging, activation, or rewind, offer only the exact phase-specific
`recovery_actions.action` returned by Doctor after a fresh explicit acknowledgement.

### Step 4: Heal, tiered

- **Tier 1 (already applied by the collector):** report plainly — "Fixed automatically:
  recreated the missing Ideas folder."
- **Tier 2 (needs a yes):** propose one at a time with the exact action and why it's safe:
  "Your changelog-checker background job is installed but not running. Want me to load it?
  (One command, reversible.)" Apply only on explicit yes, then **re-run that check** and
  confirm from the fresh result.
- **Tier 3 (user's hands):** give exact steps and the right setup skill —
  e.g. "Granola needs an API key: run `/granola-setup`" / "macOS is blocking calendar
  access: System Settings → Privacy & Security → Calendars → enable your terminal app."

### Step 5: Close with the four-bucket summary

```
🩺 Doctor's summary
   Fixed automatically: 2
   Needs your OK:       1  (waiting above)
   Needs your hands:    1  (steps above)
   Healthy:             N · Off (fine): M · Couldn't check: U
```

Here `N`, `M`, and `U` come directly from `summary.ok`, `summary.off`, and
`summary.unknown` in the collector JSON. If everything is healthy: one line — "Everything
checks out. N checks healthy, M features off by choice." No ceremony.

### Step 6: Track usage (silent) and offer to report Dex bugs

Update `System/usage_log.md` per the usage-tracking convention. If learnings surfaced
(e.g. a check that should exist but doesn't), suggest capturing via `capture_idea`.

If the run surfaced something that is a defect in Dex itself — not the user's setup —
offer once, lightly: "I've patched this for you, but it looks like a bug in Dex itself.
Want me to report it so it gets fixed properly for everyone?" If yes, invoke the
`/feedback` skill; the Doctor findings you just gathered become the report's
machine-state and investigation ingredients, so the user does nothing but approve.

## Edge cases

- **Fresh vault, onboarding incomplete:** run anyway but expect many OFFs; say "you're
  early in setup — this is normal" rather than alarming.
- **Non-macOS:** launchd checks, and Apple Calendar checks, come back UNKNOWN with
  a note; don't present them as failures. Google Calendar is still checked when
  it is the configured calendar source.
- **User says "just fix everything":** Tier 1 is already done; walk Tier 2 items one
  confirmation at a time anyway — batch-yes is how wrong heals happen. Tier 3 cannot be
  batched by definition.
- **Repeated BROKEN on the same item across runs:** suggest reporting it —
  "this looks like a Dex bug, not your setup; want me to report it to the Dex team?"
  If yes, invoke the `/feedback` skill with the repeat-BROKEN evidence.

## Related Commands

- `/granola-setup`, `/calendar-setup`, `/google-workspace-setup`, `/enable-semantic-search` — Tier-3 fix paths
- `/dex-update` — often the fix for package/version drift
- `/feedback` — when a finding is a genuine Dex bug (not the user's setup), report it to the Dex team; the Doctor evidence becomes the report and the user only approves
- `/xray` — understand what the doctor checked and why
