---
name: setup-v2
description: "Meet Dex as your new Chief of Staff and get a working Dex from your week, not a questionnaire. Use when the user says `/setup-v2`, `/setup-v2 preview`, `try the new first hour`, or `preview setup`. Not for everyone's shipped first setup; use `setup`. Not for the post-setup tour; use `getting-started`. Not for a mid-life role change; use `reset`."
---

# Meet Dex (/setup-v2)

This is the preview first hour. Shipped `/setup` is unchanged and still follows `core/onboarding/FLOW.md`.

How to try it: type `/setup-v2` in a fresh Dex folder. There is no separate starter.

Existing Dex, no writes: type `/setup-v2 preview`. Same screens. Nothing is saved. At the end there is a discard step. If `/setup-v2` is run in a vault that is already set up, offer preview as the first choice.

## Quality bar

A good run leaves them thinking: Dex already understands an extraordinary amount about my working world, and I barely had to configure anything.

At the 5–10 minute stop they have been greeted by name, confirmed who they are, have a workspace, and can see this week (or the week they described). They may stop there. Longer enrichment is an offer, not a gate.

## Anti-patterns

- Do not run the shipped questionnaire. Do not read `core/onboarding/FLOW.md` or `.claude/flows/onboarding.md` for this command.
- Do not fill dead air ("one moment", "nearly there", "still reading").
- Do not silently persist an inference. Evidence vs guess is said out loud. Writes go through confirmation, then onboarding-mcp — except in preview mode, where the server redirects every write into a temp sandbox and refuses anything outside it.
- Do not create people or company pages unless they said yes to the explicit offer.
- Do not invent a door Dex does not have. Do not say `/connect`.
- Do not claim a morning brief is ready unless Calendar.app was stored.
- Do not auto-create a skill. Shelf-first only.
- Do not treat calendar, notes, source doc, domain, or integrations as dead ends.
- Do not name models or vendors. Do not steal a mid-progress shipped `/setup` session. Do not wipe a finished vault.
- Do not write to the real vault, settings, connections, launch agents, background sync, hooks, or home config during preview. `preview_connection_step` and `preview_sync_install` are no-ops. End with `discard_preview_session`.

## First turn

The first visible text is a hello. **Zero tools on that turn.** One question, then wait. Background helper messages are never their answer.

Follow [hour.md](./references/hour.md) as the spoken journey.

## Tools (reuse onboarding-mcp — no second provisioner)

After they give their name:

1. If they typed `/setup-v2 preview`: `start_onboarding_session(preview=true)` (implies v2). Same journey, temp sandbox only.
2. Otherwise `start_onboarding_session(v2=true)` — resume a v2 session; do not attach if the tool returns `blocked: shipped_setup_in_progress`. `force_new` only if they asked to start over.
3. If the tool returns `offer_preview` (vault already set up): offer preview as the **first** choice. If they say yes, `start_onboarding_session(preview=true)`. Also mention `/getting-started` or `/reset`. Do not wipe.
4. Address calendar (select or `save_calendar_selection(skipped=true)`). Not a gate.
5. Quiet harness: `inspect_harnesses` then `save_harness_selection(..., confirmed=true)` after they have seen the preview in passing. Speak only if nothing could be confirmed. Required before finalize. No extra spoken beat.
6. Confirm identity, then `validate_and_save_step` for name, role, company size, email domain, proposed pillars, communication defaults, working week. Rooms stay on unless they volunteer a skip.
7. Optional source doc: invite, then `save_source_doc_note(status="supplied"|"skipped")`. Never copy the document into the profile.
8. Notes: ask once. `save_meeting_source(primary=...)`. None / skip / unknown door → `none`. Continue.
9. Mirror, then `finalize_onboarding`. Preview/apply working context with the real calendar source — Apple or none. Never persist Google. In preview mode this writes only the temp sandbox.
10. `run_first_week_analysis(v2=true)`. If the calendar is not Calendar.app, pass host-fetched `events`. Do not claim those events were stored.
11. Clean stop. If they continue: meeting intelligence, then `prepare_entity_page_offer(v2_window=true)` and `respond_to_entity_page_offer(..., v2_window=true)`. One motivated integration at most — in preview call `preview_connection_step` and `preview_sync_install` (no-ops). One shelf skill (`/daily-plan` or `/getting-started`). Do not create a skill.
12. If this sitting was preview: a clear discard. `discard_preview_session`. Say plainly nothing was saved. Then the optional copy-only feedback in [hour.md](./references/hour.md). Do not write or send the answers.

If onboarding tools are missing: one honest line, stop. Do not install from the chat.

## Degradation

| Situation | What to do |
|---|---|
| Calendar missing / skip / non-Mac | Skip. Ask identity. Describe the week they told you. No automatic morning brief. |
| Host Google calendar readable | Show it as evidence in this sitting. Say it is not stored. Offer `/google-workspace-setup` once, later. |
| No notes / no recorder | Record `none`. Continue. |
| No source doc | Warm continue. Do not ask again. |
| Identity wrong | Save the correction. Do not guess again. |
| No company domain | Explicit opt-out. Continue. |
| Finished vault | Preview is the first choice. Then `/getting-started` or `/reset`. Do not wipe. Rehearsal that writes needs a fresh folder. |
| Mid shipped `/setup` | Leave it. Do not attach. |
| They typed `/setup` | Shipped questionnaire. No redirect. |
| They typed `/setup-v2 preview` | Full first hour, no writes, discard at the end. |
| Preview exit early | Still `discard_preview_session`. Leftover temp folders are wiped on the next start. |
