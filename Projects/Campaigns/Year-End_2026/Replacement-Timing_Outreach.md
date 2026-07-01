# Campaign: Replacement-Timing Outreach

*Part of the [[2026-H2_Sales_Plan]] · Phase: rolling Jul–Dec · Created June 30, 2026*

## One-Liner
A rolling, always-on cadence that triggers off EDA/UCC equipment data — reaching out to accounts the month their machine crosses its replacement window or their lease nears expiry, segmented by machine type.

## Why Now
The single best predictor of a machine sale is the age and lease status of what the customer already owns. EDA/UCC data exposes both. Instead of guessing, this campaign lets the **data set the timing**: when a plasma table passes ~10 years, or a lease drops under 180 days, that account surfaces and gets a tailored, well-timed touch.

## Target Segment
- **Primary:** Tier 2 accounts — replacement-due, no open opp yet. The conversion engine of the half.
- **Trigger sources (refresh monthly):**
  - Lease expiry buckets — `/customer-intel alerts` (CRITICAL ≤90d, HIGH ≤180d, MEDIUM ≤365d).
  - Equipment age past lifecycle window — `score-key-accounts.py` replacement-urgency component + `/customer-intel scan [machine-type]`.
- **Segment by machine type** so messaging is specific: plasma, fiber laser, press brake, saw, etc. (see the Equipment Lifecycle Clock in the customer-intel skill).

## Messaging Pillars
1. **Specific to their asset** — "Your [builder] [model] dates to [year]…" (proven pattern in `.scripts/outreach-alltra-randy-2026-07-02.ps1`).
2. **Where the tech has moved** — fiber displacing plasma/CO2, automation, throughput, uptime.
3. **Low-pressure, time-anchored** — tie to a nearby demo/factory-rep visit when one exists.

## Cadence (bi-weekly per account, evergreen)
| Touch | Timing | Channel | Content |
|-------|--------|---------|---------|
| 1 | Trigger month | Email (draft → Outlook) | Replacement trigger: their machine age / lease window |
| 2 | +1 week | Call | Open discovery — current pain, throughput, plans |
| 3 | +2 weeks | Visit offer / demo invite | Territory sweep or pair with a vendor demo day |

If no response after the 3-touch cycle, drop the account to Tier 3 (quarterly radar) and re-surface when the next EDA trigger fires.

## Segmentation Cheat-Sheet (replacement window low-bound)
| Machine | Window | Trigger conversation |
|---------|--------|----------------------|
| Plasma | 8–12 yr | Fiber laser displacement |
| CO2 laser | 8–12 yr | Fiber ROI compelling ~7 yr |
| Fiber (early gen) | 10–15 yr | Higher wattage + automation |
| Press brake (mech) | 15–25 yr | CNC/servo conversation at 12–15 yr |
| Saw | 12+ yr | Throughput / automation |

## Execution
- Pull the segment list from `score-key-accounts.py` (Tier 2) + `/customer-intel scan [type]`.
- Draft waves: `/outreach-drafts-custom` → `.scripts/outreach-replacement-[type]-[date].ps1` → **Outlook Drafts (approve, never auto-send)**.
- Field routing: `/week-itinerary` folds replacement targets into territory sweeps.
- Logging: `[dex]` tags → `/pipeline-review` → `sf-activity-sync.py`.

## Success Indicators
- ≥8 Tier-2 conversions to active discovery in Q3 (ties to `Q3-2026-goal-2`).
- Every ≤180-day lease-expiry account contacted with a documented next step by Dec 31 (ties to `Q4-2026-goal-2`).

## Guardrails
Draft-and-approve only. Verify each expiry/install date against Salesforce before sending (Date Accuracy Protocol).
