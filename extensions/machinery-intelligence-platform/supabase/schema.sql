-- Used Machinery Intelligence Platform — Supabase (Postgres) schema
-- MVP scope: manual listing capture (no live scraping yet), full Pricing &
-- Profitability module, customer intake, Salesforce linkage fields.

create extension if not exists "pgcrypto";

create table if not exists manufacturers (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  is_mam_represented boolean not null default false,
  reputation_score numeric,
  created_at timestamptz not null default now()
);

create table if not exists machine_types (
  id uuid primary key default gen_random_uuid(),
  name text not null unique
);

insert into machine_types (name) values
  ('Laser'), ('Press Brake'), ('Plasma Table'), ('Waterjet'),
  ('Tube Laser'), ('Punch'), ('Saw'), ('Welding'), ('Other')
on conflict (name) do nothing;

create table if not exists machine_models (
  id uuid primary key default gen_random_uuid(),
  manufacturer_id uuid references manufacturers(id) on delete set null,
  machine_type_id uuid references machine_types(id) on delete set null,
  model_name text not null,
  axis_count integer,
  tonnage numeric,
  bed_length numeric,
  wattage numeric,
  typical_options jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists sources (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  base_url text,
  scrape_method text not null default 'manual'
    check (scrape_method in ('api', 'scrape', 'manual_feed', 'manual')),
  tos_status text not null default 'unknown'
    check (tos_status in ('permitted', 'restricted', 'unknown')),
  scrape_frequency text,
  created_at timestamptz not null default now()
);

-- MVP: every scraping-capable source starts disabled for automated crawling
-- until ToS review flips tos_status to 'permitted'. See ARCHITECTURE.md §5.
insert into sources (name, scrape_method, tos_status) values
  ('Mid Atlantic Machinery (own inventory)', 'manual_feed', 'permitted'),
  ('Machinio', 'manual', 'unknown'),
  ('Exapro', 'manual', 'unknown'),
  ('MachineTools.com', 'manual', 'unknown'),
  ('Revelation Machinery', 'manual', 'unknown'),
  ('KD Capital', 'manual', 'unknown'),
  ('Prestige Equipment', 'manual', 'unknown')
on conflict (name) do nothing;

create table if not exists customers (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  salesforce_account_id text,
  salesforce_contact_id text,
  created_at timestamptz not null default now()
);

create table if not exists listings (
  id uuid primary key default gen_random_uuid(),
  source_id uuid references sources(id) on delete set null,
  machine_model_id uuid references machine_models(id) on delete set null,
  -- Denormalized against machine_model_id: manual capture (MVP) often won't
  -- have a matched machine_model row yet, but the matching engine still
  -- needs a hard machine-type filter, and searches.machine_type_id is set
  -- directly from the intake form the same way.
  machine_type_id uuid references machine_types(id) on delete set null,
  manufacturer_raw_text text,
  model_raw_text text,
  year integer,
  wattage numeric,
  tonnage numeric,
  bed_length numeric,
  axis integer,
  condition text,
  location text,
  asking_price numeric not null,
  listing_url text,
  acquisition_type text not null default 'dealer_inventory'
    check (acquisition_type in ('dealer_inventory', 'direct_purchase')),
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  is_active boolean not null default true,
  raw_payload jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_listings_machine_model on listings(machine_model_id);
create index if not exists idx_listings_machine_type on listings(machine_type_id);
create index if not exists idx_listings_active on listings(is_active);

create table if not exists listing_options (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid not null references listings(id) on delete cascade,
  option_name text not null,
  is_must_have boolean not null default false,
  is_nice_to_have boolean not null default false
);

create table if not exists listing_price_history (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid not null references listings(id) on delete cascade,
  price numeric not null,
  observed_at timestamptz not null default now()
);
create index if not exists idx_price_history_listing on listing_price_history(listing_id, observed_at desc);

create table if not exists searches (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid references customers(id) on delete set null,
  machine_type_id uuid references machine_types(id) on delete set null,
  manufacturer_preference text,
  model text,
  min_year integer,
  min_wattage numeric,
  tonnage numeric,
  bed_length numeric,
  axis integer,
  location text,
  budget_max numeric,
  must_have_options jsonb not null default '[]'::jsonb,
  nice_to_have_options jsonb not null default '[]'::jsonb,
  notes text,
  is_saved boolean not null default true,
  alert_enabled boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists search_matches (
  id uuid primary key default gen_random_uuid(),
  search_id uuid not null references searches(id) on delete cascade,
  listing_id uuid not null references listings(id) on delete cascade,
  match_score numeric not null,
  fit_rating text not null check (fit_rating in ('strong', 'moderate', 'weak')),
  ai_rationale text,
  created_at timestamptz not null default now(),
  unique (search_id, listing_id)
);

create table if not exists alerts (
  id uuid primary key default gen_random_uuid(),
  search_id uuid not null references searches(id) on delete cascade,
  listing_id uuid references listings(id) on delete set null,
  alert_type text not null check (alert_type in ('new_match', 'price_drop')),
  channel text not null default 'email' check (channel in ('email', 'sms')),
  sent_at timestamptz
);

create table if not exists valuations (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid not null references listings(id) on delete cascade,
  fair_market_low numeric not null,
  fair_market_high numeric not null,
  fair_market_point numeric generated always as ((fair_market_low + fair_market_high) / 2) stored,
  confidence text not null default 'medium' check (confidence in ('high', 'medium', 'low')),
  method_version text,
  computed_at timestamptz not null default now()
);
create index if not exists idx_valuations_listing on valuations(listing_id, computed_at desc);

create table if not exists settings_margin_bands (
  id uuid primary key default gen_random_uuid(),
  min_margin_pct numeric not null,
  max_margin_pct numeric,
  label text not null,
  color text not null,
  sort_order integer not null
);

insert into settings_margin_bands (min_margin_pct, max_margin_pct, label, color, sort_order) values
  (0.20, null, 'Excellent', 'green', 1),
  (0.15, 0.20, 'Very Good', 'teal', 2),
  (0.10, 0.15, 'Good', 'yellow', 3),
  (0.07, 0.10, 'Thin', 'orange', 4),
  (-999, 0.07, 'Low Margin', 'red', 5)
on conflict do nothing;

create table if not exists deals (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid references listings(id) on delete set null,
  customer_id uuid references customers(id) on delete set null,
  salesforce_opportunity_id text,
  status text not null default 'open' check (status in ('open', 'won', 'lost')),
  freight_estimate numeric,
  rigging_estimate numeric,
  created_at timestamptz not null default now()
);

create table if not exists pricing_snapshots (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid references listings(id) on delete cascade,
  deal_id uuid references deals(id) on delete set null,
  dealer_asking_price numeric not null,
  dealer_discount_pct numeric,
  dealer_discount_fixed numeric,
  net_cost numeric not null,
  net_cost_override numeric,
  quote_price numeric not null,
  gross_profit numeric not null,
  gross_margin_pct numeric not null,
  markup_pct numeric not null,
  ideal_quote_price numeric,
  target_selling_price numeric,
  walkaway_price numeric,
  created_at timestamptz not null default now(),
  created_by text
);
create index if not exists idx_pricing_snapshots_listing on pricing_snapshots(listing_id, created_at desc);
