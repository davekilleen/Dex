# Campaigns — Year-End 2026

Campaign playbook for the [[2026-H2_Sales_Plan]] (Jul–Dec 2026). Each brief carries its own target segment, messaging, and multi-touch cadence. All outreach is **draft-and-approve** — drafts land in Outlook, nothing auto-sends.

| Campaign | Window | Tiers | Trigger |
|----------|--------|-------|---------|
| [[Year-End_Equipment_Refresh_Section_179]] | Q4 (Oct–Dec) | T1 + T2 | Section 179 / year-end tax + budget-flush |
| [[Replacement-Timing_Outreach]] | Rolling Jul–Dec | T2 | EDA lease-expiry / equipment age, by machine type |
| [[Vendor_Demo_Day_Competitive_Displacement]] | Event-driven | T1 + T3 | Factory rep in area / featured demo / displacement map |

## How they fit the weekly loop
`/week-plan` → `/week-itinerary` → **run the due outreach wave** (`/outreach-drafts-custom`) → `/process-meetings` → `/pipeline-review`.

## Shared mechanics
- **Target lists** come from `python .scripts/customer-intel/score-key-accounts.py` → [[Key_Accounts_H2-2026]], plus `/customer-intel` modes (`alerts`, `scan`, `competitive`).
- **Draft generation:** `/outreach-drafts-custom` → `.scripts/outreach-[campaign]-[date].ps1` → Outlook Drafts.
- **Field routing:** `/week-itinerary` → `Planning/Week NN - Itinerary MM.DD.YYYY.xlsx`.
- **Activity logging:** `[dex]` tags on project pages → `/pipeline-review` → `sf-activity-sync.py` (never `sf_create_task` directly).
