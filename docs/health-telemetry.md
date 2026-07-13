# Anonymous Nightly Health Telemetry

Dex can share one counts-only verdict after its nightly smoke check so maintainers can spot a bad release
across installed vaults quickly. This is off unless the user makes a separate, explicit choice to opt in.
It is independent of Dex analytics consent.

## Exact payload

The dedicated sender posts exactly these fields:

```json
{
  "schema_version": 1,
  "event": "smoke_verdict",
  "counts": {"ok": 2, "broken": 1, "unknown": 1, "off": 1},
  "worst_journey_id": "task_lifecycle",
  "dex_version": "1.56.0",
  "channel": "stable",
  "telemetry_id": "a random per-install UUID"
}
```

`worst_journey_id` is either one of the fixed shipped smoke journey IDs or `null`. It can never contain a
filename, path, diagnostic detail, note, or other free text. The `channel` is a plain string that currently
defaults to `stable`; the sender does not assume that it is the only possible channel.

The payload never contains names, notes, file contents, filenames, paths, role, company size, feature
adoption, journey stage, analytics visitor ID, analytics account ID, or any other profile metadata. The sender
does not call the analytics event helper and does not enrich the payload.

## Separate opt-in

The decision lives in `System/usage_log.md`:

```markdown
**Health telemetry:** opted-in|opted-out|pending
```

Only the exact `opted-in` value permits a network request. Missing, pending, duplicated, unreadable, or
malformed values fail closed and do not send. Analytics may be on or off independently; changing either
choice must never change the other.

The first opted-in nightly attempt creates a random UUID at `System/.dex/telemetry-id`. It is stable for that
installation but distinct from analytics visitor/account identity. The file is local and gitignored.

## Local audit and transport

Every nightly attempt appends a JSON line to `System/.dex/health-telemetry-log.jsonl`, including the exact
candidate payload, whether it was sent, and the outcome reason. This happens even when consent is pending or
opted out and even when transport fails. The audit file is local and gitignored.

Network access occurs only in `.scripts/nightly-smoke.sh` after `System/.smoke-last-run.json` has been written.
The sender reuses `get_analytics_transport()` only to resolve the configured endpoint and headers. It builds
the body itself, performs one synchronous POST with a five-second timeout, and drops failures. There is no
retry, background retry queue, or later replay.
