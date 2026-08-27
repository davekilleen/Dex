# First-hour onboarding — spec (not shipped)

Status: **preview implemented**. Shipped `/setup` is unchanged. Use `/setup-lab` on a fresh vault.

Audience: non-technical professionals (Doireann is one example, not the template).  
Promise: more useful context than today’s questionnaire, in about **fifteen minutes** of her attention, ending on a real demo of *her* week. Every user-facing clock says fifteen. Do not also say ten, or “the hour.”

This file is the product contract for a **preview / lab** onboarding. Shipped `/setup` stays as it is until the preview is proven.

---

## Onboarding MCP — yes, we use it

The lab hour **uses the existing onboarding MCP** (`core/mcp/onboarding_server.py`). That is the safe door: session, validation, `finalize_onboarding`, working-context preview/apply, person-page offer. Vault files are not written by a side path.

We do **not** invent a second provisioner.

Today’s MCP cannot run this hour unchanged. These limits are why Doireann’s calendar was stored as “none” while Google already worked in the chat:

- `save_calendar_selection` and `preview_confirmed_onboarding_context` accept **Apple Calendar or none**. The tool text says Google is not supported there.
- `validate_and_save_step` forces steps **in order** (name → role → company size → domain → …). A one-card identity confirm will bounce.
- `run_first_week_analysis` reads **Calendar.app**, not a signed-in Google calendar.
- `verify_dependencies` checks Calendar.app and Granola, not host email/calendar.
- `generate_nudge_calendar` builds the old month-long `.ics`, not two weeks of free cue cards.

**Same server, widened for lab** (and later for shipped `/setup` once the preview is proven):

1. Calendar source may be `apple`, `google` (already signed in on this host), or `none`. This change also lives in the lifecycle/transaction layer, not only the MCP tool text — today those layers reject anything but Apple or none. The session/tool argument stays `calendar_source`; the profile field it writes is today’s `calendar`. Persist Apple as `{provider: apple, work_calendar: "<calendar name>"}` (unchanged). Persist Google as `{provider: google, account: "<the signed-in work email>"}`. Daily-plan asks the host for that account’s calendar. `none` stays `{provider: none}`.
2. Relax the “calendar must be addressed before name” gate so Scenario B can ask her name first. A one-card identity confirm may save name + company + email domain + inferred company size without requiring role or calendar first. Role stays a later step.
3. That one confirm still validates email domain. If size cannot be inferred, show a default on the card, tap to change.
4. A new MCP tool, `save_meeting_source`, records the meeting source on the **session** (do not write `user-profile.yaml` by hand before the vault exists — finalize would overwrite it). `finalize_onboarding` then persists `meeting_sources: {primary, notes_folder}` using today’s allowed primaries (`granola`, `zoom`, `teams`, `exported-folder`, `wispr`, `none`).
5. First-week analysis accepts **events the host agent already fetched** (same pattern as `analyze_calendar_capacity(events=[...])`). The Python server cannot call Claude/Codex Google tools itself.
6. Cue-card helper: ten free all-day `[Dex]` events. Apple via calendar-mcp — today’s `calendar_create_event` has no all-day or free/busy flag, so extend that tool. Google via the host agent. If we cannot write, a chat list. The old month-long `.ics` is not this path.
7. A lab marker (`System/.onboarding-lab`) classified in the portable contract like `.onboarding-complete`. Analytics and feedback **actually read** it and mark those events `lab: true`, so beta signal is separable.

The `/setup-lab` skill still starts with `start_onboarding_session`. `finalize_onboarding` + approved working context run **after the interview mirror is approved** (section 4), **before** the wow card (section 5). The vault has to exist for person-page offers and the wow run; that is mid-hour, not the last step.

**Who does the sweep:** the host agent (Claude/Codex/Cursor) lists its own signed-in tools. The MCP cannot see those. Say that in the skill. Background “workers” are subagents started at named beats; they report when they finish — they do not chatter mid-sentence.

**Granola has three states.** Do not collapse them: (a) the Mac app is installed — not enough for Tuesday; (b) Granola is signed in on this host — good for hour one, “when we talk”; (c) a Granola key Dex can store — the only state `/process-meetings` and a morning brief can use unattended. Detect (b) before asking for a key. Ask for the key only when we promise a brief that must work when she is not in the chat.

**Daily-plan rewiring** is additive: route on the recorded profile `calendar` (`provider` + Apple calendar name or Google account). Existing Apple / none users keep today’s behaviour. Google Workspace setup is **email**, not calendar — do not tell her that skill fixes Tuesday’s meetings. The skill text must say “use the calendar tools this session actually has,” not one hardcoded name. Same preview branch is fine; this wiring must land **before** any lab user sees the hour.

---

## P0 to connect: email, calendar, meeting notes

Hour one only chases **three** things. Everything else (Slack, Salesforce, Gong) can be named and left for later.

| Need | How we detect | If missing |
|---|---|---|
| **Email** | Host Gmail / Google Workspace / Apple Mail already signed in | Company door or `/google-workspace-setup` / Apple Mail, after she says what matters |
| **Calendar** | Host Google Calendar, or Calendar.app | Same — this is what makes “her week” real |
| **Meeting notes** | Granola already signed in on the host, or a Granola key, or another recorder Dex can actually read (Zoom / Teams / a folder of notes) | Ask what she uses **now** (Granola, Fireflies, Zoom, Teams, a folder, nowhere). If Granola, walk `/granola-setup` in this hour. Fireflies has no door today — take a folder of notes, and say the direct connection is next time |

Detect Granola **before** asking for a key. If it is already there, do not make her paste one.

**Daily plan must use that calendar.** Today `/daily-plan` and `/meeting-prep` read Dex’s own `calendar-mcp` (Calendar.app) and only treat email as connected when `google-workspace.enabled` is true. That is the Doireann bug: first hour can use Google; Tuesday morning cannot. Fixing that wiring is **part of this work**, not a follow-up. Until it is fixed, we do not tell her the morning brief is ready.

---

## What we are not doing

- Not replacing everyone’s `/setup` on day one.
- Not advertising `/connect` (that door is held and not shipped).
- Not reading Slack / Salesforce / Gong *content* before she says yes.
- Not creating a page for the user themselves.
- Not offering 366 people pages in hour one.
- Not saying “I can’t see your calendar,” “connector,” “tools are on,” “cron,” or “sync failed.”
- Not editing Dex source in the user’s vault to recover from a crash.
- Not asking her to connect Slack or Salesforce in hour one.

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
2. **Email + calendar** (so we can show her week and know who she is).
3. **Meeting notes — in this hour, not later.** Ask what she uses. If Granola, walk `/granola-setup` now (key in chat). If Fireflies, take a folder of notes today. If Zoom or Teams, walk that setup now.
4. Everything else later.

Two honest doors (never `/connect`):

- **Company door:** “If your company has already put Calendar or Slack inside Claude or Codex, you can switch on the one you want me to use. I can use it while we talk.”
- **Dex door:** the real setup skills (`/granola-setup`, `/google-workspace-setup`, Apple calendar permission on a Mac). “If you want this in a morning brief even when you’re not asking, we add it to Dex. About two minutes.”

Until something is connected, the wow is built from **what she told us**, including last year’s review if she has it to hand in this hour. Do not invent a busy Thursday.

---

## Background workers (silent)

They never speak in the chat. They write only **staged suggestions**. They stop when the interview ends. Whatever is not ready is not shown.

| Worker | When it starts | Reads | Produces |
|---|---|---|---|
| Sweeper | Second zero | Which apps are signed in; her own work-email identity | Recognition card |
| Week reader | After notes are named, and calendar is allowed | This week + the last **three weeks** of calendar; recent meeting notes once a source exists | Week snapshot, regular cadence (1:1s, recurring), working-week guess, possible manager to ask about |
| People mapper | After week reader has three weeks of meetings | Attendees; exclude her confirmed email; clean names | At most 5 people, no self-page; then the auto-file people/company question |
| Wow agent | After pillars exist | Her answers + week/notes only in hour one | The closing card: how to use Dex, 2–3 pillar-tied insights, 3 shortcut choices |

Hard timeout at interview end. Salesforce/Gong content is **not** hour-one fuel unless she later gives a second yes (default: session two).

---

## The hour (what she hears)

Copy must say what is happening, why, and what she can do next. Failure copy: situation + it’s normal + one choice.

### 1. Welcome + consent (A) or welcome + name (B)

The first thing she hears is a hello — warm, a little excited, fifteen minutes, what Dex is great at. Look for her name silently first. Do not narrate looking, installing, or “checking what’s configured.”

**A:** “Hey [first name] — welcome to Dex. You’re taking the leap, and this is going to be good. For the next fifteen minutes I’ll help you keep meetings, people, and follow-ups in one place you own. I can already see [app names]. I’d like to read your calendar and meeting notes so I can organise your week. I won’t change anything in those apps. Sound good?”

First identity card uses **email only**: “From your work email: you’re Doireann Marron, at Pendo. Right?” Job title waits until after consent.

**B:** “Hey — welcome to Dex. You’re taking the leap, and this is going to be good. I’ll help you keep meetings, people, and follow-ups in one place you own. About fifteen minutes and we’ll have your week in front of you. What’s your name?” Then the short interview. Connect calendar after she names what matters.

### 2. Voice and last year’s review (after she answers the hello)

This is a spoken conversation, not a stack of tap-cards. One question at a time.

Invite her to hold the microphone in Claude or Codex and dump as much as she can — how she works, who matters, what this quarter is for. If she has last year’s review to hand, ask her to paste it or drop the file in. Do not invent a `/voice` command.

### 3. Meeting notes — now, not later

Ask what she uses: Granola, Fireflies, Zoom, Teams, a folder of notes, or nowhere. Then walk that door **in this hour**.

- Granola already signed in on this host: use it, record it, do not ask for a key.
- Granola and we need a stored key: walk `/granola-setup` now. She pastes the key in chat.
- Fireflies: no direct door today. Take a folder of those notes. Say the direct connection is next time.
- Zoom / Teams: walk that setup now.
- Nowhere: record `none` and keep going.

Record `meeting_sources` the moment she connects, or later skills forget. Do not say “we can do Granola in two minutes at the end.”

### 4. Short interview (context we keep)

Keep as real spoken questions — **role-agnostic**. Look at **three weeks** of meetings first. Find regular cadence. Guess a manager or people she keeps close, then ask — do not state it as fact.

- Role (guess if we have a title *after* consent; else ask; keep hybrid free text).
- What matters most right now (`role_focus` — this must **feed** draft pillars and goals, not die in the profile).
- 2–3 themes / pillars (with calendar evidence if we have it; always allow a theme that owns no calendar time).
- Quarter outcome (confirm a draft if the gold line already named it).
- Up to five people **and who they are to her**. Then: “Would you like me to automatically file and create people and company pages from your meetings?”
- Anything a calendar would miss, plus the review if she brought it.

Confirm, don’t quiz:

- Company + email domain (from work email).
- Company size (infer, show, tap to fix — nothing in the product branches on it today).
- Working days (“Monday to Friday — right?”).
- How Dex should talk (one line with a default). Career level stays visible — it sets coaching voice.

Workspace is created after this mirror is approved. Nothing important is written before that yes.

### 5. The wow card (one screen)

Three beats, then one ask:

1. **Her week** — this week’s meetings if we have a calendar, plus two or three cadence insights from the last three weeks; otherwise “here’s the week as you described it.”
2. **Insights tied to *her* pillars** — two or three, each with a source clause (“from your calendar this week” / “from what you told me”). Never invented counts.
3. **How to use Dex** — not a catalogue. One line: “Treat me like a person. Ask what I can do for you — I’ll answer from your role, your company, and what’s signed in. You can say that any time: ‘what can you do for me?’”

Then shortcuts — **not CS-specific**:

- Look at the shelf for *this* role and *these* apps. The shelf is **shipped skills plus contract-declared rooms** (today: career, companies, quarter goals). Role packs under `_available` are not rooms until they are declared — do not copy them into the vault by hand. Until then, the create-a-skill path covers a role-specific want.
- If a shipped skill would make her sit up **and** use her signed-in apps together, recommend that.
- If the shelf is dull for her mix, **create one** from what we gleaned + what’s signed in — only if it can be made and **run** in this session. Otherwise: “I’ll have that ready next time,” and still run the best shelf skill now.
- Always show **three** choices, recommend one: “Which should I make live? Or say you don’t know and I’ll pick.”
- Create or switch on **one**. **Run it once on her real work** (or on the story she told us, in Scenario B).
- Then: “Anytime you want another, just say so. If you’re not sure, say you don’t know — I’ll watch how you work and come back with a couple of ideas. A morning routine, a meeting brief, something that quietly runs while you’re away.”

### 6. Optional cue cards (two weeks)

Ask once. Skip if she says no. Do not ask again.

“Earlier I said I wouldn’t change anything in your apps. This is the one exception, and only if you want it: a small reminder on your calendar, on your working days, for the next two weeks. All-day, marked **free** — they never make you look busy. Each one has a prompt written for *your* role. They’re cue cards, not meetings. Search for [Dex] if you want them gone.”

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

In Scenario A, if morning skills still cannot use the company calendar, add one honest line before this: “When we’re chatting I can use your calendar. For an automatic morning brief we add it to Dex — about two minutes. Want to do that now, or later?”

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
| Calendar source | Record the **real** source on profile `calendar` (Google account, Apple calendar name, or none). Morning skills must be able to use what we claimed, or copy stays scoped to “when we talk.” |
| Meeting source | `save_meeting_source` on the session at connect time; finalize writes `meeting_sources`. |
| Person pages | Max 5, cleaned, never her; ask whether to auto-file people and company pages; then auto-vs-suggest. |
| Annual review | Ask in this hour if she has last year’s to hand. |
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

That script (when written) should: create or use a practice folder, finish the behind-the-scenes setup **before anyone opens the chat** (the small Python folder plus the file that points Claude at Dex’s helpers), drop in only the lab skill + this spec, and print “type `/setup-lab`”. If that setup is skipped, the first message has nothing to talk to and the agent starts explaining machinery instead of saying hello. It must **not** patch `onboarding.md` for existing users. The agent must not run that install from inside `/setup-lab`.

Empty-connector testing is mandatory: run Scenario B on a machine/account with company apps off, and prove the connect-at-the-right-time copy.

---

## Prerequisites (before any user sees this hour)

1. Finalize must not crash on Apple’s default Python 3.9. This ships to **everyone** — “don’t replace `/setup`” does not block the crash fix.
2. Getting-started date bug must not crash the tour (`datetime.fromisoformat` on meeting dates in `.claude/skills/getting-started/SKILL.md`).
3. An agent must not edit Dex source in the user’s vault to recover.
4. `/daily-plan` and `/meeting-prep` must read the same calendar and meeting source onboarding just recorded (host Google and Granola included). If they cannot, the first hour must not claim tomorrow’s brief is ready.
5. Granola is detected if already signed in; we do not ask for a key we already have.

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
- Use the existing onboarding MCP; widen it — do not bypass it.
- Hour-one connects are email, calendar, and her meeting notes. Ask what she uses. Walk Granola now if that is the answer.
- Look at three weeks of meetings. Find cadence. Ask about automatic people and company pages.
- Invite voice and last year’s review in this hour.
- Daily plan uses that same calendar. That fix ships with the preview.
