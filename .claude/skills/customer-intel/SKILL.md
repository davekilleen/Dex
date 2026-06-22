---
name: customer-intel
description: Deep customer intelligence from Salesforce Asset records (EDA/UCC data) — equipment inventory, lease expiration tracking, purchase pattern analysis, and strategic outreach timing
role_groups: [sales]
jtbd: |
  You need to know exactly what machines your customers have on their floor, when their
  leases expire (= freed-up cash flow), what they're likely to buy next, and the precise
  moment to pick up the phone. Your EDA Data UCC-1 records are already synced into
  Salesforce as Asset objects. This skill turns that data into a measurable sales advantage.
time_investment: "5-10 minutes per company (instant for alerts)"
---

# Customer Intelligence — Salesforce Asset Analysis

Convert your Salesforce Asset records (EDA/UCC-1 machine tool data) into a complete picture
of any account's equipment floor, buying cycles, cash flow windows, and your best next move.

> **Data source:** Salesforce Asset object — EDA Data UCC-1 filings are already synced here.
> No manual data entry or web scraping needed. Requires `sf_authenticate` to be completed first.

## Usage

- `/customer-intel [company-name]` — Full intelligence profile for a specific account
- `/customer-intel prospect [company-name]` — Research a prospect using their asset history
- `/customer-intel alerts` — All accounts with lease expirations in the next 12 months
- `/customer-intel competitive` — Competitor equipment map across all accounts
- `/customer-intel scan [machine-type]` — Find all accounts with a specific machine type
- `/customer-intel report` — Generate a full time-based report (new activity + expirations)
- `/customer-intel report 60` — Report with 60-day look-back for new activity
- `/customer-intel setup-automation` — Install the monthly auto-report (runs 1st of each month)

## Arguments

$COMPANY: Account name to research (partial match OK)
$MODE: `prospect`, `alerts`, `competitive`, `scan`, `report`, or `setup-automation`
$MACHINE_TYPE: For scan mode — machine type keyword (e.g., "laser", "press brake", "VMC")
$DAYS: For report mode — look-back window in days for new activity (default 30)

---

## Step 0: Route by Mode

- **`alerts` mode** → Skip to Step 6: Lease Expiration Dashboard
- **`competitive` mode** → Skip to Step 7: Competitive Equipment Map
- **`scan` mode** → Skip to Step 8: Machine Type Territory Scan
- **`report` mode** → Skip to Step 9: Time-Based Report
- **`setup-automation` mode** → Skip to Step 10: Monthly Auto-Report
- **All other modes** → Continue to Step 1

---

## Step 1: Load Vault Context

Before pulling Salesforce data, check what Dex already knows:

1. Check `People/Companies/` for an existing company page — read it fully if found
2. Check `People/External/` for contacts at this company
3. Search `Projects/` for open or archived opportunities with this account name
4. Note any existing equipment mentions, last contact, open quotes, relationship notes

If no company page exists, create a stub now at `People/Companies/[Company_Name].md`:
```markdown
---
name: [Company Name]
type: customer|prospect
---

# [Company Name]

## EDA Intelligence
*Not yet populated — run `/customer-intel [company]` to build*
```

---

## Step 2: Pull Salesforce Asset Data

Call `sf_get_account_assets` with the account name:
```
sf_get_account_assets(account_name="[COMPANY]", include_competitor=true)
```

If the account name returns no results, try a shorter version of the name (first word, 
or without "Inc", "LLC", "Corp", etc.).

If still no results, tell the user:
```
No assets found for "[Company]" in Salesforce. This could mean:
1. The account name in SF is slightly different — what's the exact name in Salesforce?
2. No EDA/UCC data has been synced for this account yet
3. They're a prospect not yet in your SF Asset records
```

---

## Step 3: Parse and Structure the Equipment Floor

With asset records in hand, categorize them:

**Our Equipment** (`is_competitor = false`):
- Group by `machine_type`
- For each machine: note model, builder, install date, usage_end_date, urgency rating
- Calculate equipment age: today minus install_date (or purchase_date)

**Competitor Equipment** (`is_competitor = true`):
- List separately — these are conquest and displacement opportunities
- Note which competitor brands they have (builder / ucc_vendor field)
- Note age of competitor machines — old competitor equipment = strongest upgrade conversations

**Urgency Ratings from the API:**
- 🔴 `CRITICAL` — UsageEndDate within 0–90 days (call this week)
- 🟡 `HIGH` — UsageEndDate 90–180 days out (schedule outreach now)
- 🟠 `MEDIUM` — UsageEndDate 180–365 days out (on the calendar)
- 🟢 `LOW` — UsageEndDate 12+ months out (on radar)
- ⚫ `LAPSED` — UsageEndDate passed (financing ended; machine paid off or replaced)

---

## Step 4: Analyze Purchase Patterns

From the full asset history, identify:

### Buying Frequency
- Oldest asset install/purchase date → establishes how long they've been a machine tool buyer
- Count of assets financed over time
- Average interval between purchases (months between consecutive install dates)
- Trend: accelerating (intervals shrinking), stable, or slowing

### Equipment Evolution
- Technology progression: e.g., "CO2 laser (2014) → 3kW fiber (2019) → 6kW fiber (2022)"
- Capacity growth: are machines getting larger/higher-powered?
- Process expansion: adding new process types over time?
- Brand loyalty: always the same builder, or shopping around?

### Sale vs. Lease Split
- What percentage of their equipment is leased vs. purchased outright?
- Leased = UsageEndDate present and Sale_or_Lease = "Lease"
- All-lease shop: highly finance-driven, timing conversations matter enormously
- All-purchase shop: capital budget driven, fiscal year timing matters more

### Seasonal Buying Pattern
Look at the month of install_date / purchase_date across all assets.
Fabricators cluster purchases around:
- **Oct–Dec:** Year-end tax planning (Section 179, bonus depreciation)
- **Jan–Feb:** New fiscal year, fresh capital budget
- **May–Jun:** Mid-year budget utilization

State the account's apparent buying season with confidence level.

---

## Step 5: Generate the Intelligence Profile

Write the full analysis into the company page. Replace or update `## EDA Intelligence`:

```markdown
## EDA Intelligence
*Last updated: [YYYY-MM-DD] | Source: Salesforce Assets (EDA/UCC-1)*

### Our Equipment on Floor
| Machine Type | Model | Builder | Installed | Lease Ends | Status | Sale/Lease |
|-------------|-------|---------|-----------|-----------|--------|-----------|
| [Type] | [Model or —] | [Brand] | [Date] | [Date or —] | 🔴/🟡/🟠/🟢/⚫ | [S/L] |

### Competitor Equipment on Floor
| Machine Type | Model | Competitor | Installed | Lease Ends | Status |
|-------------|-------|-----------|-----------|-----------|--------|
| [Type] | [Model] | [Brand] | [Date] | [Date] | [Urgency] |

**Fleet summary:**
- Our equipment: [X] machines | [Y] active leases | [Z] expiring within 12 months
- Competitor equipment: [X] machines (displacement opportunities)
- Buying pattern: Every ~[X] months | Buying season: [Q4/Q1/etc.] | [Sale/Lease split]
- Technology path: [e.g., "CO2 laser (2014) → 3kW fiber (2019) → tube laser (2022)"]

---

### Cash Flow & Timing Opportunities
| Urgency | Equipment | Lease Ends | Days Left | Action |
|---------|-----------|-----------|-----------|--------|
| 🔴 CRITICAL | [Machine] | [Date] | [X] days | Call this week |
| 🟡 HIGH | [Machine] | [Date] | [X] days | Schedule outreach by [Date] |
| 🟠 MEDIUM | [Machine] | [Date] | [X] days | Calendar reminder for [Date - 90 days] |

**Next predicted purchase window:** [Date range] — [rationale]

---

### Strategic Recommendations

**[Most urgent recommendation]**
[Specific, data-grounded action. E.g., "Their 2019 Trumpf fiber lease ends in 67 days.
Call [Contact] this week — if they haven't already decided to re-finance, this is the
conversation window for an upgrade to the current generation."]

**[Equipment gap or expansion opportunity]**
[E.g., "They have two fiber lasers but no press brake in their asset history — every
sheet they cut goes out for forming. Either they're job-shopping it or using an old
manual brake. Worth asking about their forming bottleneck."]

**[Competitive displacement opportunity]**
[E.g., "Their Amada CO2 laser was installed in 2013 — 13 years old. The fiber ROI
case is compelling now. Their CO2 lease is lapsed, so they own it outright and are
likely thinking about replacement. Best angle: throughput comparison demo."]

---

### Outreach Calendar
- **[Date]:** [Specific action] — [Rationale]
- **[Date]:** [Specific action] — [Rationale]
```

After writing, run auto-link:
```bash
node .scripts/auto-link-people.cjs People/Companies/[Company_Name].md
```

---

## Step 6 (Alerts Mode): Lease Expiration Dashboard

When invoked as `/customer-intel alerts`:

Call `sf_get_assets_expiring_soon(months=12)`.

Display results grouped by urgency:

```
## Equipment Lease Expiration Alert — [DATE]

### 🔴 CRITICAL — Expiring in 0–90 Days (Call This Week)
| Account | Machine Type | Model | Expires | Days Left | Follow-Up Set? |
|---------|-------------|-------|---------|-----------|---------------|

### 🟡 HIGH — Expiring in 90–180 Days (Schedule Now)
| Account | Machine Type | Model | Expires | Days Left | Suggested Outreach |
|---------|-------------|-------|---------|-----------|-------------------|

### 🟠 MEDIUM — Expiring in 180–365 Days (On Calendar)
| Account | Machine Type | Model | Expires | Predicted Purchase Window |
|---------|-------------|-------|---------|--------------------------|

---
Summary: [X] total tracked expirations | [Y] critical | [Z] accounts affected
Estimated pipeline opportunity: ~$[Range] in replacement/upgrade conversations
```

Then offer:
- "Create follow-up tasks for all CRITICAL accounts?"
- "Set follow-up dates directly on these SF Asset records?"
- "Run `/customer-intel [account]` on any of these for a full profile?"

---

## Step 7 (Competitive Mode): Competitor Equipment Map

When invoked as `/customer-intel competitive`:

Call `sf_get_competitor_assets()` for a full picture across all accounts.

Display:
```
## Competitive Equipment Map — [DATE]

### By Competitor Brand
| Brand | # Machines | Accounts | Avg Age | Expiring < 12 Mo |
|-------|-----------|---------|---------|-----------------|

### Highest-Priority Displacement Targets
[Accounts where a competitor machine is old and/or lease expiring — best upgrade conversations]

### Accounts with ONLY Competitor Equipment
[These accounts have never bought from you — conquest targets]
```

---

## Step 8 (Scan Mode): Machine Type Territory Scan

When invoked as `/customer-intel scan [machine-type]`:

Call `sf_search_assets(machine_type="[machine-type]", competitor_only=false)`.

Useful questions this answers:
- "Which of my accounts have a press brake?" → find expansion candidates for lasers
- "Which accounts have CO2 lasers?" → fiber upgrade conversation list
- "Which accounts have Trumpf equipment?" → brand-loyal accounts vs. mixed-brand accounts

Display a summary table and offer to create outreach tasks for the highest-potential accounts.

---

## Step 9 (Report Mode): Time-Based Report

When invoked as `/customer-intel report` or `/customer-intel report [days]`:

### On-Demand Report

Call both:
1. `sf_get_new_assets(days=[DAYS])` — what's been added recently
2. `sf_get_assets_expiring_soon(months=12)` — full lease expiration picture

Then call the standalone report generator via bash to produce and save the markdown file:
```bash
python3 .scripts/customer-intel/generate-report.py --days [DAYS]
```

The script saves the report to `Inbox/Reports/Customer_Intel_YYYY-MM.md` and prints the
path. Read the saved file and present the key highlights:
- Critical expiration count (and list if ≤ 5)
- New equipment/account count
- Any new competitor equipment added

After presenting, offer:
- "Create follow-up tasks for the CRITICAL accounts?"
- "Set up monthly automation so this runs automatically? (`/customer-intel setup-automation`)"

### Prompted time-range variations
- "Show me what's new in the last 60 days" → `--days 60`
- "What leases are expiring in the next 6 months" → use `sf_get_assets_expiring_soon(months=6)`
- "What changed this quarter" → `--days 90`

---

## Step 10 (Setup Automation): Monthly Auto-Report

When invoked as `/customer-intel setup-automation`:

This installs a macOS Launch Agent that runs on the 1st of every month at 8 AM and
auto-generates the customer intelligence report to `Inbox/Reports/`.

Walk the user through:

1. **Confirm they want it:**
   ```
   This will install a background task that auto-generates your Customer Intelligence
   report on the 1st of every month at 8 AM. Reports save to Inbox/Reports/.
   
   Requirements: macOS (uses launchd), Salesforce authenticated, Python 3
   
   Install? (yes / no)
   ```

2. **Run the installer:**
   ```bash
   bash .scripts/customer-intel/install-automation.sh
   ```

3. **Confirm it worked:**
   ```bash
   bash .scripts/customer-intel/install-automation.sh --status
   ```

4. **Offer to run a test report now:**
   ```bash
   bash .scripts/customer-intel/install-automation.sh --run
   ```

5. Report success:
   ```
   ✓ Monthly Customer Intelligence automation installed!
   
   Every month on the 1st, your report will auto-save to Inbox/Reports/.
   
   You'll see files like:
   - Inbox/Reports/Customer_Intel_2026-07.md
   - Inbox/Reports/Customer_Intel_2026-08.md
   
   To check status: `bash .scripts/customer-intel/install-automation.sh --status`
   To run manually: `/customer-intel report`
   To uninstall: `bash .scripts/customer-intel/install-automation.sh --stop`
   ```

**Non-macOS users:** Explain that launchd is macOS-only. For Windows/Linux, suggest a
cron job: `0 8 1 * * cd /path/to/vault && python3 .scripts/customer-intel/generate-report.py`

---

## Step 11: Task Creation

After any analysis, offer to create tasks:

```
Based on this analysis, here are suggested tasks:

1. [URGENT - P0] Call [Contact] at [Company] — [Machine] lease ends in [X] days
   Pillar: Account Management

2. [PLANNED - P1] Outreach to [Company] — upgrade conversation for [Old Machine]
   Pillar: Pipeline & Revenue

3. [RESEARCH - P2] Build displacement proposal: [Competitor Machine] → [Your Product]
   Pillar: Product & Market Knowledge

Create tasks? (1, 2, 3, all, or skip)
```

For CRITICAL items, also offer to update the asset's `FollowUpDate__c` in Salesforce:
```
sf_update_asset(asset_id="[ID]", follow_up_date="[DATE]")
```

---

## Sales Intelligence Frameworks

### The Equipment Lifecycle Clock
Use equipment age (install_date to today) to time upgrade conversations:

| Machine Type | Typical Replacement Window | Best Conversation Trigger |
|-------------|---------------------------|--------------------------|
| CO2 Laser | 8–12 years | Fiber ROI compelling at ~7 years |
| Fiber Laser (early gen) | 10–15 years | Higher wattage; automation integration |
| Press Brake (mechanical) | 15–25 years | CNC/servo conversation at 12–15 years |
| Press Brake (CNC) | 12–18 years | ATC; automation upgrade path |
| Turret Punch Press | 15–20 years | Combo punch/laser replacement |
| Turning Center | 10–15 years | Spindle hours; accuracy drift |
| VMC | 10–15 years | Multi-pallet; 5-axis upgrade |
| Plasma Cutter | 8–12 years | Fiber laser displacement |
| Tube/Structural Laser | 10–15 years | Wattage and automation upgrades |

### The Complementary Machine Matrix
When an account has Machine A, they often need Machine B next:

| They Have | They Often Need | Why |
|-----------|----------------|-----|
| Fiber laser (flat) | Press brake | Cutting creates bending demand |
| Fiber laser (flat) | Tube laser | Natural 3D cutting progression |
| Press brake | Welding robot | Formed parts need joining |
| Turret punch | Press brake | Punched blanks need forming |
| Any CNC | Pallet automation | Volume growth → lights-out pressure |
| VMC | Turning center | Rotational parts need a lathe |

### The Three Strongest Conversation Triggers
1. **Lease ending (6–12 months out):**
   > "Your [machine] financing wraps up in the next several months — a lot of shops use
   > that window to evaluate what's next rather than re-upping on older technology."

2. **Equipment age milestone:**
   > "Your [machine] is [X] years old — at that point, most shops start looking at what
   > a current-generation machine would do for throughput. Has that come up?"

3. **Competitor equipment aging:**
   > "I noticed you have a [competitor machine] that's getting up there in age. We've
   > helped a few shops in similar situations make the switch — worth a quick comparison?"

### Buying Season Hypothesis
After analyzing 5+ accounts, look for your territory's dominant buying season.
Time proposal deliveries to land 30–60 days before their typical purchase month.

### The Financial Health Signal
Active, recent asset records signal creditworthiness and growth mode — a good buyer.
Accounts with no recent assets (stale data) warrant a gentle probe before large proposals.

---

## Integration with Other Skills

- **`/customer-intel alerts`** — Run every Monday morning for weekly lease expiration review
- **`/customer-intel report`** — On-demand time-based report (new activity + expirations)
- **`/customer-intel setup-automation`** — Install monthly auto-report (1st of each month)
- **`/meeting-prep [company]`** — EDA Intelligence in the company page surfaces automatically
- **`/pipeline-sync`** — Asset expiration timing informs expected close dates in Salesforce
- **`/pipeline-review`** — Cross-reference open opportunities against lease urgency

## Monthly Report Automation

The report generator (`generate-report.py`) runs headless — no Dex session needed.
Install it once with `/customer-intel setup-automation`, then every month on the 1st
a fresh report appears in `Inbox/Reports/Customer_Intel_YYYY-MM.md` automatically.

**What the monthly report covers:**
- 🔴 CRITICAL leases expiring in 0–90 days (act now)
- 🟡 HIGH leases expiring in 90–180 days (schedule)
- 🟠 MEDIUM leases expiring in 180–365 days (calendar)
- New equipment records added in the past 30 days
- New accounts that appeared in the asset records
- New competitor equipment tracked

**Manual triggers (any time):**
```bash
# Generate now (saves to Inbox/Reports/)
python3 .scripts/customer-intel/generate-report.py

# Custom look-back (60 days of new activity)
python3 .scripts/customer-intel/generate-report.py --days 60

# Print to terminal instead of saving
python3 .scripts/customer-intel/generate-report.py --stdout

# Check automation status
bash .scripts/customer-intel/install-automation.sh --status
```
