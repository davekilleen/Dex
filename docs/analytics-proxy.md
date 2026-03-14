# Dex Analytics Proxy (Recommended)

Use a small relay service to keep `PENDO_TRACK_SECRET` server-side.

## Why

If an open-source client sends directly to Pendo, any bundled write key is eventually discoverable.
Proxy mode prevents shipping that key to users.

## Client Configuration

Set these environment variables for `dex-analytics`:

```bash
DEX_ANALYTICS_MODE=proxy
DEX_ANALYTICS_ENDPOINT=https://analytics.your-domain/track
DEX_ANALYTICS_PROXY_TOKEN=optional-bearer-token
```

## Request Contract (from Dex client)

`POST /track`

```json
{
  "type": "track",
  "event": "daily_plan_completed",
  "visitorId": "abc123...",
  "accountId": "dex-users",
  "timestamp": 1730832000000,
  "properties": {
    "journey_stage": "exploring",
    "days_since_setup": 12
  }
}
```

Headers:
- `Content-Type: application/json`
- `Authorization: Bearer <DEX_ANALYTICS_PROXY_TOKEN>` (optional)
- `x-dex-analytics-client: dex-core`

## Proxy Behavior

1. Validate auth (if token configured).
2. Enforce allowlist for event names.
3. Enforce allowlist/shape for property keys and types.
4. Reject free-text or oversized payloads.
5. Rate-limit by IP + visitor ID.
6. Forward to Pendo:
   - URL: `https://app.pendo.io/data/track`
   - Header: `x-pendo-integration-key: <server-side secret>`
7. Return only status metadata to client.

## Security Controls

- Keep `PENDO_TRACK_SECRET` only in proxy runtime secrets.
- Add request size cap (for example 8 KB).
- Add per-visitor dedupe key (optional): `event + visitorId + timestamp`.
- Log rejected events with reason (no payload content).
- Add alerting for traffic spikes or unknown event names.

## Rollout Plan

1. Rotate existing Pendo key.
2. Deploy proxy with new key.
3. Ship Dex with `DEX_ANALYTICS_MODE=proxy`.
4. Monitor proxy logs and Pendo ingestion for 24-48h.
5. Remove any remaining direct-mode key distribution.
