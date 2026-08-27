---
name: setup
description: "Run first-time Dex onboarding: build the vault structure, capture the user profile and configure MCPs. Use when `System/.onboarding-complete` is absent or the user says 'set up Dex', 'start onboarding'. Not for the post-onboarding tour; use `getting-started`. Not for a mid-life role change; use `reset`. Not for the preview first hour; use `setup-lab`."
---

# Set Up Dex

If `System/.onboarding-complete` already exists, setup is complete. Use `getting-started` for the
post-onboarding tour or `reset` for a role or preference change.

Otherwise:

1. Call `start_onboarding_session()` from `onboarding-mcp` to initialize or resume
   the session.
2. Read `.claude/flows/onboarding.md` and follow it as the single source of the
   onboarding conversation.

This file deliberately contains no question script, so onboarding cannot fork.
Change onboarding only in `.claude/flows/onboarding.md` and `onboarding-mcp`,
never here.
