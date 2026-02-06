# ScreenPipe Beta

**Status:** Beta (Invitation Only)  
**Activation Code:** `DEXSCREENPIPE2026`

---

## What Is This?

ScreenPipe enables **ambient work intelligence** - Dex learns what you're working on by capturing OCR text from your screen. Instead of manually logging your work, you can ask:

- "What was I working on this morning?"
- "Summarize my day"
- "When did I last look at the Q1 presentation?"

---

## Privacy First

**Work apps only.** Everything personal is blocked by default:

| ✅ Captured | ❌ Blocked |
|-------------|------------|
| VS Code, Terminal, IDEs | All web browsers |
| Slack, Teams, Zoom | Password managers |
| Notion, Obsidian, Figma | Personal messaging |
| Calendar, project tools | Social media, email |
|  | Banking, healthcare |
|  | Shopping, entertainment |

**Additional protections:**
- PII removal (emails, phone numbers, credit cards auto-redacted)
- 30-day auto-delete (configurable)
- All data stays on your machine
- Easy to view, pause, or delete anytime

---

## Activation

1. Run: `/beta-activate DEXSCREENPIPE2026`
2. Then run: `/screenpipe-setup`
3. Follow the prompts

---

## Quick Reference

| Action | Command |
|--------|---------|
| Enable | `/screenpipe-setup` |
| Disable | `screenpipe stop` |
| View data | `open http://localhost:3030` |
| Delete all | `rm -rf ~/.screenpipe/` |
| Change retention | "Keep screen data for 7 days" |

---

## Local Model Option

For maximum privacy (nothing to Anthropic):
1. Run `/ai-setup` → Choose "Offline/Local"
2. Then enable ScreenPipe
3. All queries stay on your machine

---

## Feedback

This is beta - we want your feedback:
- What works well?
- What's missing?
- Any privacy concerns?

Let Dave know via Slack or in your Dex conversations.
