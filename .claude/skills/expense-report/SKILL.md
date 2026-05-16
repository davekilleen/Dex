---
name: expense-report
description: Sweep Gmail for receipts in a date range, curate via XLSX, push y-marked rows to Odoo, build a merged PDF with cover + per-expense detail + embedded receipts.
model_hint: standard
---

Two-phase Futuroid expense reporting skill. Built for David's biweekly cadence: ~30 candidates → ~15 reimbursable → one auditable PDF + Odoo records with attached receipts.

## Usage

- `/expense-report collect <start> <end>` — Phase 1. Sweep Gmail for receipts/invoices in the date range, dedupe against existing Odoo records, write a curation XLSX to `~/Downloads/`.
- `/expense-report finalize <xlsx_path>` — Phase 2. Read y-marked rows, push each to Odoo as hr.expense, attach the receipt (PDF or HTML-rendered) as ir.attachment, build merged PDF report.
- `/expense-report` (no args) — interactive: ask which phase + arguments.

Dates: `YYYY-MM-DD`. Default output paths follow `Futuroid_Expenses_<start>_to_<end>.xlsx` and `Futuroid_Expenses_Report_<start>_to_<end>.pdf`.

## Arguments

- `$ACTION`: `collect` | `finalize` | (empty = ask)
- `$ARG1`: start date (collect) or xlsx path (finalize)
- `$ARG2`: end date (collect) or pdf path (finalize, optional)

## Pre-flight

Before running either phase:

1. Verify the `expense-report-venv` virtualenv at `/tmp/expense-report-venv` is healthy. If missing, recreate:
   ```bash
   python3 -m venv /tmp/expense-report-venv
   source /tmp/expense-report-venv/bin/activate
   pip install openpyxl weasyprint pillow reportlab pypdf
   ```
2. Confirm `gog` is installed (`which gog` returns a path) and authenticated for `david.orban@gmail.com` with the `mine` client. If not, run `gog auth login david.orban@gmail.com --client mine` first.
3. Confirm `.mcp.json` has working `odoo-mcp` env vars (`ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_API_KEY`).
4. Make sure Odoo currency rates are fresh — they auto-sync daily via ECB on all three companies, but stale rates yield wrong USD totals. `mcp__odoo-mcp__search_records` on `res.currency.rate` with `domain=[["company_id","=",1]]` to spot-check the date.

## Phase 1 — collect

Run:
```bash
source /tmp/expense-report-venv/bin/activate
python /Users/davidorban/Dev/Dex/.claude/skills/expense-report/scripts/collect.py <start> <end>
```

What it does:
- Issues 4 Gmail searches (SaaS, travel, generic receipt-tagged, expensify-forwards).
- Fetches each unique message, parses vendor / amount / currency / date / receipt # from the text body.
- Drops `Fwd:` and `Re:` (originals only), failed-payment notifications, past-due reminders, sub-€0.50 dust.
- Dedupes against every receipt # already in Odoo (across the whole hr.expense history for David).
- Writes the candidate XLSX with a blank `Include` column.

After the script runs: open the XLSX, mark `y` next to each reimbursable row, save. Refer to `[[expense_inclusion_pattern]]` memory for the TEG inclusion rule — AI tools/business SaaS/active business travel are reimbursable; personal travel/SaaS/family/infra are not. Travel is **context-dependent** (Booking Bucharest for a confirmed meeting = include; Airbnb Abu Dhabi vacation = exclude). When in doubt, ask David.

Spot-check before finalizing:
- Look for vendor-name oddities (sender domain instead of brand name — `davidorban.com` actually = Canva, etc.). Edit the Vendor column inline if needed.
- Watch for invoice-vs-receipt amount mismatches (e.g., Grok shows list $300 but actual paid $99 after discount). The `Amount` column comes from the email body's first plausible total — verify on the actual receipt for any line that looks high.

## Phase 2 — finalize

Run:
```bash
source /tmp/expense-report-venv/bin/activate
python /Users/davidorban/Dev/Dex/.claude/skills/expense-report/scripts/finalize.py <xlsx>
```

What it does:
- Reads y rows from the XLSX.
- For each row: creates `hr.expense` (employee_id=2 David, company_id=1 Futuroid, payment_mode=own_account, currency from row, product_id from vendor categorization).
- Categorisation rule (see `_lib.categorize`): AI tool keywords → `AI Tools` (id=8); travel keywords → `Travel & Accommodation` (id=2); SaaS keywords (Odoo, Vercel, X Developer) → `Communication` (id=5); else `Communication` default.
- Fetches the original Gmail message. If a PDF attachment exists, attaches it as `ir.attachment`. If not, renders the HTML body to PDF via WeasyPrint and attaches that.
- Builds the merged PDF: cover page (table + per-currency totals + USD grand total via live ECB rates) → per-expense detail page + receipt page(s).
- Writes the PDF to `~/Downloads/Futuroid_Expenses_Report_<start>_to_<end>.pdf`.

After running, the user should:
- Open the PDF and skim for missing/broken receipts.
- Submit via Odoo's expense workflow (the records are in draft state, employee submission is manual).

## Known gotchas

1. **WeasyPrint shutdown segfault on macOS** — Pango/HarfBuzz fails to release a font resource during CPython finalisers. Both scripts end with `_lib.safe_exit(0)` which calls `os._exit` to bypass interpreter shutdown. PDF is already on disk by then, so output is safe. If you remove that line, expect a "Python quit unexpectedly" dialog.

2. **Cohort separation by Odoo ID, not by date** — the original Expensify-forward pipeline date-stamped everything with the forward date, not the underlying receipt date. So when you build *separate* reports for non-overlapping periods, filter by `id < N` where N = first id of the next batch, instead of by date range. The skill encodes this for new batches via `_lib.get_max_expense_id`.

3. **Receipt # dedupe is exact** — patterns like `#1234-5678`. If a vendor uses a different format (no dashes, or letters), it won't be deduped. Spot-check for suspicious-looking dupes in the curation XLSX.

4. **Booking confirmations vs receipts** — same hotel stay often produces two emails on the same day: "🛄 Thanks! Your booking is confirmed at X" + "This is your receipt". Different amounts (the confirmation often shows expected total incl. taxes; the receipt is what was actually charged). Both currently survive the dedupe (different subjects). Pick one — usually the receipt.

5. **Amount-correction workflow** — if a y-marked row has the wrong amount (Grok-style discount, partial refund, exchange-rate timing), edit the XLSX Amount column **before** running finalize. Post-finalize corrections require editing the hr.expense record in Odoo directly via MCP `update_record` and re-running build_pdf.

6. **Two-Way reuse of cached attachments** — finalize uses Odoo's ir.attachment as the source of truth for the PDF. If you manually attach a paper receipt photo (taxi receipt, etc.) to an hr.expense in Odoo, the next PDF re-build picks it up automatically.

## Memory

- [[expense_inclusion_pattern]] — what's TEG-reimbursable vs personal
- [[user_profile]] — David reports to Michael at TEG; Futuroid expense reports are the TEG reimbursement vehicle

## Files

- `scripts/_lib.py` — shared helpers (Gmail OAuth, Odoo session, HTML/image → PDF, vendor categorisation, ECB rate lookup, receipt # extraction, safe_exit)
- `scripts/collect.py` — Phase 1
- `scripts/finalize.py` — Phase 2
