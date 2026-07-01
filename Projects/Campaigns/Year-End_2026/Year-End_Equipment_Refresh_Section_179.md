# Campaign: Year-End Equipment Refresh / Section 179

*Part of the [[2026-H2_Sales_Plan]] · Phase: Q4 close push · Created June 30, 2026*

## One-Liner
Use the Section 179 tax deduction and year-end budget-flush window to push replacement-due Tier 1 + Tier 2 accounts to a purchase decision before December 31.

## Why Now
Section 179 lets businesses expense qualifying equipment in the year it's placed in service. For a fab shop weighing a new plasma table, laser, or press brake, buying before Dec 31 can mean a large same-year deduction. Combined with budget-flush ("use it or lose it") and tax planning, **Oct–Dec is the strongest close window of the year.** Tie the machine they already need to the deadline that makes it cheaper now.

## Target Segment
- **Primary:** Tier 1 accounts with an open opp that has stalled in Quoting/Favorable (give them a reason to decide).
- **Secondary:** Tier 2 replacement-due accounts (aging equipment past lifecycle window, or lease expiring ≤180 days) — pull from [[Key_Accounts_H2-2026]].
- **Build the list:** `python .scripts/customer-intel/score-key-accounts.py` then filter to T1 (open, non-advanced stage) + T2; cross-check lease expiries with `/customer-intel alerts`.

## Messaging Pillars
1. **Deadline math** — "Placed in service by 12/31 to deduct this tax year." (Always: "check with your accountant.")
2. **The machine they already need** — anchor to their specific aging/expiring asset, not a generic pitch.
3. **Lead time reality** — order now so it installs before year-end; slots fill up.

## Cadence (6–8 weeks, Oct–mid Dec)
| Touch | Timing | Channel | Content |
|-------|--------|---------|---------|
| 1 | Early Oct | Email (draft → Outlook) | Section 179 intro + their specific machine/opp |
| 2 | +1 week | Call | Gauge interest, answer tax/financing questions |
| 3 | +2 weeks | Demo / visit | Territory day or factory rep; confirm config |
| 4 | Early Nov | Email | Lead-time warning — "order by X to install by 12/31" |
| 5 | Mid Nov | Call / meeting | Drive to PO; financing options |
| 6 | Late Nov | Final email | Last-call before year-end close |

Tier 2 runs a lighter 3-touch version (email trigger → call → demo invite).

## Execution
- Draft waves: `/outreach-drafts-custom` → `.scripts/outreach-section179-[date].ps1` → **Outlook Drafts (approve, never auto-send)**.
- Field routing: `/week-itinerary` sweeps target accounts by territory, anchored on any booked demos.
- Activity logging: tag touches `[dex]` on project pages → `/pipeline-review` → `sf-activity-sync.py`.

## Success Indicators
- ≥12 Tier-1 opps reach Negotiation/Won in Q4 (ties to `Q4-2026-goal-1`).
- Every targeted account has a logged next step + decision date.

## Guardrails
Never quote a specific tax outcome — always defer to the customer's accountant. All email stays draft-and-approve.
