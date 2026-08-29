# Dex for any MCP app

This folder is the unpublished npm-shaped package for Dex's already-proven
read-only tools. After Dave publishes, a person can point any MCP app at one
line. Until then, the package stays local, checksummed, and unreleased.

## What a person can do after Dave publishes

Add this one line in an MCP app that can install from the official catalogue:

```text
io.github.davekilleen/dex
```

Or start the same server from a terminal:

```sh
DEX_VAULT_PATH="/path/to/your/Dex" npx -y dex-mcp
```

Point `DEX_VAULT_PATH` at the Dex folder on that computer. The server can read
today's context, look up a person, list host support, and refuse a destructive
command. It cannot write the vault.

## What is true now

This package is packed and checked on the review branch. It is not on npm. It is
not in the public catalogue. This runner will not create an npm account, will
not publish, and will not invent the ChatGPT Work folder grant.

To pack and check locally without publishing:

```sh
python3 scripts/build-mcp-registry-artifact.py --output-dir build/mcp-registry-artifact
```

The builder writes a `.tgz`, a SHA-256 sidecar, and an `unreleased` index. It
only runs `npm publish --dry-run` and `mcp-publisher` with `--dry-run` or
`validate`.
