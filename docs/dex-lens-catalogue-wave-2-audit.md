# Dex Lens catalogue — Wave 2 audit sheet

**Status:** audit only. No catalogue entries authored. Awaiting design-owner review before any
registry authoring begins.
**Audited against:** `origin/main` @ `9fab1a45`, Core v1.95.0.
**Date:** 2026-08-12.

---

## In plain English

Dex Lens privately looks at the AI system someone has built for themselves and shows which
proven Dex capabilities would make it stronger. Right now Lens knows about six Dex
capabilities. The decision has been made that it should eventually show the honest full
picture of what Dex does — not stop at six. This document is the homework before that
happens: a line-by-line pass over every skill Dex ships, sorting each one into *include now*,
*include later*, or *honestly leave out*, so nobody has to guess later.

**What the audit found, in four sentences:**

1. Dex ships **81 real skills** plus **27 role-specific skills** that stay dormant until a
   user adopts them. Of the 81, I recommend **18 for Wave 2**, flag **6 as genuine judgement
   calls**, and recommend **51 be honestly left out** (mostly borrowed third-party skills,
   one-time connection setup, and Dex's own maintenance plumbing).
2. **Two assumptions in the starting brief turned out to be wrong**, and both change the plan:
   the role packs are *not* already pinned in the catalogue — the catalogue builder actively
   refuses them — and the three backup skills cannot be merged into a single tidy entry,
   because the builder requires one entry per skill folder, named identically.
3. **A separate problem showed up that matters more than any of the above:** the catalogue as
   it stands today would fail to build. One of the six approved capabilities (`dex-doctor`)
   has a stale fingerprint, because its file was edited after the fingerprints were recorded
   and no automated check noticed. This affects the *existing* six, not the expansion, and it
   needs the tranche-1 lane to fix it before live proof.
4. The way Lens groups capabilities into "jobs" (currently 5 groups) needs **4 new groups** to
   hold the Wave 2 entries honestly, plus a wording widen on one existing group. Renaming any
   existing group is avoidable and should be avoided.

Nothing in this document is committed to shipping. Live proof of the six approved capabilities
remains a separate, independent lane and is not blocked by anything proposed here.

---

## What I actually verified (not assumed)

Every number below was measured against the working tree at `9fab1a45`, not inferred from names.

| Claim in the starting brief | Verified result |
|---|---|
| "about 82 active skills" | **82 directories** under `.claude/skills/`, of which **81 are real skills** with a valid `SKILL.md`. The 82nd, `.claude/skills/integrations/`, is a reference-document folder (`README.md` plus three `integrate-*.md` files) with no `SKILL.md` — not a skill, not a catalogue candidate. |
| "plus 10 dormant role packs" | **9 role packs** under `.claude/skills/_available/` (`customer-success`, `design`, `engineering`, `finance`, `leadership`, `marketing`, `operations`, `product`, `sales`) holding **27 skills**. Separately, `_available/capabilities/` holds **2 optional rooms with skills** (`career` → 3 skills, `quarter_goals` → 2 skills). The portable contract (`packages/dex-contracts/dist/portable-vault.contract.json`) declares **3 rooms**: `career`, `companies` (zero skills), `quarter_goals`. So: 9 packs + 3 contract rooms, not 10 packs. |
| "registry already pins their dormant skills" | **False.** `core/lens-catalog/registry.json` contains six entries, all tranche-1, and zero role-pack entries. The builder additionally *forbids* dormant paths (see the blocker below). |
| Skill metadata is catalogue-ready | **81 of 81** active skills have YAML frontmatter with a single-line `description:` field, so the builder's summary extraction (`_skill_description`) succeeds for all of them. **81 of 81** are tracked by git and none is a symlink, so the builder's tracking and regular-file checks pass for all of them. |
| Evidence availability | Every active skill can satisfy the builder's mandatory `evidence` array via a `runtime-path` reference to its own `SKILL.md`. **Behavioural** test evidence is much thinner and was checked per candidate below. |

Headroom is not a constraint: the vendored schema allows up to **300 capabilities** and **80
job groups**. The limit on Wave 2 is editorial quality, not schema capacity.

---

## Three findings that change the plan

### 1. 🚩 The catalogue does not build today — `dex-doctor`'s fingerprint is stale

The registry records a content fingerprint (`sha256`) and byte size for each capability's
source file, and the builder refuses to produce a catalogue if the real file no longer matches.
`dex-doctor/SKILL.md` has drifted:

```
daily-plan           pinned= 30797 actual= 30797  OK
week-plan            pinned= 12007 actual= 12007  OK
process-meetings     pinned= 19094 actual= 19094  OK
dex-doctor           pinned= 17429 actual= 17600  DRIFTED
relationship-radar   pinned=  5811 actual=  5811  OK
save-insight         pinned=  2658 actual=  2658  OK

REAL REGISTRY: generator FAILED -> entry 3 source does not match its declared sha256 or byte_size
```

*Cause, traced:* the pins were refreshed on 2026-08-11 (`56958586`, "Refresh Lens catalogue
source pins"). PR #432 (`2bef8ee1`, "Troubleshooting home for /dex-doctor and /feedback")
edited `dex-doctor/SKILL.md` on 2026-08-12, after the refresh.

*Why nothing caught it:* `core/tests/test_dex_lens_catalog_generation.py` passes (16 tests) but
builds against a **synthetic fixture tree**, never the real registry. The only place the real
registry is exercised is the release job in `.github/workflows/ci.yml:393`, and that step is
gated behind `vars.DEX_LENS_CATALOG_RELEASE_GATE_ENABLED == 'true'`. So on every PR the
registry is unvalidated, and the drift surfaces for the first time at release.

*Ownership:* this is **tranche-1 scope, not Wave 2**. It is reported here, not fixed here —
this branch is audit-only and must not edit `registry.json`. Two things are needed, and the
second matters more than the first:

- refresh the `dex-doctor` pin, and
- add a PR-time check that runs the builder against the **real** registry, so a skill edit that
  invalidates a pin fails the PR that causes it rather than the release three weeks later.

Without the second, Wave 2 makes this failure mode 4× more likely simply by pinning 4× more
files.

### 2. 🚩 Wave 3 role packs are hard-blocked by the builder, twice over

I probed the real builder rather than reading it. Results:

| Probe | Outcome |
|---|---|
| Entry pointing at `.claude/skills/_available/sales/deal-review/SKILL.md` | `REJECTED -> source path must not be a dormant optional skill` |
| Entry pointing at `.claude/skills/_available/capabilities/career/skills/career-coach/SKILL.md` | `REJECTED -> source path must not be a dormant optional skill` |
| Entry `deal-review` pointing at the post-adoption path `.claude/skills/deal-review/SKILL.md` | `REJECTED -> source path is missing or not a regular file` |
| Entry pointing at `.claude/skills/commitments/SKILL.md` (active skill) | `ACCEPTED` |

Two independent blocks: an explicit `/_available/` guard
(`scripts/generate-dex-lens-catalog.py:243`), and the requirement that the source file exist as
a regular file in the release tree (`:143`). A dormant role skill lives at
`_available/<pack>/<id>/SKILL.md` in the release tree and only appears at
`.claude/skills/<id>/SKILL.md` after a user adopts it — so there is nothing at the path the
builder demands.

*What this means:* Wave 3 is **not** a registry-authoring exercise. It requires a deliberate
change to the builder and probably the schema — for example a `kind: "adoptable-skill"` source
type that pins the `_available/` source path while declaring the post-adoption id. That is a
contract change affecting signed output, and it should be scoped as its own piece of work with
its own review, not folded into Wave 2.

*A related honesty check that came out clean:* the 27 role skills **are** genuinely adoptable
by real users. `core/lifecycle/catalog/official-capabilities.json` lists all 27 as official
catalog items routed through the receipt-backed lifecycle service, so Wave 3 would be
describing something Dex really delivers, not vapour.

### 3. Entry ids are locked to folder names — "backup discipline as one entry" is not possible

The builder requires `source.path == .claude/skills/<entry_id>/SKILL.md`
(`scripts/generate-dex-lens-catalog.py:420`). Probed:

| Probe | Outcome |
|---|---|
| Entry id `backup-discipline` sourced from `.claude/skills/backup-setup/SKILL.md` | `REJECTED -> source path must match entry id 'backup-discipline'` |

The user-facing `title` is then auto-derived from the id by capitalising each hyphenated part
(`_human_title`), and `summary` is auto-derived from the skill's own frontmatter description.
So an entry cannot be renamed, retitled, or composed from several skills without changing the
builder.

**Recommendation:** ship backup as **three entries** (`backup-setup`, `backup-now`,
`backup-restore`) grouped under one new job. The three skills genuinely do three different
things, their descriptions already cross-reference each other correctly, and three honest
entries under one aisle reads better than one entry that quietly under-describes two-thirds of
the feature.

---

## Tranche 1 — already included (6, no change proposed)

| Capability id | Path | Job(s) served today |
|---|---|---|
| `daily-plan` | `.claude/skills/daily-plan/SKILL.md` | `plan-my-work` |
| `week-plan` | `.claude/skills/week-plan/SKILL.md` | `plan-my-work` |
| `process-meetings` | `.claude/skills/process-meetings/SKILL.md` | `process-meetings`, `keep-relationships-warm` |
| `dex-doctor` | `.claude/skills/dex-doctor/SKILL.md` | `keep-system-healthy` |
| `relationship-radar` | `.claude/skills/relationship-radar/SKILL.md` | `keep-relationships-warm` |
| `save-insight` | `.claude/skills/save-insight/SKILL.md` | `compound-learning` |

Only change needed to these six is the `dex-doctor` pin refresh described in finding 1, and it
belongs to the tranche-1 lane.

---

## Wave 2 — recommended includes (18)

All 18 are active shipped skills; I confirmed each is a real file, git-tracked, non-symlink,
with a frontmatter description the builder can read. Proposed capability id equals the skill
folder name in every case, because the builder requires it.

| # | Capability id | Path | Proposed job | Why include | Uncertainty |
|---|---|---|---|---|---|
| 1 | `daily-review` | `.claude/skills/daily-review/SKILL.md` | `plan-my-work`, `compound-learning` | Closes the loop `daily-plan` opens; the paired half of a routine Lens already describes. Behavioural evidence: `test_learning_capture_command_name.py`, `test_review_retirement.py`. | None. Strongest Wave 2 candidate. |
| 2 | `week-review` | `.claude/skills/week-review/SKILL.md` | `plan-my-work`, `compound-learning` | Same pairing logic for `week-plan`; explicitly avoids fake completion percentages, which is a genuine quality differentiator worth stating. Evidence: `test_review_retirement.py`, `test_instruction_honesty.py`. | None. |
| 3 | `commitments` | `.claude/skills/commitments/SKILL.md` | `stay-on-top-of-commitments` (new) | Reconciles promises made and asks received into owner/due/source, confirmation-gated. Strong evidence: `test_commitments_skill.py` pins the load-bearing behaviour and the skill ships its own `evals/trigger-cases.yaml`. | None. |
| 4 | `meeting-prep` | `.claude/skills/meeting-prep/SKILL.md` | `process-meetings` | The before-half of the meeting job Lens already covers; 12 KB of real workflow. | Evidence is `runtime-path` plus incidental mentions in `test_instruction_honesty.py`. No dedicated behavioural test — the entry must not imply one. |
| 5 | `meeting-closeout` | `.claude/skills/meeting-closeout/SKILL.md` | `process-meetings` | The immediately-after-half: locks decisions, owners and personal commitments while fresh. Dedicated test: `test_meeting_closeout_skill.py`. | None. |
| 6 | `triage` | `.claude/skills/triage/SKILL.md` | `stay-on-top-of-commitments` (new) | Routes orphaned inbox files and scattered checkboxes into the right project/person/goal. A real, recognisable pain. | `runtime-path` evidence only. |
| 7 | `project-health` | `.claude/skills/project-health/SKILL.md` | `plan-my-work` | Scans active projects for blockers and next actions — the "what's stuck" question. | Smallest Wave 2 candidate at 2.6 KB. Worth a read-through for depth before authoring; `runtime-path` evidence only. |
| 8 | `decision-log` | `.claude/skills/decision-log/SKILL.md` | `decide-and-record` (new) | Captures a decision with context, options, rationale and a review date, then finds it again. Shipped active *and* listed as an official catalog item. Evidence: `test_lifecycle_official_capabilities.py`, `test_adoption_effective_behavior.py`. | A stale 1.4 KB duplicate remains at `_available/leadership/decision-log/`. The active 4.5 KB version is the real one; the audit must pin the active path. |
| 9 | `delegate-check` | `.claude/skills/delegate-check/SKILL.md` | `stay-on-top-of-commitments` (new) | Reviews open delegations — what was handed off, to whom, status, next nudge. Same dual active/catalog status as above. | Same stale `_available/leadership/` duplicate caveat. |
| 10 | `initiative-kickoff` | `.claude/skills/initiative-kickoff/SKILL.md` | `decide-and-record` (new) | Turns "we've decided to start something" into a real initiative with an outcome and a why-now. Dedicated test: `test_initiative_kickoff_skill.py`. | None. |
| 11 | `product-brief` | `.claude/skills/product-brief/SKILL.md` | `decide-and-record` (new) | Guided extraction of an idea into a written brief; 16.8 KB, one of the deepest skills Dex ships. | `runtime-path` evidence only. Role-flavoured (product) — check it doesn't read as belonging in Wave 3. |
| 12 | `industry-truths` | `.claude/skills/industry-truths/SKILL.md` | `know-my-market` (new) | Makes time-horizoned assumptions about a market explicit so strategy isn't built on quicksand. Distinctive; few self-built systems do this. | `runtime-path` evidence only. Sole occupant of its proposed job — see the taxonomy question below. |
| 13 | `identity-snapshot` | `.claude/skills/identity-snapshot/SKILL.md` | `compound-learning` | Builds a living profile of working patterns and quality preferences from accumulated data — a clear "your system gets better the longer you use it" story. | `runtime-path` evidence only. |
| 14 | `journal` | `.claude/skills/journal/SKILL.md` | `compound-learning` | Morning/evening/weekly journaling with a genuine on/off toggle. | `runtime-path` evidence only. Overlaps candidate 15 — see below. |
| 15 | `weekly-reflection` | `.claude/skills/weekly-reflection/SKILL.md` | `compound-learning` | Guided reflection on what energised versus drained, and one change for next week. Distinct from `week-review`: how work *felt*, not what got done. Evidence: `test_adoption_effective_behavior.py`, `test_lifecycle_official_capabilities.py`. | **Overlap risk.** `journal`, `weekly-reflection` and `week-review` are three adjacent reflective surfaces. Three separate entries may read as padding. Design-owner call: ship all three with sharply differentiated `value` text, or drop `journal`. Stale `_available/leadership/` duplicate also exists. |
| 16 | `backup-setup` | `.claude/skills/backup-setup/SKILL.md` | `keep-my-work-recoverable` (new) | Automatic verified backups with tiered retention. Evidence: `test_backup_vault.py` (engine, installer and restore), `test_doctor.py`. | Requires a synced folder or cloud provider — must be stated as a prerequisite, not glossed. |
| 17 | `backup-now` | `.claude/skills/backup-now/SKILL.md` | `keep-my-work-recoverable` (new) | On-demand verified backup before a risky change. Same evidence. | Small (1.7 KB) but the behaviour is bounded and complete; small is honest here. |
| 18 | `backup-restore` | `.claude/skills/backup-restore/SKILL.md` | `keep-my-work-recoverable` (new) | Proves a backup actually restores, without ever overwriting the live vault. Same evidence. | The strongest of the three — "we prove the restore works" is exactly the claim most self-built systems cannot make. |

**Evidence-quality caveat, stated once and applied to all 18.** Automated name-matching from
skill id to test file is a lower bound, not a verdict: `save-insight` matched zero test files by
name yet is legitimately backed by `test_learning_capture_command_name.py`, and conversely
`test_nudge_calendar.py` mentions many skill names only incidentally in calendar-invite strings
and is **not** behavioural coverage for any of them. Every `evidence` array authored in Wave 2
must be hand-verified by reading the referenced test and confirming it exercises the claimed
behaviour. Where only `runtime-path` evidence exists, the entry should say so plainly — the
schema's `verified`/`supported` levels exist precisely so an entry can be honest about this.

---

## Wave 2 — borderline, design-owner decision needed (6)

Each has a recommendation. All six are mechanically eligible; the question is editorial.

| Capability id | Path | Recommendation | Reasoning |
|---|---|---|---|
| `pipeline-sync` | `.claude/skills/pipeline-sync/SKILL.md` | **Defer to Wave 3** | Genuinely good (live CRM view reconciled against a local tracker, confirm-gated writes) but it hard-requires Pipedrive, and its own description points at `pipeline-health`, which is a dormant sales-pack skill. It belongs with the sales pack, not in an everyday-workflow wave. |
| `enable-semantic-search` | `.claude/skills/enable-semantic-search/SKILL.md` | **Include** | Borderline because it looks like setup, but it is not: it is a capability Lens users would materially want (meaning-based search over their own notes, running locally) and 19 KB of real substance. Reclassify as capability, not plumbing. |
| `xray` | `.claude/skills/xray/SKILL.md` | **Include** | 25 KB — the largest skill Dex ships. Explains what just happened under the hood as AI education. Unusually well-aligned with the Lens audience, who are by definition people building their own systems. Weak evidence (`runtime-path`), so the entry must not overclaim. |
| `prompt-improver` | `.claude/skills/prompt-improver/SKILL.md` | **Exclude** | Rewrites a vague prompt into a structured one. Useful, but it is a generic AI-hygiene utility rather than a Dex capability; a Lens user's own system very likely has an equivalent. Including it invites "you already have this," which weakens every entry around it. |
| `scrape` | `.claude/skills/scrape/SKILL.md` | **Exclude** | Depends on Scrapling, which is explicitly *not* part of the default install. Advertising a capability that ships switched off, backed by an optional third-party dependency, is exactly the kind of claim the CFO test rejects. |
| `dex-level-up` | `.claude/skills/dex-level-up/SKILL.md` | **Exclude** | Recommends unused Dex features — it is Dex's own adoption surface. Lens already performs this function for the user's own system, so the entry would be self-referential. |

Net effect if all six recommendations are accepted: **Wave 2 = 20 entries** (18 + `enable-semantic-search` + `xray`), catalogue total **26**.

---

## Wave 3 — role packs and optional rooms (deferred, blocked)

**Do not attempt in Wave 2.** Blocked by finding 2 until the builder gains an adoptable-skill
source type. All paths below are relative to `.claude/skills/_available/`.

| Pack / room | Skills | Notes |
|---|---|---|
| `sales/` | `account-plan` (16.9 KB), `call-prep` (10.0 KB), `deal-review` (9.1 KB), `pipeline-health` (12.4 KB) | Deepest pack. Natural Wave 3 opener. Pairs with `pipeline-sync`. |
| `product/` | `customer-intel` (9.3 KB), `feature-decision` (10.2 KB), `roadmap` (6.1 KB) | Substantial. |
| `marketing/` | `audience-intel`, `campaign-review`, `content-calendar`, `messaging-audit` | All 1.9–2.3 KB — thin. |
| `engineering/` | `architecture-decision`, `incident-review`, `tech-debt` | All ~1.6–1.8 KB — thin. |
| `finance/` | `board-prep`, `close-status`, `variance-analysis` | All ~1.6 KB — thin. |
| `customer-success/` | `expansion-opportunities`, `health-score`, `renewal-prep` | All ~1.7 KB — thin. |
| `operations/` | `metrics-review`, `process-audit` | Both ~1.5 KB — thin. |
| `design/` | `design-review`, `design-system-audit` | Both ~1.5–1.7 KB — thin. |
| `leadership/` | `decision-log`, `delegate-check`, `weekly-reflection` | **Already active and shipped by default** — promoted to Wave 2 above. The `_available/leadership/` copies are stale ~1.4–1.6 KB leftovers superseded by the richer active versions. Wave 3 should treat this pack as empty. |
| `capabilities/career/` (contract room) | `career-setup` (14.8 KB), `career-coach` (29.5 KB), `resume-builder` (29.6 KB) | Deepest content in the entire dormant set. Activated via the portable contract and `/manage-capabilities`, a *different* mechanism from the role packs — likely needs separate handling from the 9 packs. |
| `capabilities/quarter_goals/` (contract room) | `quarter-plan` (9.4 KB), `quarter-review` (12.9 KB) | Quarterly tier of the planning hierarchy `daily-plan`/`week-plan` already represent in tranche 1. Arguably the highest-value deferred pair, and awkward to leave out of a "plan my work" story long-term. |
| `capabilities/companies` (contract room) | none | Declared by the contract with zero skills. Not a catalogue candidate. |

**Honesty check for Wave 3, worth flagging now:** 15 of the 27 role-pack skills are under
2 KB. A catalogue entry with a `value` line, prerequisites, trade-offs and a portable brief
attached to a 1.5 KB skill risks the entry promising more than the skill delivers. Wave 3
should include a depth pass, not just an authoring pass — and it may honestly conclude that
some thin skills should be deepened before they are advertised, or left out.

**Separate drift noticed while verifying the role-pack activation path** (low severity, not
blocking, not fixed here — outside this branch's remit): `.claude/skills/dex-level-up/SKILL.md`
maps user roles to role-pack directories, and two mappings do not resolve. It names role groups
`support` and `advisory`, which have no `_available/` directory, and it writes
`customer_success` with an underscore while the directory is `customer-success` with a hyphen.
The listing step at line 86 (`List files in .claude/skills/_available/[role_group]/`) would
therefore find nothing for those users. Actual adoption is unaffected, because it routes
through `build_inventory_and_plan` against `official-capabilities.json` rather than the
directory listing. Recommend a separate small fix; Wave 3 should not build on the broken
mapping.

---

## Honest exclusions (51)

Grouped by the reason they are excluded. Every one was checked individually; none is excluded
merely for having an unfamiliar name.

### Vendored third-party skills — 16

`anthropic-algorithmic-art`, `anthropic-brand-guidelines`, `anthropic-canvas-design`,
`anthropic-doc-coauthoring`, `anthropic-docx`, `anthropic-frontend-design`,
`anthropic-internal-comms`, `anthropic-mcp-builder`, `anthropic-pdf`, `anthropic-pptx`,
`anthropic-skill-creator`, `anthropic-slack-gif-creator`, `anthropic-theme-factory`,
`anthropic-web-artifacts-builder`, `anthropic-webapp-testing`, `anthropic-xlsx`

**Reason:** these are bundled third-party skills, not Dex capabilities. Dex did not design
them, does not own their quality, and cannot honestly present them as evidence of what Dex
offers — a Lens user on Claude Code can obtain them independently. **Important:** I verified
the builder does **not** enforce this — an entry for `anthropic-docx` was `ACCEPTED` in probing.
The exclusion is an editorial choice that has to be made deliberately, and it is the right one.

### One-time connection and setup plumbing — 19

`setup`, `getting-started`, `reset`, `manage-capabilities`, `connect`, `calendar-setup`,
`granola-setup`, `google-workspace-setup`, `ms-teams-setup`, `zoom-setup`, `atlassian-setup`,
`pipedrive-setup`, `todoist-setup`, `things-setup`, `trello-setup`, `dex-obsidian-setup`,
`integrate-mcp`, `dex-add-mcp`, `create-mcp`

**Reason:** each is a wizard that runs once to connect a tool or lay out a vault. A Lens user
is being shown *what a capable system does for them*, not how Dex installs itself. The
capability that matters is the workflow the connection unlocks, and where that workflow is
worth showing it appears elsewhere in this audit.

### Dex self-maintenance — 7

`dex-update`, `dex-rollback`, `dex-whats-new`, `dex-backlog`, `dex-improve`, `feedback`,
`dex-orient`

**Reason:** these maintain *Dex specifically* — its updates, its rollbacks, its idea backlog,
its bug reports, its own codebase orientation. They are not portable advice for someone else's
system. `dex-doctor` is the deliberate exception already in tranche 1, and it earns it because
honest health reporting is a genuinely transferable design principle, not a Dex housekeeping
chore.

*Noted for the design owner:* `dex-update` and `dex-rollback` implement a receipt-backed,
rewindable adoption lifecycle that is arguably one of the more transferable ideas Dex has
("never change a system without a receipt you can rewind"). If a future wave wants to carry
that idea to Lens users, the honest vehicle is a **foundation-capability narrative**
(`safe-change-recovery` already exists in the vocabulary), not a capability entry that
advertises Dex's own updater.

### Core-developer tooling — 8

`skill-score`, `create-skill`, `diff-adopt`, `diff-adopt-profile`, `diff-generate`,
`diff-list`, `diff-profile`, `diff-remove`

**Reason:** these serve people building Dex, not people using it. The `diff-*` family manages
publishing and adopting Dex customisation diffs; `skill-score` grades a skill against the
internal authoring rubric. Presenting internal tooling as user capability is precisely the kind
of breadth-over-substance move the CFO test is meant to catch.

### Retired — 1

`review`

**Reason:** `.claude/skills/review/SKILL.md` is a deprecation alias that redirects to
`daily-review` and, per `core/tests/test_review_retirement.py`, "will be removed after one
release." I verified the builder **accepts** it (it is a well-formed skill file), so nothing
mechanical prevents the mistake — cataloguing it would sign a capability that is scheduled for
deletion. The starting brief listed `review` as a Wave 2 candidate; that is the one candidate
in the brief that must be dropped outright, with `daily-review` taking its place.

---

## Proposed Wave 2 jobs taxonomy — 5 aisles becoming 9

Proposal only. Not implemented on this branch. The existing five are `plan-my-work`,
`keep-relationships-warm`, `process-meetings`, `keep-system-healthy`, `compound-learning`.

### Four additions

| New `job_id` | Proposed label | Holds | Rationale |
|---|---|---|---|
| `stay-on-top-of-commitments` | Stay on top of commitments | `commitments`, `delegate-check`, `triage` | The single most common failure of a self-built system: promises and asks scatter across meetings, notes and inboxes and quietly go unmet. `plan-my-work` is about choosing today's focus; this is about nothing falling through, which is a different job. |
| `decide-and-record` | Decide and record | `decision-log`, `product-brief`, `initiative-kickoff` | Making a decision and being able to reconstruct *why* months later is a distinct job from planning or learning capture. `compound-learning` is about reusable lessons; this is about the durable record of a specific choice. |
| `know-my-market` | Know my market | `industry-truths` | The only aisle in the proposal with a single occupant. Kept because the job is real and unmistakable, and because Wave 3 has obvious future occupants (`audience-intel`, `customer-intel`, `messaging-audit`, `pipeline-health`). **Design-owner call:** accept a one-occupant aisle now, or defer this aisle to Wave 3 and temporarily file `industry-truths` under `plan-my-work`. My recommendation is to accept it — a strategy capability filed under "plan my work" misdescribes it. |
| `keep-my-work-recoverable` | Keep my work recoverable | `backup-setup`, `backup-now`, `backup-restore` | Deliberately distinct from `keep-system-healthy`. "Is it working?" and "can I get my work back if it isn't?" are different questions, and the second is one almost no self-built system answers. Named for the user's work, not the system, which is the honest framing. |

### One wording widen, no id change

`process-meetings` currently reads as narrow, and Wave 2 adds `meeting-prep` (before) and
`meeting-closeout` (immediately after) to it. Recommend widening its `label` and `description`
to cover the full arc — for example label **"Prepare for and close out meetings"** — while
leaving `job_id` untouched.

**Why not rename the id:** `job_id` is the value Lens consumers match against, and it is carried
in signed output. Renaming it is a consumer-visible breaking change for zero user benefit,
whereas `label` and `description` are free text the builder passes straight through. Widen the
words, keep the contract.

### Deferred to Wave 3

`run-my-role` — the aisle that would hold the role packs. Blocked with them, per finding 2.

**Result:** 9 aisles. The schema permits 80, so there is ample room for `run-my-role` and any
Wave 3 additions later.

---

## Checks run on this branch

Honest accounting of what was and was not executed.

| Check | Command | Result |
|---|---|---|
| Lens catalogue builder unit tests | `python3 -m pytest core/tests/test_dex_lens_catalog_generation.py -q` | **16 passed.** Note: these build against a synthetic fixture tree, not the real registry — see finding 1. |
| Real-registry build (audit probe) | builder's `_build_catalogue` invoked against the real tree | **FAILED** — `dex-doctor` pin drift. Pre-existing on `main`, not caused by this branch. This is the finding, not a regression. |
| Include/exclude classification completeness | scripted assertion over `.claude/skills/` | **81 of 81 classified, zero duplicates, zero unclassified.** |
| Skill metadata readability | scripted frontmatter parse | **81 of 81** have a builder-readable single-line `description:`; **81 of 81** git-tracked, zero symlinks. |
| Builder acceptance probes | 9 probes against the real builder | All results reported inline above. Registry restored to its committed state afterwards; `git status` verified clean. |
| Markdown lint | — | **Not run: no Markdown linter exists in this repo.** No `markdownlint`, `remark`, `prettier` or `vale` configuration is present, and `package.json` defines no lint script covering `.md`. Claiming a Markdown check ran would be false. |
| Documentation drift gate | reviewed `scripts/check-doc-drift.sh` | **Not applicable by design.** The gate triggers only on changes to `core/**/*.py` and `.claude/hooks/**/*.{js,cjs}`. This branch changes one Markdown file, so the gate takes its no-op path. |
| Diff-aware test gate | reviewed `scripts/check-test-delta.sh` | **Not applicable by design**, same path filter as above. A docs-only change requires no test delta. |
| PII / founder-content gates | reviewed `scripts/check-pii.sh`, `scripts/check-founder-content.sh` | This document contains no personal names, addresses, credentials or founder-personal content. Full CI will run both gates on the PR. |

Full CI runs on the pull request; nothing above should be read as a substitute for it.

---

## Boundaries observed on this branch

- **No registry authoring.** `core/lens-catalog/registry.json` is untouched. Probing wrote to a
  temporary copy and restored the committed file; `git status` was verified clean afterwards.
  The only change on this branch is this document.
- **Authoring waits for design-owner review.** No Wave 2 entry is written until the
  include/exclude/wave classification and the taxonomy proposal above are approved. The
  numbers in this document are recommendations, not decisions.
- **Live proof stays independent.** Tranche-1 live proof of the six approved capabilities does
  not depend on anything proposed here and is not blocked by it. Finding 1 is the one place the
  two lanes touch, and it is a pre-existing tranche-1 defect this audit surfaced rather than
  anything the expansion introduces.
- **Untouched:** release workflow, signing, secrets, deploy, DNS, public copy, the release gate
  variable, and the vendored schema. No external sends, no live claims, no real-user pilots.

---

## What the design owner is being asked to decide

1. **Wave 2 scope** — accept the 18 recommended includes, and rule on the 6 borderline cases
   (my recommendation nets 20 entries, catalogue total 26).
2. **The reflective overlap** — `journal`, `weekly-reflection` and `week-review` are three
   adjacent surfaces. Ship all three with sharply differentiated value text, or drop `journal`?
3. **`know-my-market` as a single-occupant aisle** — accept now, or defer to Wave 3?
4. **Backup as three entries** — confirmed as the only option the builder permits; confirm it
   is acceptable editorially.
5. **Who owns finding 1** — the `dex-doctor` pin refresh *and* the missing PR-time check on the
   real registry. This is tranche-1 work and it blocks live proof.
6. **Whether Wave 3 gets its own scoping** — it needs a builder and probably schema change, not
   registry authoring, and should not be folded into Wave 2.
