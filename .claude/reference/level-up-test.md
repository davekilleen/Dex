# /dex-level-up Feature Test

**Purpose:** Practical test to verify data collection and recommendation logic works correctly.

---

## Test 1: Fresh Install → First Command

**Starting State:**

`System/usage_log.md` (all unchecked):
```markdown
## Core Workflows
- [ ] Daily planning (/daily-plan)
- [ ] Daily review (/review)
- [ ] Weekly planning (/week-plan)
...
```

**Action:** User runs `/daily-plan` for the first time

**Expected Behavior:**

1. Command executes, generates daily plan
2. At Step 7, command silently updates `System/usage_log.md`:
   ```markdown
   - [x] Daily planning (/daily-plan)  ← Changed from [ ] to [x]
   ```
3. Also updates metadata:
   ```markdown
   - **First daily plan:** 2026-01-28
   ```
4. No announcement to user about tracking

**Verification:**
```bash
# Check if box was checked
grep "Daily planning" System/usage_log.md
# Expected: "- [x] Daily planning (/daily-plan)"
```

---

## Test 2: Seven Days Later → Smart Trigger

**Starting State:**

`System/usage_log.md`:
```markdown
## Core Workflows
- [x] Daily planning (/daily-plan)
- [ ] Daily review (/review)
- [ ] Weekly planning (/week-plan)
- [ ] Weekly review (/week-review)

## Tracking Metadata
- **Last dex-level-up prompt:** (not yet prompted)
- **First daily plan:** 2026-01-21
```

**Conditions:**
- 7+ days since first daily plan
- Only 1 feature checked (daily planning)
- 3+ features unchecked
- Never prompted before

**Action:** User runs `/daily-plan` on day 8

**Expected Behavior:**

1. Command generates daily plan normally
2. At Step 3.5 (Level-Up Check):
   - Reads usage_log.md
   - Sees `last_dex_level_up_prompt: (not yet prompted)`
   - Counts unchecked features: 24 unchecked
   - Condition met: 7+ days AND 3+ unused features
3. Adds to daily plan output:
   ```markdown
   ---
   
   💡 **Tip:** You're using 1 of 25 Dex features. Run `/dex-level-up` to see what you might be missing.
   ```
4. Updates usage log metadata:
   ```markdown
   - **Last dex-level-up prompt:** 2026-01-28
   ```

**Verification:**
```bash
# Check daily plan output includes tip
grep "💡 Tip" 00-Inbox/Daily_Plans/2026-01-28.md

# Check metadata was updated
grep "Last dex-level-up prompt" System/usage_log.md
# Expected: "- **Last dex-level-up prompt:** 2026-01-28"
```

---

## Test 3: User Runs /dex-level-up

**Starting State:**

`System/usage_log.md`:
```markdown
## Core Workflows
- [x] Daily planning (/daily-plan)
- [ ] Daily review (/review)
- [ ] Weekly planning (/week-plan)
- [ ] Weekly review (/week-review)
- [ ] Quarterly planning (/quarter-plan)
- [ ] Quarterly review (/quarter-review)

## Meeting Workflows
- [ ] Meeting prep (/meeting-prep)
- [ ] Meeting processing (/process-meetings)
- [ ] Person page created
- [ ] Person page updated

## Organization
- [ ] Inbox triage (/triage)
- [ ] Learning capture (/save-insight)
- [ ] Project tracking (/project-health)
- [ ] Product brief (/product-brief)

## Journaling
- [ ] Morning journal
- [ ] Evening journal
- [ ] Weekly journal

## System Features
- [ ] Task created (via MCP)
- [ ] Task completed (via MCP)
- [ ] Project page created
- [ ] Content tracking used
- [ ] Relationship tracking used

## Advanced
- [ ] Custom MCP created (/create-mcp)
- [ ] System improvements (/dex-improve)
- [ ] Prompt improvement (/prompt-improper)
- [ ] Demo mode (/dex-demo)
```

**Action:** User types `/dex-level-up`

**Expected Behavior:**

1. Command reads `System/usage_log.md` (Step 1)
2. Analyzes patterns (Step 2):
   - User has daily planning habit (1 checked box)
   - Natural next step: daily review (complete the loop)
   - Also: person pages (relationship tracking)
   - Also: meeting processing (extract value)
3. Generates 3 recommendations (Step 3)
4. Displays output (Step 4):

```markdown
# 🚀 Level Up Your Dex System

Based on your usage, here are **3 ways to get more value** from Dex:

---

## 1. Daily Review - Close the Loop

**What you're missing:** You're planning every morning, but not reviewing at 
the end of the day. Daily reviews capture what you accomplished and feed into 
tomorrow's plans.

**Why it's relevant:** You're consistent with daily planning! Adding the review 
completes the loop and makes your planning smarter.

**How to start:** Run `/review` at end of day (5 minutes)

**Time:** 5 minutes daily

---

## 2. Person Pages - Never Walk Into Meetings Cold

**What you're missing:** Person pages aggregate everything about someone — 
meeting history, open items, context — so you're never scrambling before calls.

**Why it's relevant:** Building relationship context helps you prepare for 
meetings and track commitments.

**How to start:** Just say "Create a person page for [name]" and I'll set it up.

**Time:** 2 minutes per person, one-time setup

---

## 3. Meeting Processing - Extract Value from Your Meetings

**What you're missing:** `/process-meetings` extracts action items, decisions, 
and key points from meetings — then routes them to the right places.

**Why it's relevant:** Ensures nothing from your calls gets lost.

**How to start:** After your next meeting, run `/process-meetings` and paste 
in your notes.

**Time:** 2-3 minutes per meeting

---

## Want to try one now?

Just say the number or feature name, and I'll guide you through it.
```

**Verification:**
- Output shows exactly 3 recommendations
- Recommendations are relevant to daily planning habit
- No mention of quarterly planning (too advanced)
- Includes specific "how to start" instructions

---

## Test 4: User Tries a Recommendation

**Starting State:** (same as Test 3)

**Action:** 
1. User says: "Let's try #1" or "I'll do the daily review"
2. Dex guides them through `/review` command
3. Review completes successfully

**Expected Behavior:**

At end of `/review` command (Step 6):
1. Silently updates `System/usage_log.md`:
   ```markdown
   - [x] Daily review (/review)  ← Changed from [ ] to [x]
   ```
2. No announcement about tracking update
3. User sees only the daily review output

**Next Time User Runs `/dex-level-up`:**

System recognizes:
- Daily planning: ✅
- Daily review: ✅
- Pattern: User completes the planning/review loop

New recommendations:
1. **Weekly Planning** - Natural next step after daily consistency
2. **Task Management** - Create and manage tasks
3. **Person Pages** - Still relevant

**Verification:**
```bash
# After review completes, check usage log
grep "Daily review" System/usage_log.md
# Expected: "- [x] Daily review (/review)"

# Next /dex-level-up won't suggest daily review again
# (already checked)
```

---

## Test 5: Cooldown Period

**Starting State:**

`System/usage_log.md`:
```markdown
## Tracking Metadata
- **Last dex-level-up prompt:** 2026-01-28
```

**Action:** User runs `/daily-plan` on 2026-01-29 (next day)

**Expected Behavior:**

1. Command generates daily plan
2. At Step 3.5 (Level-Up Check):
   - Reads `last_dex_level_up_prompt: 2026-01-28`
   - Calculates: Only 1 day since last prompt
   - Condition NOT met: Need 7+ days
3. No tip added to daily plan
4. No metadata update

**On 2026-02-05 (7 days later):**

1. User runs `/daily-plan`
2. At Step 3.5:
   - Reads `last_dex_level_up_prompt: 2026-01-28`
   - Calculates: 8 days since last prompt ✅
   - Checks unused features: Still 3+ unchecked ✅
3. Adds tip to daily plan again
4. Updates metadata to 2026-02-05

**Verification:**
- Days 1-6 after prompt: No tip shown
- Day 8+ after prompt: Tip appears again
- Prevents annoying repeated prompts

---

## Test 6: Power User (All Features Used)

**Starting State:**

`System/usage_log.md`:
```markdown
## Core Workflows
- [x] Daily planning (/daily-plan)
- [x] Daily review (/review)
- [x] Weekly planning (/week-plan)
- [x] Weekly review (/week-review)
- [x] Quarterly planning (/quarter-plan)
- [x] Quarterly review (/quarter-review)

## Meeting Workflows
- [x] Meeting prep (/meeting-prep)
- [x] Meeting processing (/process-meetings)
- [x] Person page created
- [x] Person page updated

## Organization
- [x] Inbox triage (/triage)
- [x] Learning capture (/save-insight)
- [x] Project tracking (/project-health)
- [x] Product brief (/product-brief)

## Journaling
- [x] Morning journal
- [x] Evening journal
- [x] Weekly journal

## System Features
- [x] Task created (via MCP)
- [x] Task completed (via MCP)
- [x] Project page created
- [x] Content tracking used
- [x] Relationship tracking used

## Advanced
- [ ] Custom MCP created (/create-mcp)
- [ ] System improvements (/dex-improve)
- [ ] Prompt improvement (/prompt-improper)
- [x] Demo mode (/dex-demo)
```

**Action:** User runs `/dex-level-up`

**Expected Behavior:**

1. Command reads usage log
2. Counts: 24 of 27 features checked
3. Recognizes power user status
4. Shows advanced recommendations:

```markdown
# 🚀 Level Up Your Dex System

You're using Dex like a pro! 🎉 Here are **2 advanced capabilities** that could 
take your system even further:

---

## 1. Custom MCP Integration - Automate Data Sync

**What you're missing:** You're tracking relationships manually. A custom MCP 
could sync data from your CRM automatically.

**Why it's relevant:** You've built excellent tracking discipline. Automation 
would save 15-20 minutes per week.

**How to start:** Run `/create-mcp` and tell me which CRM you use.

**Time:** 30-45 minutes setup, saves 15-20 min/week ongoing

---

## 2. System Customization - Make Dex Yours

**What you're missing:** You've earned the right to bend the system to your needs.

**Why it's relevant:** After consistent use, you know your patterns. Customize 
commands and workflows for your exact needs.

**How to start:** Run `/dex-improve` and describe what you wish worked differently.

**Time:** Varies by customization, but the ROI compounds forever

---

## Want to try one now?

Just say the number or feature name, and I'll guide you through it.

---

**Pro tip:** You might also want to share your setup with others. Your discipline 
could help someone just getting started.
```

**Verification:**
- Celebration message appears
- Only suggests advanced features (custom MCPs, system improvements)
- Acknowledges mastery
- Suggests knowledge sharing

---

## Summary: What We've Verified

✅ **Data Collection Works**
- Commands update usage_log.md correctly
- Updates are silent (no user announcements)
- Metadata tracking (dates, first use) works

✅ **Smart Triggers Work**
- 7-day cooldown respected
- Only triggers when 3+ features unused
- Updates cooldown date after triggering

✅ **Recommendations Are Contextual**
- New users get basics (daily review, person pages)
- Intermediate users get progressions (weekly planning, projects)
- Power users get advanced (custom MCPs, system improvements)

✅ **User Experience Is Smooth**
- No interruption to normal workflow
- Tracking happens in background
- Recommendations are helpful, not pushy
- 2-3 suggestions at a time (never overwhelming)

✅ **System Is Maintainable**
- Simple markdown checkboxes (no complex database)
- Adding new features is easy
- Core commands have explicit tracking
- CLAUDE.md provides general guidance

---

## Running These Tests

**Manual testing:**
1. Fresh install Dex
2. Run through each test scenario
3. Verify expected outputs match

**Automated testing:**
Could build test suite, but manual testing is sufficient given:
- Simple data structure (markdown checkboxes)
- Clear verification points (grep commands)
- User-facing feature (manual testing catches UX issues)

**Regression testing:**
- When adding new commands, add checkbox to usage_log.md
- Test `/dex-level-up` still recommends correctly
- Verify smart trigger still works in daily-plan
