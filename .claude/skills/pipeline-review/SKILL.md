---
name: pipeline-review
description: Weekly pipeline activity review — surface recent activity across all deals, select what to log to Salesforce, and sync in one shot
---

Review recent activity across your open deals, decide what gets logged to Salesforce, and push it — all in one workflow. Run this at the end of your week or before a pipeline review meeting.

## Usage

- `/pipeline-review` — review past 7 days of activity
- `/pipeline-review 14` — review past 14 days
- `/pipeline-review all` — show all unsynced activity (no date limit)

## Arguments

$DAYS: Optional. Number of days to look back (default: 7). Pass "all" for no date limit.

---

## Step 1: Scan Activity

Run the activity list script:

```bash
python .scripts/sf-activity-list.py --days $DAYS
```

If $DAYS is "all", run:
```bash
python .scripts/sf-activity-list.py --all
```

Parse the output between `PIPE_DATA_START` and `PIPE_DATA_END` lines — each row is:
`account|date|text|file_path|line_num`

---

## Step 2: Present for Review

Display the activity in a clean numbered table grouped by account:

```
Here's your activity from the past 7 days — pick what to log to Salesforce:

  James Cox & Sons (2)
    [1] 2026-06-18 — Call: Left voicemail, following up on TruBend quote
    [2] 2026-06-17 — Email: Sent revised pricing sheet

  Rise Construction (1)
    [3] 2026-06-16 — Visit: Site walkthrough with Brian, confirmed install location

  Pocono Metals (3)
    [4] 2026-06-19 — Call: Spoke with Tom, demo scheduled for next week
    [5] 2026-06-18 — Demo: Showed plasma cutter specs via Zoom
    [6] 2026-06-15 — Email: Sent quote Q-00234

Reply with:
  • "all" — mark everything
  • "1 3 5" — mark specific items by number
  • "all except 2" — mark all minus specific items
  • "skip" — nothing to log this week
```

---

## Step 3: Confirm Selection

Repeat back what will be sent before writing anything:

```
Marking these for Salesforce sync:
  [1] 2026-06-18 — Call: Left voicemail... (James Cox & Sons)
  [3] 2026-06-16 — Visit: Site walkthrough... (Rise Construction)
  [4] 2026-06-19 — Call: Spoke with Tom... (Pocono Metals)

Send these to Salesforce? (yes / edit)
```

Wait for confirmation before proceeding.

---

## Step 4: Tag Selected Entries

For each confirmed entry, read the file at `file_path` and add ` [dex]` to the end of line `line_num`.

The line format is:
```
- **YYYY-MM-DD** — Activity text [dex]
```

Do NOT modify the date, text, or any other part of the line. Only append ` [dex]`.

---

## Step 5: Run Sync

Run the activity sync script:

```bash
python .scripts/sf-activity-sync.py
```

This picks up all newly tagged `[dex]` entries, posts them to Salesforce as Tasks, and marks each line with `<!-- sf:TASK_ID -->`.

---

## Step 6: Summary

Show what was logged:

```
Salesforce sync complete — 3 activities logged:

  James Cox & Sons
    Call: Left voicemail, following up on TruBend quote → Task 00TNu...

  Rise Construction
    Visit: Site walkthrough with Brian → Task 00TNu...

  Pocono Metals
    Call: Spoke with Tom, demo scheduled for next week → Task 00TNu...
```

---

## Tips

- Run at end of week during `/week-review` or before a manager pipeline call
- Entries already tagged `[dex]` or marked `<!-- sf:... -->` are excluded automatically
- Entries from SF (no `[dex]` tag, pulled during pipeline sync) are excluded automatically
- Use `Call:`, `Email:`, `Visit:` etc. prefixes when writing activity — they map to your SF Type picklist
