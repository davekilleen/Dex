# Dex FAQ (DRAFT)

> **Status:** Internal draft - not yet released
> **Last Updated:** 2026-02-04

---

## Syncing & Multi-Machine Setup

### How do I sync Dex across multiple computers?

The best option is **Obsidian Sync** ($8/month from Obsidian).

**Why we recommend it:**

1. **End-to-end encrypted** - Your notes are encrypted on your device before they're uploaded, and only you have the key. Even Obsidian's team cannot read your data.

2. **Mobile access included** - Obsidian has apps for iOS and Android, and Sync works seamlessly with them. Your entire vault becomes accessible from your phone - great for reviewing meeting notes before a call, checking tasks on the go, or capturing quick thoughts when you're away from your desk.

3. **Just works** - No technical setup, no merge conflicts, no servers to manage. Enable it once and your vault stays in sync across all your devices automatically.

**Other options that work but with caveats:**

| Option | Works? | Privacy Concern |
|--------|--------|-----------------|
| **Obsidian Sync** | ✅ | ✅ End-to-end encrypted + mobile |
| **iCloud** | ✅ | ⚠️ Apple can access your files |
| **Dropbox** | ✅ | ⚠️ Dropbox can access your files |
| **Google Drive** | ✅ | ⚠️ Google can access your files |
| **GitHub (private repo)** | ✅ | ⚠️ Microsoft/GitHub can access your files |

These services encrypt your data "at rest" on their servers, but **they hold the encryption keys** - meaning they can technically read your files if required (by law enforcement, internal policies, or in the event of a breach).

For a vault containing meeting notes, people context, career information, and business discussions, we recommend the peace of mind that comes with true end-to-end encryption.

**To set up Obsidian Sync:**
1. In Obsidian, go to Settings → Core plugins → Enable "Sync"
2. Click the Sync icon in the left sidebar
3. Sign in or create an Obsidian account
4. Follow the setup wizard
5. Install Obsidian on your phone and sign in to access on mobile

Your vault will sync automatically across all devices where you're signed in.

---

### I've already set up Dex but didn't enable Obsidian integration. How do I turn it on?

Run `/dex-obsidian-setup` in your Dex session.

This will convert your vault to use **WikiLinks** - the `[[double bracket]]` format that Obsidian uses to connect notes. Once enabled:

- **Everything links together** - When Dex mentions a person, project, or meeting, it automatically creates clickable links to the relevant pages
- **Graph view works** - See how all your knowledge connects visually in Obsidian's graph view
- **Click-through navigation** - Jump from a meeting note to a person page to their company page with single clicks
- **Backlinks appear** - See everywhere a person or project is mentioned across your vault

The migration is safe to run on existing vaults - it scans your files and converts standard markdown links to WikiLinks where appropriate.

---

## [More FAQ entries to be added]

<!-- 
Future topics to cover:
- How does Dex differ from vanilla Obsidian?
- What data does Dex/Claude have access to?
- Can I use Dex without Obsidian?
- How do I back up my vault?
- What happens if I stop using Dex?
- Is my data sent to Anthropic?
- How do I customize Dex for my workflow?
- Can I share my vault with my team?
- What's the difference between Dex and [competitor]?
-->
