---
name: delegate-check
description: "Review open delegations — what you handed off, to whom, its status, and the next useful nudge. Use when the user says 'what did I delegate', 'who owes me', 'check my handoffs', 'follow up with someone'. Not for prepping a meeting; use meeting-prep."
context: fork
---

## Purpose

Give the user a clear view of work they have handed to other people without turning delegation into hovering. Find what is moving, what is waiting, and where a short follow-up would help.

## When to Use

- The user asks what they are waiting on
- The user wants to review delegated work or team commitments
- A weekly planning or review conversation reveals unclear ownership
- A promised follow-up is approaching or overdue

## Step 1: Gather Open Delegations

Read `03-Tasks/Tasks.md` and recent notes in `00-Inbox/Meetings/`.

Look for plain-language patterns such as:

- An owner or assignee who is not the user
- "Delegated to", "waiting on", "with", or "owned by"
- A person promising to send, review, decide, introduce, or deliver something
- A user task whose next step is to follow up with someone
- An open action item in a meeting note assigned to another person

Check related person and project pages when they add useful context. If semantic search is available, use it to catch commitments expressed without the exact words above.

Do not count a general hope, discussion point, or completed promise as an open delegation.

## Step 2: Reconcile Duplicates

The same handoff may appear in both `Tasks.md` and a meeting note. Treat matching owner, outcome, and timing as one delegation, and keep links to both sources.

When two records disagree, show the disagreement plainly and ask which status is current. Do not silently choose one.

## Step 3: Build the Review

For each open delegation, capture:

- **What:** the result the user handed off
- **Who:** the person responsible
- **Handed off:** the date or source meeting, when known
- **Expected:** the promised or useful check-in date, when known
- **Status:** moving, waiting, due soon, overdue, or unclear
- **Last touch:** the latest relevant update
- **Next nudge:** one specific, proportionate follow-up

Present the items in this order:

1. Overdue or blocked
2. Due soon
3. Waiting normally
4. Status unclear

Keep healthy items brief. Spend attention where the user may need to act.

## Step 4: Recommend the Next Nudge

A good nudge is short and easy to answer. Draft it in the user's normal tone and include the outcome or date that matters.

Examples:

- "How is the pricing review looking? I need the final call by Thursday to keep the launch on track."
- "Quick check: are you still able to send the notes this week, or should we reset the date?"

Do not send a message or create a task without the user's approval.

## Step 5: Update the Record

After the user confirms what changed:

- Update a Dex task through the normal task tools, not by hand-editing its checkbox
- Add a short status line to the relevant meeting or project note when that is the clearest source of truth
- Mark a delegation complete only when the promised result is actually delivered or the user explicitly closes it
- If the owner or date changed, preserve the earlier context in the note

## Output

Use a compact review:

```markdown
## Delegations needing attention

- **Pricing review — Morgan**
  - Expected: 2026-07-23 · Status: due soon
  - Last touch: Agreed in the 2026-07-16 launch meeting
  - Next nudge: Confirm whether Thursday still holds

## Waiting normally

- **Customer notes — Riley** · Expected next week · No action today
```

If nothing is open, say so plainly: "I found no open delegations in Tasks.md or recent meeting notes."

## Rules

- Never guess that silence means progress or failure
- Keep the focus on outcomes, not activity
- Distinguish work delegated by the user from work the user personally owes
- Name missing owners, dates, or status as unclear
- Use absolute dates
- Do not nag when the agreed date has not arrived and there is no sign of risk
