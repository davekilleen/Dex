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
      "files": [
        {
          "path": ".claude/skills/decision-log/SKILL.md",
          "sha256": "<exact lowercase sha256>",
          "byte_size": 1234
        }
      ],
      "dependencies": [],
      "capabilities": []
    }
  ]
}
```

The publisher declaration pins each file's exact hash and byte size. The
generator rejects stale pins, derives ownership classes and rewind tokens from
the exact release tree, and validates the emitted items through the v1 model
and schema. The first official item declarations live in
`official-capabilities.json`.
