# Pi Troubleshooting Guide

Quick fixes for common issues.

---

## "Pi command not found"

**Symptom:** Running `/pi-build` or other Pi commands returns an error or does nothing.

**Causes & Fixes:**

### 1. Beta not activated
Check your beta status:
```
/pi-status
```

If Pi isn't enabled, contact the beta coordinator to verify your activation.

### 2. Skills not loaded
Pi commands are skills that need to be in place. Check if the directory exists:
```
ls .claude/skills/pi-*
```

If missing, the Pi skill files weren't installed. Re-run the beta activation process.

### 3. Typo in command
Commands are case-sensitive and use hyphens:
- Correct: `/pi-build`
- Wrong: `/pi build`, `/Pi-build`, `/pibuild`

---

## "Can't create tasks" or task-related errors

**Symptom:** Pi builds something that should create tasks, but tasks don't appear.

**Causes & Fixes:**

### 1. Work MCP not running
The Work MCP handles task operations. Check if it's available:
- Look for task-related errors in the output
- Try a simple task operation: "Add a test task"

If the Work MCP isn't responding, restart Claude Code.

### 2. Tasks.md missing or malformed
Pi-built tools expect the standard task file. Verify it exists:
```
cat 03-Tasks/Tasks.md
```

If missing, create the standard structure or run `/daily-plan` to initialize it.

### 3. Permission issue
On some systems, file permissions can block writes:
```
ls -la 03-Tasks/
```

The Tasks.md file should be writable by your user.

---

## "Extension failed to load" or TypeScript errors

**Symptom:** Pi reports errors about TypeScript, modules, or compilation.

**Causes & Fixes:**

### 1. Node.js version mismatch
Pi requires Node.js 18+. Check your version:
```
node --version
```

If below v18, upgrade Node.js.

### 2. Missing dependencies
Some Pi-built tools need npm packages. If you see module errors:
```
cd .claude/skills/pi-custom/[skill-name]
npm install
```

### 3. Syntax error in generated code
Occasionally Pi generates code with syntax issues. Check the file:
```
cat .claude/skills/pi-custom/[skill-name]/skill.ts
```

Look for obvious issues like unclosed brackets. Report to `/pi-feedback` with the error.

---

## How to Reset Pi State

If Pi gets into a bad state, you can reset:

### Reset a single custom skill
Delete the skill directory:
```
rm -rf .claude/skills/pi-custom/[skill-name]
```

### Reset all Pi custom skills
Remove the entire custom directory:
```
rm -rf .claude/skills/pi-custom
```

Pi will recreate this directory when you build your next skill.

### Reset Pi feedback and logs
Clear Pi's logs:
```
rm -rf System/Pi
```

This removes feedback history and workflow storage. Your custom skills in `.claude/skills/pi-custom/` are preserved.

### Full reset
To completely reset Pi (skills + state):
```
rm -rf .claude/skills/pi-custom
rm -rf System/Pi
```

Then run `/pi-status` to verify Pi is ready for a fresh start.

---

## "MCP bridge not available"

**Symptom:** Pi says it can't access calendar, tasks, or other MCP features.

**Causes & Fixes:**

### 1. MCP servers not started
Some MCP servers need to be running. Check Claude Code's MCP status in settings.

### 2. Missing MCP configuration
Pi needs certain MCPs configured. Verify your MCP config includes:
- Work MCP (for tasks)
- Calendar MCP (for calendar access)

### 3. MCP timeout
If MCPs are slow to respond, Pi may give up. Retry the command:
```
/pi-build [same request]
```

---

## "Permission denied" errors

**Symptom:** Pi can't write files to certain locations.

**Causes & Fixes:**

### 1. Directory doesn't exist
Pi expects certain directories. Create them:
```
mkdir -p .claude/skills/pi-custom
mkdir -p System/Pi
```

### 2. File system permissions
Check directory permissions:
```
ls -la .claude/skills/
ls -la System/
```

Both should be writable by your user.

### 3. File is open in another application
Close any editors that have Pi files open, then retry.

---

## Pi built something but it doesn't work

**Symptom:** The skill was created but doesn't do what you wanted.

**Causes & Fixes:**

### 1. Clarify your request
Be more specific with Pi:
```
/pi-improve [skill-name] to specifically [exact behavior you want]
```

### 2. Check the generated files
Look at what Pi created:
```
cat .claude/skills/pi-custom/[skill-name]/skill.md
cat .claude/skills/pi-custom/[skill-name]/prompt.md
```

The skill.md shows configuration, prompt.md shows the actual instructions.

### 3. Test in isolation
Run the skill and note exactly what it outputs. Compare to what you expected.

### 4. Iterate with Pi
Pi learns from feedback:
```
/pi-improve [skill-name] - it currently does X but I need it to do Y instead
```

---

## How to Report Bugs

When reporting bugs, include:

1. **What you tried:**
   - The exact command or prompt you used

2. **What happened:**
   - The error message (copy the full text)
   - Any files that were created

3. **What you expected:**
   - What should have happened instead

4. **Environment:**
   - Run `/pi-status` and include the output
   - Your operating system

### Quick report
```
/pi-feedback Bug: [description]
Command: [what you ran]
Error: [error message]
```

### Detailed report
For complex issues, create a file `System/Pi/bug-report-[date].md` with full details, then reference it in your feedback.

---

## Still Stuck?

If none of the above helps:

1. Check the beta Discord channel - others may have hit the same issue
2. Try a complete reset (see above) and start fresh
3. Reach out directly to the beta coordinator with your bug report

Thanks for helping us make Pi better!
