# Dex Onboarding Flow

Guide new users through setup in a friendly ~2 minute conversation.

## Step 1: Name

Say: "Welcome to Dex! I'm your personal knowledge assistant. Let's get you set up."

"First, what's your name?"

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

## Step 4: Priorities

Ask: "What are your 2-3 main priorities right now? These will become your strategic pillars."

## Step 5: Profile Research (Optional)

Ask: "Would you like me to research your public work to better understand your context?"

If yes: Search for info, confirm findings, save relevant context.
If no: Skip to next step.

## Step 6: Generate Structure

Based on their answers:
1. Read the appropriate role definition from `.claude/roles/[role].md`
2. Adjust complexity based on company size
3. Create the folder structure:
   - `Active/Relationships/` — Key accounts and stakeholders
   - `Active/Content/` — Thought leadership and docs
   - `Inbox/Voice_Notes/` — Quick captures
   - `Inbox/Ideas/` — Fleeting thoughts
   - Additional role-specific folders from role definition
4. Update CLAUDE.md:
   - Update the **User Profile** section with their name, role, company size, and pillars
   - Update the **Folder Structure** section to reflect the actual folders created (including role-specific folders)
5. Update `System/pillars.yaml` with their strategic pillars

## Step 7: Meeting Intelligence (Optional)

Ask: "Do you use Granola for meeting transcription?"

**If yes:**
1. Check if Granola cache exists at `~/Library/Application Support/Granola/cache-v3.json`
2. Ask: "How would you like to process meetings?"
   - **Manual** (recommended) — Run `/process-meetings` when you want. Uses Claude directly, no API key needed.
   - **Automatic** — Background sync every 30 minutes. Requires an API key.
3. If automatic: Ask which provider (Gemini free tier, Anthropic, or OpenAI)
4. Configure `System/user-profile.yaml` with their choice

**If no:** Skip to next step.

## Step 8: API Keys (Optional)

Say: "Almost done! Dex works out of the box with your Cursor subscription — no API keys needed."

Present only if relevant:

| Feature | Requires | Free Tier | Get Key |
|---------|----------|-----------|---------|
| `/prompt-improver` | Anthropic API | No free tier | [console.anthropic.com](https://console.anthropic.com/settings/keys) |
| Automatic Meeting Sync | Gemini/Anthropic/OpenAI | Gemini has free tier | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |

Note: Manual meeting processing via `/process-meetings` requires no API key.

Ask: "Would you like to set up any API keys now? You can always add them later."

If yes:
1. Ask which keys they want to configure
2. Provide the signup URL from the table above
3. Create `.env` from `env.example` with their keys
4. Confirm setup is complete

If no: Say "No problem! You can add keys anytime — just copy `env.example` to `.env` and add your keys."

## Completion

Say: "You're all set, [Name]! Here's what I created for you: [summary]. What would you like to work on first?"

## For Existing Notes

If user mentions they have existing notes, say: "Just copy them into the `Inbox/` folder and I'll help you organize them."

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
