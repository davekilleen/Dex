# Dex Onboarding Flow

Guide new users through setup in a friendly conversation of about 10 minutes. Keep it simple, practical, and focused on getting them working quickly.

## Before Starting

**CRITICAL:** Call `start_onboarding_session()` from onboarding-mcp to initialize or resume onboarding.

- If a session exists, show progress and ask if they want to resume or start fresh
- The MCP tracks completion and validates each step
- Session state enables resume if interrupted

### Choose where Dex should work (before Calendar First)

The start response includes `harness_setup` and `harness_capabilities`. This is a capability preview,
not proof that the detection is right.

1. If one or more harnesses were detected, say: "I found [names]. Do you want Dex available
   in all of those, or should I change the selection?" Allow multiple choices.
2. If none were detected, call `inspect_harnesses()` and present the returned `available`
   choices. Allow multiple choices.
3. If the user changes the selection, call `inspect_harnesses(harnesses=[...])` and show the
   resulting rows before saving.
4. Explain the four labels once: **automatic** runs at the right moment without asking;
   **on demand** is available as a skill/tool; **guided** needs a visible fallback step;
   **unavailable** is not provided by that host. Also say each selected host's named
   limits in plain words. Mode counts are not enough if a host has no built-in tool
   door, is Mac-only, or is still unreleased.
5. After the user confirms, call
   `save_harness_selection(harnesses=[...], confirmed=true)`. Never set `confirmed=true`
   without showing the capability preview.

Selecting more than one harness is supported. Do not make the user choose a single "main"
assistant, and do not promise that a guided or unavailable behavior is automatic.

**After each step (1-8):** Call `validate_and_save_step(step_number=X, step_data={...})` before proceeding. If validation fails, show the error and retry the step.

### Question UI detection (do this once, before Step 1)

This choice affects only how questions are displayed. Harness capabilities come from the
saved profile above, never from guessing based on a tool name. Use the host's structured
question tool when one is available; otherwise use numbered text options and accept typed
responses. Remember that choice for the rest of onboarding.

---

## Calendar First (Before Step 1)

Say: "Welcome to Dex. Before I ask you anything, let's connect your calendar — at the end of setup I'll show you your actual week, organised. It takes a few seconds, and you can skip it."

This opening is separate from the eight validated profile steps. It must stay non-blocking.

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

Keep the returned `calendar_source` object in the current conversation until the
explicit context-approval step after finalization. It is a proposal, not saved
profile state. Never copy `calendar_source`, `work_calendar`, or `work_email` into
the onboarding session or any `validate_and_save_step` call. `work_email` is used
only for the immediate identity-confirmation offer below.

Keep the `working_week_suggestion` from the successful save response for Step 7. It includes the suggested days, whether the suggestion came from calendar evidence or the safe default, and a plain reason when Dex could not make a useful calendar-based guess.

The successful save response also includes `derived_identity`, with conservative `name` and `domain` guesses when `work_email` is usable:

- **If both `name` and `domain` are present:** Say: "You're [name], at [domain] — right?" Present two choices: **Yes, that's right** and **Let me correct that**.
  - On **Yes, that's right**, call `validate_and_save_step(step_number=1, step_data={"name": "[confirmed name]"})`. Remember the confirmed domain, continue through Steps 2 and 3 in order, then call `validate_and_save_step(step_number=4, step_data={"email_domain": "[confirmed domain]"})` when the flow reaches Step 4.
  - On **Let me correct that**, collect both normally. Save the corrected name through step 1, remember the corrected domain or explicit no-company-domain answer, continue through Steps 2 and 3 in order, then save that remembered answer through step 4.
- **If only `domain` is present:** Offer the domain for confirmation: "It looks like your company domain is [domain] — right?" Remember the confirmed domain, corrected domain, or explicit no-company-domain answer. Then ask for the name normally in Step 1, continue through Steps 2 and 3 in order, and save the remembered answer when the flow reaches Step 4.
- **If there is no `work_email`, or neither value can be derived:** Do not guess or mention the failed derivation. Follow Steps 1 and 4 exactly as written.

Do not bypass either validation call or call step 4 early. Only skip the corresponding later question after that step's validation call succeeds.

**If the listing fails or calendar permission is denied:**

Say: "macOS hasn't let this terminal app read your calendars yet — open **System Settings** → **Privacy & Security** → **Calendars** and enable the terminal app you're using."

Offer two choices:
1. Try again after granting access — call `calendar_list_calendars` again
2. Skip for now — call `save_calendar_selection(skipped=true)`

Do not block onboarding when they skip. Keep the returned
`calendar_source={"provider":"none"}` for the later approval step.
`/dex-doctor` will confirm the calendar setup later. Continue to Step 1.

---

## Meeting Sources (Before Step 1)

Make one short, optional offer while the rest of onboarding is still ahead. Run:

```bash
node core/integrations/integration-concierge.cjs
```

Use only meeting tools the concierge actually detected in `high_value`, `moderate_value`, or `connect_detected` (an installed app, configured connector, or real vault signal). Ask: "I spotted [detected meeting tools]. Want me to start pulling notes from any of those while we finish setting up? You can skip this."

Do not ask eligibility questions. Route only what Dex can honestly read:

- **Granola:** connect with `/connect granola`, then use Dex's Granola API reader.
- **Zoom:** use `/zoom-setup`, then Dex's Zoom recording/transcript reader.
- **Teams:** use `/ms-teams-setup`, then Dex's Teams reader for the meeting context it exposes.
- **Any other meeting-notes tool:** do not imply Dex has a direct reader. Offer: "Point me at a folder of exported notes and I'll import the `.md`, `.txt`, `.vtt`, and `.srt` files." Run `python -m core.ritual_intelligence import-transcript-folder "<folder>"`.

After a selected reader is connected, start its initial sync as a background task and continue to Step 1 without waiting for the backfill. For a folder, start the import the same way. Say plainly: "I'll keep that running in the background while we finish setting up."

**Persist the choice.** Record what the user picked in `System/user-profile.yaml` → `meeting_sources`: set `primary` (granola / zoom / teams / exported-folder / wispr / none) and, for a folder, `notes_folder` (the vault-relative folder where the notes land). Meeting skills read this later to know where notes live — an unrecorded choice is forgotten the moment onboarding ends. If the user skips, leave the template default.

If nothing relevant is detected, offer the exported-notes folder once. If the user says skip, later, or no, continue immediately. This offer has no validation step and must never block onboarding.

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

If a domain or explicit no-company-domain answer was remembered from the calendar
confirmation, save it now through `validate_and_save_step(step_number=4, ...)` and
continue to Step 5 after validation succeeds. Otherwise:

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

## Step 7: Working Week

Use the `working_week_suggestion` returned when the calendar choice was saved. Always show the suggestion and let the user change it.

- When `basis` is `calendar`, say: "Looks like you work [suggested days] — right?"
- When `basis` is `default`, say: "[reason] I've suggested Monday to Friday — is that right?"

Present two choices: **Yes, that's right** and **Change the days**.

- If they confirm, use the suggested `days`.
- If they choose to change it, ask: "Which days do you work?" Let them select any combination of Monday through Sunday.

Keep this to one short exchange. Ask only which days they work, never why they chose them.

Then call `validate_and_save_step(step_number=7, step_data={"working_week": {"days": [...]}})` using lowercase day names from the confirmed answer.

---

## Step 8: Rooms

**Do not ask a question here.** All three rooms are on for a new vault, so there is
nothing to choose. Onboarding is already long; a question whose answer is always
"yes" only makes it longer.

Say: "Alongside meetings, people, and tasks, you're getting three more rooms:
**Companies** for the organizations you deal with, **Career** for growth evidence
and resumes, and **Quarter Goals** for 3-month planning. All three are set up and
ready — you don't have to use them, and nothing appears in them until you do."

Then move straight to Step 9. **Do not call `validate_and_save_step` for step 8.**
Finalization fills in every room it wasn't given an answer for, using the shipped
defaults, which turns all three on and creates their folders.

**If the user volunteers that they don't want one** — "skip the career stuff", "I
don't need quarterly planning" — take them at their word and record only that room:

```text
validate_and_save_step(
  step_number=8,
  step_data={"capabilities": {"career": false}}
)
```

Only name the rooms they actually spoke about. Any room you leave out still follows
the default, and a recorded answer — on or off — is never overwritten later.

Say: "You can change these later with `/manage-capabilities`. Turning a room off never deletes its notes; it only hides that room's skills and stops new room content from being created."

---

## Step 9: Generate Structure

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
8. Provision folders and skills only for the optional rooms selected in Step 8
9. Delete session file on success

The MCP returns a summary of what was created (folders, files, configs).

**After creation, say:** "✓ Workspace created! You now have a structure tailored for [their role]."

Show the summary from the MCP response.

### Confirm working context and calendar

The profile now exists, so collect the small amount of context Dex needs to be
useful without putting any of it in the deleted onboarding session. Ask these as
one short conversational review. The first answer is required; accept "skip" for
any of the remaining optional answers:

- "What matters most in your role right now?" → `role_focus`
- "What are you actively working on?" → `current_work`
- "What would make this week successful?" → `week_success`
- "What outcome matters most this quarter?" → `quarter_outcome`
- "Who are up to five people Dex should understand first?" For each confirmed
  person, collect `name` and optionally `relationship` and `how_to_help` →
  `key_people`
- "Anything else Dex should keep in mind?" → `anything_else`

Build one `working_context` object from only those reviewed answers. Omit empty
text fields and use an empty `key_people` list when none were provided.

Use the exact `calendar_source` returned earlier by
`save_calendar_selection`. If this is a resumed conversation and that returned
object is no longer available, repeat the Calendar First choice and validation;
do not reconstruct it from the onboarding session or guess.

Call:

```text
preview_confirmed_onboarding_context(
  working_context={...},
  calendar_source={...}
)
```

Show the normalized `working_context`, `calendar_source`, and the single proposed
profile path from the returned preview. Ask: "Save exactly this to your Dex
profile? Yes / Change it / Skip for now."

- On **Change it**, collect the correction and create a fresh preview. Never reuse
  the old token.
- On **Skip for now**, do not apply anything. Continue with the first-week reveal.
- Only after an **explicit Yes**, call
  `apply_confirmed_onboarding_context(preview=<the exact returned preview>,
  approval_token=<the exact returned approval_token>)`.

Report success only when the apply response contains the lifecycle receipt. Do
not call `apply_confirmed_onboarding_context` after silence, an ambiguous answer,
or approval of a different preview.

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

Then show `draft_weekly_plan` as a suggested draft for the user's week. Do not claim that the draft was written to the vault; this tool analyzes and drafts.

### Offer qualified pages

Only now, after `finalize_onboarding()` has succeeded and the first-week reveal has been shown, call `prepare_entity_page_offer()` from onboarding-mcp. This records the same bounded evidence and applies the same qualification threshold as the background entity engine. It stages suggestions in `System/.dex/entity-suggestions.json`; it never creates a page.

- If `suggestions` is empty, say nothing about pages, page creation, or defaults. Continue directly to Step 9.
- If `suggestions` is non-empty, show the returned names and plain `reason` values. Do not add `top_contacts` or lower the threshold to make the list longer.
- Offer exactly: "I can make pages for these people so their context has somewhere to build. yes / no / never?" Explain only if needed: no means not now; never means do not suggest these specific pages again.
- Apply the answer with `respond_to_entity_page_offer(action="yes"|"no"|"never", suggestion_ids=[the exact returned ids])`. On yes, report both newly created and already-existing/adopted pages as successful; never imply a duplicate or a failure when the result says `existing: true`.
- When a returned company suggestion is present, include it in the same offer. Company suggestions will only be returned when the Companies room is on. Never call a company creation tool separately.

After handling the offer, say: "Ask me about any of them whenever you want — I can look up anyone Dex now knows."

Then ask: "Want me to just do this automatically from now on?"

- Yes: call `set_entity_creation_default(automatic=true)`.
- No: call `set_entity_creation_default(automatic=false)`.

Always make this tool call after their answer. Do not infer the setting from their page-offer answer, and do not leave a completed setup on an unspoken automatic default.

## Step 10: Connect Your Tools (Integration Discovery)

Help the user connect the tools they use. Present the available integrations by category and let them choose — keep it light.

### 10a: Present Available Integrations

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

### 10b: Personalize with Vault Signals

Before asking which to connect, run the integration concierge — it scans for signals of tools the user already works with (apps installed on their Mac, connectors already configured, and mentions/links in their notes), so you can lead with what fits them instead of a flat list:

```bash
node core/integrations/integration-concierge.cjs
```

Parse the JSON for `high_value`, `moderate_value`, and `connect_detected`. Each entry has a `reason` and a `route`: `skill` uses its tested setup skill; `connect` uses `/connect` and deliberately has no `setup` field. Surface curated `high_value` items as before, then add at most the top three `connect_detected` items:

```
Based on what's already on your machine and in your vault, these look most useful:

- `skill`: **[shortName]** — [reason]. [value]. Setup: [setupTime].
- `connect`: **[shortName]** — [reason]. [value]. Connect with `/connect`.
```

Then present the rest of the curated list from 10a for anything not already surfaced. If both `high_value` and `connect_detected` are empty, just use the 10a list — don't mention the scan.

After presenting, set an `integrations_offered` flag in the `.onboarding-complete` marker so `/getting-started` doesn't re-run this discovery.

**Then ask:**

"Which ones would you like to connect? You can always add more later with `/connect`, `/integrate-mcp`, or individual setup commands."

### 10c: Connect Selected Integrations

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

### 10d: Optional Features (After Integrations)

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

**First, connect Granola** — skip this if you already did at the meeting-sources step earlier, where Granola is offered alongside anything else Dex spotted on your machine. Connecting it there uses `/connect`, the same as any other tool. `/granola-setup` still works if you would rather add the key that way. Either route needs an API key from Granola's own settings.

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

Do not emit an analytics consent event from this default setting. A default-on
state is not an affirmative consent action.

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
- **Harness changelog monitor** - Checks the configured reference harness for relevant changes every 6 hours
- **Learning review** - Prompts you to review accumulated learnings daily at 5pm

Without this, checks still run during session start and `/daily-plan` - this just makes them faster."

Ask: "Install background automation?"

**If yes:**
1. Run: `bash .scripts/install-learning-automation.sh`
2. Verify installation completed successfully
3. Say: "✓ Background automation installed. Checks will run automatically."

**If no:**
Say: "No problem! Self-learning checks will still run inline during session start and `/daily-plan`. You can install later with `bash .scripts/install-learning-automation.sh`"

### When Something Goes Wrong (Inform, Don't Ask)

**Shown to everyone, no question attached.** This is where a user learns Dex has a repair
loop at all. Most never find it on their own, and an unreported bug stays broken for
everyone. Say it warmly, once, and move on — there is nothing to save and no config to write.

Say: "Two last things, both for when Dex itself misbehaves.

**Just tell me what happened, in whatever words come naturally.** 'The meeting sync is doing
something weird' is plenty — you don't need a special phrase. I'll investigate on this
machine, write the bug report for you, and show it to you before anything leaves. (If I
don't pick it up as a bug, say 'report this' or run `/feedback` and I will.) The first
report asks you to sign in once, about thirty seconds, so the fix can find its way back to you.

After that it's hands-off. Your report lands on the Dex team's private desk with a reference
number. If they need one more detail, the question comes back here — you'll see it next time
you start a session, and I can go and find the answer and show it to you before it goes.
Ask me how your reports are doing any time. And when a release fixes your bug, your next
session opens with the news and the version that has it.

Nothing from your notes, meetings, people or our conversations ever goes into a report. A
report is built from a fixed list of ingredients — which version of Dex you're on, which
feature broke, the error, and what I found described as counts — and that list is enforced
in the code, not just promised. The whole list is here: https://heydex.ai/help/feedback.html

**And if things just feel off, run `/dex-doctor`.** It checks every part of Dex and tells you
honestly what's working, what's switched off, what's broken, and what it couldn't check —
then repairs what it can repair on its own, without touching your notes, and walks you
through anything left. Worth running after an update, on a new machine, or when something
has quietly stopped happening:
https://heydex.ai/help/updating-troubleshooting.html#health-dex-doctor

Genuinely — feedback is the most useful thing you can give us. Dex gets better because
someone took a moment to say 'this is broken'. Please be that someone."

**Do not turn this into a setup step.** If they ask a question about it, answer it and carry
on. Never ask them to file anything now.

## Step 11: Completion & Phase 2 Bridge

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

**Say this in BOTH cases**, whether or not they wanted the tour — it sits outside the yes/no branches on purpose, and someone who said yes should hear it too:

📖 One more thing worth bookmarking: the **Dex Guide** at https://heydex.ai/help/ — a plain-English walkthrough of everything Dex can do, with copy-paste prompts to steal. Great for your first week.

💬 And remember: if Dex ever misbehaves, just tell me in your own words. I'll investigate, write the report for you, and show it to you before anything is sent — what a report can and can't contain is at https://heydex.ai/help/feedback.html. When things feel off generally, `/dex-doctor` is the checkup."

Then ask: "Want me to put a few gentle nudges in your calendar for your first few weeks? One a day, each with something to try. They're all-day reminders marked private and free, so they never block your time or make you look busy — and you can delete the whole thing in one tap."

Present two choices: **Yes, add them** and **No thanks**.

- On **Yes, add them**: call `generate_nudge_calendar()`. Tell them the file is ready, give its returned path, and explain that opening it will offer to add a new calendar called Dex. On macOS, offer to open it for them with `open <path>`. Say plainly: choose "New Calendar" if asked, so it stays separate and is easy to remove.
- On **No thanks**: say nothing more about it and move on. Do not ask again. Do not capture anything.

---

## Step 12: Phase 2 - Deeper Getting Started (Optional but Recommended)

**Trigger:** Either immediately after Step 11, OR at next session start if vault is < 7 days old.

**Purpose:** Transform "I have a system, now what?" into confidence with a workspace tour, historical meeting processing, and useful next actions. The first-week reveal has already happened automatically in Step 9 and must not be presented again as a new discovery.

**If yes (user wants to continue):** Run the named `/getting-started` skill
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
