---
name: dex-dashboard
description: "A personal, local page showing how the user is using Dex, what stands out, and one evidence-backed next step. Use when the user says \"show my dashboard\", \"open my Dex dashboard\", \"how am I using Dex\", \"what does my Dex look like\", or \"my Dex stats\". Not for system health checks; use `dex-doctor`. Not for a chat list of unused features; use `dex-level-up`."
---

# /dex-dashboard — Your Dex at a Glance

Build and open one private, local page from the user's real Dex data. Keep the page
evidence-led: the renderer owns the layout; this session authors only the observations
and one next step.

## 1. Collect the dashboard data

`VAULT_PATH` must point to an existing Dex vault. If it is unset or invalid, stop and
ask for the vault path; never guess. Create one unique temporary directory so concurrent
runs cannot collide:

```bash
DASHBOARD_TMP="$(mktemp -d "${TMPDIR:-/tmp}/dex-dashboard.XXXXXX")"
DASHBOARD_DATA="$DASHBOARD_TMP/data.json"
DASHBOARD_OBSERVATIONS="$DASHBOARD_TMP/observations.json"
DASHBOARD_HTML="$DASHBOARD_TMP/dex-dashboard.html"

cd "$VAULT_PATH" && .venv/bin/python core/dashboard/collect.py --vault "$VAULT_PATH" --json > "$DASHBOARD_DATA" 2>/dev/null \
  || python3 core/dashboard/collect.py --vault "$VAULT_PATH" --json > "$DASHBOARD_DATA"
```

If both collector attempts fail, say the dashboard data could not be collected and stop.
Do not render a partial or invented page. Validate that `$DASHBOARD_DATA` is a JSON object,
then read the whole object before writing anything about the user's Dex.

## 2. Author the session-owned content

### Check the planning ladder FIRST

Before writing anything, read the collected `rituals` section (daily plan, week plan,
quarter goals, week priorities). Gaps in Dex's planning ladder outrank every other
observation: a user who has never run a weekly plan or set quarter goals should hear
that — warmly, with the evidence — before anything about meetings or tasks. If a ritual
gap exists, at least one observation must name it, and the next-step suggestion should
usually come from the ladder (e.g. a first `/week-plan`) unless something else is
clearly more urgent.

### Dashboard Observation Quality Bar

Write normally 2–3 short observation paragraphs, and fewer or none when the evidence is
sparse. Every observation must cite a specific number, file, or event present in the
collected data. Connect the evidence to what it means in plain “smart friend” language:
warm, specific, jargon-free, and never scolding. Use absolute dates such as
“July 27, 2026”; never use relative dates such as “today”, “recently”, or “last week”.

Do not:

- write generic praise such as “Great job using Dex!”
- invent a metric; estimated hours saved are **FORBIDDEN**
- make an observation that is not backed by a number, file, or event in the data
- turn a zero into a trend when there is no analytics evidence
- give more than one suggestion

Choose exactly one next-best suggestion. Rank unchecked entries from
`usage.features` against the user's `profile.role` and named `pillars`; choose the
closest practical fit. The `try_prompt` must be ready to paste and must include real
role, pillar, feature, count, or event details from this JSON—not placeholders or
made-up context. If no unchecked feature exists, do not invent one: use a
getting-started or reflection suggestion grounded in the available profile and counts.

Then pick 3–5 unused skills worth recommending — "picked for you", shown on the Journey
tab. Same evidence bar as observations: each `why` must connect the skill to something
real in this JSON (their role, a pillar by name, a ritual gap, a count, an integration).
"Great for staying organized" fails the bar; "You have 64 person pages and 28 meetings
with external people — `/relationship-radar` tells you who's going cold" passes. Prefer
skills adjacent to what they already do; never recommend a skill the data shows they
already use.

Write this exact JSON shape to `$DASHBOARD_OBSERVATIONS`:

```json
{
  "observations": ["Evidence-backed paragraph.", "Evidence-backed paragraph."],
  "suggestion": {
    "title": "One concise next step",
    "why": "Why this fits the user's real role, pillars, and usage.",
    "try_prompt": "A paste-ready prompt built from the user's real data."
  },
  "skill_picks": [
    {"skill": "week-plan", "why": "One sentence grounded in this user's real data."}
  ]
}
```

Validate and re-read the observations JSON. Confirm there are no extra keys, no more
than three observations, exactly one suggestion, at most five skill picks, and no claim
unsupported by the collector JSON.

## 3. Render, inspect, and open

```bash
cd "$VAULT_PATH" && .venv/bin/python core/dashboard/render.py \
  --vault "$VAULT_PATH" \
  --data "$DASHBOARD_DATA" \
  --observations "$DASHBOARD_OBSERVATIONS" \
  --out "$DASHBOARD_HTML" 2>/dev/null \
  || python3 core/dashboard/render.py \
  --vault "$VAULT_PATH" \
  --data "$DASHBOARD_DATA" \
  --observations "$DASHBOARD_OBSERVATIONS" \
  --out "$DASHBOARD_HTML"
```

Read back the rendered HTML before claiming success. Confirm it is non-empty and contains
the `Your Dex` title, every authored observation, and the one suggestion title. Then open it:

```bash
if command -v open >/dev/null 2>&1; then
  open "$DASHBOARD_HTML"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$DASHBOARD_HTML"
else
  echo "$DASHBOARD_HTML"
fi
```

If no opener exists, give the user the local HTML path and say it could not be opened
automatically. Keep the page on this machine; this skill has no sharing path.

## 3b. Interactive settings (only when asked)

If the user asked to *change* settings ("open my settings", "let me toggle things",
"interactive dashboard"), render with `--with-settings` added to the render command, then
start the temporary local server and tell the user the page will close itself:

```bash
cd "$VAULT_PATH" && { .venv/bin/python core/dashboard/server.py --vault "$VAULT_PATH" --html "$DASHBOARD_HTML" --idle-timeout 900 2>/dev/null \
  || python3 core/dashboard/server.py --vault "$VAULT_PATH" --html "$DASHBOARD_HTML" --idle-timeout 900; } &
```

Say one line: the settings page opened in the browser, changes save instantly to their
Dex files, and the page shuts itself down when closed (or after 15 quiet minutes).
Nothing keeps running afterwards. For a plain "show my dashboard", do NOT start the
server — the static page has no settings panel.

## 4. Compare with the previous snapshot

After rendering, inspect only the last two lines of
`System/.dex/dashboard/history.jsonl` with `tail -n 2`. If they are two valid snapshots,
tell the user in one line what changed from the previous snapshot, citing the previous
snapshot's absolute date and exact count differences. If fewer than two snapshots exist,
say nothing about a trend. Never scan the full history for this comparison.

## 5. Degrade truthfully

- No fresh Doctor cache: do not infer health; the page will say “run /dex-doctor for a
  fresh checkup”.
- No `System/analytics_log.jsonl`: skip trend claims. A zero is not proof of no activity.
- Empty or unconfigured vault: lean on getting-started framing and explicit zero counts;
  never fabricate momentum, history, a role, or a pillar.
- A collector section with an `error`: omit claims from that section and keep using
  sections with valid evidence.

## 6. Track usage silently

After a successful render, read `System/usage_log.md`. If a matching unchecked checkbox
for `Dex Dashboard` or `/dex-dashboard` exists, change only its `- [ ]` to `- [x]`.
If no matching checkbox exists, do nothing and do not add one. Never announce this
tracking update to the user.
