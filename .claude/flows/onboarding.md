# Dex Onboarding Flow

Guide new users through setup in a friendly conversation of about 10 minutes. Keep it simple, practical, and focused on getting them working quickly.

## Before Starting

**CRITICAL:** Call `start_onboarding_session()` from onboarding-mcp to initialize or resume onboarding.

- If a session exists, show progress and ask if they want to resume or start fresh
- The MCP tracks completion and validates each step
- Session state enables resume if interrupted

**After each step (1-7):** Call `validate_and_save_step(step_number=X, step_data={...})` before proceeding. If validation fails, show the error and retry the step.

### Platform Detection (do this once, before Step 1)

Detect which question tool is available so all subsequent steps use the right one:

- If the `AskQuestion` tool is available → you are in **Cursor**. Use `AskQuestion` for all choice prompts.
- If the `AskUserQuestion` tool is available → you are in **Claude Code** (CLI or Desktop). Use `AskUserQuestion` for all choice prompts.
- If neither tool is available → use **numbered text options** and accept typed responses.

Remember this for the rest of onboarding. Every step that says "present options" should use whichever tool you detected here. The JSON schemas below work identically for both `AskQuestion` and `AskUserQuestion`.

---

## Calendar First (Before Step 1)

Say: "Welcome to Dex. Before I ask you anything, let's connect your calendar — at the end of setup I'll show you your actual week, organised. It takes a few seconds, and you can skip it."

This opening is separate from the seven validated profile steps. It must stay non-blocking.

Detect the host platform first. Run `uname -s` when available; if that command is unavailable, use the runtime-reported operating system.

**On non-macOS platforms (anything other than `Darwin`):**

Say: "Calendar sync is currently available only on macOS, so I'll skip calendar setup on this computer."

Call `save_calendar_selection(skipped=true)`, then continue to Step 1. Do not call `calendar_list_calendars`, show macOS settings guidance, or block onboarding.

**On macOS:**

Call `calendar_list_calendars` from the Calendar MCP to get the calendar names Calendar.app can see.

**If the listing succeeds:**

Say: "Which calendar should I use for your work schedule?"

Present every returned calendar name as a numbered list:
```
1. [exact calendar name]
2. [exact calendar name]
3. [exact calendar name]
```

The user can reply with a number or type the calendar name. Resolve a number to the exact returned name, then call `save_calendar_selection` from the Onboarding MCP with:
- `work_calendar`: the exact selected calendar name
- `calendar_count`: the `count` returned by `calendar_list_calendars`
- `work_email`: the selected name only when that calendar name is an email address; otherwise omit it

Example:
```
save_calendar_selection(
  work_calendar="jane@example.com",
  work_email="jane@example.com",
  calendar_count=4
)
```

If the save returns `success: false`, show the available names from its error response and ask the user to choose again. If it succeeds, say: "✓ Got it — I'll use [calendar name] for your work schedule."

The successful save response includes `derived_identity`, with conservative `name` and `domain` guesses when `work_email` is usable:

- **If both `name` and `domain` are present:** Say: "You're [name], at [domain] — right?" Present two choices: **Yes, that's right** and **Let me correct that**.
  - On **Yes, that's right**, call `validate_and_save_step(step_number=1, step_data={"name": "[confirmed name]"})`, then call `validate_and_save_step(step_number=4, step_data={"email_domain": "[confirmed domain]"})`.
  - On **Let me correct that**, collect both normally: ask for their name and company email domain, including the existing no-company-domain option, then save each answer through those same step 1 and step 4 calls.
- **If only `domain` is present:** Offer the domain for confirmation: "It looks like your company domain is [domain] — right?" Confirm or correct it through `validate_and_save_step(step_number=4, step_data={"email_domain": "[confirmed domain]"})`, including the existing explicit no-company-domain path when correcting. Then ask for the name normally in Step 1.
- **If there is no `work_email`, or neither value can be derived:** Do not guess or mention the failed derivation. Follow Steps 1 and 4 exactly as written.

Do not bypass either validation call. Only skip the corresponding later question after that step's validation call succeeds.

**If the listing fails or calendar permission is denied:**

Say: "macOS hasn't let this terminal app read your calendars yet — open **System Settings** → **Privacy & Security** → **Calendars** and enable the terminal app you're using."

Offer two choices:
1. Try again after granting access — call `calendar_list_calendars` again
2. Skip for now — call `save_calendar_selection(skipped=true)`

Do not block onboarding when they skip. `/dex-doctor` will confirm the calendar setup later. Continue to Step 1.

---

## Step 1: Welcome

If step 1 was already validated through the calendar confirmation, continue to Step 2. Otherwise:

Say: "Welcome to Dex! I'm your personal knowledge assistant.

**What Dex does:** I help you organize your professional life—meetings, projects, people, ideas, and tasks—all in markdown files you own. Think of me as your executive assistant who never forgets context.

Let's get you set up. First, what's your name?"

**After receiving name:** Call `validate_and_save_step(step_number=1, step_data={"name": "..."})` to validate and save.

---

## Step 2: Role

First ask for their AREA:

Ask: "Which area is closest to your work?"

Present options using your detected platform tool (see "Platform Detection" above):
```json
{
  "questions": [{
    "id": "role_area",
    "prompt": "Which area is closest to your work?",
    "allow_multiple": false,
    "options": [
      {"id": "product", "label": "Product"},
      {"id": "sales", "label": "Sales"},
      {"id": "marketing", "label": "Marketing"},
      {"id": "engineering", "label": "Engineering / Data / IT"},
      {"id": "design", "label": "Design"},
      {"id": "customer_success", "label": "Customer Success"},
      {"id": "operations", "label": "Operations / Finance / People / Legal"},
      {"id": "leadership", "label": "Leadership / Exec / Advisory"},
      {"id": "other", "label": "Something else"}
    ]
  }]
}
```

Then ask for their ROLE using only the roles mapped to the selected area. Keep each existing number as the option id:

- **Product:** `1` Product Manager; `8` Product Operations; `22` CPO; `28` Fractional CPO
- **Sales:** `2` Sales / Account Executive; `7` Solutions Engineering; `20` CRO
- **Marketing:** `3` Marketing; `19` CMO
- **Engineering / Data / IT:** `4` Engineering; `10` Data / Analytics; `14` IT Support; `21` CTO; `23` CIO; `24` CISO
- **Design:** `5` Design
- **Customer Success:** `6` Customer Success; `27` CCO (Chief Customer Officer)
- **Operations / Finance / People / Legal:** `9` RevOps / BizOps; `11` Finance; `12` People (HR); `13` Legal; `17` CFO; `18` COO; `25` CHRO / Chief People Officer; `26` CLO / General Counsel
- **Leadership / Exec / Advisory:** `15` Founder; `16` CEO; `29` Consultant; `30` Coach; `31` Venture Capital / Private Equity

**If user selects "Something else" (id: "other"):**
Ask: "What's your role? Describe it however makes sense — I'll tailor the system accordingly."
Then call `validate_and_save_step(step_number=2, step_data={"role": "[their description]", "role_group": "Custom"})`.

**If user selects a role from an area:**
Call `validate_and_save_step(step_number=2, step_data={"role_number": [selected id as integer]})` to validate and save.

---

## Step 3: Company Size

Ask: "What's your company name? (Optional — leave it blank if you don't have one.)"

Then ask: "What's your company size?"

Present options using your detected platform tool:
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

If step 4 was already validated through the calendar confirmation, continue to Step 5. Otherwise:

**⚠️ ASK EVERY USER - Required for Internal/External person routing**

Ask: "What's your company email domain? This helps me automatically:
- Identify internal colleagues vs external contacts
- Create company pages for external organizations you meet with, if you switch on the Companies room"

**Example format:**
- "acme.com" (without the @)
- Multiple domains: "acme.com, acme.io"

**Store in** `System/user-profile.yaml` as `email_domain` field.

**If they don't have a company domain:** Call `validate_and_save_step(step_number=4, step_data={"email_domain": "", "no_company_domain": true})`. This explicitly completes the required step and defaults all people to External.

**After receiving email domain:** Call `validate_and_save_step(step_number=4, step_data={"email_domain": "..."})` to validate and save. The MCP enforces:
- Valid domain format with dot
- Normalization of a leading @ or a pasted full email address
- A validated domain or an explicit "I don't have one" answer before the step is complete

---

## Step 5: Strategic Pillars

Before asking, call `run_first_week_analysis()` from onboarding-mcp. This is evidence for the question, never an answer to it. Do not infer or guess pillars from calendar activity.

- If `available: true` and `meeting_count` is greater than zero, show one compact evidence block using only `pillar_evidence`:
  - Show `recurring_commitments`; if the list is empty, say that no recurring commitments were identifiable from this week.
  - Show the meeting counts in `internal_external_split`.
  - Show the returned `observations` (at most two).
  - Do not recalculate any count or hours. The MCP has already excluded all-day entries such as flights, holidays, and days off.

Then say: "That's where your time went. Pillars are what you want to be true in a year — and there's often something important that owns none of your calendar yet. That counts too."

- If `available: false` or `meeting_count: 0`, show no evidence block and no apology. Do not mention the failed or empty calendar analysis; continue directly to the unchanged question below.

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

Present these 3 questions using your detected platform tool. If using text fallback, show numbered options for each:

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

Present options using your detected platform tool:
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

## Step 7: Choose Optional Rooms

Say: "Dex's meetings, people, and tasks spine is always on. I can also add three optional rooms now. All three start off unless you say yes."

Present these three plain yes/no questions using your detected platform tool:

```json
{
  "questions": [
    {
      "id": "career",
      "prompt": "Add a Career room for growth evidence, coaching, and resumes?",
      "allow_multiple": false,
      "options": [
        {"id": "yes", "label": "Yes"},
        {"id": "no", "label": "No"}
      ]
    },
    {
      "id": "companies",
      "prompt": "Add a Companies room for organization and account pages?",
      "allow_multiple": false,
      "options": [
        {"id": "yes", "label": "Yes"},
        {"id": "no", "label": "No"}
      ]
    },
    {
      "id": "quarter_goals",
      "prompt": "Add a Quarter Goals room for 3-month planning and reviews?",
      "allow_multiple": false,
      "options": [
        {"id": "yes", "label": "Yes"},
        {"id": "no", "label": "No"}
      ]
    }
  ]
}
```

Map each `yes` to `true` and each `no` to `false`. Then call:

```text
validate_and_save_step(
  step_number=7,
  step_data={
    "capabilities": {
      "career": true/false,
      "companies": true/false,
      "quarter_goals": true/false
    }
  }
)
```

Say: "You can change these later with `/manage-capabilities`. Turning a room off never deletes its notes; it only hides that room's skills and stops new room content from being created."

---

## Step 8: Generate Structure

**BEFORE PROCEEDING - MCP Validation:**
1. Call `get_onboarding_status()` to verify all required steps (1-7) are completed
2. If Step 4 (email_domain) missing, STOP and go back - the MCP will block finalization
3. Call `verify_dependencies()` to check Python packages and Calendar.app
4. Show any missing dependencies with installation instructions (if any)

Say: "Perfect! I'm creating your workspace now. Here's what you're getting:

**Dex uses the PARA method:**
- **04-Projects/** — Time-bound work with clear outcomes
- **05-Areas/** — Ongoing responsibilities (People/ is always on; Career/ and Companies/ appear only if selected)
- **06-Resources/** — Reference material (learnings, quarterly reviews, system docs)
- **07-Archives/** — Historical records (plans, reviews, completed projects)
- **00-Inbox/** — Capture zone (meetings, ideas, notes)

This separates active work from reference material and keeps your capture zone lightweight."

**Then execute finalization:**

Call `finalize_onboarding()` from onboarding-mcp. This single call handles:
1. Pre-check: Verify all steps completed (especially Step 4!)
2. Create PARA folder structure (04-Projects/, 05-Areas/, etc.)
3. Create initial spine files (03-Tasks/Tasks.md, 02-Week_Priorities/Week_Priorities.md)
4. Write System/user-profile.yaml from session data
5. Write System/pillars.yaml from pillars
6. Update CLAUDE.md User Profile section
7. Setup root .mcp.json (replace {{VAULT_PATH}} automatically)
8. Provision folders and skills only for the optional rooms selected in Step 7
9. Delete session file on success

The MCP returns a summary of what was created (folders, files, configs).

**After creation, say:** "✓ Workspace created! You now have a structure tailored for [their role]."

Show the summary from the MCP response.

### Automatic First-Week Reveal

Immediately call `run_first_week_analysis()` from onboarding-mcp. This call is automatic; do not ask whether the user wants a tour first.

Use only the structured fields returned by the tool:

- If `available: false`, say one plain line using its `reason`, then continue: "I couldn't read your calendar for the first-week snapshot: [reason]." Never invent numbers or imply that calendar data was read.
- If `available: true` and `meeting_count: 0`, say: "Your calendar is available, and you have no timed meetings scheduled this week." This is a valid result, not an error.
- If `available: true` and `meeting_count` is greater than zero, present:
  - Timed meetings and `meeting_hours`
  - 1:1 count
  - Busiest day and count
  - `top_contacts`, only when the list is non-empty
  - Recent meeting and people/company counts, only when the corresponding values are non-zero

Then show `draft_weekly_plan` as a suggested draft for the user's week. Do not claim that the draft, person pages, or company pages were written to the vault; this tool analyzes and drafts, it does not create those artifacts.

## Step 9: Connect Your Tools (Integration Discovery)

Help the user connect the tools they use. Present the available integrations by category and let them choose — keep it light.

### 8a: Present Available Integrations

If `System/integrations/config.yaml` exists, read it first and note any already-enabled integrations so you don't re-offer them.

Say: "Now the fun part — let's connect the tools you use day to day."

```
**Here are the integrations available, organized by category:**

**Communication & Email:**
- Google Workspace (Gmail + Calendar + Docs) — Email digest, follow-up detection. Setup: 3 min
- Microsoft Teams — Teams digest alongside Slack. Setup: 2 min

**Task Management:**
- Todoist — Two-way task sync. Setup: 1 min
- Things 3 — Mac-native task sync, no account needed. Setup: 30 sec
- Trello — Board sync, cards become tasks. Setup: 2 min

**Meetings & Knowledge:**
- Zoom — Recording access and scheduling. Setup: 2 min
- Atlassian (Jira + Confluence) — Tickets and docs in daily plans. Setup: 3 min
```

Dex can also connect hundreds of other tools with `/connect`. The quick ones ask you to paste a key; browser sign-ins need a one-time setup where you register your own app for Dex in that tool's own settings. Only Google and Linear have had Dex's security review; anything else asks for your explicit opt-in before Dex continues.

If any integrations are already connected, briefly note them so you don't re-offer.

### 8b: Personalize with Vault Signals

Before asking which to connect, run the integration concierge — it scans for signals of tools the user already works with (apps installed on their Mac, connectors already configured, and mentions/links in their notes), so you can lead with what fits them instead of a flat list:

```bash
node .claude/hooks/integration-concierge.cjs
```

Parse the JSON for `high_value`, `moderate_value`, and `connect_detected`. Each entry has a `reason` and a `route`: `skill` uses its tested setup skill; `connect` uses `/connect` and deliberately has no `setup` field. Surface curated `high_value` items as before, then add at most the top three `connect_detected` items:

```
Based on what's already on your machine and in your vault, these look most useful:

- `skill`: **[shortName]** — [reason]. [value]. Setup: [setupTime].
- `connect`: **[shortName]** — [reason]. [value]. Connect with `/connect`.
```

Then present the rest of the curated list from 8a for anything not already surfaced. If both `high_value` and `connect_detected` are empty, just use the 8a list — don't mention the scan.

After presenting, set an `integrations_offered` flag in the `.onboarding-complete` marker so `/getting-started` doesn't re-run this discovery.

**Then ask:**

"Which ones would you like to connect? You can always add more later with `/connect`, `/integrate-mcp`, or individual setup commands."

### 8c: Connect Selected Integrations

For each integration the user selects, follow its `route`:

- `skill`:
  1. Run its setup skill: invoke the skill referenced in the integration's `setup` field (e.g., `/todoist-setup`, `/google-workspace-setup`)
  2. Wait for the setup skill to complete (each includes auth, config, and verification)
  3. The setup skill shows its **Capability Cascade** at the end (from `integration-patterns.md`):
     - Which existing skills just got smarter
     - What new capabilities are now available
     - Privacy and trust level summary
  4. Move to the next selected integration
- `connect`: invoke `/connect` for that provider; never invent a setup skill or setup time. `/connect` explains whether it needs a pasted key or the browser-sign-in setup. For anything other than Google or Linear, explain that it has not had Dex's security review and get explicit opt-in before using `--allow-unvetted`.

If the user selects multiple, run them in sequence. After each one, confirm success before moving to the next.

If the user says "skip" or "none" or "later":

Say: "No problem! You can connect tools anytime with `/connect`, `/integrate-mcp`, or the individual setup commands. Run `/dex-level-up` to see what's available."

### 8d: Optional Features (After Integrations)

Say: "A couple more optional add-ons:

- **Journaling** — Daily/weekly reflection prompts (2-3 min/day)
- **Granola** — Automatic meeting processing (if you use it)
- **External MCPs** — e.g. product analytics like Pendo, added via `/integrate-mcp` (if you use one)
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
3. Say: "✓ Journaling enabled. You'll see prompts in `/daily-plan` and `/daily-review`"

### Granola Setup (if selected):

Say: "Granola captures your meeting notes and transcripts. I can help you process them.

**First, connect Granola:** Dex uses the official Granola API, which needs a Granola Business plan and an API key. Run `/granola-setup` and I'll walk you through adding it — no file editing needed.

**Processing modes (once connected):**
- **Manual** (recommended) — Run `/process-meetings` when you want. No extra LLM API key needed.
- **Automatic** — Background sync every 30 minutes. Requires an LLM API key (Gemini/Anthropic/OpenAI).

**What gets processed:**
When you first connect Granola (or later via `/getting-started`), you'll choose:
- How much history to backfill (people pages, meeting notes, todos)
- Different time ranges for each type (e.g., all people, last 30 days notes, last 7 days todos)

Want to connect Granola now with `/granola-setup`, then set up manual or automatic processing?"

**If manual:** 
1. Update `System/user-profile.yaml` with:
   ```yaml
   meeting_processing:
     mode: manual
   ```
2. Say: "✓ Manual processing enabled. Once Granola is connected via `/granola-setup`, run `/process-meetings` or `/getting-started` to process your meetings."

**If automatic:**
1. Ask which provider (Gemini has free tier)
2. Get their API key
3. Update `.env` with the provider key and `System/user-profile.yaml` with:
   ```yaml
   meeting_processing:
     mode: automatic
     api_provider: gemini # or anthropic/openai, matching the user's choice
   ```
4. Say: "✓ Automatic processing enabled. I'll sync every 30 minutes. You can still use `/getting-started` for historical data."

### Analytics Notice (Inform, Don't Ask):

**This is shown for ALL new users during onboarding.**

Say: "One last thing: Dex collects anonymous feature usage data—things like 'ran /daily-plan' or 'created a task'—to help improve the product. No content, names, notes, or conversations are ever sent. You can opt out anytime by saying 'turn off Dex analytics'."

Then:
1. Update `System/usage_log.md`:
   - `Consent asked: true`
   - `Consent decision: opted-in`
   - `Consent date: YYYY-MM-DD`
2. Ensure `System/user-profile.yaml` has:
   ```yaml
   analytics:
     enabled: true
     anonymous: true
   ```
3. Fire `analytics_consent_given` event.

---

### External MCP Setup (if selected):

Dex works with any hosted or local MCP server your AI client supports. These are
optional and are **not** shipped with Dex. Product-analytics servers such as Pendo
are one example among many.

Say: "You can connect any external MCP with `/integrate-mcp`, or add it directly in
your AI client's own MCP config and authenticate per the vendor's instructions. For
product analytics like Pendo, follow the vendor's MCP documentation and use their
regional OAuth endpoint."

If the user connects one, you can record it in `System/user-profile.yaml` (for
example, `pendo_mcp_enabled: true`) so Dex knows it's available.

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

## Step 10: Completion & Phase 2 Bridge

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

You've already seen the first-week snapshot from the calendar data Dex could read.

**Want me to run the deeper getting-started tour?** It can show you around the workspace and help process meeting history. (Recommended)

[If yes:] Great! Running `/getting-started` now...

[Then actually invoke the `/getting-started` skill.]

[If no:] No problem! You can run `/getting-started` anytime. For now, try `/daily-plan` to see your day.

📖 One more thing worth bookmarking: the **Dex Guide** at https://heydex.ai/help/ — a plain-English walkthrough of everything Dex can do, with copy-paste prompts to steal. Great for your first week."

---

## Step 11: Phase 2 - Deeper Getting Started (Optional but Recommended)

**Trigger:** Either immediately after Step 10, OR at next session start if vault is < 7 days old.

**Purpose:** Transform "I have a system, now what?" into confidence with a workspace tour, historical meeting processing, and useful next actions. The first-week reveal has already happened automatically in Step 8 and must not be presented again as a new discovery.

**If yes (user wants to continue):** Run `/getting-started` skill (see `.claude/skills/getting-started/SKILL.md`)
- Start with the deeper tour or historical-data choices
- Reuse the first-week context already shown; do not repeat it
- Verify any artifact before saying it was created

**If no:** 
"No problem! You can always run `/getting-started` later when you're ready.

**Quick reference:**
- `/daily-plan` - Start your day with context
- `/meeting-prep [person]` - Prep for meetings
- `/dex-level-up` - Discover features
- `/getting-started` - Come back to the deeper tour anytime

What would you like to work on first?"

---

## Post-Onboarding (Optional)

**If user wants to continue setup:**

If the user enabled the Quarter Goals room, say: "Want to set up your first quarterly goals? These are 3-5 specific outcomes over 3 months that advance your pillars."

If the Quarter Goals room is off, do not ask this follow-up and do not create `01-Quarter_Goals/`.

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
