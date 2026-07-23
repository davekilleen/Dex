# The Dex skill standard

The Dex-specific delta over the vendored `anthropic-skill-creator` guide. Read
`anthropic-skill-creator/SKILL.md` for the general craft (concise-is-key, degrees of
freedom, progressive disclosure, packaging). This file is only what Dex adds on top.
When the two agree, follow the general guide; when Dex is stricter, Dex wins.

---

## 1. The description is the router

In Dex the one-line `description` is what the model reads to decide whether to invoke a
skill. **Description quality *is* skill quality.** A perfect body behind a description
that never fires is a skill that does nothing. Spend the effort here.

A Dex description has three parts, in this order:

1. **Outcome first** — what the user gets, in plain "smart friend" language. No internal
   function names, file paths, MCP/server/manifest jargon. "Build today's plan from your
   calendar and tasks" — not "invokes the planning MCP".
2. **WHEN trigger** — the concrete situations *and the phrases the user would actually
   say*: `Use when the user says 'plan my day', 'what's on today'`. The word `when` alone
   is not enough; it must name a real firing situation.
3. **Anti-trigger** — `Not for X; use Y`, naming the real nearest neighbor, so the router
   can disambiguate two skills that would otherwise collide.

Template:

```
{Outcome in plain language}. Use when the user says '{phrase}', '{phrase}', or {situation}.
Also use proactively when {situation}. Not for {adjacent job}; use `{neighbor-skill}`.
```

## 2. The body is a contract, not an essay

- **Thin body.** A router + a contract. Long procedural or reference detail goes in
  `references/`. Soft cap ~200 lines; over ~350 fails the bar unless justified.
- **Name the quality bar.** State what "good output" looks like for this skill.
- **Name at least one anti-pattern.** The failure mode to avoid.
- **Truthful degradation.** When a prerequisite or tool is missing, say so honestly or
  skip silently by design — never fake success or invent a result.
- **Compose, don't re-implement.** Refer to sibling skills, people, and artifacts by name;
  point at `skill-score` rather than re-deriving the rubric.

## 3. Origin decides everything downstream

| | User skill | First-party / Core skill |
|---|---|---|
| Folder | `{name}-custom/` | `{name}/` |
| Update behavior | protected — never overwritten | shipped + maintained |
| `skill-score` | **advisory — coach, never block** | **hard gate — must score ≥ 85** |
| On a low score | show the one fix, create it anyway if they want | fix and re-score until it clears |

Never append `-custom` to a first-party skill, and never author a user skill under its
bare name. If you're unsure which it is, ask one line.

## 4. Every skill carries `evals/trigger-cases.yaml`

The canonical fixture (copy the shape from
`.claude/skills/skill-score/evals/trigger-cases.yaml`):

- **3 positive** paraphrases — MUST fire this skill.
- **2 negative / collision** — MUST NOT fire; `route_to:` the named neighbor.
- **1 ambiguous** — should ASK rather than silently fire.
- **1 missing-prerequisite** — should degrade honestly, not fake a result.
- **1 failure-recovery** — must not claim success when the underlying action failed.

These are the cases `skill-score` replays. A Core skill that fails a positive or a
collision case cannot score ≥ 85.

## 5. The four hard gates (Core blocks; user warns)

Straight from the ratified synthesis. A **Core** skill cannot ship if any fails; for a
**user** skill these warn loudly but never refuse to create the skill:

1. **Indistinguishable from a neighbor** — the router would coin-flip. Fix: sharper
   outcome + anti-trigger naming that neighbor.
2. **Destructive / external / publish action without an explicit confirmation gate** in
   the body (delete, overwrite, send, post, publish, deploy, upload).
3. **PII into a shared artifact** — personal content can flow into anything that leaves
   the machine without a redaction or confirmation step.
4. **Claims success without inspecting output** — says "done/created/fixed" without
   reading back the thing it produced or the tool result that proves it.

## 6. What NOT to do

- No per-skill `group`/`category` frontmatter field. Grouping is a planning lens derived
  in the inventory generator, never stored per-skill.
- No second README beside `SKILL.md`.
- Don't fork upstream vendored Anthropic skills (`anthropic-*`) — compose them.
- Don't fork an existing job into `{name}-2` / `{name}-v2`; edit it in place.
