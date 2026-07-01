# Campaign: Vendor Demo-Day & Competitive Displacement

*Part of the [[2026-H2_Sales_Plan]] · Phase: event-driven, Jul–Dec · Created June 30, 2026*

## One-Liner
Event-driven outreach built around featured-vendor demos, factory-rep visits, and training courses — used both to advance Tier 1 deals and to plant displacement seeds at Tier 3 accounts running aging competitor equipment.

## Why Now
A factory rep in the area or a live demo is a **reason to call that isn't a sales pitch** — it lowers the barrier to a meeting and creates urgency ("he's only here Thursday"). It's also the most credible way to start a competitive-displacement conversation: get the prospect in front of the machine. The ALLtra/Randy wave (`.scripts/outreach-alltra-randy-2026-07-02.ps1`) is the proven template.

## Target Segment
- **Tier 1** with an open opp tied to that vendor — use the visit to close.
- **Tier 3 + Tier 2** running **aging competitor equipment** — `/customer-intel competitive` builds the displacement map; `score-key-accounts.py` competitive-displacement component flags them.
- **Geography matters:** cluster invites around where the rep/demo actually is (territory day), per the in-area pattern.

## Messaging Pillars
1. **The rep is local — limited window** — "Randy from ALLtra will be in [area] Thursday 7/2."
2. **No-pressure look / sample cuts** — easy yes; benchmark their current machine.
3. **For displacement:** "see how far the tech has moved since you bought your [competitor machine]."

## Cadence (per event)
| Touch | Timing | Channel | Content |
|-------|--------|---------|---------|
| 1 | T-2 weeks | Email (draft → Outlook) | Vendor-in-area invite, segmented Tier 1 (active deal) vs Tier 2/3 (displacement) |
| 2 | T-1 week | Call | Confirm interest, lock a window |
| 3 | Event day | Demo / visit | Walk the machine, sample parts, answer factory questions |
| 4 | T+3 days | Email/call | Follow-up: recap + next step (quote, second visit, config) |

## Event Pipeline (fill in as scheduled)
| Vendor / Event | Date | Area | Anchor accounts |
|----------------|------|------|-----------------|
| ALLtra (Randy) plasma | Thu 7/2/2026 | Lehigh Valley / Hazleton | SMF Truck, Gambone, Delaware Valley Steel, Michelman, Kelly Iron |
| TRUMPF fiber / demo | TBD | — | Tier 1 laser deals |
| _add as booked_ | | | |

## Execution
- Build the invite list: `/customer-intel competitive` (displacement) + Tier 1 vendor-matched opps.
- Draft waves: `/outreach-drafts-custom` → `.scripts/outreach-[vendor]-[date].ps1`, segmented Tier 1 vs displacement — **Outlook Drafts, approve, never auto-send**.
- Field routing: `/week-itinerary` anchors the week on the demo location and sweeps nearby accounts.
- Logging: `[dex]` tags → `/pipeline-review` → `sf-activity-sync.py`.

## Success Indicators
- ≥6 vendor demos / factory-rep visits completed in Q3 (ties to `Q3-2026-goal-3`).
- ≥2 year-end demo days executed in Q4 (ties to `Q4-2026-goal-3`).
- Displacement conversations opened at competitor-equipment accounts.

## Guardrails
Draft-and-approve only. Keep invites geographically honest (only invite accounts actually near the rep's route).
