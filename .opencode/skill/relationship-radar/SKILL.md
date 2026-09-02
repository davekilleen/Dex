---
name: relationship-radar
description: "Spot the relationships going cold — people you were in regular contact with and haven't touched in a while, and important contacts who are slipping — ranked by how stale each has become, so you can reconnect before it costs you. Use when the user says 'who should I reach out to', 'who am I losing touch with', 'who's going cold', 'who needs attention', or during a weekly review. Also use proactively when someone important hasn't come up in a long time. Not for prepping a specific upcoming meeting; use `meeting-prep`. Not for specific promises you owe people; use `commitments`."
---

# /relationship-radar

Relationships decay quietly — the person you spoke to every week three months ago just… stopped coming up. This surfaces who is going cold while you can still do something about it, ranked by how long it's been.

**Honest scope (read this):** today the radar reads the signal that exists now — each person page's recorded **last-interaction date**, corroborated by **meeting recency**. It does *not* yet have the entity engine's automatic "temperature / what's cooling" surface — that isn't built. So the radar is only as good as the last-interaction dates on your person pages, and it says so plainly when the signal is thin rather than inventing a coldness score. When the entity temperature surface ships, this skill gets richer; it does not block on it.

---

## Step 1 — Load the people signal

Call `build_people_index` (writes/refreshes `System/People_Index.json`) and read its `people[]`: each carries `name`, `role`, `company`, `status`, and `last_interaction` (a date, or empty). Drop anyone whose `status` marks them archived/inactive — the radar is about live relationships.

If the index is empty or absent, say so and point to the fix (add person pages, or set last-interaction dates) — do not present an empty radar as "all healthy."

## Step 2 — Rank by staleness

For each remaining person with a `last_interaction` date, compute **days since last contact** (today − last_interaction) and bucket by these stated heuristics (not a hidden score):

- **Going cold** — ~30–60 days since contact. Was a real relationship; the gap is opening.
- **Slipping** — 60+ days. At risk of going dark.
- **Warm** — under ~30 days. Not shown unless asked; the radar is about what needs attention.

Weight toward people whose `role`/`company` signals they matter (a key customer, a manager, a close collaborator) — surface those first even at a shorter gap. Say *why* each surfaced ("was weekly in Q1, nothing for 7 weeks").

## Step 3 — Handle the people you can't assess (degrade honestly)

People with **no last-interaction date** can't be ranked by it. Don't guess a coldness. Instead:
- Try to corroborate from **meeting recency** — scan recent meetings for their name/email and use the latest as an interaction proxy, saying that's what you did.
- If there's still no signal, list them under **"Can't assess — no interaction date recorded"** and offer to backfill (a last-interaction date on the page, or running `process-meetings`). Never silently drop them and never fake a date.

## Step 4 — Present the radar

Show a short ranked list, most-stale-and-important first. Each row, by name: person (and role/company), **last contact** (date + "N days ago"), the bucket, and one line of why it matters. Refer to people by name, never by id or raw file path. If genuinely nobody is cold, say that plainly — a quiet radar is a real, good result, not a reason to pad the list.

## Step 5 — Optional reconnect (confirm-gated, never automatic)

Offer — don't impose — to turn a surfaced person into a "reach out to {name}" task. **Nothing is created without the user's per-item say-so.** For each one they pick, call Work MCP `create_task` (infer the pillar per the CLAUDE.md rules; carry the person's name + last-contact into the task), then **read back the created task IDs** before reporting. If they just want to see the radar, stop after Step 4.

---

## Quality bar

A good radar surfaces the *right* people — real, still-active relationships that have genuinely gone quiet — ranked so the most costly gaps are on top, each with a plain reason. It is honest about thin signal (missing dates, no meetings) instead of manufacturing a temperature, and it never creates a task the user didn't confirm.

## Anti-patterns (do not do these)

- **Inventing a coldness score** for people with no interaction date — surface them as "can't assess," don't fake it.
- **Claiming the entity "temperature" surface** — it isn't built; use last-interaction + meeting recency and say so.
- **Padding a quiet radar** with warm contacts or vague "maybe reconnect with…" filler.
- **Auto-creating reach-out tasks** without per-item confirmation, or reporting tasks as created without their IDs.
- Surfacing archived/inactive people as if the relationship were live.

## Degradation

- `build_people_index` unavailable / empty → say so and point to the fix (add person pages / dates); never present an empty radar as "all good."
- A person has no `last_interaction` → corroborate via meeting recency, else list under "can't assess"; never guess.
- Meetings dir absent → skip the recency corroboration silently; the last-interaction pass alone still runs.
- Entity temperature surface (not yet built) → simply not used; the skill works on today's signal.

---

## Track Usage (Silent)

Update `System/usage_log.md` to mark relationship-radar as used. **Analytics (Silent):** call `track_event` with event_name `relationship_radar_run` and property `surfaced_count` (how many people surfaced — no names, no roles). Fires only if the user opted into analytics; no action if it returns "analytics_disabled".
