---
name: industry-truths
description: Define time-horizoned assumptions about your industry/domain that ground strategic thinking and prevent building on quicksand
context: fork
---

## Purpose

In rapidly changing industries (especially AI/tech), strategic decisions require grounding in **what you believe to be true** at different time horizons. This skill helps you define, document, and maintain those assumptions so every ideation session and strategic conversation carries that context.

## The Problem

When everything's shifting fast, it's easy to:
- Make bets that won't age well
- Forget key assumptions when ideating
- Build on quicksand instead of informed beliefs
- Lose track of what you believed vs. what actually happened

**The solution:** A structured file of industry truths across three time horizons (Today, 6 months, 12 months) that travels with your AI context.

## Usage

- `/industry-truths` — Create or update your Industry Truths file
- `/industry-truths review` — Review current truths and update based on new data
- `/industry-truths validate` — Compare your truths against what actually happened

---

## Interview Flow

This is an **interactive conversation**, not a form. The goal is to tease out deeply held beliefs through questions, not just capture bullet points.

### Opening Context

Start by explaining the concept:

> **Building on quicksand is expensive.**  
>  
> In fast-moving industries, strategic decisions need grounding in what you believe to be true at different time horizons. This skill helps you define those assumptions so they travel with every strategic conversation.  
>  
> We'll explore three horizons:  
> 1. **Today** — What you believe is true right now  
> 2. **6 months** — Emerging certainties  
> 3. **12 months** — Strategic bets  
>  
> Plus: who you track for signals (your "inferred truths" sources).  
>  
> This takes about 15 minutes. Ready to start?

### Section 1: Your Domain

**Ask:** What's your industry or domain? (e.g., "B2B SaaS," "Product Management," "AI/ML tooling," "Enterprise Sales")

**Why:** Context for the rest of the questions. Truths about AI tooling differ from truths about enterprise sales.

### Section 2: Today's Truths

**Prompt:** Let's start with what you believe is true **today**. Not conventional wisdom—your genuine beliefs based on what you're seeing.

**Guiding questions (ask 2-3, don't interrogate):**
- What's changing faster than most people realize?
- What conventional wisdom is becoming outdated?
- What's the new moat/advantage in your space?
- What cost structure is shifting?
- What's the new bottleneck/constraint?

**Capture:** 3-5 clear statements with brief reasoning

**Example output format:**
- **Cost of intelligence → zero** — Open source models (Llama, DeepSeek) approaching frontier quality, forcing frontier labs into enterprise plays
- **Distribution is the only moat** — Technical differentiation window shrinking to weeks

### Section 3: Six Months Out

**Prompt:** Now let's think **six months out**. What do you believe will be true by [specific month 6 months from now]? These are emerging certainties—things you're reasonably confident about.

**Guiding questions:**
- What complexity will be solved by then?
- What ideas that are too expensive/hard today will become viable?
- What adoption curve will cross a threshold?
- What will enterprise buyers expect as table stakes?

**Capture:** 3-5 emerging certainties with implications

**Example:**
- **Agent orchestration complexity solved** — When this happens, individual developers can out-compete established players
- **Token-expensive ideas become viable** — Local/mobile inference reaches production quality

### Section 4: Twelve Months Out

**Prompt:** Finally, **12 months out**—your strategic bets. What do you believe will be true a year from now? These might be wrong, but they're shaping your decisions today.

**Guiding questions:**
- What category will dominate?
- What pricing model will be default?
- What team structure becomes normal?
- What assumptions break completely?

**Capture:** 3-5 strategic bets with reasoning

**Example:**
- **Vertical AI agents dominate horizontal tools** — Generic productivity loses to specialized, context-aware agents
- **Seat-based pricing dies** — Usage/outcome-based becomes default

### Section 5: Anti-Truths (Optional but Powerful)

**Prompt:** What did you used to believe that you now think is wrong? Capturing these helps track your evolving thinking.

**Capture:** 2-3 rejected beliefs with brief explanation

**Example:**
- ~~"AI is a feature, not a product"~~ → Dead wrong. AI enables entirely new product categories.

---

## File Creation

After the interview, create `04-Projects/Product_Strategy/Industry_Truths.md` (or update if it exists):

```markdown
---
created: [today's date]
updated: [today's date]
domain: [user's domain]
tags: [strategy, assumptions, industry-truths]
---

# Industry Truths — [Domain]

A living document of what I believe to be true about [domain] at different time horizons. These ground all strategic thinking, ideation, and investment decisions.

**Purpose:** In a world where we're building on quicksand, this file ensures I'm not forgetting key assumptions when ideating. These truths travel with the AI so we're always thinking within this context.

---

## Today (Current Reality)

[User's "today" truths with brief reasoning for each]

---

## 6 Months Out (Emerging Certainties)

[User's 6-month truths with implications]

---

## 12 Months Out (Strategic Bets)

[User's 12-month truths with reasoning]

---

## Anti-Truths (What I Used to Believe, Now Reject)

[User's rejected beliefs with brief explanation]

---

## How I Use This

1. **Before Ideation:** Review truths relevant to the problem space
2. **During Roadmapping:** Validate assumptions against time horizons
3. **Monthly Review:** Update based on new data, move items between horizons
4. **Share with AI:** Include in context for strategic conversations

---

## Change Log

### [Today's date]
- Initial version created via /industry-truths skill
```

---

## Completion

After creating the file, tell the user:

> ✅ **Created Industry_Truths.md**  
>  
> Dex is already configured to reference this file during strategic conversations (product decisions, roadmap planning, ideation sessions). Your truths will automatically inform future strategic thinking.  
>  
> **Next steps:**  
> - Review the file and refine as needed  
> - Set a monthly reminder to update it (new data, move items between horizons)  
> - Use it before strategic conversations: "Let's ideate within my industry truths"  
> - Track validation: what was right, what was wrong, why?  
>  
> Run `/industry-truths review` to update or `/industry-truths validate` to check past predictions.

---

## Review Mode (`/industry-truths review`)

If user runs `/industry-truths review`:

1. Read current `Industry_Truths.md`
2. Check dates in change log (when last updated?)
3. Ask: "What's changed since you last updated this? New data? Assumptions proven/disproven?"
4. Offer to update specific sections or add to change log
5. Highlight any truths where time horizon has passed (e.g., 6-month truth from 6 months ago—was it right?)

---

## Validate Mode (`/industry-truths validate`)

If user runs `/industry-truths validate`:

1. Read change log and time horizons
2. For each past-due truth (e.g., 6-month truth from >6 months ago):
   - Ask: "Did this happen?"
   - Capture: Right / Wrong / Partially / Too Early
3. Add validation notes to change log
4. Suggest: "Want to archive validated truths and set new ones?"

**Why this matters:** Tracking accuracy trains your intuition about what bets to trust.

---

## Meta Notes

**This skill is:**
- A thought leadership artifact that ships as working software
- Immediately actionable for Dex users
- Demonstrates Dex's value as context-carrying personal OS
- Creates compound value (truths improve every strategic conversation)

**Encourage sharing:** "Built my industry truths with Dex" is shareable social content
