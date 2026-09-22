# Dex portable agent plugin

**Distribution is released; complete host support remains unverified.** The v1.97.13 artifacts establish package availability, not a successful install, trust, workflow, update or removal journey in a particular app. See [the maintained app guide](../../docs/HARNESS-PORTABILITY.md). The tools below do not include task writes, full meeting preparation, Doctor, feedback, onboarding, updates or session-end capture.

The package distributed with Dex v1.97.13 carries Dex's generated work skills, read-only context
tools, and shared safety gate into several agent harnesses. It keeps the Agent
Plugins v1 root contract and also includes native manifests for:

- Codex CLI and desktop (plugins are not currently loaded by the Codex IDE
  extension). The user must review and trust the bundled hooks.
- Claude Code and Claude Cowork. Cowork can use the file/skill/hook surfaces;
  its external connectors require a public remote endpoint, so this local
  stdio MCP bridge is not claimed in Cowork.
- GitHub Copilot CLI through its Open Plugin Spec support. A person installs
  the reviewed local package with `copilot plugin install
  ./packages/dex-agent-plugin`, confirms it in `copilot plugin list`, and
  starts the CLI from the Dex folder. Skills and MCP are native; hooks are
  not claimed. That terminal journey has not been recorded yet. Ubuntu Cloud
  is not a person opening this CLI.
- Cursor through its native manifest and local `sessionStart`/`preToolUse`
  hooks. Cursor cloud agents do not run `sessionStart`.
- Gemini CLI through a separately built extension with Gemini's fixed hook
  schema, generated from these same canonical files.
- Claude Desktop through a separately built and officially validated `.mcpb`;
  Desktop exposes the read-only MCP tools but does not run hooks.
- Other Agent Plugins v1 clients through `plugin.json` and `mcp.json`.

The MCP bridge exposes `boot_today`, `get_person_context`,
`check_safety_gate`, and `dex_harness_profiles`. It is dependency-free,
relocatable, read-only, and uses the same vendored source modules as dex-core.
The safety MCP tool is advisory; only a trusted interceptor that runs before
the action and honors the refusal can enforce it. The
native Codex/Claude `PreToolUse` adapter expresses a refusal, whose actual host
interception and tool coverage still require native verification.

## Release platforms

This package requires Node 20+ and Python 3.11+. Its Node launcher
selects `python3`/`python` on macOS and `py -3`/`python` on Windows without
invoking a shell, so installed paths containing spaces remain one argument.

| Platform | This release |
| --- | --- |
| macOS | Release-ready only after the native CI runtime gate passes. |
| Windows | Release-ready only after the native CI runtime gate passes. |
| Linux | Deferred. The runtime remains testable, but Linux packaging and live-host verification are outside this release. |

The versioned source of truth is `metadata/harnesses/registry.json`. Doctor
reports the current platform boundary alongside the saved harness receipt.

The candidate ChatGPT Work desktop recipe is documented in the maintained app
guide. A real desktop must prove local execution, folder access and the required
runtime; a shared plugin cache is not that evidence. ChatGPT web needs a
separately hosted HTTPS MCP service before it can reach a local Dex vault;
this package does not provide that remote bridge.

Regenerate and verify it from the repository root:

```bash
python3 scripts/generate-agents-skills.py
python3 scripts/generate-portable-plugin.py
python3 scripts/generate-portable-plugin.py --check
python3 scripts/verify-portable-plugin-runtime.py
python3 scripts/build-portable-harness-artifacts.py --output-dir build/portable-artifacts
```
