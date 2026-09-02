---
name: initiative-kickoff
description: "Turn a decision to start something new — a hire, a partnership, a go-to-market push, an internal bet — into a real initiative: the outcome and why now, what success looks like, who's involved, the first concrete steps, and a project page that ladders to your pillars and goals. Use when the user says 'let's kick off X', 'I'm starting a new initiative', 'set up a project for this', or 'we've decided to do Y'. Also use proactively when the user commits to a new effort mid-conversation. Not for spec'ing a product feature or writing a PRD; use `product-brief`. Not for checking the status of projects already underway; use `project-health`."
---

# /initiative-kickoff

The moment you decide to start something new is when it's cheapest to make it real — an outcome, an owner, success you can check, and a first step — instead of a vague intention that never lands. This turns "we should do X" into a project that can actually begin.

It is for **non-product** initiatives — a hire, a partnership, a GTM push, an ops or strategy bet. Spec'ing a product feature is `product-brief`; checking on projects already running is `project-health`.

---

## Step 1 — Frame the initiative

Get these crisp, asking only what's genuinely missing (don't interrogate a well-formed brief):
- **Outcome** — what "won / done" actually looks like, in one line.
- **Why now** — the reason this is worth starting today.
- **Scope / not-scope** — one line each, so it doesn't sprawl.

## Step 2 — Success criteria

Name **2–4 checkable signals** that say it worked — concrete and verifiable, not vanity ("signed 3 design-partner LOIs by end of Q3", not "build momentum"). If the user offers only fuzzy aims, sharpen them into something you could actually check later.

## Step 3 — Owner and stakeholders

Name the **owner** (accountable) and the people involved. Link existing person pages via `lookup_person`; for people without a page, follow the vault's `entity_creation` setting (auto/suggest/off) rather than hard-creating.

## Step 4 — Ladder to pillars and goals

Infer the **pillar** it serves (from `System/pillars.yaml`; never assume a fixed set). Then check `get_quarterly_goals` — if a current goal fits, offer to link it via `confirm_goal_link`. If nothing fits, say so and record it as a **standalone bet** — never manufacture a goal link that isn't real.

## Step 5 — First concrete steps (confirm-gated)

Draft the **3–5 next actions** that get it moving. Offer to turn them into tasks — **nothing is created without per-item confirmation.** For each approved one, call `create_task` (carry the owner, the initiative as source; infer the pillar), then **read back the created task IDs**. A failed `create_task` is reported as not created, never counted as done.

## Step 6 — Create the project page, then confirm

Write the project page to `04-Projects/` with the outcome, why-now, scope, success criteria, owner/stakeholders, pillar/goal link (or "standalone"), and the next steps. Then **confirm by reading back** the page path, the created task IDs, and the goal link. Never report "kicked off" without those in hand.

---

## Quality bar

A good kickoff leaves a real project page with a crisp outcome, **checkable** success criteria, a named owner, an honest ladder to a pillar/goal (or "standalone bet"), and the first steps captured as confirmed tasks — enough that the initiative can actually start, not a paragraph of aspiration.

## Anti-patterns (do not do these)

- **Spec'ing a product** (that's `product-brief`) or **reviewing existing projects** (that's `project-health`).
- **Manufacturing a goal link** when the initiative doesn't ladder to a real one — say "standalone bet."
- **Vanity success criteria** you couldn't actually check later.
- **Auto-creating tasks** without per-item confirmation, or **person pages** against the `entity_creation` setting.
- **Claiming "kicked off"** without reading back the project-page path and created task IDs.

## Degradation

- No quarterly goals set (or `get_quarterly_goals` unavailable) → skip the goal ladder, note it, record as standalone; never fabricate a goal.
- `System/pillars.yaml` absent → ask which area it serves rather than guessing a fixed pillar set.
- `entity_creation: off`/`suggest` → track/offer for new people, don't auto-create pages.
- A `create_task` call fails → report that item as not created; don't count it.

---

## Track Usage (Silent)

Update `System/usage_log.md` to mark initiative-kickoff as used. **Analytics (Silent):** call `track_event` with event_name `initiative_kicked_off` and properties `steps_created` and `linked_to_goal` (count + boolean — no initiative name, no content). Fires only if the user opted into analytics; no action if it returns "analytics_disabled".
