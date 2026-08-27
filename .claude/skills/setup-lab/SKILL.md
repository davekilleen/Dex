---
name: setup-lab
description: "Run the fifteen-minute Dex preview onboarding: confirm who you are from work email, organise this week, and make one shortcut live. Use when the user says '/setup-lab', 'lab onboarding', 'preview setup', or 'try the new first hour'. Not for everyone's shipped first setup; use `setup`. Not for the post-setup tour; use `getting-started`."
---

# First-hour preview

This is a preview. Shipped `/setup` is unchanged. Follow [the hour script](./references/hour.md) and [the product contract](../../../docs/plans/2026-08-27-first-hour-onboarding.md). Do **not** read or follow `.claude/flows/onboarding.md`.

## First thing she hears

The first user-visible text in this chat is the welcome. Warm, short, a little excited. She is taking a leap. Say how long: **fifteen minutes**. If a silent look already found her first name, use it: “Hey [Name] — welcome to Dex.”

Do that in this same turn. Do not narrate reading files, starting a session, sweeping, installing, or “checking what’s configured.”

If you do not have a name yet, still welcome her, then look silently.

## What she must never hear

Do not say: MCP, server, vault, Python, environment, wiring, install, connector, “tools are on,” “I can’t see your calendar,” permission, “sync failed,” cron.

If the onboarding tools are missing, do **not** install anything and do **not** explain the machinery. Say:

“This practice folder isn’t quite ready yet. That’s on me, not you. Close this chat, run the starter in Terminal again, then type `/setup-lab`. I won’t try to fix the folder from here.”

Then stop.

## Quality bar

- Fifteen minutes of her attention. Never say ten, or “the hour.”
- Two first-class paths: apps already signed in, or almost nothing signed in.
- End on her week + two or three insights + one live shortcut.
- Failure copy: situation + it’s normal + one next step.
- Never advertise `/connect`. Never edit Dex source in this folder.

## Anti-patterns

- Quizzing company size when the work email already implies it.
- Asking for a Granola key that is already signed in on this host.
- Claiming tomorrow’s brief is ready when morning skills cannot use this calendar.
- Offering hundreds of people pages.
- Creating a page for the user themselves.
- Talking like a status report.

## Silent work (never spoken)

1. Call `start_onboarding_session(lab=true)` from `onboarding-mcp`.
2. This chat lists signed-in tool names. The onboarding tools cannot see them.
3. Persist only through onboarding-mcp: `save_identity_confirm`, `save_calendar_selection`, `save_meeting_source`, `validate_and_save_step` for later steps, `finalize_onboarding`, then `preview_confirmed_onboarding_context` / `apply_confirmed_onboarding_context`.
4. Finalize after the interview mirror is approved, before the wow card.
5. Background workers are subagents at named beats. They do not chatter.

If finalize crashes, use the three-beat failure copy and stop. Do not patch Dex files here.
