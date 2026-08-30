# Connector box — pack the unpublished MCP server

Unreleased. Nobody has walked this card. Do not publish. Do not merge.
This is a local pack check. It is not a catalogue install.

**Lab issue (leave open):** https://github.com/davekilleen/dex-product-gtm-lab/issues/486

## Steps

### Step 1

1. From the Dex folder, run:

```sh
python3 scripts/build-mcp-registry-artifact.py --output-dir build/mcp-registry-artifact
```

**What you should see:** The command prints a packed `.tgz` name, then `Validated. Still unreleased. Did not publish.` The packed file `dex-mcp-1.0.0.tgz` is in `build/mcp-registry-artifact/`.

- [ ] I saw that.

**If this fails, send back this exact sentence:** `connector-box step 1 failed: the pack script did not stay unreleased.`

### Step 2

1. Open the SHA-256 sidecar next to the packed file: `build/mcp-registry-artifact/dex-mcp-1.0.0.tgz.sha256`.

**What you should see:** One line. A 64-character hash, two spaces, then `dex-mcp-1.0.0.tgz`.

- [ ] I saw that.

**If this fails, send back this exact sentence:** `connector-box step 2 failed: the SHA-256 sidecar was missing or did not match the packed file.`

### Step 3

1. Open `build/mcp-registry-artifact/artifacts.json` and read `one_line_after_publish`.

**What you should see:** The future catalogue name `io.github.davekilleen/dex`. It is written down only. It is not live. Do not add that line to an app.

- [ ] I saw that.

**If this fails, send back this exact sentence:** `connector-box step 3 failed: the future catalogue name was missing.`

## After the last checkbox

If every box is checked, send this exact sentence:

`connector-box pack matched. SHA-256 sidecar present. Future catalogue name is io.github.davekilleen/dex. Not a catalogue install.`

If any box is unchecked, send only the failure sentence from that step. Do not continue past a failed step. Do not publish. Do not sign. Do not store a secret. Do not invite anyone.

## Leave

When you are finished, delete the packed file and build folder.

## Status

Nobody has walked this card.
