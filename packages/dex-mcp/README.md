# Dex for any MCP app

This folder is the unpublished npm-shaped package for Dex's already-proven
read-only tools. After a public catalogue publish, a person can point any MCP
app at one line. Until then, the package stays local, checksummed, and
unreleased.

## What a person can do now

Pack the box locally. Then, before anything is published, ask it what was
decided about a topic, or what was decided lately with no topic. It answers
from that Dex folder's own decision record and names the file it came from.
Ask it what is still open with people: it lists every unchecked to-do from
person pages, each naming the person and the page, or an honest sentence if
none. Ask it who is in today's plan: it answers with each named person's
recorded role, company, last interaction, and every open item, each row
naming the person page, in plan order. Missing fields stay empty.

## What a person can do after a public catalogue publish

Add this one line in an MCP app that can install from the official catalogue:

```text
io.github.davekilleen/dex
```

Or start the same server from a terminal:

```sh
DEX_VAULT_PATH="/path/to/your/Dex" npx -y dex-mcp
```

Point `DEX_VAULT_PATH` at the Dex folder on that computer. The server can read
today's context, look up a person, list host support, refuse a destructive
command, answer what was decided about a topic or what was decided lately
with no topic from that folder's own decision record, list what is still
open with people from person pages, and say who is in today's plan from the
plan and person pages. It cannot write the vault.

## What is true now

This package is packed and checked on the review branch. It is not on npm. It is
not in the public catalogue. This runner will not create an npm account, will
not publish, and will not invent the ChatGPT Work folder grant.

To pack and check locally without publishing:

```sh
python3 scripts/build-mcp-registry-artifact.py --output-dir build/mcp-registry-artifact
```

The builder writes a `.tgz`, a SHA-256 sidecar, and an `unreleased` index. It
only runs `npm publish --dry-run` and `mcp-publisher validate`. It never
publishes.
