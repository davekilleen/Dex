# Change-Job & Reset Safety Design (nothing lost, everything migrated)

**Status:** Design draft for founder review. Nothing here is built. Grounded in a
code audit of `core/mcp/onboarding_server.py`, `core/provision.cjs`,
`core/customization_migration/`, and the reset/onboarding flow on 2026-09-03.

**Decision:** Pending. Recommendation: fix reset's silent losses first (they are
defects against the skill's own promise), then build `/change-job` as
re-onboarding with carry-forward plus a guided migration pass — reusing the
existing customization-capsule machinery as the "nothing thrown out" verifier
rather than building a new MCP server.

## The user problem (verbatim, from beta feedback 2026-09-03)

> "I've gone from a fractional-CPO to full-time CPO. That means the whole
> structure has to move: pillars, quarter goals, the 05-Areas layout, People
> Internal/External routing (new email domain), what 'Career' means, where the
> old fractional identity goes. Right now it's a huge manual reshape — I did
> one restructure today that I had to partly redo. Is there / should there be a
> /changing-jobs skill? Can I do onboarding again — but I don't want to lose
> what I already have."

Logged in the reporter's own vault backlog as idea-022. She did not find
`/reset`, which is the closest existing feature — a discoverability failure in
its own right (the name promises the opposite of "don't lose what I have").

## Outcome

A user who changes roles runs one skill and ends with: profile, pillars and
rooms re-answered; every setting they did **not** re-answer carried forward
byte-for-byte; people re-routed for the new email domain; old-role goals,
priorities and projects archived with approval, never deleted; and a verified,
rewindable record proving nothing was silently lost. `/reset` stops being able
to lose anything even when used alone.

## Verified Baseline (what reset actually does today)

`/reset` → `start_onboarding_session(force_new=True)` → replay onboarding flow
→ `finalize_onboarding()`, which shells to `node core/provision.cjs --onboard`.
The skill's promise is "Nothing you've written is deleted or moved." That is
true for vault content and false for configuration:

**The profile is replaced, not merged.** `provision.cjs:1329-1337`: on the
onboard path `profile = freshProfile` — the existing file is read (`:1319`) and
discarded. `freshProfile` is the template plus an overlay filtered to 14
`PROFILE_KEYS` (`provision.cjs:12-16`). Everything outside those keys reverts
to template defaults. The `--adopt` path has a protective merge
(`deepFillMissing`, `:1338-1363`) and even a comment explaining why
`entity_creation` and `working_week` must be protected (`:1339-1341`);
`--onboard` has none of it and force-sets `entity_creation.mode = 'suggest'`
(`:454`), overriding an explicit `auto`.

**Silently lost on every reset** (template defaults, no preview, no backup):
`calendar.provider`/`calendar.work_calendar` and `work_email` (explicitly
popped from session data, `onboarding_server.py:345`; deleted keys are read by
`calendar_server.py:102-110` and attendee classification,
`attendees.cjs:79`), the entire `working_context`, `meeting_sources`
(the connected meeting reader is disconnected in config),
`journaling` flags, `quarterly_planning.q1_start_month` (a non-calendar fiscal
year is lost), all seven `meeting_intelligence` flags,
`meeting_processing.mode/api_provider`, `vault.auto_commit` (local git
snapshots silently stop), `feedback.review_mode` (an `auto-send` choice
reverts), `timezone`, `working_style`, `role_context`, analytics
`visitor_id`/`account_id`, and `role_group` — which is collected and previewed
(`onboarding_server.py:2274-2280`, `:2790`) but not in `PROFILE_KEYS`, so it
is silently dropped, breaking analytics role reporting
(`analytics_server.py:221`) and the `role_groups:`-keyed role-pack skills.

**`pillars.yaml` is overwritten with only `{pillars: [...]}`**
(`provision.cjs:1401-1414`): `priority_limits` is deleted (P0/P1/P2 caps
silently revert to hard-coded 3/5/10, `work_server.py:331-353`) and per-pillar
`keywords` are never written (`onboarding_server.py:574-577`), so pillar
inference (`guess_pillar`, `work_server.py:391-403`) is dead after any reset
until keywords are hand-restored.

**Rooms silently re-enable.** `_capability_states`
(`onboarding_server.py:553-564`) fills unanswered rooms from
`default_enabled: true` — not from the current profile — and Step 8 asks
nothing (`.claude/flows/onboarding.md:414-427`). Every room disabled via
`/manage-capabilities` turns back on and its skills are re-copied.

**Stale after a role change, with no migration code anywhere:**

- **People routing inverts.** Routing is decided once, at page-creation time
  (`work_server.py:1558-1577`), and recorded in three places: the
  Internal/External folder, `location:` frontmatter, and the
  `dex_last_written` mirror (`entity_engine/contract.py:787-808`). The people
  index derives internal/external from the folder (`entity_engine/index.py:245-250`).
  No re-routing, re-classification or person-migration code exists (verified
  by search). After a domain change, ex-colleagues stay Internal and new
  colleagues are created External.
- `System/.onboarding-complete` is `writeIfMissing` (`provision.cjs:1474`), so
  `check_onboarding_complete` keeps reporting the old role forever and
  `/getting-started` never re-offers.
- `01-Quarter_Goals`, `02-Week_Priorities`, `03-Tasks`, `04-Projects` still
  ladder to retired pillars; no archive-to-`07-Archives` helper exists in core
  (skill-level archiving is keyed to time boundaries, never profile changes).
  An existing `Tasks.md` keeps old pillar section headings while `pillars.yaml`
  names new ones.
- `System/usage_log.md`, `System/identity-model.md`,
  `System/integrations/*.yaml`, entity-engine caches
  (`System/.dex/contacts.json`, `ritual-intelligence.db`) — all old-role.
  Analytics consent can end up contradictory: profile says `enabled: true`
  while `usage_log.md` (the authoritative gate, `analytics_helper.py:214-223`)
  says opted-out.

**Process defects in the reset path itself:**

- `force_new=True` clears `harness_setup.confirmed` and the calendar gate, so
  `finalize_onboarding` hard-refuses (`onboarding_server.py:2734-2746`) unless
  steps the reset skill never mentions are replayed; if the user later picks
  "Skip for now" at the calendar step, the calendar/working-context losses
  become permanent.
- `finalize_onboarding(dry_run=True)` understates the change: the preview
  lists 11 of ~25 profile keys (`onboarding_server.py:2787-2806`), labels the
  profile replacement as a generic "update", and promises a fresh completion
  marker that `writeIfMissing` will not write. The real run reports the
  overwritten profile under `files_created` (`:699-715`).
- **Contract violation:** `core/provision-contract.json:52-58` declares
  `user-profile.yaml` and `pillars.yaml` user-owned, yet `--onboard` replaces
  both wholesale, with no capsule, no receipt-verified rollback
  (`ProvisionTransaction` only rolls back *failed* provisions), and no test —
  `test_instruction_honesty.py:415-432` lints the skill's *prose*; nothing
  tests reset over an existing profile.

**The linter mostly already exists.** `core/customization_migration/` (17
modules; spec `docs/plans/2026-07-24-customization-migration-mcp.md`, threat
model `docs/customization-migration-threat-model.md`) builds content-addressed,
SHA-256-manifested capsules of protected customizations under an owned
transaction lock — and its `USER_CONFIG_PATHS` (`inventory.py:41-49`) already
name `System/user-profile.yaml` and `System/pillars.yaml`, the exact two files
reset overwrites. It is wired only to the `/dex-update` lane; no capsule is
ever created for a reset. Separately, the lifecycle service already has the
precise invariant pattern needed: `_render_entity_creation_mode`
(`onboarding_server.py:1530-1593`) performs a surgical single-key edit and
raises "changed unrelated profile state" if anything else moved.

## Non-Goals

- No second onboarding flow. `/change-job` replays the same
  `.claude/flows/onboarding.md`; the reset skill's existing rule that the
  question script lives only in the flow stands.
- No automatic deletion or bulk file moves without per-pass approval. Archive,
  never delete; propose, confirm, apply.
- No weakening of the lifecycle service's frozen status or the user-owned
  region law. The capsule/verifier work reuses existing modules.
- No new standalone MCP server unless the capsule reuse proves impossible —
  the onboarding MCP plus `core/customization_migration` modules are the
  cheaper, already-threat-modeled home for the new tools.

## Design

### Phase 0 — make `/reset` unable to lose anything (defect fixes)

These hold regardless of whether `/change-job` ships:

1. **Carry-forward merge on the onboard path.** Over an existing profile,
   build `freshProfile` from re-answered keys, then carry forward every other
   key from the old profile (the `--adopt` merge generalized): re-answered
   wins, unanswered carries, template fills only what neither has. Remove the
   `entity_creation` force-set when a prior value exists. Preserve
   `priority_limits` and existing `keywords` in `pillars.yaml`; write keywords
   for new pillars at creation.
2. **Fix the dropped keys:** add `role_group` to `PROFILE_KEYS`; stop popping
   `work_email`/`calendar`/`working_context` into a skippable afterthought
   when values already exist — carry them forward by default.
3. **Room states default to current profile,** not `default_enabled`, when a
   profile exists.
4. **Honest preview:** `dry_run` must enumerate every key that will change,
   show old → new, and say "replace" where it replaces. The completion marker
   must be updated on re-finalize (new role, new `completed_at`), with the
   original onboarding date retained as a separate field.
5. **Reset skill mentions the re-armed gates** (harness confirm, calendar) so
   finalize cannot hard-refuse mid-flow with no explanation.
6. **Tests:** a reset-over-populated-profile parity test asserting every
   non-re-answered key survives byte-for-byte — the missing counterpart to
   `test_apply_update.py`'s user-content pins.

### Phase 1 — the preservation linter ("baby stays in the bath")

Founder proposal: an MCP server with a linter. Verdict: **the right mechanism
exists; wire it to this lane instead of building a new server.**

- **Before finalize:** create a customization capsule of the pre-change
  `user-profile.yaml`, `pillars.yaml`, and room state via
  `core/customization_migration` (these paths are already in its protected
  inventory). This is the snapshot: content-addressed, hash-manifested,
  transactional.
- **After finalize:** a new `verify_transition()` tool (onboarding MCP) diffs
  capsule vs. result against a **transition manifest** — the explicit list of
  keys this run was allowed to change (the re-answered steps). Any other
  changed key fails the verification, mirroring the existing "changed
  unrelated profile state" invariant. The report is shown to the user:
  "Changed (you chose): role, company, email_domain, pillars. Carried forward:
  31 settings. Lost: none."
- **Rollback:** the capsule gives a verified restore path for the two config
  files if the user rejects the result — reusing capsule verification
  semantics, without touching lifecycle receipts.

### Phase 2 — `/change-job` (the transition, not just the re-onboarding)

A skill (natural-language triggers: "I changed jobs", "new role", "went
full-time", "I'm now CPO at…"; `/reset` gains a pointer to it) that runs:

1. **Re-onboarding with carry-forward** — Phases 0–1 above, capsule first.
2. **People re-routing pass** — new MCP tool `reroute_people(old_domains,
   new_domains, dry_run)`: for each person page, recompute location from
   recorded `emails:` frontmatter against the new domain set; move
   Internal/External, rewrite `location:` and the `dex_last_written` mirror,
   rebuild the people index. Propose-confirm-apply with a full list shown;
   ambiguous pages (no email) listed, never guessed. This tool is net-new —
   nothing like it exists.
3. **Identity archive pass** — offer to archive old-role
   `Quarter_Goals.md` and `Week_Priorities.md` to
   `07-Archives/Role_Transitions/<date>-<old-role>/` (the quarter-plan
   archive pattern, extended to role boundaries), and walk active
   `04-Projects/` with close/carry/archive per project.
4. **Task re-pillar pass** — hand the open pool to the grooming flow (see the
   companion spec `2026-09-03-task-goal-backlog-design.md`): remap or retire
   open tasks against the new pillars; reconcile `Tasks.md` section headings.
5. **Housekeeping pass** — refresh the completion marker, offer
   `/identity-snapshot` regeneration, flag stale `System/integrations/*.yaml`
   entries and old-employer MCP servers for review (never auto-remove), reset
   usage-log role-specific sections, prompt Career-folder reframing.

Each pass is independently skippable and independently reversible (capsule for
config; git/archive moves for content). The final report is the linter output
plus a per-pass ledger.

### Sequencing

1. Phase 0 defect fixes + tests (small, high-severity, justified alone: the
   current behavior contradicts the skill's stated promise and the provision
   contract).
2. Phase 1 capsule wiring + `verify_transition`.
3. Phase 2 skill, passes 2–3 first (people re-routing and archiving are the
   reported pain), then 4–5.
4. Beta trial with the reporter; review her idea-022 write-up for anything
   missed.

## Open questions for the founder

1. Naming: keep `/reset` and add `/change-job` as the guided transition on top
   (recommended — reset stays the honest low-level lever), or fold both into
   one skill?
2. Should Phase 0's carry-forward merge also apply to first-run `--onboard`
   over a crashed/partial profile, or only when `.onboarding-complete` exists?
3. People re-routing: move pages on disk (folder is the index's source of
   truth today) or teach the index to trust frontmatter `location:` and stop
   moving files? Recommendation: move on disk now — smaller change, matches
   current reader behavior.
4. Does the transition capsule surface in `/dex-doctor` (a "pending/verified
   transition" probe) the way update capsules do?
