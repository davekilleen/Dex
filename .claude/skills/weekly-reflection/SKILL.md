---
name: weekly-reflection
description: "A short guided reflection on what energized you, what drained you, and one change for next week. Use when the user wants to reflect on how work *felt*, not what got done — 'reflect on my week', 'what's draining me'. Not for progress-and-goals tracking; use `week-review`."
context: fork
---

## Purpose

Pause for a few minutes and notice the lived experience of the week. This is not a progress report. It helps the user see where their energy went and choose one practical change for the week ahead.

## How This Differs from `/week-review`

`/week-review` looks at progress, completed work, goals, and concrete measures. `/weekly-reflection` looks at experience: what felt alive, what felt heavy, and what the user wants to do differently.

The two can be used together, but neither requires the other.

## Step 1: Set the Frame

Say:

> Let's take five minutes to notice the week, not score it. I'll ask three short questions, one at a time.

If the user wants an even shorter version, accept one sentence per question.

## Step 2: Ask What Energized Them

Ask:

> What gave you energy this week? Think about work, people, pace, or moments that felt worthwhile.

After the answer, reflect back the specific source of energy in one or two sentences. Avoid turning it into advice yet.

## Step 3: Ask What Drained Them

Ask:

> What drained you this week? What felt heavier, more frustrating, or more costly than it should have?

Notice whether the drain came from the work itself, unclear expectations, too many switches, a relationship, or lack of recovery. Offer the pattern as a possibility, not a diagnosis.

## Step 4: Choose One Change

Ask:

> What is one thing you want to change next week?

Help make the answer small and observable. Prefer a change the user can control.

Examples:

- Protect one meeting-free morning
- Ask for the decision before starting the work
- End the day with ten minutes to close open loops
- Spend more time on the work that created energy this week

If the user names several changes, ask which single one would make the biggest difference.

## Step 5: Save the Reflection

Read `System/user-profile.yaml` and check `journaling.weekly`.

### If weekly journaling is enabled

Append the reflection to the current weekly journal under:

`00-Inbox/Journals/YYYY/MM-Month/Weekly/YYYY-Www.md`

Create the file from the existing weekly journal pattern if needed. Never replace an earlier entry.

### If weekly journaling is not enabled

Ask whether the user wants the reflection saved. If yes, append it to:

`06-Resources/Reflections/Weekly_Reflections.md`

If they prefer not to save it, leave the reflection in the conversation only.

Use this structure:

```markdown
## Week YYYY-Www — ending YYYY-MM-DD

**Energized by:**
[User's answer]

**Drained by:**
[User's answer]

**One change for next week:**
[User's answer]
```

Keep the user's own words where possible.

## Step 6: Close Gently

End with a short summary:

> This week, [energy source] gave you something back, while [drain] took more than it should. Next week you're trying [one change].

If the chosen change needs a reminder or task, offer to add it through the normal task flow. Do not create one automatically.

## Rules

- Ask one question at a time
- Do not grade the week or force a positive lesson
- Do not turn every feeling into a task
- Keep the reflection short unless the user wants to go deeper
- Use absolute dates in the saved entry
- Append to journal files; never overwrite the user's earlier writing
