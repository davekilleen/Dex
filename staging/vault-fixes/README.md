# Staging: fixes to apply in Dave's Vault (NOT dex-core product code)

This directory holds corrected copies of files whose live home is Dave's
private Vault, not dex-core. They are staged here because the build agent
works read-only against the Vault. The orchestrator applies them vault-side
during go-live (see the funnel go-live checklist in
`heydex-website/docs/funnel-go-live-checklist.md`, step "Apply the vault-side
telemetry fix").

| File | Live destination | What changed |
|---|---|---|
| `delight-capture.cjs` | `<vault>/.claude/hooks/delight-capture.cjs` | The hook JSON.parsed the whole transcript file, but Claude Code transcripts are JSON-Lines — the parse threw on line one, the catch swallowed it, and the hook captured nothing for 10 weeks. Now parses line by line (legacy single-array transcripts still supported), reads text out of content-block arrays, ignores tool_result blocks so file contents cannot fake delight, and runs the milestone check even when no user messages are found (it was unreachable behind the early exit). |

Verification before applying: from this directory run

```bash
node test-delight-capture.cjs
```

All assertions must pass. To apply: copy the file over the vault copy
byte-for-byte, then re-run the test pointing CLAUDE_PROJECT_DIR at a temp
dir if you want a second proof. The hook's registration in
`.claude/settings.json` (Stop event) is already correct and unchanged.
