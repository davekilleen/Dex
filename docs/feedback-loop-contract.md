# Feedback loop contract (terminal Dex ⇄ heydex.ai)

Status: contract of record for the `/feedback` concierge loop (V1 + V2), decided with
Dave 2026-08-08. Build Card: `feedback-concierge-loop-terminal-dex`. Design explainer:
`2026-08-08-feedback-concierge-loop.html` (private gallery).

## Decisions this contract encodes

1. Transport is heydex.ai, not GitHub. Reports land in a private inbox only.
2. Sign-in is compulsory. Every report is tied to a heydex account via the existing
   connect-code flow (`~/.dex/heydex-auth.json`, minted by `POST /api/connect/redeem`).
3. V1 and V2 ship together: reporting loop plus the two-way question/answer round trip.
4. Triage: every report becomes (or attaches to) a Build Card immediately. The duplicate
   counter is a priority multiplier, never a threshold.
5. Privacy by construction: the report is assembled only from the allowed ingredients
   below. Conversation content is never a source. The user's trust dial
   (`feedback.review_mode`) controls show-before-send, not what may be collected.

## Backend

DexDiff Convex deployment (`heydex-web` project, prod `gallant-reindeer-229`).
Base URL: `https://gallant-reindeer-229.eu-west-1.convex.site` (same origin the publish
path uses; `api.heydex.ai` routes to the separate Dex Desktop backend and is not used).
Override for tests: `DEX_FEEDBACK_API_BASE`.

Auth on every feedback route: `Authorization: Bearer <sessionToken>` resolved against
`cliSessions` (required — the beta-gate-disabled bypass does not apply to feedback).
Sign-in is compulsory, but DexDiff beta membership is NOT (Dave, 2026-08-10): any
signed-in Heydex account may link a terminal and file feedback. The DexDiff private
beta continues to gate publishing, love letters, and diff/profile reads only.

The Dex-side client (`.claude/skills/feedback/scripts/feedback_client.py`) must treat
a linked Heydex session (`sessionToken` in `~/.dex/heydex-auth.json`) as sufficient
to send. Missing DexDiff beta membership is not a client-side send refusal. If the
hosted API still rejects a linked non-beta session, that is a heydex-web blocker,
not a Dex client gate. Tickets still land on the private DexDiff desk.

## HTTP endpoints (all also answer OPTIONS for CORS)

### POST /api/feedback/report

Request body (JSON, capped at 32 KB, unknown fields rejected):

```json
{
  "schema_version": 1,
  "captured_at": 1754640000000,
  "dex_version": "1.81.19",
  "feature": "/process-meetings",
  "summary": "Sync stopped with 'attendee index out of range' when a meeting had no attendees.",
  "error_trace": "Traceback ... (optional; Dex code paths only)",
  "machine_state": {
    "os": "darwin",
    "host_app": "claude-code",
    "features": { "granola": "ok", "todoist": "off" },
    "automation": { "meeting_sync": "loaded" }
  },
  "investigation": "Focus items in the daily plan are missing task identity — checked 5 lines, 0 had it. (optional)",
  "user_note": "optional free text the user typed",
  "review_mode": "always-review",
  "fingerprint": "sha256 of feature + normalized error head, client-computed"
}
```

Response `200`: `{ "ticket": "DEX-142", "receivedAt": 1754640001000 }`
Errors: `401` (invalid/expired session — client shows the connect instructions),
`400` opaque `{"error":"invalid_request","code":"INVALID_REQUEST"}`, `429` rate
limit (both the per-IP limiter and the per-account daily submission cap).

### GET /api/feedback/status

Returns the authenticated account's reports, newest first (up to 1000):

```json
{
  "reports": [
    {
      "ticket": "DEX-142",
      "feature": "/process-meetings",
      "summary": "Sync stopped with ...",
      "status": "fixed",
      "statusChangedAt": 1754700000000,
      "fixedInVersion": "1.82.0",
      "comment": "Great catch — this was hitting 14 other people too. Thank you.",
      "question": null,
      "answers": [ { "text": "Both — earliest July 2.", "receivedAt": 1754650000000 } ],
      "createdAt": 1754640001000
    }
  ]
}
```

`status` enum: `received | investigating | needs_info | fixed | wont_fix`.
`question` is non-null only in `needs_info`; `fixedInVersion` only in `fixed`.

### POST /api/feedback/answer

```json
{ "schema_version": 1, "ticket": "DEX-158", "captured_at": 1754640000000,
  "answer": "Both — 3 duplicates, all created by the meeting sync, earliest July 2." }
```

Appends the answer to the ticket's thread and moves `needs_info → investigating`.
Only the ticket's owner may answer. Response `200`: `{ "ok": true }`.

## Founder / triage access

No public HTTP surface. Internal Convex functions invoked with the deploy key
(`npx convex run`), which is how Dave-side agents authenticate as owner:

- `feedback:listNew` — reports not yet triaged (plus fingerprint-match hints).
- `feedback:setStatus { ticket, status, comment?, fixedInVersion? }`
- `feedback:askQuestion { ticket, question }` — sets `needs_info`.

Every new report is expected to become (or attach to) a Mission Control Build Card at
triage time; matching `fingerprint` values attach to the same card and increment its
affects-count.

## Table (Convex `feedbackReports`)

`userId`, `ticket` (unique, `DEX-<n>` from a counter document), `schemaVersion`,
`clientCapturedAt`, `dexVersion`, `feature`, `summary`, `errorTrace?`, `machineState?`,
`investigation?`, `userNote?`, `reviewMode`, `fingerprint`, `status`,
`statusChangedAt`, `comment?`, `question?`, `answers[]`, `triaged` (bool).
Indexes: `by_userId`, `by_ticket`, `by_fingerprint`, `by_status`.

## Client-side state (terminal Dex)

- Claim tickets: `System/.dex/feedback/<ticket>.json` (one JSON per report — the local
  copy of what was sent plus last known status). Travels with the vault.
- Send receipts: `System/.dex/feedback-log.jsonl`, append-only, one line per attempt
  whether or not anything was sent (health-telemetry honesty pattern).
- Sweep dedup: the once-daily status sweep claims the day before doing work
  (update-verifier pattern) and stores its marker under `System/.dex/`.
- Trust dial: `feedback.review_mode` in `System/user-profile.yaml`
  (`always-review` default | `auto-send`). First report is always reviewed regardless.
  V2 answers are always reviewed regardless of dial.

## Allowed ingredients (privacy by construction)

A report may contain only: Dex version; feature/skill name; what-happened vs expected
in Dex-mechanics phrasing; error text and stack trace (Dex code paths); the Doctor
machine-state bundle (never config values, only presence/health states); investigation
mechanisms as counts and descriptions (never file contents, names, or note text); file
paths with vault-relative segments replaced by placeholders; an optional user-typed
note. The conversation transcript is never read as a source.
