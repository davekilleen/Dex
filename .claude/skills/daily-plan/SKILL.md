---
name: daily-plan
description: "Build today's plan from calendar, tasks, priorities and commitments, with smart scheduling suggestions. Use when the user says 'plan my day', 'what's on today', 'help me focus', or starts the morning. Also use proactively at the first session of the day. Not for reviewing a finished day; use `daily-review`."
model_routing:
  default: balanced
  steps:
    data-gathering: fast
    synthesis: balanced
hooks:
  Stop:
    - type: command
      command: "node .claude/hooks/daily-plan-quick-ref.cjs"
---

## Execution mode

Run inline in the current conversation by default, so this work can see what the
user has already discussed, decided, or settled this session. Do not fork merely
because this skill was selected. Only run in the background when the user
explicitly asks for a background run or the host has already obtained a specific
background-work approval for this run.

### Delegated gathering (large-vault scaling)

This skill stays inline as described above: it keeps session awareness, it asks
the user the questions, and it owns every interactive step. What it does NOT do
inline is the bulk read-gathering, which on a mature vault (hundreds of notes,
thousands of indexed messages, a live calendar and multiple integrations) can be
large enough to exhaust the main conversation before the useful work starts.

So the gathering phase is delegated to one `general-purpose` subagent via the
Agent tool, using the self-contained prompt in this skill's
`AGENT_INSTRUCTIONS.md`:

1. Read `.claude/skills/daily-plan/AGENT_INSTRUCTIONS.md`.
2. Substitute its placeholders (`{{TARGET_DATE}}`, `{{TARGET_DATE_PLUS_1}}`,
   `{{DAY_NAME}}`, `{{MONTH}}`, `{{DD}}`).
3. Call the Agent tool with `subagent_type: "general-purpose"`, that prompt, and
   a short description.
4. Verify it wrote the draft plan to `07-Archives/Plans/YYYY-MM-DD.md`, then run
   the remaining interactive steps from its findings and present the plan.
5. **Close out every `<!-- NEEDS TASK -->` line in the draft.** The subagent
   never creates tasks, so a focus candidate with no existing task is written
   without a checkbox and marked. For each one: confirm it with the user per
   Step 6, create the task with `create_task`, then rewrite that line as a
   `- [ ]` checkbox carrying the returned `^task-YYYYMMDD-XXX` anchor and
   remove the marker. If the user declines, remove the marker and leave the
   line checkbox-free. Never leave the marker in the saved plan, and never turn
   one of these lines into a checkbox without an anchor — an anchorless
   checkbox is invisible to completion sync forever (Step 6).

The subagent inherits MCP connections, runs in its own context, and that context
is freed when it completes, so only its findings reach this conversation.

**Use `AGENT_INSTRUCTIONS.md` verbatim.** Read the file and pass its content as
the subagent prompt, substituting only the placeholders. Do NOT hand-write a
replacement brief from what you already know about the day: that is how steps get
silently dropped, and the omission looks complete because nothing errors. If
context from this conversation is worth adding, APPEND it to the file's content;
never substitute for it.

**Two caveats that are load-bearing:**

- **Do not count on hooks for the subagent's writes.** The hooks declared in
  this skill's own frontmatter belong to this skill's run, not the subagent's,
  and whether the repository-wide hooks in `.claude/settings.json` reach a
  subagent's tool calls is not something a skill should assume either way.
  Nothing in this skill's gathering depends on a hook; the subagent's writes
  must stand on their own.
- **Always fall back.** If the subagent fails, times out, or returns nothing
  usable, say so plainly and run the gathering inline from the same
  `AGENT_INSTRUCTIONS.md`. A missing subagent must never mean a missing result.

**Stays inline:** the journal and Monday week-planning gates, the yesterday's
review check, Dex Inbox triage, the meeting-task review and goal-link
confirmations, inbound external task review, pushing focus tasks to Reminders,
and usage tracking. These need the user, so they must not be delegated.

## Purpose

Generate your daily plan with full context awareness. Automatically gathers information from your calendar, tasks, meetings, relationships, and weekly progress to create a focused plan with genuine situational awareness.

## Usage

- `/daily-plan` — Create today's daily plan
- `/daily-plan tomorrow` — Plan for tomorrow (evening planning)
- `/daily-plan --setup` — Re-run integration setup

---

## Tone Calibration

Before executing this command, read `System/user-profile.yaml` → `communication` section and adapt tone accordingly (see CLAUDE.md → "Communication Adaptation").

---

## Step 0: Process Unprocessed Meetings

Before gathering context, ensure recent meetings are in the vault by running `/process-meetings`. This pulls any unprocessed meetings from the meeting source (Otter.ai, Granola, etc.), creates meeting notes, updates person/company pages, and extracts tasks — so the daily plan has complete data from yesterday and any earlier gaps.

- If no new meetings are found, continue silently
- If meetings are processed, note the count and use the extracted context in the plan
- Do NOT ask for a skill rating after this sub-step — save that for the end of the full plan

## Step 0.5: Dex Inbox Check (Phone Captures)

Check for tasks captured from phone that haven't been triaged:

```
Use: reminders_list_items(list_name="Dex Inbox")
```

**If the tool is unavailable or errors** (Apple Reminders phone-capture is optional and may not be set up on this machine): skip this step silently — do not surface an error for a feature the user never enabled.

If items found, triage them before building the plan so task counts are accurate. See Step 5.10a for the full triage flow.

**If empty:** Skip silently.

---

## Step 1: Background Checks (Silent)

Run these silently without user-facing output:

1. **Release evidence**: SessionStart already performs the at-most-daily bounded fetch-only check. Read its result;
   do not start a second network attempt. Surface only its complete `release-appears-available-unverified` notice,
   verbatim. Keep `no-newer-release-observed-unverified`, `offline`, `UNKNOWN`, and `skipped` silent here.
2. **Self-learning checks**: Run changelog and learning review scripts if due
3. **Search index refresh**: Run `qmd update && qmd embed` to refresh vault search index with any overnight changes (meetings processed, files edited, etc.). If `qmd` is not installed, skip silently.
4. **People index refresh**: Call `build_people_index` from Work MCP. This keeps the People Directory current so person lookups throughout the day are fast. Takes <2 seconds.
5. **Innovation synthesis** (silent): Call `synthesize_changelog()` and `synthesize_learnings()` from Improvements MCP. These run in background and populate the backlog — results are surfaced in Step 1.5 below.
6. **Granola check** (silent): Granola sync uses the official API via `GRANOLA_API_KEY` (environment or vault-root `.env`). If no key is configured, skip all Granola steps silently — an unconnected optional integration is not an error.
7. **System health** (silent): Read `System/.smoke-last-run.json` when present and retain any broken-journey context for Step 5.10b.

---

## Step 1.5: Innovation Spotlight (Concierge)

After background checks complete, check for noteworthy backlog activity:

1. Call `list_ideas(status="active", min_score=70)` from Improvements MCP
2. Check `System/.synthesis-state.json` for recent synthesis activity (last 7 days)
3. If there are AI-authored or recently enriched ideas, pick the most impactful one

**Surface as a brief spotlight in the plan output (1-2 lines max):**

> **Innovation Spotlight:** Claude Code shipped native memory (v2.1.32) — this could simplify idea-006 (Session Memory MCP). Run `/dex-improve idea-006` to explore.

**Rules:**
- Show at most 1 spotlight per daily plan (don't overwhelm)
- Rotate through ideas — don't show the same one twice in a row
- Only show if there's genuine "Why Now?" urgency (new evidence in last 7 days)
- If no recent synthesis activity, skip this section entirely
- Never block the plan for this — it's a helpful aside, not a gate

---

## Step 2: Morning Journal Check (If Enabled)

If `journaling.morning: true` in user-profile.yaml, check for today's morning journal and prompt if missing.

---

## Step 3: Monday Weekly Planning Gate

If today is Monday and week isn't planned, offer to run `/week-plan` first.

---

## Step 4: Yesterday's Review Check (Soft Gate)

Check for yesterday's review and extract context (open loops, tomorrow's focus, blocked items).

---

## Step 5: Context Gathering (ENHANCED)

Gather context from all available sources. **This is where the magic happens.**

### 5.1 Midweek Progress Check (NEW)

```
Use: get_week_progress()
```

This is critical for genuine situational awareness. Extract:
- Day of week and days remaining
- Weekly priority status (complete / in_progress / not_started)
- Warnings for priorities with no activity

**Surface this prominently:**

> "It's **Wednesday**. Here's where you are on this week's priorities:
> 
> 1. ✅ **Ship pricing page** — Complete (finished Monday)
> 2. 🔄 **Review proposal** — In progress (2 of 5 tasks done)
> 3. ⚠️ **Customer interviews** — Not started (no activity yet)
> 
> You have 2 days left this week. Priority 3 needs attention."

### 5.2 Calendar Capacity Analysis (NEW)

```
Use: analyze_calendar_capacity(days_ahead=1, events=[...from calendar MCP...])
```

Understand the *shape* of today:

- **Day type**: stacked / moderate / open
- **Meeting count and hours**
- **Free blocks available**
- **Recommendation**: What kind of work fits today

**Surface this:**

> "📅 **Today's shape:** Moderate (4 meetings, 3 hours total)
> 
> **Free blocks:**
> - 8:00-9:30 AM (90 min) — Morning focus time
> - 2:00-4:00 PM (120 min) — Afternoon block
> 
> **Recommendation:** Good for medium tasks and meeting prep. Deep work fits the 2-4pm block."

### 5.3 Meeting Intelligence (NEW)

For each meeting today:

```
Use: get_meeting_context(meeting_title="...", attendees=[...])
```

Get genuine context, not just attendee names:
- **Related project**: What project is this connected to?
- **Project status**: What's outstanding? What's blocked?
- **Outstanding tasks with attendees**: What do you owe them? What do they owe you?
- **Prep suggestions**: What should you review before this meeting?

**Surface this with surprise and delight:**

> "📍 **Meeting: Acme Quarterly Review** (2pm with Sarah Chen, Mike Ross)
> 
> **Related project:** Acme Implementation (Phase 2)
> - Status: On track, but pricing section still in draft
> - Outstanding: You owe Sarah the pricing proposal
> 
> **Prep suggestion:** Review proposal draft, prepare pricing options. Block 30 min before this meeting?"

### 5.4 Commitment Tracking (NEW)

Before commitments, read `System/.dex/entity-suggestions.json` (if present). If it has `suggested` entries, add one compact context line: "Dex suggests person pages for: X (N meetings), Y — say the word and I'll create them." This step is read-only.

Also read `System/.dex/entity-cooling.json` when it is present and fresh. If its consequential `cold` list is non-empty, surface it as one compact "❄️ Going cold" line in `## ⚠️ Heads Up`; degrade silently when the feed is absent or empty, and never widen this into a vault-wide people dump.

Also read `System/.dex/entity-relationships.json` when it is present and fresh. If its `suggestions` list is non-empty, surface one compact "🔗 Relationships to confirm" line in `## ⚠️ Heads Up`; degrade silently when the feed is absent, stale, or empty. Keep it as a nudge, show the page and edge being proposed, and offer the real Work MCP actions: `confirm_relationship(page, edge_key)` or `dismiss_relationship(page, edge_key)`. Never choose either action without the user's per-edge say-so.

```
Use: get_commitments_due(date_range="today")
```

Surface things you said you'd do:

> "⚡ **Commitments due today:**
> 
> - You told Mike you'd get back to him by Wednesday (from Monday 1:1)
> - Follow up on competitive analysis (from Acme meeting)"

### 5.5 Task Scheduling Suggestions (NEW)

```
Use: suggest_task_scheduling(include_all_tasks=False, calendar_events=[...])
```

Match tasks to available time based on effort classification:

> "📋 **Scheduling suggestions:**
> 
> | Task | Effort | Suggested Time |
> |------|--------|----------------|
> | Write Q1 strategy doc | Deep work (2-3h) | Tomorrow (you have a 3h morning block) |
> | Review Sarah's proposal | Medium (1h) | Today 2-3pm (before Acme meeting) |
> | Reply to Mike | Quick (15min) | Between meetings |
> 
> ⚠️ **Heads up:** You have 2 deep work tasks but today's too fragmented. Consider protecting tomorrow morning."

### 5.6 Semantic Context Enrichment (if QMD available)

**This step runs automatically when QMD is installed via `/enable-semantic-search`.** It adds a semantic search layer on top of the standard context gathering to surface connections that keyword search misses.

Check if QMD MCP tools are available by calling the `status` tool (QMD MCP). **If available:**

1. **For each meeting today**, run:
   ```
   query(query="[meeting topic] [attendee names]", limit=3)
   ```
   Surface: past discussions, related decisions, relevant commitments that share **meaning** but not keywords with this meeting. Example: a meeting about "customer onboarding" finds notes about "activation rates" and "time to value".

2. **For each weekly priority that's lagging**, run:
   ```
   query(query="[priority description]", limit=3)
   ```
   Surface: vault content that advances or relates to this priority but wouldn't appear in a keyword search. Especially useful for finding forgotten context about stalled work.

3. **Cross-topic connection scan:**
   ```
   query(query="[today's key themes combined]", limit=5)
   ```
   Surface: unexpected connections between today's meetings, tasks, and priorities. This is where semantic search shines — finding that a 2pm customer call relates to a PRD you wrote last month using completely different terminology.

4. **Merge with existing context** — only add genuinely new insights. Don't duplicate what Steps 5.1-5.5 already found. Mark semantic results with their source so the plan output can distinguish them.

**What this enables in the plan output:**
- Meeting context sections include "**Also relevant:**" with thematically related past discussions
- Priority recommendations cite relevant vault content discovered by meaning
- "Heads Up" section catches connections between seemingly unrelated items
- Focus recommendations are informed by deeper vault knowledge

**If QMD is not available:** Skip silently. Steps 5.1-5.5 and 5.7 provide full context via standard methods.

---

### 5.7 Reminders Completion Sync (Dex Today → Dex)

Check if any tasks were completed on phone since the last plan:

```
Use: reminders_list_completed(list_name="Dex Today")
```

**If the tool is unavailable or errors** (Apple Reminders sync is optional and may not be set up on this machine): skip this step silently — do not surface an error for a feature the user never enabled. Note: Reminders access never works when Claude Code runs inside the VS Code extension (macOS never shows the permission dialog to that process) — see the known limitation in `06-Resources/Dex_System/Calendar_Setup.md`. Do not advise reinstalling or reconfiguring; skip silently.

For each completed item:
- Match to a Dex task by title
- Update task status via Work MCP: `update_task_status(task_title="...", status="d")`
- Surface what was synced:

> "📱 **Synced from phone:**
> - ✅ "Follow up with Hero Coders" — marked done in Dex"

**If nothing to sync:** Skip silently.

### 5.8 Email Intelligence (if connected)

Check `System/integrations/config.yaml` for `google-workspace.enabled: true`. Also treat a
registered `apple-mail-mcp` server as a connected source. Before querying a connected email
source, run `python3 core/utils/doctor.py --check mail.apple-search` — a focused local check,
not `--deep`. Apple Mail search is usable only when that check reports `OK` /
`feature_status: ok`.

If connected and healthy:
1. Get unread count and priority emails from monitored labels
2. Flag emails needing reply (> 48h since received, from key contacts in `05-Areas/People/`)
3. Surface email threads with today's meeting attendees

Include in plan:

> "Email: [X] unread, [Y] need replies. [Z] threads with today's meeting attendees."

For Apple Mail, never interpret an empty search as "no matching mail" unless that health check
is OK. If a connected source is broken or could not be checked, **do not silently skip**:
include one calm "Email context omitted" line with Doctor's `user_message` or fix path. If the
source is not connected (`OFF`), omit it without noise.

### 5.9 Teams Intelligence (if Teams connected)

Check `System/integrations/config.yaml` for `teams.enabled: true`.

If enabled and MCP healthy:
1. Get unread messages from priority channels
2. Surface DMs needing response
3. Check for mentions

Include in plan:

> "**Teams:** [X] unread chats, [Y] mentions. [Z] threads with today's meeting attendees."

If BOTH Slack and Teams enabled:
- Show both digests, clearly labeled: "**Slack:** ..." and "**Teams:** ..."
- Deduplicate if the same person appears in both (merge context, label the source)
- Present side by side in the plan output under a combined "Chat Intelligence" heading

If unhealthy: skip silently (graceful degradation -- no error to user).

### 5.10a Mobile Capture Check (Dex Inbox)

```
Use: reminders_list_items(list_name="Dex Inbox")
```

**If the tool is unavailable or errors** (Apple Reminders phone-capture is optional and may not be set up on this machine): skip this step silently — do not surface an error for a feature the user never enabled.

If items found, surface:

> 📱 **Captured on phone** (3 items in Dex Inbox):
>
> 1. "Follow up with Peter about roadmap" — captured yesterday 4:32pm
> 2. "Look into Rovo for in-app guides" — captured today 2:15pm
> 3. "Send Anastasia the productized offering doc" — captured today 11:45am
>
> **Triage these now?** I'll help assign pillars and priorities.

**Triage flow:**
- Run Work MCP `process_inbox_with_dedup` to classify the captured items — it flags
  duplicates and ambiguous items and suggests a pillar; it does NOT create tasks
- Present each item, confirm pillar with user (smart pillar inference)
- Create each confirmed task via Work MCP `create_task` (pass `due`, `people`, or
  `account` when the captured item mentions them)
- Mark Reminder as complete via `reminders_complete_item`

**If Dex Inbox is empty:** Skip silently (no "0 items captured" noise).

### 5.10b Standard Context Gathering

Also gather:
- **Calendar**: Today's meetings with times and attendees
- **Tasks**: P0, P1, started-but-not-completed, overdue
- **Week Priorities**: This week's Top 3
- **Work Summary**: Quarterly goals context (if enabled)
- **People**: Context for meeting attendees
- **Self-Learning Alerts**: Changelog updates, pending learnings
- **System health**: Only when the overnight smoke report has `summary.broken > 0`, note that a self-check found a problem and point to `/dex-doctor` for diagnosis

### 5.11 Meeting-Task Review (NEW)

Give the user one place to review what their meetings turned into. Work from the
`list_tasks` output already gathered (open tasks include `metadata_source` — the
meeting note each task came from — and `goal_tentative`).

1. **Recent meeting tasks.** Collect open tasks whose `metadata_source` is set and
   whose task ID date (`^task-YYYYMMDD-…`) is within the last 3 days. If any,
   present them compactly under the plan's context:

   > **From your meetings** (3 tasks)
   > - Send Acme the revised pricing — from *Acme Quarterly Review* (due Jul 15)
   > - …

2. **Tentative goal links.** Collect open tasks where `goal_tentative` is true.
   If any, review them in one pass:

   > **2 tasks have a likely goal link marked (?)** — want to confirm them?
   > 1. "Draft churn playbook" → *Q3-2026-goal-2: Reduce churn to 4%* — keep this link?

   For each answer, call Work MCP `confirm_goal_link(task_id, "confirm")` to keep
   the link or `confirm_goal_link(task_id, "clear")` to remove it. Never edit the
   task file by hand for this.

3. **Unprocessed meetings.** If `00-Inbox/Meetings/` has notes with unchecked
   `### For Me` items and no `tasks-extracted` marker, add one line:
   "N meetings have unextracted action items — run `/process-meetings` to turn
   them into tasks."

Skip this entire step silently when nothing qualifies — no "0 tasks from meetings"
noise.

### 5.12 Inbound External Tasks Review (NEW)

Give the user one place to review tasks that arrived from a connected task app
(Todoist / Things / Trello) since the last sync. Check
`System/integrations/inbound-tasks.json`. If it exists and is non-empty:

1. Read each item: `{service, external_id, title, raw}`. The `raw` object contains the
   service payload and may include notes/description, priority, and an inferred `pillar`.
2. For each, offer a one-line summary and ask whether to bring it into Dex:
   ```
   📥 From [service]: "[title]"
   Import as a Dex task? (yes / skip / [pillar] [priority])
   ```
3. On confirmation (or pillar/priority provided), call `create_task` with:
   - `title`: from the item
   - `on_duplicate: "fail"` (skip if already exists)
   - `pillar`: user-specified, otherwise `raw.pillar` (the sync step fills this in
     from an automatic pillar guess when inference succeeds). If it is absent, ask the
     user to choose a valid pillar before calling `create_task`
   - `priority`: user-specified, otherwise a valid P0-P3 value from `raw` when present
   - `context`: notes/description/context from `raw` when present
   - Do not pass the integration name as `source`; `source` is reserved for a
     vault-relative source page, while the external mapping records provenance
4. On "skip": leave the item in the queue so it can be reviewed later
5. Immediately after each successful create, call `record_external_task_mapping` with
   the returned `task.task_id`, the item's `service`, and its `external_id`. This records
   the link and removes that item from the inbound queue.

**Silent when empty:** if `inbound-tasks.json` doesn't exist or is empty/`[]`, skip this
step entirely. Never say "no inbound tasks" — just proceed.

---

## Step 6: Synthesis

Combine all gathered context into actionable recommendations:

### Focus Recommendation

Generate 3 recommended focus items based on:
- P0 tasks (highest weight)
- Weekly priority alignment (especially lagging priorities!)
- Meeting prep needs
- Commitments due

**The system should actively recommend, not just list:**

> "Based on your week progress and today's shape, I recommend focusing on:
> 
> 1. **Prep for Acme meeting** — Priority 2 is lagging and this meeting is critical
> 2. **Reply to Mike** — Commitment due today
> 3. **Task X from Priority 1** — Keeps momentum on your shipped priority"

**Task IDs are mandatory on focus items (completion sync depends on them):**

Completion sync (Work MCP `update_task_status`, which updates every file the task
appears in) only finds a line if that single line contains BOTH a `- [ ]` / `- [x]`
checkbox AND the task's `^task-YYYYMMDD-XXX` anchor. A focus item written without the ID — or with the ID on
a different line — is invisible to sync: ticking the task done in Tasks.md never
updates the plan, and marking the plan item done never updates Tasks.md.

So, for each recommended focus item:
1. **If it maps to an existing Tasks.md task** (search by title/keywords), you MUST
   write it in the plan as a `- [ ]` checkbox line with that task's `^task-YYYYMMDD-XXX`
   anchor at the end of the same line. Never omit the ID, never put it on its own line.
2. **If it's real work with no Tasks.md entry yet**, create the task first via Work MCP
   `create_task`, then embed the returned task ID the same way.
3. **Only if it isn't a task at all** (e.g. "protect the 2-4pm free block") may the line
   omit an ID — and then it gets no checkbox either, so it can't masquerade as a
   syncable task.

Format notes that matter: use `- [ ]` (dash checkbox), not `1. [ ]` — numbered
checkboxes do not contain the literal `- [ ]` string the sync matcher looks for, so
they never sync even with an ID present.

### Meeting Prep (Enhanced)

For each meeting, show:
- Who's attending + People/ context
- Related project status
- Outstanding tasks with attendees
- Suggested prep time and what to prepare

### Heads Up (Enhanced)

Flag potential issues:
- Weekly priorities with no activity (midweek warning)
- Commitments due today
- Back-to-back meetings
- P0 items with no time blocked
- Deep work tasks with no suitable slot this week

---

## Step 7: Generate Daily Plan

**ALWAYS generate and save a new plan file.** Never skip generation because a plan from a previous day exists in the conversation or vault. Even if context from a prior plan is visible, today is a new day and requires its own plan. If a plan for today's date already exists, overwrite it (the user is requesting a refresh).

**Filling in `{{^task-id}}` in Today's Focus:** replace it with the item's real
`^task-YYYYMMDD-XXX` anchor per the Task IDs rule in Step 6 (mandatory whenever the
item maps to a Tasks.md task — create the task first if needed). If the item is not a
task at all, drop both the placeholder and the `- [ ]` checkbox for that line.

Create `07-Archives/Plans/YYYY-MM-DD.md`:

```markdown
---
date: YYYY-MM-DD
type: daily-plan
integrations_used: [calendar, tasks, people, work-intelligence]
---

# Daily Plan — {{Day}}, {{Month}} {{DD}}

## TL;DR
- {{1-2 sentence summary including week progress}}
- {{X}} meetings today, day is {{stacked/moderate/open}}
- {{Key focus area based on week priorities}}

---

## 📊 Week Progress (Midweek Check)

**Day {{X}} of 5** — {{days_remaining}} days left this week

| Priority | Status | Notes |
|----------|--------|-------|
| {{Priority 1}} | ✅ Complete | Finished {{day}} |
| {{Priority 2}} | 🔄 In progress | {{X}} of {{Y}} tasks done |
| {{Priority 3}} | ⚠️ Not started | Needs attention |

**This week's focus:** {{Recommendation based on lagging priorities}}

---

## 📅 Today's Shape

**Day type:** {{stacked/moderate/open}} ({{X}} meetings, {{Y}} hours)

**Free blocks:**
- {{Time range}}: {{Size}} — {{Recommended use}}

**Best for:** {{Quick tasks only / Medium tasks / Deep work opportunity}}

---

## ⚡ Commitments Due Today

- [ ] {{Commitment}} — from {{source}}
- [ ] {{Commitment}} — from {{source}}

---

## 🎯 Today's Focus

**If I only do three things today:**

- [ ] {{Focus item 1}} — {{Pillar}} *(supports Week Priority #X)* {{^task-id}}
- [ ] {{Focus item 2}} — {{Pillar}} *(supports Week Priority #Y)* {{^task-id}}
- [ ] {{Focus item 3}} — {{Pillar}} {{^task-id}}

---

## 📍 Meetings (with Context)

### {{Time}} — {{Meeting Title}}

**Attendees:** {{Names}}
**Related project:** {{Project name}} ({{status}})
**Outstanding with them:**
- {{Task/commitment}}

**Prep needed:** {{What to review/prepare}}
**Suggested prep time:** {{Block X min before}}

---

### {{Time}} — {{Meeting Title}}

[Repeat for each meeting]

---

## 📋 Task Scheduling

| Task | Effort | Suggested Slot | Reason |
|------|--------|----------------|--------|
| {{Task}} | Deep work | {{Day/time}} | {{Reason}} |
| {{Task}} | Medium | {{Day/time}} | {{Reason}} |
| {{Task}} | Quick | Between meetings | Batch these |

{{If deep work capacity warning}}
> ⚠️ You have {{X}} deep work tasks but only {{Y}} suitable slots this week. Consider protecting time or deferring.

---

## ⚠️ Heads Up

- {{❄️ Going cold: consequential people/accounts from the cooling feed, when present}}
- {{🔗 Relationships to confirm: suggested typed relationships from the feed, when present}}
- {{Warning about lagging weekly priority}}
- {{Commitment due today}}
- {{Back-to-back meetings}}
- {{Other flags}}

---

*Generated: {{timestamp}}*
*Week progress: {{X}}/{{Y}} priorities on track*
```

---

## Step 7.5: Push Focus Tasks to Reminders (Dex → iPhone)

After generating the plan, push today's P0 and P1 focus tasks to Apple Reminders for native iOS notifications:

1. **Clear yesterday's items:**
   ```
   Use: reminders_clear_completed(list_name="Dex Today")
   ```

2. **Push today's focus items:**
   For each P0/P1 task in today's focus:
   ```
   Use: reminders_create_item(
       list_name="Dex Today",
       title="Task title",
       notes="From Dex daily plan",
       due_date="YYYY-MM-DD"
   )
   ```

3. **Confirm silently:**
   > "📱 Pushed 3 focus tasks to iPhone Reminders (Dex Today)"

**If the tool is unavailable or errors:** Skip silently — do not surface an error for a feature the user never enabled. (This includes Claude Code running inside the VS Code extension, where macOS never grants Reminders access — see `06-Resources/Dex_System/Calendar_Setup.md`.)

---

## Step 8: Track Usage (Silent)

Update `System/usage_log.md` to mark daily planning as used.

**Analytics (Silent):**

Call `track_event` with event_name `daily_plan_completed` and properties:
- `meetings_count`: number of meetings today
- `tasks_surfaced`: number of tasks shown
- `priorities_count`: number of priorities

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".

---

## Graceful Degradation

For MCP responses, follow CLAUDE.md's `feature_status` rendering convention before applying these fallbacks.

The plan works at multiple levels:

### Full Context (All MCPs available)
- Complete week progress, meeting intelligence, scheduling suggestions
- Maximum "surprise and delight"

### Partial Context (Work MCP only)
- Week progress and task scheduling
- No meeting context (prompt user to add manually)

### Minimal Context (No MCPs)
- Interactive flow asking about priorities
- Basic daily note

---

## MCP Dependencies (Updated)

| Integration | MCP Server | Tools Used |
|-------------|------------|------------|
| Calendar | calendar-mcp | `calendar_get_today`, `calendar_get_events_with_attendees` |
| Reminders | calendar-mcp | `reminders_list_items`, `reminders_complete_item`, `reminders_create_item`, `reminders_ensure_lists`, `reminders_list_completed`, `reminders_find_and_complete`, `reminders_clear_completed` |
| Granola | granola-mcp | `granola_get_recent_meetings` |
| Work | work-mcp | `list_tasks`, `get_week_progress`, `get_meeting_context`, `get_commitments_due`, `analyze_calendar_capacity`, `suggest_task_scheduling` |
| Improvements | dex-improvements-mcp | `synthesize_changelog`, `synthesize_learnings`, `list_ideas` |
| Google Workspace | google-workspace-mcp | Gmail query, email search (if enabled) |
| Apple Mail | apple-mail-mcp | Local full-text mail search (only after `mail.apple-search` is healthy) |
| Teams | teams-mcp | `teams_list_chats`, `teams_search_messages`, `teams_health_check` (if enabled) |
