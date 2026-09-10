# Use Dex from another agent harness

> **Distribution baseline: v1.97.13 (7 September 2026).** Portable package files
> are present in the released vault bundle; separate Claude Desktop and Gemini
> artifacts are also published. Complete supported install, trust, workflow,
> update and removal journeys in new apps remain **unverified**. Package
> publication, conformance tests and saved profile receipts are distinct evidence.
> [Release](https://github.com/davekilleen/dex/releases/tag/v1.97.13).

Dex is the durable vault and capability layer; the harness is the application
or agent you use to talk to it. For a local developer preview, explicitly select the **existing full Dex folder**
and confirm the actual host has permission to read it. Installing a plugin does
not create a vault or grant access. Onboarding detects likely hosts,
lets the user select more than one, previews the exact capability modes, and
stores the confirmed selection at `System/.dex/harness-profile.json`. Doctor
reports the same receipt.

## Platform boundary for this release

| Platform | Release contract | Required runtime proof |
| --- | --- | --- |
| macOS | Native CI required on each review head | A native GitHub runner must complete MCP initialization, tool discovery, SessionStart context, and PreToolUse refusal through the installed launcher shape before this platform can be called release-ready. |
| Windows | Native CI required on each review head | The same native runtime round trips must pass with a Windows Python executable path before this platform can be called release-ready. |
| Linux | Deferred | The runtime is still exercised on the Devbox, but Linux packaging and live-host verification are explicitly outside this release. |

Exact-commit CI evidence belongs to the pull request and release record. Native
CI protocol checks do not certify a complete user journey in the installed app.

The portable Agent Plugin package requires Node 20+ and Python 3.11+. The Claude
Desktop MCPB is the documented exception: it declares Node.js >=18, supplied by
Claude Desktop, and still requires Python 3.11+. The supported-platform contract
lives in `core/harnesses/registry.json`, is copied into the package, and is
reported by Doctor. Native CI evidence lives in the workflow run for the exact
commit; the registry's `release_ready` requirement does not mean an unrun branch
has already passed that evidence gate.

## What is shared

`packages/dex-agent-plugin/` contains one generated package with:

- the portable Dex skill catalogue;
- read-only `boot_today`, `get_person_context`, `check_safety_gate`, and
  `dex_harness_profiles` MCP tools;
- byte-identical vendored copies of the canonical context and safety modules;
- SessionStart context and PreToolUse safety hooks for hosts that can genuinely
  run them;
- native OpenAI, Claude, and Cursor manifests plus the Agent Plugins v1 root
  contract;
- separate, generated Gemini CLI and Claude Desktop artifacts where their
  package contracts cannot safely share the same hook manifest.

The safety MCP result is advisory. It becomes an enforced refusal only where a
trusted PreToolUse hook intercepts the action before it runs.

## Local installation journeys

These are unverified developer-preview recipes, not supported customer install instructions. Local marketplace names such as `dex-unreleased` are literal candidate identifiers retained in the generated metadata; they do not mean the v1.97.13 files were never distributed. Do not run preview setup over a working vault without reviewing its scope. The supported new-app install CTA remains withheld until native acceptance.

Build the separate installable artifacts from the same canonical package:

```sh
npm ci --ignore-scripts
python3 scripts/build-portable-harness-artifacts.py --output-dir build/portable-artifacts
```

The builder validates and packs `dex-claude-desktop.mcpb`, builds the complete
`dex-gemini-extension/` install directory and deterministic archive, and writes
`artifacts.json` with unreleased status, sizes, and SHA-256 checksums. It does
not publish, install, or release anything. The stable and beta release jobs run
the same builder with the matching channel recorded in `artifacts.json`, then
attach both archives and the index through Dex's draft-first, byte-verified
publication path. No attachment is public until the release itself is approved
and the final publication step succeeds.

| Harness | Local package journey | Honest boundary |
| --- | --- | --- |
| Codex CLI / desktop | From the Dex root, run `codex plugin marketplace add .`, then `codex plugin add dex@dex-unreleased`. Review and trust the hooks, then start a new task. | Codex IDE extensions do not load plugins. |
| ChatGPT Work desktop | Copy `packages/dex-agent-plugin` to `~/.codex/plugins/dex`, add `~/.agents/plugins/marketplace.json` with `source.path` `./.codex/plugins/dex` (relative to the home marketplace root, not the `.agents/plugins` folder), restart the ChatGPT desktop app, install Dex from **Dex (unreleased local build)**, review its hooks, start a new Work chat with Work locally selected, and grant the Dex vault folder. If Work is already opened on this Dex checkout, the repo marketplace at `.agents/plugins/marketplace.json` can be used instead of the personal copy. | ChatGPT web cannot use this local plugin for a local vault. A person must complete this on a real desktop; Ubuntu Cloud is not that journey. A shared plugin cache on disk is not ChatGPT Work proof. Folder access, installed runtime dependencies, workflows, permission refusals and update/removal still need native proof. |
| Claude Code | Run `claude plugin validate packages/dex-agent-plugin`, then test with `claude --plugin-dir ./packages/dex-agent-plugin` before creating a private marketplace entry. | The shared package maps two lifecycle guarantees; Claude's complete mature Dex hook suite remains the reference. |
| Claude Desktop | Select `build/portable-artifacts/dex-claude-desktop.mcpb` in **Settings > Extensions > Advanced settings > Install Extension**, then select the Dex vault during configuration. | The officially validated desktop bundle exposes local read-only MCP tools. Chat does not run hooks, and Python 3.11+ remains required. |
| Claude Cowork | Upload/install the reviewed Claude plugin package and grant the full Dex folder. | Cowork external connectors require a public internet endpoint, so the local stdio MCP server is not claimed. |
| GitHub Copilot CLI | From the Dex checkout, run `copilot plugin install ./packages/dex-agent-plugin`. Confirm Dex in `copilot plugin list`. Start the CLI from the Dex folder so the vault is the working directory. | Skills and MCP use the open package. Hooks are not bundled. A person must do this in a real terminal; Ubuntu Cloud is not that journey. Detection tests and CI are not a live install. |
| Cursor | Copy or link `packages/dex-agent-plugin` to `~/.cursor/plugins/local/dex`, reload Cursor, and approve the native hooks. | The candidate declares local context and safety hooks; native behavior remains unverified. Cursor cloud agents do not run `sessionStart`, so that lifecycle guarantee is local-only. |
| Gemini CLI | Run `gemini extensions install build/portable-artifacts/dex-gemini-extension`, approve its hooks, and restart Gemini CLI in the full Dex folder. | Gemini's fixed hook file uses a different schema, so Dex builds a separate complete artifact from the same canonical sources. |
| Agent Plugins v1 client | Install the folder using root `plugin.json` and `mcp.json`. | The open specification standardizes skills and MCP, not every host lifecycle. |
| Pi | Use the native `dex-pi/extensions/dex` package from the pinned [`dex-pi` commit `5bf33ad7b23a06a890b25445cb1b4f4077b2ac19`](https://github.com/davekilleen/dex-pi/tree/5bf33ad7b23a06a890b25445cb1b4f4077b2ac19) and open the full Dex folder. | Pi has no built-in MCP client; its extension supplies native tools and lifecycle events instead. Core verifies the pinned manifest and source-level lifecycle markers when the checkout is available; live installation remains a release-candidate check. |
| BB | Candidate work paused; no install recommendation. | Separate unreleased read-only package; no supported host or marketplace claim. |

## Acceptance journey

After installation, verify these outcomes in a fresh task:

1. The host can find at least one Dex skill and the capability registry.
2. `boot_today` reads the selected vault without writing anything.
3. `get_person_context` returns a known person or a clean `found: false` result.
4. `check_safety_gate` refuses a synthetic `rm -rf /` proposal.
5. In a verified Codex, Claude, Cursor, or Gemini hook package, session start
   injects current Dex context and the host's pre-tool event blocks that
   synthetic destructive proposal before execution.
6. Doctor reports the confirmed harness receipt and does not call a guided or
   unavailable feature automatic.

Do not run an actual destructive command to test a hook. The package's hook and
MCP test harnesses submit the proposal as data only.

## Capability truth

Modes must be read per surface and per operation. `automatic` requires a trusted
host event; `on_demand` requires a registered tool; `guided` needs explicit user
steps; `unavailable` has no implemented route. A declared candidate mode is not
native proof. The released bridge exposes four read-only/advisory tools only.

| Surface | Candidate mode and scope | Evidence boundary |
| --- | --- | --- |
| Claude Code full-vault setup | Automatic configured session/tool hooks; on-demand full skills/services | Existing reference route; plugin subset is not the entire hook suite. |
| Cursor full-vault setup | On-demand configured tools/skills | Existing route; portable local-hook candidate requires separate proof. |
| Codex CLI and desktop | Candidate automatic boot/gate hooks; on-demand four-tool bridge; guided finish | Native complete journey unverified; task writes, feedback, Doctor and updater absent from this bundle. |
| ChatGPT Work desktop | Candidate on-demand bridge after local execution and folder grant | Native installation, tools and workflows unverified. |
| Claude Desktop chat | Candidate on-demand four-tool MCPB; automatic hooks unavailable | Artifact validation is not an installed desktop journey. |
| Claude Cowork | Candidate skill/plugin route; local tool/runtime scope unverified | External connectors cannot reach the local stdio server as packaged. |
| Copilot CLI | Candidate on-demand skills/MCP; hooks unavailable in this package | Complete native journey unverified; no VS Code/app support inferred. |
| Gemini CLI | Candidate automatic SessionStart/BeforeTool; on-demand read tools | Separate artifact; native complete journey unverified. |
| Agent Plugins v1 clients | Candidate on-demand skills/MCP | Each concrete client needs proof; no universal lifecycle guarantee. |
| Pi | Candidate native extension tools/events | Separate unreleased extension; native install remains unverified. |
| BB | Unavailable as a supported route; candidate paused | No install or activation recommendation. |
| Codex IDE extension, ChatGPT web | This local plugin route unavailable | No local-vault bridge or complete journey claimed. |

The current matrix is generated from `core/harnesses/registry.json`, not this
prose. Each row is explicitly `automatic`, `on_demand`, `guided`, or
`unavailable`. See [the capability contract](architecture/HARNESS-CAPABILITY.md)
and [hook inventory](architecture/HOOK-INVENTORY.md) for the design boundary.

First-party references used for this build:

- [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins)
  and [supported ChatGPT/Codex surfaces](https://learn.chatgpt.com/docs/plugins)
- [OpenAI hook behavior and trust](https://learn.chatgpt.com/docs/hooks)
- [Claude plugin reference](https://code.claude.com/docs/en/plugins-reference)
  and [Cowork plugin guide](https://claude.com/docs/cowork/guide/plugins)
- [Claude Desktop local extensions](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)
  and [MCP Bundles](https://blog.modelcontextprotocol.io/posts/2025-11-20-adopting-mcpb/)
- [GitHub Copilot CLI plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)
  and [Copilot's distinct hooks contract](https://docs.github.com/en/copilot/reference/hooks-reference)
- [Cursor plugins](https://cursor.com/docs/plugins) and
  [Cursor hooks](https://cursor.com/docs/hooks)
- [Gemini CLI extensions](https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/reference.md)
  and [Gemini hooks](https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/reference.md)
- [Agent Plugins v1 specification](https://agent-plugins.org/specification)
- [Pi documentation](https://pi.dev/docs/latest) and [BB](https://getbb.app/)
