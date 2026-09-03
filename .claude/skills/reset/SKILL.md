---
name: reset
description: "Re-run the setup questions over an existing Dex vault when preferences or setup answers changed, without losing data. Use when the user says 'restructure my Dex', 'redo my setup', 'my pillars are wrong now'. Not for a job or role change; use `change-job` — it runs this same reset plus the people, archive and task passes. Not for first-time setup; use `setup`. Not for just toggling one feature; use `manage-capabilities`."
---

# Reset Dex for changed answers

If `04-Projects/` does not exist, this vault was never set up. Use `setup` instead.

If the user actually changed jobs or roles — new employer, new email domain, an
old identity to archive — use `change-job` instead: it runs this same reset and
then guides the passes a reset alone never touches (re-sorting people for the
new domain, archiving old-role goals, priorities and projects, re-pointing open
tasks). A reset by itself is the right lever only for changed preferences or
answers within the same working life.

To turn a single room on or off, use `manage-capabilities` — it is a much smaller
change than a full reset and never touches the rest of the profile.

Otherwise:

1. Tell the user what a reset does and does not do, and get an explicit yes before
   calling anything:

   > "I'll walk you through the same questions as first-time setup and rewrite your
   > profile — role, company, pillars, communication style, working week and rooms.
   > Every setting you don't re-answer carries forward unchanged, and nothing
   > you've written is deleted or moved: your notes, people, meetings and
   > projects all stay exactly where they are. Want to go ahead?"

   Stop here if they decline.

2. Call `start_onboarding_session(force_new=True)` from `onboarding-mcp`. The
   `force_new` flag is what makes this a reset rather than resuming a half-finished
   setup. Know what it re-arms: the fresh session clears the calendar answer and
   the harness confirmation, so the flow's calendar step and harness-selection
   confirmation must both be replayed — `finalize_onboarding` refuses to run
   until each has been addressed again. Do not skip past them expecting the old
   answers to still count.
3. Read `.claude/flows/onboarding.md` and follow it as the single source of the
   conversation, exactly as `setup` does.
4. Before finalizing, call `finalize_onboarding(dry_run=True)` and show the user
   what it reports it would create, plus the `profile_changes` list — every
   profile setting that will change, old value → new value. Settings not in that
   list carry forward. Tell the user that on a vault that already completed
   onboarding, finalizing first takes a snapshot of the current profile, pillars
   and room choices — before anything is rewritten — so the reset can be checked
   afterwards and undone if it went wrong. Then call `finalize_onboarding()`.
5. After finalizing, show the user the `transition_verification` summary from the
   finalize response — it reads "Changed (you chose): … Carried forward: N
   settings. Lost: none." Read it before relaying it: if it reports anything
   lost or changed outside their answers, say so plainly instead of declaring
   success, and offer `restore_transition_capsule` — preview first (it defaults
   to a dry run), then rerun it with `dry_run=false` if they want the two
   settings files put back exactly as they were. `verify_transition` re-runs the
   same check anytime against the snapshot named in the response.

## What a reset actually changes

Say this honestly — do not promise more:

- **Rewritten:** `System/user-profile.yaml`, `System/pillars.yaml`, and the room
  set, through the onboarding MCP and `core/capabilities.py`.
- **Carried forward:** on a vault that completed onboarding, every profile
  setting the user does not re-answer keeps its current value — calendar
  connection, work email, working context, journaling, meeting sources,
  timezone, quarterly planning, entity-creation mode, analytics identity, and
  the rest. Rooms the user disabled stay disabled unless they are re-answered.
  In `System/pillars.yaml`, `priority_limits` survives, and a pillar kept under
  the same name keeps its keywords and description. Only a vault that never
  finished onboarding is rebuilt from the answers alone.
- **Added if missing:** any folders and starter files the new role needs.
  Finalizing only creates what is not already there.
- **Left alone:** every existing folder and file. A reset does not rename, merge
  or move your content. If the new role means you want `Pipeline/` renamed to
  `Portfolio/`, that is a manual choice the user makes afterwards — offer to help,
  do not do it silently as part of the reset. The completion marker keeps its
  original setup date; the reset is recorded alongside it, not over it.
- **Snapshotted and checked:** before rewriting anything, finalize captures the
  current `user-profile.yaml`, `pillars.yaml` and room states, then verifies the
  result against the keys the re-answered steps were allowed to change. The
  snapshot stays in `System/.dex/transition-capsules/` and can restore those two
  files exactly — it is not a backup of anything else.

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
