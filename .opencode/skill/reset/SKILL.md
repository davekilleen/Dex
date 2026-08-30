---
name: reset
description: "Restructure an existing Dex vault for a new role or changed preferences, without losing data. Use when the user says 'I changed jobs', 'restructure my Dex', 'my role is different now'. Not for first-time setup; use `setup`. Not for just toggling one feature; use `manage-capabilities`."
---

# Reset Dex for a new role

If `04-Projects/` does not exist, this vault was never set up. Use `setup` instead.

To turn a single room on or off, use `manage-capabilities` — it is a much smaller
change than a full reset and never touches the rest of the profile.

Otherwise:

1. Tell the user what a reset does and does not do, and get an explicit yes before
   calling anything:

   > "I'll walk you through the same questions as first-time setup and rewrite your
   > profile — role, company, pillars, communication style, working week and rooms.
   > Nothing you've written is deleted or moved: your notes, people, meetings and
   > projects all stay exactly where they are. Want to go ahead?"

   Stop here if they decline.

2. Call `start_onboarding_session(force_new=True)` from `onboarding-mcp`. The
   `force_new` flag is what makes this a reset rather than resuming a half-finished
   setup.
3. Read `.claude/flows/onboarding.md` and follow it as the single source of the
   conversation, exactly as `setup` does.
4. Before finalizing, call `finalize_onboarding(dry_run=True)` and show the user
   what it reports it would create. Then call `finalize_onboarding()`.

## What a reset actually changes

Say this honestly — do not promise more:

- **Rewritten:** `System/user-profile.yaml`, `System/pillars.yaml`, and the room
  set, through the onboarding MCP and `core/capabilities.py`.
- **Added if missing:** any folders and starter files the new role needs.
  Finalizing only creates what is not already there.
- **Left alone:** every existing folder and file. A reset does not rename, merge
  or move your content. If the new role means you want `Pipeline/` renamed to
  `Portfolio/`, that is a manual choice the user makes afterwards — offer to help,
  do not do it silently as part of the reset.

## Rules

This file deliberately contains no question script, no role list and no company-size
list, so reset cannot fork away from setup. The roles, the area→role picker and every
other question live in `.claude/flows/onboarding.md`; change them only there.

Never create folders, move files, or edit `CLAUDE.md` or `System/user-profile.yaml`
by hand in this skill. `core/provision.cjs`, `core.lifecycle.service` and
`core/capabilities.py` own all vault mutation, and the onboarding MCP owns all
profile writes and their validation.

---

## Track Usage (Silent)

Update `System/usage_log.md` to mark vault reset as used.

**Analytics (Silent):**

Call `track_event` with event_name `vault_reset` and properties:
- (no properties)

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".
