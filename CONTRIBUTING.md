# Contributing to Dex

You've been using Dex. Maybe you fixed something that was bugging you. Maybe you built a new skill, connected a new tool, or wrote a guide that would've saved you an hour on day one. Whatever it is — we'd love to see it.

**You don't need to be a developer to contribute.** If you can use Dex, you can share improvements. Claude will help you with the technical bits.

---

## What Counts as a Contribution

Anything that makes Dex better for someone else:

- **Bug fixes** — Something wasn't working and you figured out why
- **New skills** — You built a `/skill` that's useful beyond your personal setup
- **Documentation** — Setup guides, workflow tips, "here's how I use Dex for X"
- **Templates** — Meeting note templates, project structures, pillar configurations for specific roles
- **Integrations** — Connected Dex to a new tool (Slack, Notion, Linear, etc.)
- **Ideas** — Even if you can't build it, describing what you wish Dex could do is valuable

---

## Getting Started

### Prerequisites

- **macOS** (Dex uses AppleScript for Calendar.app and macOS LaunchAgents)
- **Python 3.12+** and **Node.js 20+**
- **Claude Code** CLI installed

### Local setup

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/<your-username>/Dex.git
cd Dex

# 2. Install dependencies
npm ci
pip install pytest pytest-cov ruff mcp pyyaml python-dateutil requests

# 3. Copy the environment template
cp .env.example .env
# Fill in your values — see .env.example for documentation

# 4. Run the test suite to verify everything works
pytest core/tests/ core/mcp/tests/ -v
npm run test:hooks
```

---

## How to Share Your Changes

### The simple version (recommended)

1. **Make your changes in Dex as normal** — fix the bug, build the skill, write the guide
2. **Ask Claude to help you share it.** Say something like:

   > "I made some improvements to Dex that I'd like to share back with the community. Can you help me create a pull request?"

3. Claude will walk you through it — creating a branch, describing what you changed, and submitting it. You don't need to know what any of those words mean. Just follow along.

4. **Your changes appear on GitHub** for review.

That's it. Claude handles the git mechanics. You just describe what you changed and why.

### The developer version

```bash
# 1. Create a branch from main
git checkout main && git pull
git checkout -b feat/your-feature-name

# 2. Make your changes, then run tests
pytest core/tests/ core/mcp/tests/ -v --cov=core
npm run test:hooks

# 3. Commit with conventional format (see Commit Conventions below)
git commit -m "feat: add calendar sync for Google Workspace"

# 4. Push and create a PR
git push -u origin feat/your-feature-name
gh pr create --fill
```

---

## Branch Naming

Use prefixes that describe the type of change:

| Prefix | Use for |
|--------|---------|
| `feat/` | New features or integrations |
| `fix/` | Bug fixes |
| `docs/` | Documentation only |
| `chore/` | Maintenance, dependencies, CI |
| `ship/` | Multi-feature shipping branches |

Examples: `feat/notion-sync`, `fix/calendar-timezone`, `docs/office365-setup`

---

## Commit Conventions

Dex uses [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <short description>

<optional body explaining why, not what>
```

**Types:** `feat`, `fix`, `docs`, `chore`, `refactor`, `test`

**Good examples:**
- `feat: add Office 365 calendar backend`
- `fix: prevent command injection in vault search`
- `docs: add Notion sync setup guide`

**Avoid:**
- `update files` (too vague)
- `fix stuff` (what stuff?)
- `WIP` (don't commit work-in-progress to shared branches)

---

## Pull Request Guide

Every PR uses the template at `.github/pull_request_template.md`. Here's how to fill each section:

### What Changed

2-4 bullets covering **what** you built, **why** it matters, and **how** (if non-obvious). Lead with the user impact, not file names.

```markdown
- Added Office 365 calendar support for users who don't use Apple Calendar
- Uses Microsoft Graph API with OAuth2 device-code flow
- Configured via `calendar_backend: office365` in user-profile.yaml
```

### Test Plan

Be specific about what you tested and how:

```markdown
- Unit tests: `pytest core/mcp/tests/test_calendar.py -v`
- Manual: Verified OAuth flow with personal Azure tenant
- Edge case: Tested with expired refresh token — error message is clear
```

### Ralph Wiggum Loop

A self-review checklist. Check each box honestly:

- **I implemented the change** — obvious, but confirm it's complete
- **I self-reviewed for defects** — re-read your own diff before submitting
- **I requested specialist review** — if you touched auth, MCP servers, or CI, flag it
- **I addressed review findings** — after feedback, check this off

### Risk & Rollback

Assess honestly:

| Level | When to use | Example |
|-------|-------------|---------|
| **Low** | Additive changes, docs, new files nothing depends on | New skill, README update |
| **Medium** | New integrations, changes to existing features | Calendar backend, Slack bot |
| **High** | Data migrations, auth changes, CLAUDE.md core behaviors | Changing task ID format |

Include a rollback plan: "Revert commit" is fine for most changes.

### Docs Impact

If you added a feature, at minimum update:
- **CLAUDE.md** — so Dex knows about it and can help users
- **CHANGELOG.md** — so users know what's new (use the existing format)

---

## CI Pipeline

Every PR runs these automated checks. **All must pass before merge.**

| Check | What it does | Common fix |
|-------|-------------|------------|
| **Pytest + coverage** | Runs all test suites, enforces 15% minimum coverage | Add tests for new code |
| **Hook harness tests** | Tests Claude Code hooks | `npm run test:hooks` locally |
| **PR governance** | Validates PR template is filled out | Fill in all sections |
| **Diff-aware test gate** | Ensures changed files have corresponding tests | Add test file for new modules |
| **Path-contract usage** | Verifies code uses `core/paths.py` constants | Use `paths.VAULT_DIR` not hardcoded paths |
| **Documentation drift** | Checks docs match code changes | Update docs when changing features |
| **Security gate** | Scans for secrets, hardcoded paths, unsafe patterns | See Security Rules below |
| **Ruff linting** | Python code style and quality | `ruff check core/ --fix` |
| **Distribution safety** | Ensures no user data leaks into the repo | Check `.gitignore` coverage |
| **Path consistency** | Validates path references across codebase | Use path constants consistently |

Run the full suite locally before pushing:

```bash
pytest core/tests/ core/mcp/tests/ core/migrations/tests/ -v --cov=core
npm run test:hooks
ruff check core/
bash scripts/security-gate.sh
```

---

## Security Rules

Dex handles personal data — meetings, contacts, calendar events, messages. Security is non-negotiable.

### Must do

- **Never commit secrets.** API keys, tokens, and passwords go in `.env` (which is gitignored). Use `.env.example` to document new variables.
- **Never commit PII.** Names, phone numbers, email addresses, meeting content must not appear in tracked files. Ask Claude to scan: "Check these files for personal information."
- **Use `execFileSync` for external commands.** Never pass user input through `execSync` shell strings — this enables command injection. Pass arguments as arrays via `execFileSync`.
- **Validate at system boundaries.** Sanitize input from Slack messages, WhatsApp, API responses, and LLM outputs before using it in commands or file operations.
- **Least privilege for OAuth scopes.** Request only the permissions you actually need (e.g., `Calendars.Read` not `Calendars.ReadWrite` if you only read).
- **Keep `.env` permissions restricted.** `chmod 600 .env` — owner read/write only.

### Must avoid

- Hardcoded resource IDs (Notion database IDs, Slack channel IDs) — use environment variables
- Hardcoded filesystem paths (`/Users/username/...`) — use `core/paths.py` or `__dirname`
- Logging sensitive data (tokens, full error responses from OAuth providers)
- Storing unencrypted conversation history in git-tracked directories

---

## What Makes a Good Contribution

- **Explain the "why", not just the "what."** "Calendar setup was confusing for Google Calendar users on Mac" is more helpful than "changed 3 files."
- **Keep it generic.** Your personal setup has your name, your company, your deals. Strip those out before sharing. Use placeholder examples like "Acme Corp" instead of real company names.
- **Test it.** Run your change at least once to make sure it works. Mention what you tested in your PR.
- **Small is fine.** A one-line fix that helps everyone is just as valuable as a big new feature.
- **Update CLAUDE.md.** If you add a feature that Dex should know about, add a section so it can guide users.

---

## What to Avoid

- **Personal data.** Double-check that your real names, companies, emails, and meeting content aren't in the files you're sharing. Ask Claude: "Can you check these files for any personal information before I share them?"
- **Breaking existing features.** If you're not sure whether your change might affect something else, mention that in your PR description.
- **Scope creep.** Fix the bug, add the feature, update the docs — then stop. Don't refactor surrounding code or add "nice to have" improvements in the same PR.

---

## Project Structure (Key Directories)

```
core/mcp/           # MCP servers (Python) — calendar, work, improvements, etc.
core/tests/          # Python test suites
.claude/skills/      # Skill definitions (SKILL.md files)
.claude/hooks/       # Claude Code hooks (context injection, safety)
.scripts/            # Node.js automation (Slack bot, meeting sync, Notion sync)
scripts/             # CI/CD and quality gate scripts
System/              # User config (gitignored — pillars, profile, integrations)
06-Resources/        # Reference documentation and system guides
.github/             # CI workflows, PR template, CODEOWNERS
```

**CODEOWNERS:** All changes are reviewed by `@davekilleen`. Changes to `.github/`, `core/mcp/`, `scripts/`, `System/PRDs/`, and `docs/` require explicit owner approval.

---

## The Review Process

When you submit changes:

1. **CI runs automatically** — fix any failures before requesting review
2. **A maintainer will review within a few days** — usually faster
3. **They might ask questions** — not because something's wrong, just to understand your thinking
4. **They might suggest tweaks** — small adjustments to fit Dex conventions
5. **They'll merge it** — and credit you in the changelog

If your contribution adds a meaningful feature, you'll be mentioned by name in the release notes.

---

## Ideas Welcome Too

Not sure how to build something? Open an issue on GitHub and describe what you wish Dex could do. The best features often start as "wouldn't it be nice if..." from someone using the system every day.

Describe:
- What you were trying to do
- What happened instead (or what's missing)
- Why it matters to your workflow

---

## A Note on AI-Assisted Contributions

Most Dex contributions are written with AI help — and that's not just OK, it's the point. Dex is an AI-powered system built by people who use AI daily. If Claude helped you write the code, that's great. Just make sure you understand what it does and that you've tested it.

When Claude co-authors a commit, add the co-author trailer:

```
Co-Authored-By: Claude <noreply@anthropic.com>
```

---

## Thank You

Dex started as a personal project. Seeing other people use it, improve it, and share those improvements back is genuinely amazing. Every pull request, every issue, every "hey, this doesn't work" message makes the system better for everyone.

Welcome aboard.
