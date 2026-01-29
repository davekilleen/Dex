---
name: prompt-improver
description: Transform vague prompts into rich, structured prompts using Anthropic Messages API
---

## Purpose

Transform vague, ambiguous prompts into rich, well-structured prompts using the **Anthropic Messages API**. This skill makes a meta API call to Claude specifically designed to improve prompt quality, then silently injects the enhanced prompt back into the conversation.

**How it works:**
1. User provides a vague prompt (e.g., "critique this doc")
2. Skill calls Anthropic Messages API with prompt engineering expertise
3. API returns a far better, richer, more structured prompt
4. Skill executes the improved prompt and returns results
5. User sees the answer **without seeing the improved prompt** (unless flags are set)

**Why this matters:**
- Turns casual requests into expert-level prompts
- Applies Anthropic's prompt engineering best practices automatically
- No mental overhead - just ask naturally and get better results

---

## Arguments

**$PROMPT** - The prompt to improve (required)
**$FEEDBACK** - Optional feedback on what to improve (e.g., "Make it more detailed", "Add examples", "Focus on clarity")

---

## Qualifiers

Check if $PROMPT starts with a flag:

| Flag | Behavior |
|------|----------|
| `-p` | **Prompt only** - Show the improved prompt, don't execute |
| `-v` | **Verbose** - Show the improved prompt, then execute |
| (none) | **Quick** - Execute immediately without showing full prompt |

Strip the flag from $PROMPT before processing.

---

## Process

### Step 1: Parse Flags and Extract Prompt

Check if $PROMPT starts with a flag (`-p`, `-v`) and extract:
- **mode**: `prompt-only`, `verbose`, or `quick` (default)
- **original_prompt**: The actual prompt text (flag removed)
- **feedback**: Optional improvement guidance from $FEEDBACK

### Step 2: Call Anthropic Messages API to Improve Prompt

**API Call Configuration:**
- **Endpoint**: Anthropic Messages API
- **Model**: `claude-3-5-sonnet-20241022` (optimized for prompt engineering)
- **System Prompt**: Prompt engineering expert persona (see below)
- **User Message**: The original vague prompt
- **Temperature**: 0.3 (balanced creativity for prompt improvement)

**System Prompt Template:**
```
You are an expert prompt engineer trained in Anthropic's best practices. Your job is to transform vague, ambiguous prompts into clear, structured, effective prompts.

Analyze the user's prompt and improve it using these techniques:

1. **Structure**: Add clear sections with XML tags or markdown headers
2. **Clarity**: Be specific about format, length, and success criteria
3. **Context**: Include necessary background and define ambiguous terms
4. **Examples**: Add few-shot examples when helpful
5. **Chain of Thought**: For complex tasks, request step-by-step reasoning
6. **Constraints**: Make implicit constraints explicit

Return ONLY the improved prompt. Do not explain your changes or add meta-commentary.

{if $FEEDBACK exists: "Focus on: {$FEEDBACK}"}
```

**API Response:**
- Extract the improved prompt from the API response
- This becomes the **enhanced_prompt**

### Step 3: Handle Based on Mode

**Mode: `prompt-only` (flag: `-p`):**
1. Show: `> **Original:** [original_prompt]`
2. Show the **enhanced_prompt** in a code block
3. Stop. Do NOT execute. User can review and manually run if desired.

**Mode: `verbose` (flag: `-v`):**
1. Show: `> **Original:** [original_prompt]`
2. Show the **enhanced_prompt** in a collapsible block:
   ```html
   <details>
   <summary>📝 Improved Prompt (click to expand)</summary>
   
   [enhanced_prompt from API]
   
   </details>
   ```
3. Add `---` separator
4. **Execute the enhanced_prompt** and return results

**Mode: `quick` (no flag - DEFAULT):**
1. Silently execute the **enhanced_prompt**
2. Return results directly to user
3. **Do NOT show the improved prompt** - user just sees the answer

This is the magic mode: user asks casually, gets expert-level results, never sees the prompt engineering machinery.

---

## Examples

```
/prompt-improver -p critique this strategy doc
→ Shows improved prompt only, doesn't execute

/prompt-improver -v critique this strategy doc  
→ Shows improved prompt, then executes it

/prompt-improver critique this strategy doc
→ Just executes the improved prompt
```

---

## API Implementation Details

**Requirements:**
- Anthropic API key set in `.env` file (see `env.example`)
- Network access to Anthropic Messages API

**Fallback Behavior:**
If Anthropic API key is not configured:
- Skill automatically falls back to inline prompt improvement (current Claude session improves the prompt)
- Notify user: `"💡 Using inline improvement (Anthropic API key not configured). For best results, add ANTHROPIC_API_KEY to .env"`
- Continue with process using inline improvement instead of API call

**Error Handling:**
- API rate limits → Retry with exponential backoff
- API errors → Fall back to inline improvement
- Network issues → Fall back to inline improvement

---

## Improvement Template Reference

The Anthropic Messages API call transforms prompts using this general structure:

```markdown
# Task
[Clear statement of what to do]

# Context
[Background information needed]

# Instructions
1. [Step 1]
2. [Step 2]
3. [Step 3]

# Constraints
- [Constraint 1]
- [Constraint 2]

# Output Format
[Expected format and structure]

# Examples (if helpful)
[Input/output examples]
```

The API applies this structure intelligently based on the specific prompt needs.

---

## Philosophy

**Meta-prompting:** This skill uses Claude to improve prompts for Claude. It's prompt engineering as a service.

**Invisible by default:** The best tools disappear. Users ask naturally, get expert results, never see the complexity.

**Progressive disclosure:** Flags (`-v`, `-p`) let power users inspect and learn from the improvements.
