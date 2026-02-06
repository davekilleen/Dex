# Pi-Generated Skills

This directory contains auto-generated skill stubs for Pi extensions.

## How It Works

1. The `pi-extensions-sync.cjs` hook runs on SessionStart
2. It scans `.pi/extensions/` for TypeScript files
3. For each extension, it parses:
   - JSDoc comments for descriptions
   - `pi.registerTool()` calls for tools
   - `pi.registerCommand()` calls for commands
4. Generates a skill stub in this directory
5. Updates `.claude/pi-extensions-registry.json`

## Directory Structure

```
pi-generated/
  pi-[extension-id]/
    SKILL.md          # Auto-generated skill stub
```

## Important Notes

- **Do not manually edit** files in this directory
- Changes will be overwritten on next sync
- Delete an extension from `.pi/extensions/` to remove its skill
- Run `/pi-tools sync` to force refresh

## Skill Naming Convention

Pi extension skills use the `pi:` prefix:
- `pi:dex-mcp-bridge` - MCP bridge extension
- `pi:custom-tool` - Custom extension

This distinguishes them from native Dex skills.

## Related

- **Source:** `.pi/extensions/` - TypeScript extension files
- **Registry:** `.claude/pi-extensions-registry.json` - Sync metadata
- **Hook:** `.claude/hooks/pi-extensions-sync.cjs` - Sync logic
- **Command:** `/pi-tools` - View and manage extensions
