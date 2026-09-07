# Dex Everywhere — plan critique and gap report

**Date:** 2026-09-07
**Purpose:** Independent review of the Dex Everywhere approach, for Dave and for the Codex
session carrying the programme forward. Written to be actionable: every finding ends in a
concrete addition, cut, or question.
**Requested by:** Dave Killeen
**Status:** Review document only. Changes nothing. Programme remains unreleased.

## 0. What this review is grounded in — and one caveat

The review request pointed at `/srv/dex-dev/context/dex-everywhere/2026-09-07-project-plan.md`
on the founder's dev machine. That path is not reachable from this environment and the file
exists on no branch of `davekilleen/Dex`. This critique is therefore grounded in the latest
plan material that *is* in the repository, plus the shipped code itself:

- `docs/plans/2026-08-25-harness-portable-dex.md` (implementation plan)
- `docs/plans/2026-08-27-cursor-cloud-dex-everywhere-handover.md` (programme handover,
  Fable findings, NO-SHIP privacy findings)
- `docs/plans/2026-08-27-dex-everywhere-codex-evidence.md` (per-host evidence ledger)
- `docs/press/2026-08-25-dex-everywhere-unreleased.md` (press release + internal FAQ)
- Current code: `core/harnesses/` (registry, 11 host profiles, adapters),
  `packages/dex-agent-plugin|dex-claude-desktop|dex-gemini-extension`, the five
  portability generators under `scripts/`, Work MCP portable services
  (`boot_today`, `get_person_context`, `check_safety_gate`), and
  `docs/architecture/DEX-CORE-MAP.md`.

If the 2026-09-07 revision differs materially from this lineage — in particular around the
bridge connector, which appears in the stated goal but in none of the in-repo documents —
re-run the specific sections below against it. The structural critique should hold either
way, because it is mostly about the goal statement itself.

## 1. Verdict in one paragraph

The engineering foundation is genuinely strong — better than most portability programmes
ever get: a data-driven capability registry with drift gates, generated (not forked)
portable surfaces, a one-safe-door write contract, per-host golden journeys, and a culture
of refusing to claim what wasn't proven. The risk is not the architecture. The risk is that
the **new goal statement — "all the features available within Claude Code are ultimately
available through workarounds like the bridge connector" — quietly contradicts the
programme's own founding principle of truthful capability continuity**, and that the plan
still mistakes CI-shaped evidence for person-shaped evidence, still spreads across eleven
hosts before any host has a proven live user journey, and still has no specification at all
for the bridge connector it now leans on. Those four things are where the plan needs
finessing, and they are fixable without discarding anything built.

## 2. What is solid — keep, and defend against "simplification"

1. **The capability registry as the single truth.** `automatic / on_demand / guided /
   unavailable` per capability per host, generated and drift-gated, consumed by
   onboarding, Doctor, and setup previews. This is the right spine. Any bridge work must
   land as new registry rows, never as prose claims.
2. **Generated portable surfaces from one canonical source.** 270+ skills, the agent
   plugin, the MCPB, the Gemini extension — all generated with dependency-closure and
   byte-identity checks. No content forks. Keep this absolute.
3. **One safe door for vault mutation.** Every write through
   `core/lifecycle/service.py` → transaction core → ownership contract. Section 5 below
   makes this the load-bearing constraint for the bridge.
4. **The evidence discipline.** Exact-head CI, "a later commit is a new head," "do not
   invent the grant," Ubuntu-is-not-a-Mac. Painful and correct. The critique below asks
   for *more* of this honesty applied to the goal statement, not less of it in the process.
5. **Codex-first sequencing.** Given the shared OpenAI plugin package covers Codex CLI,
   Codex desktop, and ChatGPT Work desktop, Codex-first maximises reuse. Correct call.

## 3. The central tension the plan must resolve first

The 2026-08-25 plan says the portability promise is **"truthful capability continuity, not
false pixel- or hook-level parity."** The press FAQ says **"Claude Code's complete set of
mature Dex hooks is not magically reproduced in every host. Only the shared, verified
subset is portable."** The new goal says **all Claude Code features become available
everywhere via workarounds**.

Both cannot be the product promise. Pick deliberately, because they produce different
plans, different release bars, and different failure modes:

- Under *continuity*, ChatGPT Work shipping with guided vault access and no automatic
  session injection is a **success** if Doctor says so plainly.
- Under *parity-via-workaround*, the same state is an **open defect**, and the programme
  cannot release until a bridge closes it.

**Recommendation: keep continuity as the promise, and adopt parity as an internal
engineering target per capability class** — pursued where a workaround is honest,
explicitly declined where it is not. Concretely, replace "all features everywhere" with a
**Dex Experience Baseline (DEB)**: a named list of user journeys that define "the Dex
experience" — first session orientation, `/daily-plan`, person lookup with context,
meeting processing, task capture/completion sync, safety refusal of a destructive action,
`/dex-update` with rollback, `/dex-doctor`, onboarding — each scored per host in the
registry's four modes. The release bar for a host tier is then a *minimum DEB scorecard*,
not a parity vow. This keeps the ambition measurable and keeps Doctor honest.

Why this matters beyond wording: the four delivery modes are not interchangeable
experiences. A safety gate that is `automatic` in Claude Code and `on_demand` via MCP in
Claude Desktop is not the same feature with different wiring — one protects a user who
never asks, the other protects only the user who asks. The plan already knows this ("MCP
advice is not an interceptor"). The goal statement should say it too.

## 4. Capability-class analysis: what a bridge can and cannot recover

"Workarounds like the bridge connector" needs decomposing, because the Claude Code feature
set rests on four different mechanisms with four different portability ceilings:

| Class | Claude Code mechanism | Portable ceiling | Honest workaround |
| --- | --- | --- | --- |
| **Context & knowledge** (vault read, person/company context, session boot) | Hooks + Work MCP | **Fully recoverable** on any MCP-capable host; recoverable over a bridge for web hosts | `boot_today`/`get_person_context` already exist; bridge exposes them remotely |
| **Skills & journeys** | Agent Skills | **Fully recoverable** where skills are supported; degraded to prompt-pasting elsewhere | Already generated; see §6.3 on model-behaviour parity |
| **Lifecycle automation** (session-start injection, pre-tool safety interception, stop/post-tool, autocommit) | Trusted hooks at guaranteed lifecycle points | **Host-bound.** No bridge can insert Dex between a host's model and its tool execution unless the host offers the hook point | None. Registry truth (`guided`/`unavailable`) + visible receipt. Do not let a bridge imply otherwise |
| **Background automation** (Granola sync, entity engine, release checks, scheduled learning) | launchd/cron installed by Dex | **Host-independent** — this never needed the harness at all | See below: move it out of the harness matrix entirely |

Two consequences the plan should state explicitly:

1. **Background jobs are wrongly framed as a per-harness capability.** Every profile marks
   `background-jobs: unavailable` because no host scheduler is assumed. But Dex's own
   automation already runs outside the harness (launchd on macOS). The honest, cheap
   parity win is a **Dex-owned background runtime** (existing scripts + scheduler,
   installed once per machine) whose *outcomes* every harness reads from the vault. That
   converts the biggest visible gap on non-Claude hosts (meetings don't sync, nothing is
   fresh at session start) into a solved problem with zero per-host work — at the cost of
   acknowledging that Dex ships a small resident service, which is a product-position
   sentence Dave should sign off on, since the plan currently positions Dex as "not a
   runtime." Windows needs its own answer (Task Scheduler) and is currently unwritten.
2. **Pre-tool safety enforcement can never be bridged**, only hosted. The plan already
   holds this line; the new goal statement must not erode it. Any marketing or onboarding
   copy derived from "all features via workarounds" will eventually claim enforced safety
   on a host that cannot enforce it. Put the non-claim in the DEB scorecard so it is
   structurally impossible to overclaim.

## 5. The bridge connector: currently a phrase, not a plan

No in-repo document specifies the bridge. The press FAQ actually argues *against* it in
its current form: *"A public connector needs strong authentication, authorization, tenant
isolation, transport security, audit, revocation, and a clear privacy story."* If the
2026-09-07 plan promotes the bridge to a load-bearing component, that paragraph converts
into a requirements list the plan must now satisfy. What is missing:

1. **Topology decision.** Local daemon + user-initiated authenticated tunnel
   (local-first, vault never leaves the machine, but requires the machine to be on) vs
   hosted relay (always-on, but Dex now operates a service holding a door to private
   vaults — a company-changing liability). This single decision drives cost, privacy
   story, and release timeline more than anything else in the programme. It is unmade.
2. **Threat model and credential boundary.** The house already has a precedent for the
   required rigor: the connection-manager doorway (`/connect`) is **still no-go** after
   seven hardening phases because a same-user credential boundary was not clean
   (DEX-CORE-MAP §6). A bridge that exposes vault read — let alone write — to a cloud
   host is a strictly larger surface than the one that earned that no-go. Budget for the
   same treatment: threat model, failing-first security tests, independent review, and a
   realistic chance of a NO-SHIP verdict on the first design.
3. **Pairing and consent UX.** How a user connects host X to vault Y: device-code flow,
   scoped per-harness tokens, visible active-connections list in Doctor, one-command
   revocation, kill switch, and an audit log written into the vault itself.
4. **Writes over the wire vs one safe door.** If the bridge is read-only, say so and
   scorecard the write journeys as `guided` on web hosts. If it writes, every mutation
   must route through the lifecycle service on the vault machine — the bridge is a
   *client* of the one safe door, never a second door. This sentence needs to be in the
   plan before any bridge code exists.
5. **Concurrency.** The moment two harnesses reach one vault (Claude Code locally,
   ChatGPT via bridge), concurrent-write behaviour stops being theoretical. The
   transaction core assumed one local actor. Locking/queueing semantics, and what a
   losing writer sees, need tests before the second door opens.
6. **Version skew.** Bridge protocol version vs vault version vs plugin version across N
   hosts. Define compatibility rules and what Doctor says when they diverge.
7. **Failure honesty.** Machine asleep, tunnel down, token expired — each maps to a
   `feature_status`-style envelope, not a silent empty result. This mirrors the existing
   calendar confidence contract and should reuse its pattern.

**Recommendation:** make the bridge its own phase with its own design doc, threat model,
and go/no-go gate — after the local-host tiers ship. Do not let "bridge" appear in any
host's capability notes until that doc exists, because the registry is generated into
user-facing promises.

## 6. Wishful-thinking audit

Ranked by how much trouble each will cause if left as-is.

### 6.1 CI-shaped proof standing in for person-shaped proof

The evidence ledger is admirably honest that live journeys are missing — ChatGPT Work
vault grant, live Copilot CLI install, Cowork folder permission, Claude Desktop install
UI, live BB install, Pi installation. But the plan's structure still treats these as
release-candidate checkboxes at the end. They are not checkboxes; they are **the first
moment a real person meets the product**, and historically that is where portability
efforts die (trust prompts that read as scary, plugin caches that don't refresh, folder
pickers that can't reach the vault). Two changes:

- Pull one **manual install-day per host tier** forward, before more breadth work. One
  hour of Dave on a real desktop per host will re-rank the backlog more accurately than
  any further CI.
- Add the missing journey the matrix never mentions: **uninstall/cleanup** per host, and
  **what a Dex update does to an already-installed host package** (does a v1.98 vault
  with a v1.97 Codex plugin degrade honestly?). Update skew across N hosts is currently
  unaddressed anywhere in the lineage.

### 6.2 Eleven hosts, zero users

Descriptors exist for Claude Code, Cowork, Claude Desktop, Codex, Cursor, Gemini CLI,
Copilot CLI, Pi, generic Agent Plugin clients, ChatGPT Work, and BB. Every host added
before release adds permanent costs: upstream API churn watch, golden-journey
maintenance, support surface, and marketplace/ToS review cycles — against zero
demand evidence. The registry makes *carrying* a profile cheap, but *advertising* one is
a promise. Recommendation:

- **Tier the launch**: Tier 1 = Codex family + Claude family (shipped, DEB-scored,
  live-journey proven). Tier 2 = Cursor, Gemini CLI, Copilot CLI (packages exist; gate on
  demand signals from Tier 1 users). Tier 3 = Pi, BB, generic clients (keep green,
  unadvertised).
- Add an **upstream-watch job** to the plan: host plugin formats are all under a year old
  and moving (Codex plugin spec, Copilot's separate hook contract, BB SDK 0.4.x). Today
  nothing detects that a host changed its contract until a user is broken. A scheduled
  re-validation of each package against pinned upstream versions, with a named owner,
  belongs in Lane E.
- Define a **host deprecation policy** now (what Dex says when a host breaks its side),
  because with eleven hosts, one will.

### 6.3 The silent assumption that skills behave the same under other models

Everything portable ships instructions that were authored against and tuned on Claude.
Codex, Gemini, and Copilot models will follow SKILL.md prose differently — different
tool-call habits, different obedience to "never do X" phrasing, different context
budgets. The plan verifies that skills *arrive* intact (byte identity, dependency
closure) but never that they *work* on the target model. The DEB journeys should
therefore be executed per host tier as **behavioural evals** (the repo already has a
skill-eval culture to extend), and the date-accuracy and safety-refusal behaviours — the
two places where model drift does user-visible damage — should be the first two evals.
Without this, "Dex works in Codex" means "Dex's files are readable in Codex."

### 6.4 "Automatic after trust" is doing quiet double duty

The Codex profile marks session-lifecycle `automatic` with the note "after the plugin is
trusted." From the user's chair, a behaviour that silently doesn't run because a trust
prompt was dismissed three weeks ago is indistinguishable from a broken feature. Either
Doctor must be able to *verify* the trust state per host (and report `hooks: granted /
not granted`), or these rows should be `guided` until granted. The registry has the
vocabulary; use it at the granularity users experience. Related: the plan should add a
short **security review of the bundled hooks themselves** — Dex is now asking users to
trust executable hooks in four host formats, and "user must trust them" is a
responsibility transfer only if the hooks are demonstrably minimal and auditable.

### 6.5 Capability exchange is still NO-SHIP and should be formally decoupled

The handover's five P1/P2 privacy findings (raw prose egress by construction, decline
storage inside inspected roots, detector false negatives, identity-before-consent,
concurrent-decline loss) are of the never-ship-half-fixed kind, and the required fix —
minimisation by construction rather than detection — is a redesign, not a patch. If the
2026-09-07 plan still lists the two-way exchange as an end-state requirement *of this
release*, that is the plan's single biggest schedule risk. Recommendation: name it a
separate programme with its own release gate, so Dex Everywhere's host work can ship
without it and nobody is tempted to soften a privacy boundary to hit a combined date.

### 6.6 Onboarding and feedback parity are assumed, not planned

Two Claude-shaped dependencies sit under "the ultimate Dex experience" and appear nowhere
in the lanes:

- **Onboarding**: the flow is MCP-driven (good — portable in principle) but the
  onboarding MCP is one of three servers *without* the `feature_status` honesty envelope
  (DEX-CORE-MAP §5), and the flow's prose lives in `.claude/flows/`. First-run on Codex
  is the first thing a new-host user touches; it needs its own golden journey and the
  envelope gap closed.
- **`/feedback` and analytics**: a Codex user who hits a bug has no proven report path,
  and the Fable review already flagged share/feedback portability (finding 7). Analytics
  consent semantics per host are similarly unstated. Both belong in the DEB.

## 7. Additions checklist (hand this to Codex)

In priority order; items 1–4 change what gets built next, 5–10 harden the plan's edges.

1. Replace the parity goal with the **Dex Experience Baseline**: named journeys ×
   registry modes × host tiers, with a published minimum scorecard per tier (§3).
2. Write the **bridge connector design doc** as a separate phase: topology decision,
   threat model, pairing/consent/revocation UX, read-only-vs-one-safe-door ruling,
   concurrency semantics, version-skew rules, failure envelopes (§5). No registry or
   marketing reference to the bridge until it exists.
3. Split **background automation out of the per-harness matrix** into a Dex-owned
   runtime with a Windows answer; re-score every host's freshness journeys against it
   (§4.1).
4. Schedule **manual install-days** for Tier 1 hosts now; add uninstall and
   update-skew journeys to the matrix (§6.1).
5. Adopt the **three-tier host launch** and add the upstream-watch job with a named
   owner plus a host deprecation policy (§6.2).
6. Add **per-host behavioural evals** for DEB journeys, starting with date accuracy and
   safety refusal (§6.3).
7. Make **hook-trust state visible to Doctor** per host, or downgrade those rows to
   `guided`; add a security review of the bundled hooks (§6.4).
8. Formally **decouple capability exchange** into its own programme and gate (§6.5).
9. Add **onboarding, `/feedback`, and analytics-consent parity** to the DEB; close the
   `feature_status` gap on the onboarding MCP (§6.6).
10. Add **multi-harness concurrency tests** (two hosts, one vault) before any second
    write path opens — bridge or not (§5.5).

## 8. Open questions for Dave

1. Continuity or parity: which sentence goes on heydex.ai? (§3 recommends continuity
   with a DEB; this is a founder call because it is the promise.)
2. Is Dex allowed to ship a resident background service on user machines? (§4.1 — it
   already effectively does on macOS via launchd; this makes it a stated product fact.)
3. Bridge topology: is Dex prepared to *operate a hosted service* touching private
   vaults, or is the bridge local-first tunnel only? (§5.1 — this decision gates
   everything else about the bridge.)
4. Which two or three hosts have actual user demand signals today? Tiering (§6.2) is
   guesswork without this.
5. Does capability exchange stay inside this release's definition of done, or move to
   its own programme? (§6.5.)

---

*Review conducted against the repository state at branch
`claude/dex-everywhere-plan-review-4zsvm4` (base `main` at v1.97.13, 2026-09-07). The
2026-09-07 project-plan file itself was not reachable from this environment; see §0.*
