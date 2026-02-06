# Dex Onboarding Flow

Guide new users through setup in a friendly ~5 minute conversation. Keep it simple, practical, and focused on getting them working quickly.

## Before Starting

**CRITICAL:** Call `start_onboarding_session()` from onboarding-mcp to initialize or resume onboarding.

- If a session exists, show progress and ask if they want to resume or start fresh
- The MCP tracks completion and validates each step
- Session state enables resume if interrupted

**After each step (1-6):** Call `validate_and_save_step(step_number=X, step_data={...})` before proceeding. If validation fails, show the error and retry the step.

---

## Step 1: Welcome

Say: "Welcome to Dex! I'm your personal knowledge assistant.

**What Dex does:** I help you organize your professional life—meetings, projects, people, ideas, and tasks—all in markdown files you own. Think of me as your executive assistant who never forgets context.

Let's get you set up. First, what's your name?"

**After receiving name:** Call `validate_and_save_step(step_number=1, step_data={"name": "..."})` to validate and save.

---

## Step 2: Role

Ask: "What's your role?"

Present this numbered list:

```
**Core Functions**
1. Product Manager
2. Sales / Account Executive
3. Marketing
4. Engineering
5. Design

**Customer-Facing**
6. Customer Success
7. Solutions Engineering

**Operations**
8. Product Operations
9. RevOps / BizOps
10. Data / Analytics

**Support Functions**
11. Finance
12. People (HR)
13. Legal
14. IT Support

**Leadership**
15. Founder

**C-Suite**
16. CEO
17. CFO
18. COO
19. CMO
20. CRO
21. CTO
22. CPO
23. CIO
24. CISO
25. CHRO / Chief People Officer
26. CLO / General Counsel
27. CCO (Chief Customer Officer)

**Independent / Advisory**
28. Fractional CPO
29. Consultant
30. Coach

**Investment**
31. Venture Capital / Private Equity

Type a number, or describe your role if it's not listed:
```

Accept numbers, role names, or hybrid descriptions like "I'm mostly PM but do some engineering."

**After receiving role:** Call `validate_and_save_step(step_number=2, step_data={"role_number": X})` or `{"role": "...", "role_group": "..."}` to validate and save.

---

## Step 3: Company Size

Ask: "What's your company size?"

Use the AskQuestion tool:
```json
{
  "questions": [{
    "id": "company_size",
    "prompt": "What's your company size?",
    "allow_multiple": false,
    "options": [
      {"id": "startup", "label": "1-100 people (startup/small)"},
      {"id": "scaling", "label": "100-1,000 people (scaling)"},
      {"id": "enterprise", "label": "1,000-10,000 people (enterprise)"},
      {"id": "large_enterprise", "label": "10,000+ people (large enterprise)"}
    ]
  }]
}
```

**After receiving company size:** Call `validate_and_save_step(step_number=3, step_data={"company": "...", "company_size": "[selected id]"})` to validate and save. The `company_size` value should be the option id (startup, scaling, enterprise, or large_enterprise).

---

## Step 4: Email Domain (MANDATORY)

**⚠️ DO NOT SKIP THIS STEP - Required for Internal/External person routing**

Ask: "What's your company email domain? This helps me automatically:
- Identify internal colleagues vs external contacts
- Create company pages for external organizations you meet with"

**Example format:**
- "pendo.io" (without the @)
- "acme.com"
- Multiple domains: "acme.com, acme.io"

**Store in** `System/user-profile.yaml` as `email_domain` field.

**If they're unsure or don't have one:** Set to empty string, system will default to External for all people.

**After receiving email domain:** Call `validate_and_save_step(step_number=4, step_data={"email_domain": "..."})` to validate and save. The MCP enforces:
- Non-empty value
- No @ symbol
- Valid domain format with dot
- This step CANNOT be skipped

---

## Step 4b: Calendar Optimization (Auto-detected)

**This step is AUTOMATIC - no user input needed unless multiple calendars detected.**

**Purpose:** Optimize calendar queries for performance (45s → 0.3s) by identifying the user's work calendar.

**How to check calendar count:**

Run this AppleScript to count calendars:
```bash
osascript -e 'tell application "Calendar" to return count of calendars'
```

**If 1-2 calendars:**
- Skip this step silently
- Store `calendar.calendar_count: 1` in user-profile.yaml
- The system will query all calendars (fast enough with just 1-2)

**If 3+ calendars:**

Say: "I noticed you have [X] calendars connected to Apple Calendar. To keep things fast, I'll focus on your work calendar.

**What's your work email address?** (e.g., dave@company.com)

This helps me:
- Query only your work calendar (much faster)
- Skip personal calendars, holidays, etc."

**After receiving work email:**

1. Verify the calendar exists:
```bash
osascript -e 'tell application "Calendar" to return name of calendars' | grep -i "[work_email]"
```

2. If found, store in `System/user-profile.yaml`:
```yaml
work_email: "user@company.com"
calendar:
  work_calendar: "user@company.com"
  calendar_count: [X]
  lazy_load: true
```

3. Say: "✓ Found your work calendar. Calendar queries will be much faster now."

**If calendar not found:**

Say: "I couldn't find a calendar matching that email. Your calendars are:
[list calendar names]

Which one is your primary work calendar?"

**If user doesn't want to specify:**

Say: "No problem! I'll query all calendars. Note: This may take 15-45 seconds when you ask about your schedule."

Store:
```yaml
calendar:
  work_calendar: ""
  calendar_count: [X]
  lazy_load: true
```

**Note:** This step doesn't use validate_and_save_step() - it's handled inline. Move directly to Step 5.

---

## Step 5: Strategic Pillars

Ask: "What are the 2-3 long-term areas of focus for your role? Think broad themes, not specific goals.

These are your **strategic pillars**—the ongoing areas you'll always focus on, regardless of what specific projects or goals you're working on. They're NOT time-bound.

**Examples of what pillars ARE:**
- 'Pipeline generation' (ongoing area)
- 'Product strategy' (ongoing area)
- 'Customer retention' (ongoing area)

**Examples of what pillars are NOT:**
- 'Close Q1 deals' (that's a quarterly goal)
- 'Launch new feature' (that's a project)
- 'Hit 150% quota' (that's a goal)"

**If they need role-specific examples, show ONLY relevant ones:**
- **Product Manager:** Product strategy, Customer discovery, Engineering partnerships
- **Sales/AE:** Pipeline generation, Customer relationships, Deal execution
- **Customer Success:** Customer retention, Product adoption, Expansion opportunities
- **Engineering:** System reliability, Technical excellence, Team growth
- **Marketing:** Demand generation, Brand positioning, Content strategy
- **CEO/Founder:** Revenue growth, Team development, Product vision
- **For other roles:** Adapt based on their role - think about what they focus on day-to-day

Say: "These pillars organize everything you do. Here's how it flows:
- **Pillars** (ongoing areas) → inform your **quarterly goals** (specific 3-month outcomes)
- **Quarterly goals** → inform your **weekly priorities** (this week's focus)
- **Weekly priorities** → inform your **daily work** (today's tasks)

You'll see this hierarchy in action as you use the system."

**After receiving pillars:** Call `validate_and_save_step(step_number=5, step_data={"pillars": ["...", "..."]})` to validate and save. The MCP enforces 2-3 pillars (warns if outside range).

---

## Step 6: Communication Preferences

Say: "Quick preferences check—how should I communicate with you?"

Use the AskUserQuestion tool to present 3 questions. If AskUserQuestion is not available, ask the same questions via CLI with numbered options and capture the selections:

1. **Formality Level:**
   - Formal (professional, structured)
   - Professional but casual (friendly but business-focused) [recommended]
   - Casual (relaxed, conversational)

2. **Directness:**
   - Very direct (bottom line up front, minimal context)
   - Balanced (context + action) [recommended]
   - Supportive (extra encouragement and explanation)

3. **Your Career Level:**
   - Early career (first 0-3 years in role)
   - Mid-level (3-7 years, established in role)
   - Senior (7+ years, deep expertise)
   - Leadership (managing teams/functions)
   - Executive / C-Suite

Explain: "This helps me match my tone and language to what works for you. You can always change these later by editing `System/user-profile.yaml`."

**After receiving responses:**
1. Save to `System/user-profile.yaml` → `communication` section
2. Map formality to: formal, professional_casual, casual
3. Map directness to: very_direct, balanced, supportive
4. Map career level to: junior, mid, senior, leadership, c_suite
5. Set default coaching_style based on career level:
   - Early career → encouraging
   - Mid-level → collaborative
   - Senior/Leadership/Executive → challenging

**After receiving preferences:** Call `validate_and_save_step(step_number=6, step_data={"communication": {...}, "obsidian_mode": true/false})` to validate and save.

---

## Step 6.5: Obsidian Integration (Optional)

Say: "One more thing—do you use **Obsidian** to view your notes?

**What is Obsidian?** It's a free markdown editor with a graph view that shows connections between notes. Think of it like a visual map of your knowledge.

**Why it matters for Dex:**
- **With Obsidian:** Your vault becomes a connected graph. Click any person, project, or meeting reference to navigate instantly.
- **Without Obsidian:** You'll use Dex through Cursor or terminal, which works great but without clickable links.

**Obsidian is completely optional** - Dex works perfectly either way. Some people love the graph visualization, others prefer terminal/Cursor. Both are first-class experiences.

**New to Obsidian?** [Watch this beginner's guide](https://www.youtube.com/watch?v=gafuqdKwD_U) to see what it can do (5 min)."

Use the AskQuestion tool:
```json
{
  "questions": [{
    "id": "obsidian_mode",
    "prompt": "Do you use Obsidian, or want to try it?",
    "allow_multiple": false,
    "options": [
      {"id": "yes", "label": "Yes - I use Obsidian or want to try it"},
      {"id": "no", "label": "No - I'll use Cursor/terminal"},
      {"id": "later", "label": "Not sure - I'll decide later"}
    ]
  }]
}
```

**If YES (id: "yes"):**
1. Set `obsidian_mode: true` in session data
2. Say: "Great! I'll format all references as wiki links for easy navigation."
3. Optional: "Want me to generate an Obsidian config optimized for Dex? (Recommended settings, hotkeys, etc.)"

**If NO or LATER (id: "no" or "later"):**
1. Set `obsidian_mode: false` in session data
2. Say: "No problem! Your notes will use plain text references. You can enable Obsidian mode anytime with `/dex-obsidian-setup`"

**Important:** Include `obsidian_mode` field in Step 6 data when calling `validate_and_save_step`. It should be part of the same step_data dictionary.

---

## Step 7: Generate Structure

**BEFORE PROCEEDING - MCP Validation:**
1. Call `get_onboarding_status()` to verify all required steps (1-6) are completed
2. If Step 4 (email_domain) missing, STOP and go back - the MCP will block finalization
3. Call `verify_dependencies()` to check Python packages and Calendar.app
4. Show any missing dependencies with installation instructions (if any)

Say: "Perfect! I'm creating your workspace now. Here's what you're getting:

**Dex uses the PARA method:**
- **04-Projects/** — Time-bound work with clear outcomes
- **05-Areas/** — Ongoing responsibilities (People/, Career/, plus role-specific areas)
- **06-Resources/** — Reference material (learnings, quarterly reviews, system docs)
- **07-Archives/** — Historical records (plans, reviews, completed projects)
- **00-Inbox/** — Capture zone (meetings, ideas, notes)

This separates active work from reference material and keeps your capture zone lightweight."

**Then execute finalization:**

Call `finalize_onboarding()` from onboarding-mcp. This single call handles:
1. Pre-check: Verify all steps completed (especially Step 4!)
2. Create PARA folder structure (04-Projects/, 05-Areas/, etc.)
3. Create initial files (03-Tasks/Tasks.md, 02-Week_Priorities/Week_Priorities.md)
4. Write System/user-profile.yaml from session data
5. Write System/pillars.yaml from pillars
6. Update CLAUDE.md User Profile section
7. Setup System/.mcp.json (replace {{VAULT_PATH}} automatically)
8. Delete session file on success

The MCP returns a summary of what was created (folders, files, configs).

**After creation, say:** "✓ Workspace created! You now have a structure tailored for [their role]."

Show the summary from the MCP response.

## Step 8: Optional Features

Say: "The core system is ready. A couple optional add-ons you can set up now or skip:

- **Journaling** — Daily/weekly reflection prompts (2-3 min/day)
- **Granola** — Automatic meeting processing (if you use it)
- **Pendo** — Product analytics integration (if you're a Pendo customer)
- **Background Learning** — Automatic checks for new Claude features and pending learnings (macOS only)

Want to set up any of these now, or skip and discover them later?"

**Note:** Background learning checks run automatically during session start and `/daily-plan` even without this setup. This is just an optimization for faster execution.

### Journaling Setup (if selected):

Ask: "Which journaling prompts do you want?"
- Morning (intention-setting)
- Evening (reflection)
- Weekly (patterns)
- All three

**Then:**
1. Create `00-Inbox/Journals/` folder
2. Update `System/user-profile.yaml` with selections
3. Say: "✓ Journaling enabled. You'll see prompts in `/daily-plan` and `/review`"

### Granola Setup (if selected):

Say: "Granola captures your meeting notes and transcripts. I can help you process them.

**Processing modes:**
- **Manual** (recommended) — Run `/process-meetings` when you want. No API key needed.
- **Automatic** — Background sync every 30 minutes. Requires API key (Gemini/Anthropic/OpenAI).

**What gets processed:**
When you first connect Granola (or later via `/getting-started`), you'll choose:
- How much history to backfill (people pages, meeting notes, todos)
- Different time ranges for each type (e.g., all people, last 30 days notes, last 7 days todos)

Want to set up manual or automatic processing?"

**If manual:** 
1. Update `System/user-profile.yaml` with `meeting_processing: manual`
2. Say: "✓ Manual processing enabled. Run `/process-meetings` or `/getting-started` to process your Granola data."

**If automatic:**
1. Ask which provider (Gemini has free tier)
2. Get their API key
3. Update `System/user-profile.yaml` and `.env`
4. Say: "✓ Automatic processing enabled. I'll sync every 30 minutes. You can still use `/getting-started` for historical data."

### Analytics Consent (Always Ask):

**This is asked for ALL new users, not just those selecting Pendo.**

Say: "One quick question before we finish:

**Dave could use your help improving Dex.** By sharing anonymous feature usage—things like 'ran /daily-plan' or 'created a task'—you help show what's working and what needs improvement.

• **What's tracked:** Only Dex built-in features (not anything you customize or add)
• **What Dave never sees:** What you DO with features—just that you used them
• **Never sent:** Your content, names, notes, conversations, or anything personal
• **Your control:** You can change this anytime in System/user-profile.yaml

**Help improve Dex?**"

Use the AskQuestion tool:
```json
{
  "questions": [{
    "id": "analytics_consent",
    "prompt": "Share anonymous usage data to help improve Dex?",
    "allow_multiple": false,
    "options": [
      {"id": "yes", "label": "Yes, help improve Dex"},
      {"id": "no", "label": "No thanks"}
    ]
  }]
}
```

**If YES:**
1. Update `System/user-profile.yaml`:
   ```yaml
   analytics:
     enabled: true
     anonymous: true
   ```
2. Update `System/usage_log.md`:
   - `Consent asked: true`
   - `Consent decision: opted-in`
   - `Consent date: YYYY-MM-DD`
3. Fire `analytics_consent_given` event (first event!)
4. Say: "Thanks! This really helps Dave make Dex better. 🙏"

**If NO:**
1. Update `System/user-profile.yaml`:
   ```yaml
   analytics:
     enabled: false
   ```
2. Update `System/usage_log.md`:
   - `Consent asked: true`
   - `Consent decision: opted-out`
   - `Consent date: YYYY-MM-DD`
3. Say: "No problem! Dex works exactly the same either way."

---

### Pendo MCP Setup (if selected - for Pendo customers):

Ask: "Are you a Pendo customer? Pendo's MCP integration gives you:
- Guide performance tracking (in-app messages, onboarding flows)
- Feature adoption metrics
- Visitor and account engagement data
- Product usage insights

**What you'll need:**
- Pendo subscription with MCP enabled (admin must enable in Settings → Subscription Settings → AI Features)
- Your Pendo login credentials for OAuth

Want to connect Pendo now?"

**If yes:**
1. Say: "I'll guide you through adding Pendo's hosted MCP server."
2. Ask: "Which AI client are you using? (Cursor/Claude Desktop/Claude Code/ChatGPT/Gemini CLI/Windsurf/Other)"
3. Based on their answer, provide specific setup instructions:

**For Cursor:**
```
1. Go to Cursor → Settings → Cursor Settings
2. In Tools & MCP, select "+ New MCP Server"
3. Add this configuration to your mcp.json:

{
  "mcpServers": {
    "pendo": {
      "url": "https://app.pendo.io/mcp/v0/shttp"
    }
  }
}

4. Select "Connect" and sign in with your Pendo credentials
5. Allow Cursor to access your Pendo subscription
```

**For Claude Desktop:**
- Admin must first add Pendo connector in Admin Settings → Connectors
- Then users can connect via Settings → Connectors → Pendo → Connect

**For other clients:** Provide the regional URL (US: `https://app.pendo.io/mcp/v0/shttp`) and OAuth instructions.

4. Update `System/user-profile.yaml` with `pendo_mcp_enabled: true` to track that it's configured
5. Say: "✓ Pendo MCP configured! Once you authenticate, you can query product analytics. Try asking about guide performance or feature adoption."

**If no:**
Say: "No problem! You can connect Pendo MCP later. Full instructions: https://support.pendo.io/hc/en-us/articles/41102236924955"

### Background Learning Setup (if selected, macOS only):

Say: "This installs two background jobs that run automatically:
- **Changelog monitor** - Checks for new Claude Code features every 6 hours
- **Learning review** - Prompts you to review accumulated learnings daily at 5pm

Without this, checks still run during session start and `/daily-plan` - this just makes them faster."

Ask: "Install background automation?"

**If yes:**
1. Run: `bash .scripts/install-learning-automation.sh`
2. Verify installation completed successfully
3. Say: "✓ Background automation installed. Checks will run automatically."

**If no:**
Say: "No problem! Self-learning checks will still run inline during session start and `/daily-plan`. You can install later with `bash .scripts/install-learning-automation.sh`"

## Step 9: Completion & Phase 2 Bridge

### Cursor Version Check (If Cursor Detected)

Before the completion message, check if user is using Cursor < 2.4:

**Check:** Look for `~/.cursor` directory. If it exists, try to detect version from `/Applications/Cursor.app/Contents/Info.plist` (macOS).

**If Cursor < 2.4 detected:**

Say: "⚠️ **Important: Cursor Version Update Needed**

I noticed you're using Cursor [version]. Dex skills (like `/daily-plan`, `/meeting-prep`, etc.) require **Cursor 2.4 or later**.

**To update:**
1. Cursor menu → Check for Updates, OR
2. Download latest from [cursor.com](https://cursor.com)

After updating, all Dex skills will work automatically. For now, you can continue setup, but skills won't appear in the `/` menu until you upgrade.

[Continue with setup anyway] / [Pause and update Cursor first]"

**If user continues:** Proceed with setup, skills will work after they update.
**If user pauses:** Say "No problem! Update Cursor first, then come back and type `/setup` to resume."

---

### Completion Message

Say: "✓ **Your workspace is ready, [Name]!**

I've configured your system with:
- Strategic pillars: [list their pillars]
- Folder structure for PARA method
- [Any optional features they enabled]
- **All your integrations** (calendar, Granola, etc.)

**Here's what happens next:**

I'm going to analyze your calendar and recent meetings to:
• Create your weekly plan with actual meeting data
• Build person pages for your frequent contacts  
• Show you what's on your plate this week
• Get you oriented with quick wins

This takes about 2 minutes and shows you what Dex can really do.

**Want me to run the getting started tour?** (Highly recommended)

[If yes:] Great! Running `/getting-started` now...

[Then actually invoke the /getting-started skill, which will have MCPs loaded]

[If no:] No problem! You can run `/getting-started` anytime. For now, try `/daily-plan` to see your day."

---

## Step 10: Phase 2 - Getting Started (Optional but Recommended)

**Trigger:** Either immediately after Step 9, OR at next session start if vault is < 7 days old.

**Purpose:** Transform "I have a system, now what?" into immediate value and confidence. This is where the **dramatic reveal** happens - analyzing their calendar/Granola data and showing what Dex built automatically.

**If yes (user wants to continue):** Run `/getting-started` skill (see `.claude/skills/getting-started/SKILL.md`)
- The skill will check for `pre_analysis_deferred: true` flag in `.onboarding-complete`
- If found, it will run the full calendar/Granola analysis NOW
- This includes the dramatic reveal showing meetings, contacts, and auto-created artifacts
- Much better UX than blocking during finalization

**If no:** 
"No problem! You can always run `/getting-started` later when you're ready.

**Quick reference:**
- `/daily-plan` - Start your day with context
- `/meeting-prep [person]` - Prep for meetings
- `/dex-level-up` - Discover features
- `/getting-started` - Come back to this tour anytime (includes data analysis)

What would you like to work on first?"

---

## Post-Onboarding (Optional)

**If user wants to continue setup:**

Say: "Want to set up quarterly goals? These are 3-5 specific outcomes over 3 months that advance your pillars."

**If yes:**

Ask: "What are your top 3-5 goals for this quarter? These should be specific outcomes that advance your pillars."

**Then:**
1. Create `01-Quarter_Goals/Quarter_Goals.md` with their goals
2. Tag each goal to a pillar
3. Say: "✓ Goals set! You can update these anytime with `/quarter-plan`"

**If no:**
Say: "No problem! You can set them up later with `/quarter-plan`."

---

## Final Completion

After all chosen post-onboarding features are set up (or skipped):

Say: "All done! You're ready to use Dex. What would you like to work on first?"

## For Existing Notes

If user mentions they have existing notes, say: "Just copy them into the `00-Inbox/` folder and I'll help you organize them."

## Viewing Your Notes

Dex creates markdown files you can view with any app: VS Code, Cursor, Obsidian, or any text editor.

---

## Size-Based Adjustments

Complexity scales with company size:

**1-100 (Startup)**
- Lean structure, fewer folders
- Action-biased, less process
- Generalist focus

**100-1k (Scaling)**
- Cross-functional templates
- Process documentation
- Scaling playbooks

**1k-10k (Enterprise)**
- Stakeholder maps
- Governance docs
- More formal structure

**10k+ (Large Enterprise)**
- Influence tracking
- Political navigation notes
- Strategic focus over tactical
