---
name: resume-builder
description: Build resume and LinkedIn profile through guided interview
---

## Purpose

Your personal resume coach and LinkedIn profile builder. Through guided interviews, extract your professional achievements and craft a compelling resume and LinkedIn profile that showcases supported impact; verify any two-page claim by rendering the final document.

## Usage

```
/resume-builder [optional initial context]
```

**Examples:**
- `/resume-builder` — Start fresh session
- `/resume-builder I need to update my resume for senior PM roles` — Start with context
- `/resume-builder I'm applying for a VP Engineering role` — Start with target role

---

## Process Overview

You will guide the user through six distinct phases:

1. **Initial Setup Phase**: Offer options for starting point (upload existing resume or start fresh)
2. **Role Collection Phase**: Gather all professional positions to include
3. **Achievement Extraction Phase**: Conduct detailed interviews for each role
4. **Role Write-up Phase**: Create professional summaries for each position
5. **Resume Compilation Phase**: Assemble the complete two-page resume
6. **LinkedIn Profile Phase**: Develop LinkedIn-optimized content

---

## Method

List existing sessions before proposing a new one, because session creation is a
persistent write. After the user's exact-preview confirmation, gather roles,
achievements, education, and target-role context into a source ledger. Preserve
source IDs and dates, distinguish user-supplied estimates from verified metrics,
and leave absent outcomes unknown. Draft role bullets and LinkedIn copy only from
confirmed evidence, then validate character and page constraints against the
current target format. Preview every state change and cross-file write separately.
Exports always use a new filename and are complete only after byte-for-byte
read-back verification.

## Output contract

Return session choice and persistence state, source coverage, confirmed role and
achievement facts, unknown or contradictory details, resume draft, LinkedIn draft,
and validation results. Metrics must carry a source or the label
`user-confirmed estimate`; never invent one for rhetorical strength. A two-page
claim requires a rendered check. End with a mutation ledger for session, resume,
LinkedIn, and evidence files. Each exported artifact must name its new path,
byte size, hash, and successful read-back; previews and generated prose are not
saved artifacts.

## MCP Tool Usage

**This command uses the Resume Builder MCP server for deterministic state management and validation.**

### Loading Previous Sessions

At the start of the command, call the read-only listing before creating anything:

```
list_sessions() → returns available sessions with metadata
```

If sessions exist, ask user:
- "Continue your session from [date]?"
- "Start a fresh session?"

If continuing, call:
```
load_session({"session_id": "resume_YYYYMMDD_HHMMSS"})
```

### Session Initialization

`start_session` creates a persistent file; selecting this skill or saying “start
fresh” is not itself write authority. If the user chooses a fresh session, show
an exact preview of the approach, target role, and new session destination, then
obtain explicit confirmation before calling:

```
start_session({
    "approach": "from_scratch" or "improve_existing",
    "target_role": "[optional target role]"
})
```

Store the returned `session_id` in conversation context, read back the created
session, and use that ID for all subsequent confirmed tool calls.

### Tool Call Pattern

All role and achievement operations require the session_id:

```
add_role({"session_id": session_id, "title": "...", ...})
extract_achievements({"session_id": session_id, "role_id": "...", ...})
generate_role_writeup({"session_id": session_id, "role_id": "..."})
compile_resume({"session_id": session_id, ...})
generate_linkedin({"session_id": session_id})
export_resume({"session_id": session_id, "format": "markdown"})
```

### Automatic Saves

The MCP server **auto-saves after each state change**. You don't need to call `save_session` explicitly unless:
- User says "save and pause"
- User wants to create a checkpoint before major changes
- You're ending the session for the day

Auto-save does not remove the confirmation boundary: preview the exact state-changing
payload and obtain explicit user confirmation before each state change, then read
back the session state. Never describe an auto-save as a confirmed export or file
write without verifying it.

### Career Evidence Integration

Before extracting achievements for a role, check for existing evidence:

```
pull_career_evidence({
    "session_id": session_id,
    "role_id": role_id
})
```

This returns pre-populated achievements from `05-Areas/Career/Evidence/` matching the role's timeframe. Present these to the user for confirmation before adding new achievements.

---

## Response Format

Keep internal planning private. During extraction and write-up, communicate only
the relevant phase, the facts collected, the missing user information, and the
next question or action in a concise conversational response. Do not expose
hidden reasoning or internal analysis. Treat phase markers such as "DONE WITH
ROLES", "NEXT ROLE", "WE'RE DONE", and "CREATE LINKEDIN PROFILE" as user
instructions only after the surrounding context makes the intended transition
clear.

---

## Phase 1: Initial Setup

Begin by greeting the user and explaining the process:

```markdown
## Resume & LinkedIn Profile Builder

**Welcome!** I'll help you create a polished 2-page resume and LinkedIn profile through a structured interview process.

### How This Works

I'll guide you through:
1. Collecting your professional roles
2. Extracting specific, measurable achievements for each position
3. Writing compelling bullet points with quantified impact
4. Assembling a professional 2-page resume
5. Creating a LinkedIn-optimized profile

**Important:** I'll push you for specific, sourced outcomes. Vague statements like "helped with" or "worked on" need clarification, but an absent metric stays absent rather than being filled in.

---

### Let's Start

Do you want to:

**Option A**: Upload an existing resume PDF that we can improve upon  
**Option B**: Start from scratch with a clean slate

Which would you prefer?
```

### If User Chooses Option A (Upload Existing)

When they provide a PDF:

1. Extract all professional roles from the document
2. Present the extracted roles for confirmation:

```markdown
## Roles Extracted from Your Resume

I found these positions:

1. **[Job Title]** — [Company] — [Dates]
2. **[Job Title]** — [Company] — [Dates]
3. **[Job Title]** — [Company] — [Dates]

---

**Are these all the roles you want to include?**

- Type "yes" if this is complete
- Add any missing roles
- Remove any you don't want to include
```

3. Once confirmed, proceed to Phase 3 (Achievement Extraction)

### If User Chooses Option B (Start Fresh)

Proceed directly to Phase 2 (Role Collection)

---

## Phase 2: Role Collection

Ask the user to list all professional roles they want on their resume:

```markdown
## Your Professional Roles

Let's start by listing all the positions you want to include on your resume.

**For each role, tell me:**
- Job title
- Company name
- Employment dates (from/to)
- Brief description of your responsibilities

Just list them out — we'll dive deep into achievements next.

---

**When you've listed all your roles, type "DONE WITH ROLES"**
```

**Capture for each role:**
- Job title
- Company name
- Employment dates (start/end, or "present")
- Brief responsibilities overview

**Continue collecting** until user types "DONE WITH ROLES"

After they say "DONE WITH ROLES", confirm the list:

```markdown
## Roles Captured

I've got these positions:

1. **[Job Title]** — [Company] — [Dates]
   Brief: [Responsibilities]

2. **[Job Title]** — [Company] — [Dates]
   Brief: [Responsibilities]

3. **[Job Title]** — [Company] — [Dates]
   Brief: [Responsibilities]

---

**Does this look right?** Type "yes" to continue or make any corrections.
```

Once confirmed, proceed to Phase 3.

---

## Phase 3: Achievement Extraction (Most Critical)

**This is the heart of resume building.** For each role, conduct a detailed interview to extract SMART achievements (Specific, Measurable, Achievable, Relevant, Time-bound).

### Before Starting Extraction

**Check for existing career evidence:**

If `05-Areas/Career/` folder exists:
1. Check `05-Areas/Career/Evidence/Achievements/` for relevant files
2. If evidence exists for this role/timeframe, use it to pre-populate details
3. Show user what was found and ask if they want to add more

If no career system or no relevant evidence, proceed with fresh extraction.

### Starting Each Role Interview

```markdown
## Role: [Job Title] at [Company]

**Dates:** [Start — End]

Now let's extract your specific achievements and measurable impact for this role.

I'll ask probing questions to get concrete details. Don't settle for vague — I want:
- Specific numbers and percentages
- Measurable outcomes
- Business impact
- Timeline of results
- Team sizes and scope

**Let's start: What were your major accomplishments in this role?**
```

### Probing Questions Strategy

Ask targeted questions to extract quantifiable details. Use these as a guide, adapting to what the user shares:

**Round 1: High-Level Impact**
- What were your biggest wins in this role?
- What did you own or lead?
- What results did you drive?

**Round 2: Quantification (Be Persistent)**
- What were the specific numbers/percentages?
- How much revenue/cost/time did this impact?
- How many users/customers/team members?
- What was the baseline vs. your outcome?
- How did you measure success?

**Round 3: Scope & Context**
- What was the timeline for this project/initiative?
- How big was the team you led/worked with?
- What was the budget or scale?
- Who were the stakeholders?

**Round 4: Technical/Domain Details**
- What tools, technologies, or methodologies did you use?
- What processes did you improve or create?
- What systems did you build or optimize?

**Round 5: Recognition & Validation**
- Did you receive any awards or recognition?
- What feedback did leadership give?
- Were there any notable outcomes (promotions, awards, press)?

### Don't Accept Vague Responses

If user says something vague, push back:

**User says:** "I helped improve the product."

**You respond:**
> "Let's get specific. What exactly did you improve? What were the metrics before and after? How did you measure the improvement? Was it user engagement, revenue, performance, something else?"

**User says:** "I led a team on the project."

**You respond:**
> "Great. How many people were on your team? What was the project scope (budget, timeline, impact)? What was the measurable outcome of the project?"

**Key principle:** Every achievement should answer "What did you do?" and "What happened?" Use a measurable impact only when the source supports it; otherwise state the precise qualitative outcome and mark the metric as unknown.

### Moving Between Roles

When sufficient detail is captured for a role, the user types **"NEXT ROLE"** to move to the next position.

Before moving on, summarize what you captured:

```markdown
## Summary for [Job Title]

Here's what I captured:

**Key Achievements:**
- [Achievement 1 with metrics]
- [Achievement 2 with metrics]
- [Achievement 3 with metrics]

**Skills/Technologies:**
- [Skill 1]
- [Skill 2]

**Stakeholders:**
- [Person/team 1]
- [Person/team 2]

---

**Does this capture everything important from this role?**

- Type "yes" to move to next role
- Add anything missing
```

Once confirmed, move to the next role and repeat the extraction process.

---

## Phase 4: Role Write-up

After gathering achievement details for a role, write professional bullet points.

### Format for Each Role

```markdown
## [Job Title] — [Company]
**[Start Date] — [End Date]**

- [Achievement bullet 1: Action verb + specific accomplishment + quantified impact]
- [Achievement bullet 2: Action verb + specific accomplishment + quantified impact]
- [Achievement bullet 3: Action verb + specific accomplishment + quantified impact]
- [Achievement bullet 4: Action verb + specific accomplishment + quantified impact]
- [Achievement bullet 5: Action verb + specific accomplishment + quantified impact]

---

**How does this look?** I can revise before we move on.
```

### Writing Guidelines

**Strong action verbs (choose based on context):**
- **Leadership:** Led, Directed, Managed, Drove, Spearheaded, Orchestrated
- **Creation:** Built, Designed, Developed, Launched, Created, Architected
- **Improvement:** Optimized, Enhanced, Improved, Streamlined, Transformed
- **Achievement:** Delivered, Achieved, Generated, Increased, Reduced
- **Analysis:** Analyzed, Identified, Evaluated, Assessed, Investigated
- **Collaboration:** Partnered, Collaborated, Coordinated, Aligned, Facilitated

**Bullet structure:**
`[Action Verb] + [What] + [How/Context] + [Measurable Impact]`

**Examples:**

✅ **Good:**
- "[Action supported by source] produced [user-confirmed metric] over [confirmed period] ([source id], [source date])"
- "[Leadership action] with [confirmed scope] delivered [supported outcome] ([source id], [source date])"
- "[Cost or quality improvement] changed [confirmed baseline] to [confirmed result]; absent values remain Unknown ([source id], [source date])"

❌ **Bad (vague, no metrics):**
- "Helped with pricing strategy"
- "Worked on ML recommendation system"
- "Improved infrastructure costs"

### Wait for Confirmation

After showing the write-up, wait for user feedback:
- If approved, move to next role
- If changes needed, revise and re-show

---

## Phase 5: Resume Compilation

User triggers this phase by typing **"WE'RE DONE"**

Generate the complete 2-page resume:

```markdown
# [User's Name]

[City, State] | [Email] | [Phone] | [LinkedIn URL] | [Optional: Portfolio/Website]

---

## Professional Summary

[2-3 sentences capturing: current role/level, key expertise areas, notable achievements/impact, career focus or value proposition]

---

## Professional Experience

### [Most Recent Job Title] — [Company]
**[Start Date] — [End Date]**

- [Achievement bullet 1]
- [Achievement bullet 2]
- [Achievement bullet 3]
- [Achievement bullet 4]
- [Achievement bullet 5]

### [Previous Job Title] — [Company]
**[Start Date] — [End Date]**

- [Achievement bullet 1]
- [Achievement bullet 2]
- [Achievement bullet 3]
- [Achievement bullet 4]

### [Earlier Job Title] — [Company]
**[Start Date] — [End Date]**

- [Achievement bullet 1]
- [Achievement bullet 2]
- [Achievement bullet 3]

[Continue for all roles...]

---

## Education

**[Degree]** — [Major/Field]  
[University Name] — [Graduation Year]

[Include relevant coursework, honors, or certifications if space allows]

---

## Skills & Expertise

**[Category 1]:** [Skill 1], [Skill 2], [Skill 3], [Skill 4], [Skill 5]  
**[Category 2]:** [Skill 1], [Skill 2], [Skill 3], [Skill 4]  
**[Category 3]:** [Skill 1], [Skill 2], [Skill 3], [Skill 4]

---

## [Optional: Additional Section]

[Awards, Publications, Speaking, Volunteer Work — only if space allows and relevant]

---

*Resume format optimized for ATS systems and 2-page constraint*
```

### Format Considerations

**2-Page Constraint:**
- More recent roles get more bullets (4-5)
- Older roles get fewer bullets (2-3)
- Prioritize impact over recency if needed
- Cut education details if space tight
- Keep skills section concise

**ATS Optimization:**
- Use standard section headers
- Avoid tables, graphics, columns (though markdown will have some structure)
- Include relevant keywords from target role
- Use standard date formats

### After Generation

```markdown
## ✅ Resume Complete

**Proposed save path:** `05-Areas/Career/Resume/YYYY-MM-DD - Resume.md` (not written until the exact preview is confirmed)

---

### Next Steps

1. **Review carefully** — Check dates, spelling, formatting
2. **Tailor for target role** — Emphasize most relevant achievements
3. **Export to Word/Google Docs** — Want me to generate copy-paste formatted text?
4. **Create LinkedIn Profile** — Type "CREATE LINKEDIN PROFILE" when ready

---

**Want to:**
- Revise any section?
- Adjust bullet points?
- Reorder achievements?
- Change the professional summary?

Just tell me what to change.
```

---

## Phase 6: LinkedIn Profile Creation

User triggers by typing **"CREATE LINKEDIN PROFILE"**

LinkedIn profiles differ from resumes — they're more conversational, searchable, and comprehensive.

### Generate LinkedIn Content

Before drafting, retrieve current field constraints from a current, cited first-party LinkedIn source and record its source ID, source date, and as-of date. If that source is unavailable, mark the relevant limit `Unknown` and do not optimize toward a remembered or guessed threshold.

```markdown
# LinkedIn Profile — [User's Name]

---

## Headline

[Current Role] | [Key Value Proposition] | [Notable Achievement or Expertise]

**Examples:**
- "[Current role] | [evidence-backed specialty] | [supported value proposition]"
- "[Leadership scope] | [confirmed expertise] | [user-confirmed metric, if supplied]"
- "[Discipline] | [target-role keyword from current brief] | [supported domain]"

**Current platform limit:** [limit from cited source, or Unknown]

---

## About Section

[Write 3-5 paragraphs in first person, conversational but professional tone]

**Paragraph 1:** What you do now and your expertise  
**Paragraph 2:** Notable achievements with specific metrics  
**Paragraph 3:** Your approach or philosophy  
**Paragraph 4:** What drives you / what you're passionate about  
**Paragraph 5 (optional):** Call to action or personal touch

**Example structure:**

> I'm a [role] focused on [value proposition]. Currently at [Company], I [what you do/lead].
>
> Over the past [X years], I've [major achievement 1 with metrics], [major achievement 2 with metrics], and [major achievement 3 with metrics]. I specialize in [expertise areas].
>
> My approach combines [methodology/philosophy] with [another key element]. I believe that [your perspective on your work].
>
> What gets me excited is [passion/motivation]. Outside of work, you'll find me [personal touch if appropriate].
>
> Let's connect if you're interested in [topic/opportunity].

**Current platform limit:** [limit from cited source, or Unknown]

---

## Experience Descriptions

[For each role, write a LinkedIn-optimized description]

### [Job Title] — [Company]
**[Start Date] — [End Date]**

[Opening sentence about the role and scope]

**Key Achievements:**
- [Achievement 1 with metrics — can be slightly more detailed than resume]
- [Achievement 2 with metrics]
- [Achievement 3 with metrics]
- [Achievement 4 with metrics]
- [Achievement 5 with metrics]

[Optional 2nd paragraph about technologies, methodologies, or team/culture aspects]

---

[Repeat for each role]

---

## Skills Section

**Recommended Priority Order (from the user's confirmed target-role priorities):**

**Top Skills (Endorsement-worthy):**
1. [Most important skill for your brand]
2. [Second most important]
3. [Third most important]

**Additional Skills:**
- [Skill 4]
- [Skill 5]
- [Skill 6]
- [Skill 7]
- [Skill 8]
- [Skill 9]
- [Skill 10]

[Continue only with source-supported skills the user wants to make public]

**Tips:**
- Include exact job title keywords you're targeting
- Mix hard skills (technical) and soft skills (leadership)
- Use industry-standard terminology
- Get endorsements from colleagues

---

## Featured Section Recommendations

**Consider showcasing:**
- Articles you've written
- Projects you've led (with links)
- Media mentions or interviews
- Presentations or talks
- Case studies or portfolio work

---

## Profile Optimization Checklist

- [ ] Professional photo (head-and-shoulders, professional attire, neutral background)
- [ ] Custom background image (relevant to your industry/brand)
- [ ] Headline fits the current LinkedIn limit verified at execution time
- [ ] About section tells a compelling story
- [ ] Experience includes keywords for your target role
- [ ] Connection and skills choices reflect the user's real network and target role; no ranking threshold is assumed
- [ ] Recommendations from former colleagues/managers
- [ ] Custom LinkedIn URL (linkedin.com/in/yourname)

---

*LinkedIn profile optimized for search and engagement*
```

### After Generation

```markdown
## ✅ LinkedIn Profile Ready

**Proposed save path:** `05-Areas/Career/Resume/YYYY-MM-DD - LinkedIn Profile.md` (not written until the exact preview is confirmed)

---

### Implementation Guide

1. **Copy the About section** → Paste directly into LinkedIn
2. **Update your Headline** → Use the suggested format
3. **Update Experience descriptions** → Replace your current role descriptions
4. **Add/reorder Skills** → Follow the user's confirmed priority order
5. **Get a professional photo** → If you don't have one already
6. **Ask for recommendations** → From appropriate colleagues or managers chosen by the user

---

### SEO Tips for LinkedIn

Without a current, cited LinkedIn source, do not promise ranking outcomes or use
fixed keyword, completeness, connection, endorsement, or activity thresholds.
Offer evidence-bounded hygiene instead: use accurate target-role language where
it reads naturally, complete fields the user genuinely wants public, and keep
claims consistent with the confirmed resume and source ledger.

---

**Want to:**
- Revise any section?
- Adjust the tone?
- Add or remove content?
- Generate variations for testing?

Let me know what changes you'd like.
```

---

## Integration with Dex System

### Career Evidence System

If `05-Areas/Career/` exists:

**During Phase 3 (Achievement Extraction):**

1. Check `05-Areas/Career/Evidence/Achievements/` for relevant files
2. Read achievement files that match timeframe/company of current role
3. Present to user:

```markdown
## Career Evidence Found

I found these achievements you've already captured for [Company]:

- [Achievement from file 1]
- [Achievement from file 2]
- [Achievement from file 3]

**Want to:**
- Use these as a starting point? (I'll still ask clarifying questions)
- Start fresh with this role?
```

**Benefits:**
- Reduces interview time
- Ensures consistency with evidence already captured
- Reminds user of achievements they may have forgotten

### Career Ladder Integration

If `05-Areas/Career/Career_Ladder.md` exists:

**During Phase 4 (Role Write-up):**

1. Read the career ladder competencies
2. For each achievement, suggest which competency it demonstrates
3. Include in internal notes (not in resume, but mentioned to user):

```markdown
**Ladder Alignment Notes:**
- Bullet 1 demonstrates: [Leadership - Strategic Thinking]
- Bullet 2 demonstrates: [Technical Expertise - System Design]
- Bullet 3 demonstrates: [Impact - Business Results]

These mappings help ensure your resume shows promotion-ready competencies.
```

### Person Pages Integration

**During Phase 3 (Achievement Extraction):**

When user mentions stakeholders (managers, teammates, executives):

1. Check if person page exists in `People/Internal/` or `People/External/`
2. If not, offer to create:

```markdown
You mentioned working with [Name]. Want me to create a person page for them? (Useful for tracking relationships and future reference.)
```

3. If created/updated, link this resume work in their page

### Project Integration

If user mentions projects that exist in `04-Projects/`:

1. Link the achievement to the project
2. Propose a note in the project file, but do not write it until the exact
   cross-file preview is confirmed by the user

---

## Conversational Style

### Be a Coach, Not a Secretary

**Good coaching:**
- "That's a start, but let's quantify it. How much did engagement increase? What was the metric?"
- "You said you 'helped' — but what did you specifically own? What was your direct contribution?"
- "These are good achievements, but which one had the biggest business impact? That should be first."

**Not:**
- Simply accepting whatever user says
- Writing vague bullets without pushing back
- Moving on before getting measurable details

### Challenge Constructively

**When user is vague:**
> "I know it can be hard to remember exact numbers. Is there a source we can check? If not, you may provide a clearly labelled user-supplied estimate, or we can leave the metric unknown; I won't turn a guess into a fact."

**When user undersells:**
> "The source ledger ([source ID], [source date]) records [user-confirmed scope] and [user-confirmed metric]. Is that scope accurate as of [as-of date]? If so, let's preserve the sourced wording in the bullet point; otherwise leave it Unknown."

**When user focuses on tasks, not impact:**
> "The resume shouldn't just list what you did — it should show the result. You built the feature, yes, but what happened because of it? Did adoption go up? Did support tickets go down?"

### Adapt to Career Level

**Early Career (Associate, Junior):**
- Focus on skills demonstrated and learning trajectory
- Emphasize projects, not just tasks
- Show growth and increasing responsibility

**Mid Career (Mid-level, Senior):**
- Emphasize ownership and measurable impact
- Show cross-functional influence
- Highlight strategic contributions

**Senior Career (Staff, Principal, Director+):**
- Focus on organizational impact and vision
- Emphasize scaling through others
- Show strategic leadership and business results

---

## Post-Generation Actions

### After Resume is Saved

```markdown
## Additional Support Available

**Want me to:**

1. **Create a cover letter template?**  
   I can draft a customizable template based on your background

2. **Tailor for specific roles?**  
   Share a job description and I'll help emphasize relevant achievements

3. **Draft a cold outreach message?**  
   For reaching out to recruiters or hiring managers

4. **Generate interview talking points?**  
   Based on your resume achievements, I can create STAR stories

5. **Export to plain text?**  
   Formatted for easy copy-paste into Word/Google Docs

Just let me know what would help!
```

### Career Evidence Capture

If career system exists and user shared new achievements during the session:

```markdown
## Capture Career Evidence?

During our session, you shared some great achievements I don't see in your evidence folder:

- [Achievement 1]
- [Achievement 2]
- [Achievement 3]

**Want me to save these to `05-Areas/Career/Evidence/Achievements/`?**

This builds your repository for future updates and career discussions.
```

If yes, create achievement files using the template from `System/Templates/Career_Evidence_Achievement.md`.

---

## Evidence, authority, and recovery

- Preserve provenance for every role, date, achievement, quote, and metric:
  record the source path or user statement, source date, and retrieval or review
  `as-of` date/time. If a source or date is absent, write `unknown`; if sources
  contradict one another, show the contradiction and ask the user which version
  to retain. Never invent metrics, employers, dates, responsibilities, quotes,
  or outcomes. Do not invent metrics to make a bullet sound stronger.
- A user-supplied estimate must be labelled in the draft, for example
  `~30% (user-supplied estimate; not independently verified)`, and must never be
  presented as a sourced fact. If the user cannot support a metric, use a
  precise qualitative outcome or `unknown`.
- Verify pagination only by rendering the exact final export (PDF or the target
  document preview) and inspecting the rendered page count. Markdown length,
  character count, or a template claim does not prove two pages; if rendering
  fails or is unavailable, say pagination is unverified and do not claim a
  two-page result.
- Before any save, export, evidence capture, person-page update, project-file
  note, or other cross-file write, show an exact preview: every destination path
  and the complete new bytes or patch. Obtain explicit confirmation from the
  human user for each cross-file write (or for an explicitly enumerated group of
  writes). Recommendations are not human decisions or authority.
- After confirmation, read back every destination and compare it with the
  confirmed preview. If a tool, export, render, write, or read-back fails,
  surface the exact failure, preserve existing bytes, and do not claim the
  resume or profile was saved. List any partial confirmed writes and offer a new
  preview to resume; never retry or overwrite a conflict silently.

---

## Quality Checks

Before finalizing resume and LinkedIn profile, verify:

### Resume
- [ ] Every metric is supported by a named source or visibly labelled as a user-supplied estimate
- [ ] Action verbs used consistently (varied, not repetitive)
- [ ] No vague statements ("helped with", "assisted", "worked on", "responsible for")
- [ ] Most recent roles have more detail than older roles
- [ ] Format is ATS-friendly (standard headers, no graphics)
- [ ] Pagination was verified by rendering the final export; if it was not rendered, say pagination is unverified
- [ ] Dates are consistent format throughout
- [ ] No typos or grammatical errors
- [ ] Professional tone throughout

### LinkedIn Profile
- [ ] Headline fits the current cited platform limit, or the limit is labelled Unknown
- [ ] About section is first-person, conversational, compelling
- [ ] Experience descriptions more detailed than resume (appropriate for platform)
- [ ] Keywords included for target roles (SEO optimized)
- [ ] Skills follow the user's confirmed target-role priorities without an assumed ranking threshold
- [ ] Tone is professional but personable
- [ ] Call to action included (connect, reach out, etc.)

---

## When to Use This Command

**Use `/resume-builder` when:**
- Creating or updating a resume from scratch
- Need help articulating achievements with metrics
- Building a LinkedIn profile or refreshing existing one
- Preparing for job search or promotion discussions
- Want structured interview to extract your experience

**Don't use it for:**
- Quick resume tweaks (just ask normally: "update my resume with X")
- If you already have polished resume copy (just save it directly)
- Non-career profile building (this is specifically for resumes/LinkedIn)

---

## Tips for Effectiveness

### For the User

**Before starting:**
- Gather any performance reviews or feedback that mention achievements
- Check if you have career evidence already captured in Dex
- Think about your target role (influences how you position achievements)
- Have job descriptions handy if tailoring for specific opportunities

**During the session:**
- Don't rush — take time to remember specific metrics
- If you provide an estimate, label it as a user-supplied estimate and keep it distinct from verified results
- Share the context, not just the achievement
- Mention teammates, stakeholders, and collaborators

**After completion:**
- Get feedback from trusted colleagues or mentors
- Tailor the resume for each significant application
- Keep the LinkedIn profile updated as you progress
- Come back to update as you accomplish new things

### For Dex

**Be persistent:**
- Don't accept "I improved things" without a concrete outcome; do not invent a metric when none is available
- Push for scope (team size, budget, timeline, scale)
- Ask "compared to what?" to establish baseline

**Be a quality filter:**
- Weak bullet: "Managed the project team"
- Evidence-bounded bullet: "[Leadership action] with [confirmed team scope] delivered [supported outcome] by [confirmed date] ([source id], [source date]); [user-confirmed metric] or Unknown"

**Connect the dots:**
- Link achievements to career ladder competencies
- Reference existing career evidence when available
- Note patterns (user is strongest in X type of work)

**Save strategically:**
- Resume to `05-Areas/Career/Resume/`
- LinkedIn to `05-Areas/Career/Resume/`
- Achievement evidence to `05-Areas/Career/Evidence/Achievements/`

---

## Output Locations

**Resume:**
`05-Areas/Career/Resume/YYYY-MM-DD - Resume.md`

**LinkedIn Profile:**
`05-Areas/Career/Resume/YYYY-MM-DD - LinkedIn Profile.md`

**Career Evidence (if captured):**
`05-Areas/Career/Evidence/Achievements/YYYY-MM-DD - [Achievement Name].md`

---

## Example Session Flow

**User:** `/resume-builder I need to update my resume for senior PM roles`

**Dex:**

```markdown
## Resume & LinkedIn Profile Builder

**Welcome!** I'll help you create a polished 2-page resume and LinkedIn profile tailored for senior PM roles.

[... explains process ...]

Do you want to:
- **Option A**: Upload an existing resume PDF to improve  
- **Option B**: Start from scratch

Which would you prefer?
```

**User:** "Start from scratch"

**Dex:**

```markdown
## Your Professional Roles

Let's start by listing all the positions you want to include.

For each role, tell me:
- Job title
- Company name
- Employment dates
- Brief description

When you've listed all your roles, type "DONE WITH ROLES"
```

**User:** [Lists 4 roles]

**Dex:** [Confirms roles, moves to achievement extraction]

```markdown
## Role: [Confirmed Job Title] at [Confirmed Company]

**Dates:** Jan 2020 — Present

Now let's extract your specific achievements and measurable impact.

What were your major accomplishments in this role?
```

[Conversation continues through all phases...]

---

**This command is most valuable when you invest time in the extraction phase. The better the details you provide, the stronger your resume will be.**

---

## Track Usage (Silent)

"Silent" does not bypass the mutation boundary: include the exact
`System/usage_log.md` patch in the preview, honor analytics opt-in, obtain human
confirmation, read it back, and surface any failure before claiming it was updated.

**Analytics (Silent):**

Call `track_event` with event_name `resume_builder_used` and properties:
- `roles_added`
- `achievements_count`

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".
