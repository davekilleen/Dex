---
name: meeting-prep
description: "Prepare for a specific upcoming meeting by gathering attendee context, history and related topics. Use when the user says 'prep me for my meeting with X', 'what do I need for the 2pm', or before a calendar event. Also use proactively when a meeting is imminent. Not for writing up a meeting that already happened; use `process-meetings`."
---

<!-- Generated from `.claude/skills/meeting-prep/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

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

1. Read `.agents/skills/meeting-prep/AGENT_INSTRUCTIONS.md`.
2. Substitute its placeholders (`{{TARGET_DATE}}`, `{{MEETING_TITLE}}`,
   `{{ATTENDEE_RECORDS}}`). `{{ATTENDEE_RECORDS}}` is the filtered JSON array
   from the selected invite, preserving `name`, `person_page`, `email`,
   `status`, `type`, and `is_current_user` for each attendee. For attendees the
   user supplied manually, use the same fields with unknown values set to
   `null`, `type` set to `Person`, and `is_current_user` set to `false`.
3. Call the Agent tool with `subagent_type: "general-purpose"`, that prompt, and
   a short description.
4. Present its findings as the prep brief, in the Output Format below.

Spot-check before presenting: the brief names person pages, projects and past
meetings. Confirm a sample of those files actually exist before repeating their
content to the user, and drop anything you cannot stand behind. A subagent's
report is a claim, not evidence.

The subagent inherits MCP connections, runs in its own context, and that context
is freed when it completes, so only its findings reach this conversation.

**Use `AGENT_INSTRUCTIONS.md` verbatim.** Read the file and pass its content as
the subagent prompt, substituting only the placeholders. Do NOT hand-write a
replacement brief from what you already know about the meeting: that is how steps
get silently dropped, and the omission looks complete because nothing errors. If
context from this conversation is worth adding, APPEND it to the file's content;
never substitute for it.

**Two caveats that are load-bearing:**

- **Do not count on hooks for the subagent's writes.** The hooks declared in
  this skill's own frontmatter belong to this skill's run, not the subagent's,
  and whether the repository-wide hooks in `the host's lifecycle settings` reach a
  subagent's tool calls is not something a skill should assume either way.
  Nothing in this skill's gathering depends on a hook; the subagent's writes
  must stand on their own.
- **Always fall back.** If the subagent fails, times out, or returns nothing
  usable, say so plainly and run the gathering inline from the same
  `AGENT_INSTRUCTIONS.md`. A missing subagent must never mean a missing result.

**Stays inline:** confirming which meeting is meant, and presenting the brief.

Prepare for an upcoming meeting by gathering context on attendees and related topics.

## Tone Calibration

Before executing this command, read `System/user-profile.yaml` → `communication` section and adapt:

**Career Level Adaptations:**
- **Junior:** Provide more context about attendees, suggest preparation tips
- **Mid:** Balance context with action, suggest talking points
- **Senior/Leadership:** Strategic framing, influence opportunities, key decisions
- **C-Suite:** High-level strategic context, organizational implications, key stakeholders

**Directness:**
- **Very direct:** Bullet points, key facts only
- **Balanced:** Context + talking points (default)
- **Supportive:** Detailed prep, conversation strategies

**Detail Level:**
- **Concise:** Names, roles, top 3 talking points
- **Balanced:** Standard prep format
- **Comprehensive:** Full context, relationship dynamics, strategic considerations

See CLAUDE.md → "Communication Adaptation" for full guidelines.

---

## Arguments

**Optional:** $MEETING, $ATTENDEES

If either value is missing, try the calendar before prompting. Ask for the
meeting topic or attendee list only when the calendar status or the returned
events cannot identify the meeting safely.

**Examples:**
- `/meeting-prep "Q1 Planning" "Sarah Chen, Mike Rodriguez"`
- `/meeting-prep` (then prompt for details)

## What This Does

1. Reads the matching calendar invite and keeps its resolved attendee records
2. Looks up only attendees whose invite record has no `person_page`
3. Surfaces recent interactions and open action items
4. Checks for related projects
5. Suggests talking points based on context

## Process

### Step 0: Gather Context (if needed)

**If $MEETING or $ATTENDEES are not provided, try the calendar before asking.** The user booked
the meeting; the invite already holds the title and the attendee list, and asking them to retype
it is both friction and a source of duplicate person pages from misspelt names.

When the calendar integration is available, search every calendar visible to
Apple Calendar by default:

```
mcp__calendar-mcp__calendar_get_events_with_attendees(calendar_name="all", start_date="YYYY-MM-DD", end_date="YYYY-MM-DD")
```

`calendar_name="all"` means all calendars currently visible to the local Apple
Calendar integration. It cannot see a calendar account that is not synced into
Apple Calendar, and on hosts that do not support the `all` selector you must say
which single calendar was searched. Never describe a no-match from one calendar
as proof that the meeting is absent from every calendar.

**The end date is exclusive.** For a single day, pass the following day as `end_date`. Passing
the same date twice returns zero events with no error, which is indistinguishable from an empty
calendar.

Match the user's phrasing to an event:

- **A time** ("prep me for the 2pm", "tomorrow's 1:30"): match on start time, usually
  unambiguous on its own.
- **A person or topic** ("prep me for the Acme call"): match on title, or on an attendee name
  within the event's `attendees` list.
- **Nothing specified:** list today's and tomorrow's events and ask which one is meant.

Each attendee carries `name`, `email`, `status`, `type`, `is_organizer`,
`is_current_user`, plus `has_person_page` and (when resolved) `person_page`, so
the vault lookup in Step 1 is already done for anyone who has a page.

Before delegating gathering, build `{{ATTENDEE_RECORDS}}` from the selected
event. Preserve `name`, `person_page` (or `null`), `email`, `status`, `type`, and
`is_current_user`; do not reduce the records to display names. Filter out:

- the user (`is_current_user: true`)
- `Room`, `Resource`, and `Group` attendee types
- invitees whose status is `Declined` or `Delegated`

Keep `Person` attendees who are `Accepted` or `Tentative`. A `Pending` or
`Unknown` person may still attend: keep them, but do not describe their
attendance as confirmed. If an attendee has an unknown type, keep them only
when they have a usable name or email and flag that uncertainty in the brief.

**Ask when the calendar cannot answer.** The calendar is the preferred source,
not a required one, and this skill must still work without it. Inspect the
complete calendar response before reading `events` or `count`, and follow
CLAUDE.md's **Calendar response confidence contract** at this inline call site:

- Only `success: true` is a healthy read. A healthy `count: 0` means the
  searched range is empty only when the response has no `warning`; preserve a
  warning and ask rather than claiming there are no meetings.
- `feature_status: off` is healthy optional absence. Ask for the meeting and
  attendees with no error tone, setup advice, or nag.
- `feature_status: not_installed` surfaces the returned `user_message` and fix
  once in a calm setup tone, then asks for the meeting and attendees.
- `feature_status: broken` surfaces the returned `user_message` exactly,
  including its permission or other fix guidance, then asks so prep can
  continue. Never recast it as “not connected” or “no meetings.”
- `feature_status: unknown`, or an unstructured tool error, means the calendar
  could not be checked. Say that plainly and ask rather than guessing.
- **No Calendar tool response** (for example, on a non-macOS machine) is
  optional absence. Ask for the meeting and attendees without reporting a
  fault.

Every non-healthy branch is unavailable evidence, not an empty calendar. Never
substitute an empty event list for a missing or failed response.

- **No matching event** in the range returned: ask which meeting is meant rather than guessing.
- **Two events match a stated time:** that is a double-booking. Name both and let the user
  choose; it is worth telling them about in itself.

Never treat an empty result as proof of an empty calendar. A tool that is absent, a permission
that was refused, and a query built with the wrong range all return nothing, and none of them
mean "no meetings". If you cannot tell which it was, say so and ask.

When asking, accept any natural format: "Sarah Chen, Mike Rodriguez", "Sarah, Mike", or a plain
list.

### Step 1: Attendee Lookup

For each filtered attendee record:

1. **If the calendar supplied `person_page`, use it and pass it through to
   delegated gathering.** That resolution is already done and is
   more reliable than matching a name, particularly for the display forms invites actually
   carry: `Surname, First`, a job title in parentheses, or a bare email address where the name
   should be. Only fall back to searching when `has_person_page` is false or the attendee came
   from the user rather than the calendar.

   Otherwise search `05-Areas/People/Internal/` and
   `05-Areas/People/External/` using the attendee's email first, then name.
2. If found, extract:
   - Role and company
   - Last interaction date
   - Open action items involving them
   - Key context or notes

3. If not found, note: "No person page for [Name] - consider creating one after the meeting"

### Step 2: Related Projects

Search `04-Projects/` for any projects that:
- Mention the attendees
- Relate to the meeting topic ($MEETING)

Extract:
- Project name and status
- Relevant milestones or blockers
- Recent updates

### Step 3: Recent Context

Search `00-Inbox/Meetings/` for recent meetings with these attendees:
- What was discussed?
- What was decided?
- What follow-ups were committed?

### Step 3a: Semantic Context Enrichment (if QMD available)

**This step runs automatically when QMD is installed.** It enriches meeting prep with semantically related vault content that keyword search would miss.

Check if QMD MCP tools are available by calling the `status` tool (QMD MCP). **If available:**

1. **Semantic search for meeting topic:**
   ```
   query(query="$MEETING", limit=5)
   ```
   Look for: related past discussions, relevant decisions, thematic connections — content that shares meaning with the meeting topic but uses different words.

2. **Semantic search for each attendee (beyond their person page):**
   ```
   query(query="$ATTENDEE_NAME context discussions decisions", limit=3)
   ```
   Look for: contextual references where this person is mentioned by role/title/team (e.g., "the VP of Sales asked about..."), not just by name.

3. **Cross-reference results** with what Steps 1-3 already found. **Only surface NEW insights** — content that the keyword-based person page lookup and meeting folder grep in earlier steps missed.

**Add to the prep brief under a "Semantic Connections" heading:**
- Past discussions thematically related to this meeting (even if different keywords were used)
- Decisions made in adjacent contexts that are relevant here
- Commitments or open items discovered through semantic matching
- Related projects or goals that connect by meaning

**If QMD is not available:** Skip this step silently. Steps 1-3 provide the standard keyword-based context.

---

### Step 3b: Integration Context (if available)

Check `System/integrations/config.yaml` to see which integrations are enabled.

**Notion Integration:**
If `enabled.notion: true` AND Notion MCP is available:
```
Search Notion for pages related to:
- Meeting topic ($MEETING)
- Attendee names

Include in prep:
- Relevant Notion docs (title + summary)
- Shared pages with attendees
```

**Slack Integration:**
If `enabled.slack: true` AND Slack MCP is available:
```
Search Slack for recent conversations:
- With/about each attendee
- Mentioning the meeting topic

Include in prep:
- Recent Slack context (last 7 days)
- Key threads or decisions
- Any commitments made
```

**Teams Integration:**
If `teams.enabled: true` AND Teams MCP available:
```
Search Teams chats with attendees:
- Recent 1:1 and group chats involving each attendee
- Mentioning the meeting topic

Check Teams channels related to meeting topic:
- Project channels, department channels
- Recent posts and replies

Surface recent decisions from Teams threads:
- Key decisions made in channel conversations
- Any commitments or follow-ups from Teams chats

Include in prep:
- Recent Teams context (last 7 days)
- Key threads or decisions from channels
- Any commitments made in Teams chats
```

**When BOTH Slack and Teams are enabled:**
- Check both sources for each attendee
- Label context by source: "**From Slack:**" / "**From Teams:**"
- Deduplicate if the same person appears in both (merge context, label the source)
- Present in separate sub-sections under Integration Context

**Google Workspace Integration:**
If `google-workspace.enabled: true` AND Google Workspace MCP is available:
```
Search Gmail for recent threads with each attendee (last 7 days):
- Email exchanges and their topics
- Shared Google Docs mentioned in threads
- Outstanding email requests (sent but no reply)

Search for Google Docs related to:
- Meeting topic ($MEETING)
- Shared documents with attendees

Include in prep:
- Recent email exchanges (last 7 days) — key threads summarized
- Shared documents — Google Docs, Sheets, or Slides linked in emails
- Outstanding requests/follow-ups — emails waiting > 48h for reply
```

**Graceful Degradation:**
For MCP responses, follow CLAUDE.md's `feature_status` rendering convention before applying these fallbacks.

If an integration is enabled but the MCP isn't responding:
- Render its status using that convention, then continue with vault-only context.

### Step 4: Compile Prep Brief

## Output Format

```markdown
# Meeting Prep: $MEETING

**Date:** [Today's date]
**Attendees:** $ATTENDEES

---

## People Context

### [Attendee Name]
- **Role:** [Role at Company]
- **Last Interaction:** [Date] - [Topic]
- **Open Items:**
  - [ ] [Action item]
- **Notes:** [Key context about this person]

### [Next Attendee]
...

---

## Related Projects

| Project | Status | Relevance |
|---------|--------|-----------|
| [Name]  | [Status] | [Why it relates] |

---

## Recent History

Previous meetings with these attendees:

| Date | Topic | Key Outcomes |
|------|-------|--------------|
| [Date] | [Topic] | [What was decided/discussed] |

---

## Integration Context (if available)

*This section appears when productivity integrations are enabled.*

### From Slack
> Recent conversation context with attendees (last 7 days)

### From Teams
> Recent Teams chats and channel threads with attendees (last 7 days)

### From Notion
> Related Notion docs: [Doc title](link)

### From Gmail
> Email threads with [Attendee]: [Summary of outstanding requests]

---

## Suggested Talking Points

Based on the context above:

1. **Follow up on:** [Open item from last meeting]
2. **Discuss:** [Project-related topic]
3. **Ask about:** [Something from their context]

---

## Questions to Consider

- What's your main goal for this meeting?
- What do you need from these attendees?
- What decisions need to be made?

---

## Post-Meeting

After the meeting:
1. Add notes to `00-Inbox/Meetings/YYYY-MM-DD - [Topic].md`
2. Update person pages with new context
3. Create tasks for any action items
```

---

## Track Usage (Silent)

Call the `mark_feature_used` tool on the `dex-analytics` MCP server with `meeting-prep`. This ticks the feature's box in `System/usage_log.md`, which is what `/dex-level-up` reads to recommend features that have not been tried. It writes locally and sends nothing, so it runs whether or not analytics is enabled.

**Analytics (Silent):**

Call `track_event` with event_name `meeting_prep_completed` and properties:
- `attendees_count`: number of attendees

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".

---

## When to Use

- Before any meeting with multiple attendees
- When meeting someone you haven't seen in a while
- Before important meetings where you want full context

## MCP Dependencies

| Integration | MCP Server | Tools Used |
|-------------|------------|------------|
| Calendar | calendar-mcp | `calendar_get_events_with_attendees` (optional: resolves the meeting and its attendees; the skill asks the user when it is unavailable) |

---

## Tips

- Run this 15-30 minutes before the meeting
- Create person pages for new contacts after meetings
- Update this context regularly for accurate prep
