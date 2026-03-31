---
name: ai-status
description: Check your AI model configuration - see what's set up, current model, credits remaining
---

## Purpose

Quick status check for AI model configuration. Shows:
- Which models are configured (premium, budget, offline)
- Current model in use
- OpenRouter credit balance
- Ollama status
- Quick tips for switching

## When to Run

- User types `/ai-status`
- User asks "what model am I using?"
- User asks about AI credits or costs
- Troubleshooting model issues

---

## Execution

### Step 1: Gather Status

Run the test script silently:
```bash
bash $VAULT_PATH/System/scripts/test-ai-connections.sh 2>/dev/null
```

Also check:
- Current pi model (from session state)
- `System/user-profile.yaml` for AI settings

### Step 2: Display Status

```
**Your AI Configuration**

| Mode | Status | Model |
|------|--------|-------|
| Premium | ✅ Ready | Claude Sonnet |
| Budget Cloud | {{✅ Ready / ❌ Not set up}} | {{Kimi K2.5 / —}} |
| Offline | {{✅ Ready / ❌ Not set up}} | {{Qwen 2.5 14B / —}} |
| Smart Routing | {{✅ Enabled / ❌ Disabled}} | |

**Currently using:** {{current_model}}

{{If OpenRouter configured:}}
**OpenRouter credits:** ${{balance}} remaining

{{If Ollama configured:}}
**Ollama:** {{Running ✅ / Not running ⚠️}}

---

**Quick actions:**
- `/model` — Switch models
- `/ai-setup` — Configure more options
- "Use budget model" — Quick switch for this task
```

### Step 3: Offer Help if Issues

If something isn't working:

```
**⚠️ Issues detected:**

{{If OpenRouter not working:}}
- Budget cloud: API key may be invalid or no credits
  Fix: Check openrouter.ai/credits

{{If Ollama not running:}}
- Offline mode: Ollama isn't running
  Fix: Open Ollama app, or run `ollama serve` in Terminal

Need help? Run `/ai-setup` to reconfigure.
```

---

## Edge Cases

### No Alternative Models Configured

```
**Your AI Configuration**

Currently using **Claude** (premium) only.

Want to save money or work offline? Run `/ai-setup` to configure:
- 💰 Budget cloud (80% cheaper for routine tasks)
- ✈️ Offline mode (works without internet)
```

### Currently Offline

```
**Your AI Configuration**

⚠️ **Currently offline** — Using local model

| Mode | Status |
|------|--------|
| Premium (Claude) | ❌ No internet |
| Budget Cloud | ❌ No internet |
| **Offline** | ✅ Active |

**Using:** Qwen 2.5 14B (local)

When you're back online, I'll automatically have access to Claude again.
```

## Track Usage (Silent)

Update `System/usage_log.md` to mark AI status check as used.

**Analytics (Silent):**

Call `track_event` with event_name `ai_status_checked` (no properties).

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".
