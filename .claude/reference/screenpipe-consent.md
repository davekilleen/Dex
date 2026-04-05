# ScreenPipe Consent Flow (One-Time Ask)

**Beta Feature:** Only applies if user has activated the screenpipe beta.

**Before prompting, check:**
1. Call `check_beta_enabled(feature="screenpipe")` from Beta MCP
2. If NOT enabled → skip ScreenPipe entirely (no prompt, no scanning)
3. If enabled → check `System/usage_log.md` → ScreenPipe Consent section

**If screenpipe beta is enabled AND `Consent asked: false` AND user-profile.yaml `screenpipe.prompted: false`:**

During `/daily-plan` or `/daily-review`, ask ONCE per vault:

```
**🔔 New Feature: Ambient Commitment Detection**

Dex can now detect promises and asks from your screen activity — things like
"I'll send that over" in Slack or "Can you review this?" in email.

**How it works:**
- ScreenPipe records your screen locally (never sent anywhere)
- Dex scans for commitment patterns during your daily review
- You decide what becomes a task — nothing auto-created

**Privacy-first:**
- All data stays on your machine
- Browsers, banking, social media blocked by default
- Auto-deletes after 30 days
- Disable anytime with `/screenpipe-setup disable`

**Want to enable ScreenPipe features?** [Yes, set it up] / [Not now] / [Never ask again]
```

Based on response:
- **Yes**:
  - Run `/screenpipe-setup` inline
  - Update `System/user-profile.yaml` → `screenpipe.enabled: true`, `screenpipe.prompted: true`
  - Update `System/usage_log.md` → ScreenPipe Consent: `opted-in`

- **Not now**:
  - Update `System/user-profile.yaml` → `screenpipe.prompted: true`
  - Say: "No problem! Run `/screenpipe-setup` anytime if you change your mind."
  - Ask again in 7 days (don't mark as permanent opt-out)

- **Never ask again**:
  - Update `System/user-profile.yaml` → `screenpipe.enabled: false`, `screenpipe.prompted: true`
  - Update `System/usage_log.md` → ScreenPipe Consent: `opted-out`
  - Remove this section from CLAUDE.md
