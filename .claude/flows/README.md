# Flows

**Purpose:** Multi-step interactive workflows that guide users through complex processes requiring decisions and input.

---

## What Are Flows?

**Flows** are guided setup wizards that walk you through complex processes step by step. They ask questions, adapt based on your answers, and configure your system automatically. Think of them like having someone guide you through setup rather than figuring it out alone.

### How Flows Work

**Example: Onboarding a New User**

```
1. Welcome message
2. Q: "What's your role?"
   → User selects "Product Manager"
3. Q: "Company size?"
   → User selects "50-200"
4. Q: "Enable quarterly planning?"
   → User selects "Yes"
5. [Flow creates PM-specific folders]
6. [Flow generates strategic pillars]
7. [Flow sets up templates]
8. "Setup complete! Run /daily-plan to start."
```

### Key Characteristics

**Sequential:** Each step builds on the previous one
**Interactive:** Pauses for user input at decision points
**Branching:** Different paths based on user choices
**One-time:** Typically for setup or configuration (not daily use)

### Flows vs Skills vs Agents

| Aspect | Flows | Skills | Agents |
|--------|-------|--------|--------|
| **Interaction** | Multi-step wizard with branching | Single invocation | Autonomous (no user input) |
| **Frequency** | One-time or rare | Repeatable daily/weekly | As needed |
| **Purpose** | Setup and configuration | Execute workflows | Background analysis |
| **Example** | Onboarding wizard | `/daily-plan` | `project-health` scan |
| **User input** | Multiple questions throughout | Optional at start | None during execution |

### When to Use Each

**Use a Flow when:**
- ✅ Setting up system for the first time
- ✅ Configuring a complex feature with multiple options
- ✅ Guiding unfamiliar users through a process
- ✅ Decisions affect what happens next (branching)

**Use a Skill when:**
- ✅ Repeatable daily/weekly command
- ✅ Linear workflow without complex branching
- ✅ User explicitly invokes with `/command`

**Use an Agent when:**
- ✅ Autonomous background work
- ✅ No user interaction needed
- ✅ Multi-step analysis returning a summary

---

## What Goes Here

Flow definition files (`.md` format) that:
- Guide users through multi-step processes
- Require user decisions at key points
- Create or configure system components
- Onboard new users or features

## When to Use

Create a flow when:
- **Sequential steps** - Process has a clear progression with dependencies
- **User input required** - Decisions or information needed at each step
- **One-time setup** - Configuring system components or integrations
- **Teaching moment** - Explaining concepts while building

Don't use flows for:
- Autonomous tasks (use agents instead)
- Simple single-step operations (use skills)
- Routine daily operations (use skills)

## Structure

Flows typically include:
- Clear step-by-step instructions
- Decision points and branching logic
- Validation of prerequisites
- File creation or configuration
- Confirmation of success

## Examples

- **onboarding.md** - First-time Dex setup (creates folders, configures pillars, sets preferences)
- Future: Integration setup flows, feature enablement guides

## Related

- **Skills** (`.claude/skills/`) - Simple user commands
- **Agents** - Autonomous multi-step tasks (invoked via Task tool)
