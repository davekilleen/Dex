# DRAFT — UNRELEASED — NOT FOR PUBLICATION

This is an Amazon-style working-backwards press release: it describes the
customer outcome this build is intended to enable. The software exists on
unreleased branches, but nothing described here is merged, published, listed in
a marketplace, deployed, or available to customers yet.

---

# Dex brings your working memory to the AI agent you choose

## One personal intelligence system now adapts to Codex, ChatGPT, Claude, Cursor, Gemini, Copilot, Pi, BB, and compatible agent harnesses—without trapping the user in one interface

**LONDON — Future release date** — Dex today announced Dex Everywhere, a new
way for people to bring the same goals, tasks, relationships, meetings, working
history, and trusted workflows into the agent environment they prefer.

Until now, changing AI tools often meant starting again. An assistant might be
excellent at coding, research, or desktop work but know nothing about the user's
commitments, priorities, colleagues, or way of working. Useful context was tied
to a chat history or to one product's private extension system.

Dex Everywhere separates the durable intelligence from the temporary
interface. A user's Dex vault remains the source of truth. At setup, Dex detects
the agent harnesses available on the computer, lets the user choose one or many,
and explains exactly what each can do automatically, on demand, with guidance,
or not at all. Dex then unfolds the appropriate package for that environment.

“People should be able to choose the best agent for the job without abandoning
the context that makes the agent useful,” said Dave Killeen, founder of Dex.
“Your understanding of your work should belong to you. The agent is a window
onto that understanding, not the place it gets trapped.”

With Dex Everywhere, a Codex user can install a native plugin containing Dex's
work skills, read-only context tools, and trusted lifecycle hooks. Claude Code
and Cowork users receive the same shared package through Claude's plugin model,
while Claude Desktop receives a validated local MCP bundle. Cursor uses a native
manifest over the same package. Gemini CLI receives a generated complete
extension from the same canonical sources. GitHub Copilot CLI and compatible
clients use the open Agent Plugin skills and MCP contract; Copilot's separate
lifecycle-hook format is not claimed. Pi uses its native Dex extension. BB users
receive a local, read-only plugin with a Dex panel, tools, and command-line
briefing. ChatGPT desktop can use the same OpenAI plugin package; web access to a
private local vault remains behind a separate secure-connection milestone.

The result is continuity without false sameness. Claude Code remains Dex's
complete reference experience. Other hosts receive native experiences backed by
the same source code, plus a visible capability receipt that prevents Dex from
claiming an automatic behavior where the host can only offer a guided one.

> “I can use the agent that fits the moment and Dex still knows what matters,
> who is involved, and what I promised. I no longer have to choose between the
> best tool and my own working memory.”
>
> — Illustrative customer quote for the working-backwards draft; not a real testimonial

Dex Everywhere also introduces a portable safety layer. The same deterministic
check evaluates destructive command and unsafe-path proposals across hosts. In
an MCP-only environment the result is clearly advisory. In a host with a
trusted pre-action hook, Dex can refuse the proposal before it runs. The system
never upgrades an advisory check into an enforcement claim.

Dex Everywhere is built to remain local-first. The portable context tools read
the selected vault and do not write to it. Onboarding receipts contain harness
names and capability modes, not credentials or private environment paths. Vault
changes continue through Dex's existing transaction-protected lifecycle rather
than through plugin-specific shortcuts.

Dex Everywhere will be available after the current private build passes
release-candidate installation on every advertised host, mandatory independent
Fable review, security review, and Dex's normal release gates on macOS and
Windows. Linux is deferred from this release. Pricing, marketplace availability,
and the release date will be announced separately.

## Customer experience

1. Install Dex and open the full Dex folder in the preferred agent environment.
2. Dex detects likely harnesses and asks the user to confirm one or several.
3. Dex previews a plain-language capability card for each selection.
4. The appropriate plugin, skills, tools, and trusted hooks become available.
5. A fresh session can orient to current goals and priorities, retrieve person
   context, and inspect safety before an action.
6. Dex Doctor shows what is active, guided, or unavailable and how to repair a
   missing piece.

## Why this matters for Dex

Dex is no longer defined by the first terminal in which it became useful. It is
becoming a durable personal-intelligence layer that can outlast individual AI
models, agent products, and interface fashions.

That changes Dex's strategic position in three ways:

- **From assistant to owned context layer.** The durable asset is the user's
  structured understanding of work, not a proprietary chat history.
- **From integration-by-accident to a platform contract.** Every harness is
  described by explicit capabilities and backed by conformance evidence.
- **From one distribution channel to many native doors.** Dex can meet users in
  the environment they already trust while maintaining one core product truth.

---

# Internal FAQ

## What has actually been built?

The unreleased dex-core branch contains the capability registry, multi-harness
onboarding and receipt, Doctor reporting, generated portable skills, shared
context and safety runtime, native OpenAI and Claude manifests, the Agent
Plugins v1/Copilot package, a local OpenAI marketplace entry, release-time
product instructions for Codex, and golden journey tests.

A separate unreleased standalone `dex-bb-plugin` workspace contains BB-native
status, capabilities, and brief tools; `bb dex` commands; a sidebar panel;
bundled skills; Core catalogue readers; and package tests. Its remote repository
has not been chosen yet. Pi's existing native Dex extension remains the Pi path.
The public website installer branch has also been changed to acquire the
supported `release` branch rather than `main`.

## Is any of this live?

No. Nothing has been merged to shared main, published, deployed, submitted to a
marketplace, or released. This document is intentionally a future announcement.

## Is Dex identical in every harness?

No. That would be both technically false and bad product design. Dex preserves
the same vault, shared capabilities, and named journeys while adapting to the
host's real lifecycle and interface. The registry labels every capability as
`automatic`, `on_demand`, `guided`, or `unavailable`.

## Which environments have native packages?

- Codex CLI and Codex in the ChatGPT desktop app: native OpenAI plugin.
- ChatGPT desktop: the same universal OpenAI plugin package.
- Claude Code and Claude Cowork: native Claude plugin.
- Claude Desktop: validated local MCP bundle with read-only tools and no hook claim.
- Cursor: native local plugin with shared skills, MCP, and trusted hooks.
- Gemini CLI: generated native extension with shared skills, MCP, and trusted hooks.
- GitHub Copilot CLI: Agent Plugins/Open Plugin Spec skills and MCP package;
  Copilot-specific lifecycle hooks are not included in this release.
- Compatible Agent Plugins v1 clients: the open skills-and-MCP floor.
- Pi: native Dex Pi extension.
- BB on macOS: standalone native BB plugin. BB currently documents Windows
  through WSL2, so BB-on-Windows remains in this release's deferred Linux lane.

## What does not work through these packages?

- Codex IDE extensions do not currently load plugins.
- ChatGPT web cannot directly start a local stdio server for a private vault.
- Cowork external connectors require a public internet endpoint.
- Copilot's lifecycle hooks use a different package contract and are not
  included; its portable safety check is on demand, not automatic.
- Pi does not have a built-in MCP client; Dex uses its native extension model.
- The BB v1 package is deliberately read-only and does not add jobs, vault
  writes, remote relay, or an experimental provider/host bridge.
- The BB v1 package currently targets macOS. BB does not offer a native Windows
  host; its WSL2 route is deferred with Linux rather than being mislabelled as
  native Windows support.
- Claude Code's complete set of mature Dex hooks is not magically reproduced in
  every host. Only the shared, verified subset is portable.

## Why not expose the local vault through a public server now?

That changes the security and operating model. A public connector needs strong
authentication, authorization, tenant isolation, transport security, audit,
revocation, and a clear privacy story. The local packages can ship without
pretending that work is already complete.

## How does onboarding choose a harness?

Detection is advisory. Dex looks for known environment and path markers, shows
what it found, allows multi-selection and override, previews the capability
modes, and requires explicit confirmation. The saved receipt is local,
non-secret, deterministic, and transactionally provisioned.

## What happens when a user changes agent tools later?

They can rerun the harness selection, add another supported profile, and keep
the same vault. The capability receipt and Doctor report change; their tasks,
people, goals, and working history do not need to migrate to a new chat silo.

## How does the portable safety gate work?

All hosts use the same deterministic source module. The MCP tool returns a
structured decision and is advisory. Codex and Claude plugin packages also map
that module to trusted PreToolUse hooks, where a known-destructive proposal can
be refused before execution. Tests pass proposals as data; they never execute
the destructive commands.

## Can plugins write directly to a user's vault?

The portable plugin and BB v1 package are read-only. Future vault mutations
must go through Dex's lifecycle service and transaction core—the existing “one
safe door”—rather than a new plugin shortcut.

## Why is BB strategically interesting?

BB is both a harness for several agents and a local, plugin-driven IDE. A native
Dex panel demonstrates that Dex can become the shared work context inside an
agent workbench without becoming an agent provider itself. The first package is
narrow by design so Dex can validate demand and trust before adding mutation or
automation.

## Does this make Dex a model router?

No. Dex does not choose or resell the reasoning model. The user chooses the
harness and its provider. Dex supplies durable context, capabilities, and
workflows behind that choice.

## What proof exists today?

- The Codex CLI resolved the repo marketplace and installed/enabled the plugin
  into an isolated temporary Codex home.
- Claude's own plugin validator passed the package.
- MCP initialize/list/call, SessionStart injection, PreToolUse refusal, runtime
  byte identity, registry, onboarding, receipt, Doctor, provisioning, skills,
  hooks, and distribution tests pass on the feature branch.
- Dex Core's release contract names macOS and native Windows as its release
  platforms. Exact-commit native round-trip evidence lives on the draft pull
  request and must be repeated for every review head; Linux remains deliberately
  deferred. The BB package is macOS-only because BB's Windows route is WSL2.
- The BB package passes TypeScript, Vitest, current-stable SDK backend and
  frontend harnesses, package audit, and tarball checks.
- Release and vault bundle builders include byte-identical product-facing
  `AGENTS.md` instructions in their installed-files manifests.

## What still has to happen before release?

Keep the final review head green on the native macOS/Windows matrix and complete
the mandatory Fable reviews; run live release-candidate installs in ChatGPT
desktop, Cowork, Copilot CLI, Pi, and BB; complete the final combined test and
security gates; keep the private Build Card reconciled; clear the private BB
repository's Actions-budget block and run its native macOS review CI; decide the
later public packaging sequence; merge only with explicit founder approval;
then build and verify a real release artifact. Linux remains a separate future
delivery.

## What is the release principle?

Ship one honest capability at a time. Never claim that a feature is automatic
because it can be called manually, never expose a private vault merely to fill
a matrix cell, and never make the harness more important than the user's owned
working memory.
