---
name: feedback
description: Report a Dex bug to the Dex team with zero homework — Dex investigates locally, builds a privacy-safe report, shows it to you (or auto-sends if you've chosen that), and tracks the ticket until it's fixed. Use when the user says "report this", "send this to the Dex team", "file feedback", "/feedback", asks "what happened to my bug report", or accepts Doctor's offer to report a Dex bug. Also use when the user describes something in Dex misbehaving in their own words, without asking for a report at all — "the meeting sync is doing something weird", "this keeps breaking", "X stopped working", "that's not what I asked for" — investigate first, then offer. Not for capturing ideas about your own vault or workflow; use the improvements backlog for those. Not for trouble in the user's own notes, calendar or projects, which is never a Dex defect.
---

# /feedback — concierge bug reporting

Turn "something in Dex is broken" into a high-quality report on the Dex team's desk,
with the user doing nothing but approving. Contract: `docs/feedback-loop-contract.md`.

## Cardinal rules (read every time)

1. **The conversation is never a source.** A report may contain ONLY the allowed
   ingredients: Dex version, feature/skill name, what happened vs what was expected
   (phrased as Dex mechanics), error text and stack traces (Dex's own code paths),
   machine-state facts (OS, host app, feature health — never config values or file
   contents), investigation findings as mechanisms and counts ("checked 5 lines,
   0 had task identity" — never the lines themselves), and a note the user types.
   Nothing about the user's work, people, meetings, or personal life — even if it
   feels relevant. If a fact can't be phrased without private content, leave it out.
2. **File paths:** Dex's own code paths (like `core/utils/doctor.py`) are fine.
   Paths to the user's notes are not — describe the folder role instead
   ("a person page under the People folder").
3. **Show-before-send is governed by the trust dial** (`feedback` →
   `review_mode` in `System/user-profile.yaml`):
   - `always-review` (default): show the exact draft, wait for a clear yes.
     The user may edit anything first.
   - `auto-send`: send without asking, then confirm in one calm line and offer
     "say 'show it' to see exactly what went."
   - **The first report is always reviewed** regardless of the dial (no ticket
     files under `System/.dex/feedback/` means first report).
   - **Answers to questions are always reviewed** regardless of the dial.
4. **Never send without the script.** All sends go through the client script so
   every attempt lands in the local receipt log (`System/.dex/feedback-log.jsonl`).
5. **Prefer the vault interpreter.** Resolve it once, then use `"$FEEDBACK_PYTHON"`
   for every `feedback_client.py` call (check, report, status, answer, and link).
   Bare `python3` is the fallback only when neither vault path is executable.

   ```bash
   FEEDBACK_PYTHON="python3"
   if [ -x "${CLAUDE_DIR:-}/.venv/bin/python" ]; then
     FEEDBACK_PYTHON="$CLAUDE_DIR/.venv/bin/python"
   elif [ -x "${VAULT_PATH:-}/.venv/bin/python" ]; then
     FEEDBACK_PYTHON="$VAULT_PATH/.venv/bin/python"
   fi
   ```

## Filing a report

0. **Preflight the connection first** — before investigating or drafting anything:

   ```bash
   "$FEEDBACK_PYTHON" .claude/skills/feedback/scripts/feedback_client.py check --vault "$VAULT_PATH"
   ```

   - Exit 0 (LINKED): carry on.
   - Exit 2 (CONNECTION NEEDED): tell the user now, not after drafting: "One-time
     setup first (~30 seconds): open the connect page, sign in, create a code, and
     I'll link this terminal." Show the script's instructions, then run the
     `link` subcommand with their code using the same `"$FEEDBACK_PYTHON"` —
     do not switch to bare `python3` even if the printed example uses it.
     If they'd rather not link right now, offer to draft the report anyway and
     save it locally so nothing is lost — but never let them discover the
     missing link only after approving a draft.
1. **Establish the facts.** From the conversation and quick local checks:
   - Dex version: read `version` from `package.json` at the vault root.
   - Feature: which skill/command/automation misbehaved.
   - What happened vs expected, in one or two Dex-mechanics sentences.
   - Error trace: if an error or traceback was captured this session, include it
     whole (it contains only Dex code paths). Do not reconstruct one from memory.
2. **Investigate locally before sending** (this is what makes reports actionable).
   Debug like an engineer with full local access, then send the *mechanism*, not
   the data. Examples of good investigation findings:
   - "Focus items in the daily plan are missing task identity — checked 5 lines, 0 had it."
   - "The sync automation is installed but not loaded; last successful run July 30."
   - "The person index exists but has not been rebuilt since the folder was renamed."
   Keep it to what you verified, with counts. Never quote vault content.
3. **Machine state.** Assemble a small `machine_state` object from cheap facts:
   `os` (from `uname -s`, lowercased), `host_app` (e.g. claude-code), and — when
   `System/.dex/smoke-last-run.json` or a recent Doctor report exists — a
   `features` map of health states (values like ok/off/broken only). If
   `System/.onboarding-lab` exists, set `lab: true` so beta reports stay
   separable. Skip anything you can't check cheaply; an empty machine_state is fine.
4. **Write the draft** to a temp file (e.g. `/tmp/dex-feedback-draft.json`):

   ```json
   {
     "dex_version": "<from package.json>",
     "feature": "/process-meetings",
     "summary": "<what happened vs expected>",
     "error_trace": "<verbatim, optional>",
     "machine_state": { "os": "darwin", "host_app": "claude-code" },
     "investigation": "<mechanism findings, optional>",
     "user_note": "<only if the user typed one>",
     "review_mode": "<the user's dial setting>"
   }
   ```

   The script adds the timestamp and failure fingerprint itself.
5. **Apply the trust dial** (cardinal rule 3). For review: show the draft's
   fields exactly as they will be sent, in a readable form, and ask once —
   "Send it? You can edit anything first." Apply any edits to the draft file.
6. **Send:**

   ```bash
   "$FEEDBACK_PYTHON" .claude/skills/feedback/scripts/feedback_client.py report --file /tmp/dex-feedback-draft.json --vault "$VAULT_PATH"
   ```

   - Exit 0: confirm with the ticket reference the script printed, e.g.
     "Sent — reference DEX-142. I'll tell you when there's news."
   - Exit 2 (CONNECTION NEEDED): the terminal isn't linked yet. Show the
     script's instructions — the user opens the connect page, signs in, creates
     a code, and you run the `link` subcommand with `"$FEEDBACK_PYTHON"` (not
     bare `python3`). This is a one-time, ~30-second step; after linking, send
     the report without re-asking.
   - Other exits: relay the script's plain-language message; don't invent detail.
7. **First-approval upgrade offer.** If the user approved without changing
   anything and their dial is `always-review`, offer once: "Want me to just send
   future reports automatically? You can switch back anytime." If yes, set
   `feedback.review_mode: auto-send` in `System/user-profile.yaml`. Never
   re-offer in the same vault after a no (note the no in the user's preferences).

## Checking status

When the user asks about their reports (or after filing):

```bash
"$FEEDBACK_PYTHON" .claude/skills/feedback/scripts/feedback_client.py status --vault "$VAULT_PATH"
```

Relay the script's list plainly. Statuses mean: RECEIVED (on the team's desk),
INVESTIGATING (being worked), NEEDS INFO (a question is waiting — offer to answer
it), FIXED in vX (suggest /dex-update if their version is older), CAN'T FIX
(give the reason from the comment, honestly).

## Answering a question (two-way loop)

When a ticket is NEEDS INFO (surfaced by the session-start sweep or status):

1. Read the question aloud to the user and ask if they'd like you to look into it:
   "I can check and answer that myself — you'll see exactly what goes back."
2. Investigate locally under the same cardinal rules — mechanisms and counts,
   never content.
3. **Always show the drafted answer and wait for a yes** (even for auto-send
   users — answering means you looked inside their vault).
4. Send:

   ```bash
   "$FEEDBACK_PYTHON" .claude/skills/feedback/scripts/feedback_client.py answer --ticket DEX-158 --text "<approved answer>" --vault "$VAULT_PATH"
   ```

If the user declines, drop it without pressure; the question stays available in
status whenever they're ready.

## What the user can always inspect

- Every send attempt: `System/.dex/feedback-log.jsonl` (kept even when nothing
  was sent).
- Every ticket and its last known state: `System/.dex/feedback/DEX-*.json`.

## Edge cases

- **No sign-in and user declines linking:** respect it. Offer to save the draft
  locally instead (keep the temp file path visible) and mention they can run
  /feedback later — never send anything without a linked account.
- **Multiple bugs in one session:** one report per distinct failure; shared
  context can repeat across drafts.
- **The bug is in the user's own configuration**, not Dex: say so honestly and
  fix it locally instead — /feedback is for defects in Dex itself. When unsure,
  file it; triage would rather see a false alarm than miss a real defect.
