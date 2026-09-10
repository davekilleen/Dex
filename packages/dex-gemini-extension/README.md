# Dex for Gemini CLI

This source overlay builds the Gemini CLI extension distributed with v1.97.13. The
artifact builder combines it with Dex's canonical skills, read-only MCP runtime,
and shared context/safety bridge so those files do not drift into a fork.

## Build and install locally

From the repository root:

```sh
npm ci --ignore-scripts
python3 scripts/build-portable-harness-artifacts.py --output-dir build/portable-artifacts
gemini extensions install build/portable-artifacts/dex-gemini-extension
```

Restart Gemini CLI after installation and open the full Dex folder. Review the
extension's `SessionStart` and `BeforeTool` hooks before consenting. The extension
requires Node 20+ and Python 3.11+. Package distribution is released; this developer-preview install journey is not
certified native host support or marketplace publication.
