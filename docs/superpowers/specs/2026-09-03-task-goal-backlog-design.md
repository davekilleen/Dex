# Task–Goal Backlog Design (the missing planning layer)

**Status:** Design draft for founder review. Nothing here is built. Grounded in a
code audit of `core/mcp/work_server.py` and the planning skills on 2026-09-03.

**Decision:** Pending. The recommendation below is a generated per-goal backlog
view plus grooming skill, not a new hand-maintained document type.

## The user problem (verbatim, from beta feedback 2026-09-03)

> "Dex goes quarter goals → week priorities → daily plan → tasks. There's
> nothing in between for 'the running backlog of everything under this quarter
> goal / objective / area of responsibility' — the stuff I know I need to do,
> grouped by what it serves, not yet pulled into a week. At the moment
> everything lands as a flat task and Tasks.md becomes a swamp (mine hit ~40
> open P2s). I ended up hand-building a backlog doc per objective."

Logged in the reporter's own vault backlog as idea-023.

## Outcome

A user can see and groom everything open under each quarter goal (and each
pillar for work that serves no goal), mark what's next, and have `/week-plan`
pull from that groomed pool — without maintaining any document by hand, and
without a second source of truth that can drift from `03-Tasks/Tasks.md`.

## Verified Baseline (what the code actually does today)

The single most important finding: **task→goal linkage is already written but
has no reader anywhere.**

- `create_task` accepts a `goal` parameter (`core/mcp/work_server.py:3957`),
  validates it against parsed goal IDs (`:4788-4809`), and when omitted
  auto-infers a link via `infer_goal_link` (`:4877-4908`) — strong matches are
  hard-linked, weak ones written with a tentative ` (?)` marker that
  `confirm_goal_link` (`:5058-5170`) promotes or clears. The link is stored as
  a child bullet `- Goal: Q3-2026-goal-2` (`:4944-4946`) and parsed back
  (`:571-579`).
- But `list_tasks` filters only on `pillar`, `priority`, `status`, `source`
  (`:3932-3941`, `:4649-4675`). **No goal filter, no due filter, no project
  filter, no weekly-priority filter.**
- `calculate_goal_progress` (`:2370-2392`) rolls up weekly priorities only;
  tasks contribute nothing to goal progress.
- `check_goal_alignment` (`:6011-6054`) is advertised as "identify orphaned
  work" but its task half is a stub: `tasks_with_no_priority = []  #
  Simplified for now` (`:6023`). It always reports zero orphaned tasks.
- The only per-goal task reasoning in the product is prose instruction to the
  model in `week-plan/SKILL.md:83` ("Find tasks that could advance stalled
  goals") plus an optional semantic-search workaround (`:153-165`) — evidence
  the gap was already felt and papered over.
- `/triage` is an inbound router, not a groomer: it routes new items into the
  pool and dedups against it (`triage/SKILL.md:213-216`) but never
  reprioritizes, resequences, or retires existing tasks.
- There is no "next up", ordering, or dependency concept anywhere in skills or
  `work_server.py`. Ranking is a flat priority-score sort
  (`suggest_focus`, `:5479-5507`): P0=100 … P3=25, nothing else — no due date,
  no goal, no age, no effort.
- The only grouped view that exists is per-pillar (`get_pillar_summary`,
  `:5509`). No per-goal view.

### Defects found during the audit (fix regardless of this design)

These are bugs, not design gaps; several silently disable the goal machinery
the design depends on:

1. **The seed goals file is unparseable by the goal parser.**
   `01-Quarter_Goals/Quarter_Goals.md` invites freeform writing ("just start
   writing", line 6), but `parse_quarterly_goals` requires the
   `### N. Title — **Pillar** ^Qn-YYYY-goal-N` shape (`:2254`). A user who
   follows the file's own invitation gets zero parsed goals, so goal inference
   silently finds nothing and every weekly priority is tagged `operational`.
   The capability-room variant seed is equally unparseable. `/quarter-plan`,
   which would produce the parseable shape, lives only in the gated
   `quarter_goals` room and is not installed by default.
2. **Three-way Tasks.md section conflict.** The shipped seed is P0–P3
   sectioned (`03-Tasks/Tasks.md:9-21`); `core/provision.cjs:850-859` generates
   pillar-sectioned content instead; `create_task` defaults to a `"Next Week"`
   section (`work_server.py:3953`) that exists in neither and is injected
   fresh when missing (`:4969-4978`). Which structure a vault has depends on
   install path and persists forever (03-Tasks is user-owned,
   `core/portable_contract.py:84-93`). Pillar-sectioned vaults also lose
   section-derived priority entirely (`priority_from_section` `:431-446`
   matches only P0–P3 headings).
3. **`get_blocked_tasks` ignores the real blocked status.** It keyword-matches
   titles for waiting/blocked/pending (`:5470`) and never checks
   `status == 'b'`, even though `update_task_status(status="b")` writes a real
   `- [b]` checkbox (`:815`) that the parser reads back (`:2832`).
4. **`check_goal_alignment` orphan-task branch stubbed** (`:6023`, above).
5. **The Technical Guide documents a task format the code cannot read.**
   `docs/Dex_System/Dex_Technical_Guide.md:676-698` specifies inline
   `#pillar` / `[Q1-1]` goal / `[Week-3]` tags; the implementation reads only
   child bullets, and `[Q1-1]` fails the real goal-ID pattern
   `Q\d+-\d{4}-goal-\d+` (`:574`). Anyone following the guide produces tasks
   whose linkage is silently dropped.
6. **Status `s` (started) is unrepresentable on disk** — `n` and `s` both
   write `- [ ]` (`:811-821`) and round-trip back as `n`.

## Non-Goals

- No new hand-maintained backlog documents. A per-objective doc the user edits
  is a second source of truth; it will drift from Tasks.md and reproduce the
  swamp twice. (The reporter hand-built exactly this and found it clunky —
  that is the workaround to replace, not the pattern to bless.)
- No change to where tasks live. `03-Tasks/Tasks.md` remains the single store;
  everything here is readers, views, and one optional ordering field.
- No dependency graph / blocked-by model in this pass.
- No background automation; grooming stays a user-invoked conversation.

## Design

### Layer 1 — give the existing links readers (MCP, small)

1. `list_tasks`: add `goal` and `project` filters, plus `goal: "none"` /
   `"tentative"` selectors for orphaned and unconfirmed links.
2. New `get_goal_backlog(goal_id | "all")`: open tasks grouped by goal, then
   pillar-only work, then fully orphaned work; each group sorted by
   next-up order (Layer 2), then priority, then age. Returns counts and
   staleness so skills can say "Goal 2 has 14 open tasks, 9 untouched in
   3+ weeks".
3. Finish `check_goal_alignment`: implement the stubbed orphaned-task branch
   using the same parsed fields.
4. Fold task counts into `calculate_goal_progress` and
   `get_weekly_planning_context` (goal health should reflect the pool, not
   just the 3 weekly priorities).
5. Fix defects 3 and 6 above while in the file (blocked-status query; decide
   whether `s` gets a glyph or is removed from the enum).

### Layer 2 — one small schema addition: `Next up`

An optional child bullet `- Next up: 1..N` written by the grooming skill,
parsed like the other metadata bullets. Scoped per goal (or per pillar for
goal-less work). This is the entire "sequencing" model: no dependencies, no
dates — just "when this goal gets week-time, take these first."

### Layer 3 — `/goal-backlog` grooming skill

A conversation over `get_goal_backlog`, one goal at a time:

- show the group with age/staleness flags;
- confirm or clear tentative ` (?)` goal links (`confirm_goal_link` already
  exists for this);
- offer retire/archive for stale items (the 40-open-P2 swamp shrinks here);
- set `Next up` order for the survivors;
- flag orphans and offer to link or consciously leave them operational.

`/week-plan` step 2 then reads `get_goal_backlog` instead of relying on prose
("find tasks that could advance stalled goals") — its suggestions become
"Goal X's next-up items are A and B; they fit Wednesday's 3-hour block."
`/triage` gains one closing line: if the routed item landed under a goal with
a groomed order, ask whether it jumps the queue.

### Layer 4 — the try-it-then-roll-back experiment channel

Founder ask: let the reporter test the new logic on her own vault and roll
back to a snapshot if she doesn't like it. Audit of the existing machinery:

- **Lifecycle receipts** (`core/lifecycle/service.py`, `/dex-update` /
  `/dex-rollback`) have exactly the right semantics (snapshot → apply →
  verify → rewindable, refuse on drift) but structurally exclude vault
  content: `03-Tasks` is a user-owned region an update may never write into
  except to seed when absent (`core/portable_contract.py:79-93`), and
  `core/tests/test_apply_update.py:417,447` pins Tasks.md byte-identical
  across updates.
- **Backups** (`core/backup/backup_vault.py`) capture Tasks.md fully but
  restore only a whole archive into an empty non-vault folder
  (`core/backup/restore_vault.py:193-205`) — no single-file rollback.

So neither system can rewind task content today, and the receipts' user-region
law should not be weakened. Two honest options:

- **Option A (recommended): additive trial, no snapshot needed.** Layers 1–3
  are readers plus one optional child bullet per task. The rollback story is
  "stop using the skill and delete the `Next up` bullets", which the skill can
  offer as a one-command undo. Ship to her as a pre-release branch install;
  content risk is near zero because nothing existing is rewritten.
- **Option B (only if a future experiment must rewrite content, e.g. a
  Tasks.md restructure): a scoped experiment transaction.** A
  `/dex-experiment` skill that, with explicit consent naming the exact files,
  copies the declared file set to `System/.dex/experiments/<id>/` with hashes
  before applying, then offers keep/rollback; rollback refuses if the saved
  copies were tampered with, mirroring receipt semantics without touching the
  frozen lifecycle service. This is real machinery and only worth building
  when an experiment actually needs to rewrite user content — the current one
  does not.

### Sequencing

1. Defect fixes 1–6 (independent, small, ship first — several make the
   existing goal machinery work at all).
2. Layer 1 readers + Layer 2 field.
3. Layer 3 skill + `/week-plan` and `/triage` integration.
4. Beta trial with the reporter per Option A; her idea-023 write-up reviewed
   for anything this design misses.

## Open questions for the founder

1. Does `Next up` ordering earn its place, or is groom-and-retire (Layer 3
   minus ordering) enough for a first cut?
2. Should the unparseable seed goals file be fixed by making the seed
   parseable, by teaching the parser the freeform shape, or by promoting
   `/quarter-plan` out of the gated room? (Recommendation: parseable seed +
   promote the skill; parser leniency invites silent half-matches.)
3. Is Option B worth building now as general experiment infrastructure, or
   deferred until an experiment actually rewrites user content?
