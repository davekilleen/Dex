# Used Machinery Intelligence Platform

Sales-decision tool for used sheet metal / structural steel fabrication machinery: customer requirement intake, fair market valuation, and a Pricing & Profitability module for live quoting.

**Status:** Core MVP loop is usable end to end — intake a customer requirement, get ranked matches, price the deal. See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full system architecture, database schema, scraping strategy, API design, AI workflow, and the Pricing & Profitability module spec.

Confirmed decisions (see ARCHITECTURE.md §15): scraping starts manual-only per source until ToS review; MVP matching/UI prioritizes Press Brakes, Plasma, Lasers, and Saws; margin targets are 20% target / 15% negotiable / 10–12% floor; notifications are email-only for MVP.

## What's built so far

- **Pricing & Profitability engine** (`src/lib/pricing.ts`) — net cost, gross profit/margin/markup, Quick Pricing Scenarios table, Pricing Indicators (vs. dealer asking, vs. fair market value), Profitability rating (editable margin bands), Competitiveness rating, and the Negotiation Assistant (ideal quote / target selling price / lowest acceptable price). Fully unit tested against the worked example in the spec (`src/lib/pricing.test.ts`, 29 tests).
- **Rule-based matching engine** (`src/lib/matching.ts`) — scores a saved customer search against every active listing (machine type as a hard filter, must-have options as a hard filter, everything else — manufacturer, year, wattage, tonnage, bed length, axis, budget, location — as tolerance-scaled partial credit so near-misses still surface, ranked lower). 7 unit tests (`src/lib/matching.test.ts`). AI-based fit rationale is a V2 item; this is rules only.
- **Database schema** (`supabase/schema.sql`) — manufacturers, machine types/models, sources (with per-source ToS gating), listings (now including a direct `machine_type_id` for matching), price history, searches, search_matches, valuations, margin-band settings, deals, and pricing snapshots.
- **API routes** — `/api/searches` (customer intake), `/api/searches/[id]/refresh` + `/api/searches/[id]/matches` (matching engine), `/api/listings/manual-capture` (manual paste-URL listing entry), `/api/machine-types`, `/api/pricing` (persist a pricing snapshot), `/api/pricing/scenarios` (quick scenario table), `/api/deals`, `/api/deals/[id]/push-salesforce` (stub — see below).
- **UI** — customer intake form with machine-type selector (`/intake`) that redirects into ranked results (`/searches/[id]`); a listings browser (`/listings`) and manual add-listing form (`/listings/new`); listing detail page with the full interactive Pricing Panel and always-visible Deal Summary Card (`/listings/[id]`).

## Not yet built (see roadmap in ARCHITECTURE.md)

- Scraping workers, AI valuation/summarization/negotiation rationale, alerts, dashboard.
- **Salesforce push for won deals** — `/api/deals/[id]/push-salesforce` is a stub that returns `501` on purpose. Finishing this needs a Salesforce connected app (`SALESFORCE_CLIENT_ID`, `SALESFORCE_CLIENT_SECRET`, `SALESFORCE_INSTANCE_URL` in `.env.example`) that only the account owner can provision — it's not something to fake with placeholder credentials.

## Applying schema changes to an already-created Supabase project

`schema.sql` uses `create table if not exists`, so re-running it won't add new columns to existing tables. If you already ran an earlier version of this schema, apply this migration once (adds `machine_type_id` to `listings`):

```sql
alter table listings add column if not exists machine_type_id uuid references machine_types(id) on delete set null;
create index if not exists idx_listings_machine_type on listings(machine_type_id);
```

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
