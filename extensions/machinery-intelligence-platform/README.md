# Used Machinery Intelligence Platform

Sales-decision tool for used sheet metal / structural steel fabrication machinery: customer requirement intake, fair market valuation, and a Pricing & Profitability module for live quoting.

**Status:** MVP in progress. See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full system architecture, database schema, scraping strategy, API design, AI workflow, and the Pricing & Profitability module spec.

Confirmed decisions (see ARCHITECTURE.md §15): scraping starts manual-only per source until ToS review; MVP matching/UI prioritizes Press Brakes, Plasma, Lasers, and Saws; margin targets are 20% target / 15% negotiable / 10–12% floor; notifications are email-only for MVP.

## What's built so far

- **Pricing & Profitability engine** (`src/lib/pricing.ts`) — net cost, gross profit/margin/markup, Quick Pricing Scenarios table, Pricing Indicators (vs. dealer asking, vs. fair market value), Profitability rating (editable margin bands), Competitiveness rating, and the Negotiation Assistant (ideal quote / target selling price / lowest acceptable price). Fully unit tested against the worked example in the spec (`src/lib/pricing.test.ts`, 29 tests).
- **Database schema** (`supabase/schema.sql`) — manufacturers, machine types/models, sources (with per-source ToS gating), listings, price history, searches, valuations, margin-band settings, deals, and pricing snapshots.
- **API routes** — `/api/searches` (customer intake), `/api/listings/manual-capture` (manual paste-URL listing entry), `/api/pricing` (persist a pricing snapshot), `/api/pricing/scenarios` (quick scenario table), `/api/deals`.
- **UI** — customer intake form (`/intake`), listing detail page with the full interactive Pricing Panel and always-visible Deal Summary Card (`/listings/[id]`).

## Not yet built (see roadmap in ARCHITECTURE.md)

- Scraping workers, matching engine scoring, AI valuation/summarization/negotiation rationale, alerts, dashboard, Salesforce push (the `deals` table has the field for it; the actual Salesforce API call is not wired yet).

## Setup

```bash
cd extensions/machinery-intelligence-platform
npm install
cp .env.example .env.local   # fill in your Supabase project URL + service role key
```

Create the schema in your Supabase project (SQL editor or `psql`):

```bash
psql "$SUPABASE_DB_URL" -f supabase/schema.sql
```

Run the dev server:

```bash
npm run dev
```

## Testing

```bash
npm test          # runs the pricing engine test suite (vitest)
npm run test:watch
npx tsc --noEmit   # typecheck
npm run build      # production build sanity check
```

The pricing engine (`src/lib/pricing.ts`) is the module worth trusting most — it's pure functions with no I/O, so it's fully covered by unit tests independent of Supabase/Next.js being configured. UI and API routes require a real Supabase project (see Setup) to exercise end-to-end.
