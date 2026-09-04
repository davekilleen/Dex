---
name: goal-backlog
description: "Groom the open task pool goal by goal: see everything under each quarter goal, confirm doubtful goal links, retire what has gone stale, and mark what gets picked up first when that goal earns week-time. Use when the user says 'groom my backlog', 'what's under this goal', 'my tasks are a swamp', 'clean up my tasks', or when open tasks have piled up untouched. Not for routing new inbox items; use `triage`. Not for setting the week's priorities; use `week-plan`."
---

<!-- Generated from `.claude/skills/goal-backlog/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

Turn a swampy task list back into a groomed pool: one goal at a time, decide what's still real, what's next, and what can go — so `/week-plan` pulls from decisions you already made instead of a flat dump.

## Usage

- `/goal-backlog` — Walk every group, one goal at a time
- `/goal-backlog Q3-2026-goal-2` — Groom one goal only

## The one rule that overrides everything

**Never delete or move a task silently.** Every exit from the backlog is the user's decision, and before any line is removed or relocated you show the exact lines that will change. Completing a task through the Work MCP is the only exit that needs no preview, because nothing is removed.

---

## Step 1: Load the backlog

Call `get_goal_backlog(goal_id="all")` (or the single goal ID the user named).

Handle the response per CLAUDE.md's `feature_status` convention:
- `off` (Quarter Goals room off): one calm line with the returned `user_message`, no error tone, and stop — there is nothing to groom without goals.
- `not_installed` / `broken`: surface the returned `user_message` and its fix path, then stop.
- `unknown`, or the tool errors: say the backlog could not be checked. Do not improvise a grooming pass from grep.

If the pool is empty (`open_task_count` is 0), say so plainly and stop — no invented work.

Then show a one-screen overview in plain language, largest and stalest groups first:

> "27 open tasks. Goal 2 (Launch mobile beta) holds 14 — 9 untouched for 3+ weeks. Goal 1 holds 6, all fresh. 5 tasks serve a pillar but no goal, and 2 are linked to nothing at all. Where do you want to start?"

Staleness comes from each task's `staleness_days` (age since the task was created); a group's `stale_count` uses the 3-week line the tool reports. Say "sat untouched for 3+ weeks" — never dress the number up as activity data it isn't.

## Step 2: Groom one goal at a time

For the chosen group, show: the count, the stale flags, tentative `(?)` links, and the current next-up order if one exists. Keep it to one screen; titles and ages, not raw metadata.

Work through three passes, in this order:

### 2a. Settle the doubtful links

For each task marked `tentative`, ask one short question — "Does 'Draft partner FAQ' really serve this goal?" — and call `confirm_goal_link(task_id, action="confirm")` or `action="clear"`. Cleared tasks fall back to their pillar group; mention that so they don't seem to vanish.

### 2b. Retire what's dead — completion is not the only exit

For stale items (and anything the user calls out), offer four honest exits:

| Exit | What happens | How |
|------|--------------|-----|
| **Done** | It was actually finished — mark it complete everywhere | `update_task_status(task_id, status="d")` |
| **Someday** | Still real, not this quarter — park it out of the open pool | Move the task line **and its indented child bullets** from `03-Tasks/Tasks.md` to `03-Tasks/Someday.md` (create that file with a one-line header if missing). Show the exact lines before moving. Nothing is deleted; moving the lines back revives the task. |
| **Delete** | It's noise — remove it for good | Show the exact lines that will be removed and get an explicit yes **for that task** first. Never batch-delete on one blanket approval. |
| **Keep** | Still earning its place | No change |

### 2c. Set the next-up order for the survivors

Ask the deciding question plainly: **"When this goal gets week-time, what should be picked up first?"**

For each item the user sequences, call `set_task_next_up(task_id, next_up=N)` (1 = first). To drop something out of the order, `set_task_next_up(task_id, next_up=null)`. Suggest an order from priority and age if asked, but the user ranks — don't renumber a queue they already set without asking.

## Step 3: Pillar-only and orphaned work — last

After the goal groups, walk the pillar groups, then the fully orphaned tasks:

- For each, offer to link it to a goal — or **consciously leave it operational**; not everything must ladder up, and saying so is a fine outcome.
- To add a link, append the documented indented child bullet under the task line in `03-Tasks/Tasks.md` — for example `- Goal: Q3-2026-goal-2` — matching the metadata format Dex writes itself. Show the edit before making it.
- Orphans with no pillar either get a pillar bullet the same way or stay put by choice.

Pillar groups can carry a next-up order too — same question, same tool.

## Step 4: Provisional goals — offer once, then move on

A group flagged `provisional` was recovered from freeform text: its ID is generated and tasks cannot link to it until it is structured. Offer **once**:

> "Two of your goals were recovered from freeform notes. Want me to structure them into the quarter goals page shape (`### N. Title — **Pillar** ^Qn-YYYY-goal-N`) so tasks can link to them?"

If declined, drop it — don't raise it again this session, and don't repeat the offer per goal.

## Step 5: Close with a one-screen summary

End with exactly what changed, nothing rhetorical:

> "Grooming done.
> - Goal 2: confirmed 2 links, cleared 1, marked 1 done, parked 3 in Someday, next-up order set (3 items).
> - Goal 1: untouched — all fresh.
> - Linked 2 pillar tasks to Goal 3; left 3 operational by your call.
> - Deleted 1 task (you approved the exact line).
>
> `/week-plan` will now pull each goal's next-up items first. To undo an order, ask me to clear next-up on a task; to revive a parked task, move its lines back from `03-Tasks/Someday.md`."

---

## Quality bar

A good grooming pass leaves every surviving task deliberately kept, every stale item decided (not re-snoozed by silence), and at least the most active goals with a next-up order `/week-plan` can pull from. The user should be able to say afterwards what left the pool and why.

## Anti-patterns

- **Deleting or moving anything without showing the exact lines and getting a yes.** This is the cardinal sin of a groomer.
- **Marking a task done to tidy it away.** Done means finished; use Someday or delete for the rest.
- **Nagging about provisional goals** after one declined offer.
- **Renumbering the user's existing next-up order** on your own initiative.
- **Grooming into planning.** Choosing the week's priorities is `/week-plan`'s job; hand off there instead of duplicating it.

## Track Usage (Silent)

Update `System/usage_log.md` to mark goal-backlog grooming as used.

**Analytics (Silent):** Call `track_event` with event_name `goal_backlog_completed` and properties `goals_groomed`, `tasks_retired`, `next_up_set`. Fires only if the user opted into analytics; no action if it returns "analytics_disabled".
