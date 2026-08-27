---
name: setup-lab
description: "Run the fifteen-minute Dex preview onboarding: confirm who you are from work email, organise this week, and make one shortcut live. Use when the user says '/setup-lab', 'lab onboarding', 'preview setup', or 'try the new first hour'. Not for everyone's shipped first setup; use `setup`. Not for the post-setup tour; use `getting-started`."
---

# First-hour preview

Follow [the product contract](../../../docs/plans/2026-08-27-first-hour-onboarding.md) and [the hour script](./references/hour.md). Do **not** read or follow `.claude/flows/onboarding.md`.

This is a preview. Shipped `/setup` is unchanged.

## Quality bar

- Fifteen minutes of her attention. Never say ten, or “the hour.”
- Two first-class paths: apps already signed in, or almost nothing signed in.
- End on her week + two or three insights + one live shortcut.
- Failure copy: situation + it’s normal + one next step.
- Never advertise `/connect`. Never edit Dex source in the vault.

## Anti-patterns

- Quizzing company size when the work email already implies it.
- Asking for a Granola key that is already signed in on this host.
- Claiming tomorrow’s brief is ready when morning skills cannot use this calendar.
- Offering hundreds of people pages.
- Creating a page for the user themselves.

## Contract

1. Call `start_onboarding_session(lab=true)` from `onboarding-mcp`.
2. The host agent (this chat) lists signed-in tools. The MCP cannot see them.
3. Persist only through onboarding-mcp: `save_identity_confirm`, `save_calendar_selection`, `save_meeting_source`, `validate_and_save_step` for later steps, `finalize_onboarding`, then `preview_confirmed_onboarding_context` / `apply_confirmed_onboarding_context`.
4. Finalize after the interview mirror is approved, before the wow card.
5. Background workers are subagents at named beats. They do not chatter.

If finalize crashes, say so in the three-beat pattern and stop. Do not patch Dex files in this vault.
