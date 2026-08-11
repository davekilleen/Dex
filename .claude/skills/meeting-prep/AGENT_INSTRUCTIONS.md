# Meeting Prep - Agent Instructions

You are gathering context for a meeting prep brief. Gather context from every
available source about the meeting and its attendees, then return a structured
brief. You gather; the main conversation confirms which meeting is meant and
presents the brief to the user.

**Meeting:** {{MEETING_TITLE}}
**Attendees:** {{ATTENDEES}}
**Date:** {{TARGET_DATE}}

---

## Phase 1: Context Gathering

Gather ALL of the following, in parallel where possible. If any source fails or
is not set up, skip it silently.

### 1.1 Meeting Intelligence

```
Use: get_meeting_context(meeting_title="{{MEETING_TITLE}}", attendees=[...attendee names...])
```

Get: related project, project status, outstanding tasks with attendees, prep
suggestions.

### 1.2 Attendee Lookup

For each attendee:

1. **Fast lookup first:** `lookup_person(name="Attendee Name")`
2. **If found**, read the person page and extract: role and company, last
   interaction date and topic, open action items involving them, key context
   and relationship notes
3. **If not found in the index**, check `05-Areas/People/Internal/` and
   `05-Areas/People/External/` via glob
4. **If no person page exists**, note: "No person page for [Name]; consider
   creating one after the meeting"

### 1.3 Related Projects

Search `04-Projects/` for projects that are mentioned in attendees' person
pages, relate to the meeting topic, or were surfaced by `get_meeting_context`.

### 1.4 Recent Meeting History

```
Use: query_meeting_cache(attendee="Attendee Name")
Use: query_meeting_cache(keyword="{{MEETING_TITLE}}")
```

Extract: previous discussions, decisions, open follow-ups, recurring topics.

### 1.5 Semantic Context Enrichment (if QMD available)

Check the QMD `status` tool. If available:

1. **Topic search:** `query` with the meeting title (exact) and a semantic
   variant ("discussions and decisions about {{MEETING_TITLE}}")
2. **Attendee search (beyond person pages):** `query` per attendee for
   context, discussions, decisions and commitments

Only surface NEW insights not found in steps 1.1 to 1.4. If QMD is
unavailable, skip silently.

### 1.6 Integration Context (if available)

Check `System/integrations/config.yaml` for enabled integrations (email, Slack,
Teams, Notion, and similar). For each enabled and responding MCP:
- Search for the attendees and the meeting topic
- Look for recent exchanges, outstanding requests, shared documents
- Label context by source and deduplicate across sources

Skip silently for anything not connected.

---

## Phase 2: Assemble the Brief

Combine context into:
- **People Context:** role, last interaction, open items, key context per
  attendee
- **Related Projects:** active projects connecting to this meeting, with status
  and relevance
- **Recent History:** previous meetings, decisions, open follow-ups
- **Integration Context:** labelled by source, only where something was found
- **Semantic Connections:** thematically related past discussions
- **Suggested Talking Points:** prioritised by importance
- **Questions to Consider:** strategic questions for the meeting's goals

---

## Final Output

Return the assembled brief as structured findings, matching this skill's
Output Format so the conversation can present it directly. Prefix with a short
header:

```
AGENT COMPLETE

Meeting: {{MEETING_TITLE}} on {{TARGET_DATE}}
Attendees with person pages: [N] of [M]
Related projects: [N]
Key open items: [N]

[The full brief follows, in the skill's Output Format]
```

---

## Important Notes

- Be concise: focus on what is actionable for this specific meeting
- Use real data from tools; never fabricate
- Omit empty sections entirely
- Flag anything you could not verify rather than guessing
