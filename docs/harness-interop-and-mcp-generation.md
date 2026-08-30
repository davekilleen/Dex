# Harness interoperability & MCP config generation

Dex keeps a **single source of truth** for MCP server definitions and turns it into
whatever config your harness actually needs. Point the same vault at Claude Code,
Cursor, opencode, or any MCP client — the profile and servers travel with the vault.

## The model

- **Author** every server once in `System/.mcp.json.example` (templated with
  `{{VAULT_PATH}}`).
- **Generate** per-harness config with `scripts/generate-harness-config.py`.
- **Connect** that vault from any harness; the harness reads its own native config,
  all of which resolves to the same in-vault MCP servers.

Only servers whose `env` values fully resolve are emitted. A server holding an
unresolved `{{...}}` placeholder (e.g. an API key you haven't configured) is treated
as optional/secret and skipped — the same rule `core/provision.cjs#configuredMcp`
already uses, so Claude and opencode stay consistent.

## Usage

Run from anywhere; the vault is detected via `--vault`, `$VAULT_PATH`, or by walking
up for `System/.mcp.json.example`.

```bash
PY=".venv/bin/python"        # or system python3 (no third-party deps)

# .mcp.json  -> Claude Code, Cursor, any stdio MCP client
$PY scripts/generate-harness-config.py --format mcp --write .mcp.json

# opencode    -> splices the "mcp" block into the vault's opencode.json
$PY scripts/generate-harness-config.py --format opencode --write opencode.json

# inspect    -> what servers are available in this vault
$PY scripts/generate-harness-config.py --format list
```

Options: `--format {mcp,opencode,list}`, `--vault <path>`, `--include <name...>`,
`--exclude <name...>`, `--write <path>` (relative to the vault, or absolute).

## Wiring per harness

### Claude Code / Cursor (`.mcp.json`)

The `mcp` format is the standard `{"mcpServers": { ... }}` shape with `stdio` servers.
`provision.cjs` already materialises this at onboarding; regenerate it any time you
edit `System/.mcp.json.example`:

```bash
$PY scripts/generate-harness-config.py --format mcp --write .mcp.json
```

### opencode (`opencode.json`)

Write straight into the project `opencode.json`; the tool splices the generated
block into the top-level `mcp` key and leaves `agent`, `instructions`, and any
hand-added MCP entries that aren't this vault's own servers untouched:

```bash
$PY scripts/generate-harness-config.py --format opencode --write opencode.json --exclude slack-mcp
```

(`slack-mcp` is excluded here because it needs a token before it can connect;
drop the flag once Slack is configured.) Server names are the canonical ones from
the template (`work-mcp`, `calendar-mcp`, `session-memory`, …), which is what the
skills reference, so opencode tool names come out as `work-mcp_<tool>`.

`opencode.json` holds machine-specific absolute paths, so it is gitignored. The
tracked seed is `opencode.json.example` (agent persona + instructions, no `mcp`);
on a fresh clone the command above creates `opencode.json` from it.

Skills are ported by `.scripts/port-skills-to-opencode.py` into
`.opencode/skill/<name>/SKILL.md` (frontmatter trimmed to what opencode reads);
the Dex persona and operating rules live in `opencode.json`'s `dex` agent and
`.opencode/AGENTS.md`.

### Safety guard

`.claude/hooks/dex-safety-guard.sh` (a Claude Code `PreToolUse` hook) is ported as
the auto-discovered plugin `.opencode/plugin/dex-safety-guard.js`, with the same
rules and reasons: hard blocks for raw Git repair during a live vault migration,
recursive deletes of root/home, disk wipes, force-push to `main`/`master`, SQL
`DROP`, `gh repo delete`, and the non-preferred scraper MCPs; warnings (allowed,
prefixed onto the tool output) for `chmod 777` and `kill -9`. A block is a thrown
error from `tool.execute.before`, which opencode reports to the model as the tool's
failure. It has no dependencies; `node scripts/test-opencode-safety-guard.mjs`
exercises every rule.

The remaining Claude Code hooks (person/company context injection, session-start
sweeps, `ensure-mcp-user-scope`, which only concerns `claude mcp add`) are not
ported.

Each server becomes `{"type": "local", "command": [<python>, <server.py>],
"enabled": true, "environment": {...}}` with absolute paths, so it works regardless
of which directory opencode launches from. The generated block validates cleanly
against `https://opencode.ai/config.json` (verified).

### Any other MCP client

The `.mcp.json` output is a spec-compliant `mcpServers` document; import it into any
client that reads that shape, or use `--format list` to drive your own launcher.

## Profile portability

Your identity context lives in `System/user-profile.yaml` (created from
`System/user-profile-template.yaml` during onboarding) and is **vault-scoped**, so it
moves with the vault from machine to machine and harness to harness. The MCP servers
that read it (`work`, `calendar`, `career`, `session-memory`, …) are the same files
regardless of which harness launched them.
