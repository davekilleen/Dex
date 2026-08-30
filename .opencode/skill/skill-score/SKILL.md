---
name: skill-score
description: Grade a Dex skill against the shape-aware quality rubric and report a ship/revise/no verdict with the exact fixes. Use when you finish writing or editing a skill, when create-skill hands off a new package, before shipping a first-party skill, or when the user asks "is this skill any good / will it fire / score my skill". Also use proactively right after any SKILL.md is created or its description changes. Not for authoring a new skill from scratch (use create-skill) or fixing broken YAML frontmatter alone (create-skill's validator does that); skill-score judges architecture and routing, not just format.
---

# /skill-score

Grade a skill the way the router and a real user will experience it — then say plainly whether it ships, and if not, exactly what to fix.

Two things make a skill good: **it fires when it should** (the description is the router) and **it does the job safely and well when it fires** (the body is a contract, not a how-to essay). This skill scores both, applies the hard safety gates that override the number, and returns a verdict.

Governing principle: **hard on Core, gentle on the user's own creations.** A Core / first-party skill that scores below the bar does not ship — that is a hard gate we hold ourselves to. A skill the user wrote for themselves is *coached, never blocked*: show the score, name the one change that would make it fire, offer to make it — but always create/keep their skill if they want it.

---

## Arguments

`$TARGET`: Optional.
- A skill name or path (`triage`, `.claude/skills/triage/`) → score that one skill.
- `--all` → portfolio pass over every shipped skill: routing collisions, stale references, bad frontmatter, and per-skill grades in one table.
- Empty → score the skill most recently created or edited this session; if none, ask which.

`$ORIGIN`: Optional. `core` (first-party, hard gate) or `user` (coach-don't-block). If omitted, infer: a `-custom` suffix or a path under `.claude/skills-custom/` ⇒ `user`; anything else shipped in the repo ⇒ `core`.

---

## Step 0: Prefer the script

The scoring math (Tier-1/Tier-2 point tally, length checks, `when`-trigger detection, reference-path existence, collision proximity) is deterministic. **Run the script, don't recompute by hand:**

```
python3 .claude/skills/skill-score/scripts/score_skill.py <path-to-skill-dir-or-SKILL.md> [--all] [--origin core|user] [--json]
```

The script returns the mechanical sub-scores, every hard-gate check it can decide from files alone, and a provisional grade. Then **you** (the model) do the judgment-only parts the script flags as `NEEDS_MODEL`: is the description actually distinguishable from its nearest neighbor in *meaning* (not just string distance)? Does the body inspect its own output before claiming success? Are the anti-triggers pointing at the *right* neighbor? Merge the script's tally with your judgment calls into the final verdict.

If the script cannot run (no Python), fall back to scoring by hand against the rubric below — say so in the output.

---

## The hard gates (any one fails ⇒ verdict is NO, whatever the number)

These come straight from the ratified synthesis. A skill cannot ship if:

1. **Indistinguishable from a neighbor.** Its description cannot be told apart from its nearest existing skill — the router would coin-flip between them. (Fix: sharper outcome + anti-trigger naming that neighbor.)
2. **Destructive / external / publish action without authority.** It can delete, overwrite, send, post, or publish outside the user's vault without an explicit confirmation gate in the body.
3. **PII into a shared artifact.** Secrets or personal content can flow into anything that leaves the machine (a published DexDiff profile, an uploaded page, an external message) without a redaction or confirmation step.
4. **Claims success without inspecting output.** It tells the user "done / created / fixed" without reading back the thing it just produced or the tool result that proves it.

For a **user-origin** skill, gates 2–4 still *warn loudly* and gate 1 becomes advice ("this won't fire on its own unless we distinguish it from `X` — want me to?") — but they do not refuse to create the user's own skill. For a **core-origin** skill, any gate failure blocks the ship.

---

## Tier 1 — universal must-pass (~60 pts). Every skill, every shape.

| # | Criterion | Pts | What "pass" looks like |
|---|-----------|----:|------------------------|
| T1.1 | **Description carries a WHEN trigger** | 12 | Frontmatter names concrete situations AND user phrases ("when the user says…"). The word `when`/`whenever` is necessary but not sufficient — it must describe a real firing situation. |
| T1.2 | **Description has an anti-trigger** | 10 | "Not for X; use Y" naming the real nearest neighbor, so the router can disambiguate. |
| T1.3 | **Description states the outcome, not the mechanism** | 8 | Leads with what the user gets, in plain language — no internal function/file names. |
| T1.4 | **Thin body; detail externalized** | 8 | Body is a router + contract. Long procedural/reference detail lives in `references/`. Soft cap ~200 lines; over ~350 is a fail unless justified. |
| T1.5 | **Named quality bar + anti-patterns** | 8 | The body says what "good output" is and names at least one failure mode to avoid. |
| T1.6 | **Truthful degradation** | 8 | When a prerequisite/tool is missing, it says so honestly (or skips silently by design) — never fakes success or invents a result. |
| T1.7 | **Legible + composes** | 6 | Refers to people/skills/artifacts by name not id; points to sibling skills instead of re-implementing them. |

Tier-1 floor: a core skill must clear **≥50/60** on Tier 1 regardless of Tier 2.

## Tier 2 — situational, scored only if the shape applies

Classify the skill's shape first, then score only the matching block. **Do not cargo-cult these onto a plain conversational workflow** — an inapplicable criterion is scored N/A, not zero.

| Shape | Criterion | Pts |
|-------|-----------|----:|
| setup / integration | Idempotent writes + a re-run/repair path; states the setup contract | 10 |
| dependent (needs a tool/feature) | Doctor/degradation ladder: detect → explain → fix-path | 10 |
| generative (produces user-facing content) | Named bar + anti-slop rules + inspect-real-output-before-claiming | 12 |
| multi-session / stateful | State externalized + sized to a session; consider `disable-model-invocation` only if destructive/dev | 8 |
| script-bearing | Agent-native output contract: `--diagnose`/`--dry-run`, exit codes, machine-readable result | 10 |

Tier-2 available points vary by shape; normalize the final grade to 100 (`earned / applicable * 100`). The script does this.

---

## Grade bands

- **≥85 — SHIP.** Clears the bar. (Core: may merge. User: great, ship it.)
- **70–84 — REVISE.** Close. Return the specific criteria that lost points; usually 1–2 description fixes.
- **<70 — NO.** Not ready. For core: does not ship. For user: coach, offer to sharpen, still create if they insist.
- **Any hard-gate failure — NO**, printed above the number with the gate named.

---

## Step 1: Load and classify

Read the target `SKILL.md` (+ its dir). Determine origin (`core`/`user`) and shape (workflow / setup / generative / multi-session / research / script-bearing — a skill can be more than one). Note which Tier-2 blocks apply.

## Step 2: Run the checks

Run `.claude/skills/skill-score/scripts/score_skill.py`. It returns: Tier-1 sub-scores, applicable Tier-2 sub-scores, hard-gate results it can decide, referenced-path existence, nearest-neighbor by description proximity, and a provisional grade.

## Step 3: Model judgment (the parts a script can't)

For each item the script marks `NEEDS_MODEL`, decide it and record one line of evidence:
- **Distinguishable-in-meaning?** Read the nearest-neighbor's description; would *you* pick the right one from a real user utterance? If not → gate 1.
- **Inspects its own output?** Find the place the skill declares done. Does it read back what it made? If not → gate 4.
- **Anti-trigger points at the true collision?** The named neighbor must be the one users would actually confuse it with.
- **Degradation honest?** Trace the missing-prereq path.

## Step 4: Run the trigger evals

Load `evals/trigger-cases.yaml` for the skill (see shape below). For each case, decide whether *this description* would fire. Positives must fire; negatives/collisions must NOT (they should route to the named neighbor); the ambiguous case should ask; the missing-prereq case should degrade honestly; the failure-recovery case should not claim false success. Report pass/fail per case. A core skill that fails a positive or a collision case cannot score ≥85.

## Step 5: Verdict

Print, in this order:
1. **VERDICT: SHIP / REVISE / NO** + the numeric grade.
2. Any **hard-gate failures**, each named, with the one change that clears it.
3. **Lost points**, grouped Tier-1 / Tier-2, each with the concrete fix (ideally the rewritten line).
4. **Trigger-eval results** (X/8 passed; list failures).
5. For **user-origin**: the coaching line — never a refusal. For **core-origin**: the ship decision.

Keep it short and actionable. The output is a fix list, not an essay.

---

## `--all` portfolio mode

Score every shipped skill and emit one report:
- Grade table (skill | origin | shape | grade | verdict).
- **Routing collisions**: pairs whose descriptions are too close to disambiguate.
- **Stale references**: `references/`/script paths named but absent.
- **Bad frontmatter**: missing name/description, malformed YAML.
- Portfolio summary: how many core skills are below the bar (the ship-blocking list).

This is the health check behind the description-rewrite / consolidation program — run it before and after the overhaul to measure the win.

---

## Anti-patterns (for this skill itself)

- Do not pass a skill just because its YAML is valid — that is create-skill's floor, not the bar.
- Do not invent a Tier-2 penalty for a shape that doesn't apply.
- Do not block a user's own skill. Coach it.
- Do not claim a grade without running the checks (or saying you fell back to hand-scoring).
