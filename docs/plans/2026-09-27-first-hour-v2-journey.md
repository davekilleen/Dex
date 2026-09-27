# First Hour v2 — journey

**Status:** Phase 2 product contract. Implements the pasted brief.  
**Date:** 2026-09-27  
**Command:** `/setup-v2`  
**Shipped default:** `/setup` (unchanged)  
**How to try it:** type `/setup-v2` in a fresh Dex folder. There is no separate starter.

This is what the person hears. Tool names stay in stage directions. They never appear in the spoken lines.

Success: they think “Dex already understands an extraordinary amount about my working world, and I barely had to configure anything.”

---

## Command

**Name:** `/setup-v2` (settled)

Router description:

> Meet Dex as your new Chief of Staff and get a working Dex from your week, not a questionnaire. Use when the user says `/setup-v2`, `try the new first hour`, or `preview setup`. Not for everyone’s shipped first setup; use `setup`. Not for the post-setup tour; use `getting-started`. Not for a mid-life role change; use `reset`.

---

## Progressive value (the hour is not a wizard)

Demonstrate before configuring. Infer, propose, confirm. Every expensive step earns its time. The person can stop as soon as Dex is useful.

| Elapsed | What they have | They may stop? |
|---|---|---|
| **~2 min** | They know what Dex is. They have been greeted by name. | Yes — but offer to continue. |
| **~5–10 min** | Dex has enough to be useful: who they are, what matters, a workspace, and one real output (their week, or the week they described). | **Yes. This is the clean stop.** |
| **~15–30 min** | Deeper enrichment: meeting cadence, people and companies proposed (not silently filed), optional integrations, one shelf skill run. | Yes. |
| **First hour and after** | Normal Dex. Oriented to real people, commitments, and goals. | — |

Do not drag them through 15–30 minutes to reach a working Dex. The happy path ends at the 5–10 minute stop. Longer enrichment is an offer, not a gate.

---

## Settled decisions

1. Command is `/setup-v2`.
2. Google persist stays Apple or none. If a host Google calendar is readable in the chat, show the week and stay honest: an automatic morning brief still needs `/google-workspace-setup`. The shared “refuses Google calendar” test stays green.
3. Harness confirm happens early and quietly, before finalize. No extra spoken beat. After the first answer, inspect and save in the background; only speak if nothing could be confirmed.
4. People from the last few weeks may be offered only through a **v2-only** parameter. Shipped `/setup` stays at five. That cap test stays green.
5. No practice starter. Type `/setup-v2` in a fresh folder.
6. Shelf-first only. Do not create a skill in hour one.
7. Notes and recorders are not a gate. None / skip / unavailable → continue.
8. Source-doc invite is optional, with a warm “I don’t have one / not now” path.
9. Resume an in-progress `/setup-v2`. Start fresh only if they ask. A finished vault is not wiped.

---

## Rules that apply to every path

- First visible text is a hello. **Zero tools on that turn.**
- One question, then wait. Background helper messages are never treated as their answer.
- Never fill dead air with “one moment,” “nearly there,” or “still reading.”
- Never name host products, models, or vendors.
- Never say: connector, MCP, vault, permission, sync failed, cron, `/connect`.
- Never invent a door Dex does not have.
- Never silently persist an inference. Evidence vs guess is said out loud. Writes go through confirmation, then `onboarding-mcp` → lifecycle.
- Never claim a morning brief is ready unless morning skills can read the same calendar just stored.
- Never create a page for the person themselves.
- Email domain is still mandatory underneath (or an explicit “I don’t have one”).
- No dead ends: missing calendar, recorder, source doc, domain, or integration still finishes a working Dex.
- If the onboarding tools are missing: one honest line, stop. Do not install from the chat.

---

## The beats (what the hour is made of)

Order is flexible when a skip happens. Do not skip the 5–10 minute stop.

1. **Opening** — hello, what Dex is, consent or name.
2. **Calendar moment** — read if we can; skip if we cannot. Not a gate.
3. **Identity** — confirm from work email, or ask. Correctable.
4. **Role / context** — what matters most right now. Infer a role if we have evidence; confirm it.
5. **Optional source doc** — annual or performance review, job spec, career ladder, or a public-profile extract. “I don’t have one / not now” is a great answer.
6. **Meeting intelligence** — only if a calendar or notes exist. Recurring meetings, people, themes. Label evidence vs inference.
7. **People / company discovery** — “Here are the people and companies I found. Shall I create these?” Never silent.
8. **Pillars** — propose from what they said and any calendar evidence; they edit; then save.
9. **Integrations** — only the one that would change the next result, and only if they want it. Not a catalogue.
10. **First useful output** — their week, or the week they described. Then the clean stop.
11. **Transition** — helping hand, then normal Dex (`/daily-plan`, `/getting-started` if they want more).

Harness confirm is silent machinery around beats 2–4, not its own question.

---

## Happy path (remarkably simple)

They have a readable calendar. They skip the source doc. They skip notes. They stop at 5–10 minutes. Names are generic.

### ~2 minutes — opening

**Dex:** Hey — welcome to Dex. I’m your new Chief of Staff. I help you keep meetings, people, and follow-ups in one place you own. About two minutes to say hello, then I’ll use your week if I can. What’s your name?

*(stop. Zero tools.)*

**They:** Alex.

**Dex:** Hi Alex, great to meet you. I’m Dex, your new Chief of Staff.

*(After this message they may already feel they understand Dex. Offer to continue; do not require it.)*

### Calendar moment + identity (still inside 5–10)

*(Silently: `start_onboarding_session(v2=true)` — resume if a v2 session exists, otherwise new. Address calendar: list Apple calendars, or skip. Harness inspect + save, quiet. Do not narrate.)*

**Dex:** I’d like to read your calendar so I can organise this week. I won’t change anything there. Which work calendar should I use — or say skip?

*(They pick one. Or skip — see Branch: calendar unavailable.)*

**Dex:** From that calendar you’re Alex Rivera, at northwind.example — right?

*(They say yes. If wrong, they correct. Nothing inferred is saved until this yes.)*

### Role / context + source doc

**Dex:** What matters most in your role right now?

*(They answer. If talking is easier and the host has a microphone, they may hold it. Do not invent a `/voice` command.)*

**Dex:** If you have last year’s review, your job spec, your career ladder, or a saved extract of your public profile, paste it in. If you don’t have one, or not now — that’s completely fine. We’ll keep going from what you just told me.

*(They say “not now.” Warm. Continue. See Branch: no source doc.)*

### Pillars + workspace + first useful output (the clean stop)

*(Silently: skip calendar is already recorded, or Apple selection is held for later apply. `validate_and_save_step` for name, a role from their words, company size inferred and shown, email domain, 2–3 proposed pillars, default communication, working week from calendar or Mon–Fri. Rooms stay on. `finalize_onboarding`. Preview/apply working context with the real `calendar_source` — Apple or none, never a silent Google persist. Then `run_first_week_analysis`. If the calendar is not Calendar.app, pass host-fetched events into that call; do not pretend they were stored as the Dex calendar.)*

**Dex:** Here’s what I’ll keep. Tell me if I have this wrong.

- Alex Rivera at Northwind (northwind.example)
- What matters: shipping the shared inbox without dropping renewals
- Pillars I’ll use: customer retention, product strategy, team health
- Working days: Monday to Friday

Save this and I’ll put your week in front of you?

*(They say yes.)*

**Dex:** Your workspace is ready. This week, from your calendar:

- Tuesday 10:00 — 1:1 with Sam
- Wednesday 14:00 — design-partner review
- Thursday is the heavy day (five timed meetings)

Your next working morning is Tuesday, 29 September.

Treat me like a person. Ask what I can do for you.

That’s enough to start. We can stop here — Dex is working. If you have another ten minutes I can look at the last few weeks, propose people and company pages, and run one shortcut. Want to continue, or stop?

*(They stop. Helping hand, once. This is a successful first hour.)*

**Dex:** **Help:** https://heydex.ai/help

**Analytics** can save a preference to count things like “ran a daily plan.” Names, notes, and conversations are never part of that. Nothing is sent unless a usage relay is configured. Say “turn off Dex analytics” if you do not want the preference saved.

**If something’s broken:** just tell me, or type `/feedback`. **If things feel off:** `/dex-doctor`.

---

## The six required branches

### 1. Calendar unavailable

Apple Calendar.app missing, listing failed, non-macOS, or they said skip.

Record `save_calendar_selection(skipped=true)`. Continue. Identity is asked, not guessed from a calendar. First useful output is “the week as you described it.” No invented Thursday. Do not claim an automatic morning brief. Next working morning uses the working week only (weekends skipped; no OOO data).

If a host Google calendar is readable in the chat: show that week as **evidence in this sitting**, and say plainly that Dex has not stored it for mornings. Offer `/google-workspace-setup` once, later, if they want the brief when they are away.

### 2. No meeting notes

They have no recorder, they skip, or the named recorder has no Dex door.

**Dex:** What do you use to keep meeting notes — Granola, Zoom, Teams, Wispr, a folder, or nowhere yet?

- Named door Dex has → walk that setup **only if they want**. Skip is fine.
- Named door Dex does not have (e.g. Fireflies) → folder of exports, or continue. No invented connection.
- Nowhere / skip / never answered after one gentle retry → record `none`. Continue.

Notes are never a gate. The 5–10 minute stop still happens.

### 3. No source doc

They say “I don’t have one,” “not now,” or send nothing after the invite.

**Dex:** That’s completely fine — we’ll use what you already told me.

Do not ask again in this sitting. Do not make the hour feel poorer. Source-doc content, when present, is used as **evidence** in the mirror (“from the review you pasted”) and never silently copied into the profile beyond the fields they confirm.

### 4. Shortest setup (the happy path)

Name → Chief of Staff greeting → calendar or skip → identity confirm → what matters → source doc declined → proposed pillars → save → week (or described week) → **stop**.

They are not asked for pages, integrations, or a shortcut. Those belong to longer enrichment.

### 5. Longer enrichment (15–30 minutes)

Only after they say they want to continue past the clean stop.

1. **Meeting intelligence.** You read this week, the last three weeks, and the next three weeks. Recurring 1:1s, themes, possible manager — asked, not stated as fact. Label “from your calendar” vs “from what you told me.”
2. **People / companies.** “Here are the people and companies I found from the last few weeks. Shall I create these?” Yes files the **v2** returned set. No files none. Shipped `/setup` still offers five.
3. **Integrations.** At most one motivated ask (the recorder or calendar that would change the next result). Not a catalogue. Never `/connect`.
4. **One shelf skill.** Recommend `/daily-plan` if a calendar exists, else `/getting-started`. Run it once on real work or on their story. Do not create a skill.
5. Optional cue cards only if a writable calendar exists; skip if not. Ask once.

Then the same helping hand and transition to normal Dex.

### 6. Returning / resume

`start_onboarding_session(v2=true)` **without** `force_new` unless they asked to start over.

- **In-progress v2 session:** show progress in one line. “We were about to save your workspace — pick up there, or start fresh?” Resume is the default if they just say hello.
- **Finished vault** (`.onboarding-complete` exists): do not wipe. Offer `/getting-started` or `/reset`. Rehearsal needs a fresh folder.
- **Mid shipped `/setup`:** leave it. `/setup-v2` does not attach to that session.
- **Crashed finalize:** answers stay on the session. “Your answers are saved. Type `/setup-v2` and ask me to finish from the mirror.” Do not rebuild the interview. Do not edit Dex files.

---

## Other safety branches (short)

These must not dead-end the hour.

| Situation | What happens |
|---|---|
| Identity wrong | They correct. Save the correction. Do not guess again. |
| No company domain | Explicit opt-out. Everyone External. Continue. |
| Company domain missing and they have a company | Get it. Finalize still requires it. |
| Out of office on the calendar | Next working morning = weekday **and** date they are actually back. Never a bare “Monday.” Before any calendar read, say “your next working morning.” |
| Empty calendar week | Valid. Say so. Still use lookback if those weeks have timed meetings. |
| Slow calendar read | One factual line, then a real question. Never “one moment.” If a helper finishes with no findings, read the calendar yourself. |
| Helper / teammate ping while they write | Ignore. Not an answer. |
| They volunteer skip career / quarter goals | Record only that room off. No rooms questionnaire. |
| Slack / Salesforce / Gong visible | May be named. Content not read. Not offered. |
| They ask for a door Dex lacks | Situation + it’s normal + folder or later. |
| “Just edit the files” | Refuse. `/feedback` or resume from the mirror. |
| Already-onboarded harness repair | Stays on `/setup`. `/setup-v2` does not steal it. |
| They typed `/setup` | Shipped questionnaire. No redirect. |
| Onboarding tools missing | One line, stop. No install from chat. |
| Host Google calendar only | Show week in chat. Do not persist Google. Honest morning-brief line. |
| Company lookup empty | Omit marketplace colour. Do not invent competitors. |
| Automatic filing default | Asked only during longer enrichment, after the page offer. Not inferred. |

---

## Next working morning

After a calendar is read (Apple, or host events passed into analysis):

- Use their working week (default Monday–Friday).
- Skip weekends and any all-day out-of-office / holiday on that calendar.
- Speak a **weekday and a date** (“Tuesday, 29 September”).
- Never hardcode a weekday. Never a bare Monday.

With no calendar: next working day from today + working week only. Still a weekday and a date.

---

## What they should feel at the 5–10 minute stop

They have:

- been greeted like a person
- a workspace that belongs to them
- a week they recognise, or the week they described
- pillars they confirmed, not a quiz they failed
- permission to stop

They do not have:

- a catalogue of tools
- a promise Dex cannot keep tomorrow morning
- silently created people pages
- a stack of unanswered cards
- a sense that they “didn’t finish setup”

---

## What Phase 2 must not reopen

- Widening the shared Google persist contract
- Changing shipped `/setup`, `FLOW.md`, the compatibility copy, hooks, or shared tool defaults
- A practice-folder starter
- Auto-creating skills
- Treating notes, calendar, source doc, or integrations as gates
