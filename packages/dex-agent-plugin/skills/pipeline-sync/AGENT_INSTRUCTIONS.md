# Pipeline Sync - Agent Instructions

You are gathering and diffing pipeline data for the user. You have all MCP tools. Do the heavy read/diff work here and return a **compact structured report**. Do NOT write to Pipedrive, and do NOT edit any markdown. All writes and confirmations happen back in the main conversation.

**Mode:** `{{MODE}}` - one of `reconcile` (default), `map`, `discover`.

---

## Common context (all modes)

1. Read `System/integrations/pipedrive.yaml` for `tracker_path` (default `04-Projects/Pipeline_Tracker.md`), `stage_mapping` and `owner_mapping`.
2. Read the tracker file in full. Parse:
   - The active pipeline table rows (deal name, account, value, probability, owner, stage phrase, next action, due).
   - Any per-deal detail blocks; extract any existing `**Pipedrive deal:** <id>` lines.
   - Any totals row (gross, weighted), if the tracker keeps one.
3. Read `pipedrive_get_mapping()` to see which focus deals already map to a Pipedrive deal id.

A "focus deal" = a row in the tracker's active pipeline table. Any emerging/watch-list table is **not** synced unless asked.

---

## Mode: reconcile

For every focus deal that has a mapped Pipedrive deal id:

1. Call `pipedrive_get_pipeline_snapshot(deal_ids=[...all mapped ids...])` (one call).
2. For each deal, compare tracker vs Pipedrive on these fields:
   - **value** (normalise: tracker "£250k" -> 250000; compare to Pipedrive `value`)
   - **probability** (tracker "60%" -> 60 vs Pipedrive `probability`; note Pipedrive may report null if deal probability isn't enabled - flag as "not tracked in CRM" rather than a diff)
   - **stage** (map tracker stage phrase -> expected `stage_id` via `stage_mapping`; compare to Pipedrive `stage_id`. If no mapping exists, report "unmapped stage" not a diff)
   - **owner** (map tracker owner name -> `user_id` via `owner_mapping`; compare to Pipedrive `owner_id`)
   - **expected_close_date** (only if the tracker carries a date)
3. Also: if the tracker prints totals, independently recompute gross + weighted from the rows and compare - flag any arithmetic drift.

**Return:**
```json
{
  "mode": "reconcile",
  "fetched_at": "...",
  "drift": [
    {"deal": "Platform Migration", "account": "Acme", "deal_id": 123,
     "field": "value", "tracker": "£250k", "pipedrive": "£200k"}
  ],
  "unmapped_focus_deals": ["Initech Data Warehouse"],
  "crm_not_tracked": [{"deal":"Platform Migration","field":"probability","note":"deal probability disabled in CRM"}],
  "totals_check": {"gross_printed":"£1.2M","gross_computed":"£1.2M","ok":true},
  "fetch_errors": []
}
```
Keep it tight - only rows that actually differ go in `drift`.

---

## Mode: map

For each active focus deal **without** a mapped Pipedrive id:

1. Derive an org search term from the account name; optionally `pipedrive_find_org(query)` to get an `org_id`.
2. `pipedrive_find_deal(query=<deal/account terms>, org_id=<if found>)`.
3. Return up to 3 candidate matches per focus deal with enough detail for the user to pick.

**Return:**
```json
{
  "mode": "map",
  "to_map": [
    {"dex_key": "Acme/Platform Migration", "account": "Acme",
     "candidates": [{"deal_id":123,"title":"Platform Migration","org_name":"Acme","value":200000,"stage_name":"Proposal"}]}
  ],
  "no_candidates": ["Initech/Data Warehouse"]
}
```
Do not save mappings here - the conversation confirms each, then calls `pipedrive_save_mapping`.

---

## Mode: discover

1. `pipedrive_list_deals(status="open", limit=100)`.
2. Exclude any whose id is already in the mapping cache.
3. Return the remainder so the conversation can ask whether to track them.

**Return:**
```json
{
  "mode": "discover",
  "untracked_open_deals": [
    {"deal_id": 456, "title": "...", "org_name": "...", "value": 120000, "stage_name": "...", "owner_name": "..."}
  ]
}
```

---

## Rules

- **Read-only.** Never call `pipedrive_add_deal_note`, `pipedrive_add_deal_activity`, `pipedrive_update_deal`, `pipedrive_create_deal`, `pipedrive_create_org`, or edit markdown. (`pipedrive_save_mapping` writes only the local cache and is allowed only if the orchestrator explicitly tells you to in map mode - otherwise leave it to the conversation.)
- If any MCP call fails, capture it in a `*_errors` list and continue - never error out to the user.
- Normalise money/percent carefully so you don't report false drift (e.g. "£2.7M" = 2700000; "£100k placeholder" = 100000 with a `placeholder: true` note).
- Be conservative: when unsure whether something is a real diff (missing mapping, placeholder value, CRM field disabled), classify it as a note, not drift.
