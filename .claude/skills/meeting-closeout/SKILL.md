---
name: meeting-closeout
description: "Close out the meeting you just had while it's fresh — lock the decisions, the action items and who owns each, what you personally committed to, and the single next step — then capture it and, only with your OK, turn the actions into tracked tasks. Use when the user says 'wrap up this meeting', 'close out my 3pm', 'here are my notes from the call', or right after a meeting ends. Also use proactively when the user pastes raw notes from a meeting that just happened. Not for bulk-processing many already-synced meetings; use `process-meetings`. Not for prepping a meeting that hasn't happened yet; use `meeting-prep`."
---

# /meeting-closeout

The gap between walking out of a meeting and the next context switch is where decisions and promises evaporate. This closes **one** meeting the moment it ends — while you still remember who said they'd do what — and locks it down.

It is the single-meeting, in-the-moment ritual. It is **not** the bulk "catch up all my synced notes" pass (`process-meetings`) and **not** pre-meeting prep (`meeting-prep`).

---

## Step 1 — Get the meeting

Work from whichever exists, in this order:
1. **Notes the user just pasted or dictated** — the common case; use them directly even if the meeting was never synced.
2. **The meeting they name** ("my 3pm with Acme") — pull it via `get_meeting_context` or the latest file in `00-Inbox/Meetings/`.

If there are no notes and no matching synced meeting, **ask for the notes** (or a two-line recap) — do not fabricate a summary of a meeting you can't see.

## Step 2 — Extract the closeout essentials

Pull only what the notes support — never invent a decision or an owner the meeting didn't produce:

- **Decisions** — what was actually decided (not everything discussed).
- **Action items + owner + due** — each task, who owns it, by when. Name the owner explicitly; if the notes don't say, mark it "owner TBD" rather than guessing.
- **Your commitments** — what *you* personally promised (these are the trust-critical ones; they feed the same promise-tracking as `commitments`).
- **Open questions** — unresolved threads to revisit.
- **The single next step** — the one thing that moves this forward.

## Step 3 — People (respect the entity setting)

Identify attendees and **update existing person pages** with the relevant context (via `lookup_person`). For people who don't have a page yet, follow the vault's `entity_creation` setting — `auto` creates, `suggest` (the default) offers, `off` just tracks. Do not hard-create person pages against the user's setting.

## Step 4 — Turn actions into tasks (confirm-gated, never automatic)

Offer to create tasks from the action items and your commitments. **Nothing is written without per-item confirmation.** For each one the user approves, call Work MCP `create_task` (carry the owner, due, and the meeting as source; infer the pillar per the CLAUDE.md rules), then **read back the created task IDs**. Items the user skips are left out; a failed `create_task` is reported as not created, never counted as done.

## Step 5 — Capture, then confirm what happened

Save the closeout to the meeting note (or `00-Inbox/Meetings/` if it was pasted, unsynced). Then confirm the real result by reading it back: the note path saved, the tasks created (by ID), and which person pages were updated. Never report "captured / done" without those in hand.

---

## Quality bar

A good closeout leaves the meeting's **decisions, owned actions, your commitments, and one next step** captured while they're fresh — each grounded in what was actually said — so nothing important is lost between the meeting and the next thing. Owners are named or honestly TBD; nothing is created the user didn't confirm.

## Anti-patterns (do not do these)

- **Re-running the bulk sync/catch-up** over many meetings — that's `process-meetings`; closeout is this one meeting.
- **Inventing decisions, owners, or commitments** the notes don't support — mark unknowns TBD instead.
- **Auto-creating tasks** without per-item confirmation, or **person pages** against the `entity_creation` setting.
- **Claiming "captured / done"** without reading back the saved note path and created task IDs.
- Dumping the whole transcript back as "notes" instead of extracting decisions and owned actions.

## Degradation

- No pasted notes and no matching synced meeting → ask for the notes; never fabricate a recap.
- `entity_creation: off` → track people, don't create pages; `suggest` → offer, don't auto-create.
- A `create_task` call fails → report that item as not created; don't count it.
- QMD/semantic search absent → link people/projects by keyword; the closeout still runs.

---

## Track Usage (Silent)

Update `System/usage_log.md` to mark meeting-closeout as used. **Analytics (Silent):** call `track_event` with event_name `meeting_closed_out` and properties `tasks_created` and `decisions_captured` (counts only — no meeting content, no names). Fires only if the user opted into analytics; no action if it returns "analytics_disabled".
