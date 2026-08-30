---
name: create-skill
description: "Author a new Dex skill — a reusable `/command` — that actually fires and passes the quality bar. Runs a collision check, classifies the shape, writes a router-grade description, generates the real package (SKILL.md + evals), and grades it with `skill-score` before calling it done. Use when the user says 'make a skill', 'I want a /command for X', 'turn this into a skill'. A skill the user builds for themselves is saved as `-custom` (protected from updates) and coached, never blocked; a first-party skill is held to the hard gate. Not for connecting an external tool; use `create-mcp`. Not for grading a skill that already exists; use `skill-score`."
---

# Create a Skill

Author a skill the way the router and a real user will experience it: it must **fire when it should** (the description is the router) and **do the job safely and well when it fires** (the body is a contract, not a how-to essay). This skill runs a real authoring sequence — collision → classify → contract → generate → validate → score — and does not declare done until `skill-score` has graded the package.

Governing principle: **hard on Core, gentle on the user's own creations.** A first-party (Core) skill must pass `skill-score ≥ 85` to ship — a hard gate we hold ourselves to. A skill the user writes for themselves is *coached, never blocked*: show the score, name the one change that would make it fire, offer to make it — but always create/keep their skill if they want it.

Compose, don't fork: `anthropic-skill-creator` (vendored) is the general skill-authoring guide; the Dex-specific delta lives in `references/dex-skill-standard.md`. Read that reference before generating the package.

---

## Step 1 — Get intent

Ask the user for:

```
1. A short name (e.g. "meeting-notes", "board-update") — hyphens, no spaces
2. What it should do for you, in 1–2 sentences
3. When you'd want it to fire — the phrases you'd actually say
```

Point 3 is not optional — it is the raw material for the WHEN trigger. If the user only gives 1–2, ask for the trigger phrases before continuing.

## Step 2 — Determine origin

- **User skill** (the default in an end-user vault): the user is building this for themselves. It is authored under `{name}-custom/` and is **coached, never blocked**. Do NOT let the user add `-custom` themselves — you append it automatically.
- **First-party / Core skill** (authoring inside the Dex repo, to ship to everyone): authored under its real `{name}/` and **held to the hard gate** (`skill-score ≥ 85`).

Infer from context; if genuinely unsure, ask one line: "Is this just for you, or something Dex should ship to everyone?"

## Step 3 — Collision check (before writing anything)

The most common failure is a skill the router can't tell apart from one that already exists. Check first — run `skill-score --all` (its portfolio mode lists every routing collision and the nearest neighbor of each skill; it owns and runs the scorer, so you don't re-implement it here).

Read the `routing collisions` list and find the nearest neighbor to the intended job. Then decide:

- **This is a genuinely new job** → note the nearest neighbor; its name goes in the anti-trigger (Step 5).
- **A skill with this exact job already exists** → do NOT create a duplicate. Either **edit that skill in place** (overwrite its `SKILL.md`, keep its name — never a `-name-2` or `-v2` fork) or, if it's a Core skill the user wants to customize, save the user's version as `{name}-custom` alongside it (both stay invocable) and hand off to the conflict-resolution flow. A suffixed fork of a job that already exists fragments discoverability and is not allowed.
- **A near neighbor exists but the jobs are distinct** → sharpen this skill's outcome and add an anti-trigger naming that neighbor so the router can disambiguate.

If the scorer can't run (no `python3`), fall back to reading the descriptions in `.claude/skills/*/SKILL.md` by hand and say you did so — never skip the collision check silently.

## Step 4 — Classify the shape

Pick the shape(s) — a skill can be more than one — because it decides the contract the body must carry (see `references/dex-skill-standard.md`):

- **workflow** — a multi-step process over the vault
- **setup / integration** — connects a tool; must be idempotent + carry a re-run/repair path
- **dependent** — needs a tool/feature; must detect → explain → fix-path when it's missing
- **generative** — produces user-facing content; must name a quality bar + anti-slop rules + inspect real output before claiming success
- **script-bearing** — ships a script; the script needs a `--diagnose`/`--dry-run` and machine-readable output
- **multi-session / stateful** — state kept in a file and sized to a single session

## Step 5 — Write the description (the router)

This is the highest-leverage line in the whole package. Follow the template in `references/dex-skill-standard.md`. It must:

1. **Lead with the outcome** in plain language — what the user gets, no internal function/file names.
2. **Carry a WHEN trigger** — concrete situations AND the user phrases from Step 1 ("Use when the user says…").
3. **Carry an anti-trigger** — "Not for X; use Y" naming the real nearest neighbor from Step 3.

## Step 6 — Generate the package

Create the folder — `{name}-custom/` for a user skill, `{name}/` for a first-party skill — and write:

- **`SKILL.md`** — the description from Step 5 + a **thin body**: a router + contract, not a reference essay. Name the quality bar and at least one anti-pattern. Push long procedural detail into `references/`. Soft cap ~200 lines.
- **`evals/trigger-cases.yaml`** — the standard fixture every skill carries: 3 positive paraphrases (must fire), 2 negative/collision (must route to the named neighbor), 1 ambiguous (ask), 1 missing-prerequisite (degrade honestly), 1 failure-recovery (never claim false success). Copy the shape from `.claude/skills/skill-score/evals/trigger-cases.yaml`.
- Optional `references/` and `scripts/` only if the shape needs them.
- **No README** — the SKILL.md is the entry point; a second doc just drifts.

## Step 7 — Validate frontmatter

Immediately after writing `SKILL.md`, run `validators.validate_skill_frontmatter` from `core.utils` against that exact file and show the result. If it returns errors, fix the frontmatter and re-run; do not continue until it is clean.

## Step 8 — Score it (the gate)

Invoke `skill-score` on the new folder, passing its origin (`core` or `user`). That skill runs the deterministic scorer and completes the model-judged parts of the rubric — don't recompute the score here.

- **First-party / Core:** this is a **hard gate**. If the verdict is REVISE or NO, fix what it flags and re-score. Do not declare the skill done, and do not ship it, until it scores **≥ 85** with no hard-gate failure.
- **User skill:** **advisory — coach, never block.** Show the score. If it won't fire on its own, say so plainly and offer the one fix: "This won't fire unless we distinguish it from `X` — want me to sharpen the trigger?" If the user wants it as-is, create it anyway. Their skill is theirs.

## Step 9 — Inspect, then confirm

Read the files you just wrote back before claiming success — confirm the frontmatter, the description, and the evals file are actually on disk and say what the score was. Then:

**User skill:**
```
✅ Created /{name}-custom  (score: NN/100 — {verdict})
Try it: /{name}-custom
Protected from updates — the -custom suffix means Dex updates never overwrite it.
Edit: .claude/skills/{name}-custom/SKILL.md
{if <85: the one change that would make it fire more reliably}
```

**First-party skill:**
```
✅ Created /{name}  (score: NN/100 — SHIP)
Held to the Core hard gate: passed skill-score ≥ 85, no gate failures.
Carries evals/trigger-cases.yaml.
```

---

## Quality bar for this skill

A good run leaves behind a skill that **fires on the user's real phrasing, routes cleanly against its nearest neighbor, and carries its own evals**. A Core skill additionally clears `skill-score ≥ 85`.

## Anti-patterns (do not do these)

- **Appending `-custom` to a first-party skill**, or authoring a user skill under its bare name. Origin decides the suffix.
- **Skipping the collision check** and shipping a skill the router can't tell from an existing one.
- **Forking an existing job** into `{name}-2` / `{name}-v2` instead of editing it in place.
- **Writing the description as a mechanism** ("runs the MCP that…") instead of the outcome.
- **Claiming "created / ready"** without reading the files back or running `skill-score`.
- **Blocking a user's own skill** because it scored low — coach it, then create it if they want it.
- Emitting a second README alongside SKILL.md.

## Degradation

- No `python3` → collision check and scoring fall back to reading descriptions by hand; **say so** and never emit a fake score.
- `skill-score` unavailable → hand-score against its rubric and state that you did.

---

## Track Usage (Silent)

Update `System/usage_log.md` to mark custom skill creation as used.

**Analytics (Silent):** Call `track_event` with event_name `custom_skill_created` and no properties (never include skill names). Fires only if the user opted into analytics; no action if it returns "analytics_disabled".
