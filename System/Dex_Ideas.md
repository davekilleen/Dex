# Dex Improvement Ideas

*Last ranked: 2026-01-28 (Initial setup)*

Welcome to your PKM improvement ideas! This file tracks ideas for making Dex better.

## How It Works

1. **Capture ideas** anytime using the `capture_idea` MCP tool
2. **Review regularly** with `/review-ideas` to see AI-ranked priorities
3. **Workshop ideas** by running `/dex-improve [idea title]`
4. **Mark implemented** when you build an idea

Ideas are automatically ranked on 5 dimensions:
- **Impact** (35%) - How much would this improve daily workflow?
- **Alignment** (20%) - Fits your actual usage patterns?
- **Token Efficiency** (20%) - Reduces context/token usage?
- **Memory & Learning** (15%) - Enhances persistence, self-learning, compounding knowledge?
- **Proactivity** (10%) - Enables proactive concierge behavior?

*Effort intentionally excluded - with AI coding, implementation is cheap. Focus on value.*

---

## Priority Queue

<!-- Auto-ranked by /review-ideas command -->

### 🔥 High Priority (Score: 85+)

- **[idea-001]** Meeting context cache with smart summaries
  - **Score:** 92 (Impact: 95, Alignment: 85, Token: 95, Memory: 90, Proactive: 85)
  - **Category:** knowledge
  - **Captured:** 2026-01-28
  - **Why ranked here:** Huge token savings + builds persistent memory. Currently re-reading full meeting notes every time. Cache would store structured summaries, enabling faster recall and pattern recognition across meetings.
  - **Description:** Create cached summaries of meetings stored in structured format (decisions, action items, key points). When preparing for follow-up meetings, use cache instead of re-reading full notes. Reduces token usage by 70-80% while building persistent knowledge graph of meeting history.

- **[idea-002]** Learning pattern synthesizer with auto-recommendations
  - **Score:** 89 (Impact: 90, Alignment: 80, Token: 75, Memory: 95, Proactive: 90)
  - **Category:** knowledge
  - **Captured:** 2026-01-28
  - **Why ranked here:** Pure system learning + proactive behavior. Analyzes session learnings to detect patterns, then proactively suggests improvements before you ask. System gets smarter over time, compounds knowledge.
  - **Description:** Background process that analyzes `System/Session_Learnings/` to identify recurring patterns (same mistakes, common workflows, repeated pain points). Builds a learning model that proactively surfaces relevant past learnings during relevant contexts. Example: If you're editing a command, it shows "Last time you worked on commands, you learned X."

### ⚡ Medium Priority (Score: 60-84)

- **[idea-003]** Preference learning from edit patterns
  - **Score:** 82 (Impact: 80, Alignment: 85, Token: 70, Memory: 90, Proactive: 75)
  - **Category:** automation
  - **Captured:** 2026-01-28
  - **Why ranked here:** Strong memory + proactive component. System learns your editing style, formatting preferences, and common patterns from your changes, then applies them automatically.
  - **Description:** Track file edits over time to learn preferences: formatting style, common sections you add, typical structures. Store as preference model. When creating new files or suggesting edits, apply learned preferences automatically. Reduces back-and-forth corrections.

- **[idea-004]** Structured data extraction for faster retrieval
  - **Score:** 78 (Impact: 75, Alignment: 80, Token: 90, Memory: 70, Proactive: 65)
  - **Category:** system
  - **Captured:** 2026-01-28
  - **Why ranked here:** Massive token efficiency gains. Convert verbose markdown to structured data (JSON/YAML) for frequently accessed info. Example: Person pages → structured records, enabling O(1) lookup instead of full file reads.
  - **Description:** Create structured indexes for high-frequency data: person pages, project metadata, task status. Store in lightweight format (YAML/JSON). Use for quick lookups, fall back to full markdown when needed. Estimated 60% token reduction for common operations.

### 💡 Low Priority (Score: <60)

- **[idea-005]** Export weekly summaries to blog
  - **Score:** 48 (Impact: 55, Alignment: 40, Token: 45, Memory: 50, Proactive: 40)
  - **Category:** knowledge
  - **Captured:** 2026-01-28
  - **Why ranked here:** Doesn't optimize core dimensions. Increases token usage (formatting), no learning component, not proactive. Nice to have but low strategic value.
  - **Description:** Create a command to export weekly reviews as formatted blog posts. Would help with public learning and knowledge sharing. Better to tackle after establishing consistent weekly review habit and after higher-value ideas are implemented.

---

## Archive (Implemented)

*Implemented ideas will appear here with completion dates.*

---

*Run `/review-ideas` to re-rank ideas based on current system state.*
