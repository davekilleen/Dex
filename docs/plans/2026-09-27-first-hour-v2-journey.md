# First Hour v2 — journey

**Status:** Phase 1 transcript. No implementation in this commit.  
**Date:** 2026-09-27  
**Proposed command:** `/setup-v2`  
**Shipped default:** `/setup` (unchanged)

This is what the person hears. Tool names stay in stage directions. They never appear in the spoken lines.

Source note: the attached brief and `dex-product-gtm-lab#720` were not readable in this run. The happy path and branches below are taken from this run’s Phase 1 instructions, the #621 product contract (`docs/plans/2026-08-27-first-hour-onboarding.md` @ `20c9dc52`), and what current `main` can actually do. If the brief names extra branches, add them here before Phase 2.

---

## Command

**Name:** `/setup-v2`

Why this name:

- Repo skills are kebab-case (`/granola-setup`, `/getting-started`).
- The job is distinct from shipped `/setup`, so a second command is required.
- `/setup-lab` is the August preview name on PR #621. This is a new experience on current `main`.
- The first-party skill standard prefers not to suffix a *duplicate* job with `-v2`. This is not a duplicate: `/setup` stays the default questionnaire; `/setup-v2` is the conversation hour.

Router description (draft, for Phase 2):

> Run the fifteen-minute Dex first-hour preview: confirm who you are, organise this week from your calendar and notes, and make one shortcut live. Use when the user says `/setup-v2`, `try the new first hour`, or `preview setup`. Not for everyone’s shipped first setup; use `setup`. Not for the post-setup tour; use `getting-started`. Not for a mid-life role change; use `reset`.

---

## Rules that apply to every path

- Fifteen minutes of attention. Never say ten. Never say “the hour” to the person.
- First visible text is a hello. **Zero tools on that turn.**
- One question, then wait. Ignore teammate pings and helper-idle notices while they are answering.
- Never name host products, models, or vendors.
- Never say: connector, MCP, vault, permission, sync failed, cron, `/connect`.
- Never invent a door Dex does not have (Fireflies, Gong, Slack content, Salesforce content).
- Never claim a morning brief is ready unless morning skills can read the same calendar just stored.
- Never create a page for the person themselves.
- Email domain is still mandatory underneath (or an explicit “I don’t have one”).
- Vault writes go only through `onboarding-mcp` → lifecycle.
- A new `/setup-v2` starts fresh (`force_new`). Only skip that if they asked to finish a crashed close.
- If the onboarding tools are missing: one honest line, stop. Do not install from the chat.

---

## Happy path (Scenario A)

Apps already signed in on this host. Calendar readable. Meeting notes are Granola with a key Dex can store, or Granola already usable in this chat. They say yes to pages and to one shortcut. They skip cue cards.

Names below are generic.

### Turn 1 — hello only

**Dex:** Hey Alex — welcome to Dex. You’re taking the leap, and this is going to be good. For the next fifteen minutes I’ll help you keep meetings, people, and follow-ups in one place you own. I can already see your calendar, mail, and meeting notes. I’d like to read the calendar and the notes so I can organise your week. I won’t change anything in those apps. Sound good?

*(stop)*

### Turn 2 — after “yes”

**Dex:** Hi Alex, great to meet you. I’m Dex, your new Chief of Staff.

If talking is easier, hold the microphone and tell me as much as you like — how you work, who matters, what this quarter is for. If you have last year’s annual or performance review, your career ladder, your job spec, or a saved extract of your public profile, paste that in too. The more you give me now, the more useful your next working morning is.

*(stop. After they send something or skip: silently `start_onboarding_session` with the v2 flag and `force_new`. Confirm identity from work email. Do not narrate.)*

### Turn 3 — notes, now

**Dex:** From your work email: you’re Alex Rivera, at northwind.example — right?

*(They confirm.)*

**Dex:** What do you use to keep meeting notes — Granola, Zoom, Teams, Wispr, a folder of notes, or nowhere yet?

*(They say Granola. Silently: if a Dex key already exists, record `granola` and continue. If the host can see Granola but Dex has no key, say so honestly and walk `/granola-setup` in this sitting. If they already connected it, do not ask for another key.)*

**Dex:** I can use those Granola notes while we talk. If you want them in a morning brief when you’re not here, Dex also needs the key saved — we can do that in a minute if it isn’t already.

### Turn 4 — wait line, then one real question

*(Silently: you read this week, the last three weeks, and the next three weeks. Pass events into first-week analysis if the calendar is not Calendar.app. A company lookup may run in the background. It never speaks.)*

**Dex:** This part can take a minute — I’m reading the last few weeks of your calendar myself. Meanwhile: we’ll pin down who matters, file people and company pages if you want, and finish with your week and one shortcut you can actually use.

I’ve got a helper looking up Northwind in the background so we can keep talking.

What matters most in your role right now?

*(stop. Never “one moment.”)*

### Turn 5 — cadence, then people

**Dex:** From the last three weeks you have a regular 1:1 with Sam Chen, and a weekly product review. Is Sam your manager, or someone you keep close?

*(They say manager.)*

**Dex:** From the last few weeks I can file pages for 14 people and 4 companies. I’ll create all of those now, and keep filing anyone new from your meetings. Sound right?

*(They say yes. Save the preference on the session. After finalize, apply the full returned set — not the shipped five.)*

### Turn 6 — mirror

**Dex:** Here’s what I’ll keep. Tell me if I have this wrong.

- Alex Rivera, product lead at Northwind (northwind.example). Enterprise-sized company — they make workflow software; they sit near the usual work-os tools.
- What matters most: shipping the shared inbox without dropping enterprise renewals.
- Pillars: customer retention, product strategy, team health.
- Quarter: shared inbox in two design partners’ hands.
- Working days: Monday to Friday.
- I’ll talk like a colleague: clear, not stiff.

Save this and build your workspace?

*(They say yes. Silently: `validate_and_save_step` for the remaining required fields, harness confirm if not done, `finalize_onboarding`, preview/apply working context + the real calendar source, entity default + offer. If finalize fails, do not restart the interview.)*

### Turn 7 — wow card

**Dex:** Your week, from the calendar:

- Tuesday 10:00 — 1:1 with Sam
- Wednesday 14:00 — design-partner review
- Thursday is the heavy meeting day (five timed meetings)

From the last three weeks: Sam is the regular 1:1; the partner review slipped a week when you were out.

From what you told me: retention is a pillar, and most of this week’s external time is still discovery, not renewals.

Treat me like a person. Ask what I can do for you — I’ll answer from your role, your company, and what’s signed in.

Which should I make live?

1. **Today’s plan** — recommended. Uses this calendar.
2. **Prep for Sam** — the next 1:1.
3. **A short week view** — same calendar, slightly wider.

Or say you don’t know and I’ll pick.

*(They take 1. Run `/daily-plan` once on the real calendar. Do not invent counts.)*

### Turn 8 — cue cards, then the helping hand

**Dex:** Earlier I said I wouldn’t change anything in your apps. This is the one exception, and only if you want it: a small reminder on your working days for the next two weeks. All-day, marked free. Each one has a prompt for your role. Search for [Dex] if you want them gone.

Yes, add them — or no thanks?

*(They say no. Do not ask again.)*

**Dex:** Your workspace is ready.

**Help:** the Dex Guide is at https://heydex.ai/help — plain English, prompts you can copy.

**Analytics** can save a preference to count things like “ran a daily plan.” Names, notes, and conversations are never part of that. Nothing is sent unless a usage relay is configured. Say “turn off Dex analytics” if you do not want the preference saved.

**If something’s broken or you want to say thanks:** just tell me, or type `/feedback`. I’ll show you the report before anything is sent.

**If things just feel off:** `/dex-doctor` checks what’s working and fixes what it can.

Treat me like a person. Ask what I can do for you.

*(If morning skills still cannot use this calendar, add one line before the helping hand: “When we’re chatting I can use your calendar. For an automatic morning brief we add it to Dex — about two minutes. Want to do that now, or later?”)*

---

## Shortest path

Same person. They skip the review dump, skip cue cards, accept the identity card, accept the page set, and say “you pick” on shortcuts.

Spoken beats they must answer:

1. “Sound good?”
2. Voice / review invite — they say “skip.”
3. “You’re Alex Rivera, at northwind.example — right?”
4. “What do you use to keep meeting notes?”
5. “What matters most right now?” *(asked during the calendar wait)*
6. “Is Sam your manager, or someone you keep close?”
7. “File pages for N people and M companies?”
8. “Save this and build your workspace?”
9. “Which shortcut — or you pick?”
10. “Cue cards?”

That is the shortest honest hour. Do not remove the notes question, the page question, or the mirror. Those are how Dex avoids guessing.

---

## Scenario B — almost nothing signed in

Do not say this is unusual.

### Turn 1

**Dex:** Hey — welcome to Dex. You’re taking the leap, and this is going to be good. I’ll help you keep meetings, people, and follow-ups in one place you own. About fifteen minutes and we’ll have your week in front of you. What’s your name?

*(stop)*

### After the name

**Dex:** Hi Jordan, great to meet you. I’m Dex, your new Chief of Staff.

*(Same voice / review invite. Then the short interview carries the hour.)*

**Dex:** What matters most in your role right now?

*(After they answer, one motivated connect — not a catalogue.)*

**Dex:** To put your actual week in front of you I need a calendar. If your company has already put Calendar inside this chat, switch on the one you want. If you want a morning brief even when you’re not asking, we add it to Dex with `/google-workspace-setup` or, on a Mac, Apple Calendar. About two minutes. Want to do that now?

Then notes, same question as A. Walk only the door they named.

**Wow card without a calendar:** “Here’s the week as you described it.” No invented Thursday. Cue cards are offered only if a calendar can take them; otherwise the same prompts as a short list in the chat.

---

## Branches

Each branch starts from the happy path and names only what changes. If a branch is not listed in the missing brief, it still comes from #621 or from a `main` constraint that v2 must not lie about.

### B1. They refuse calendar and notes

Record calendar `none` and meeting source `none`. Continue. Wow is built from what they said. Do not apologise. Do not invent meetings.

### B2. Non-macOS (no Apple Calendar.app)

Do not show macOS settings copy. If a host Google calendar is signed in, use that for the read and stay honest about persist (see B4). If not, this is Scenario B.

### B3. Apple Calendar listing fails on a Mac

One line: they can grant access in System Settings and retry, or skip. Skip must not block the hour. `/dex-doctor` can confirm later. Do not loop.

### B4. Host calendar works; Dex persist still cannot store Google

This is today’s `main` contract (`calendar source must be Apple Calendar or no calendar`).

Read the calendar in the chat. Show the week. **Do not** say the next working morning’s automatic brief is ready. Use the two-minute honest line. Offer `/google-workspace-setup` only if they want unattended access. Open decision: whether Phase 2 widens persist.

### B5. Granola — app installed, no signed-in host session, no Dex key

Walk `/granola-setup` now. They paste a key that starts with `grn_`. Needs a Granola Business or Enterprise plan. If that settings section is missing: take a folder of notes today. Never `/connect`.

### B6. Granola — signed in on this host, no stored Dex key

Use it while you talk. Say that a morning brief still needs the key saved. Offer `/granola-setup` once. If they skip, record host-only use in the conversation and `granola` on the session only if finalize can honestly persist it; otherwise record `none` and say why.

### B7. Granola — Dex already has a key

Record `granola`. Do not ask for another key.

### B8. Zoom

Walk `/zoom-setup` now. Record `zoom` after it connects.

### B9. Teams

Walk `/ms-teams-setup` now. Record `teams`.

### B10. Wispr

Walk `/wispr-setup` now. Record `wispr`. (#621 script omitted this; `main` already allows the primary.)

### B11. A folder of notes

Ask where the exports live. Record `exported-folder` + that folder. Import in the background. Do not wait.

### B12. Fireflies (or any recorder with no Dex reader)

**Dex:** I can take a folder of those notes today. A direct Fireflies connection is not something Dex can do yet. Where do you keep the exports?

No promised “next time” date. If they have no folder, record `none`.

### B13. Nowhere / “skip” on notes

Record `none`. Ask once more only if they never answered (B14). If they skipped, do not ask again.

### B14. Notes question never answered

A later beat jumped in. Ask once more, gently. Then move on.

### B15. Out of office

After the calendar read, next working morning is the weekday **and** the date they are actually back. Friday plus “out until 6 September” → Monday 7 September, not a bare “Monday.” Before the calendar is read, say “your next working morning,” never a weekday.

### B16. Empty calendar week

Valid. “Your calendar is available, and you have no timed meetings scheduled this week.” Still use the last-three-weeks lookback for cadence if those weeks have timed meetings.

### B17. Calendar read is slow

The wait line in Turn 4, once. Then one real question. If a helper returns “finished” with no findings, read the calendar yourself immediately. Never “one moment.”

### B18. Teammate ping or idle notice while they are writing

Ignore it. Do not reply. Do not dump a “short version.”

### B19. Pages — yes

File the **full last-few-weeks set** returned for this v2 session. Then keep filing new ones. If N is large, say the count and a few names. Never a self-page. Never a year of names.

### B20. Pages — no

Do not create pages. Leave future creation on suggest-first. Do not infer “never.”

### B21. Pages — never (shipped wording) / “don’t suggest these”

Only the shown ids are suppressed. Do not widen to a global off without asking “Want me to just do this automatically from now on?”

### B22. Automatic filing default

Ask after the offer, every time. Yes → `set_entity_creation_default(automatic=true)`. No → `automatic=false`. Do not infer from the page answer.

### B23. Cue cards — yes

Next 10 working days. All-day, free, title prefixed `[Dex]`. Apple via calendar tools only if all-day + free exist. Host calendar write only if that write is real. If write fails: situation + it’s normal + the prompts as a chat list.

### B24. Cue cards — no

Say nothing more about them.

### B25. Cue cards — no calendar to write to

Do not ask the calendar-consent exception. Offer the prompts in chat, or skip.

### B26. Finalize fails

Answers stay on the session. Do not restart the interview. Do not edit Dex files.

**Dex:** Your answers are saved. That’s on me, not you. Close this chat, open the folder again, type `/setup-v2`, and ask me to finish from the mirror. I won’t rebuild the interview.

### B27. Onboarding tools missing / folder not ready

**Dex:** This folder isn’t quite ready yet. That’s on me, not you. Close this chat, run the starter you were given (or open a finished Dex folder), then type `/setup-v2`. I won’t try to fix the folder from here.

Then stop.

### B28. They typed `/setup` instead

Do the shipped questionnaire. Do not redirect to v2. Do not change `FLOW.md`.

### B29. They typed `/setup-v2` on a vault that already has `.onboarding-complete`

Do not wipe them. Offer `/getting-started` or `/reset`. If they explicitly want a rehearsal, say they need a fresh folder.

### B30. New `/setup-v2` after a half-finished v2 sitting

Start fresh. Do not resume yesterday. Exception: they said “finish the close, don’t re-ask.”

### B31. Identity card is wrong

They correct name and domain. Save the correction. Do not guess again.

### B32. No company domain

Explicit opt-out completes Step 4. Everyone routes External. Do not block.

### B33. Email domain missing and they have a company

Stop and get it. Internal vs External routing depends on it. The MCP will refuse finalize without it.

### B34. They volunteer “skip career / skip quarter goals”

Record only that room off. Do not open a rooms questionnaire.

### B35. Harness not yet confirmed

`main` will not finalize without `save_harness_selection(..., confirmed=true)`. After the hello, once tools are allowed: show the capability preview (automatic / on demand / guided / unavailable, plus each host’s named limits). Confirm one or more hosts. Do not make them pick a single “main” assistant. Open decision: exact beat placement.

### B36. Slack / Salesforce / Gong visible on the host

Name them on the hello if they are there. Do not read their content in hour one. Do not offer to connect them.

### B37. They ask to connect something Dex cannot do

Situation + it’s normal + one next step (folder of exports, or “later”). No invented skill.

### B38. They ask you to “just edit the files”

Refuse. Point at `/feedback` or the starter. Same as B26.

### B39. Already-onboarded harness repair

That remains `/setup`’s one narrow repair (`.claude/skills/setup/SKILL.md`). `/setup-v2` does not steal it.

### B40. `/getting-started` during or after

If they want the tour after the wow card, run it. Do not repeat the first-week snapshot as a new discovery.

### B41. Company lookup returns nothing

Omit the marketplace lines. Do not invent competitors.

### B42. Shortcut cannot be run in this sitting

Run the best shipped skill that can. “I’ll have that ready next time” for anything that cannot. Do not create a custom skill unless it can be made **and run** now.

### B43. They are already mid `/setup`

Leave it. v2 does not attach to a shipped session.

---

## What they should feel at the end

They have:

- a workspace that belongs to them
- a week they recognise (or the week they described)
- pages for the people from the last few weeks, if they said yes
- one shortcut that actually ran
- one place to get help, and one way to say something is broken

They do not have:

- a catalogue of tools
- a promise Dex cannot keep tomorrow morning
- a page about themselves
- a stack of unanswered cards

---

## Open decisions (journey)

1. **Command name.** `/setup-v2` (this doc) vs `/setup-preview` vs keeping `/setup-lab`. Recommendation: `/setup-v2`.
2. **Google persist.** Honesty line only, or a real contract change (see the audit).
3. **Harness beat.** In the hello, after the name, or immediately before finalize.
4. **Page cap.** v2 files the last few weeks; shipped `/setup` stays at five. Confirm that split.
5. **Practice starter.** Whether Phase 2 ships a new starter script, or only the skill.
6. **Create-a-skill in hour one.** This journey keeps shelf-first. Confirm before Phase 2 builds a creator path.
7. **Brief gap.** Re-check issue 720 for any branch not listed here.
