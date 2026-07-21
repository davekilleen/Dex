# Release catalog item declarations

This is the publisher-owned source of truth for lifecycle catalog items. The
release builder reads every `*.json` file here in filename order and emits the
canonical `System/.release-catalog.json` through the B1 model and schema.

Each source file is a closed document:

```json
{
  "catalog_source_version": 1,
  "items": [
    {
      "id": "decision-log",
      "kind": "skill",
      "version": "1.0.0",
      "files": [".claude/skills/decision-log/SKILL.md"],
      "dependencies": [],
      "capabilities": []
    }
  ]
}
```

The generator derives hashes, ownership classes, and rewind tokens from the
exact release tree. B2 intentionally ships no items; the first official item
declarations land in D3.
