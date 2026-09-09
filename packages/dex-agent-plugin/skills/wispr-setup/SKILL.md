---
name: wispr-setup
description: "Connect Wispr Flow so meeting captures arrive in your vault on their own. Use when the user says 'connect Wispr', 'set up Wispr Flow', 'my Wispr meetings aren't in Dex'. Not for Granola; use `granola-setup`. Not for processing meetings already in the vault; use `process-meetings`."
integration:
  id: wispr
  name: Wispr Flow
  auth: oauth2
  credential: dex-held
  transport: remote-mcp
  enhances:
    - skill: process-meetings
      capability: "Wispr captures become meeting notes, person page updates and tasks"
    - skill: daily-plan
      capability: "Yesterday's captures are already in the vault before the day starts"
  entities: meetings, transcripts, calendar events
---

<!-- Generated from `.claude/skills/wispr-setup/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

# Connect Wispr Flow

Wispr Flow records meetings and writes a summary. This connects it to Dex so
those captures arrive in `00-Inbox/Meetings/` by themselves, and `/process-meetings`
treats them exactly like any other meeting note.

## What makes this connection different, and why it matters to you

Dex holds the credential itself rather than borrowing one from whichever app you
happen to be running. That is the difference between a source that works while
you are sitting in a session and one that works overnight. Once connected:

- Captures can be fetched on a schedule, so they are in the vault before you
  open Dex in the morning.
- The connection follows the vault. It works the same in Claude Code, Cursor, or
  anything else that runs Dex, because nothing depends on that app's own
  connector store.

## Before you start

You need a Wispr Flow account with the notetaker enabled. There is no key to
paste and nothing to copy: you authorise once in a browser.

## Step 1: Run the connection

```bash
python3 -c "from pathlib import Path; from core.meeting_sources.wispr_setup import connect; print(connect(Path('.')))"
```

This registers Dex with Wispr, opens your browser, and waits for you to approve.
When you do, it stores the credential in `System/.dex/wispr-credential.json`
with owner-only permissions.

**If the browser does not open**, the command prints the URL. Open it yourself.

## Step 2: Confirm it worked

```bash
python3 -c "from pathlib import Path; from core.meeting_sources import wispr_client; print(wispr_client.list_tools(Path('.')))"
```

You should see the tools Wispr exposes. If this fails, say what the error was
rather than assuming the connection is fine.

## Step 3: Pull your recent captures

```bash
python3 -m core.meeting_sources.wispr_sync
```

It reports what it did in one line. Then run `/process-meetings` to turn the new
notes into person page updates and tasks.

## Step 4: Keep it running (optional)

To have captures arrive on their own, schedule the same command. On macOS that
is a launch agent running `python3 -m core.meeting_sources.wispr_sync` with
`VAULT_PATH` set to your vault.

## Two things to tell the user plainly

**Your captures may arrive without attendee names.** Wispr titles and attributes
a capture from the calendar it is connected to, and its calendar sync is Google
only. On Microsoft 365 the capture arrives with no title and no attendees, so
Dex derives a title from the summary and marks the note as unresolved. Speaker
labels in the summary are turns in a recording, not people. Do not let anything
downstream assign an action or a quote on the strength of that note alone;
match it against the calendar entry for that time first.

**The credential is in your vault.** `System/.dex/wispr-credential.json` holds a
refresh token. If your backups include `System/`, exclude that file, in the same
way `.env` is excluded. Anyone who can read it can read your meetings.

## If it stops working

Wispr's access tokens last five minutes and the refresh token is replaced every
time it is used, so the stored file is rewritten constantly. If the credential
is lost or corrupted, re-run Step 1: there is nothing to recover and
re-authorising takes one browser click.

Say plainly when the connection is broken. A meeting source that quietly returns
nothing looks exactly like a quiet week, and that is the failure this setup is
built to avoid.
