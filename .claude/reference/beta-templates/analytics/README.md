# Dex Analytics Beta

Welcome to the Dex Analytics beta! By opting in, you're helping the Dex maintainers understand how people use Dex so they can make it better.

## What Gets Tracked

**What we track:**
- Which Dex built-in features you use (e.g., "ran /daily-plan", "created a task")
- When features are used (for journey analysis)
- Basic metadata: days since setup, feature adoption score, journey stage

**What we NEVER track:**
- Your content (notes, tasks, meeting content)
- Names of people or companies
- What you actually DO with features
- Any custom skills or MCPs you create
- Your conversations with Claude

## Privacy Commitment

- **On by default in the beta:** anonymous feature usage only
- **Settings off is real:** `analytics.enabled: false` means zero analytics egress
- **Your control:** Say "turn off Dex analytics" anytime
- **Transparent:** See the local attempt receipt in `System/.dex/analytics-attempts.jsonl`
- **Bug reports are separate:** they still wait for an explicit yes

## How It Works

1. **Disclosure:** Onboarding shows the founder-approved notice (`[founder-yes]` in `.claude/flows/onboarding.md`). It informs; it does not ask.
2. **Settings switch:** `analytics.enabled` in `System/user-profile.yaml` is the off switch. False means zero analytics egress.
3. **Event firing:** When Settings is on, app-level events (feature opened, error class, version) may be sent through the existing transport. No Dex-held key is shipped.

## Configuration

User consent settings are stored in `System/user-profile.yaml`:

```yaml
analytics:
  enabled: true  # or false if you declined
```

Transport settings are configured via environment variables:

```bash
# Recommended: proxy mode (server-side relay holds Pendo key)
DEX_ANALYTICS_MODE=proxy
DEX_ANALYTICS_ENDPOINT=https://analytics.your-domain/track
DEX_ANALYTICS_PROXY_TOKEN=optional-token

# Direct mode (not recommended for OSS clients)
DEX_ANALYTICS_MODE=direct
PENDO_TRACK_SECRET=your-pendo-track-key
```

Security note:
- Dex no longer bundles a default `PENDO_TRACK_SECRET` in source.
- For public/open-source clients, use proxy mode so write keys stay server-side.

Your consent status is tracked in `System/usage_log.md`:
- `Consent asked: true/false`
- `Consent decision: pending/opted-in/opted-out`
- `Consent date: YYYY-MM-DD`

## Changing Your Mind

To opt out after opting in:
1. Open `System/user-profile.yaml`
2. Set `analytics.enabled: false`
3. Events will stop immediately

To opt in after opting out:
1. Open `System/user-profile.yaml`  
2. Set `analytics.enabled: true`

## Questions?

This is a beta feature. If you have questions or concerns, open an issue in the Dex repository.

---

*Beta version 0.1.0 • Last updated: 2026-02-04*
