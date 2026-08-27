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
| **Search** | A pre-built local index (default `~/.apple-mail-mcp/index.db`), which requires **Full Disk Access** to build *and* to keep current | **Looks empty — or worse, returns subject/sender hits labelled as body matches.** |

Because list and read keep working, the integration *looks* healthy. On older server
versions, search returned nothing. On the current supported release (0.4.3), a missing
index no longer stays silent: body search falls through to a live Mail query of subject
and sender, then labels those hits as body matches. That is plausible-looking evidence
for a search that never read a message body.

One reporter ran the silent version for months. The labelled-as-body version is worse
than silence.

So this setup is not finished when the server is registered. It is finished when the
index exists, the serving process can read `~/Library/Mail`, and `/dex-doctor` reports
`mail.apple-search` as `OK`.

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

### 4. Grant Full Disk Access to two apps — the terminal *and* the app that launches Mail search

This is the step people skip, and skipping it is what produces the silent (or worse,
plausible-looking) failure. Building the index reads `~/Library/Mail` directly, which
macOS protects. Keeping the index current does the same read from whatever process
launches the Mail server — that is Dex, Claude, or Cursor, not the terminal that ran
`index`.

Those are two different grants. The one you would naturally test (Terminal) is not the
one that keeps search alive.

Full Disk Access is a broad macOS permission: the approved app can read protected personal
data across the Mac, not only Mail. Grant it to:

1. The terminal app that will run the one-off `index` command
2. The app that launches the Mail server (Dex, Claude, or Cursor)

Walk the user through it for each app:

```
1. Open System Settings (Command+Space, type "System Settings")
2. Click "Privacy & Security" in the sidebar
3. Click "Full Disk Access"
4. Click "+" and add the app
5. Toggle it ON
6. Quit and reopen that app — the permission only applies to a fresh launch
```

Explain why in one line: "macOS treats your mail files as private. The indexer needs
permission to build the search copy, and the app that runs Mail search needs the same
permission to keep that copy current — without it, refresh can report success after
reading nothing."

### 5. Build the index

Have the user run, in the terminal they just granted access to:

```
umask 077; apple-mail-mcp index --verbose
```

`umask 077` makes any new database and SQLite sidecar files private to this Mac account.
The build takes a few minutes on a large mailbox and must be run manually. After the
build, leave Full Disk Access on for the app that launches the Mail server. Background
sync reads `~/Library/Mail` the same way the indexer does; if that grant is missing,
every refresh can return zero changes and still write a fresh "last synced" time.

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

1. **A recent "last synced" time is not proof the index is alive.** If the app that
   launches the Mail server lacks Full Disk Access, refresh can read nothing, write a
   fresh timestamp, and leave the copy frozen for months. Doctor now checks that this
   process can actually read `~/Library/Mail`, not only that the index file looks fresh.
2. **The terminal grant can be removed after the build.** The Dex / Claude / Cursor
   grant cannot — that is the process that keeps the copy current.

---

## Ongoing health

`/dex-doctor` runs `mail.apple-search` as a local checkup (also as
`python3 core/utils/doctor.py --check mail.apple-search`) and reports:

| Verdict | Meaning |
|---|---|
| `OFF` | No Apple Mail server registered — opt-in, not a problem |
| `OK` | The configured SQLite index has real schema and data, a successful sync within its configured freshness limit, private file permissions, *and* this process can read `~/Library/Mail` |
| `BROKEN` | Command missing; config invalid; index missing, empty, unreadable, corrupt, incomplete, stale, readable by other local accounts, or the serving process cannot read the Mail store — each with the exact fix and the Full Disk Access prerequisite |
| `UNKNOWN` | A server is registered but this isn't macOS |

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
Run `apple-mail-mcp status`, then `/dex-doctor`. A recent last-sync time is not enough —
if Doctor says the serving process cannot read `~/Library/Mail`, grant Full Disk Access
to Dex / Claude / Cursor (not only Terminal), quit and reopen that app, then rebuild.

**Search returns subject-looking hits labelled as body matches:**
On 0.4.3, body search with no usable index falls through to a live Mail query of
subject and sender. Treat that as broken, not as evidence. Run `/dex-doctor`.

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
