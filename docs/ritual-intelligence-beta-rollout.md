# Ritual Intelligence Beta Rollout

This document is the rollout handoff for sending Ritual Intelligence to a small beta-tester cohort.

It is split into two parts:
- `Operator setup` for Dave or whoever is running the rollout
- `Beta tester handout` that can be copied into a Google Doc, email, or Slack message

---

## Operator Setup

### Recommended rollout model

Use the existing Dex beta activation system rather than a separate build:

1. Ship the same `dex-core` release to everyone.
2. Add a new beta feature key for Ritual Intelligence.
3. Give the activation code only to the BT cohort.
4. Keep Ritual Intelligence behind both:
   - beta activation
   - the built-in `observe -> preview -> opt-in` behavior

This keeps rollout selective without maintaining a separate branch or package.

### Suggested feature key

`ritual_intelligence`

### Suggested activation code

Replace this with your real code before sending:

`DEXRITUAL2026`

### Suggested beta config entry

Add a new feature entry in `.claude/config/beta-features.yaml`:

```yaml
  ritual_intelligence:
    name: "Ritual Intelligence"
    description: "Local-first recurring meeting intelligence for prep, transcript matching, and contact suggestions."
    version: "0.1.0"
    status: "active"
    code_hash: "[sha256 of salt:code]"
    code_salt: "ritual-intelligence-beta-2026"
    instructions_file: "System/Beta/ritual-intelligence/README.md"
    capabilities:
      - "ritual_preview"
      - "ritual_confirm"
      - "ritual_one_off_prep"
      - "ritual_transcript_matching"
      - "ritual_contact_suggestions"
    min_dex_version: "1.0.0"
    feature_flags:
      enable_ritual_intelligence: true
```

### Rollout steps

1. Merge the Ritual Intelligence implementation into the release branch you want BT users on.
2. Add the Ritual Intelligence beta feature entry to `.claude/config/beta-features.yaml`.
3. Create or copy user-facing instructions into `System/Beta/ritual-intelligence/README.md`.
4. Share the activation code only with the BT cohort.
5. Ask testers to update Dex, activate the feature, and run the test flows below.
6. Collect feedback for 1-2 weeks before opening it more broadly.

### What users will get

Ritual Intelligence v1 is local-first and writes only to:
- `05-Areas/Meetings`
- `05-Areas/Meetings/Daily_Log`

Compatibility behavior:
- `00-Inbox/Meetings` is read-only compatibility storage for matching/import only
- the canonical store lives in `System/.dex/ritual-intelligence.db`
- markdown remains a projection, not the system of record

### What to watch during beta

Focus on trust and correctness, not just feature excitement:
- Did Dex create anything surprising?
- Did it match the right meeting occurrence?
- Did it avoid writing where it should not?
- Did it preserve user-edited prep blocks?
- Did it avoid duplicate meeting notes?
- Did contact suggestions feel useful rather than noisy?

---

## Beta Tester Handout

Copy from here downward into a Google Doc, email, or Slack post.

---

# Ritual Intelligence — Private Beta

Hey — thanks for being one of the first people to try this. I'm genuinely excited about this one.

## The Problem

You have meetings that happen every week. The Monday pipeline review. The Thursday 1:1 with your manager. The fortnightly deal sync.

Before each one, there's a scramble. What did we talk about last time? Did I follow up on that thing I said I'd do? What's changed since we last spoke? Who's the new person on the invite?

So you either spend 10 minutes hunting through old notes, Slack threads, and email — or you walk in cold and wing it. Neither feels great. And you do this *every week*, for *every recurring meeting*.

**Ritual Intelligence means you never walk into a recurring meeting unprepared again.**

## What's Different About This

Most AI meeting tools help you *after* a meeting — they transcribe, summarise, generate action items. That's useful, but it's table stakes now.

**What's different is that Dex works *before* the meeting starts.**

Dex learns which meetings are your recurring rituals. Then, before each one, it automatically builds you a brief:

- **What happened last time** — key decisions, open threads, actions that are still dangling
- **What's changed since then** — updates from your notes, tasks, and the people involved
- **Who's in the room** — context on each attendee, pulled from everything Dex knows about them
- **What you should probably raise** — suggested talking points based on commitments you've made and activity since the last session

And here's the bit I'm most excited about: **it gets smarter over time.** Each meeting builds on the last. Context carries forward automatically — so the brief for your Thursday 1:1 in week 12 knows what happened in weeks 11, 10, and 9. It's compound meeting memory.

Think of it as a chief of staff who reads all your notes before you walk in.

## How It Works Day-to-Day

Everything happens through your normal Dex chat. No new apps, no new windows.

**During your daily plan:** When you run `/daily-plan`, Dex will now show you any upcoming meetings it thinks are recurring rituals. The first time, it'll ask you to confirm which ones you actually want it to track — you pick the ones that matter.

**Before each ritual:** For any meeting you've confirmed as a ritual, Dex creates a prep brief as a markdown file in your Meetings folder. You'll see it referenced in your daily plan, and you can open it like any other note. It includes everything listed above — last session context, attendee info, suggested talking points, open actions.

**After the meeting:** If you use Granola for transcription, Dex matches the transcript to the correct meeting. It does this by comparing the meeting time, title, and attendees — not just the name, which can be ambiguous when you have multiple recurring meetings with similar titles. If it's not confident about the match, it'll ask you rather than guess. That matched transcript then feeds into the *next* ritual brief, closing the loop.

**One-off prep:** Got a meeting that isn't a ritual but you'd like a brief for? Just ask Dex: "prep me for the 2pm with Sarah" and it'll build a one-time brief without enrolling the whole series.

**Contact suggestions:** Inside each ritual brief, Dex may suggest people who came up in conversation or appeared on the invite that you don't have a page for yet. You'll see these as inline suggestions in the brief itself — "Create page for James Chen?" with options to accept, skip, or tell Dex to stop suggesting that person.

### For the Adventurous

If you want to go deeper and trigger things manually (you know who you are), there are Python commands you can run directly:

- `python -m core.ritual_intelligence refresh-calendar` — pull latest calendar data
- `python -m core.ritual_intelligence preview-suggestions` — see what Dex thinks your rituals are
- `python -m core.ritual_intelligence confirm-ritual <series_id>` — confirm a ritual
- `python -m core.ritual_intelligence review-transcripts` — see unmatched transcripts

But honestly, most of you shouldn't need these. The chat flow handles it.

## How To Turn It On

1. Make sure you're on the latest version of Dex
2. Tell Dex: `/beta-activate DEXRITUAL2026`
3. Tell Dex: `/beta-status` to confirm it's active

That's it. Next time you run `/daily-plan`, Dex will start recognising your recurring meetings and ask which ones to track.

## Trust and Boundaries

I've been very deliberate about keeping this trustworthy. Here's what Dex will *not* do:

- **It won't create people or company pages without asking.** It suggests — you decide. (Depending on your feedback, I may add a setting to let it auto-create if you prefer that. But the default is always ask-first.)
- **It won't prep meetings you haven't confirmed as rituals.** No surprise notes popping up for random calendar events. You choose which recurring meetings Dex should care about.
- **It won't overwrite notes you've written yourself.** If you've manually written or edited the meeting notes file that Dex created, it recognises that and stops auto-updating it. Your words take priority.
- **It won't touch your existing meeting notes.** Anything you had before this beta stays exactly where it is.

The philosophy: **confident when right, silent when uncertain.** If Dex isn't sure, it asks rather than guesses.

## What I'd Love You To Try

Just use it with your real meetings for a week or two. Don't try to break it — just see if it actually helps your day.

Specifically:

1. **Confirm 2-3 recurring meetings** and see if the prep briefs feel useful before your next session
2. **Check the continuity** — does this week's brief actually know what happened last week?
3. **Try one-off prep** for a non-recurring meeting and see how it feels
4. **If you use Granola**, check that transcripts land on the right meeting — especially when you have multiple meetings with similar names on the same day
5. **Check the contact suggestions** inside the ritual briefs — are they people worth tracking, or noise?

## Telling Me What You Think

The most helpful feedback is just your honest reaction:

- **"This saved me 10 minutes before my Monday sync"** — great, tell me
- **"It prepped the wrong meeting"** — tell me which one and when
- **"The contact suggestions were noisy"** — tell me what felt off
- **"It felt too automatic / spooky"** — that's exactly what I need to hear
- **"I didn't understand what it was doing"** — that's on me, not you

When something goes wrong, the most useful details are:
- Which meeting (name and rough date)
- Whether it was a recurring or one-off meeting
- What you expected vs what actually happened

For now, send feedback to **hey@heydex.ai**. Put **"Ritual Intelligence"** in the subject so I can track it. I'll have a better feedback setup in the next couple of weeks, but email works for now.

## What's Coming Next

This beta doesn't include everything yet. On the roadmap:

- Multi-calendar support (right now it works with your primary calendar)
- Speculative prep for non-ritual meetings (so Dex preps *every* meeting, not just the ones you've confirmed)
- More transcript sources beyond Granola
- A proper feedback channel for betas in general

## Thank You

I think this could genuinely change how people prepare for meetings. Not by recording more — by remembering better.

I'd rather ship something small that earns your trust than something flashy that feels creepy. So if anything feels off, that's the single most valuable thing you can tell me.

— Dave

---

*Beta v0.1.0 • March 2026*
