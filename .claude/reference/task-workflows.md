# Task Workflows

## Task Creation (Smart Pillar Inference)

When the user requests task creation without specifying a pillar:
- "Create a task to review Q1 numbers"
- "Remind me to prep for Sarah's demo"
- "Add task: write LinkedIn post about feature launch"

**Your workflow:**
1. **Analyze the request** against pillar keywords (from `System/pillars.yaml`)
2. **Infer the most likely pillar** based on content:
   - **Deal Support**: deal, sales, customer, demo, presentation, enablement, account, pipeline, prospect, opportunity
   - **Thought Leadership**: podcast, conference, linkedin, content, blog, talk, speaking, brand, article, webinar
   - **Product Feedback**: product, feedback, feature, roadmap, ux, research, insight, customer voice, beta
3. **Propose with quick confirmation**:
   ```
   Creating "Review Q1 numbers" under Product Feedback pillar (looks like data gathering).
   Sound right, or should it be Deal Support / Thought Leadership?
   ```
4. **Handle response**:
   - User confirms (yes/sounds good/correct) → Create task with inferred pillar
   - User specifies different pillar → Use their choice
   - Unclear task → Ask which pillar makes most sense
5. **Call Work MCP**: `work_mcp_create_task` with confirmed pillar

**Inference examples:**
- "Prep demo for Acme Corp" → **Deal Support** (customer + demo keywords)
- "Write blog post about AI agents" → **Thought Leadership** (content + article keywords)
- "Review beta feedback on search" → **Product Feedback** (feedback + beta keywords)
- "Call prospect about pricing" → **Deal Support** (prospect keyword)

**Key points:**
- Always show your reasoning ("looks like X because Y")
- Make correction easy - list alternatives in the confirmation
- If genuinely ambiguous, ask rather than guess
- Default to user's pillar choice if they override

## Task Completion (Natural Language)

When the user says they completed a task (any phrasing):
- "I finished X", "Mark Y as done", "Completed Z", "Done with the meeting prep"

**Your workflow:**
1. Search `03-Tasks/Work_Tasks.md` and `03-Tasks/Personal_Tasks.md` for tasks matching the description. Use the `query` tool (QMD MCP) to catch semantic matches like "I finished the pricing thing" matching task "Finalize Q1 pricing proposal." Fall back to keyword/context matching if QMD is unavailable.
2. Find the task and extract its task ID (format: `^task-YYYYMMDD-XXX`)
3. Call Work MCP: `update_task_status(task_id="task-20260128-001", status="d")`
4. The MCP automatically updates the task everywhere:
   - `03-Tasks/Work_Tasks.md` and `03-Tasks/Personal_Tasks.md`
   - Meeting notes where it originated
   - Person pages (Related Tasks sections)
   - Project/company pages
   - Adds completion timestamp (e.g., `✅ 2026-01-28 14:35`)
5. Confirm to user: "Done! Marked complete in [list locations] at [timestamp]"

**Key points:**
- Accept any natural phrasing - be smart about parsing intent
- If multiple tasks match, ask for clarification
- If no task ID exists (legacy task), update the source file only and note that future tasks will sync everywhere
- Don't require exact task title - use fuzzy matching on keywords
