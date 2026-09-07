# GitHub hook adapter candidate

This is an experimental translator contract, not verified GitHub host support.
The CLI, VS Code and GitHub Copilot app remain separate acceptance rows. No
authenticated host session, installation, Windows/macOS execution or app trace
was run for this change.

## Source and assembly

`core/harnesses/copilot_hooks.py` translates host inputs directly into
`core.gates.safety.evaluate_hook_payload`; context comes from
`core.context.session_boot.build_session_boot`, with the same
`core.vault_selection.select_vault` policy. There is no second policy engine,
transcript reader, task writer, autocommit or checkpoint implementation here.

The assembler must copy these canonical files, preserving their relative paths:

- `core/{__init__,paths,path_safety,vault_selection}.py` into `runtime/core/`.
- `core/gates/{__init__,safety}.py` into `runtime/core/gates/`.
- `core/context/{__init__,person_context,session_boot}.py` into `runtime/core/context/`.
- `core/harnesses/{__init__,copilot_hooks}.py` into `runtime/core/harnesses/`.
- `core/harnesses/templates/copilot/dex-copilot-hook.mjs` into `bin/`, beside the
  existing `dex-launcher-lib.mjs`. The shim reuses its Python resolution contract.

The two JSON source templates in that directory are alternatives. The CLI
template selects `--surface copilot-cli`; the VS Code template selects
`--surface vscode`. Both pass the configured event explicitly. This is required
because native CLI events omit their name from the input, while CLI compatibility
payloads overlap VS Code payloads. Do not infer surface from a matching schema.

Do not activate either template as a universal GitHub hook configuration. A
surface-specific assembly/install step must select one, avoid duplicate hooks,
and prove discovery in that host. The Agent Plugins 1.0 location is
`com.github.copilot/hooks/hooks.json`; `${PLUGIN_ROOT}` expands to the installed
package. GitHub-specific component discovery and the shared namespace are
documented in the [VS Code plugin reference](https://code.visualstudio.com/docs/agent-customization/agent-plugins).
The root schema remains Agent Plugins 1.0; a top-level portable `hooks` manifest
field is not a substitute for its client namespace.

## Protocol boundary

The CLI adapter accepts native camelCase event inputs (`toolName`, `toolArgs`),
including object arguments serialized as JSON, and PascalCase compatibility
inputs (`tool_name`, `tool_input`). Denials and session context use the CLI's
flat response envelope in both modes. Native `apply_patch` and compatibility
`Edit` patch data use the shared patch target parser. The documented event
configuration version is 1. See the [GitHub hook reference](https://docs.github.com/en/copilot/reference/hooks-reference).

VS Code uses `hookSpecificOutput` for a tool refusal and session context. The
adapter normalizes `filePath` and related camelCase path fields, checks file
arrays and replacement batches, and recognizes the documented file/terminal
tool spellings. Matchers are omitted: filtering happens inside the adapter.
See [VS Code hook configuration](https://code.visualstudio.com/docs/agent-customization/hooks)
and its [event reference](https://code.visualstudio.com/docs/agents/reference/hooks-reference).

An accepted pre-tool proposal returns `{}`, preserving the host's normal
permission flow instead of automatically approving execution. Invalid JSON,
duplicate keys, conflicting event/input aliases, unknown envelope fields,
unknown tool schemas and uninspectable targets refuse. Opaque MCP schemas are
also refused; actual MCP names/arguments must be captured and reviewed before
adding them. This limitation prevents claiming a complete GitHub Dex workflow.
Proposed commands and writes are never executed by the adapter or its tests.

Relative targets require the host's `cwd`. A configured vault and a conflicting
working directory refuse; a descendant directory is accepted. VS Code's
optional missing `cwd` is refused for pre-tool events. Session start without
`cwd` requires an existing vault environment binding, avoiding plugin-cache
fallback. Unknown schema evolution therefore fails conservatively until reviewed.

The CLI's `sessionEnd` and `agentStop` are distinct. VS Code's `Stop` does not
establish session termination; its documented SessionStart source is `new`.
Finish events currently validate and return `{}` without persistence. Do not
advertise checkpoint or resume-context parity from these no-op handlers.

## Failure limits and acceptance

The Node shim captures one final checker response. Crashes, missing runtime
dependencies, invalid/unknown outputs and an eight-second child timeout become
a denial with exit 2. It never forwards private arguments, paths or tracebacks.
The source templates give the host fifteen seconds.

This does not guarantee interception: CLI command-hook timeouts fail open,
HTTP hook failures fail open, and invalid/empty final output can fall through.
If the outer launcher stalls, never starts, is disabled, or the host ignores
the hook, its inner deadline cannot help. These are documented host limits,
not failures this wrapper can override. Core-owned mutations must retain their
own service-level checks. Shared shell checks recognize known patterns; they
are not a shell sandbox or a proof of PowerShell-language coverage.

Before any supported-host claim, capture real CLI, VS Code and app traces;
test selected/decoy vaults, denial sentinel non-creation, ordinary allowed
controls, hook crash/timeout, duplicate installations, disable/update/remove,
and the intended workflow. Record exact app, extension, CLI and OS builds.
App behavior is unknown until observed; CLI reuse is not app evidence.

The CLI reserves `/feedback` for GitHub feedback and documents plugin-qualified
skill names such as `/my-plugin/search`. With the current package name, test
`/dex-agent-plugin/feedback` and prove the Dex intake receipt before documenting
it as working. This is a candidate invocation, not an observed result. See the
[CLI command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference).

Official references were re-read on 7 September 2026. GitHub's online hook and
command references are unversioned; the VS Code pages display 2 September 2026
and hooks remain Preview. These document dates do not establish a minimum
working product build.
