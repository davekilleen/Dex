# Updating Dex — Explained Simply

**Last Updated:** July 26, 2026 (reflects the receipt-backed update system, v1.65+)

This guide explains how Dex updates work, written for people who've never used
developer tools. The short version: **you type `/dex-update`, Dex shows you exactly
what would change, nothing happens without your yes, and every change can be undone.**

---

## The Big Picture

**What are updates?**

Think of Dex like an app on your phone. Every week or two there are improvements:
new features, bug fixes, things running smoother. Dex lives on your computer rather
than in an app store, so you update it by asking Dex itself.

**The one promise that matters:**

> Every change goes through one safe door: Dex previews what would change, backs it
> up, applies it, verifies it, writes a receipt — and can rewind it exactly.

Your notes, tasks, projects, and people pages are **never part of an update**. Dex
keeps a strict map of which files belong to the product and which belong to you, and
the update machinery refuses to write into yours. A file it can't confidently
classify is left alone, always.

**No git, no GitHub account, no Terminal required.** Older versions of this guide
walked through git commands and GitHub setup. That era is over: the update engine
handles everything behind the scenes.

---

## Updating: What Actually Happens

### Step 1 — Ask for the update

In your Dex chat, type:

```
/dex-update
```

Dex checks what's available and shows you a preview sorted into five honest groups:

1. **New and safe to adopt** — improvements Dex can apply without touching anything of yours.
2. **Needs your review** — files where *you've* made changes and the update also
   carries a new version. Nothing here moves until you decide (see "When you've
   customized things" below).
3. **Held back by you** — things you previously said no to. Dex remembers and doesn't re-ask.
4. **Could not be proved** — anything Dex can't verify with certainty. No change
   will be made to these, period. Honesty over completeness.
5. **Already yours** — what you've adopted before, with its undo receipt still available.

### Step 2 — Say yes (or no)

For anything that would actually change, Dex shows the exact files first and asks one
direct question: *"Apply this exact update?"* Saying "update Dex" earlier doesn't
count as approval — only a yes to the concrete preview does.

### Step 3 — The receipt

After applying, Dex shows a receipt: what changed, applied in one crash-safe step,
with a backup taken first. If your computer lost power mid-update, you'd end up with
either the old version or the new one — never a half-done mess.

### Undoing an update

Type `/dex-rollback`. Dex uses the receipt to rewind the exact change — the same
files, byte for byte. Dex keeps your last 3 rewind points.

---

## When You've Customized Things

If you've edited a skill, added your own scripts, or tuned your instructions, updates
respect that — and this got a major upgrade in mid-2026 (v1.75).

**Conflicts get four choices, per file:**

- **Keep mine** — your version stays; nothing is written.
- **Take theirs** — the new release version goes live; yours stays recoverable via rewind.
- **Keep both** — the release version becomes the standard one, and your edited
  version is preserved beside it (as `name-custom`) where it still works. Fully rewindable.
- **Compare** — see the differences first, then choose. Looking never changes anything.

**Deeply customized setups get a guided journey.** If Dex's health check
(`/dex-doctor`) finds you've customized a lot, `/dex-update` offers to walk you
through it: it inventories everything you've changed, explains what the update would
affect, and — only with your explicit yes — saves a protected local snapshot of your
customization evidence (called a **Capsule**, stored inside your vault's
`System/.dex/` area, never uploaded) before proceeding through the normal
preview-and-approve flow. Nothing is overwritten, and the Capsule survives the update
so your work is never lost.

---

## The One-Time "Brain and Vault" Separation

Older Dex installs kept the product's files and your personal notes together in one
combined history. Newer Dex separates them — the product (the "brain") and your
content (the "vault") — so an update can't even theoretically touch your notes, and
your private vault history is never uploaded anywhere.

If your install still has the combined layout, `/dex-update` offers this move as a
**one-time step**, with the same rules as everything else: full preview first,
explicit yes required, and the old combined history is kept locally as an undo
archive named in the receipt. Dex refuses to attempt it in risky situations (for
example, a vault living inside a Dropbox- or iCloud-synced folder) rather than gamble
with your files.

---

## Frequently Asked

**How do I see what's new without updating?** Type `/dex-whats-new`.

**Should I update?** Usually yes. You can always preview first and adopt nothing, and
anything you adopt can be rewound.

**Can I skip individual items?** Yes — each item is decided independently, and
"skip this one" can't affect the rest. Skipped items show up under "Held back by
you" next time, without nagging.

**What if an update refuses to proceed?** That's the safety system working, not
breaking. Dex explains the refusal in plain language and leaves everything untouched.
Run `/dex-doctor` for a full health check.

**Do I need a GitHub account, git, or Terminal?** No.

**What about my custom MCP servers and personal instructions?** They're classified as
yours in the ownership map, so updates never write them. Personal additions to your
instructions survive updates too.

**Where do I get help?** The Dex Guide at https://heydex.ai/help, or ask Dex
directly in chat — "something went wrong with the update" routes to `/dex-doctor`.

---

*For the technical design behind all this, see `docs/architecture/DEX-CORE-MAP.md`
(lifecycle engine, transaction core, and customization migration sections) in the
dex-core repository.*
