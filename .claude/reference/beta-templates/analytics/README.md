# Dex Analytics Beta

Welcome to the Dex Analytics beta! By activating this feature, you're helping Dave understand how people use Dex so he can make it better.

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

- **Opt-in only:** You choose whether to share analytics
- **One-time ask:** After you decide, you're never asked again
- **Your control:** You can change your decision anytime in `System/user-profile.yaml`
- **Transparent:** See exactly what's tracked in `System/usage_log.md`

## How It Works

1. **Consent prompt:** During your next planning session (`/daily-plan`, `/review`, etc.), you'll be asked once if you want to help improve Dex
2. **Your choice:** Say yes to help, or no thanks — Dex works exactly the same either way
3. **Event firing:** If you opt in, anonymous feature usage events are sent to Pendo

## Configuration

Your analytics settings are stored in `System/user-profile.yaml`:

```yaml
analytics:
  enabled: true  # or false if you declined
```

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

This is a beta feature. If you have questions or concerns, reach out to Dave directly.

---

*Beta version 0.1.0 • Last updated: 2026-02-04*
