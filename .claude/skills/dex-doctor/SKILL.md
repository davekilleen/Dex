---
name: dex-doctor
description: Rigorous whole-system checkup — verifies every Dex feature honestly (working / off / broken / couldn't-check), self-heals what is provably safe, and guides the user only where Dex cannot fix itself. Replaces /health-check.
---

# /dex-doctor — Full System Checkup

Diagnose everything, heal what's safe, guide the user through the rest.

## Purpose

One honest answer to "is my Dex actually working?" Built against the failure modes found
in the July 2026 audit: checks that never ran, checks that probed an easier path than the
real feature, "off" reported as "broken", and background jobs that died silently for
months.

## When to Run

- User asks "is everything working?", "what's broken?", "check my setup"
- Something feels off — features silently not happening
- After an update, migration, or machine change
- User invokes `/dex-doctor` directly

## Cardinal rules

1. **Never report "off" as a problem.** A feature the user never enabled is healthy.
   List it under "Off — that's fine", once, without nagging.
2. **Never hide "couldn't check".** If a probe failed to run, say so prominently. An
   unknown presented as a pass is how watchdogs go blind.
3. **Never claim a heal worked without re-checking it.**
4. **Heal conservatively.** Tier 1 only automatically. Tier 2 only after an explicit yes,
   one item at a time. Tier 3 is always the user's hands. Never delete or overwrite user
   data; never touch credentials.

## Execution

### Step 1: Run the collector (quick mode + safe auto-heals)

```bash
cd "$VAULT_PATH" && .venv/bin/python core/utils/doctor.py --heal 2>/dev/null \
  || python3 core/utils/doctor.py --heal
```

This returns JSON: every check with a verdict (`OK` / `OFF` / `BROKEN` / `UNKNOWN`), any
Tier-1 heals already applied, and an `instruments` block saying whether the doctor itself
ran completely.

**If the collector itself fails to run:** that IS the finding. Report it first, with the
error, and continue with whatever manual checks you can do — do not present a partial
picture as a full one.

### Step 2: Offer the deep scan

Quick mode checks configuration, wiring, and background-job freshness. Deep mode
additionally contacts live services (Granola API, Calendar via EventKit, enabled
integrations). Ask:

> "Quick check done. Want the deep scan too? It contacts your connected services
> (Granola, Calendar) to prove the real query paths work — takes ~30 seconds."

If yes: run with `--deep` and merge results.

### Step 3: Render the report

Order: **instruments first if anything failed**, then BROKEN, then UNKNOWN, then OFF
(one compact line each, labelled "off — that's fine"), then healthy collapsed to a single
line ("✓ N checks healthy"). Fill every displayed count from the collector JSON — use
the current report's `summary` values and `checks` array rather than a hardcoded quick or
deep total, because the check registry can change.

For each BROKEN item: what it means for the user in one plain sentence (what stopped
working, since when if known), then the fix path.

For the **Entity engine** check, keep the rendering short and plain: say whether entity
creation is working, off, or needs attention, include the contact/observation counts,
and call out unresolved verification results or quarantined pages. Mention stale
verification or a stale/missing People index as a follow-up signal.

### Step 4: Heal, tiered

- **Tier 1 (already applied by the collector):** report plainly — "Fixed automatically:
  recreated the missing Ideas folder."
- **Tier 2 (needs a yes):** propose one at a time with the exact action and why it's safe:
  "Your changelog-checker background job is installed but not running. Want me to load it?
  (One command, reversible.)" Apply only on explicit yes, then **re-run that check** and
  confirm from the fresh result.
- **Tier 3 (user's hands):** give exact steps and the right setup skill —
  e.g. "Granola needs an API key: run `/granola-setup`" / "macOS is blocking calendar
  access: System Settings → Privacy & Security → Calendars → enable your terminal app."

### Step 5: Close with the four-bucket summary

```
🩺 Doctor's summary
   Fixed automatically: 2
   Needs your OK:       1  (waiting above)
   Needs your hands:    1  (steps above)
   Healthy:             N · Off (fine): M · Couldn't check: U
```

Here `N`, `M`, and `U` come directly from `summary.ok`, `summary.off`, and
`summary.unknown` in the collector JSON. If everything is healthy: one line — "Everything
checks out. N checks healthy, M features off by choice." No ceremony.

### Step 6: Track usage (silent)

Update `System/usage_log.md` per the usage-tracking convention. If learnings surfaced
(e.g. a check that should exist but doesn't), suggest capturing via `capture_idea`.

## Edge cases

- **Fresh vault, onboarding incomplete:** run anyway but expect many OFFs; say "you're
  early in setup — this is normal" rather than alarming.
- **Non-macOS:** launchd/EventKit checks come back UNKNOWN with a note; don't present
  them as failures.
- **User says "just fix everything":** Tier 1 is already done; walk Tier 2 items one
  confirmation at a time anyway — batch-yes is how wrong heals happen. Tier 3 cannot be
  batched by definition.
- **Repeated BROKEN on the same item across runs:** suggest filing it —
  "this looks like a Dex bug, not your setup; want me to draft a GitHub issue?"

## Related Commands

- `/granola-setup`, `/calendar-setup`, `/enable-semantic-search` — Tier-3 fix paths
- `/dex-update` — often the fix for package/version drift
- `/xray` — understand what the doctor checked and why
