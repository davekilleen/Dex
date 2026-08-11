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
| **Search** | A pre-built index at `~/.apple-mail-mcp/index.db`, which requires **Full Disk Access** to build | **Returns empty. Forever. Silently.** |

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

If not, install it: `pipx install apple-mail-mcp`

If `pipx` itself is missing: `brew install pipx && pipx ensurepath`

### 3. Register the server at user scope

Dex requires an explicit scope (a hook enforces this). Register it for the user:

```
claude mcp add --scope user apple-mail -- apple-mail-mcp serve
```

### 4. Grant Full Disk Access — do this before building the index

This is the step people skip, and skipping it is what produces the silent failure. Building
the index reads `~/Library/Mail` directly, which macOS protects.

Walk the user through it:

```
1. Open System Settings (Command+Space, type "System Settings")
2. Click "Privacy & Security" in the sidebar
3. Click "Full Disk Access"
4. Click "+" and add Terminal (or whichever terminal app you'll run the next command in)
5. Toggle it ON
6. Quit and reopen Terminal — the permission only applies to a fresh launch
```

Explain why in one line: "macOS treats your mail files as private, so the indexer needs
explicit permission to read them — without it, it exits quietly and builds nothing."

### 5. Build the index

Have the user run, in the terminal they just granted access to:

```
apple-mail-mcp index
```

This takes a few minutes on a large mailbox. It must be run manually — the server's own
startup sync **silently does nothing** when launched without Full Disk Access, which is the
second half of the trap.

### 6. Verify — do not skip this

```
apple-mail-mcp status
```

- **"No index found"** → Full Disk Access was not actually in effect. The most common cause is
  not quitting and reopening Terminal after toggling it. Go back to step 4, then step 5.
- **An index with a recent build time** → working.

Then confirm through Dex itself: `/dex-doctor` — check `mail.apple-search` reports `OK`.

### 7. After success

Confirm: "✅ Mail search is working — indexed and fresh."

Then tell them the one maintenance fact that matters: **the index does not update itself
reliably.** If the server is launched without Full Disk Access, its background sync no-ops and
the index quietly ages. Dex's Doctor check now catches this — it reports mail search as broken
once the index is more than 7 days old, rather than letting it silently return stale results.

---

## Ongoing health

`/dex-doctor` runs `mail.apple-search` as a deep check and reports:

| Verdict | Meaning |
|---|---|
| `OFF` | No Apple Mail server registered — opt-in, not a problem |
| `OK` | Index exists and was built within 7 days |
| `BROKEN` | Command missing, index never built, index empty, or index stale — each with the exact fix |
| `UNKNOWN` | A server is registered but this isn't macOS, or the index couldn't be read |

---

## Troubleshooting

**Search returns empty but `status` says an index exists:**
Rebuild it — `apple-mail-mcp index`. The index can be present but stale or partial.

**"No index found" even after granting Full Disk Access:**
Quit Terminal completely (Command+Q, not just closing the window) and reopen it. macOS applies
the permission at launch.

**Search worked before and stopped:**
The startup sync swallows a Full Disk Access denial. Confirm the permission is still granted,
then rebuild the index manually.

**The model keeps retrying searches with different keywords:**
That's the server's empty-result hint ("try fewer keywords") being misread as a search miss
rather than a missing index. Run `apple-mail-mcp status` to check the real cause — and if it
says no index, that hint was the bug, not your query.

---

## Technical Notes

- **Index location:** `~/.apple-mail-mcp/index.db` (FTS5 SQLite)
- **Why an index at all:** searching it takes ~2ms versus seconds for driving Mail.app directly
- **Privacy:** the index is local, built from your own mail, and never sent anywhere
- **Community server:** this is not a first-party Dex integration; behaviour depends on the
  server you install
