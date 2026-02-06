# AI Model Options for Dex

**Quick setup:** Run `/ai-setup` in Dex — I'll guide you through everything.

---

## Overview

Dex can use different AI models depending on your needs:

| Option | Cost | Internet Required | Best For |
|--------|------|-------------------|----------|
| **Claude** (default) | ~$3-15/M tokens | Yes | Best quality, complex tasks |
| **Budget Cloud** | ~$0.14-3/M tokens | Yes | Daily tasks, save 80%+ |
| **Offline** | Free | No | Travel, privacy |

---

## Option 1: Budget Cloud Models

### What Are They?

Other companies make AI models that cost much less than Claude:
- **Kimi K2.5** (Moonshot AI) — 80% cheaper, similar quality
- **DeepSeek V3** — 95% cheaper, great for coding
- **Gemini Flash** (Google) — 97% cheaper, handles long documents

### Why Use Them?

- Save money on everyday tasks
- Claude is overkill for simple stuff
- Still get excellent results for most things

### Quality Comparison

| Task | Claude | Kimi | DeepSeek |
|------|--------|------|----------|
| Complex planning | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| Meeting summaries | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Daily planning | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Code help | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Creative writing | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |

### How to Set Up

1. Run `/ai-setup` in Dex
2. Choose "Budget Cloud Mode"
3. Follow the prompts to create an OpenRouter account
4. Add $5-10 in credits (lasts weeks or months)
5. Done! Use `/model` to switch between models

### Cost Calculator

| Usage Level | Claude/Month | With Budget Models |
|-------------|--------------|-------------------|
| Light (10 queries/day) | ~$15 | ~$3 |
| Medium (30 queries/day) | ~$45 | ~$9 |
| Heavy (100 queries/day) | ~$150 | ~$30 |

---

## Option 2: Offline Mode

### What Is It?

Download an AI model directly to your computer. It runs without internet.

### Why Use It?

- ✈️ Works on airplanes
- 🚂 Works on trains with bad WiFi
- 🔒 Your data never leaves your computer
- 💰 Completely free forever

### Requirements

| Your RAM | Recommended Model | Quality |
|----------|-------------------|---------|
| 8 GB | Qwen 2.5 7B | Good for basic tasks |
| 16 GB | Qwen 2.5 14B | Good for most tasks |
| 32 GB+ | Qwen 2.5 32B | Great for everything |

**Not sure about your RAM?**
- Mac: Apple menu → About This Mac → look for "Memory"
- Windows: Right-click Start → System → look for "Installed RAM"

### How to Set Up

1. Run `/ai-setup` in Dex
2. Choose "Offline Mode"
3. Answer questions about your computer
4. Install Ollama (free app) from ollama.ai
5. Download the recommended model
6. Done! Works automatically when offline

### What Works Offline

**Works great:**
- Daily planning and reviews
- Meeting summaries
- Task management
- Note organization
- Quick questions

**Better with Claude:**
- Quarterly planning
- Career coaching
- Complex analysis
- Creative writing

---

## Option 3: Smart Routing

### What Is It?

Let Dex automatically pick the best model for each task:
- Complex stuff → Claude (best quality)
- Simple stuff → Budget model (saves money)
- No internet → Local model (offline backup)

### How It Works

| Task | Model Used | Reason |
|------|------------|--------|
| `/quarter-plan` | Claude | Needs deep thinking |
| `/daily-plan` | Budget (Kimi) | Routine task |
| `/meeting-prep` | Budget (Kimi) | Straightforward |
| `/career-coach` | Claude | Needs nuance |
| "What's on my calendar?" | Budget | Simple question |
| *No internet* | Local | Only option |

### How to Enable

1. Run `/ai-setup` in Dex
2. Set up budget cloud first
3. Optionally set up offline mode
4. Choose "Smart Routing"
5. Done! I'll pick automatically (you can always override)

---

## Quick Reference

### Switching Models

**Method 1: Ask me**
- "Use the budget model for this"
- "Switch to Kimi"
- "Use Claude for this one"

**Method 2: Model picker**
- Type `/model` in pi
- Select from the list

### Checking Your Setup

Run `/ai-status` to see:
- Which models are configured
- Current model in use
- OpenRouter credit balance
- Ollama status

### Model Names

| Display Name | Technical ID |
|--------------|--------------|
| Claude Sonnet | `claude-sonnet-4-20250514` |
| Kimi K2.5 | `moonshotai/kimi-k2.5` |
| DeepSeek V3 | `deepseek/deepseek-chat` |
| Gemini Flash | `google/gemini-2.0-flash-exp:free` |
| Qwen (Offline) | `qwen2.5:14b` |

---

## Troubleshooting

### Budget model not working?

1. Check OpenRouter has credits (openrouter.ai/credits)
2. Verify API key is correct (starts with `sk-or-`)
3. Try regenerating the key

### Offline model too slow?

Your model might be too big for your RAM:
1. Open Activity Monitor (Mac) or Task Manager (Windows)
2. If RAM is maxed, download a smaller model:
   ```
   ollama pull qwen2.5:7b
   ```

### Ollama won't start?

**Mac:** 
- Open Applications, right-click Ollama → Open
- If blocked: System Settings → Privacy & Security → Allow

**Manual start:**
- Open Terminal
- Run: `ollama serve`
- Keep window open

---

## FAQ

**Q: Will I notice a quality difference with budget models?**
A: For everyday tasks (planning, summaries, organization), most people don't notice. For complex reasoning or creative work, Claude is noticeably better.

**Q: How much will I actually save?**
A: Depends on usage, but typically 50-80% if you use budget models for routine tasks and Claude for complex ones.

**Q: Is my data safe with other models?**
A: Budget cloud models (Kimi, DeepSeek) are hosted by other companies. If privacy is critical, use offline mode — data never leaves your computer.

**Q: Can I go back to Claude-only?**
A: Yes! Just don't use the other models, or disable them in settings.

**Q: What if I'm offline and haven't set up local models?**
A: Dex will let you know and offer to set it up when you're back online. You can still browse/edit files manually.

---

## Related

- [Dex System Guide](Dex_System_Guide.md) — Full system documentation
- [Dex Technical Guide](Dex_Technical_Guide.md) — Advanced configuration
