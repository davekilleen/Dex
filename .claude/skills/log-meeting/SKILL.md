---
name: log-meeting
description: Log meeting notes to Dex and Salesforce in one step — extracts action items, matches opportunity, pushes activity log
---

Turn raw meeting notes or a transcript into a structured Dex note and a logged Salesforce activity. The goal is speed: 30 seconds to capture, zero manual SF data entry.

## Arguments

**Optional:** $ACCOUNT, $NOTES

- `/log-meeting` — prompts for account and notes interactively
- `/log-meeting "Pocono Metals"` — jumps straight to notes input
- `/log-meeting "Pocono Metals" "Spoke with John, he's interested in the EMI press..."` — fully inline

---

## Step 0: Gather Input

If $ACCOUNT is not provided, ask:
> "Which account or company was this meeting with?"

If $NOTES is not provided, ask:
> "Paste your notes, transcript, or voice dump — anything works:"

Accept raw, messy input. Fathom summaries, voice-to-text transcripts, bullet lists, stream-of-consciousness — all valid.

---

## Step 1: Parse the Notes

Extract from the raw input:

- **Meeting date** — look for explicit date mentions; default to today (YYYY-MM-DD)
- **Contact names** — anyone mentioned by name
- **Key discussion points** — 3–5 bullets summarizing what was covered
- **Decisions made** — anything resolved or agreed to
- **Action items** — tasks for you or the contact (flag ownership)
- **Next steps** — follow-up calls, demos, quotes requested
- **Sentiment/stage signal** — buying signals, objections, timeline indicators

---

## Step 2: Match Salesforce Opportunity

Call `sf_get_account` with the account name from $ACCOUNT.

If an account is found:
- Note the Account Id (`what_id` for task logging)
- Call `sf_get_opportunity` or `sf_get_pipeline` to find open opportunities under that account
- If exactly one open opp: use it automatically, note the name
- If multiple open opps: list them and ask which one to log against
- If no open opps: log against the Account directly (still valuable)

If no account is found:
- Ask: "I couldn't find '[name]' in Salesforce — log against account name only, or skip SF logging?"

---

## Step 3: Log Activity to Salesforce

Call `sf_create_task` with:

```
subject: "Meeting - [Account Name] - [YYYY-MM-DD]"
description: [structured summary — see format below]
activity_date: [meeting date from Step 1]
what_id: [Opportunity Id if found, else Account Id]
who_id: [Contact Id if a specific contact was matched]
status: "Completed"
priority: "Normal"
```

**Description format for Salesforce:**
```
Meeting Notes — [Account Name] — [Date]

DISCUSSED:
• [point 1]
• [point 2]

DECISIONS:
• [decision if any]

NEXT STEPS:
• [action item / follow-up]

[Dex note link: 00-Inbox/Meetings/YYYY-MM-DD - Account Name.md]
```

Keep it clean — Salesforce descriptions are plain text, no markdown headers.

---

## Step 4: Save Dex Note

Write a meeting note to `00-Inbox/Meetings/YYYY-MM-DD - [Account Name].md`:

```markdown
---
date: YYYY-MM-DD
account: [Account Name]
contacts: [name1, name2]
sf_logged: true
sf_task_id: [task ID returned from sf_create_task]
---

# [Account Name] — [YYYY-MM-DD]

## Summary
[3–5 bullet discussion points]

## Decisions
[Decisions or "None"]

## Action Items
- [ ] [Your action item] ^task-YYYYMMDD-XXX
- [ ] [Their action item — note who owns it]

## Next Steps
[Follow-up timeline, what's expected]

## Raw Notes
[Original input preserved here for reference]
```

---

## Step 5: Create Dex Tasks

For each action item assigned to YOU from Step 1:

Infer the pillar from `System/pillars.yaml`:
- Follow-up calls, quotes → Pipeline & Revenue
- Check-ins, relationship work → Account Management
- Research, product questions → Product & Market Knowledge

Call `work_mcp_create_task` for each, or write directly to `03-Tasks/Tasks.md` if Work MCP is unavailable.

Format:
```
- [ ] [Action] — [Account] [[^task-YYYYMMDD-XXX]] #pillar_1
```

---

## Step 6: Update Person Pages

For each contact mentioned by name:

1. Look up via `lookup_person` (Work MCP)
2. If found, append to their page under `## Meeting History`:
   ```
   - [[YYYY-MM-DD - Account Name]] — [1-line summary]
   ```
3. If not found and they seem like a recurring contact, offer: "Want me to create a person page for [Name]?"

---

## Step 7: Confirm

Show a summary:

```
✅ Logged to Salesforce
   Task ID: [id]
   Linked to: [Opportunity or Account name]

📝 Dex note saved
   00-Inbox/Meetings/YYYY-MM-DD - Account Name.md

✅ Tasks created ([n])
   • [task 1]
   • [task 2]

👤 People updated
   • [Name] — meeting reference added
```

If Salesforce logging failed, show the error and offer to retry or log manually.

---

## Error Handling

- **SF auth expired**: Prompt "Salesforce needs re-auth — run `sf_authenticate` and then retry"
- **No match in SF**: Still save the Dex note; offer to log to SF manually later
- **Empty notes**: Ask again — don't process an empty input
- **No action items found**: Confirm with user: "I didn't spot any action items — anything to add before I wrap up?"

---

## Tips

- Works great with Fathom summaries — paste the AI summary directly
- Voice-to-text from Windows (Win+H) dumps fine too — messy is OK
- You can say "log meeting Pocono Metals" in natural language and Dex will invoke this
- Run `/triage` later if you need to route the note to a project folder
