# Exploration: Dex as an Org-Wide Brain

**Status:** Exploration / RFC — not a commitment
**Created:** 2026-06-05
**Owner:** Dave Killeen
**One-liner:** What would it take to evolve Dex from a *personal* knowledge system into a *shared organizational* brain — and should we?

---

## 1. Why this is worth exploring

Every Dex user is independently building a high-fidelity model of *their* slice of the company: the people, the projects, the decisions, the open commitments. Today those models are silos. The person who knows why the pricing model changed in Q1 has it in their vault; the new hire asking the question six months later has no way to reach it.

The latent value is obvious: if ten people each maintain a personal brain, the *organization* is one connective layer away from a brain of its own. The "wish" here is reachable precisely because the hard part — getting individuals to capture context at all — is the thing Dex already solves.

But "org-wide brain" is a phrase that hides at least four different products. **Before building anything, we should pick which one we mean.** The biggest risk isn't technical; it's building a multi-tenant data platform when what the org actually wanted was a shared search box.

---

## 2. Challenge first: what does "org-wide brain" actually mean?

These are not the same product. They differ by an order of magnitude in cost, risk, and time-to-value.

| Interpretation | What it is | Effort | Headline risk |
|----------------|-----------|--------|---------------|
| **A. Shared read layer** | Each person keeps a private vault; opt-in slices are published to a queryable shared index. "Ask the org" search. | Low–Med | Stale/contradictory content |
| **B. Shared write layer** | Canonical org objects (projects, accounts, people) that multiple Dexes read *and* update. | High | Conflict resolution, ownership |
| **C. Federated agents** | My Dex can *ask your Dex* a question, mediated by permissions. No central store. | Med–High | Latency, availability, trust |
| **D. Central org brain + personal satellites** | A hosted org vault is the source of truth; personal Dex is a local cache/view. | Very High | This is now a SaaS, not a vault |

My instinct: **the value/effort curve peaks at A, with a deliberate path toward C.** B and D quietly turn Dex from "a folder of markdown you own" into "a platform you rent," which contradicts the local-first, you-own-your-data DNA in the current architecture (local MCP servers, plain markdown, no central server). That tension is the central design question of this whole exploration — see §6.

**Recommendation for this branch:** scope the exploration to **Interpretation A (shared read layer)** as v1, and design it so it doesn't foreclose **C (federation)**. Treat B/D as explicitly out of scope unless a concrete need forces them.

---

## 3. What we'd be building on (current architecture)

Grounding the idea in what Dex *is* today, so we extend rather than reinvent:

- **Storage:** Plain markdown vault in PARA structure. Human-readable, git-friendly, no database. *(This is a feature, not a limitation — it's why sharing can be incremental.)*
- **Identity of objects:** People are `Firstname_Lastname.md`; companies, projects similar. There's already a **people index** (lightweight JSON, fuzzy match) and **QMD semantic search**. These are the seeds of a shared schema.
- **Compute:** Local MCP servers (`work_server`, `career_server`, `session_memory_server`, `granola_server`, etc.) — per-user processes, no shared backend today.
- **Memory layers** (from `Memory_Ownership.md`): Claude auto-memory (preferences), agent memory (per-agent state), session learnings (operational), QMD (search). Notably **all four are single-user-scoped**. An org brain needs a *fifth* layer: **shared/org memory** with explicit ownership rules — this is the cleanest place to slot the new concept without disturbing the existing four.
- **Sync primitive that already exists:** git. The repo is already a git repo with branches. Git is a credible v1 transport for a shared read layer (see §5).

**Key insight:** Dex already has the two hardest ingredients of a shared brain — *structured per-person context* and *semantic search over it*. The missing piece is a **boundary model**: what's private, what's shared, and how the line is drawn and enforced.

---

## 4. The four problems that actually matter

Everything hard about this reduces to four problems. Any proposal has to answer all four.

### 4.1 The privacy boundary (the make-or-break)
A personal vault contains career notes, 1:1 venting, manager feedback, salary context, half-formed opinions about colleagues. **None of that can leak into an org brain.** This is not a "permissions" nice-to-have; one bad leak kills adoption permanently.

Design stance: **private by default, share by explicit act.** Nothing is shared unless the user marks it shared. Candidate mechanisms:
- Frontmatter flag: `visibility: org | team:<name> | private` (default `private`).
- A dedicated `08-Shared/` (or `05-Areas/Org/`) folder that is the *only* publishable surface — opt-in by location, which is more legible than per-file flags.
- A pre-publish redaction/lint pass (an MCP tool) that flags career/People-External/journal content trying to cross the boundary.

I lean toward **folder-as-boundary** for v1 (legible, hard to get wrong) plus a lint guard, over per-file flags (powerful but easy to misconfigure — and a misconfiguration here is a data leak).

### 4.2 Identity resolution across vaults
My `Sarah_Chen.md` and your `Sarah_Chen.md` are the same human — or are they? Two people, same name, two companies. The org brain needs stable identity:
- Lean on `email_domain` + email as the primary key (it's already the routing key for Internal/External people pages).
- The existing **people index** becomes the natural place for org-level person IDs.
- Companies/projects need the same: a shared registry of canonical IDs that personal vaults reference.

### 4.3 Freshness, conflict, and authority
Ten vaults will disagree. Whose "project status" is correct? For a **read layer (A)** this is softer — you show provenance ("per Dave's vault, updated May 30") and let the human adjudicate. For a **write layer (B)** it's brutal and is the main reason to defer B.
- v1 answer: **never merge, always attribute.** Shared results carry source + timestamp. Contradiction is surfaced, not resolved.

### 4.4 Trust, access, and governance
Who can read the org brain? Teams? Everyone? Ex-employees? Offboarding = revoking a share is a real workflow. This is where "just use git" starts to creak and a real access layer (or an existing one — Notion/Google/Slack ACLs) becomes attractive.

---

## 5. Candidate architectures (concrete, for A)

### Option 1 — Git-native shared vault (lowest cost, most on-brand)
A separate **org repo** (e.g. `org-brain/`). Each person's Dex publishes opt-in markdown into it via a skill (`/share-to-org`); a scheduled job rebuilds a shared QMD index. Querying the org brain = querying that index.
- **Pros:** Reuses git, markdown, QMD. No new infra. Preserves local-first. Access control via repo permissions (GitHub teams) — which *already* maps to org structure.
- **Cons:** Git isn't real-time. Redaction discipline is on the user. No fine-grained per-paragraph ACL.
- **Verdict:** **Best v1.** Ships fastest, tests the actual demand cheaply, doesn't betray the architecture.

### Option 2 — Federated query (path toward C)
No central store. An MCP server exposes a *query* endpoint over my shared slice. My Dex can call yours: "what's the latest on Acme renewal?" Permission-mediated, answered live from the source vault.
- **Pros:** Always fresh. No central honeypot of data. Strongest privacy story (data never leaves origin).
- **Cons:** Availability (your laptop is asleep), latency, discovery, harder auth. Needs a registry of who-runs-what.
- **Verdict:** Compelling **v2**. Design v1's share surface so these same files are what a federated endpoint would serve.

### Option 3 — Hosted org service (B/D)
A real backend: multi-tenant store, sync, web UI, ACLs. This is a company, not a feature.
- **Verdict:** Out of scope for exploration. Flag it as the "if this takes off" destination, not the starting point.

---

## 6. The core tension to resolve before any build

> Dex's identity is **local-first, you-own-your-data, plain markdown, no server.**
> An org brain pulls toward **shared, governed, synced, central.**

These can coexist *only* if the org layer is **additive and opt-in**: your private vault stays exactly as it is, and "org" is a thin shared surface you publish *to*, not a platform that absorbs you. The moment the personal vault becomes a cache of a central store (Option 3 / Interpretation D), we've changed what Dex *is*. 

This is the decision that should be made by a human, explicitly, before code — it's a product-identity choice, not a technical one.

---

## 7. A possible phased path (if we proceed)

1. **Phase 0 — Boundary primitives.** Add `visibility` frontmatter + an `08-Shared/` surface + a redaction-lint MCP tool. *Useful even for a single user* (clean public/private separation). Lowest risk, no org needed yet.
2. **Phase 1 — Shared read layer (Option 1).** Org repo + `/share-to-org` skill + shared QMD index + `/ask-org` query skill. Provenance on every result.
3. **Phase 2 — Identity registry.** Canonical person/company/project IDs in a shared index; reconcile across vaults.
4. **Phase 3 — Federation (Option 2).** Live cross-vault queries, permission-mediated.
5. **Phase 4 — Governance.** Teams, offboarding/revocation, audit.

Each phase is independently valuable and independently abortable. We learn whether the demand is real at Phase 1 before paying for anything harder.

---

## 8. Open questions (need human input)

1. **Which interpretation (A/B/C/D) are we actually chasing?** (My rec: A now, C later.)
2. **What's the smallest org that makes this worth it** — a 5-person team, or 50+? Changes the governance cost dramatically.
3. **Is the wish "search across the team" or "a living single source of truth"?** The first is Option 1 in weeks; the second is a multi-year platform.
4. **Where does access control live** — GitHub teams (free, coarse), or a dedicated layer (costly, fine-grained)?
5. **Does this stay local-first** (§6), or is the org willing to host? This decision gates everything downstream.
6. **Build vs. integrate:** much of "shared org knowledge" overlaps with Notion/Confluence/Slack the org already pays for. Is Dex's edge the *capture* (which those tools lack) feeding *their* shared layer, rather than a new shared store? Worth pressure-testing before building any sharing infra at all.

---

## 9. My recommendation

1. **Don't build a platform.** Build the **boundary primitives (Phase 0)** first — they're valuable to a solo user *today* and are the prerequisite for everything else.
2. **Prototype Option 1** (git-native shared read layer) with a real 3–5 person team to test whether "ask the org" demand is real before investing in identity/federation.
3. **Explicitly decide §6** (local-first vs. hosted) with a human before any Phase 2+ work.
4. **Seriously consider §8.6** — Dex-as-capture feeding the org's *existing* knowledge tool may beat Dex-as-new-shared-store on both effort and adoption.

The most likely failure mode is over-building: shipping multi-tenant sync for a problem that a shared search index and good redaction discipline would have solved. Start at the cheap end of the curve.

---

## Appendix: where this touches the current codebase

- **Memory model:** add a 5th "Org/Shared memory" layer to `06-Resources/Dex_System/Memory_Ownership.md`.
- **People index / QMD:** the natural substrate for an org-level identity registry and shared index.
- **MCP servers** (`core/mcp/`): a new `share_server.py` (publish + redaction-lint) and later a `federation_server.py` (Option 2 query endpoint).
- **Skills:** `/share-to-org`, `/ask-org`, `/org-setup`.
- **Routing:** `email_domain` (already in `user-profile.yaml`) is the existing primitive for identity and the Internal/External boundary — reuse it.
- **Privacy-sensitive zones to fence off by default:** `05-Areas/Career/`, `05-Areas/People/External/`, journal entries, `System/Session_Learnings/`.
