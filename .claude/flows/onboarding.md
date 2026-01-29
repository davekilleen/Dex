# Dex Onboarding Flow

Guide new users through setup in a friendly ~5 minute conversation. Keep it simple, practical, and focused on getting them working quickly.

## Step 1: Welcome

Say: "Welcome to Dex! I'm your personal knowledge assistant.

**What Dex does:** I help you organize your professional life—meetings, projects, people, ideas, and tasks—all in markdown files you own. Think of me as your executive assistant who never forgets context.

Let's get you set up. First, what's your name?"

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

## Step 3: Company Size

Ask: "What's your company size?"

```
1. 1-100 people (startup/small)
2. 100-1,000 people (scaling)
3. 1,000-10,000 people (enterprise)
4. 10,000+ people (large enterprise)
```

## Step 3.5: Email Domain

Ask: "What's your company email domain? This helps me automatically:
- Identify internal colleagues vs external contacts
- Create company pages for external organizations you meet with"

**Example format:**
- "pendo.io" (without the @)
- "acme.com"
- Multiple domains: "acme.com, acme.io"

**Store in** `System/user-profile.yaml` as `email_domain` field.

**If they're unsure or don't have one:** Set to empty string, system will default to External for all people.

## Step 4: Strategic Pillars

Ask: "What are the 2-3 main themes of your role? These are your strategic pillars—not time-bound priorities, but the broader areas you focus on long-term."

**If they need examples, show ONLY role-relevant ones:**
- **Product Manager:** Product strategy, Customer discovery, Engineering partnerships
- **Sales/AE:** Pipeline generation, Customer relationships, Deal execution
- **Customer Success:** Customer retention, Product adoption, Expansion opportunities
- **Engineering:** System reliability, Technical excellence, Team growth
- **Marketing:** Demand generation, Brand positioning, Content strategy
- **CEO/Founder:** Revenue growth, Team development, Product vision
- **For other roles:** Adapt based on their role - think about what they focus on day-to-day

Say: "These pillars organize your work. Everything connects: pillars → quarterly goals → weekly priorities → daily tasks. You'll see how this works as you use the system."

## Step 5: Communication Preferences

Say: "Quick preferences check—how should I communicate with you?"

Use the AskQuestion tool to present 3 questions:

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

## Step 6: Generate Structure

Say: "Perfect! I'm creating your workspace now. Here's what you're getting:

**Dex uses the PARA method:**
- **04-Projects/** — Time-bound work with clear outcomes
- **05-Areas/** — Ongoing responsibilities (People/, Career/, plus role-specific areas)
- **06-Resources/** — Reference material (learnings, templates, system docs)
- **07-Archives/** — Historical records (plans, reviews, completed projects)
- **00-Inbox/** — Capture zone (meetings, ideas, notes)

This separates active work from reference material and keeps your capture zone lightweight."

**Then execute:**
1. Read the appropriate role definition from `.claude/roles/[role].md`
2. Read `.claude/reference/role-areas-mapping.md` to check if role needs additional areas
3. Create the PARA folder structure:
   - `04-Projects/` — Time-bound initiatives
   - `05-Areas/People/Internal/` and `05-Areas/People/External/` — Person pages (universal)
   - `05-Areas/Companies/` — External organizations (universal for all roles)
   - `00-Inbox/Meetings/`, `00-Inbox/Ideas/` — Capture zone
   - `06-Resources/Learnings/`, `06-Resources/Templates/` — Reference material
   - `07-Archives/04-Projects/`, `07-Archives/Plans/`, `07-Archives/Reviews/` — Historical records
   - **Only if mapped:** Create role-specific area (e.g., `05-Areas/Accounts/` for Sales, `05-Areas/Team/` for CEO, `05-Areas/Content/` for Marketing)
4. Create state files at root:
   - `03-Tasks/Tasks.md` — Task backlog (empty to start)
   - `02-Week_Priorities/Week_Priorities.md` — Weekly priorities (empty to start)
5. Update CLAUDE.md:
   - Update the **User Profile** section with their name, role, company size, and pillars
   - Update the **Folder Structure (PARA)** section to reflect the actual areas created (add role-specific area to the list if created)
6. Update `System/pillars.yaml` with their strategic pillars
7. Update `System/user-profile.yaml`:
   - Add name, role, company, company_size from Steps 1-3
   - Add email_domain from Step 3.5
   - Add communication preferences from Step 5
   - Add role_group (based on mapping)
   - Set meeting_intelligence flags based on role (e.g., customer_intel for PM, stakeholder_dynamics for Sales)

**After creation, say:** "✓ Workspace created! You now have a structure tailored for [their role]."

## Step 7: Optional Features

Say: "The core system is ready. A couple optional add-ons you can set up now or skip:

- **Journaling** — Daily/weekly reflection prompts (2-3 min/day)
- **Granola** — Automatic meeting processing (if you use it)
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

Ask: "How would you like to process meetings?"
- **Manual** (recommended) — Run `/process-meetings` when you want. No API key needed.
- **Automatic** — Background sync every 30 minutes. Requires API key (Gemini/Anthropic/OpenAI).

**If manual:** Update `System/user-profile.yaml` with `meeting_processing: manual`

**If automatic:**
1. Ask which provider (Gemini has free tier)
2. Get their API key
3. Update `System/user-profile.yaml` and `.env`

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

## Step 8: Completion

Say: "You're all set, [Name]! 

**Your workspace:**
- Strategic pillars: [list their pillars]
- Folder structure: 04-Projects/, 05-Areas/, 06-Resources/, 07-Archives/, 00-Inbox/, System/
- [Any optional features they enabled]

**Start here:**
- Run `/daily-plan` to plan your day
- Run `/meeting-prep` before your next meeting (I'll ask who's attending)
- Tell me about a meeting → I'll extract action items and update person pages
- Run `/dex-level-up` to discover unused features and see role-specific skills for [their role]

Want to continue with a few more optional features, or start using the system?"

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
