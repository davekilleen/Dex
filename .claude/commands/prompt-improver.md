# Prompt Improver

Improve prompts using Anthropic's prompt engineering best practices.

## Arguments

$PROMPT: The prompt to improve (required)
$FEEDBACK: Optional feedback on what to improve (e.g., "Make it more detailed", "Add examples", "Focus on clarity")

## Qualifiers

Check if $PROMPT starts with a flag:

| Flag | Behavior |
|------|----------|
| `-p` | **Prompt only** - Show the improved prompt, don't execute |
| `-v` | **Verbose** - Show the improved prompt, then execute |
| (none) | **Quick** - Execute immediately without showing full prompt |

Strip the flag from $PROMPT before processing.

## Process

### 1. Analyze the Original Prompt

Identify:
- What the prompt is trying to accomplish
- Missing context or constraints
- Ambiguous instructions
- Opportunities for structure

### 2. Apply Improvement Techniques

Use these prompt engineering best practices:

**Structure:**
- Add clear sections with XML tags or markdown headers
- Separate instructions from examples
- Put important constraints at the beginning and end

**Clarity:**
- Be specific about format and length expectations
- Define any ambiguous terms
- Add explicit success criteria

**Context:**
- Include relevant background information
- Specify the intended audience
- Clarify the use case

**Examples:**
- Add few-shot examples if helpful
- Show both good and bad outputs when relevant

**Chain of Thought:**
- For complex tasks, ask for step-by-step reasoning
- Use "Let's think through this..." prefixes

### 3. Handle Based on Qualifier

**If `-p` (prompt only):**
- Show: `> **Original:** [original prompt]`
- Show the full improved prompt in a code block
- Stop. Do NOT execute.

**If `-v` (verbose):**
- Show: `> **Original:** [original prompt]`
- Show the full improved prompt in a collapsible block:
```
<details>
<summary>📝 Improved Prompt (click to expand)</summary>

[full improved prompt]

</details>
```
- Add `---` separator
- Execute the improved prompt

**If no flag (quick mode):**
- Execute the improved prompt immediately
- No need to display it

## Examples

```
/prompt-improver -p critique this strategy doc
→ Shows improved prompt only, doesn't execute

/prompt-improver -v critique this strategy doc  
→ Shows improved prompt, then executes it

/prompt-improver critique this strategy doc
→ Just executes the improved prompt
```

## Improvement Template

When improving a prompt, consider this structure:

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

## Philosophy

Good prompts are clear, specific, and structured. The goal is to reduce ambiguity and help the model understand exactly what you want.
