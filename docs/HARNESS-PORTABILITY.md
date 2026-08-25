# Use Dex from another agent harness

> **Unreleased build.** These packages are implemented and locally verified on
> `codex/harness-portable-dex`. They have not been merged, published, submitted
> to a marketplace, or released to users.

Dex is the durable vault and capability layer; the harness is the application
or agent you use to talk to it. Start every host from the **full Dex folder** so
the root instructions and vault are in scope. Onboarding detects likely hosts,
lets the user select more than one, previews the exact capability modes, and
stores the confirmed selection at `System/.dex/harness-profile.json`. Doctor
reports the same receipt.

## What is shared

`packages/dex-agent-plugin/` contains one generated package with:

- the portable Dex skill catalogue;
- read-only `boot_today`, `get_person_context`, `check_safety_gate`, and
  `dex_harness_profiles` MCP tools;
- byte-identical vendored copies of the canonical context and safety modules;
- SessionStart context and PreToolUse safety hooks for hosts that can genuinely
  run them;
- native OpenAI and Claude manifests plus the Agent Plugins v1 root contract.

The safety MCP result is advisory. It becomes an enforced refusal only where a
trusted PreToolUse hook intercepts the action before it runs.

## Local installation journeys

These are developer-preview journeys, not customer release instructions.

| Harness | Local package journey | Honest boundary |
| --- | --- | --- |
| Codex CLI / desktop | From the Dex root, run `codex plugin marketplace add .`, then `codex plugin add dex@dex-unreleased`. Review and trust the hooks, then start a new task. | Codex IDE extensions do not load plugins. |
| ChatGPT desktop | Restart the app, open the Plugins Directory, choose **Dex (unreleased local build)**, install Dex, review its hooks, and start a new chat. | ChatGPT web cannot use this local stdio server; a secured HTTPS MCP service is separate future work. |
| Claude Code | Run `claude plugin validate packages/dex-agent-plugin`, then test with `claude --plugin-dir ./packages/dex-agent-plugin` before creating a private marketplace entry. | The shared package maps two lifecycle guarantees; Claude's complete mature Dex hook suite remains the reference. |
| Claude Cowork | Upload/install the reviewed Claude plugin package and grant the full Dex folder. | Cowork external connectors require a public internet endpoint, so the local stdio MCP server is not claimed. |
| GitHub Copilot CLI | Run `copilot plugin install ./packages/dex-agent-plugin`, inspect the installed plugin, then open the full Dex folder. | Confirm hook support in the installed CLI version before relying on automatic enforcement. |
| Agent Plugins v1 client | Install the folder using root `plugin.json` and `mcp.json`. | The open specification standardizes skills and MCP, not every host lifecycle. |
| Pi | Use the native `dex-pi/extensions/dex` package and open the full Dex folder. | Pi has no built-in MCP client; its extension supplies native tools and lifecycle events instead. |
| BB | Install the separately built `bb-plugin-dex` package from a reviewed local path and select the vault in settings. | Version one is read-only: status, capabilities, brief, CLI, and panel; no jobs, writes, provider bridge, or marketplace release. |

## Acceptance journey

After installation, verify these outcomes in a fresh task:

1. The host can find at least one Dex skill and the capability registry.
2. `boot_today` reads the selected vault without writing anything.
3. `get_person_context` returns a known person or a clean `found: false` result.
4. `check_safety_gate` refuses a synthetic `rm -rf /` proposal.
5. If hooks are supported and trusted, SessionStart injects current Dex context
   and PreToolUse blocks that synthetic destructive proposal before execution.
6. Doctor reports the confirmed harness receipt and does not call a guided or
   unavailable feature automatic.

Do not run an actual destructive command to test a hook. The package's hook and
MCP test harnesses submit the proposal as data only.

## Capability truth

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
- [GitHub Copilot CLI plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)
- [Agent Plugins v1 specification](https://agent-plugins.org/specification)
- [Pi documentation](https://pi.dev/docs/latest) and [BB](https://getbb.app/)
