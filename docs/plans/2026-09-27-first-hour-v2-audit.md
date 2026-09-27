# First Hour v2 — audit

**Status:** Phase 1 audit, updated for the Phase 2 brief.  
**Date:** 2026-09-27  
**Audience:** founder review and Phase 2 implementers  
**Command:** `/setup-v2`. Shipped `/setup` stays the default.

This audit is grounded in **current `main`** and in **open draft PR #621**. It does not merge, rebase, or cherry-pick that branch.

---

## Sources used

| Source | Identity | Role |
|---|---|---|
| Current `main` (branch base) | `836c01b401dead214460d1db971b07a1a3b76067` | Shipped first setup. Two commits after the first evidence pass (`aab02b19`): #751 Todoist titles, #752 Windows CI. Neither touches onboarding. |
| PR #621 head | `20c9dc526dfc6b2cc37c7d295eefb754739ddaa2` on `cursor/first-hour-onboarding-spec-b76d` | Preview prototype + product contract |
| Closed #617 | parked 2026-08-27 | Earlier draft of the same preview; not a second design |
| Shipped flow | `core/onboarding/FLOW.md` (947 lines) | Single source of truth for `/setup` |
| Compatibility copy | `.claude/flows/onboarding.md` | Byte-identical to `FLOW.md` (`core/tests/test_onboarding_flow_portability.py`) |
| Shipped skill | `.claude/skills/setup/SKILL.md` | Thin wrapper: start session, then follow `FLOW.md` |

**Brief.** Pasted in full for Phase 2 (the upload and `dex-product-gtm-lab#720` were not readable in Phase 1). Product intent: meet your Chief of Staff; progressive 2 / 5–10 / 15–30 minute value; infer–propose–confirm; no dead ends; finish with something real. Required branches: calendar unavailable, no meeting notes, no source doc, shortest setup, longer enrichment, returning/resume.

---

## 1. What `main` already does

Shipped first setup is a **validated questionnaire**, not a conversation over the last few weeks of meetings. The door is `/setup`. The conversation lives only in `core/onboarding/FLOW.md`. `.claude/skills/setup/SKILL.md` (`8decb8ed`) refuses to carry a second script.

### 1.1 The hour a new person actually hears

Order on `main` today (`FLOW.md`):

1. **Harness pick** — `inspect_harnesses` / `save_harness_selection`. Multiple hosts allowed. This landed after #621 branched (`8decb8ed` and later onboarding-server work).
2. **Calendar First** — Apple Calendar.app on macOS, or an explicit skip. Non-macOS skips with `save_calendar_selection(skipped=true)` and never calls Calendar.app.
3. **Optional identity confirm** from a calendar name that looks like an email. Name and domain are still saved through the later numbered steps, in order.
4. **Optional meeting-source offer** via `node core/integrations/integration-concierge.cjs`. Allowed primaries in the flow and profile template: `granola / zoom / teams / exported-folder / wispr / none` (`2c575f79`).
5. **Steps 1–7** in order: name, role area + role, company + size, **email domain (mandatory)**, pillars, communication + optional Obsidian, working week.
6. **Step 8 rooms** — not asked. Career, Companies, and Quarter Goals turn on by default.
7. **`finalize_onboarding()`** — the only vault write door. Creates the PARA folders, profile, pillars, MCP config.
8. **Working-context review** — `role_focus`, current work, week success, quarter outcome, up to **five** key people. Then `preview_confirmed_onboarding_context` / `apply_confirmed_onboarding_context`.
9. **Automatic first-week reveal** — `run_first_week_analysis()` with **no host-event argument**. Reads Calendar.app for **this week**.
10. **Qualified page offer** — `prepare_entity_page_offer` after finalize. Same threshold as the background entity engine. **Hard cap: 5** (`core/mcp/scripts/onboarding_entity_offer.cjs` `MAX_ONBOARDING_SUGGESTIONS = 5`; MCP `maxItems: 5`).
11. **Integration catalogue** — Google Workspace, Teams, Todoist, Things, Trello, Zoom, Atlassian, plus optional journaling, Granola, external MCPs, background learning.
12. **Analytics notice** — preference saved; nothing is sent without a relay (`c519882b` / #732).
13. **Feedback + Doctor** — said once, no extra step.
14. **Optional nudge calendar** — `generate_nudge_calendar()` (the old month-style `.ics`, not two-week free cue cards).
15. **Optional `/getting-started`.**

Resume is the default: `start_onboarding_session()` continues yesterday’s answers unless the person starts fresh.

### 1.2 What the onboarding MCP can actually persist

`core/mcp/onboarding_server.py` on `main` (`ae78d175`, DEX-171) exposes these tools (inventory: `docs/architecture/INVENTORY.md`):

`start_onboarding_session`, `inspect_harnesses`, `save_harness_selection`, `validate_and_save_step`, `save_calendar_selection`, `preview_confirmed_onboarding_context`, `apply_confirmed_onboarding_context`, `get_onboarding_status`, `verify_dependencies`, `run_first_week_analysis`, `generate_nudge_calendar`, `prepare_entity_page_offer`, `respond_to_entity_page_offer`, `set_entity_creation_default`, `finalize_onboarding`, `verify_transition`, plus QA helpers.

**Not on `main`:** `save_identity_confirm`, `save_meeting_source`, a `lab` flag, `force_new` on start, `events=` on first-week analysis, or `System/.onboarding-lab`.

Calendar persist is still **Apple or none**. The tool text says so. The lifecycle layer enforces it:

```688:689:core/lifecycle/service.py
    if provider != "apple" or set(calendar_source) != {"provider", "work_calendar"}:
        raise PlanRejected("calendar source must be Apple Calendar or no calendar")
```

That reject is from `843cfb93` (2026-07-29) and is still live. `test_confirmed_onboarding_context_refuses_google_calendar` will fail if Phase 2 widens this without updating the test on purpose.

Morning skills **can** already read a Google calendar **if** the profile already says `calendar.provider: google` (`.claude/skills/daily-plan/SKILL.md` and `AGENT_INSTRUCTIONS.md`; gated by `core/tests/test_calendar_provider_routing_instruction_contract.py`). First setup cannot write that shape. That is the practice-hour hole #621 named: chat can see a host calendar; the persist path cannot store it.

### 1.3 What Dex can honestly do today (no invented doors)

These setup skills already exist on `main` and may be walked **in hour one** when the person names that source:

| Need | Honest door on `main` | Not a door |
|---|---|---|
| Apple Calendar | Calendar First + `/calendar-setup` | Host calendar names are not Calendar.app |
| Google Calendar / mail | `/google-workspace-setup` | Onboarding persist (`apple` / `none` only) |
| Granola notes | `/granola-setup` (official API key, Business/Enterprise) | “Already signed in on the host” is not a stored Dex key |
| Zoom | `/zoom-setup` | — |
| Teams | `/ms-teams-setup` | — |
| Wispr | `/wispr-setup` | — |
| A folder of notes | exported-folder + `notes_folder` | A recorder Dex has no reader for |
| Fireflies / Gong / Slack / Salesforce content | none in hour one | Do not invent a connection |

`/connect` is **held** (draft PR #231, security no-go not lifted — `AGENTS.md`). Shipped `FLOW.md` still tells the agent to offer `/connect granola` and a catalogue of `/connect` tools. That is a shipped honesty problem. First Hour v2 must not copy it.

### 1.4 Vault writes already go through one door

Finalize and working-context apply already use `core/lifecycle/service.py` → transaction core → portable ownership (`onboarding-provision`, `onboarding-context` in `core/portable_contract.py`). Classified runtime files today:

- `System/.onboarding-session.json`
- `System/.onboarding-complete`
- `System/.onboarding/`

There is no `.onboarding-lab` class on `main`. Adding one later is a portable-contract change (CI: `scripts/check-portable-contract.sh`).

---

## 2. What is valuable in #621

#621 is a **preview**, not a replacement. 15 commits, 48 files. It should be read, not merged.

Valuable product intent (from `docs/plans/2026-08-27-first-hour-onboarding.md` @ `e7c93831`…`20c9dc52`, and `.claude/skills/setup-lab/references/hour.md`):

1. **A conversation, not a form.** One spoken question. Wait. No stacked tap-cards.
2. **Two first-class hours.** Apps already signed in, or almost nothing signed in. Empty-apps is designed, not a shrug.
3. **Fifteen minutes of attention.** The close is *her week*, not “workspace created.”
4. **Three hour-one connects only:** email, calendar, meeting notes. Slack / Salesforce / Gong are named, not opened.
5. **Meeting notes in this sitting.** Ask what she uses. Walk the real door now. Granola has three states (app installed / signed in on the host / stored Dex key). Do not collapse them.
6. **You read the meetings.** This week + last three + next three. Do not spawn a meetings helper and wait for notes that never come back.
7. **Cadence, then ask.** Regular 1:1s are a guess about who matters, not a stated fact.
8. **File the last few weeks, not five and not a year.** #621 raised the lab offer window; shipped `/setup` still caps at five.
9. **Invite voice + a real review** (annual, ladder, job spec, or a public-profile extract). No invented `/voice` command.
10. **Next working morning = weekday + date**, after the calendar is read. Skip out-of-office. Never a hardcoded Tuesday or a bare Monday (`9969337e`, `core/utils/working_week.py` on that branch).
11. **Hello first. Zero tools on turn one.** The practice-hour failure mode was narrating wiring (`52ed64cd`, `bd21d8e9`).
12. **A preview that can start clean.** #621 used `force_new` so a new sitting did not resume yesterday (`bf69d516`). The Phase 2 brief requires a **returning / resume** branch instead: resume an in-progress v2 session; start fresh only if they ask.
13. **Reuse the onboarding MCP.** Widen it. Do not invent a second provisioner (`c83c035f`).
14. **Honest failure.** If helpers are missing, close the chat and run the starter again. Do not edit Dex source in the vault (`bd21d8e9`).
15. **Never advertise `/connect`.** Point Granola at `/granola-setup` (`bd21d8e9`).
16. **Optional two-week free cue cards**, skippable, instead of the old nudge `.ics`.
17. **One helping-hand breath** at the end (guide, analytics truth, feedback, Doctor).

Valuable implementation patterns to **re-derive on current `main`**, not copy from the stale branch:

| Pattern | #621 files | Why keep the idea |
|---|---|---|
| Side skill + anti-trigger to `/setup` and `/getting-started` | `.claude/skills/setup-lab/SKILL.md`, `evals/trigger-cases.yaml` | Router must not steal shipped first setup |
| Hour script in `references/` | `setup-lab/references/hour.md` | Keep the skill thin |
| Session-only meeting source until finalize | `save_meeting_source` | Avoid writing `user-profile.yaml` before the vault exists |
| Host-fetched events into first-week analysis | `run_first_week_analysis(events=[...])` | Python cannot call host calendar tools |
| Lab/preview marker | `System/.onboarding-lab` | Beta signal stays separable |
| Tests that protect shipped order | `test_shipped_session_still_requires_calendar_before_name` | The shared MCP must not quietly change `/setup` |

---

## 3. What #621 is missing against current `main`

#621 branched from late-August `main`. Current `main` has moved. A merge or cherry-pick would fight a month of onboarding and harness work.

Missing or stale relative to `aab02b19`:

1. **Harness selection.** Shipped `/setup` now starts with `inspect_harnesses` / `save_harness_selection`. Finalize refuses an unconfirmed harness (`test_new_portable_session_cannot_finalize_before_harness_confirmation`). #621 never saw this. v2 must either do a short harness confirm or reuse the existing tools without rewriting `FLOW.md`.
2. **Honest analytics.** `FLOW.md` @ `c519882b` / #732: preference saved, nothing sent without a relay. #621’s helping-hand still says analytics “is on” and “records ‘ran a daily plan’.” That copy is now wrong.
3. **Wispr.** Named in the shipped flow and profile template (`2c575f79`). #621’s `save_meeting_source` allow-list already includes `wispr`, but the hour script never walks `/wispr-setup`.
4. **DEX-171 Mac finalize** (`ae78d175`). #621 spent time on empty builder receipts and practice-folder Python. Some of that pain is already fixed on `main`.
5. **Reset / change-job / transition capsules.** `verify_transition`, `restore_transition_capsule`, carry-forward. #621 does not know these tools exist. v2 must not collide with `/reset`.
6. **Google routing in morning skills.** Already on `main` as instruction-contract. #621 also patched `daily-plan` and `meeting-prep`. Re-patching those shipped skills is how `/setup` behaviour quietly changes.
7. **Entity engine + 28-day offer window.** `get_calendar_events_for_entity_offer(days_back=28)` is already on `main`. The shipped **cap of 5** is the gap, not the lookback.
8. **Portable hosts.** Written host paths, extra host limits, and plugin packaging have landed on `main`. #621’s practice starter assumes one chat host and a full Dex copy via `rsync`.
9. **Feature-status honesty** on other MCPs. Onboarding still lacks `feature_status` (`DEX-CORE-MAP.md`). Do not pretend the onboarding server reports health the way Calendar does.

---

## 4. What to discard from #621

Do **not** bring these across.

| Discard | Why |
|---|---|
| Merge / rebase / cherry-pick of `cursor/first-hour-onboarding-spec-b76d` | Explicit Phase 1 rule. Branch is a month stale. |
| Name `/setup-lab` | Preview name from August. This run is First Hour v2. Proposed name is `/setup-v2`. |
| Edits to `core/onboarding/FLOW.md` or `.claude/flows/onboarding.md` | Shipped SSoT. `test_portable_flow_and_claude_bridge_are_byte_identical` and `test_setup_skill_points_at_portable_flow` must stay green. |
| The one-line change to `.claude/skills/setup/SKILL.md` | Any edit risks the portability test and shipped routing. |
| Patches to shipped `/daily-plan`, `/meeting-prep`, `/getting-started`, `/feedback` | Those are everyone’s skills. Google routing already exists. Getting-started must not start advertising v2. |
| Hand-edits to `docs/architecture/INVENTORY.md`, `core/lens-catalog/registry.json`, `packages/dex-contracts/dist/*` | Generated. Change the source, regenerate. |
| `CHANGELOG.md` entry as if this shipped | Phase 1 is docs. No release. |
| `scripts/lab-onboarding.sh` as written | Full-tree `rsync` of the Dex checkout into `~/Dex-lab-onboarding`, then `provision.cjs`. That is a developer practice folder, not a user first hour. It also edits `CLAUDE.md` user extensions. |
| Session-start hook that points a vault at `/setup-lab` | Hijacks first-run away from shipped `/setup`. |
| Stop-hook heartbeat (`lab-onboarding-nudge.cjs`) wired in `.claude/settings.json` | Touches the shared hook list. Easy to misfire on real `/setup`. |
| Company-research “helper” that invents marketplace copy | Public facts only if a real lookup ran. Never invent competitors. |
| Creating a skill in hour one unless it can be **made and run** in that sitting | #621 allows create-from-gleanings. Easy to over-promise. Shelf-first is enough for v2. |
| Cue-card calendar writes before a real calendar persist exists | Do not put `[Dex]` events on a calendar we cannot name. |
| Vendor/model names in skill copy | Hard rule for this run. #621 names host products in user-facing lines. Rewrite as “this chat” / “the host.” |
| Always-fresh `force_new` as the only start | The brief requires resume. `force_new` only when they ask to start over. |
| Practice-hour copy that names a real person or company | PII gate. Use generic names in transcripts and tests. |
| `/connect` even as a “don’t say this” list that still leaks into FLOW-style catalogues | v2 never offers that door. |
| Claiming “tomorrow’s brief is ready” | Still false unless the same calendar persist morning skills can read. |
| Raising shipped entity-offer `maxItems` as a side effect of lab | That changes `/setup`. Lab/v2 limits must stay behind a v2 session flag. |
| Advertising Slack, Salesforce, or Gong as hour-one readers | Named only. No content until a later yes. |

---

## 5. Risks to shipped `/setup`

The danger is not the new skill. The danger is **shared machinery**.

1. **Widening `save_calendar_selection` / lifecycle persist to accept Google.**  
   Today `test_confirmed_onboarding_context_refuses_google_calendar` and the tool schema say Google is unsupported *here*. A shared widening changes `/setup` even if `FLOW.md` is untouched, because `/setup` uses the same tools.

2. **Relaxing “calendar before name.”**  
   `test_rejects_step_1_until_calendar_is_addressed` and `test_finalize_rejects_session_without_calendar_addressed` lock shipped order. #621 gated the exception on `session["lab"]`. v2 must keep that exception **off** for a normal session.

3. **`force_new` as the default for `start_onboarding_session`.**  
   Shipped `/setup` resumes. If the default flips, interrupted real setups start over.

4. **Entity-offer cap and lookback.**  
   Changing `MAX_ONBOARDING_SUGGESTIONS` or `respond_to_entity_page_offer` `maxItems` changes the shipped offer. v2 “file the last few weeks” needs its own path or a session flag.

5. **Writing `meeting_sources` into the profile before finalize.**  
   Shipped `FLOW.md` tells the agent to write `System/user-profile.yaml` during the pre-step offer. That is already a bit loose. A new tool should stay on the **session** until finalize, and must not teach `/setup` a second write path.

6. **Hook and first-run changes.**  
   Session-start and Stop hooks are global. A v2 nudge that fires in a normal vault will talk over shipped setup.

7. **Generated inventory / lens catalog / contracts.**  
   #621 edited generated files in the same PR as the skill. That is how a preview becomes a catalog change for everyone.

8. **`FLOW.md` drift.**  
   If Phase 2 “just adds a sentence” to the shipped flow, the compatibility copy and the portability tests break, or worse, they stay green while `/setup` and the bridge diverge.

9. **Honesty regressions.**  
   Copying #621’s “analytics is on” or FLOW’s `/connect` catalogue into v2 would ship a lie. Copying FLOW’s `/connect` into v2 is also a held-door leak.

**Isolation rule for Phase 2:** new skill + new tests + optional v2-only MCP arguments that default to today’s shipped behaviour. No edits to `FLOW.md`, `.claude/flows/onboarding.md`, or `.claude/skills/setup/SKILL.md` unless a later review explicitly asks for them.

---

## 6. Contracts and tests that must stay green

Phase 2 may add tests. It must not turn these red unless a named contract is intentionally changed and the test is updated in the same change.

### 6.1 Hard locks on shipped `/setup`

| Test | What it protects |
|---|---|
| `core/tests/test_onboarding_flow_portability.py::test_portable_flow_and_claude_bridge_are_byte_identical` | `FLOW.md` ↔ `.claude/flows/onboarding.md` |
| `test_setup_skill_points_at_portable_flow` | `/setup` stays a pointer, not a second script |
| `core/tests/test_onboarding_context_lifecycle.py::test_confirmed_onboarding_context_refuses_google_calendar` | Persist shape is Apple or none |
| `test_confirmed_onboarding_context_is_previewed_then_transactionally_applied` | Preview → token → receipt |
| `test_execute_refuses_missing_or_wrong_approval_token` and siblings | No silent profile write |
| `core/tests/test_onboarding_calendar.py` (all) | Calendar selection is transient; skip works; finalize strips unapproved calendar |
| `core/mcp/tests/test_onboarding_server.py` calendar-before-name + finalize-without-calendar | Shipped order |
| `test_new_portable_session_cannot_finalize_before_harness_confirmation` | Harness receipt |
| `test_onboarding_flow_requires_context_preview_and_explicit_approval` | Working context |
| `test_rejects_out_of_order_step_with_next_expected_step` | Step order |
| `test_normalizes_and_saves_email_domains` / `test_explicit_no_company_domain_completes_step_and_allows_finalize` | Step 4 |
| `test_numbered_role_contract_is_unchanged` / `test_custom_role_contract_is_unchanged` | Role list |
| `core/mcp/tests/test_onboarding_entity_offer.py` | Qualified offer, cap, yes/no/never |
| `core/tests/test_meeting_source_instruction_contract.py` | Meeting-source primaries stay aligned across FLOW, template, validators |
| `core/tests/test_calendar_provider_routing_instruction_contract.py` | Morning skills still read `calendar.provider` |
| `core/tests/test_nudge_calendar.py` | Shipped nudge path still works for `/setup` |
| `core/tests/test_harness_onboarding_receipt.py` | Existing-vault harness repair does not restart onboarding |
| `core/tests/test_portable_contract.py` onboarding operations | Only declared paths are writable |
| `core/tests/test_lifecycle_service_contract.py` | Lifecycle signatures |

### 6.2 Repo-wide gates (CI)

From `.github/workflows/ci.yml`:

- `npm run test:hooks`
- `npm run test:scripts`
- `npm run test:integrations`
- `bash scripts/check-pii.sh` — no real identities in committed copy
- `python scripts/check-instructed-tools.py`
- `bash scripts/check-portable-contract.sh`
- `npm run check:connections-contract`
- `pytest core/tests/ core/mcp/tests/ core/migrations/tests/ -m "not fuzz"`
- Portable plugin runtime verify

A new top-level path or a new `System/.onboarding-*` marker needs a `core/portable_contract.py` class **and** a regenerated inventory. Do not hand-edit `docs/architecture/INVENTORY.md`.

### 6.3 Tests #621 added that are **not** on `main`

Useful as a checklist for Phase 2, to be rewritten against current `main` and `/setup-v2`:

- `core/tests/test_lab_onboarding.py` — starter + welcome-first
- `core/mcp/tests/test_onboarding_lab.py` — fresh session, name-before-calendar **only in lab**, shipped order unchanged, identity confirm, Google returned-not-stored, meeting source on session, host events, out-of-office Monday, honest missing-helper copy
- `.claude/hooks/tests/lab-onboarding-nudge.test.cjs` — **only if** Phase 2 decides a hook is still worth the shared-hook risk (default: no)

---

## 7. Recommended build shape (Phase 2)

1. New first-party skill `.claude/skills/setup-v2/` with `evals/trigger-cases.yaml` and a `references/` hour script that follows the **progressive 2 / 5–10 / 15–30** journey. Clean stop at 5–10 minutes.
2. Anti-triggers: not `/setup`, not `/getting-started`, not `/reset`, not `/change-job`.
3. Reuse `onboarding-mcp` as the only vault write door. No second provisioner. No practice starter.
4. Any MCP widening is **opt-in** (`v2=true` / session flag) and covered by a test that shipped sessions still behave as today. Shared defaults, including the five-person entity cap, stay unchanged.
5. Do not touch `FLOW.md`, the `.claude/flows` copy, `.claude/skills/setup/SKILL.md`, or hooks.
6. Do not claim a morning brief, a recorder, or a page set Dex cannot actually produce from tools on `main`.
7. Do not widen Google persist. Host Google may be *shown* in chat; it is not stored through `preview_confirmed_onboarding_context`.
8. Harness confirm is early, quiet, and required before finalize — not a spoken extra beat.
9. Source-doc invite is required in the script; “not now” is a first-class path. Notes are never a gate.

---

## 8. Settled decisions (no longer open)

1. **Command.** `/setup-v2`.
2. **Google persist.** Stay on Apple or none. `test_confirmed_onboarding_context_refuses_google_calendar` stays green.
3. **Harness.** Confirm early and quietly with existing tools, before finalize.
4. **Entity window.** v2-only parameter or path may offer the last few weeks. Shipped `/setup` stays at five. The existing cap test stays green.
5. **Starter.** None. Type `/setup-v2` in a fresh folder.
6. **Skills in hour one.** Shelf-first only. Do not auto-create a skill.
7. **Notes.** Not a gate.
8. **Source doc.** Invite with a great “I don’t have one / not now” path.
9. **Shape.** Progressive value, not an hour-long wizard. Happy path = shortest setup to the 5–10 minute stop.
