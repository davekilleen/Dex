---
name: customer-intel
description: Deep customer intelligence from EDA Data UCC-1 filings — equipment inventory, lease expiration tracking, purchase pattern analysis, and strategic outreach timing
role_groups: [sales]
jtbd: |
  You need to know exactly what machines your customers and prospects have on their floor,
  when their leases expire (= cash flow freed up), what they're likely to buy next, and
  the precise moment to pick up the phone. EDA Data's UCC-1 filings give you all of this.
  This skill turns raw filing data into a measurable sales advantage.
time_investment: "15-30 minutes per company (2 minutes for alerts/scans)"
---

# Customer Intelligence — EDA Data Analysis

Convert UCC-1 machine tool financing records into a complete picture of any company's
equipment floor, buying cycles, cash flow windows, and your best next move.

## Usage

- `/customer-intel [company-name]` — Full intelligence analysis for a specific company
- `/customer-intel prospect [company-name]` — Research a prospect not yet in your vault
- `/customer-intel alerts` — All accounts with lease expirations in the next 12 months
- `/customer-intel scan [state or industry]` — Find new prospects from recent EDA filings
- `/customer-intel update [company-name]` — Refresh EDA data for an existing account

## Arguments

$COMPANY: Company name to research (partial match OK — try the most distinctive part)
$MODE: `prospect`, `alerts`, `scan`, or `update` (default: full company analysis)
$REGION: For scan mode — state abbreviation, metro area name, or industry keyword

---

## Step 0: Route by Mode

- **`alerts` mode** → Skip to Step 6: Lease Expiration Dashboard
- **`scan` mode** → Skip to Step 7: Territory Discovery
- **All other modes** → Continue to Step 1

---

## Step 1: Load Existing Vault Context

Before touching EDA Data, gather what Dex already knows:

1. Check `People/Companies/` for an existing company page — read it fully if found
2. Check `People/External/` for contacts at this company
3. Search `Projects/` for open or archived opportunities with this company name
4. Note: existing equipment mentions, last touch date, open quotes, relationship notes

If no company page exists, create a stub now at `People/Companies/[Company_Name].md` with:
```markdown
---
name: [Company Name]
type: customer|prospect
industry: [infer from context]
location: [City, State if known]
---

# [Company Name]

## EDA Intelligence
*Not yet populated — run `/customer-intel [company]` to build*
```

Summarize what you already know before pulling EDA data. Tell the user what you found.

---

## Step 2: Pull EDA Data

Attempt to fetch UCC-1 filings from EDA Data using Scrapling.

**Try direct fetch first:**
```
scrapling_stealthy_fetch(url="https://edadata.com/search/[COMPANY_NAME_URL_ENCODED]")
```

Try these URL patterns if the first fails:
- `https://edadata.com/?s=[company]`
- `https://edadata.com/search/?debtor=[company]`
- `https://edadata.com/results?q=[company]`

Pass `css_selector=".results, table, .filings, .records, main"` to extract the relevant content.

**If the site requires login or URL pattern is unknown:**

Tell the user exactly what to do:
```
To pull EDA Data for [Company], I need the filing records. Quickest option:

1. Go to edadata.com and search for "[Company]"
2. Select all results on the page (Ctrl+A / Cmd+A), copy (Ctrl+C / Cmd+C)
3. Paste it here

Alternatively, copy the URL of your search results and I'll fetch it directly.

What to look for: filing date, equipment description (collateral), secured party
(lender), and expiration/lapse date for each filing.
```

Accept data in ANY format — copied table, raw text, CSV, screenshot description, or
manual entry. The analysis works regardless of how the data arrives.

---

## Step 3: Parse Each UCC-1 Filing

For every filing record, extract and calculate:

**Extract these fields:**

| Field | What It Means | How to Parse |
|-------|--------------|--------------|
| Filing Date | When they bought/leased | Use as equipment acquisition date |
| Lapse/Expiration Date | When financing ends | If absent, estimate: Filing Date + 5 years |
| Secured Party | The lender/lessor | Wells Fargo, Key Equipment Finance, NMHG Financial, etc. |
| Collateral Description | The actual equipment | Extract manufacturer, machine type, model, serial if present |
| Amendment/Continuation | Filing was modified | Continuation = lease extended; Amendment = terms changed |
| Filing State | Where equipment is | Confirms physical location |

**Equipment Name Parsing — Extract:**
- **Manufacturer:** Trumpf, Amada, Bystronic, Mazak, Haas, Okuma, Cincinnati, LVD,
  Prima Power, Salvagnini, Mitsubishi, Fanuc, Hypertherm, Lincoln, Miller, etc.
- **Machine Type:** fiber laser, CO2 laser, tube laser, press brake, punch press,
  turret punch, VMC, turning center, lathe, plasma cutter, waterjet, robot, automation, etc.
- **Model:** If present in collateral text — capture it exactly
- **Specificity flag:** "All equipment" = generic (can't identify exact machine) vs.
  "Trumpf TruLaser 3030 Fiber 6kW S/N 12345" = specific

**Calculate for each record:**
- **Age:** `[Today] - [Filing Date]` → years and months
- **Months to Lapse:** `[Lapse Date] - [Today]` → positive = time remaining, negative = already lapsed
- **Status:**
  - 🔴 **EXPIRING** — 0 to 3 months remaining (act immediately)
  - 🟡 **APPROACHING** — 3 to 12 months remaining (schedule outreach now)
  - 🟢 **ACTIVE** — 12+ months remaining (on radar)
  - ⚫ **LAPSED** — expiration date passed (financing ended; machine may be paid off or replaced)

---

## Step 4: Analyze Purchase Patterns

With all filings parsed, identify these patterns across the full filing history:

### Buying Frequency
- First EDA appearance: what year? What equipment? (establishes when they became a machine tool buyer)
- Total machines financed over time
- Average interval between purchases (months)
- Trend: **Accelerating** (intervals shrinking) | **Stable** | **Slowing** (intervals growing)

### Equipment Evolution
- Technology progression: e.g., "CO2 laser (2014) → fiber laser (2019) → added tube laser (2022)"
- Capacity trajectory: are machines getting larger/higher-powered over time?
- Process expansion: are they adding new processes (e.g., added bending after laser)?
- Brand loyalty score: same manufacturer every time? Switching brands?

### Financing Patterns
- Primary lender(s): same lender consistently = strong relationship there
- Lender switching: may indicate credit changes or lender-driven deals
- Term patterns: if multiple filings visible, infer average lease term
- Cash purchase signal: long gap between filings with known activity = possible cash buyer

### Seasonal Buying Pattern
Look at the month of each filing date. Fabricators cluster purchases around:
- **Oct-Dec:** Year-end tax planning (Section 179, bonus depreciation)
- **Jan-Feb:** New budget year approval
- **May-Jun:** Mid-year capital utilization

State the company's apparent buying season with confidence level.

### Expansion Signals (Bullish)
- Multiple filings within 12 months = rapid growth mode
- Increasingly capable equipment (higher wattage, larger bed, more axes)
- Adding complementary processes (laser + press brake + automation)

### Caution Signals
- UCC amendments with lender changes = possible financial restructuring
- No new filings in 4+ years despite known activity = may have switched to cash, or slowing growth
- Multiple lenders simultaneously = complex financing situation

---

## Step 5: Generate the Intelligence Profile

Write the full analysis into the company page. Replace or update the `## EDA Intelligence`
section with:

```markdown
## EDA Intelligence
*Last updated: [YYYY-MM-DD] | Source: EDA Data UCC-1 Filings*

### Equipment Inventory
| Equipment | Manufacturer | Model | Filed | Lease Expires | Status | Financed By |
|-----------|-------------|-------|-------|---------------|--------|-------------|
| [Type] | [Brand] | [Model or —] | [Date] | [Date] | 🟢/🟡/🔴/⚫ | [Lender] |

**Fleet summary:**
- [X] machines in EDA history | [Y] active financing | [Z] lapsed/paid off
- Est. floor value: $[Range] (based on typical new pricing for equipment types found)
- Fleet age: Newest [X yr] | Oldest [X yr] | Average [X yr]

---

### Purchase Pattern
- **EDA history start:** [Year] — [First equipment]
- **Buying cadence:** Every ~[X] months ([trend: accelerating/stable/slowing])
- **Buying season:** [Q4/Q1/etc.] — based on [X] of [Y] purchases occurring [Month range]
- **Technology path:** [e.g., "CO2 laser (2014) → 3kW fiber (2019) → 6kW fiber + tube laser (2022)"]
- **Brand loyalty:** [e.g., "Exclusively Trumpf" / "Mix of Amada and LVD" / "No clear preference"]
- **Financing:** [e.g., "Consistently uses Key Equipment Finance"]
- **Growth signal:** [Accelerating / Stable / Contracting] — [one sentence rationale]

---

### Cash Flow & Timing Opportunities
| Window | Equipment | Lease Ends | Action Date | Priority |
|--------|-----------|-----------|-------------|----------|
| 🔴 Now | [Machine] | [Date] | Call this week | Immediate |
| 🟡 Q[X] | [Machine] | [Date] | Reach out by [Date] | Schedule |
| 🟢 [Year] | [Machine] | [Date] | Log for later | On radar |

**Next predicted purchase window:** [Date range] — [rationale: cadence pattern + lease timing]

---

### Strategic Recommendations

**[Recommendation 1 — most urgent]**
[Specific action grounded in the data. E.g., "Their 2019 Trumpf fiber lease lapses in 4 months.
With fiber laser technology now 40% more productive at the same power level, this is a strong
upgrade conversation. Call before they decide to re-finance the existing machine."]

**[Recommendation 2 — equipment gap or expansion]**
[E.g., "They have a fiber laser but no press brake in EDA history — every sheet they cut has
to go somewhere. Either they're job-shopping forming work or using an old brake not financed
through EDA. Worth asking."]

**[Recommendation 3 — competitive or financial insight]**
[E.g., "Two filings in 18 months signals growth. This is the right time to get in front of
their next capital purchase before they go to bid."]

---

### Outreach Calendar
- **[Date]:** [Specific action] — [Rationale]
- **[Date]:** [Specific action] — [Rationale]
- **[Date]:** [Specific action] — [Rationale]
```

After writing the profile, run auto-link to connect people mentions:
```bash
node .scripts/auto-link-people.cjs People/Companies/[Company_Name].md
```

---

## Step 6 (Alerts Mode): Lease Expiration Dashboard

When invoked as `/customer-intel alerts`:

1. Scan every file in `People/Companies/` that contains an `## EDA Intelligence` section
2. Extract all equipment rows and their Lease Expires dates
3. Calculate days until expiration for each
4. Sort by urgency (soonest first)

Display:

```
## Equipment Lease Expiration Report — [DATE]

### 🔴 Expiring in 0–3 Months — Call This Week
| Company | Equipment | Expires | Days Left | Primary Contact | Last Touch |
|---------|-----------|---------|-----------|-----------------|------------|

### 🟡 Expiring in 3–12 Months — Schedule Outreach Now
| Company | Equipment | Expires | Suggested Outreach Date | Primary Contact |
|---------|-----------|---------|------------------------|-----------------|

### 🟢 On Radar — 12–24 Months
| Company | Equipment | Expires | Predicted Purchase Window |
|---------|-----------|---------|--------------------------|

---
**Summary:** [X] tracked expirations across [Y] accounts
**Revenue opportunity:** ~$[Range] in potential equipment replacements/upgrades in the next 12 months
**Most urgent:** [Company] — [Equipment] expires [DATE] ([X] days)
```

Offer:
- "Create follow-up tasks for all 🔴 accounts?" 
- "Export this as a PDF for your sales manager?"
- "Run `/customer-intel [company]` on any of these for a full profile?"

---

## Step 7 (Scan Mode): Territory Prospect Discovery

When invoked as `/customer-intel scan [region]`:

Use Scrapling to search EDA Data for recent filings in the target area. Search for:
- New filings in the past 90 days (fresh purchases = great time to introduce yourself)
- Companies with multiple recent filings (rapid growth)
- Companies not already in `People/Companies/` (net-new prospects)

```
scrapling_stealthy_fetch(url="https://edadata.com/search?state=[STATE]&days=90")
```

For each new company found:
1. Check if they're already in your vault — skip if yes
2. Evaluate: first-time buyer vs. repeat buyer?
3. Note equipment type — does it match what you sell?
4. Flag growth signals (multiple filings, increasing machine capability)

Present findings:
```
## Territory Scan — [Region] — [DATE]
Found [X] companies with recent machine tool financing not yet in your vault.

### Top New Prospects

**[Company Name]** — [City, State]
- Just financed: [Equipment] ([Date])
- Signal: [First machine tool purchase / Third purchase in 18 months / etc.]
- Why interesting: [Specific rationale]
- Suggested approach: [Cold call? LinkedIn? Trade association? Reference from nearby customer?]
- Est. deal potential: [Size range based on equipment type purchased]

[Repeat for each prospect]
```

Offer to create stub company pages and prospecting tasks for the top candidates.

---

## Step 8: Task Creation

After any analysis (Steps 5, 6, or 7), offer to create tasks:

```
Based on this analysis, here are suggested tasks:

1. [URGENT - P0] Call [Contact] at [Company] — [Equipment] lease expires [DATE] ([X] days)
   Pillar: Account Management

2. [PLANNED - P1] Outreach to [Company] — lease expiration window opens [DATE]
   Pillar: Pipeline & Revenue

3. [RESEARCH - P2] Build upgrade proposal: [Old Machine] → [Recommended New Machine]
   Pillar: Product & Market Knowledge

Create tasks? Reply with numbers (e.g., "1 3"), "all", or "skip"
```

---

## Sales Intelligence Frameworks

Apply these frameworks once you have EDA data for your accounts.

### The Equipment Lifecycle Clock
Use equipment age (filing date to today) to time upgrade conversations:

| Equipment Type | Typical Replacement Window | Upgrade Trigger |
|---------------|---------------------------|-----------------|
| CO2 Laser Cutter | 8–12 years | Fiber ROI becomes compelling at ~7 years |
| Fiber Laser (early gen) | 10–15 years | Higher wattage economics; automation integration |
| Press Brake (mechanical) | 15–25 years | CNC retrofit conversation at 12–15 years |
| Press Brake (CNC) | 12–18 years | Servo/ATC; EuroBend-style automation |
| Turret Punch Press | 15–20 years | Combo punch/laser often replaces aging turrets |
| Turning Center | 10–15 years (precision) | Spindle hours and accuracy drift |
| VMC | 10–15 years | Multi-pallet; 5-axis upgrade path |
| Plasma Cutter | 8–12 years | Fiber laser displacement (if cutting <1") |
| Tube Laser | 10–15 years | Wattage and automation upgrades |

Cross-reference age against these windows to prioritize your conversations.

### The Complementary Machine Matrix
When a customer has Machine A, they often need Machine B. Drive account expansion:

| They Have | They Often Need Next | Why |
|-----------|---------------------|-----|
| Fiber laser (flat) | Press brake | Cutting creates bending demand immediately |
| Fiber laser (flat) | Tube/structural laser | Natural progression to 3D cutting |
| Press brake | Welding robot | Formed parts need joining; labor pressure |
| Turret punch | Press brake | Punched blanks still need forming |
| Any CNC | Automation / pallet system | Volume growth → lights-out pressure |
| VMC | Turning center | Rotational parts need a lathe |
| Manual processes | First CNC | Labor cost and accuracy forcing the move |
| Laser + brake | Automated material handling | Throughput bottleneck shifts to material flow |

Use their current EDA inventory to identify which conversation to start.

### The Three Strongest Conversation Triggers
1. **Lease ending (6–12 months out):**
   > "Your [machine] financing is winding down in the next several months — a lot of shops
   > use that timing to evaluate what's next rather than re-upping on older technology.
   > Worth a conversation?"

2. **Equipment age milestone (cross-reference lifecycle clock above):**
   > "Your [machine] is [X] years old now — at that point, most shops start looking at
   > what a current-generation machine would do for throughput. Has that come up for you?"

3. **New filing detected (they just bought something):**
   > "I saw you recently added a [machine] — how's it fitting in? Any bottlenecks it's
   > created that we might be able to help with?"

### The Buying Season Hypothesis
Fabricators cluster purchases around:
- **Oct–Dec:** Section 179 / bonus depreciation — year-end tax planning
- **Jan–Feb:** New fiscal year, fresh capital budget approved
- **May–Jun:** Mid-year budget reviews, use-it-or-lose-it capital

After building EDA profiles on 5+ accounts, look for your territory's dominant buying season.
Time your proposal deliveries to land 30–60 days before their typical filing month.

### Lookalike Prospecting Formula
Take your best customer's EDA profile:
- Equipment types they have → search EDA for other companies with the same equipment
- Their industry/size → filter by SIC code or NAICS if EDA supports it
- Their geography → expand to adjacent metro areas

Companies with similar equipment profiles face the same challenges → highest-probability new prospects.
Run `/customer-intel scan` with the equipment type as a keyword to find them.

### The Financial Health Signal
Active, recent UCC-1 filings tell you:
- **Creditworthy** — a lender approved them
- **Growth mode** — they're investing in capacity
- **Equipment financers** — comfortable with the leasing model (your deal is easier)

No recent filings (in a company you know is active) could mean: cash purchases, growth pause,
or financial difficulty. Worth a casual question before investing heavily in a proposal.

### The Competitive Intelligence Layer
UCC-1 collateral descriptions often include brand names. Track:
- Customers buying competitor equipment → understand why; position alternatives for next time
- Prospects buying only competitor equipment → conquest targets with displacement story
- Mixed-brand shops → open to options; focus on total cost of ownership

Track "brand affinity" in each company's EDA profile. It turns your customer list into a
competitive landscape map.

### Annual Account Planning Integration
After running `/customer-intel` for each account, you have the inputs for a data-driven
annual account plan:
- Current equipment floor → what are they doing today?
- Lease schedule → when will they have capital to spend?
- Technology gaps → where can you add value?
- Buying history → what's the realistic deal size and frequency?
- Purchase season → when should you have your proposal ready?

This turns EDA data into a multi-year revenue forecast per account.
Run this alongside `/pipeline-sync` at the start of each quarter.

---

## Integration with Other Skills

- **`/customer-intel alerts`** — Run weekly (every Monday) to stay ahead of expiring leases
- **`/meeting-prep [company]`** — EDA intelligence in the company page auto-surfaces here
- **`/pipeline-sync`** — EDA expiration timing informs expected close dates in Salesforce
- **`/pipeline-review`** — Cross-reference pipeline stage against lease expiration urgency
- **`/account-plan [company]`** — EDA data is the foundation of a credible account plan
