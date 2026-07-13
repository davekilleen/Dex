# Contributing to Dex

You've been using Dex. Maybe you fixed something that was bugging you. Maybe you built a new skill, connected a new tool, or wrote a guide that would've saved you an hour on day one. Whatever it is — Dave would love to see it.

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

## How to Share Your Changes

### The simple version (recommended)

1. **Make your changes in Dex as normal** — fix the bug, build the skill, write the guide
2. **Ask Claude to help you share it.** Say something like:

   > "I made some improvements to Dex that I'd like to share back with the community. Can you help me create a pull request?"

3. Claude will walk you through it — creating a branch, describing what you changed, and submitting it. You don't need to know what any of those words mean. Just follow along.

4. **Your changes appear on GitHub** for review. Dave will take a look, give feedback if needed, and merge it in.

That's it. Claude handles the git mechanics. You just describe what you changed and why.

### What makes a good contribution

- **Explain the "why", not just the "what."** "Calendar setup was confusing for Google Calendar users on Mac" is more helpful than "changed 3 files."
- **Keep it generic.** Your personal setup has your name, your company, your deals. Strip those out before sharing. Use placeholder examples like "Acme Corp" instead of real company names.
- **Test it.** Run your change at least once to make sure it works. Mention what you tested in your description.
- **Small is fine.** A one-line fix that helps everyone is just as valuable as a big new feature.

### What to avoid

- **Personal data.** CI enforces this on every pull request by checking newly added lines for real emails, filled-in profile or integration identity, vault content, and other personal configuration. If the PII / personal-config gate fails, remove the named data, restore the tracked placeholder template, or replace examples with an approved fake value from `scripts/pii-allowlist.txt`; the failure prints the exact file and line. You can still ask Claude: "Can you check these files for any personal information before I share them?"
- **Breaking existing features.** If you're not sure whether your change might affect something else, mention that in your description. Dave would rather know upfront than discover it later.

---

## The Review Process

When you submit changes:

1. **Dave will review within a few days** — usually faster
2. **He might ask questions** — not because something's wrong, just to understand your thinking
3. **He might suggest tweaks** — small adjustments to fit Dex conventions
4. **He'll merge it** — and credit you in the changelog

If your contribution adds a meaningful feature, you'll be mentioned by name in the release notes. Every contribution matters.

---

## Ideas Welcome Too

Not sure how to build something? Open an issue on GitHub and describe what you wish Dex could do. The best features often start as "wouldn't it be nice if..." from someone using the system every day.

To open an issue, go to: **github.com/davekilleen/Dex/issues** and click "New Issue."

Describe:
- What you were trying to do
- What happened instead (or what's missing)
- Why it matters to your workflow

---

## A Note on AI-Assisted Contributions

Most Dex contributions are written with AI help — and that's not just OK, it's the point. Dex is an AI-powered system built by people who use AI daily. If Claude helped you write the code, that's great. Just make sure you understand what it does and that you've tested it.

---

## Thank You

Dex started as a personal project. Seeing other people use it, improve it, and share those improvements back is genuinely amazing. Every pull request, every issue, every "hey, this doesn't work" message makes the system better for everyone.

Welcome aboard.
