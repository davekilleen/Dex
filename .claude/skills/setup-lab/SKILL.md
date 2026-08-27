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

Then, silently: `start_onboarding_session(lab=true)`, look at signed-in apps, persist through onboarding-mcp.

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
- After welcome, at most **two** spoken beats before the mirror: what matters most, then who to keep. Infer the rest.
- End on her week + two or three insights + one live shortcut.
- Failure copy: situation + it’s normal + one next step.
- Never advertise `/connect`. Never read or edit Dex source (`core/`, `scripts/`, tests) in this folder.

## Anti-patterns

- Tool calls before the hello.
- Three question cards at once.
- Quizzing company size, notes source, or how Dex should talk.
- Asking for a Granola key that is already signed in on this host.
- Claiming tomorrow’s brief is ready when morning skills cannot use this calendar.
- Offering hundreds of people pages.
- Creating a page for the user themselves.
- Grepping Dex files to learn allowed values.

## Silent work (never spoken)

1. After she answers the welcome, call `start_onboarding_session(lab=true)` from `onboarding-mcp`.
2. This chat lists signed-in tool names. The onboarding tools cannot see them.
3. Persist only through onboarding-mcp: `save_identity_confirm`, `save_calendar_selection`, `save_meeting_source`, `validate_and_save_step` for later steps, `finalize_onboarding`, then `preview_confirmed_onboarding_context` / `apply_confirmed_onboarding_context`.
4. Defaults — do not look them up in source: formality `professional_casual`, directness `balanced`, career_level `leadership` unless she said otherwise. Working week Monday–Friday unless the calendar says different.
5. Finalize after the interview mirror is approved, before the wow card.
6. Background workers are subagents at named beats. They do not chatter.

If finalize fails, her answers are already saved. Do not restart the interview. One next step: close the chat, run the starter, type `/setup-lab`. Do not patch Dex files here.
