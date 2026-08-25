# Dex Agent Plugin

This package targets Agent Plugins specification v1.0.0. It contains the
generated Tier 2 Agent Skills surface and a relocatable stdio MCP bridge. The
plugin uses only `./` paths and `${PLUGIN_ROOT}` / `${PLUGIN_DATA}` placeholders
so a conforming client can install it anywhere.

The package deliberately does not claim Claude Code hooks, commands, agents,
or session lifecycle behavior; those remain client-specific extensions.

Regenerate and verify it from the repository root:

```bash
python3 scripts/generate-agents-skills.py
python3 scripts/generate-portable-plugin.py
python3 scripts/generate-portable-plugin.py --check
```

