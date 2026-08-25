# Dex portable agent plugin

One unreleased package carries Dex's generated work skills, read-only context
tools, and shared safety gate into several agent harnesses. It keeps the Agent
Plugins v1 root contract and also includes native manifests for:

- Codex CLI and desktop (plugins are not currently loaded by the Codex IDE
  extension). The user must review and trust the bundled hooks.
- Claude Code and Claude Cowork. Cowork can use the file/skill/hook surfaces;
  its external connectors require a public remote endpoint, so this local
  stdio MCP bridge is not claimed in Cowork.
- GitHub Copilot CLI through its Open Plugin Spec support.
- Other Agent Plugins v1 clients through `plugin.json` and `mcp.json`.

The MCP bridge exposes `boot_today`, `get_person_context`,
`check_safety_gate`, and `dex_harness_profiles`. It is dependency-free,
relocatable, read-only, and uses the same vendored source modules as dex-core.
The safety MCP tool is advisory unless the host calls it before acting; the
native Codex/Claude `PreToolUse` hook can actively refuse known-dangerous work.

ChatGPT desktop can load compatible local plugins and skills. ChatGPT web needs
a separately hosted HTTPS MCP service before it can reach a local Dex vault;
this repository does not claim that remote bridge yet.

Regenerate and verify it from the repository root:

```bash
python3 scripts/generate-agents-skills.py
python3 scripts/generate-portable-plugin.py
python3 scripts/generate-portable-plugin.py --check
```
