---
name: analytics
description: Analytics intelligence for Dot Connector Dispatch (Substack) and DotConnector.ai — weekly snapshots, deep chart analysis, natural language queries, and automated insights via Amplitude.
context: fork
---

## Purpose

Provide analytics intelligence across both web properties. Three modes:

1. **`/analytics`** — Weekly traffic snapshot with insights (default)
2. **`/analytics [chart URL]`** — Deep analysis of a specific Amplitude chart
3. **`/analytics [question]`** — Natural language query (e.g., "why did traffic drop this week?")

---

## Amplitude Projects

| Property | App ID | Notes |
|----------|--------|-------|
| Dot Connector Dispatch (Substack) | **791104** | Newsletter / blog. Amplitude snippet may only cover custom pages, not full Substack. |
| DotConnector.ai (website) | **789539** | Marketing site. Has click tracking, referrer data, session replay, gclid. |

---

## Available Events

### Both Projects (791104 & 789539)

| Event | Key Properties |
|-------|---------------|
| `[Amplitude] Page Viewed` | Page Title, Page URL, Page Path, Page Domain, Page Counter |
| `session_start` (Start Session) | — |

### DotConnector.ai Only (789539)

| Event | Key Properties |
|-------|---------------|
| `[Amplitude] Element Clicked` | Element Text, Element Href, Element Tag, Page Title, Page URL |
| `session_end` (End Session) | — |
| `[Amplitude] Replay Captured` | Session Replay ID |
| `[Amplitude] Page Viewed` (additional) | referrer, referring_domain, gclid |

---

## Mode 1: Weekly Snapshot (`/analytics`)

### Query Process

Use `mcp__claude_ai_Amplitude__query_dataset` or `mcp__claude_ai_Amplitude__query_chart` tools. Set date ranges to:
- **This week:** last 7 days (today minus 6 days through today)
- **Last week:** the 7 days before that (today minus 13 days through today minus 7 days)

### For EACH project (791104 and 789539):

1. **Unique visitors** — Uniques on `[Amplitude] Page Viewed`, this week vs last week
2. **Total page views** — Event count of `[Amplitude] Page Viewed`, this week vs last week
3. **Sessions** — Event count of `session_start`, this week vs last week
4. **Top 5 pages** — `[Amplitude] Page Viewed` grouped by `Page Title`, this week only

### DotConnector.ai only (789539):

5. **Top referral sources** — `[Amplitude] Page Viewed` grouped by `referring_domain`, exclude empty/direct
6. **Top clicked elements** — `[Amplitude] Element Clicked` grouped by `Element Text`, top 5

### Output Format

```markdown
## 📊 Weekly Analytics — Week of [YYYY-MM-DD]

### Dot Connector Dispatch (Substack)

| Metric | This Week | Last Week | Trend |
|--------|-----------|-----------|-------|
| Unique Visitors | X | Y | ↑/↓/→ |
| Page Views | X | Y | ↑/↓/→ |
| Sessions | X | Y | ↑/↓/→ |

**Top Pages:**
1. [page title] — X views
...

---

### DotConnector.ai

| Metric | This Week | Last Week | Trend |
|--------|-----------|-----------|-------|
| Unique Visitors | X | Y | ↑/↓/→ |
| Page Views | X | Y | ↑/↓/→ |
| Sessions | X | Y | ↑/↓/→ |

**Top Pages:**
1. [page title] — X views
...

**Top Referrers:**
1. [domain] — X visits
...

**Top Clicks:**
1. [element text] — X clicks
...

---

### Insights

[3-5 bullet points with interpretation — see Analysis Heuristics below]
```

### Trend Arrows

- More than 10% increase: ↑ (up)
- More than 10% decrease: ↓ (down)
- Within 10% either way: → (flat)

---

## Mode 2: Deep Chart Analysis (`/analytics [chart URL]`)

When the user provides an Amplitude chart URL:

1. **Parse the URL** to identify the chart ID and project
2. **Fetch the chart** using `mcp__claude_ai_Amplitude__query_chart`
3. **Identify the metric and timeframe** from the chart configuration
4. **Cross-reference related metrics** — if one metric dropped, check correlated events
5. **Check for inflection points** — when exactly did the change start?
6. **Look for segment differences** — break down by device, referrer, page to isolate cause

### Output Format for Chart Analysis

```markdown
## 🔍 Chart Analysis

**Chart:** [chart name]
**Timeframe:** [date range]
**Key Metric:** [metric name]

### What Happened
[1-2 sentences: the change observed]

### When It Started
[Specific date/time of inflection point]

### Likely Causes
1. [Hypothesis with supporting data]
2. [Alternative explanation]
3. [External factor if relevant]

### Segments Affected
[Which segments show the change vs. which don't]

### Recommended Actions
1. [Specific next step]
2. [Investigation to run]
```

---

## Mode 3: Natural Language Query (`/analytics [question]`)

When the user asks a question like:
- "Why did traffic drop this week?"
- "Which pages are converting best?"
- "Where is my DotConnector.ai traffic coming from?"
- "How is my latest Substack post performing?"

### Process

1. **Determine which project(s)** the question relates to (or query both)
2. **Translate to Amplitude queries** — use `query_dataset` with appropriate events, filters, and group-bys
3. **Run supporting queries** — if the primary answer raises more questions, run follow-ups automatically
4. **Synthesize a narrative answer** — don't just return data tables; explain what the data means

### Example

User: "Why did DotConnector.ai traffic drop?"
→ Query unique visitors by day for last 14 days (find when drop happened)
→ Query by referring_domain (did a referral source dry up?)
→ Query by Page Path (did a specific page lose traffic?)
→ Synthesize: "Traffic dropped 24% starting March 18. The drop is concentrated in direct visits — referral traffic from Google held steady. This suggests fewer people are typing in the URL directly, possibly because [hypothesis]."

---

## Analysis Heuristics

Apply these interpretation rules when presenting data:

### KPI Metrics (visitor counts, page views, sessions)
- Always show **percentage change** vs. prior period
- Flag anything over ±25% as notable
- If traffic is very low (under 50 visitors/week), note that small changes are not statistically meaningful

### Bar Charts / Top Lists
- Look for **concentrations** — is one page/referrer dominating? That's a dependency risk.
- Look for **gaps** — what's missing that should be there? (e.g., no organic search traffic)
- Look for **new entries** — a referrer appearing for the first time is a signal worth calling out

### Trend Data
- Identify **inflection points** — don't just say "it went down," say when and by how much
- **Cross-reference with known events** — did a Substack article publish that day? Did Don start outreach? Did a LinkedIn post go viral?
- **Separate signal from noise** — at low traffic volumes, day-to-day fluctuation is normal. Week-over-week is more meaningful.

### Connecting to Goals
- Tie insights back to quarterly goals where relevant:
  - Substack traffic → Goal #4 (advisory pipeline, thought leadership)
  - DotConnector.ai traffic → Goal #4 (advisory revenue) and Don Moore's outreach
  - "Clarity Assessment" clicks → product interest, potential leads

---

## Integration with /week-review

During `/week-review`, automatically include the weekly snapshot as a section. Place it after Task Completion and before Meetings.

**For the weekly review, provide a condensed version:**
- 3 bullet points max per property
- Lead with the most important insight, not the raw numbers
- Frame as "up/down/flat and here's why it matters"
- Connect to quarterly goals

Example:
> **DotConnector.ai:** 13 visitors (↓24% from 17). All homepage traffic, no inner pages converting. "Clarity Assessment" CTA got 1 click — watch this metric as Don's April outreach begins.

---

## Integration with /daily-plan

If the user published a Substack article in the last 48 hours, proactively mention its performance in the daily plan. Use a quick query for that article's page views and unique readers.

---

## MCP Dependencies

| Integration | MCP Server | Tools Used |
|-------------|------------|------------|
| Amplitude | claude_ai_Amplitude | `query_dataset`, `query_chart`, `search`, `get_context`, `get_event_properties`, `get_charts` |

**Context management note:** Amplitude MCP uses ~5-10% of context window. This is acceptable. Do not load additional analytics MCPs unless explicitly requested.

---

## Track Usage (Silent)

Update `System/usage_log.md` to mark analytics as used.
