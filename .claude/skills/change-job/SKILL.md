---
name: change-job
description: "Guided job or role transition: re-run the setup questions with every unanswered setting carried forward and checked afterwards, re-sort people for the new work email domain, archive the old role's goals, priorities and projects (never deleted), re-point open tasks at the new pillars, and close with a ledger of what changed and how to undo each step. Use when the user says 'I changed jobs', 'I'm changing jobs', 'new role', 'new job', 'went full-time', or 'I'm now [role] at [company]'. Not for a preference change within the same job; use `reset`. Not for first-time setup; use `setup`."
---

Move a whole Dex vault from one role to the next without losing anything: the same setup questions, then people, planning, and tasks — each pass proposed before it runs, each pass skippable, nothing ever deleted.

## The one rule that overrides everything

**Nothing is deleted, and nothing moves without a yes.** Every pass shows exactly what it will do for review before anything is applied. Old-role material is archived where the user can always find it — never removed. Skipping any pass is always a fine answer.

## Step 0: Orient and promise

Read `System/user-profile.yaml` (read-only — never edit it from this skill) and note the current `role`, `company_size`, `email_domain` and, if present, the company name. These are the **old role** values the later passes need. Then lay out the whole transition in plain words and get an explicit yes:

> "Congratulations on the new role. Here's what a job change involves — five steps, and you can skip any of them:
>
> 1. **Setup questions again.** The same questions as first-time setup. Every setting you don't re-answer carries forward unchanged. A snapshot of your current settings is taken first, and the result is checked against it afterwards — if anything was lost, you'll know, and the snapshot can put it back.
> 2. **Re-sort your people.** Old colleagues and new ones are re-filed for your new work email — you see the full list before anyone moves.
> 3. **Archive the old role's planning.** Quarter goals, week priorities and projects from the old role are archived, never deleted, and each project is your call: carry it, close it, or park it.
> 4. **Re-point open tasks.** Tasks still aimed at retired pillars get re-pointed at the new ones, then groomed goal by goal.
> 5. **Housekeeping.** A few one-line offers — refresh your working-patterns profile, review connections that mention the old employer.
>
> Nothing is deleted at any step. Ready to start with the setup questions?"

Stop here if they decline. If what changed is really just preferences within the same job, point at `reset` instead — it is the lighter lever.

## Step 1: Setup questions with carry-forward

Delegate to the `reset` skill: read `.claude/skills/reset/SKILL.md` and follow its steps 2–5 exactly — `start_onboarding_session(force_new=True)`, then the conversation in `.claude/flows/onboarding.md` (the single source of every question; never restate the script here), then `finalize_onboarding(dry_run=True)` showing the `profile_changes` list (every setting that will change, old value → new value — settings not listed carry forward), then `finalize_onboarding()`.

After finalizing, relay the `transition_verification` summary word for word — it reads "Changed (you chose): … Carried forward: N settings. Lost: none." Note the snapshot id it names; the closing ledger needs it.

**If verification fails, stop the whole transition.** Do not run any later pass. Say:

> "The after-check found a problem: [the verification summary, word for word]. I'm stopping the transition here — none of the later steps will run. The snapshot taken before anything changed can put your settings files back exactly as they were. Want me to preview that restore?"

Offer `restore_transition_capsule` exactly as the reset skill describes it: preview first (it defaults to a dry run), then rerun with `dry_run=false` only if they confirm.

If the user skips this step, ask for the new work email domain in one line — the people pass needs it — and pass it explicitly in Step 2.

## Step 2: Re-sort people for the new domain

Call `reroute_people()` from the Work MCP — it defaults to a dry run and to the email domain now in the profile. If Step 1 was skipped, pass `domains` with the domain the user gave. If the tool is missing or errors without a structured response, say the people re-sort could not be run in this vault version and move on — never move person pages by hand.

Show the returned plan in plain language before anything moves:

> "I re-checked [scanned] person pages against [domain]:
> - [count] move to Internal — new colleagues, e.g. Priya Shah (priya@example.com matches the new domain)
> - [count] move to External — people from the old company
> - [count] are already where they belong
> - [count] have no email recorded, so I won't guess — they stay put: [names]
> [Any skipped pages, with the tool's reason, word for word.]
> Apply these moves?"

On yes, call `reroute_people(dry_run=false)` and report the ledger honestly from the response: moved, relabeled, anything that failed (relay `warnings` word for word — a collision is skipped, never overwritten), and that the people index was rebuilt. Ambiguous pages are never moved; offer to add an email to a page so the next run can place it.

## Step 3: Archive the old role's planning

**3a — goals and priorities.** Offer once:

> "Your quarter goals and week priorities still describe the old role. I can move both pages, whole, to `07-Archives/Role_Transitions/[YYYY-MM-DD]-[old-role]/` and start fresh ones from the blank starter. Nothing is deleted — moving the files back undoes it. Want me to?"

On yes: show the exact source → destination for each file first. Create `07-Archives/Role_Transitions/<YYYY-MM-DD>-<old-role-slug>/` (date = today, slug = the old role lowercased, spaces to hyphens) and move `01-Quarter_Goals/Quarter_Goals.md` and `02-Week_Priorities/Week_Priorities.md` there under their own names. If a destination file already exists, stop on that conflict and keep both versions — never overwrite. Then reseed the live files from this skill's own starters: copy `references/quarter-goals-starter.md` to `01-Quarter_Goals/Quarter_Goals.md` and `references/week-priorities-starter.md` to `02-Week_Priorities/Week_Priorities.md`, replacing `{{WEEK_START_DATE}}` with the coming Monday's date. A page that doesn't exist (room off, or never created) gets one calm line and is skipped — no error tone.

**3b — projects, one at a time.** Walk each page in `04-Projects/`, never as a batch. For each:

> "**[Project name]** — last touched [date]. Carry it into the new role (no change), close it (archive to `07-Archives/Projects/` with a one-line outcome), or park it (marked on hold, left in place)?"

Every project gets its own answer — never apply one blanket yes to the rest. Close = move the page to `07-Archives/Projects/` keeping its filename, adding the completion date and a one-line outcome at the top. Park = add `**Status:** Parked (role transition YYYY-MM-DD)` at the top of the page and leave it where it is. Nothing is deleted under any answer.

## Step 4: Re-point open tasks

Read the current pillar names from `System/pillars.yaml`, then scan open tasks in `03-Tasks/Tasks.md` for `- Pillar:` child bullets naming a pillar that no longer exists. If any:

> "[count] open tasks still point at pillars from the old role: [count] at '[old pillar]', [count] at '[old pillar]'. Tell me which new pillar each old one maps to and I'll re-point them in one pass — or leave any group as-is. Here's what one edit looks like:
> `- Pillar: Fractional Clients | Priority: P2` → `- Pillar: Customer Growth | Priority: P2`"

Apply a confirmed mapping by editing only the `- Pillar:` child bullets — never the task's title line or its ID. Show one real sample edit from their file before running the pass.

Then hand the pool to the groomer: suggest `/goal-backlog` to walk the open tasks goal by goal — confirming links, retiring stale work, and setting what gets picked up first. Don't duplicate its grooming here.

## Step 5: Housekeeping — one line each, no nagging

- "Want me to refresh your working-patterns profile for the new role? (`/identity-snapshot`)"
- Read `System/integrations/config.yaml` and `.mcp.json` and list any entries that mention the old employer: "These connections still mention [old company]: [list]. I never remove a connection myself — worth a look when you have a minute." If nothing matches, say nothing.
- "Your usage history still reflects the old role; it evens out on its own — nothing to do."

Each is an offer made once. A no is final for this session.

## Close: the ledger

End with one screen — exactly what happened, pass by pass, and how each is undone:

> "Job change done. The record:
> - **Settings:** [the verification summary, word for word]. Snapshot [id] kept in `System/.dex/transition-capsules/` — `restore_transition_capsule` puts the two settings files back exactly as they were.
> - **People:** [moved] moved, [relabeled] relabeled, [ambiguous] left in place (no email recorded). Running the re-sort again with the old domain reverses it.
> - **Archives:** goals and priorities moved to `07-Archives/Role_Transitions/[folder]/`; [count] projects closed, [count] parked, [count] carried. Moving a file back reverses any of it.
> - **Tasks:** [count] re-pointed to new pillars. `/goal-backlog` grooms the rest.
> - **Skipped:** [each skipped pass by name, or 'nothing'].
>
> Nothing was deleted at any step."

Only report what actually happened — a pass that failed or was skipped is named as such, never summarized as done.

## Rules

The question script lives only in `.claude/flows/onboarding.md`, via the `reset` skill — this skill never restates it. `System/user-profile.yaml` and `System/pillars.yaml` are written only by the onboarding tools, never by hand from here. File moves in Steps 3–4 are this skill's own work: always previewed, always confirmed, never a delete.

## Quality bar

A good transition leaves the user able to say, from the ledger alone, what changed, what carried forward, where the old role's material lives, and how to undo any single pass. Every pass they skipped is recorded as skipped, not silently absorbed.

## Anti-patterns

- **Continuing after a failed verification.** A failed after-check stops everything; later passes never run on top of a suspect profile.
- **Deleting anything, ever.** Archive, park, or leave alone — those are the only exits.
- **One blanket yes for many projects.** Each project is its own question.
- **Guessing where an email-less person belongs.** Ambiguous pages stay put and are listed.
- **Removing an integration or connection automatically.** They are listed for review, only ever removed by the user.
- **Restating the onboarding questions here.** They live in the flow; forking them is how scripts drift.

## Track Usage (Silent)

Update `System/usage_log.md` to mark job-change transition as used.

**Analytics (Silent):** Call `track_event` with event_name `change_job_completed` and properties `passes_completed`, `passes_skipped`, `people_moved`, `projects_archived`, `tasks_repillared` (counts only, never names or content). Fires only if the user opted into analytics; no action if it returns "analytics_disabled".
