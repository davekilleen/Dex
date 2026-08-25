# `.agents/` — generated cross-harness skill surface (Tier 2)

`.claude/skills/` remains Dex's canonical skill source. The adapters under
`.agents/skills/` are generated for harnesses that understand the Agent Skills
layout but do not load Claude Code's settings or hooks.

```bash
python3 scripts/generate-agents-skills.py          # write adapters
python3 scripts/generate-agents-skills.py --check  # CI drift gate
```

The generator reads `core/harnesses/portability.json`, strips Claude-only
frontmatter, copies each portable skill's complete resource tree (including
`scripts/`, `references/`, `assets/`, and `evals/`), and rewrites a canonical
`.claude/skills/...` reference only after proving the destination exists.
Missing local resources, transitive `.claude/flows`/hook references, and
host-only body commands fail closed. Skills classified `claude-only`,
`conditional`, or `broken` remain documented in the manifest but are not
silently presented as portable.

User-authored `*-custom/` directories are never generated, deleted, or
rewritten. They remain user-owned even when a release regenerates this tree.

The generated adapters are a Tier 2 surface: vault files and in-turn MCP
tools are available when the host provides them, while Claude Code's Tier 3
hooks, injectors, and session lifecycle are intentionally not claimed here.
