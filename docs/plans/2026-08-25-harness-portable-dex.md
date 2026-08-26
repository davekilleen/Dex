# Harness-portable Dex and BB plugin — implementation plan

**Status:** Built, final verification and review in progress; deliberately unreleased
**Branch:** `codex/harness-portable-dex-resume`
**Decision owner:** Dave Killeen
**Date:** 2026-08-25

## Outcome

Make Dex a portable personal-intelligence layer that can sit behind more than one agent
harness. A user should be able to bring the same vault, core tools, and named journeys to
Claude Code/Cowork/Desktop, Codex, ChatGPT desktop, Cursor, Gemini CLI, GitHub Copilot CLI,
Pi, a generic Agent Plugin client, or BB and receive a precise account of what is automatic,
guided, or unavailable in that host.

The build stops before merge, publication, marketplace submission, installation for another
user, or release.

Dex Core's portable distribution targets macOS and native Windows. Linux remains deliberately
deferred. The standalone BB adapter is narrower: BB 0.40.0 has no native Windows host and
documents WSL2 instead, so this BB release targets macOS while Windows/WSL stays in the
deferred Linux lane. A platform is not called release-ready until the same launcher completes
real round trips on that operating system's CI runner. Node 20+ and Python 3.11+ are explicit
Core prerequisites.

## Product position

Dex is not an agent provider or a model router. It is the durable knowledge system and
capability layer behind a user's chosen agent. Harnesses may offer different event hooks,
interfaces, and background runtimes, so equal outcomes do not always mean identical wiring.

The portability promise is therefore **truthful capability continuity**, not false pixel- or
hook-level parity.

## Repository boundaries

| Repository | Owns | Does not own |
| --- | --- | --- |
| `dex-core` | Capability profile, shared context/safety services, portable skill and Agent Plugin surfaces, onboarding, Doctor, conformance | BB UI, model routing, remote ChatGPT service |
| Dex Lens | Cross-host diagnosis, signed capability catalogue verification/ranking, portable briefs | Dex vault mutation, BB shell |
| new local `dex-bb-plugin` | BB manifest, native skills/tools/CLI/panel and packaging tests | Core capability truth, internal Product Lab |
| `dex-lab-plugin` | Internal dogfood and implementation reference | Public Dex distribution |
| `dex-desktop`, `dex-pi` | Existing product-specific responsibilities | New portability work in this delivery |

## Architecture

### 1. Capability contract

Create a versioned, data-driven registry for these independently testable capabilities:

- local Markdown vault access;
- MCP stdio access;
- Agent Skills discovery;
- session-start and session-end events;
- prompt-submit events;
- guaranteed pre-tool interception;
- post-tool and stop events;
- background scheduling;
- native settings/status UI.

Each harness descriptor states support, adapter location, and delivery mode:

- `automatic`: the host executes the behavior at the required lifecycle point;
- `on_demand`: a tool/skill can execute it when the agent or user asks;
- `guided`: Dex supplies a visible fallback journey;
- `unavailable`: Dex must not imply the behavior happens.

Initial descriptors cover Claude Code, Claude Cowork, Claude Desktop, Codex, Cursor,
Gemini CLI, GitHub Copilot CLI, Pi, generic Agent Plugin v1 clients, ChatGPT Work
companion mode, and BB.

### 2. Shared services

Extract deterministic session boot, person context, and destructive-operation evaluation
from Claude wrappers into `core/`. Expose them through Work MCP. Claude hooks become thin
adapters. Other hook-capable hosts may invoke the same portable entry points.

The safety evaluator is advisory through MCP and automatic only when a verified pre-tool
interceptor calls it before execution.

### 3. Skills and portable plugin

Keep canonical authored skills in their current home for this delivery, but generate the
portable surface from an explicit portability manifest. A skill must be one of:

- portable as written;
- portable after a reviewed adapter transform;
- host-bound and intentionally omitted with a named fallback/reason.

Generation must copy the complete dependency closure for each included skill (instructions,
references, scripts, assets, templates, and eval fixtures as applicable). It must preserve
user-owned `*-custom` directories and reject broken relative references or leaked
host-specific runtime commands.

Package the reviewed portable set as an [Agent Plugin v1.0.0](https://agent-plugins.org/specification)
with root `plugin.json`, `skills/`, and a project-root-safe MCP launcher/config where the
client supports stdio MCP. The same folder also carries native `.codex-plugin` and
`.claude-plugin` manifests, shared trusted-hook wiring, and platform-correct MCP configs.
Pi keeps its native extension; BB keeps its native package. No content fork owns the shared
context or safety truth.

### 4. Onboarding and Doctor

Move harness detection out of prose/tool-name branches into the capability registry. The
installer/onboarding flow should:

1. detect likely installed/active harnesses;
2. let a user accept or override that detection and select more than one;
3. preview the capabilities and limitations for the selected set;
4. provision only supported adapter/config surfaces through the existing provisioning and
   lifecycle ownership contracts;
5. write a local receipt under `System/.dex/`;
6. show the same receipt in Doctor, including remediation for missing pieces.

### 5. Native BB plugin

Build a standalone, local, unreleased plugin using BB's public plugin SDK. Version one:

- discovers/configures a local Dex vault;
- contributes the portable Dex orientation/Doctor skill;
- exposes read-only `status`, `capabilities`, and `brief` tools plus `bb dex ...` CLI;
- shows a small native panel with vault connection, capability mode, and next action;
- consumes signed Core/Lens artefacts rather than re-encoding the catalogue;
- stores only namespaced plugin state and no third-party credentials;
- keeps BB bound to loopback and states that plugins are trusted local code.

Direct vault writes, automation, remote relay setup, marketplace publication, and BB's
experimental provider/host bridge are deferred. A provider would make Dex itself a coding
agent, which is not this product position.

## Test-first delivery lanes

### Lane A — portable contract and generated distribution

1. Add failing capability-registry, adapter-manifest, and plugin-schema tests.
2. Add failing generator dependency-closure, body-portability, custom-preservation, and
   drift tests.
3. Implement registry/generator/manifests.
4. Generate portable output and architecture inventory.

### Lane B — shared runtime services

1. Port and harden deterministic context/safety tests from the closed prototype branches.
2. Implement shared modules.
3. Add Work MCP tools and thin Claude wrappers without removing later session-start logic.
4. Prove wrapper/shared-service parity and existing hook tests.

### Lane C — onboarding and Doctor

1. Add failing detection, multi-selection, receipt, report, and no-overclaim tests.
2. Implement capability-aware onboarding/provisioning.
3. Add Doctor output and remedies.
4. Prove customization/update ownership remains intact.

### Lane D — BB plugin

1. Scaffold an isolated standalone plugin using the public SDK version compatible with the
   installed BB release.
2. Add contract tests before server/UI implementation.
3. Implement read-only tools/CLI/panel and signed artefact consumption.
4. Build the installable local package and verify it against a clean BB test harness/runtime.

### Lane E — end-to-end evidence

1. Run golden journeys for every advertised harness profile.
2. Run Python, hook, script, integration, contract, generated-inventory, PII, founder-content,
   and package gates proportionate to the changed surfaces.
3. Independently inspect the final diffs and overclaim boundaries.
4. Reconcile Mission Control, architecture docs, README, CHANGELOG, and branch/PR evidence.
5. Write the Amazon-style press release and FAQ, marked unreleased.

## Golden journeys

Every profile must prove: discovery, orientation, one read-only Dex action, capability
receipt/Doctor truth, and a safe failure/fallback for one unsupported automatic behavior.

| Harness | Required proof |
| --- | --- |
| Claude Code | Existing hook behavior still works through shared services |
| Claude Cowork | Plugin/skill discovery plus explicit hook/cloud limitations |
| Claude Desktop | Validated MCPB manifest and built `.mcpb`; read-only MCP round trip with explicit no-hook result |
| Codex | Portable skill and MCP discovery; supported hooks call shared entry points |
| Cursor | Native manifest, shared MCP/skills, and translated local session/safety hooks |
| Gemini CLI | Generated complete extension, shared MCP/skills, and translated lifecycle/safety hooks |
| Copilot CLI | Plugin/skill/MCP discovery plus an explicit unavailable result for the unbundled Copilot-specific hook contract |
| Pi | Agent Skill discovery plus guided/MCP-less tool path or extension adapter |
| Agent Plugin client | v1 manifest/schema and relocatable plugin-root behavior |
| ChatGPT Work | Local companion reads files; no claim that web ChatGPT runs local hooks |
| BB | Local install/build, native status panel/tool/CLI, no write or provider claim |

### Evidence captured in this unreleased build

| Surface | Evidence | Remaining release boundary |
| --- | --- | --- |
| Codex | Repo marketplace resolved the package; a temporary isolated Codex home installed and enabled version `1.0.0`; MCP and hook harness tests pass. | No public marketplace submission; Codex IDE is unsupported by the host. |
| Claude Code | `claude plugin validate packages/dex-agent-plugin` passes; shared hook tests pass. | No marketplace install or Cowork upload performed. |
| Claude Desktop | The official MCPB validator accepts the generated manifest; the builder emits an installable `.mcpb`; its staged read-only MCP runtime completes a real round trip. | The headless Devbox cannot exercise the Desktop install UI; live installation remains a release-candidate check. |
| ChatGPT | Uses the same validated OpenAI package and local repo marketplace. | Desktop UI install was not exercised on this headless Devbox; web needs a secured HTTPS MCP endpoint. |
| Cursor | Native plugin manifest, shared skills/MCP, local hook schemas, context injection, and destructive-action refusal pass golden tests. | A live trusted-workspace install remains a release-candidate check; cloud agents do not run `sessionStart`. |
| Gemini CLI | The generated extension archive contains the full shared runtime and skills; staged MCP and translated hook journeys pass. | A live CLI install and trust prompt remain release-candidate checks. |
| Copilot CLI | Root manifest follows the Open Plugin Spec accepted by Copilot; package and schema tests pass. Its incompatible hook schema is now explicitly unavailable rather than overclaimed. | The Copilot binary is not installed on this Devbox, so live CLI installation remains a release-candidate check. |
| Pi | Existing native `dex-pi/extensions/dex/package.json` and lifecycle extension are present in the Pi repository. | The dirty shared Pi checkout was inspected read-only; no Pi package was changed or released. |
| Agent Plugin | v1 schema, Node-to-Python launcher, tools, resources, dependency closure, and Linux deferred-runtime journey pass golden tests. A mandatory macOS/Windows CI matrix is wired. | Exact-commit macOS and Windows evidence belongs to the draft pull request and must be green on the final review head. Mandatory Fable reviews remain required; client-specific hooks stay outside the v1 floor. |
| BB | Standalone head `9686e2266834e194ceef4eeafaf35cc27a812991`; 36 tests, TypeScript, BB `0.40.0`, plugin SDK `0.4.21`, SDK backend/frontend harness, package audit, and tarball checks pass. Exact-head native macOS push and draft-PR runs [32949546856](https://github.com/davekilleen/dex-bb-plugin/actions/runs/32949546856) and [32949551083](https://github.com/davekilleen/dex-bb-plugin/actions/runs/32949551083) are green. Its package and runtime truthfully scope this release to macOS. Private draft PR [dex-bb-plugin#1](https://github.com/davekilleen/dex-bb-plugin/pull/1) requests full-tree review. | Live path install and marketplace release remain undone. BB has no native Windows host; its WSL2 route stays deferred with Linux. |

## Research decisions and sources

- Agent Plugins standardizes skills and MCP, not every host's hooks/UI/distribution:
  [Agent Plugins specification](https://agent-plugins.org/specification).
- OpenAI's universal plugin package supports ChatGPT and Codex surfaces, including
  lifecycle hooks after trust review, but not the Codex IDE extension:
  [packaging](https://developers.openai.com/plugins/build/plugins),
  [surfaces](https://learn.chatgpt.com/docs/plugins), and
  [hooks](https://learn.chatgpt.com/docs/hooks).
- Claude plugins provide skills, hooks, MCP, and other components in Claude Code; Cowork
  accepts Claude plugins but external connectors require a public endpoint:
  [Claude plugin reference](https://code.claude.com/docs/en/plugins-reference) and
  [Cowork guide](https://claude.com/docs/cowork/guide/plugins).
- GitHub Copilot CLI supports plugins and the Open Plugin Spec additively:
  [Copilot CLI plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference).
  Its hooks use a separate versioned, lower-camel-case contract with explicit
  Bash/PowerShell commands, so this release does not reuse the Claude/Codex hook file:
  [Copilot hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference).
- Pi's native extension/skill model is documented separately from MCP:
  [Pi documentation](https://pi.dev/docs/latest).
- BB plugins are full-trust TypeScript packages with skills, tools, CLI, UI, storage, and
  lifecycle surfaces: [BB plugin guide](https://github.com/get-bb/bb/blob/main/packages/templates/src/templates/bb-guide-plugins.md)
  and [plugin SDK](https://github.com/get-bb/bb/blob/main/packages/plugin-sdk/README.md).
- BB is local-first and open source: [getbb.app](https://getbb.app/) and
  [BB repository](https://github.com/get-bb/bb).
- Community marketplace listing is reviewed and separate from direct local/Git/npm
  installation: [BB marketplace](https://github.com/get-bb/marketplace).
- Plugins run with broad local trust and are not a security sandbox; the Dex plugin must
  remain narrow and explicit: [BB configuration](https://github.com/get-bb/bb/blob/main/docs/configuration.md).

## Stop lines

Do not merge shared main, publish a package or plugin, create/submit a marketplace listing,
install for another user, deploy a remote service, ship a release, or represent this work as
live without Dave's explicit approval.
