# Share your Dex setup — and adopt other people's (DexDiff)

*A guide for Dex users. Applies to both the **Desktop app** and **open-source Dex** (this repo). Read the capability table — some of this is desktop-only today.*

---

## What this is, in one line

DexDiff lets you **publish how you use Dex** — your real workflows and methodologies — so a colleague can **pull your setup into their own Dex** and start working the way you do. No copying files by hand.

## Why it's useful

Most people rebuild the same AI workflows from scratch. DexDiff lets the person who already figured out "how to run great meeting prep in Dex" hand that whole way-of-working to a teammate — the methodology, the folder conventions, the ordered set of skills — as a living thing their Dex adapts to *their* vault, not a static doc they have to reimplement.

Two verbs:

- **Publish** — share your profile (a set of workflows) so others can adopt it.
- **Adopt** — pull someone's published profile into your own Dex.

---

## Who can see what you publish — three visibility levels

When you publish, you choose one:

| Visibility | Who can see / adopt it |
|---|---|
| **Private** | Only you. A safe place to draft before sharing. |
| **Colleagues** | Only people at your company (verified by your work-email domain). |
| **Public** | Anyone. *(Not enabled in the current version — see "Current status".)* |

Your profile lives on the web at `heydex.ai/diff/<your-handle>`, gated by whichever level you chose. "Colleagues" means a signed-in teammate on the same work domain — nobody outside your company, and nobody who simply guesses your handle.

---

## On the **Desktop app** — the full experience

**Publish:** in chat, ask Dex to "publish my profile." Dex drafts it from your vault, opens a browser review page where you edit and approve, and you pick a visibility level. Nothing goes live until you approve it.

**Adopt a colleague's profile:**
1. Your colleague signs in at **heydex.ai/diff** with their work Google account and opens your profile.
2. They click **Open in Dex**.
3. The Dex app opens and walks them through adopting your workflows in chat — previewing what will be written into *their* vault, adapting to their setup, and never overwriting anything.

The desktop app handles colleagues-only adoption safely: because your profile isn't public, the website hands the app a **single-use pass** (valid ~10 minutes, for exactly your profile, only because your colleague is a verified teammate). The app uses it once to fetch, then it's spent. Your profile never becomes public.

---

## On **open-source Dex** (this repo)

Open-source Dex ships the same DexDiff **skills** (`/diff-adopt-profile`, `/diff-list`, and the publish flow) — the command-line experience, without the desktop app around them.

**What works here:**

- **Publishing your profile** — runs from the CLI. Dex drafts your profile, you approve it in a browser review page, and you can set Private / Colleagues / Public.
- **Adopting a *public* profile** — `/diff-adopt-profile @handle` fetches and installs a public profile into your vault.

**What doesn't (yet):**

- **Adopting a *colleagues-only* profile is desktop-only.** The private-adopt flow relies on the desktop app's `dex://` "Open in Dex" link and its single-use pass, which the command-line tools don't have. The CLI fetches profiles anonymously, so it can only reach *public* ones — point it at a colleagues-only profile and it will tell you the profile is private and stop.

---

## Capability at a glance

| Capability | Desktop app | Open-source Dex |
|---|---|---|
| Publish your profile (private / colleagues / public) | ✅ | ✅ |
| Adopt a **public** profile | ✅ | ✅ |
| Adopt a **colleagues-only** profile | ✅ | ❌ (desktop-only) |
| One-click "Open in Dex" from the web | ✅ | ❌ (no desktop app to open) |

---

## Current status

- **Colleagues-only sharing and adoption is live on the Desktop app.**
- **Public sharing is not enabled in the current version** — nothing renders publicly yet. Until it is, the open-source "adopt a public profile" path has nothing to point at.
- **For open-source users:** you can publish today. Adopting a colleague's private profile is a desktop-app capability in this version; public adoption becomes useful once public sharing is turned on.

---

## FAQ

**"I'm on open-source Dex — will I be able to adopt my colleague's private profile?"**
Not in the current version — it's desktop-only today. It's a known limitation that may be addressed in a future release (it would need a small addition to the command-line tools and a way to receive a pass without the desktop app).

**"Does adopting someone's profile overwrite my own files?"**
No. Adoption previews what it will add and never overwrites existing files without asking.

**"Is my colleagues-only profile really private?"**
Yes. It's served only to signed-in teammates on your work domain, and the desktop adopt uses a single-use, short-lived, profile-specific pass. There is no anonymous path to a colleagues-only profile.
