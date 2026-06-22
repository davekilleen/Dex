---
name: week-itinerary
description: Build the weekly field itinerary Excel file — pulls Salesforce opportunities, open tasks, calendar events, and email follow-ups, then routes accounts by territory and exports a formatted .xlsx matching the standard template.
---

Build this week's field itinerary as an Excel file. Run every Sunday evening before the week starts.

## Usage

- `/week-itinerary` — build itinerary for the upcoming Mon–Fri week
- `/week-itinerary next` — explicitly plan next week

---

## Output

File saved to: `Planning/Week XX - Itinerary MM.DD.YYYY.xlsx`

Matches the established template format:
- 3 columns: **A** = Account/Activity, **B** = Date (formula), **C** = Details
- Column widths: A=37, B=13.5, C=75
- Day header rows use theme fill (copied from prior week's file)
- **Yellow highlight** on any account row where the related SF opportunity vendor is in the featured vendor list (Row 2)
- No icons or emoji in cells

---

## Step 0: Find Base Template

Locate the most recent prior week's itinerary file in `Planning/`:

```python
import glob, os
files = glob.glob("Planning/Week * - Itinerary *.xlsx")
src = sorted(files)[-1]  # most recent
```

All formatting, theme fills, and column widths are copied from this file. Never rebuild from scratch.

---

## Step 1: Gather Data (run all in parallel)

### 1a. Salesforce Pipeline
```
sf_get_pipeline(limit=200)
```
Save the full result. Key fields per opportunity: `account`, `name`, `stage`, `amount`, `vendor`.

### 1b. Open Tasks
```
list_tasks(include_done=False)
```
Look for: P0/P1 items, overdue SF tasks, follow-ups with named accounts.

### 1c. Calendar Events
```
calendar_get_events(start_date=MONDAY, end_date=FRIDAY)
```
Identify: confirmed in-person meetings (anchor stops for routing), all-day blocks, travel commitments.

### 1d. Recent Emails
```
get_recent_emails(limit=50)
```
or
```
search_emails(query="follow up OR reply OR quote OR proposal", days=7)
```
Look for: open threads needing replies, quotes sent but not responded to, contacts who reached out.

---

## Step 2: Identify the Week's Anchor Stops

Anchor stops are confirmed in-person meetings from the calendar. These fix the geography for that day's route.

Example: "Penn Steel Fabrication at 1pm Tuesday in Bristol, PA" → Tuesday territory = Bensalem/Bristol.

If no anchors exist for a day, ask the user which territory to cover, or suggest based on last week's rotation.

---

## Step 3: Determine Territory per Day

Standard territory rotation for reference (adjust based on anchors):

| Day | Territory | Cities |
|-----|-----------|--------|
| Mon | Lehigh Valley | Allentown, Bethlehem, Macungie, Easton |
| Tue | Bucks County / Bristol | Bensalem, Bristol, Levittown, Langhorne |
| Wed | Montgomery County | Norristown, King of Prussia, Lansdale, Gwynedd |
| Thu | Upper Bucks / Souderton | Doylestown, Souderton, Telford, Quakertown |
| Fri | Office + NEPA Calls | Scranton, Wilkes-Barre, Pocono area (phone) |

Present the suggested territory map to the user and confirm before building.

---

## Step 4: Pull Account Details for Each Territory

For each territory, find matching accounts from the SF pipeline by:
1. Searching account names for known city/area keywords
2. Using `sf_get_account(name=...)` to get contacts and phone numbers for top accounts

Target **6–8 accounts per day**. Prioritize:
- High-amount opportunities in Negotiation or Favorable stage
- Accounts with no recent activity (stale)
- Overdue tasks from the task list
- Accounts flagged in recent emails

For each account include in Details column:
`[Vendor Code] - [Product] ($Amount Stage) — [Contact Name] ([Phone]) — [One-line action]`

---

## Step 5: Build the Excel File

```python
import shutil
from copy import copy
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from datetime import date

# Copy prior week as base (preserves theme fills and column widths)
shutil.copy2(src, dst)
wb = load_workbook(dst)
ws = wb.active

# Save theme fills from original day-header rows before clearing
fills = {}
for orig_row in [6, 15, 22, 30, 37]:
    fills[orig_row] = copy(ws.cell(row=orig_row, column=1).fill)

# Clear all content rows (preserve header rows 1-4)
# Then set day headers and account rows
```

### Row Layout
```
Row 1:  "Itinerary Week of:" | [Monday date] | —
Row 2:  "Highlight the accounts..." | [Vendor list] | —
Row 3:  "Highlight (2) New Accounts to visit" | [New accounts] | —
Row 4:  "Day:" | "Comment:" | "Details:"
Row 5:  (spacer)
Row 6:  [Monday header — theme fill] | =B1 | —
Rows 7-14:   Monday accounts (8 rows)
Row 15: [Tuesday header — theme fill] | =B1+1 | —
Rows 16-25:  Tuesday accounts (10 rows)
Row 26: [Wednesday header — theme fill] | =B1+2 | —
Rows 27-35:  Wednesday accounts (9 rows)
Row 36: [Thursday header — theme fill] | =B1+3 | —
Rows 37-44:  Thursday accounts (8 rows)
Row 45: [Friday header — theme fill] | =B1+4 | —
Rows 46-57:  Friday accounts (12 rows)
```

### Yellow Highlight Rule

Apply `PatternFill("solid", fgColor="FFF2CC")` to ALL cells in a row (columns A–C) when the account's SF opportunity vendor matches any of:

> AGT Robotics, TRUMPF - Vendor, KALTENBACH North America Inc., Mid Atlantic Global, Pat Mooney Saws, FAB-LINE MACHINERY LLC (Baykal), Cidan Machinery, Flow Waterjet, Vectis Automation, Electro-Mechanical Integrators Inc. (EMI), ALLtra Corp., Geka USA, HE&M Saw, Mid Atlantic Machinery Automation, Standard Industrial Corp.

Vendor code mapping:
| Code | Vendor |
|------|--------|
| TRU | TRUMPF - Vendor |
| AGT | AGT Robotics |
| KAL | KALTENBACH North America Inc. |
| MAG | Mid Atlantic Global |
| PMI | Pat Mooney Saws |
| BAY | FAB-LINE MACHINERY LLC (Baykal) |
| CID | Cidan Machinery |
| FLO | Flow Waterjet |
| VEC | Vectis Automation |
| EMI | Electro-Mechanical Integrators Inc. (EMI) |
| ALL | ALLtra Corp. |
| GEK | Geka USA |
| HEM | HE&M Saw |
| MAM | Mid Atlantic Machinery Automation |
| STA | Standard Industrial Corp. |

Do NOT highlight: internal activities (MAM Huddle, Pipeline Review, Follow-Ups & Admin, Strategy Session, debrief rows, post-meeting follow-ups).

### Cell Formatting Rules
- Font: Calibri, size 10 throughout
- Day headers: bold, size 10, theme fill (copied from prior file)
- Account rows: not bold, no fill (unless yellow)
- All cells: `wrap_text=True`, `vertical="top"`
- No icons, emoji, or special characters in any cell value

---

## Step 6: Surface Email Follow-Ups

After building the day-by-day account list, scan email results and append any open threads that don't map to a field visit as a call or note — typically on Friday's list or as a Monday morning task.

Examples:
- Quote sent 5+ days ago with no reply → add as "(call)" to that account's day
- Inbound inquiry from a new account → add to Monday or Friday call block

---

## Step 7: Save and Confirm

Save file to `Planning/Week XX - Itinerary MM.DD.YYYY.xlsx` where:
- `XX` = ISO week number (e.g., 26)
- `MM.DD.YYYY` = Monday's date (e.g., 06.22.2026)

Confirm with user:
> "Itinerary saved to `Planning/Week 26 - Itinerary 06.22.2026.xlsx`
> 
> Mon: Lehigh Valley (8 accounts) | Tue: Bensalem/Bristol (9) | Wed: Montgomery County (9) | Thu: Upper Bucks (8) | Fri: Office/Calls (12)
> 
> Yellow rows: [count] accounts with featured vendor opportunities."

---

## MCP Dependencies

| Data | MCP | Tool |
|------|-----|------|
| Pipeline | salesforce | `sf_get_pipeline` |
| Account contacts | salesforce | `sf_get_account` |
| Open tasks | work-mcp | `list_tasks` |
| Calendar | calendar-mcp | `calendar_get_events` |
| Email follow-ups | retool-email | `get_recent_emails`, `search_emails` |

---

## Notes

- Always copy prior week's file as base — never rebuild from scratch (preserves theme fills)
- The Details column format is: `[Vendor] - [Product] ($Amount Stage) — [Contact] ([Phone]) — [Action]`
- Keep Details to one line where possible; use wrap for longer entries
- Internal activity rows (huddles, admin, debrief) are never highlighted yellow
- Friday is always office/NEPA calls unless a field anchor exists
