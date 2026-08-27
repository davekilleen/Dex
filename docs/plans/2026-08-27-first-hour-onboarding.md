# First-hour onboarding — spec (not shipped)

Status: **draft for founder approval**. Do not change shipped `/setup` until a lab/preview path exists and this spec is approved.

Audience: non-technical professionals (Doireann is one example, not the template).  
Promise: more useful context than today’s questionnaire, in about 15–20 minutes of her attention, ending on a real demo of *her* week.

This file is the product contract for a **preview / lab** onboarding. Shipped `/setup` stays as it is until the preview is proven.

---

## What we are not doing

- Not replacing everyone’s `/setup` on day one.
- Not advertising `/connect` (that door is held and not shipped).
- Not reading Slack / Salesforce / Gong *content* before she says yes.
- Not creating a page for the user themselves.
- Not offering 366 people pages in hour one.
- Not saying “I can’t see your calendar,” “connector,” “tools are on,” “cron,” or “sync failed.”
- Not editing Dex source in the user’s vault to recover from a crash.

---

## Two first-class scenarios

Onboarding has **two designed hours**, not a happy path and a shrug.

### Scenario A — apps already signed in

The host (Claude or Codex) already has work apps available: typically a calendar, mail, Slack, meeting notes (Granola), sometimes Salesforce or Gong.

Sweep those **names** at second zero. Confirm identity from her **work email** only on the first card. After one consent line, read **calendar + meeting notes**. Other apps are named, not opened, until she asks or a later session.

### Scenario B — almost nothing signed in

Personal machine, no company Claude/Codex apps, or only one thin app.

Do **not** say that is unusual. The interview carries the hour. Connect the **one** missing source at the moment it would change the next result, tied to what she just said matters — not a catalogue at the start.

Right time to connect:

1. After “what matters most right now” — so the ask has a reason.
2. Calendar first (so we can show her week).
3. Meeting notes second (Granola key in chat is fine, or a folder of exported notes).
4. Everything else later.

Two honest doors (never `/connect`):

- **Company door:** “If your company has already put Calendar or Slack inside Claude or Codex, you can switch on the one you want me to use. I can use it while we talk.”
- **Dex door:** the real setup skills (`/granola-setup`, `/google-workspace-setup`, Apple calendar permission on a Mac). “If you want this in a morning brief even when you’re not asking, we add it to Dex. About two minutes.”

Until something is connected, the wow is built from **what she told us** (and an optional annual review next session). Do not invent a busy Thursday.

---

## Background workers (silent)

They never speak in the chat. They write only **staged suggestions**. They stop when the interview ends. Whatever is not ready is not shown.

| Worker | When it starts | Reads | Produces |
|---|---|---|---|
| Sweeper | Second zero | Which apps are signed in; her own work-email identity | Recognition card |
| Week reader | After consent (A) or after calendar connects (B) | This week + last 4 weeks of calendar; recent meeting notes once a source exists | Week snapshot, busiest day, working-week guess |
| People mapper | After week reader has people | Attendees; exclude her confirmed email; clean names | At most 5 people, no self-page |
| Wow agent | After pillars exist | Her answers + week/notes only in hour one | The closing card: how to use Dex, 2–3 pillar-tied insights, 3 shortcut choices |

Hard timeout at interview end. Salesforce/Gong content is **not** hour-one fuel unless she later gives a second yes (default: session two).

---

## The hour (what she hears)

Copy must say what is happening, why, and what she can do next. Failure copy: situation + it’s normal + one choice.

### 1. Welcome + consent (A) or welcome + name (B)

**A:** “Hi [first name if we have it from the email]. Your work calendar, Slack, Granola, and Salesforce are already signed in here. For the next ten minutes I’d like to read your calendar and meeting notes so I can organise your week. I won’t change anything in those apps. Is that okay?”

First identity card uses **email only**: “From your work email: you’re Doireann Marron, at Pendo. Right?” Job title waits until after consent.

**B:** “Hi — I’m Dex. I’ll help you keep meetings, people, and follow-ups in one place you own. What’s your name?” Then the short interview. Connect calendar after she names what matters.

### 2. Early meeting notes (when a source exists or she wants one)

Granola key in chat is allowed. Record `meeting_sources` the moment she connects, or later skills forget.

### 3. Offer voice

“You can type or talk — `/voice` if talking is easier.”

### 4. Short interview (context we keep)

Keep as real questions or one-tap confirms — **role-agnostic**:

- Role (guess if we have a title *after* consent; else ask; keep hybrid free text).
- What matters most right now (`role_focus` — this must **feed** draft pillars and goals, not die in the profile).
- 2–3 themes / pillars (with calendar evidence if we have it; always allow a theme that owns no calendar time).
- Quarter outcome (confirm a draft if the gold line already named it).
- Up to five people **and who they are to her** (manager cannot be inferred).
- Anything a calendar would miss.

Confirm, don’t quiz:

- Company + email domain (from work email).
- Company size (infer, show, tap to fix — nothing in the product branches on it today).
- Working days (“Monday to Friday — right?”).
- How Dex should talk (one line with a default). Career level stays visible — it sets coaching voice.

Workspace is created after this mirror is approved. Nothing important is written before that yes.

### 5. The wow card (one screen)

Three beats, then one ask:

1. **Her week** — real meetings if we have a calendar; otherwise “here’s the week as you described it.”
2. **Insights tied to *her* pillars** — two or three, each with a source clause (“from your calendar this week” / “from what you told me”). Never invented counts.
3. **How to use Dex** — not a catalogue. One line: “Treat me like a person. Ask what I can do for you — I’ll answer from your role, your company, and what’s signed in. You can say that any time: ‘what can you do for me?’”

Then shortcuts — **not CS-specific**:

- Look at the shelf for *this* role and *these* apps.
- If a shipped skill would make her sit up **and** use her signed-in apps together, recommend that.
- If the shelf is dull for her mix, **create one** from what we gleaned + what’s signed in.
- Always show **three** choices, recommend one: “Which should I make live? Or say you don’t know and I’ll pick.”
- Create or switch on **one**. **Run it once on her real work** (or on the story she told us, in Scenario B).
- Then: “Anytime you want another, just say so. If you’re not sure, say you don’t know — I’ll watch how you work and come back with a couple of ideas. A morning routine, a meeting brief, something that quietly runs while you’re away.”

### 6. Optional cue cards (two weeks)

Ask once. Skip if she says no. Do not ask again.

“Want a small reminder on your calendar, Monday to Friday, for the next two weeks? All-day, marked **free** — they never make you look busy. Each one has a prompt written for *your* role and what’s in front of you. They’re cue cards, not meetings. Search for [Dex] if you want them gone.”

Rules:

- Next **10 working days** only (her working week, default Mon–Fri).
- All-day, **free / available**, private if the host allows.
- Title prefixed `[Dex]`. Description = one tailored prompt + “just ask me in your own words.”
- Do **not** promise a separate calendar she can delete in one tap unless that host can actually create one. On Google-via-chat, events go on the calendar we can write to, marked free, easy to search-delete.
- If we cannot write to her calendar, say so in the three-beat failure pattern and offer the same prompts as a short list in the chat instead.

### 7. Helping hand (one breath, not four speeches)

Say this once, then stop talking:

“Your workspace is ready.

**Help:** the Dex Guide is at https://heydex.ai/help — plain English, prompts you can copy.

**Analytics** is on. It only records things like ‘ran a daily plan’ — never your notes, names, or conversations. It helps Dave make Dex better for everyone. Say ‘turn off Dex analytics’ anytime.

**If something’s broken or you want to say thanks:** just tell me, or type `/feedback`. I’ll show you the report before anything is sent. When it’s fixed, I’ll tell you. Ask me how your feedback is doing anytime.

**If things just feel off:** `/dex-doctor` checks what’s working and fixes what it can.

Treat me like a person. Ask what I can do for you.”

In Scenario A, if morning skills still cannot use the company calendar, add one honest line before this: “When we’re chatting I can use your calendar. For an automatic morning brief we add it to Dex — about three minutes. Want to do that now, or later?”

---

## Context ledger (nothing important is dropped)

| Today’s field | How the new hour gets it |
|---|---|
| Name | Confirm from work email (A) or ask (B). Keep surname. |
| Role | Ask or confirm. Hybrids stay free text. |
| Company | Confirm from domain. |
| Company size | Infer, show, tap to fix. |
| Email domain | Confirm. Still mandatory underneath (Internal vs External). |
| Pillars | Asked, with evidence if we have it. |
| Formality / directness | One default line in the mirror. |
| Career level | Kept visible (coaching voice). |
| Obsidian | Session two / `/dex-obsidian-setup`. |
| Working week | Confirm from calendar or default. |
| Rooms | On by default; one line, no question. |
| role_focus | Gold question; **must feed** pillars/goals. |
| current_work | Infer + confirm; question 3 catches gaps. |
| week_success | `/week-plan` asks when it is used. |
| quarter_outcome | Confirm a draft in the mirror. |
| key_people + relationship | Names from meetings or her list; **relationship asked**. |
| anything_else | Mirror close. |
| Calendar source | Record the **real** source (company Google, Apple, or none). Morning skills must be able to use what we claimed, or copy stays scoped to “when we talk.” |
| Meeting source | Written at connect time. |
| Person pages | Max 5, cleaned, never her; then auto-vs-suggest. |
| Analytics notice | Helping-hand card. |
| Feedback + doctor + help | Helping-hand card. |
| Nudge calendar | Replaced by optional 2-week free cue cards, tailored. |
| Getting-started / 366 backfill | Next session; this week only in hour one. |

---

## Lab / preview (so Dave can beta without shipping)

Shipped `/setup` and `.claude/flows/onboarding.md` stay untouched until the preview is signed off.

Preview entry (to implement after this spec is approved):

- A **side skill** (working name `/setup-lab`) that follows **this file**, not the shipped flow.
- A vault marker such as `System/.onboarding-lab` so a lab vault cannot be mistaken for a completed production setup.
- A one-line installer for a **fresh** vault, something like:

```bash
curl -fsSL https://heydex.ai/lab-onboarding.sh | bash
```

That script (when written) should: create or use a throwaway folder, install Dex as today, drop in only the lab skill + this spec, and print “type `/setup-lab`”. It must **not** patch `onboarding.md` for existing users.

Empty-connector testing is mandatory: run Scenario B on a machine/account with company apps off, and prove the connect-at-the-right-time copy.

---

## Prerequisites (before any user sees this hour)

1. Finalize must not crash on Apple’s default Python 3.9.
2. Getting-started date bug must not crash the tour.
3. An agent must not edit Dex source in the user’s vault to recover.
4. Morning skills and the first-hour calendar story must not contradict each other.

---

## Acceptance (preview)

- Scenario A: identity confirmed from email; week shown from a real calendar; wow card has week + pillar insights + three shortcuts; one shortcut runs on her work; helping hand said once.
- Scenario B: no “unusual” language; one motivated connect ask; wow still happens from her words; cue cards offered only if a calendar can take them (else prompts in chat).
- No `/connect` in user-facing copy.
- No self person-page.
- Optional cue cards: 10 free all-day `[Dex]` events, tailored, skippable.
- `/feedback` and `/dex-doctor` named once, with “ask me the status anytime.”
- Analytics default-on + the exact opt-out phrase.

---

## Founder calls already taken in this spec

- Ending is week + pillars + insights + shortcuts, then “just ask me.”
- Shelf first; **create** a skill if nothing on the shelf would wow *this* person with *these* apps.
- Cue cards optional, two weeks, working days, marked free.
- Help, analytics, feedback, doctor as one helping hand.
- Empty-apps path is first-class.
- Preview first; do not ship over everyone’s `/setup`.
