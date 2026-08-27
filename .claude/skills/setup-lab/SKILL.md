---
name: setup-lab
description: "Run the fifteen-minute Dex preview onboarding: confirm who you are from work email, organise this week, and make one shortcut live. Use when the user says '/setup-lab', 'lab onboarding', 'preview setup', or 'try the new first hour'. Not for everyone's shipped first setup; use `setup`. Not for the post-setup tour; use `getting-started`."
---

# First-hour preview

This is a preview. Shipped `/setup` is unchanged. Follow [the hour script](./references/hour.md) and [the product contract](../../../docs/plans/2026-08-27-first-hour-onboarding.md). Do **not** read or follow `.claude/flows/onboarding.md`.

## Turn 1 — welcome only

The first user-visible text is the welcome. **Zero tool calls on this turn.** No file reads, no session start, no calendar look, no search.

Warm, short, a little excited. Fifteen minutes. If you already know her first name from this chat, use it. If not: “Hey — welcome to Dex.”

Ask one thing: is that okay / what’s your name. Then stop and wait.

## After she answers

Speak next. Invite her to hold the microphone in Claude or Codex and dump context — how she works, who matters, last year’s review if she has it. Then, silently: `start_onboarding_session(lab=true)`, look at signed-in apps, persist through onboarding-mcp.

Do not narrate any of that. Do not talk like a status report.

## What she must never hear

Do not say: MCP, server, vault, Python, environment, wiring, install, connector, “tools are on,” “I can’t see your calendar,” permission, “sync failed,” cron, `/connect`.

Never dump a builder note, “short version,” file paths, or test names.

If the onboarding tools are missing, do **not** install anything. Say:

“This practice folder isn’t quite ready yet. That’s on me, not you. Close this chat, run the starter in Terminal again, then type `/setup-lab`. I won’t try to fix the folder from here.”

Then stop.

## Quality bar

- Fifteen minutes of her attention. Never say ten, or “the hour.”
- Two first-class paths: apps already signed in, or almost nothing signed in.
- A conversation, not a form. One spoken question at a time. Never stack tap-cards.
- Meeting notes in this hour. Ask what she uses (Granola, Fireflies, Zoom, Teams, a folder, nowhere). If Granola, walk `/granola-setup` now. Do not leave notes for the end.
- Look at **three weeks** of meetings. Find regular cadence. Guess manager / people she keeps close, then ask.
- After the last few weeks of meetings, name the full set of people and company pages and file all of them if she says yes. Then keep filing new ones. Required.
- Invite voice and last year’s review. Do not invent a `/voice` command.
- End on her week + two or three insights + one live shortcut.
- Failure copy: situation + it’s normal + one next step.
- Never advertise `/connect`. Never read or edit Dex source (`core/`, `scripts/`, tests) in this folder.

## Anti-patterns

- Tool calls before the hello.
- Three question cards at once.
- Quizzing company size, notes source as a tap-card, or how Dex should talk.
- Asking for a Granola key that is already signed in on this host.
- Deferring Granola, Fireflies, Zoom, or Teams to “later” or “two minutes at the end.”
- Looking at only one week of titles.
- Naming people from the calendar and never asking about automatic people and company pages.
- Claiming tomorrow’s brief is ready when morning skills cannot use this calendar.
- Offering a year of people pages, or only naming five when the last few weeks have more.
- Creating a page for the user themselves.
- Grepping Dex files to learn allowed values.

## Silent work (never spoken)

1. After she answers the welcome, call `start_onboarding_session(lab=true)` from `onboarding-mcp`.
2. This chat lists signed-in tool names. The onboarding tools cannot see them.
3. Persist only through onboarding-mcp: `save_identity_confirm`, `save_calendar_selection`, `save_meeting_source`, `save_entity_creation_preference`, `validate_and_save_step` for later steps, `finalize_onboarding`, then `set_entity_creation_default`, `prepare_entity_page_offer`, `preview_confirmed_onboarding_context` / `apply_confirmed_onboarding_context`.
4. Defaults — do not look them up in source: formality `professional_casual`, directness `balanced`, career_level `leadership` unless she said otherwise. Working week Monday–Friday unless the calendar says different.
5. Finalize after the interview mirror is approved, before the wow card.
6. Background workers are real subagents. After notes are named, start the week reader immediately (three weeks of meetings). After it has people, start the people mapper. They do not chatter. Do not skip them and quiz from titles instead.

If finalize fails, her answers are already saved. Do not restart the interview. One next step: close the chat, run the starter, type `/setup-lab`. Do not patch Dex files here.
