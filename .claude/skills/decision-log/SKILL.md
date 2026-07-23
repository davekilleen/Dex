---
name: decision-log
description: Capture an important decision with its context, options, rationale, and review date, then find it again when it matters.
context: fork
---

## Purpose

Keep important decisions from disappearing into meetings, messages, or memory. Record what was decided, why it made sense at the time, and when it should be looked at again.

Use this for decisions that would be costly, confusing, or time-consuming to reconstruct later. Do not turn every small preference into a formal entry.

## When to Use

- The user says "we decided", "I chose", or "the call is"
- A meeting ends with a meaningful choice
- Several options were considered and the reasoning may matter later
- A past decision is shaping today's work
- The user asks why something was done

## Step 1: Look for Relevant Past Decisions

Before recording a new decision, search for the topic in:

1. The active project's files under `04-Projects/`
2. `06-Resources/Decisions/Decision_Log.md`
3. Recent meeting notes under `00-Inbox/Meetings/`
4. Related person or company pages when the decision concerns them

If semantic search is available, use it to find decisions expressed in different words. Otherwise use a careful text search.

Surface a past decision only when it is genuinely relevant. Say what was decided, when, and whether the new choice confirms, changes, or replaces it.

## Step 2: Confirm the Decision

Gather the minimum information needed for a useful record:

- **Decision:** the choice in one clear sentence
- **Context:** what made the choice necessary
- **Options considered:** the real alternatives, including keeping things as they are when relevant
- **Rationale:** why this option won
- **Review date:** a date or a clear statement that no review is needed
- **Related work:** project, goal, people, company, or meeting

If anything important is missing, ask one question at a time. Do not invent options or reasoning the user did not give.

## Step 3: Choose the Right Home

Use the narrowest useful location:

- A decision that belongs to one active project → append to that project's `Decisions.md`
- A decision that applies across projects or to the user's wider work → append to `06-Resources/Decisions/Decision_Log.md`
- If the best project is unclear → ask before filing it

Create the parent folder or file when it does not exist. Append to an existing file; never replace earlier decisions.

## Step 4: Write the Entry

Use this structure:

```markdown
## YYYY-MM-DD — Decision title

**Decision:** One sentence stating the choice.

**Context:** The situation, constraint, or question that prompted it.

**Options considered:**
- Option A — the main benefit or trade-off
- Option B — the main benefit or trade-off

**Rationale:** Why this choice made the most sense with the information available.

**Review:** YYYY-MM-DD — what would justify revisiting it

**Related:** [[Project, goal, meeting, person, or company]]
```

If no review is needed, write `**Review:** No planned review` rather than leaving the field blank.

Keep the entry factual and compact. Preserve uncertainty: if the choice was a trial, say so.

## Step 5: Close the Loop

After saving, confirm:

- The decision in one sentence
- Where it was saved
- The review date, if any
- Any earlier decision it replaces

If the decision creates follow-up work, offer to add the next action through the normal task flow. Do not create a task without the user's confirmation.

## Connection to `/week-review`

Entries with a review date, a changed assumption, or an unresolved follow-up are designed to be surfaced during `/week-review`. When this skill records one of those, mention that `/week-review` can bring it back at the right time. This is a connection between the two skills; do not edit the week-review files.

## Rules

- Record the user's decision, not your preferred answer
- Separate facts from assumptions
- Never rewrite an older entry to make history look cleaner
- When a decision changes, add a new entry and link the earlier one
- Use absolute dates
- Keep sensitive personal details out unless the user explicitly wants them recorded
