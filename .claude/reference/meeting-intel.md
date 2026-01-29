# Meeting Intelligence Reference

Process meetings from Granola to extract structured insights, action items, and update person pages.

## Manual Processing (Recommended)

Run `/process-meetings` whenever you want to pull in new meetings. Uses Claude directly — **no API key needed**.

```
/process-meetings           # Process all unprocessed meetings (last 7 days)
/process-meetings today     # Just today's meetings
/process-meetings "Acme"    # Find and process specific meeting
```

**What gets extracted:**
- Summary (2-3 sentences)
- Key discussion points with context
- Decisions made
- Action items (for you and others)
- Customer intelligence (pain points, feature requests, competitive mentions)
- Automatic pillar classification

**Output:**
- Meeting notes: `00-Inbox/Meetings/YYYY-MM-DD/meeting-slug.md`
- Person pages updated with meeting references

## Automatic Processing (Optional)

For hands-off processing every 30 minutes, even when Cursor is closed:

1. Choose API provider during onboarding (Gemini free tier, Anthropic, or OpenAI)
2. Add API key to `.env`
3. Run `./.scripts/meeting-intel/install-automation.sh`

**Manual commands for automatic mode:**

```bash
node .scripts/meeting-intel/sync-from-granola.cjs           # Process now
node .scripts/meeting-intel/sync-from-granola.cjs --dry-run # Preview
./.scripts/meeting-intel/install-automation.sh --status     # Check status
```

## Configuration

Meeting intelligence extraction is configured in `System/user-profile.yaml`:

```yaml
meeting_intelligence:
  extract_customer_intel: true    # Pain points, requests
  extract_competitive_intel: true # Competitor mentions
  extract_action_items: true      # Always recommended
  extract_decisions: true         # Always recommended
```

Meetings are automatically classified into your pillars from `System/pillars.yaml`.

## Logs

- `.scripts/logs/meeting-intel.log` - Processing log
- `.scripts/logs/meeting-intel.stdout.log` - Standard output
- `.scripts/logs/meeting-intel.stderr.log` - Errors
