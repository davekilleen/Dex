# Dex for Claude Desktop

This source directory becomes the unreleased `dex-claude-desktop.mcpb` local
extension. It exposes the read-only Dex MCP tools and asks the user to select
their Dex folder during installation. Claude Desktop chat does not run lifecycle
hooks, so this artifact makes no hook or automatic-safety claim.

## Build and inspect locally

From the repository root:

```sh
npm ci --ignore-scripts
python3 scripts/build-portable-harness-artifacts.py --output-dir build/portable-artifacts
node_modules/.bin/mcpb info build/portable-artifacts/dex-claude-desktop.mcpb
```

On Windows, use `python` in place of `python3` when that is the installed Python
launcher. The bundle requires Python 3.11+ and Node.js >=18; Claude Desktop
supplies the Node runtime, so no separate Node installation is needed for this
artifact.

To test the reviewed artifact without publishing it, open Claude Desktop and use
**Settings > Extensions > Advanced settings > Install Extension**. Select the
Dex folder when prompted. This developer-preview journey is not a release.
