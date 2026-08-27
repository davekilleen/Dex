# /dex-doctor — specification (v1)

**Status:** approved by Dave 2026-07-11 ("spec it and then ship it"; "replace health check").
**Replaces:** `/health-check` (deleted; all references repointed).

## Why

The 2026-07-10 audit found that Dex's failures cluster into one root defect: Dex misreports
its own state. Health machinery existed but was dishonest in specific, recurring ways —
checks that never ran, checks that probed an easier path than the real feature, "off"
reported as "broken", and background jobs that died silently for months. `/dex-doctor` is
the single diagnostic surface built against those exact failure modes, with self-healing
where that is provably safe and user guidance only where Dex genuinely cannot act.

## Design rules (each one paid for by a specific audit finding)

1. **Probes exercise the real path.** A check must use the same code path and parameters
   the real feature uses. (Granola reported "connected" while every real query failed,
   because its probe omitted the parameter that was broken.)
2. **Four verdicts, never collapsed:** `OK` · `OFF` · `BROKEN` · `UNKNOWN`.
   `OFF` = deliberately not enabled/installed — healthy, never nagged, never an error.
   `UNKNOWN` = the check itself could not run — surfaced prominently, never silently
   counted as passing. (The launch-agent validator was blind for months because
   "didn't check" looked identical to "passed".)
3. **Freshness, not just configuration.** For every installed background job: is it loaded,
   did its last run succeed, and how stale is its output vs its cadence? (A user's contact
   sync was dead from February to July with zero signal.)
4. **The doctor checks its own instruments.** The collector counts checks attempted vs
   completed; any probe that raises becomes `UNKNOWN` with the error attached. The report
   opens with instrument status if anything could not be checked.
5. **Self-heal is tiered by risk, and conservative.**
   - **T1 — auto-fix silently, report after.** Only actions that are provably safe,
     idempotent, and reversible, touching no user data and no credentials:
     create missing standard PARA directories; regenerate the generated `core/paths.json`;
     restore executable bits on repo-shipped scripts; tighten a vault-root `.env` that other
     accounts could read to owner-only permissions (permission bits only — the file's
     contents are never read, copied, or logged).
   - **T2 — propose, fix on explicit yes.** State-changing but standard: load an installed-
     but-unloaded `com.dex.*` launch agent; re-run plist substitution from templates;
     repair a `.mcp.json` entry whose target file is missing (additive/corrective edits
     only — never remove user-added servers); reinstall missing Python packages into `.venv`.
   - **T3 — user-only, guided.** Grant macOS Calendar/Reminders permission; paste an API
     key; install an app (Granola, node, bun/qmd); sign in. Doctor gives exact steps and
     the skill to run (e.g. `/granola-setup`).
   - **Never:** delete or overwrite user data; touch credential *contents*; force-anything.
     (The one credential-adjacent T1 heal — tightening `.env` to owner-only — changes
     permission bits through a no-follow descriptor and never reads, copies, or logs a
     byte of the file.) A doctor that mis-heals is worse than one that only reports.

## Architecture

Two layers, separated so the facts are deterministic and testable:

### 1. Collector — `core/utils/doctor.py` (Python, stdlib + existing deps only)

Read-only by default. Emits JSON to stdout. Reuses `core/utils/preflight.py` and
`core/paths.py` rather than duplicating them.

```
python core/utils/doctor.py            # quick mode, JSON to stdout
python core/utils/doctor.py --deep     # adds live probes (network / EventKit)
python core/utils/doctor.py --heal     # apply T1 heals only; JSON notes what was done
```

JSON contract:
```json
{
  "generated_at": "ISO8601",
  "mode": "quick|deep",
  "instruments": {"attempted": 14, "completed": 14, "failed": []},
  "checks": [
    {
      "id": "granola.query_path",
      "feature": "Granola meeting sync",
      "verdict": "OK|OFF|BROKEN|UNKNOWN",
      "detail": "one plain-English sentence",
      "heal": {"tier": 1|2|3, "action": "…", "applied": false} | null
    }
  ],
  "summary": {"ok": 9, "off": 3, "broken": 1, "unknown": 1}
}
```

Written after every run: `System/.doctor-last-run.json` (same JSON) — so future features
(session-start staleness surface) can report on the doctor itself.

### 2. Skill — `.claude/skills/dex-doctor/SKILL.md` (instruction layer)

Runs the collector, then:
1. Renders the report grouped by verdict — broken first, unknown second, off last
   (labelled "off — that's fine"), healthy collapsed to one line.
2. Reports T1 heals already applied ("Fixed automatically: …").
3. Proposes T2 heals one at a time, applying each only on explicit yes.
4. For T3, gives the exact guided steps / setup skill per feature.
5. Ends with the four-bucket summary: **Fixed / Needs your OK / Needs your hands / Healthy**.
6. Tracks usage silently (existing usage-log convention).

Register in the skills catalog; `/health-check` directory is deleted and every reference
repointed to `/dex-doctor`.

## Check registry — v1

### Quick (default, no network, target < 5 s)

| id | probe | OFF when | BROKEN when |
|---|---|---|---|
| vault.structure | PARA dirs from `core.paths` exist | — | missing dirs (T1 heal: create) |
| vault.configs | `user-profile.yaml`, `pillars.yaml`, `.claude/settings.json` parse; vault-root `.env` is owner-only | — | parse error (T3: guided repair) / `.env` readable by other users (T1 heal: tighten to 0600 when we own the regular file; T3 manual guidance when `.env` is a symlink or owned by another user). Both conditions are always evaluated — a parse failure never hides the permission finding, and the post-heal annotation appends to a still-BROKEN result instead of replacing its heal |
| mcp.registered | `.mcp.json` exists, valid; every entry's target file exists | no `.mcp.json` + never onboarded | entry → missing file (T2 repair) |
| mcp.orphans | every `core/mcp/*_server.py` present in `.mcp.json` | — | orphaned server (T2 add) |
| python.env | `.venv` python exists; `mcp`, `yaml`, `dateutil`, `requests` importable | — | missing (T2: pip install into venv) |
| hooks.wired | every hook command in `settings.json` points at an existing file | — | dangling hook (T2) |
| jobs.loaded | classifies every `~/Library/LaunchAgents/*.plist` once per run (shared with jobs.fresh, via `core/utils/launch_agents.py` — the same module the session-start hook calls, so hook warnings and doctor findings can never diverge). Ownership is path evidence, never the filename: a `ProgramArguments` invocation referencing the checked vault (absolute path contained by the vault, or the vault path embedded in a shell string) claims the agent under any label, so user-installed jobs are covered; a plist whose strings reference the vault's stored former root (`~/.config/dex/vault-path` breadcrumb, boundary-matched) is owned-and-stale → BROKEN with a T2 repoint-or-remove heal, never skipped as another product's — including owned agents with leftover former-root keys (partially repointed). The shipped-name heuristic (`com.dex.` / `com.claudesidian.` prefixes only, so `com.samsung.dex.*` / `com.dexcom.*` are never touched) exists solely so a corrupt shipped plist reads `UNKNOWN` instead of foreign; a corrupt third-party plist can never degrade the probe. Same-label agents for another vault, including another temporary worktree vault, are skipped as foreign state. Owned agents get `launchctl list` state + interpreter exists+executable (ProgramArguments[0]). | no attributable plist installed | installed but unloaded (T2 load) / stale former-vault paths (T2 repoint/remove) / interpreter missing (T3 install node) |
| jobs.fresh | audits the health promise register (`core/health/promises.py`): each installed job's success receipt vs its promised cadence (meeting-intel `lastSync` >48 h, smoke-nightly success log >26 h, changelog-checker/learning-review activity logs >7 d). Legacy `com.claudesidian.*` labels map onto their `com.dex.*` promises, so pre-rename installs get real audits. Receipts prove completion, not activity — a job that keeps running while failing reports BROKEN. Daemons and same-label foreign jobs are ignored; an unreadable shipped plist is `UNKNOWN`. Owned agents with no registered promise are named at every verdict as "checked for loading only, not freshness" so OFF can't read as full coverage. | no attributable job installed | receipt missing ("never recorded a completed run") or stale beyond cadence (detail says last-success date) |
| preflight.queue | `run_preflight()` result + queued errors | — | per preflight |
| doctor.self | instruments counter; last-run file writable | — | any probe raised (UNKNOWN with error) |

### Deep (adds live probes; the skill states it will contact services first)

| id | probe | OFF when | BROKEN when |
|---|---|---|---|
| granola.query_path | filtered `created_after` list via the same helper real queries use (`_cutoff_iso`) | no `GRANOLA_API_KEY` | API error (surface `GranolaAPIError` detail) |
| pipedrive.connection | resolves the server's own `feature_status` payload, then proves the stored credential with one live `users/me` read | Pipedrive not connected, or `enabled: false` in `System/integrations/config.yaml` | auth/API failure, or missing `base_url`/`company_domain` (T3: run `/pipedrive-setup`) |
| config.meeting_sources | `meeting_sources.notes_folder` (profile) must exist inside the vault (symlink escapes refused) and contain at least one supported note; empty-but-configured is `UNKNOWN`, not BROKEN | no meeting source configured | folder missing or outside the vault |
| update.post-canary | reads the post-update canary receipt (`System/.dex/health/post-update-canary.json`) written right after an update applies | no canary has run yet | last canary failed (plan/state doors did not open after an update) |
| calendar.access | `calendar_list_calendars` path via EventKit; configured `work_calendar` present in the list | permission never granted AND feature unused | permission denied (T3) / configured calendar not found (T3: set `calendar.work_calendar`, list real names) |
| qmd.live | registered in `.mcp.json` → `which qmd` + `qmd status` | not registered (opt-in respected) | registered but binary/status fails (T3: `/enable-semantic-search`) |
| integrations.enabled | for each `enabled: true` in `System/integrations/config.yaml`, run its existing health checker (gmail/teams/connection cjs) | not enabled | checker reports failure |
| mcp.importable | each registered `core/mcp/*_server.py` imports in a subprocess | — | ImportError (T2: reinstall deps) |
| backup.freshness | reads the engine's run record (`System/.dex/backup-last-run.json`, written on every run, success or failure) against the `backup:` block in `System/integrations/config.yaml`. OFF when backups are not configured (a healthy, never-nagged state). OK when the newest run succeeded within 2 days AND recorded no warnings; a run that succeeded but stored less than a full backup (history it could not bundle, linked files a restore cannot unpack) is BROKEN with the recorded reason, never a bare OK. Sandbox denials while reading config or record are `UNKNOWN`; an unparseable record is `UNKNOWN`, never silently OK. Exists because a real vault's scheduled backup died silently for ten days. | `backup.enabled` absent or false | last run failed (detail carries the stamped error), configured-but-never-ran, or newest success older than 2 days (T3: `/backup-setup`) |

Sandbox note (for the builder): EventKit/GPU/permission probes can fail in a sandboxed
build environment even when correct — such failures must map to `UNKNOWN`, and tests must
stub all external probes.

## Testing (required)

`core/tests/test_doctor.py`, no network, all probes stubbed:
- verdict mapping per check type incl. OFF-vs-BROKEN boundaries (e.g. no API key → OFF,
  API 400 → BROKEN; job-not-installed → OFF, installed-but-stale → BROKEN)
- a raising probe → UNKNOWN + instruments.failed populated, exit code still 0, JSON valid
- `--heal` applies T1 only (tmp vault fixture: missing dir gets created; nothing else touched)
- JSON contract shape (keys, verdict enum) — this is the skill's API
- freshness thresholds honored only when job installed
- `--heal` prints `Apply safe Tier-1 repairs before checking.` on stderr immediately, then `Checking this Dex install (read-only)...` before the read-only pass; JSON stays on stdout at the end
- probes and Tier-1 heals run in-process; Doctor does not abandon work in daemon threads after a shared deadline

## Non-goals (v1)

- No scheduled/automatic doctor runs (session-start already runs preflight; doctor is
  on-demand). A later `--brief` integration may surface staleness at session start.
- No healing of user content, ever.
- No new external dependencies.

## Rollout

One PR: collector + tests + skill + `/health-check` deletion + reference repoints +
CHANGELOG (house style) + version bump. Ships as v1.27.0 via the normal release pipeline.

## Adoption, holdback, and recovery section (D2)

Doctor's additive `adoption` section is a deterministic, read-only report. Shell and
skills collect inputs and render; they never own lifecycle mutation. The collector emits
canonical JSON from a frozen `AdoptionReport` with exactly five ordered groups:

1. `new-and-safe` — catalog items whose planner action is `adopt`.
2. `needs-your-review` — items whose action is `conflict`, with planner reason codes
   and per-file reason/path pairs. Planner `unknown` items are retained here verbatim
   and make the group/report `UNKNOWN`; unprovable authority never disappears.
3. `preserved-for-now` — ledger-held items plus `stock-modified` files preserved from
   the `CustomizationReport`.
4. `continue-or-recover` — unfinished transaction journals found by read-only,
   `Transaction.resume`-style classification, transaction-inspection errors, and
   incomplete or invalid ledger publication.
5. `receipts-and-rewind` — current ledger adoption receipts: item, version,
   transaction-id-derived local time, `rewind_verdict`, and whether the canonical
   receipt, current bytes, committed journal, and retained snapshot all pass the
   engine's read-only rewind preflight (`rewindable: true`). A cleanly absent snapshot
   is pruned (`false` with `rewind_verdict: OK`); invalid evidence is `UNKNOWN`.

Every group has `id`, `verdict`, `count`, authority records, and one fixed `surface`
line. Authority includes item ids and versions, actions, statuses, verdicts, counts,
paths, reasons, transaction ids, and rewindable booleans. A renderer reproduces these
verbatim. It may paraphrase only `surface`, as one plain-English sentence; it never
upgrades, downgrades, merges, omits, infers, or manufactures authority.

The fixed adoption-status vocabulary is `applied` / `adopted` / `rewound` /
`held-for-review` / `customization-review-required` /
`external-reconciliation-pending` / `needs-recheck` / `skipped-by-user` /
`failed-rolled-back`. Planner actions such as `adopt`, `conflict`, and
`skip-held-back` are also rendered exactly, never translated into a new status.

Degradation uses Doctor's existing vocabulary: `OFF` when no catalog is installed;
`BROKEN` for an invalid catalog or unfinished transaction; `UNKNOWN` when ledger or
transaction evidence cannot be verified; otherwise `OK`. Unknown ledger evidence
withholds unprovable adoption actions and carries the ledger-owned
`python3 -m core.lifecycle.cli --vault-root <vault> rebuild-state` command.

The collector never resumes, rolls back, rebuilds, quarantines, creates locks, or writes
a cache. The renderer may name only mechanisms the engine exposes: ledger
`rebuild-state`, read-only transaction evidence, and the exact receipt-backed
`rewind_adoption` flow when `rewindable` is true. It never invents a rewind CLI or
offers rewind after snapshot pruning.
