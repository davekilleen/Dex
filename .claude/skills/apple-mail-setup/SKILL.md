---
name: apple-mail-setup
description: "Set up and verify Apple Mail search on macOS, including the search index that silently returns nothing when it was never built. Use when the user says 'connect Apple Mail', 'set up mail search', 'Dex can't find my emails', 'mail search returns nothing'. Not for Gmail or Google Workspace; use `google-workspace-setup`."
---

# Apple Mail Setup — Make Mail Search Actually Work

**Purpose:** Connect a community Apple Mail MCP server and — critically — build and verify its
search index, so mail search reports honestly instead of failing silently.

**When to run:**
- User types `/apple-mail-setup`
- User asks about connecting Apple Mail, or wants Dex to read their inbox
- `/dex-doctor` reports `mail.apple-search` as broken
- User says mail search "finds nothing" or their daily plan misses obvious emails

---

## The failure this prevents

Apple Mail servers have **two data paths with different permissions**, and only one of them
announces failure:

| Path | Needs | What happens when it's missing |
|---|---|---|
| List / read messages | Automation permission | Prompts you — you notice |
| **Search** | A pre-built local index (default `~/.apple-mail-mcp/index.db`), which requires **Full Disk Access** to build | **Returns empty. Forever. Silently.** |

Because list and read keep working, the integration *looks* healthy. Search returns nothing,
Dex falls back to reading messages one at a time, and nobody ever learns the index was never
built. One reporter ran that way for months.

So this setup is not finished when the server is registered. It is finished when the index
exists and is fresh.

---

## Process

### 1. Confirm the platform

Apple Mail is macOS-only. On any other platform, say so plainly and stop:
"Apple Mail integration only works on macOS. For Gmail, run `/google-workspace-setup`."

### 2. Install the server

Check whether it is already installed: `which apple-mail-mcp`

If not, install the version Dex currently supports and tests:
`pipx install 'apple-mail-mcp==0.4.3'`

`apple-mail-mcp` is community-maintained. Version 0.4.3 is Dex's current supported
contract for its index schema and CLI. Do not upgrade it during setup; a newer community
release should be adopted only after Dex's health checks and macOS CI prove compatibility.

If `pipx` itself is missing: `brew install pipx && pipx ensurepath`

### 3. Register the server at user scope

Dex requires an explicit scope (a hook enforces this). Register it for the user:

```
claude mcp add --scope user apple-mail -- apple-mail-mcp serve
```

### 4. Grant narrowly scoped Full Disk Access — do this before building the index

This is the step people skip, and skipping it is what produces the silent failure. Building
the index reads `~/Library/Mail` directly, which macOS protects.

Full Disk Access is a broad macOS permission: the approved app can read protected personal
data across the Mac, not only Mail. Grant it to the specific terminal app used for this
one-off build. Do **not** grant it to Dex, Claude, or the ordinary MCP server process.

Walk the user through it:

```
1. Open System Settings (Command+Space, type "System Settings")
2. Click "Privacy & Security" in the sidebar
3. Click "Full Disk Access"
4. Click "+" and add Terminal (or whichever terminal app you'll run the next command in)
5. Toggle it ON
6. Quit and reopen Terminal — the permission only applies to a fresh launch
```

Explain why in one line: "macOS treats your mail files as private, so this one-off indexer
needs explicit permission to read them — without it, it exits quietly and builds nothing."

### 5. Build the index

Have the user run, in the terminal they just granted access to:

```
umask 077; apple-mail-mcp index --verbose
```

`umask 077` makes any new database and SQLite sidecar files private to this Mac account.
The build takes a few minutes on a large mailbox and must be run manually. Do not solve future
freshness by giving the always-running MCP host Full Disk Access; refresh from the narrowly
approved terminal when Doctor says the configured freshness limit has been exceeded.

### 6. Verify — do not skip this

```
apple-mail-mcp status
```

- **"No index found"** → Full Disk Access was not actually in effect. The most common cause is
  not quitting and reopening Terminal after toggling it. Go back to step 4, then step 5.
- **A non-zero email count and a recent last-sync time** → continue to the Doctor check.

Then confirm through Dex itself: `/dex-doctor` — check `mail.apple-search` reports `OK`.
Doctor also verifies that the database and any `-wal` / `-shm` sidecars are exactly `0600`
(readable and writable only by this Mac account).

### 7. After success

Confirm: "✅ Mail search is working — indexed and fresh."

Then tell them the two maintenance facts that matter:

1. **The index may not update itself reliably without protected-file access.** Doctor reads
   the server's real last-sync record and applies its configured freshness limit (24 hours by
   default), rather than guessing from the database file's modified time.
2. **Full Disk Access can be removed from the terminal after the build.** Grant it again only
   when a manual refresh is needed. This is safer than leaving the always-running MCP host with
   broad access to the Mac.

---

## Ongoing health

`/dex-doctor` runs `mail.apple-search` as a deep check and reports:

| Verdict | Meaning |
|---|---|
| `OFF` | No Apple Mail server registered — opt-in, not a problem |
| `OK` | The configured SQLite index has real schema and data, a successful sync within its configured freshness limit, and private file permissions |
| `BROKEN` | Command missing; config invalid; index missing, empty, corrupt, incomplete, stale, or readable by other local accounts — each with the exact fix |
| `UNKNOWN` | A server is registered but this isn't macOS, or the index couldn't be read |

---

## Troubleshooting

**Search returns empty but `status` says an index exists:**
Run `/dex-doctor`. A file can exist while its schema is broken, it contains zero messages,
or its recorded sync is stale. Rebuild with `apple-mail-mcp rebuild --verbose` if instructed.

**The index is in a custom location:**
Dex follows `APPLE_MAIL_INDEX_PATH` from the registered MCP server first, then `[index] path`
in `~/.apple-mail-mcp/config.toml`, then the default location. Doctor applies the same order.

**"No index found" even after granting Full Disk Access:**
Quit Terminal completely (Command+Q, not just closing the window) and reopen it. macOS applies
the permission at launch.

**Search worked before and stopped:**
Run `apple-mail-mcp status`, then `/dex-doctor`. If the recorded sync is older than the
configured limit, temporarily grant the indexing terminal Full Disk Access and refresh.

**The model keeps retrying searches with different keywords:**
That's the server's empty-result hint ("try fewer keywords") being misread as a search miss
rather than a missing index. Run `apple-mail-mcp status` to check the real cause — and if it
says no index, that hint was the bug, not your query.

---

## Technical Notes

- **Index location:** `~/.apple-mail-mcp/index.db` by default; the server supports a custom
  path through its MCP environment or `config.toml`
- **Why an index at all:** searching it takes ~2ms versus seconds for driving Mail.app directly
- **What it contains:** message subjects, senders, bodies, local `.emlx` paths, attachment
  metadata, and sync records; the database plus any `-wal` / `-shm` sidecars must be `0600`
- **What leaves the Mac:** the index file stays local. Doctor reads only schema, counts,
  timestamps, integrity, and file permissions—not message text. Mail search results are returned
  to the configured AI client and may be sent to that client's model provider under its normal
  privacy settings; setup must never claim that no mail content leaves the Mac.
- **Community server:** this is not a first-party Dex integration; behaviour depends on the
  server you install
