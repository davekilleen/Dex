
# Changelog

All notable changes to Dex will be documented in this file.

**For users:** Each entry explains what was frustrating before, what's different now, and why you'll care.

---

## [1.73.0] — ✅ Every suggested connection gets its own yes or no (2026-07-24)

Last release Dex started spotting connections between the people you know and offering them as suggestions. There was a rough edge worth fixing quickly: the moment you confirmed one connection on someone's page, Dex quietly stopped offering *new* ones for that person — and a suggestion you'd dismissed could later drift back. This tidies both.

**What this fixes for you:**

* **Confirming one connection no longer silences the rest.** Each suggested connection is handled on its own now — say yes to one, and Dex keeps surfacing new ones for that same person as they come up, instead of going quiet.
* **A "no" actually sticks.** When you dismiss a suggested connection — or just delete one yourself — Dex remembers, and the same meeting won't quietly bring it back later.
* **"Relationships to confirm" now actually lets you confirm.** The heads-up in your daily plan leads straight to a real yes-or-no step, rather than pointing you somewhere that couldn't act on it.
* **"Off" means off.** If you've told Dex not to create things on its own, it now leaves connections alone too — no exceptions.

## [1.72.0] — 🔗 Dex starts mapping how the people you know connect (2026-07-24)

Dex has always kept a page for each person and company you deal with. What it couldn't do was join them up — see that someone works at a particular company, reports to someone else, or is the key stakeholder on a deal. This release starts drawing those connections, quietly, from what's already in your meetings.

### 🔗 The connections between your people, drawn for you

**What this fixes for you:**

* **Dex now notices relationships and proposes them.** As it processes your meetings it spots things like "this person works at that company" or "these two are on the same deal," and adds them to the relevant pages — kept as *suggestions* until you say yes.
* **Nothing is ever stated as fact until you confirm it.** Every connection Dex draws starts as a suggestion. You confirm the ones that are right, and from then on Dex treats them as settled and never quietly changes them. The ones you ignore stay as gentle suggestions, nothing more.
* **A short "relationships to confirm" nudge in your daily plan.** When there are new connections waiting for a yes-or-no, Dex mentions it in one line during your daily plan and points you to `relationship-radar` to review them. If there's nothing pending, you'll never hear about it.
* **It's careful with your pages.** Connections live in their own clearly-marked section on each page — everything you've written yourself is left exactly as it was.

This is the groundwork for Dex understanding your world as a web of people, not just a stack of separate pages — which is what will make things like meeting prep and "who should I loop in?" genuinely smart down the line.

## [1.71.0] — 🤝 Dex keeps you on top of your people, and closes out your meetings (2026-07-23)

This one is mostly about the people side of your work. Dex now notices when you're drifting out of touch with someone who matters, helps you wrap up a meeting the moment it ends, keeps track of the small promises that are easy to drop, and adds a couple of new tools for starting something new. There's also a safer way to take an update when you've personalized Dex.

### ❄️ Dex tells you who you're losing touch with

You have people you mean to stay close to — and it's easy for weeks to slip by without noticing one has gone quiet. Until now Dex had no sense of that rhythm.

**What this fixes for you:**

* **A gentle "going cold" heads-up.** Dex watches how regularly you're in contact with the people on your pages, and when someone you were close to goes quiet for a while, it says so — ranked by how overdue each one is — so you can reach out before it costs you.
* **A tool to ask directly.** The new `relationship-radar` skill answers "who should I reach out to?" or "who am I losing touch with?" whenever you want it, and it turns up during your weekly review.
* **It never nags or acts on its own.** It only ever suggests; reaching out stays entirely your call.

### 🤝 Wrap up a meeting while it's still fresh

The best moment to capture what a meeting decided is the minute it ends — and that's exactly when it's easiest to move straight to the next thing and lose it.

**What this fixes for you:**

* **`meeting-closeout` locks it in.** Right after a call, Dex helps you pin down the decisions, who owns each action, what *you* committed to, and the single next step — then, only with your OK, turns those actions into tracked tasks.
* **`commitments` catches what you're on the hook for.** Ask "what did I promise?" or "anything I owe people?" and Dex reconciles the promises you made and the asks you received across your meetings and notes into a clear owner/due/source list — then tracks the real ones once you confirm.
* **Nothing becomes a task without your say-so.** Both tools show you the list first and wait for your yes.

### ✍️ Small promises don't slip through

In conversation you say things like "I'll follow up on that" or "let me get back to you" — real commitments that rarely make it onto any list.

**What this fixes for you:**

* **Dex now spots soft promises in your meetings** — the "I'll send that over" kind — and offers to capture them, so the quiet commitments get the same follow-through as the formal ones.
* **Your meetings turn into updates you can trust.** Behind the scenes I rebuilt how a synced meeting updates your people pages so that if anything is interrupted mid-way, no update is silently lost — it's retried until it lands, and never leaves a page half-written.

### 🚀 Two new tools for starting something

* **`initiative-kickoff`** — when you decide to start something new (a hire, a partnership, a push), Dex turns it into a real project: the outcome and why now, what success looks like, who's involved, the first steps, and a project page that ladders up to your goals.
* **`create-skill` got a rebuild.** Building your own Dex tool is now smarter — it checks nothing else already does the job, writes it properly, and grades it before calling it done. Anything you build for yourself is protected from future updates.

### 🔐 A safer update when you've made Dex your own

If you'd personalized one of Dex's tools and an update changed that same tool, you used to face an awkward either/or: keep your version or take the new one.

**What this fixes for you:**

* **Keep both.** Dex can now put the new version live *and* save your version right beside it, still fully usable — so you never have to throw away your customization to move forward. The whole change stays undoable.
* **Your personal instructions survive an update.** A particular kind of update could drop the personal notes you'd added to Dex's main instructions. Those are now carried across intact.
* **Dex still asks before touching anything, and shows you exactly what it will do first.**

## [1.70.0] — 🛟 Your own words stay safe, and Dex finds people properly again (2026-07-23)

Two things in this one: a rare but unrecoverable way your writing could be overwritten, closed for good — and a rebuild of how Dex looks people up, which was quietly getting slower and occasionally turning up people who no longer exist.

### 🛟 Your own words on a person page can't be overwritten

Dex keeps a short summary at the top of each person's page and refreshes it as things change. It has always been careful to stay inside its own marked-off section and leave your writing alone — but there was one way that could go wrong. If the marker closing off that section ever went missing (two machines syncing the same page at once can do it), the next refresh would carry on past where it should have stopped and replace everything below with the summary, including anything you had written yourself. It happened in an instant, and there was no getting it back.

**What this fixes for you:**

* **Dex now stops rather than guesses.** If the marked-off section on a page looks wrong in any way, Dex leaves that page completely alone and moves on to the next one, instead of writing into it and hoping for the best.
* **Three separate checks, not one.** The problem is caught when Dex first reads the page, again just before it writes, and once more inside the writing itself — so one missed check can't let it slip through.
* **Nothing else changes.** Pages that look perfectly normal — which is all of them, for almost everyone — are handled exactly as before.

I went looking for this deliberately, by attacking my own code to find ways it could destroy someone's work. The odds of hitting it were slim, but you would never have got those notes back, so it was worth fixing on its own.

### 🔎 Finding a person got faster — and stopped turning up ghosts

Every time you asked Dex about someone, it read its way through a single list of everyone you know. That worked fine at first and got slower as your world grew. Worse, the list could fall out of step with reality: delete or rename someone's page and they could keep appearing in searches, pointing at a page that wasn't there any more.

Dex now keeps a small, disposable index built from your actual pages, and rebuilds it whenever anything changes.

**What this fixes for you:**

* **People you've deleted actually disappear.** Removing or renaming someone's page now removes them from search, instead of leaving a ghost behind that points nowhere.
* **Looking someone up stays quick as your world grows.** Dex no longer re-reads an ever-growing list every single time you ask about someone.
* **Your notes are still the only thing that counts.** The index is disposable — Dex can throw it away and rebuild it from your pages at any moment. It never travels between your machines, so two computers can't end up disagreeing about it.
* **A small typo no longer makes someone vanish.** A formatting mistake at the top of a person's page used to drop them out of search entirely. They now stay findable by name, with only the unreliable details left blank rather than guessed at.
* **Two things at once no longer breaks a search.** If Dex happens to be updating the index at the exact moment you ask about someone, your question waits a moment and falls back to the last good copy, rather than failing.

**Behind the scenes:** the test version of Dex now publishes its own vault package, the same way the stable version does.

---

## [1.69.0] — 🎯 Dex picks the right tool more often — and stops confusing similar ones (2026-07-22)

Before, if you said "clean up my inbox" or "prep me for my 2pm," Dex sometimes didn't reach for the right built-in skill, because those skills didn't clearly spell out *when* to use them.

**What this fixes for you:**

- **The right skill fires when you ask.** I rewrote how 49 of Dex's built-in skills describe themselves, so everyday phrasing — "plan my week," "clean up my inbox," "connect my calendar" — reliably lands on the right one. Several skills that previously wouldn't trigger on their own now do.

- **No more confusing the twins.** Skills that do similar-sounding things — planning your day versus reviewing it — now point at each other, so Dex stops reaching for the wrong one.

- **Your career wins get captured again.** A behind-the-scenes step during career coaching that quietly stopped working — logging your achievements — is fixed.

- **New skills stay good.** I added a built-in quality check, so any new skill — yours or mine — gets graded on whether it'll actually fire and behave safely before it ships.

## [1.68.0] — 🚪 Every way Dex changes your vault now goes through one safe door (2026-07-22)

For months, different parts of Dex changed your files in different ways — installing, updating, undoing, fixing itself. This release routes every one of them through the single protected engine built over the last week, and gives you a whole shelf of new role-specific tools you can turn on safely.

**What this changes for you:**

* **One safe door for every change.** Installing Dex, updating it, adding a feature, letting Dex Doctor fix something, or undoing an update — all of it now goes through the same engine that shows you exactly what will change, backs it up first, and can undo it. There are no longer any side paths that quietly edit your files a different way.
* **New tools, turned on the safe way.** Two dozen role-specific tools that shipped quietly inside Dex — for sales, product, and engineering work (things like account planning, roadmap reviews, and tracking technical debt) — can now be switched on through `/dex-level-up`. Turning one on shows you exactly what it adds and can be undone, and it will never overwrite a tool you've customized yourself.
* **Turning on a feature can never overwrite your own version.** If you've already made your own tool with the same name, Dex spots the difference and stops to ask, rather than replacing your work.
* **A smooth bridge from older versions.** If you're updating from an earlier Dex, this release carries you onto the new safe engine cleanly, resuming safely even if a previous update was interrupted.

This is the release where the "updates that can't hurt your files" promise becomes true everywhere, not just in the newest parts. Every piece passed an independent security review before shipping.

---

## [1.67.0] — 🧭 Three new leadership tools, and a full, honest history of every change Dex makes (2026-07-22)

The safe-update machinery from the last two releases now has a face you can actually use — plus the first three tools built to run through it end to end.

**What this changes for you:**

* **Three new tools for leading, not just organizing.** `/decision-log` captures a real decision — the context, the options you weighed, why you chose, and when to revisit — so it doesn't evaporate into a meeting. `/delegate-check` shows what you've handed to other people, where each one stands, and who needs a nudge. `/weekly-reflection` is a two-minute prompt on what gave you energy and what drained it, separate from your metrics review.
* **Dex Doctor now shows updates in plain groups.** When there's anything to update, you see it sorted into five simple buckets: new and safe, needs your review, preserved as-is, something to continue or undo, and your receipts. The wording can vary, but the facts underneath — what changed, what's yours, what can be undone — are always exact.
* **A complete, tamper-evident history of every change.** Dex keeps a running log of everything it installs, adopts, or undoes in your vault. If any past entry is altered or a file goes missing, Dex notices and tells you how to repair it — and an ordinary crash mid-write now heals itself instead of getting stuck.
* **Dex stops quietly editing your Mac's background settings.** When your vault moves, Dex used to silently rewrite system startup files. Now it just tells you what it noticed and points you to `/dex-doctor` to fix it safely — nothing on your machine changes without you.
* **Proven against a deliberately broken vault.** Everything above was stress-tested against a vault packed with every nasty edge case at once — corrupted files, broken shortcuts, interrupted updates — and had to come through without changing a single thing it wasn't asked to.

Every part of this release passed an independent security review before shipping.

---

## [1.66.0] — ↩️ Every change Dex makes can now be undone — and your data files are protected too (2026-07-21)

This morning's release gave Dex full sight of what an update would change. This one adds the hands: Dex can now apply those changes safely, and take any of them back.

**What this changes for you:**

* **Nothing is applied without a double-check.** Before writing anything, Dex shows exactly what will change and gets an approval bound to that exact list. At the moment of writing, it re-checks everything from scratch — if anything on disk moved in between, it refuses and asks again rather than guessing.
* **Every change comes with an undo.** Each applied change produces a receipt, and Dex can restore things to exactly how they were — byte for byte. If you've edited a file since, Dex refuses to undo over your edit and tells you which file, instead of destroying your work.
* **A crash can never leave you half-changed.** Pull the plug at any instant during an apply or an undo and you end up either fully done or exactly where you started. This was independently attack-tested at every possible interruption point.
* **Databases get real protection.** Some tools keep your data in database files that can be silently corrupted by naive copying. Dex now backs these up the one safe way, verifies the result, and — after a security reviewer proved a subtle power-loss risk — restores them in an order that no crash timing can corrupt.
* **A heads-up if your vault lives in Dropbox, iCloud, or OneDrive.** Sync services can corrupt databases mid-write, so Dex now asks before backing up a database inside one.
* **Honest housekeeping.** Dex keeps the last three undo points (about the last three changes), warns if they ever grow past ~2GB of disk, and tells you plainly when something is too old to undo.

Every piece of this release passed an independent adversarial security review before merging.

---

## [1.65.0] — 🔍 Dex now knows exactly what an update would change — before it changes anything (2026-07-21)

Until now, updating Dex meant trusting that the new version and your vault would get along. This release gives Dex full sight before any future update touches anything.

**What this changes for you:**

* **Every release now carries a complete packing list.** Each new version of Dex ships with an exact inventory of what's inside, and the release build fails if that list is ever incomplete — so "what's in this update?" always has a precise answer.
* **Dex can now read your vault like a map — without touching it.** It can tell what came from Dex, what you've customized (so updates will respect it), what's yours alone, and what it doesn't recognize. Anything unrecognized is reported honestly instead of guessed at.
* **You'll be able to skip parts of an update safely.** The planning engine guarantees that saying "not this one" to any piece never changes what happens to the rest — each piece is decided completely on its own.
* **`/dex-doctor` gained two new checks** that report on all of the above, in the same honest working / off / broken / couldn't-check language as everything else.

This completes the "look, don't touch" phase of the update-safety program. Next up: applying updates through this map, with automatic backups and one-command undo.

---

## [1.64.0] — 🛡️ Updates that can no longer harm your files, and the last of the leftovers cleared out (2026-07-21)

This release finishes two stories that began yesterday: making Dex updates fundamentally safe, and getting the last of the maker's own files out of your install.

**What this changes for you:**

* **Updates now run through a protected engine.** For vaults on the new layout, updating no longer mixes Dex's changes into your files the old way. Instead: Dex backs everything up, applies the new version, checks its own work, and can undo the whole thing exactly. If your machine crashes mid-update, you end up either fully updated or exactly where you started — never in between.
* **Your vault can become fully yours.** New machinery (not yet switched on by default) can separate Dex's code from your content entirely, so your notes live in their own private, versioned space that updates physically cannot touch — with a practice run first and one command to change your mind.
* **A few old files from the maker's setup are being retired the safe way.** If you ever edited them, your copies are preserved exactly; nothing of yours is touched.
* **Fresh installs land in the right shape automatically**, with plain-English guidance if anything needs a decision.

---

## [1.63.0] — 🏠 Dex only sets up the rooms you actually need (2026-07-20)

Until now every Dex install arrived fully furnished — career coaching, company pages, quarterly goals — whether or not any of that matched your working life.

**What this changes for you:**

* **Dex asks what your work life actually looks like.** New setups keep the core always on — meetings, people and tasks — then ask three quick yes-or-no questions: do you want a Career room, a Companies room, a Quarterly Goals room? Say no and they simply don't exist in your vault, so you're not left with empty folders about a job you don't have. You can switch any room on or off later, and switching one off never deletes anything you wrote.
* **If you already use those features, nothing changes.** Existing setups keep every room exactly as it is.
* **The foundations for worry-free updates are in place.** Dex now has a single rulebook saying, for every file, whether it belongs to Dex or to you — plus a new update engine that backs up before touching anything, checks its own work, and can undo it exactly. If an update is ever interrupted, even by a crash, your files end up either completely untouched or completely updated — never half-done. You'll feel this properly in the next few releases, as updating becomes one command with one-click undo.
* **The last of my own files are on their way out.** Earlier versions shipped with a few of my personal notes mixed in. Most went in this release, and the machinery to remove the final few safely — without disturbing anyone's update history — ships here too.

---

## [1.62.0] — 🔐 Some housekeeping on your connection keys, and Dex never updates itself behind your back (2026-07-20)

A round of tidying up, and one thing you're now in control of.

**What this changes for you:**

* **Your connection keys now live in a private file of their own.** When you connect a tool like Todoist or Trello, Dex saves a key that lets the two talk to each other. Those keys used to sit in a settings file inside your Dex folder — and that folder keeps its own history. Dex never sent them anywhere, but if you ever share, publish or back up that folder, they'd travel with it, and old copies linger in the history even after the file changes. So Dex now keeps them in a separate private file, away from all that. If it spots an old key sitting where they used to be, it'll suggest swapping it for a fresh one.
* **Dex's own tidiness check got better at its job.** Dex glances over your files for anything that looks like a key or a password before saving. The old check could be fooled by one written in an unusual way and would say everything was fine. The new one reads your settings properly, and if it genuinely can't tell, it says so rather than assuming.
* **Dex never updates itself without asking.** Dex used to be able to quietly fetch and apply changes to itself when you started a session. Now it only *notices* that a newer version exists and mentions it. Nothing changes until you say so.
* **Your own files survive an update.** Files and settings that only exist on your machine are kept safe through an update or a rollback, rather than risking being written over.
* **Task syncing with Jira works reliably again**, and an add-on I no longer wanted to ship was taken out of the package.

---

## [1.61.0] — 🧪 Behind the scenes: groundwork for a test version of Dex (2026-07-14)

Beta-channel build pipeline (internal): CI can now produce a `release-beta` build and every release gets an immutable tag; no user-visible change yet.

**What this changes today:**

* **Stable builds keep their existing path.** Pushes to `main` still produce the stripped `release` branch and the normal versioned GitHub Release.
* **Beta builds are ready internally.** Once a `beta` source branch exists, pushes to it can produce `release-beta` with the same stripping and installed-files manifest as stable, without creating a GitHub Release or changing which release is latest.
* **Every built distribution has a permanent identity.** An annotated tag points to the exact release commit and its manifest, so a later rollback update can find historical release contents even after a release branch is rebuilt.
* **Beta is not user-selectable yet.** Update, rollback, and channel-switching behavior is unchanged and will ship separately.

---

## [1.60.0] — 🧪 Behind the scenes: more test-version groundwork (nothing changes for you yet) (2026-07-13)

Dex now has the internal release-channel plumbing needed for a future opt-in beta. The health check understands which release line an installation belongs to, so future beta users will not get false "couldn't verify" warnings from being compared with stable code.

**What this changes for you today:**

* **Stable updates work exactly as before.** Existing installations still use the stable release path, including profiles that do not yet contain the new internal setting.
* **Unverifiable channels fail safely.** Health checks report that they could not verify a missing beta release or invalid channel instead of treating it as broken or silently trusting stable code.
* **Beta is not selectable yet.** This release adds only the safety foundation; update, rollback, and channel-switching controls will arrive separately.

---

## [1.59.0] — ⏱️ Dex stops calling a working feature "broken" just because your Mac was slow to start it (2026-07-13)

Dex's health check gave built-in services just 1.5 seconds to wake up. On a slower or busy machine, a service could still be starting normally when Dex labelled it broken. Those services now get a fair eight-second window, with enough room in the overall check for the slower start to finish without changing the usual quick path.

**What this fixes for you:**

* **Slow starts no longer look like failures.** `/dex-doctor` and nightly health checks wait long enough for working built-in services to answer, even when your machine is under load.
* **Unusually slow setups can choose a longer window.** Set `DEX_MCP_HANDSHAKE_TIMEOUT` to a positive number of seconds when your services genuinely need more than the standard eight seconds; missing or invalid values safely keep the default.

---

## [1.58.0] — ✅ Your tasks and priorities are handled more carefully (2026-07-13)

A coverage review of the code that edits your task and priority files turned up eight ways Dex could quietly mishandle them. All eight are now fixed, each locked in by a test so they can't come back.

**What this fixes for you:**

* **Completing a task marks the *right* one.** If two tasks had similar wording (one a substring of the other) and no ID, saying "done" could flip the wrong task. Dex now matches the exact task, and refuses to guess when it's genuinely ambiguous rather than picking wrong.
* **"Done" actually completes an open task.** If an already-completed copy of a task sat above an open one, Dex could report success without ticking the open one. It now finds the open task and completes it.
* **Your file's line endings are left alone.** Completing a task in a file edited on Windows no longer rewrites every line ending — only the one task line changes.
* **Checkbox text inside a task title is safe.** A task whose title happened to contain checkbox characters is no longer mangled when completed.
* **Weekly priorities stay in order.** New "Top 3" priorities are added at the bottom, numbered in sequence — no more entries landing out of order or two items sharing a number.
* **A fourth priority is handled gracefully.** Adding beyond three no longer corrupts the list; the item is numbered correctly and Dex gently notes that "Top 3" is meant to keep your focus tight.
* **Backlog ideas rank correctly.** A captured idea now sorts into the right spot by score instead of jumping ahead of higher-scored ones, and marking an idea implemented no longer alters its title.

---

## [1.57.0] — 📡 Help catch a bad update early — without sharing a word of your content (2026-07-13)

Opt in to help catch bad releases across all vaults — anonymous nightly health counts, no content ever.

**What this fixes for you:**

* **Bad releases can show up within hours.** If you explicitly opt in, Dex shares one tiny verdict after its nightly self-check so maintainers can see when the same update starts breaking across installations.
* **Your work never joins the report.** The verdict contains only outcome counts, one fixed check identifier when something is wrong, the Dex version and release channel, and a random installation ID. It never includes names, notes, filenames, paths, or file contents.
* **This choice is separate and defaults to no.** Existing analytics consent does not enable health sharing. Missing, pending, or malformed consent sends nothing, and you can turn health telemetry on or off in plain language anytime.
* **You can inspect every attempt locally.** Dex keeps an ignored local line-by-line audit of exactly what it would send, including attempts skipped by consent and requests dropped after a network failure.

---

## [1.56.0] — 👀 Dex notices the apps you actually have installed (2026-07-13)

When Dex suggests connecting a tool, it now leans on real evidence — is the app sitting in your Applications folder? Is the connector already half set up? — instead of just scanning your notes for mentions. A tool you actually have installed is a far better signal than a passing reference to one.

**What this fixes for you:**

* **"Installed on your Mac" beats a guess.** When Dex offers to connect Things, Trello, Todoist, Zoom, or Teams, it now checks whether the app is actually installed and leads with that — so its suggestions feel observant, not random. An installed app is strong enough to surface on its own.
* **Half-finished setups get noticed.** If a tool's connector is already configured but sync was never switched on, Dex spots the loose end and offers to finish it, rather than treating it as brand new.
* **Suggestions say why.** Each recommendation now comes with its reason in plain words — "installed on your Mac", "already set up but not switched on yet", or how many times you mentioned it — so you understand where the nudge came from.
* **Nothing leaves your machine.** The check is a local look at your Applications folder and your own config files — no network calls, and it quietly does nothing on non-Mac systems where those apps don't apply.

---

## [1.55.0] — 🤝 Contributing to Dex is now safer (2026-07-13)

Contributing to Dex is now safer — CI catches personal data before it's shared, and tells contributors in plain English what their change touches.

**What this fixes for you:**

* **Personal details are stopped before merge.** Pull-request CI checks only newly added lines and names the exact file and line when it finds a real email, filled-in tracked profile or integration identity, personal vault content, or configured CLAUDE profile.
* **Every contribution gets a product map.** A sticky report translates changed paths into recognizable Dex areas, the user journeys they feed, and the quality gates that apply. Fork contributors still get the identical report in the job summary when GitHub withholds comment permission.
* **Messy real-world content gets exercised.** Disposable vault fixtures now include unicode and spaced filenames, half-written notes, duplicate task headings, and recoverable malformed YAML, backed by fast property tests and larger nightly fuzz cases.
* **A busy machine no longer makes one of my own checks look broken.** One release check now gets more breathing room and a single retry if it simply ran out of time. What Dex promises you at run time is unchanged.

---

## [1.54.0] — 🧾 See exactly what Dex checked before a release reached you (2026-07-13)

Dex's release checks were rigorous but invisible once a release reached you. Each successful release build now publishes a small public page showing the evidence for that exact version, without turning checks that did not run into reassuring green ticks.

* **The proof is tied to one release.** The page names the package version, source commit, generated release commit, verification time, and workflow run.
* **Every gate tells the truth.** Checks run by the successful main build are marked passed; pull-request-only checks are explicitly marked not applicable and not run on the release build. Missing evidence stays unknown.
* **A failed later build cannot rewrite history.** The published page remains labelled as the last successful release build, so it never claims to describe a newer failing `HEAD`.

---

## [1.53.0] — 🔗 Dex now tells you it can connect to your task apps (2026-07-13)

Dex quietly gained two-way sync with Todoist, Things 3, and Trello — but you'd only have found out during first-run setup, or by already knowing to ask. That's a shame for a feature this useful. Now Dex surfaces it the moment it's relevant.

**What this fixes for you:**

* **Mention your task app and Dex offers to connect it.** Say "I keep my tasks in Trello" or "that's on my Todoist" — or just paste a board link — and Dex offers to set up sync right there, in one light line. Say no and it drops it; no nagging.
* **Dex notices the tools you already use.** During the getting-started tour and when you run `/dex-level-up`, Dex now scans your notes for signs of the tools you work with (mentions, links) and leads with the ones that actually fit you — "I noticed you mention Things in a few places" — instead of a generic list.
* **First-time setup leads with what fits you.** Onboarding still offers every integration, but now puts the ones your vault already hints at up top.
* **They're in the catalog now.** The skills list (`/dex-level-up`, `.claude/skills/README.md`) finally names every connect skill — Todoist, Things, Trello, Gmail, Teams, Zoom, Jira, Granola, calendar — so browsing "what can Dex do?" actually shows them.
* **`/integrate-mcp` points you the right way.** The "connect more tools" skill now names the task apps and their built-in setup skills first, instead of sending you to hunt through a marketplace for something Dex already supports natively.

## [1.52.0] — 🩺 Your own tools can now be health-checked for real — only when you say so (2026-07-13)

Tools you build yourself used to sit permanently at "can't tell", because Dex won't run your own code during a checkup without permission. You can now ask `/create-mcp` for a one-off startup proof and, as a separate default-no choice, trust one exact local Python file for nightly and deep checks.

* **Consent is specific and honest.** Dex shows the vault-relative file and SHA-256 first, and says plainly that this runs the file with your user permissions and trusts whatever it imports.
* **Changed code never inherits old consent.** Name, path, and opened-file hash must all match. Dex hashes and copies from the same no-follow file handle, then starts only that private copy.
* **Everything else stays structural-only.** Missing or linked files, changed content, invalid registries, extra Python flags, remote servers, npm/npx commands, binaries, and hand-edited ineligible entries are refused with an exact reason.
* **Your trust choices remain yours.** `System/trusted-mcps.yaml` is gitignored and included in update recovery's user-data preservation list, so an upstream update cannot add or replace consent entries.

---

## [1.51.0] — 🔁 Things 3 and Trello sync join the party (2026-07-13)

Real two-way sync landed for Todoist in the last release. This one brings your Mac's Things 3 and your Trello boards onto the same engine — so whichever task app you actually live in, Dex keeps step with it.

**What this fixes for you:**

* **Things 3, fully local, now syncs.** Ask Dex to sync and your pending tasks appear in the right Things Area (mapped from your pillars), the urgent ones land in Today, completions flow both ways, and anything you drop into your Things Inbox comes back for review in your morning plan. No accounts, no network — it all happens on your Mac through Things' own scripting.
* **Trello boards stay in step.** New Dex tasks become cards in the right list, finishing a task moves its card to Done, and cards you add or move on the board come back to you for review — matched to the exact lists you picked during setup, not guessed from their names.
* **Tasks from either tool arrive through your review, never behind your back.** Whatever you created in Things or Trello queues up in your daily plan, where you decide what becomes a Dex task — with duplicate checks and pillar linking — instead of it silently appearing in your backlog.
* **A task title with an apostrophe can't break things anymore.** The Things connection was rebuilt to hand your task text to macOS safely, so quotes, apostrophes, and punctuation in a task name just work instead of causing a failure.
* **Your pillars, not someone else's.** Both connections now read the Areas and lists from your own setup rather than falling back to a hardcoded set of categories that only fit one person's vault.
* **Honest setup guides, again.** The Things, Trello, and Todoist setup walkthroughs now describe the sync that genuinely exists — the "coming later" note is gone because it's here.

## [1.50.0] — 🔁 Real Todoist sync — the promise, finally built (2026-07-13)

Earlier setups promised automatic two-way Todoist sync that never existed (I removed that promise in 1.36.0). This release builds the real thing, carefully.

**What this fixes for you:**

* **Ask Dex to sync, and it actually syncs.** New Dex tasks appear in Todoist (in the right project via your pillar mapping), tasks you complete in Dex get closed in Todoist, and tasks you complete in Todoist get marked done in Dex — with the completion recorded everywhere the task appears.
* **Tasks created in Todoist arrive through your review, not behind your back.** Inbound tasks queue up for your daily plan, where they're created properly — with duplicate checking and people/goal linking — instead of being silently injected into your backlog.
* **First sync can't flood anything.** Connecting starts clean from that moment; your existing backlog is never bulk-pushed to Todoist, and Todoist history is never bulk-imported.
* **Preview before you trust it.** A dry-run mode reports exactly what a sync would do while changing nothing, anywhere.
* **Built on Todoist's current platform.** The old attempt was built against a version of Todoist's connection that Todoist retired in early 2026; this is built and tested against the current version of Todoist's connection, and it copes properly when Todoist asks it to slow down.
* **One connector failing never blocks another.** Each service syncs independently; errors are reported per service, and a failed sync never moves its place-marker forward, so nothing gets skipped next time.

Things 3 and Trello sync arrive next on the same engine.

## [1.49.0] — 🌙 Dex now checks itself overnight — and tells you what changed when something breaks (2026-07-13)

Dex's safe release checks used to run only when someone asked for a deep diagnosis or
prepared a release. A problem that appeared between updates could therefore sit quietly
until the next manual check.

**What this fixes for you:**

* **Dex checks its core journeys every night.** At 03:15 it safely tests configuration,
  task creation, built-in services, skills, and hooks in temporary copies without writing
  into your live vault.
* **The next session tells you when something broke.** You see the affected journey and
  its concrete failure, while healthy nights stay silent.
* **`/dex-doctor` narrows down what changed.** It compares the last passing night with the
  first broken one and reports only matching configuration edits, custom-skill edits, or
  a Dex update—without inventing a cause when the evidence is not there.
* **You can look at the evidence yourself.** The latest result and a capped history sit as plain
  text files in your own folders, written so you never catch one half-finished.

## [1.48.0] — ☀️ Your morning plan now shows what your meetings turned into (2026-07-13)

Tasks extracted from meetings used to land in your backlog without a moment to review them, and tasks that guessed at a goal link had no way to be confirmed. The daily plan now closes both loops.

**What this fixes for you:**

* **One glance at what your meetings produced.** The daily plan lists tasks created from recent meetings, each with the meeting it came from and its due date — so nothing your meetings generated slips past you.
* **Likely goal links get a yes or no.** When Dex links a task to a quarterly goal with a "(?)" (meaning "probably, but confirm"), the daily plan walks you through them in one pass — keep the link or clear it, one word each. A new under-the-hood tool makes the answer stick properly, so you never have to edit task files by hand.
* **Unextracted meetings get a nudge.** If meetings are sitting with action items nobody turned into tasks, the plan says so and points at `/process-meetings`.
* **Quiet when there's nothing to review.** No "0 tasks from meetings" noise on quiet days.

## [1.47.0] — 🔧 Behind the scenes: my own checks stopped tripping over themselves (2026-07-12)

The automated checks that run on every proposed change could fail with a confusing "cannot find a common ancestor" error that had nothing to do with the change itself — a self-inflicted glitch in how the checks fetched the project's main line.

**What this fixes for you:**

* **Contributor and update checks stop flaking.** The checks now fetch the main line in full instead of a truncated snapshot, so they can always compare your change against it. The earlier partial-fetch was the actual cause of the spurious "no common ancestor" failures — not, as first suspected, anything rewriting the project history.
* **A guard keeps it from coming back.** A new test fails the build if any check reintroduces the truncated fetch.

---

## [1.46.0] — 🔧 Two recent fixes, finished properly (2026-07-12)

An independent review of this week's safety fixes caught two cases where a fix didn't fully deliver what it promised. Both are now closed.

**What this fixes for you:**

* **Checking a task off directly in your task list now updates everywhere.** A recent change meant that ticking a box straight in `Tasks.md` (rather than through chat or a person page) quietly stopped updating the linked person and meeting pages. Those edits propagate again.
* **An empty pillar keyword list no longer wipes your pillars.** Leaving a pillar's keywords blank in your settings could quietly reset *all* your pillars to the defaults. A blank list is now handled safely.

---

## [1.45.0] — 🩺 Dex can prove your setup still works (2026-07-12)

Dex can now tell you when YOUR customizations break it — and updates prove themselves
before declaring success. The checks keep your files and skills safe while separating
problems in your setup from problems in Dex itself.

**What this fixes for you:**

* **Your custom skills and connections get an exact diagnosis.** `/dex-doctor` names the
  file that needs attention and tells you to fix or remove that customization, rather
  than blaming Dex or suggesting an unrelated rollback.
* **Deep checks exercise real journeys without risking your vault.** Dex loads configs,
  creates and updates a task, starts only Dex's own built-in services, and checks every skill
  and hook in temporary copies. It never runs skills you wrote yourself, contacts the network,
  or writes into your live vault.
* **Updates and rollbacks verify the result.** Both flows run the doctor and smoke tests
  before declaring success, and rollback cleanup uses shipped manifests so files you
  created remain yours.
* **Changes to shipped Dex files are visible before an update.** The doctor warns which
  modified files may conflict while leaving sanctioned customization surfaces alone.

## [1.44.0] — 🧠 Person pages now get smarter, not just longer (2026-07-12)

The entity engine made pages accumulate facts automatically — meetings, tasks, dates. But accumulation isn't understanding: a page that only grows becomes a log file. The gardener fixes that.

**What this fixes for you:**

* **Every active person page keeps a living summary.** A short "who this person is to you right now" section — role, what you've been meeting about, open threads — distilled from their recent meetings and tasks, refreshed as things change.
* **It never touches your own writing.** The summary lives in its own clearly marked block. If you ever edit inside that block, Dex takes the hint and permanently stops maintaining that page's summary (and the doctor checkup tells you it did).
* **Costs stay small and predictable.** At most five pages per sync, each page at most weekly, and only when something new actually happened for that person. It runs only if you already use an AI key for meeting processing, and one settings line (`entity_gardener: enabled: false`) turns it off.
* **Nothing is written on a bad day.** If the AI returns nothing useful, the page is left exactly as it was — and failures now print the actual reason instead of just an error count.

---

## [1.43.0] — ✅ Adding a task never fails just because a priority is busy (2026-07-12)

When a priority level was already full, Dex used to refuse to create the task at all — and that refusal was easy to miss in a wall of terminal text, so the task either vanished or landed at the wrong priority.

**What this fixes for you:**

* **Your task always gets created.** If a priority level is over its guideline, Dex still adds the task there and simply notes that the level is getting crowded — it never silently drops the task or quietly downgrades it.
* **The nudge is gentle, not a wall.** You see a one-line heads-up with the current count, so you can rebalance when you choose to — not mid-thought.
* **A pillar keyword like `1:1` no longer breaks task filing.** Certain shorthand written in your pillar settings could crash the step that guesses which pillar a task belongs to; it's now handled safely. Thanks to stevegranshaw for reporting.

---

## [1.42.0] — 💬 Dex now tells the truth about what your setup can do (2026-07-12)

Some setup and recovery guidance could promise features that never reached your active Dex, point you to skills that did not exist, or treat an optional choice as a failure.

**What this fixes for you:**

* **Model setup no longer leads you into a dead end.** Dex used to offer budget and offline settings that only ever configured Pi — a separate tool Dex no longer ships — so they did nothing. They're gone, and Dex no longer guesses how much memory your computer has.
* **Parked meeting experiments stay out of your way.** An unwired ritual beta handout no longer tells testers that `/daily-plan` will surface recurring-meeting previews when that feature is not connected.
* **Integration prompts now open a skill that exists.** Setup and post-update guidance sends you to `/integrate-mcp` for Notion, Slack, and Google Workspace instead of naming skills Dex cannot run.
* **Calendar onboarding fits your operating system.** macOS users still get the permission steps they need; Windows and Linux users now get a clear explanation that calendar sync is macOS-only and can continue setup without looping on impossible instructions.
* **Optional features are described consistently.** A feature that is off stays calm and healthy, a missing or broken feature includes the real fix, and an uncertain check simply admits it could not verify the state.
* **Developer probes no longer clutter your install.** One-off diagnostics and an obsolete launch-agent repair utility are gone; `/dex-doctor` remains the supported place to check background-job health.

---

## [1.41.0] — 🩺 Your checkup now tells the truth on a brand-new Dex (2026-07-12)

A fresh install could mistake other Dex products or optional features for failures, miss one of its own services, and inherit integration choices that belonged to the release builder.

**What this fixes for you:**

* **Other Dex products stay out of your checkup.** Background jobs belonging to a different Dex installation are skipped in one quiet note instead of being reported as broken against the wrong vault.
* **Calendar access tells you exactly what is missing.** Write-only access is now explained as insufficient for reading your calendar, with the right guidance to grant full access; unfamiliar permission states include the value Dex actually received.
* **Every built-in service is checked.** The session-memory service is included on fresh installs, and an automatic consistency check prevents future services from being registered without being checked.
* **Checkup totals add up.** Status summaries now use the numbers from the checkup that just ran instead of copying contradictory example totals.
* **Career features stay quietly optional.** If career tracking is not set up, Dex offers the setup skill calmly without an error, a missing-file warning, or a private path from your Mac.
* **New installs start genuinely clean.** Slack and every related meeting or planning hook begin off, so a new vault no longer inherits someone else's connected-tool state or gets noisy connection warnings.
---

## [1.40.0] — 🎙️ Granola setup now tells you the truth (2026-07-12)

Granola could be fully connected while Dex said it was missing, look ready without the key it needed, or ignore your choice to process meetings manually.

**What this fixes for you:**

* **Connected now means ready to sync.** Setup and the background checks now look for the actual Granola key that meeting sync needs, so simply having the app installed — or an old leftover file — can no longer produce a false green light.
* **Manual processing stays manual.** Choosing manual mode now saves the setting in the right shape, and existing vaults with the older shape remain understood instead of silently switching to automatic processing.
* **Fresh installs show the real next step.** Dex detects the Granola app without claiming meeting intelligence is already connected, then points you to `/granola-setup` and explains that you'll need a Granola Business plan to get the key.
* **Every setup path follows the same model.** Onboarding, updates, analytics, and meeting guidance agree on the official Granola connection, so you no longer get contradictory instructions depending on where you ask.

---

## [1.39.0] — 🛟 Four ways your work could quietly vanish, all closed (2026-07-12)

An outside review of Dex's safety net found four situations where your own work could disappear without anyone noticing. All four are fixed.

**What this fixes for you:**

* **Undoing an update no longer undoes your week.** `/dex-rollback` used to put your tasks, quarterly goals and weekly priorities back to how they looked at the last update — losing everything you'd added since — while cheerfully telling you your data was safe. Now everything you've written is set aside first and put back afterwards, and if anything clashes, both versions are kept for you in `System/rollback-rescue/`.
* **Two meetings with the same name stop overwriting each other.** A recurring "1:1" or "Standup" happening twice in one day used to end up as a single note, with the second meeting silently replacing the first. Both are kept now.
* **Obsidian syncing stopped doing pointless work.** It was rewriting files whenever anything changed, whether or not the thing it cared about had changed at all. Now it only acts on a real change — and if it keeps failing, it tells you at the start of your next session instead of failing in silence.
* **Updating by hand no longer drops folders.** The manual instructions quietly missed your Resources folder and your saved session learnings while claiming everything was preserved. Both are included now.

---

## [1.38.0] — 🔗 Tasks now connect themselves to your people, companies, and goals (2026-07-12)

Two long-standing gaps closed at once: tasks extracted from meetings finally get real, trackable IDs, and every task you create now links itself to the right person page, company, and quarterly goal — carefully, never by guessing.

**What this fixes for you:**

* **Meeting action items become real tasks with a closed loop.** Before, meeting notes carried made-up task IDs that collided and matched nothing. Now the note gets a plain checkbox, Dex creates the real task, writes the real ID back onto that exact line — and when you complete the task, the checkbox in the meeting note ticks itself too.
* **Name a person, get the right link.** Say "task about the pricing deck for Sarah" and Dex resolves "Sarah" through your people directory — by email, alias, or name. If two Sarahs match, it asks instead of picking one. It never invents a link to a page that doesn't exist.
* **Companies resolve from a name, a domain, or even a URL.** "acme.com", "Acme", or a pasted link all find the same company page.
* **Tasks find their goal.** When a new task clearly serves one of your quarterly goals, it links itself. When the match is only likely, it links with a visible "(?)" you can confirm or clear — uncertain never masquerades as certain.
* **Old meeting notes heal instead of breaking.** If an old note already carries one of the legacy made-up IDs, Dex adopts it rather than minting a competitor, so nothing you have gets orphaned.
* **Pillar names just work.** You can pass a pillar by its display name ("Deal Support") or its internal ID — both resolve.

## [1.37.0] — 👥 Your people and company pages now build themselves (2026-07-12)

Dex has always said your person and company pages would look after themselves. Until now they didn't. Nothing actually created a page, four different page layouts had grown up side by side, and the step meant to update someone after a meeting had quietly been doing nothing since the day it shipped. This is the release where the promise becomes real.

**What this changes for you:**

* **Pages appear on their own.** When someone turns up in your meetings often enough to matter, Dex creates their page — their role, the company they're at, and the history of when you've met. Same for the companies behind them. You choose whether this happens automatically, gets suggested to you first, or stays off.
* **Colleagues and outsiders get filed correctly.** Dex tells them apart by their email address rather than guessing, so customers stop landing in your internal folder.
* **One page layout, at last.** Pages in any of the older formats still open and still work — Dex reads them all. Anything it genuinely can't make sense of is set aside untouched rather than overwritten.
* **Your own writing is off limits.** Dex only ever edits inside its own clearly marked section of a page. Anything you wrote yourself it leaves exactly as it found it.
* **Finding the right person got much better.** Dex works through email, then nickname, then full name, then first name — and when two people could both be the match, it asks you instead of picking one.

## [1.36.0] — ✅ Every promise about tasks is now one Dex keeps (2026-07-12)

A few task features described things that didn't actually happen: the Todoist, Things, and Trello setups promised automatic two-way sync that was never built, the inbox triage helper read planning files from locations that no longer exist, and some flows quietly wrote tasks in a way the rest of the system couldn't track. This release makes every promise honest and every capture path first-class.

**What this fixes for you:**

* **Todoist, Things, and Trello setups now tell the truth.** They connect Dex so you can check, create, and complete tasks in those apps *on request, in conversation* — and they say plainly that there's no automatic background sync. Before, setup walked you through configuring "auto-sync" choices that did nothing.
* **Inbox triage reads your real plans again.** `/triage` was reading your weekly priorities and quarterly goals from folders that were reorganized long ago, so its routing suggestions ignored your actual priorities.
* **Every captured task is now a real task.** Triage and end-of-day follow-ups used to write plain checkboxes into files; those never got a task ID, so completion tracking, duplicate detection, and goal progress couldn't see them. Both now create tasks properly, carrying the person, company, due date, and goal details they learned along the way.
* **Phone-captured items are handled honestly.** The morning-plan flow claimed one tool both checked and created your captured tasks; it only checked. The instructions now match reality, and the misleading option was removed from the tool itself.

## [1.35.0] — 🗂️ Tasks now remember what you told them (2026-07-11)

When you created a task and confirmed its pillar and priority, Dex wrote them down — and then never read them back, re-guessing both from the task's wording every time it listed your tasks. A P0 could show up as P2 unless its title happened to sound urgent. This release makes task details stick, and adds the fields tasks always needed.

**What this fixes for you:**

* **The priority and pillar you confirm are the ones you see.** Lists, focus suggestions, and limits now read the stored values instead of guessing from the title.
* **Tasks linked to a weekly priority finally count.** Goal and week progress now include tasks you created through Dex — before, those links were written where nothing could read them, so rollups showed zero.
* **Tasks can carry a due date, a project, and a quarterly goal.** All optional, all checked when set — an unknown goal or missing project file gets a helpful error listing what's available instead of a silent dead link.
* **Duplicate detection stops teaching the wrong habit.** When Dex flags a similar task, you can now say "create it anyway" — before, the suggested workaround was to reword the title, which defeated the duplicate check entirely.
* **A rare data-loss bug is gone.** Adding a task to a section whose heading appeared twice in your task file could silently delete everything after the second heading. Inserts are now safe no matter what your file looks like.
* **Completed tasks stay clickable in Obsidian.** The completion timestamp used to be written where it broke Obsidian's link-to-this-line feature; it now goes before the link anchor.
* **Meeting prep sees all your meetings again.** Synced meetings are stored in dated folders that the meeting memory never looked inside — daily plans and meeting prep were blind to them. Both now scan the full folder tree.

## [1.34.1] — 🤝 Dex's release checks no longer break contributor setups (2026-07-12)

Release checks now preserve your local Git history and explain when they cannot compare it.

**What this fixes for you:**

* **My checks no longer trim down the copy of the project history on your machine.** They now leave it intact when you run them yourself.
* **A failed history comparison now explains how to fix it.** Instead of stopping with no output, Dex tells you to fetch the full project history and try again.

## [1.34.0] — 🔗 People in your notes now link themselves — safely (2026-07-11)

People auto-linking was promised but never shipped (issue #46); this release finally delivers it with safeguards that keep links accurate.

**What this fixes for you:**

* **People become connected on their first useful mention.** Full names, unique aliases, and safe unique first names now create backlinks to the right person page without cluttering every mention.
* **Dex never guesses on ambiguous names.** Shared first names, common English words, and names that could refer to someone unknown stay as plain text.
* **Your identity and carefully formatted text stay untouched.** Your own name, existing links, note metadata, code, and Markdown links are preserved, and running the feature again adds nothing extra.

---

## [1.33.0] — 🚦 'Off' and 'broken' now mean different things — everywhere (2026-07-11)

Dex could describe an optional feature as broken in one place and merely disconnected in another; this release gives those responses one shared meaning.

**What this fixes for you:**

* **Optional features stay peacefully off.** If you deliberately did not enable or configure something, Dex treats it as healthy, never uses an error tone, and never nags you to fix it.
* **Real failures stand out.** “Broken” is reserved for a feature that is configured and expected to work but is failing, so genuine problems no longer look like personal setup choices.
* **Missing software has its own answer.** When a required app, binary, or dependency is absent, Dex says that directly instead of calling the feature broken.
* **Uncertain checks admit uncertainty.** If a check itself fails, Dex reports that it could not determine the state instead of inventing a diagnosis.

---

## [1.32.0] — 🧰 Dex can no longer tell you to use tools that don't exist (2026-07-11)

Some instructions could send you looking for a tool or runnable helper that was never included, leaving you stuck at the moment Dex was supposed to help.

**What this fixes for you:**

* **Tool instructions now match what Dex can actually use.** Every release checks each named tool against what Dex ships or deliberately supports through an installed connection, so stale or mistyped names stop the release.
* **A skill pointing at something missing now blocks a release.** If instructions point to a missing required helper, the release fails instead of passing with a warning; truly optional helpers remain clearly identified.
* **Skill-creation guidance no longer points to a missing file.** The shipped guidance now points to the skill creator that actually exists.

---

## [1.31.0] — 📅 Dex asks which calendar is yours instead of guessing (2026-07-11)

Empty calendar results were traced back to onboarding guessing a work calendar name that did not match the names Apple Calendar actually exposes.

**What this fixes for you:**

* **You choose from calendars Dex can actually see.** Onboarding shows the exact Calendar.app names and saves your selection instead of constructing one from your email address.
* **Wrong calendar names are caught during setup.** If a typed name does not match, Dex shows the available calendars and asks again before an empty schedule can surprise you later.
* **Calendar permissions no longer block onboarding.** Dex explains the one-time macOS setting, lets you try again, or records that you skipped so `/dex-doctor` can confirm the setup later.

---

## [1.30.0] — 🔔 Dex now tells you when its background sync has quietly stopped (2026-07-11)

A beta user's meeting sync was dead from February to July with no signal, so Dex now surfaces that silent failure at the start of your next session.

**What this fixes for you:**

* **You will know when meeting sync has stopped.** If its background service is installed but has not run recently, Dex tells you when you next start a session and points you to `/dex-doctor`.
* **A never-started service no longer looks fine.** Dex calls out a configured background sync that has no record of ever running.
* **Normal sessions stay quiet.** Fresh services, and optional services you have never installed, do not create an alert.

---

## [1.29.0] — ✅ Creating tasks works again (2026-07-11)

Since mid-February, asking Dex to create a task quietly failed with a technical error — every time, for everyone. A code mix-up made the task tool trip over an optional search feature even when that feature wasn't installed, and the existing tests happened to sidestep the exact switch that was broken, so nothing caught it.

**What this fixes for you:**

* **"Create a task to…" actually creates the task.** The error that blocked every task creation — and also broke meeting-context lookups and inbox processing — is gone.
* **This can't silently break again.** Dex now tests task creation the exact way your vault runs it: starting the real task service and creating, listing, and completing a task end to end. If a future change breaks task creation, the release checks catch it before an update reaches you.

---

## [1.28.0] — 📦 Installs now contain the Dex features they promise (2026-07-11)

Some install and update paths looked successful while quietly leaving out working parts of Dex, carrying developer-only files, or saving connection settings somewhere Claude Code never reads. This release makes installs complete and checks them through the same journeys you use.

**What this fixes for you:**

* **Downloading Dex as a zip file now gives you complete skills.** Document, presentation, PDF, and other scripted skills could arrive as instructions with no working code behind them. ZIP downloads now include everything those skills need to run.
* **Updates no longer dump 58 of my own test files into your folders.** Releases now leave out test suites and developer setup files reliably, even when filenames contain spaces, and no longer include commands that point at files you do not have.
* **Setup and Claude Code now read your connection settings from the same place.** New setup, Claude Code, and Dex's health checks all look in one place. Existing vaults that use the old location still work, and Dex tells you when it is relying on that fallback.
* **Release checks now use Dex the way you do.** They complete real onboarding and task journeys, confirm meeting updates are written back, start every built-in service, validate every shipped skill, and run every hook in an isolated vault. Packaging and startup failures should be caught before an update reaches you.

*Version note: package metadata moves from 1.26.0 to 1.28.0 to catch up with the already-published 1.27.0 changelog entry.*

---

## [1.27.0] — 🩺 /dex-doctor: a real system checkup that tells the truth (2026-07-11)

Replaces `/health-check` with a rigorous whole-system diagnostic that knows the difference between "off", "broken", "couldn't check", and "fine" — built against the exact failure modes the July 2026 audit uncovered.

**What this fixes for you:**

* **One honest answer to "is my Dex actually working?"** Run `/dex-doctor` and get a clear report: what's healthy, what's broken, what's switched off by choice, and what the doctor itself couldn't verify. Nothing is hidden, nothing is collapsed.
* **It heals what's safe to heal, silently.** Missing standard folders, an out-of-date settings file, helper scripts that lost permission to run — it fixes these before reporting and tells you it did. For riskier fixes (starting a background job, repairing a broken setting) it proposes one at a time and only acts on your yes.
* **Background jobs are checked honestly — freshness, not just presence.** The doctor confirms each installed Dex job actually ran recently, says when it last ran if it's stale, and spots a job that can no longer start before it becomes your problem.
* **Replaces `/health-check`**, which diagnosed Granola by looking at a file the connector never reads and had other stale assumptions. All references now point at `/dex-doctor`.
* **Deep scan available.** Ask for the deep scan and Dex will actually contact the tools you've connected — Granola, your calendar, and the rest — to confirm the real query paths work, not just that the config looks right.

---

## [1.26.0] — 🧹 A tidy-up, and one missing piece finally shipped (2026-07-11)

The final batch from the dex-core audit — removing things that looked real but were wired to nothing, and shipping one thing that was real but never left the developer's machine.

**What this changes for you:**

* **The integration concierge actually ships.** The vault scanner that recommends which tools to connect (used by onboarding and `/getting-started`) existed only on the developer's Mac — it was never committed, so the tour silently skipped it for everyone. It's now included, with its setup-skill references corrected.
* **People auto-linking is paused instead of broken.** Dex's instructions required running a script that was never shipped (issue #46) — erroring on every meeting note and daily plan. The instruction is removed; the real auto-linking feature is queued to be built properly.
* **Deleted two settings files nobody was reading** — they looked official, were wired to nothing, and were behind the whole family of "this service can't be reached" bugs.
* **Removed a dead installer step and a write-only config file** nothing ever read.

---

## [1.25.0] — 🎙️ Granola stops silently reporting zero meetings (2026-07-11)

Fixes the bug where Granola showed "connected and ready" while every meeting query
returned nothing (reported by a beta user with full diagnosis — thank you, Michelle).

**What this fixes for you:**

* **Your meetings come back.** Dex was asking Granola for your meetings using a date format Granola rejects. The
  rejection was swallowed on the way back and reached you as "you have no meetings."
* **Failures now say so.** If a Granola query fails for any reason, Dex reports
  "Granola query failed" with the cause — it will never again disguise an error as an
  empty calendar.
* **The connection check tells the truth.** It now asks Granola the same way a real meeting
  lookup does, so it can't show green while your actual lookups come back empty.

---

## [1.24.0] — ✅ Honest task completion, and search that only switches on when you ask (2026-07-11)

Final code batch from the dex-core audit.

**What this fixes for you:**

* **"Task marked done" now means it.** If updating a completed task failed in some of its locations, Dex used to report success anyway. It now tells you exactly which locations updated and which failed.
* **No more phantom "failing server" for search you never enabled.** Search-by-meaning is no longer switched on for everyone in advance; it registers when you actually enable it (`/enable-semantic-search`), or automatically at install if it's already on your machine.
* **Empty calendar results now explain themselves.** If your configured work calendar doesn't match any real calendar, Dex says so and lists the calendars it can see — instead of silently returning nothing.
* **The safety guard actually guards.** A safeguard that blocks damaging commands had never been switched on, so it had never once run. It's now active.

---

## [1.23.0] — 🩺 The health system tells the truth (2026-07-11)

Fixes from the full dex-core audit (every finding independently verified before fixing).

**What this fixes for you:**

* **Dex's per-session health check now actually runs.** It was silently skipped on every real install — it looked for a folder layout that only existed on the developer's machine. It now runs when you start a session, stays silent when everything is healthy, and says so if it can't run at all.
* **The background-job checker no longer looks away from real breakage.** It used to skip system paths entirely, which hid the exact class of failure users hit (a background job pointing at a piece of software that isn't there). It now checks directly that every Dex background job can actually start.
* **The changelog-checker background job works on Apple Silicon.** It was looking for a piece of software in a location that only exists on older Intel Macs, so on modern Macs it failed every six hours, forever, without a word. Dex now finds where that software actually lives — and refuses to set up a background job that can't run.
* **Instructions match reality (shipped in 1.22.x line).** Ten places where Dex's own instructions described things that weren't true — search tools named wrongly in the daily commands, the Granola check looking at a file nothing reads, optional Apple Reminders calls that weren't marked optional, and references to files that don't exist.

---

## [1.22.0] — 🧹 Behind the scenes: Dex stops bundling a coding tool nobody was using (2026-07-10)

Every copy of Dex was carrying files for Pi — a separate coding tool that lives in its own
project and was never part of Dex itself. Nobody using Dex needed them, so they've been taken
out, along with a broken shortcut and the leftover settings pointing at them.

Nothing you use changes. Pi carries on exactly as before in its own right; it's simply no
longer riding along inside Dex.

---

## [1.21.0] — 🧹 Behind the scenes: four features removed that were never actually switched on (2026-07-10)

Four things had been sitting inside Dex that you could never actually use: a screen-recording
connection, an early-access gating system, a commitment detector, and a demo mode. The services
behind all of them were never switched on in anyone's install, so none of it could ever run.

They're now gone, along with their setup skills, settings, sample data and documentation.
Nothing you could use has been taken away, because none of this was reachable in the first
place. Your analytics choice is unaffected — that has always been its own separate setting.

---

## [1.20.1] — 🔧 Fixes: a false startup alarm, blocked tasks, and the budget model (2026-06-02)

A round of fixes for small things that were quietly getting in the way.

**What this fixes for you:**

* **No more false "your install is broken" alarm.** On startup, Dex sometimes warned that "0/8 MCP servers ready" and that it "may need reinstalling" — even when everything was working perfectly. It was looking in the wrong folder. Fixed.
* **Tasks won't get wrongly rejected.** Adding a task could fail with "priority limit exceeded" even when you only had a couple of tasks at that level, because Dex was miscounting and reading the priority from the wrong place. It now reads your real backlog correctly.
* **The budget AI model works again.** The low-cost option still pointed at a Google model that has since been retired, so it could fail. It now uses the current Gemini 2.5 Flash (still around 90% cheaper than Claude).
* **Behind the scenes:** the automated checks that run on every release no longer fail spuriously, so Dex's own update pipeline is healthy again.

Nothing to do on your end — just update.

---

## [1.20.0] - Granola Meetings Now Sync Through the Official API (2026-06-01)

For a while, Dex pulled your Granola meetings by reading Granola's local files on your machine. That worked until Granola encrypted those files in v7.162.6, and the local route quietly stopped being viable.

Dex now connects to Granola the supported way: through Granola's official public API. It pulls both your notes and your transcripts directly from Granola, so nothing depends on poking around in local files anymore.

**What this means for you:**

* Meeting sync uses Granola's official, supported API, so there is no more reading of local files
* Both your notes and full transcripts come through
* It keeps working through Granola updates, including encryption changes

**To connect:** Run `/granola-setup` and Dex will walk you through adding your Granola API key. API access comes with Granola's Business plan, which is available to individuals, not just companies, at $14 a month. You do not need a big corporate plan.

---

## [1.19.0] — Semantic Search Now Covers Your Entire Vault (2026-03-23)

### 🔍 Semantic Search Now Covers Your Entire Vault

**Before:** Smart search only covered 6 folders — meetings, people, projects,
accounts, tasks, and goals. Finding anything in your PRDs, plans, or session
learnings required remembering exact keywords.

**Now:** Semantic search covers 14 collections across your whole vault.
PRDs, implementation plans, session learnings, and resource docs are all
searchable by meaning.

**Result:** Ask "what did we decide about notifications?" or "find past work
on MCP integration" — Dex finds the right content wherever it lives.

**To pick up new collections:** Run `/enable-semantic-search`.

---

## [1.18.3] — Fix Python Install on Modern Macs + Atlassian MCP Config (2026-03-21)

**Python/pip fix (affects most macOS users with Homebrew):**

`install.sh` and `/dex-update` used `pip3` to install Python helpers, which fails on modern Macs with Homebrew Python (and recent Linux) due to a Python safety rule called PEP 668 — the system refuses direct pip installs. The `--user` fallback also fails in many setups.

Dex now creates a private sandboxed Python environment (`.venv/`) inside your vault folder and installs all dependencies there. This works on all platforms and never touches your system Python.

**What changed:**
* `install.sh` creates `.venv/` and installs deps via the venv pip — no more PEP 668 errors
* `.mcp.json` now points MCP servers to the venv Python instead of system `python3`
* `/dex-update` uses the venv pip when updating dependencies, creating the venv first if upgrading from an older Dex install
* Windows path handled automatically (`.venv/Scripts/python.exe`)

**Atlassian MCP fix:**

`/atlassian-setup` and `.mcp.json.example` referenced `@anthropic/atlassian-mcp` — a package that doesn't exist on npm. Atlassian's official MCP is a remote server, not an npm package.

**What changed:**
* Atlassian MCP config now uses `mcp-remote@latest` pointing to `https://mcp.atlassian.com/v1/sse`
* No credentials needed in the config — authentication is handled via the OAuth browser flow

**What you need to do:** Run `/dex-update` to get these fixes. If your install previously failed on the Python step, run `./install.sh` again.

---

## [1.18.2] — Fix Background Meeting Sync Installation (2026-03-12)

`install-automation.sh` failed because it referenced two files that no longer exist: `granola-auth.cjs` (deprecated — Granola now stores credentials in `supabase.json` automatically) and `sync-from-granola-v2.cjs` (never shipped — v1 works fine).

**What changed:**

* Plist template now points to `sync-from-granola.cjs` (the script that actually exists)
* Install script checks for `supabase.json` instead of calling the removed `granola-auth.cjs`
* No more interactive browser auth step — Granola handles credentials automatically
* `--auth` flag now checks credential status instead of launching a dead script

**What you need to do:** Run `./install-automation.sh` again — it should complete without errors now.

---

## [1.18.1] — Meeting Sync Now Works Reliably Again (2026-03-05)

In v1.17.0, I switched background meeting sync to use Granola's official MCP server — thinking the "official" route would be more reliable. Turns out, the MCP server sends meeting data back in a format designed for AI to read in conversation, not for code to process in the background. The sync script expected structured data, got free-form text, couldn't make sense of it, and quietly fell back to old cached data. Meetings were going missing with no error message.

I've switched to using Granola's direct API instead. It returns clean structured data, includes mobile recordings, and uses the same credentials Granola already stores on your machine — no separate sign-in needed.

**What this means for you:**

* Meeting sync is reliable again — no more silent failures
* Mobile recordings still sync (that wasn't the problem — the data source was)
* One fewer thing to authenticate: no separate Granola MCP sign-in step
* If you previously ran through the MCP OAuth setup, you don't need to do anything — the new approach uses your existing Granola sign-in automatically

**What changed under the hood:**

* Background sync now uses Granola's direct API (`api.granola.ai`) instead of the MCP server
* Removed `granola-mcp-client.cjs`, `granola-auth.cjs`, and `check-granola-migration.cjs` — no longer needed
* Local cache remains as fallback for offline scenarios

---

## [1.18.0] — Intelligent Model Routing Metadata + Safer Skill Updates (2026-03-02)

Dex skills now carry explicit model-routing metadata so cheap/fast models can be used for simple work while higher-tier models stay reserved for heavier thinking.

**What this means for you:**
- Many built-in skills now declare `model_hint` or `model_routing` in `SKILL.md`
- Routing metadata is now standardized across the core skill catalog
- Update flow now has a skill-aware conflict resolver for routing metadata

**Conflict handling improvement:**
- During `/dex-update`, conflicted skill files can now be auto-resolved by:
  - keeping your local skill instructions/custom edits
  - merging upstream routing metadata (`model_hint`, `model_routing`)
  - skipping `*-custom` skills completely

This reduces update friction for users who customize built-in skills while still letting new model-routing behavior land safely.

---

## [1.17.0] — Mobile Meeting Recordings Now Sync Automatically (2026-03-01)

If you record meetings on your phone with Granola, those recordings now appear in Dex alongside your desktop meetings. No manual import, no extra steps — they just show up.

This is powered by Granola's official integration, which means it's more reliable and officially supported. Dex will prompt you to sign in to Granola in your browser (takes about 10 seconds), and after that, mobile recordings sync automatically in the background.

**What this means for you:**
- Meetings recorded on your phone now appear in Dex alongside desktop recordings
- One-time sign-in: Dex prompts you when it's time, and walks you through it
- Everything keeps working while you set up — your existing meetings aren't affected

**Behind the scenes:**
- Background sync now uses Granola's official MCP server instead of a custom integration
- Automatic fallback to local data if the cloud connection is temporarily unavailable
- Migration detection tells you when the upgrade is available — no guesswork

**If you set up Dex before this update:** Run `/dex-update` and Dex will detect the upgrade opportunity. When you next run `/process-meetings`, it'll offer to connect you to Granola's official API.

---

## [1.16.0] — 🕷️ Scrapling is your default web scraper (2026-03-01)

When you share a URL with Dex — an article, a blog post, a page you want summarized — it now uses **Scrapling** every time. Scrapling is free, runs on your machine, and handles sites that block other tools (including Cloudflare-protected pages).

**What this means for you:**
- Share a URL, get the content. No API keys, no credits, no limits.
- Sites that used to come back empty (anti-bot protection) now work out of the box.
- Your data never leaves your machine — Scrapling fetches locally, not through a cloud service.

**What changed under the hood:** Dex now has a safety guard that enforces Scrapling as the default. If the AI ever tries to use a different scraper, the guard catches it and redirects to Scrapling automatically. You don't need to do anything — it just works.

**If you set up Dex before this update:** Run `/dex-update` and Scrapling will be added to your tools automatically. If it asks you to install it, just run: `pip install "scrapling[ai]" && scrapling install`

---

## [1.15.0] — 🔌 The Integrations Release (2026-02-19)

This is a big one. Dex now connects to 8 tools where your real work happens — and it goes both ways. Complete a task in Dex and it's done in Todoist. Get an email flagged in your morning plan because someone hasn't replied in 3 days. See your Jira sprint status right next to your weekly priorities.

Some of you have already been building your own integrations using `/create-mcp` and `/integrate-mcp` — and honestly, that's impressive. But Dave kept hearing the same thing: "I just want to get up and running without figuring out the plumbing." So it's built in now.

---

### 🔗 8 integrations, ready to go

Each one takes a few minutes to set up. Run the command, answer a couple of questions, and you're connected. Dex tells you exactly what changed — which skills got smarter, what new capabilities unlocked.

**Communication:**
- **Slack** (`/slack-setup`) — Chat context in your daily plan and meeting prep. Unread DMs, mentions, active threads. No admin approval needed — just Slack open in Chrome. 2-minute setup.
- **Google Workspace** (`/google-workspace-setup`) — Gmail, Google Calendar, and Docs in one connection. Email digest in your morning plan. Follow-up detection flags emails waiting for replies: "Sarah hasn't replied to your pricing email from Monday." Meeting prep shows recent email exchanges with attendees. 3-minute setup.
- **Microsoft Teams** (`/ms-teams-setup`) — Same as Slack but for Teams users. Works alongside Slack — both digests appear, clearly labeled. If your company uses both, Dex handles both.

**Task Management:**
- **Todoist** (`/todoist-setup`) — Two-way task sync. Create in Dex, appears in Todoist. Complete on your phone, done in Dex. Your pillars map to Todoist projects. 1-minute setup.
- **Things 3** (`/things-setup`) — Two-way sync for Mac users. No account needed, works offline, pure local sync via AppleScript. Your pillars map to Things Areas, P0/P1 tasks go straight to Today. 30-second setup.
- **Trello** (`/trello-setup`) — Board sync. Cards become tasks. Move a card to "Done" and it's complete in Dex. Your Kanban board and your task list stay in sync.

**Meetings & Knowledge:**
- **Zoom** (`/zoom-setup`) — Access recordings, schedule meetings. Smart enough to know if Granola already handles your meeting capture so they don't step on each other.
- **Jira + Confluence** (`/atlassian-setup`) — Sprint status in your daily plan. Project health from Jira. Confluence docs surfaced during meeting prep.

### 🔄 Two-way task sync

This is the headline feature. Connect Todoist, Things 3, Trello, or Jira and your tasks flow between systems automatically. One task in Todoist maps to one task in Dex — even though Dex shows it in meeting notes, person pages, and project pages. Complete anywhere, done everywhere.

The sync is safe by design — it creates, completes, and archives. It never deletes anything.

### 👋 New users: pick your stack during onboarding

When new users set up Dex, Step 8 now asks what tools they use. Pick Gmail and Todoist? You'll be walked through connecting both, and at the end Dex shows you exactly what changed: "Your daily plan now includes an email digest. Meeting prep shows recent emails with attendees. Tasks sync both ways with Todoist." Each tool connection ends with a clear summary of what just got smarter.

### ⚡ Existing users: add integrations anytime

Already using Dex? Just run the setup command for any tool:

- `/slack-setup` — Slack
- `/google-workspace-setup` — Gmail + Calendar + Docs
- `/ms-teams-setup` — Microsoft Teams
- `/todoist-setup` — Todoist
- `/things-setup` — Things 3
- `/trello-setup` — Trello
- `/zoom-setup` — Zoom
- `/atlassian-setup` — Jira + Confluence

Or run `/dex-level-up` and Dex will suggest which integrations would make the biggest difference based on what you're already doing.

### 🏢 Corporate environments

Some corporate IT policies restrict access for third-party tools. If you hit a wall during setup — a blocked consent screen, a missing permission — just ask Dex about it. There are often creative workarounds: personal API keys that don't need admin approval, local-only integrations like Things 3 that bypass corporate restrictions entirely. Dex generally finds a way if you give it a go.

### 📋 Smarter daily plans and meeting prep

Every skill that touches your day got more useful:

- **`/daily-plan`** now includes email digest, Slack/Teams digest, external task status, Jira sprint progress, and Trello card updates — all in one view.
- **`/meeting-prep`** pulls in recent email exchanges, Slack/Teams messages, Zoom recordings, Confluence docs, and Jira/Trello context for every attendee.
- **`/week-review`** shows email stats, Zoom meeting time, cross-system task completion, and Jira velocity alongside your existing review.
- **`/project-health`** surfaces Trello board status and Jira sprint health for connected projects.
- **`/dex-level-up`** spots unused integration capabilities — "You connected Gmail but haven't enabled email follow-up detection. Try it."

### 🩺 Integration health

Dex checks whether your connected tools are healthy each time you start a session. If something's gone stale — an expired token, a disconnected service — you'll know right away with a friendly nudge to reconnect, instead of discovering it mid-meeting-prep.

---

## [1.14.0] — 🧠 Dex Got a Brain Upgrade (2026-02-19)

This is the biggest single release since semantic search. Dex remembers things now. It gets smarter each day you use it. Sessions stay fast all day. And your skills take care of their own housekeeping instead of leaving it to you.

---

### 🧠 Memory

**Cross-session memory.** When you start a new chat, Dex now opens with context from previous sessions — what you decided, what's been escalating, what commitments are due. No more re-explaining where you left off. Your daily plan opens with "Based on previous sessions: you discussed Acme Corp 3 times last week, decided to move to negotiation, and Sarah committed to send pricing by Friday — that's today." That context was invisible before. Now it's automatic.

**Critical decisions persist.** When you make an important decision in a session — "decided to move Acme to negotiation by March" — it now survives across sessions. Critical decisions appear at every session start for 30 days, so you never lose track of what you committed to.

**Meeting cache.** Every meeting you process now gets stored as a compact summary instead of the full transcript. Meeting prep and daily planning are dramatically faster — same intelligence, fraction of the processing time.

**Memory that compounds.** The six agents that power your morning intelligence — deals, commitments, people, projects, focus, and pillar balance — now remember what they found in previous sessions. First run, they scan everything. Second run, they know what they already told you. Resolved items quietly drop off. New issues are clearly marked. And things you've been ignoring? Dex notices. "I've flagged this three sessions running. Still no action. This is a pattern, not a blip."

**Faster people lookups.** Dex now keeps a lightweight directory of everyone you know. Instead of scanning dozens of files every time you mention someone, it reads one small index. Looking up "Paul" instantly returns the right person with their role, company, and context. The index stays fresh automatically — it rebuilds during your daily plan and self-heals if it goes stale.

**Memory ownership, clarified.** With multiple memory layers now active, Dave has documented exactly what owns what. Claude's built-in memory handles your preferences and communication style. Dex's memory handles your work — who said what in which meeting, what you committed to, which deals need attention. They stack, not compete. See the new Memory Ownership guide in your Dex System docs.

---

### 🔍 Intelligence

**Pattern detection.** After 2+ weeks of use, Dex starts noticing your patterns. "You've prepped for deal calls 8 times this month but checked MEDDPICC gaps only twice." Recurring mistakes get surfaced before you make them. Emerging workflows get noticed so you can turn them into skills.

**Identity snapshot.** Dex now automatically builds a living profile of how you actually work — your goals, priorities, task patterns, learnings, and skill ratings all feed into it. Not self-reported traits — observed patterns. What pillar gets neglected under pressure. Which skills you rate highest. Where your blind spots are. It refreshes during weekly reviews and Dex reads it when making prioritization suggestions. You can also run `/identity-snapshot` anytime to see it on demand.

**Skill quality signals.** After key workflows like daily plans, meeting prep, and reviews, Dex asks one optional question: "Quick rating, 1-5?" Your ratings accumulate over time. During weekly reviews, if a skill has been trending down, Dex surfaces it with context — "Your meeting prep averaged 2.8 this week, common note: missing context from last meeting." If everything's fine, you hear nothing. Ratings also feed into anonymous product analytics so Dave knows which skills to invest in.

---

### ⚡ Performance & Safety

**Sessions that last all day.** Your heaviest skills — daily plan, weekly review, meeting prep, and seven others — now run in their own space instead of loading everything into your main conversation. Previously, running `/daily-plan` then staying in that chat all day meant things got slower and muddier by the afternoon. Now each skill does its work separately and hands back just the result. Stay in one chat from morning planning through end-of-day review without penalty.

**Command safety guard.** A protective layer that silently watches every terminal command and blocks catastrophic ones before they execute. Disk wipes, force pushes to main, repo deletions — all stopped instantly. Normal commands pass through with zero overhead. You never notice it until the one time it saves you.

**Faster startup and routing.** Background services start faster and use less memory. Quick operations like `/triage` and inbox processing are tuned for speed — routing decisions that used to take 8 seconds now feel instant.

---

### 🤖 Skills That Take Care of Themselves

- **Meeting processing** — whenever meetings are processed, every person mentioned gets the meeting added to their page. Their history stays current without you lifting a finger.
- **Career coaching** — when `/career-coach` surfaces achievements with real metrics, it automatically logs them to your Career Evidence file. Come review season, the evidence is already collected.
- **Daily planning** — after your plan generates, a condensed quickref appears with just your top focus items, key meetings, and time blocks. Glanceable during the day.

---

### 📚 New Guides

Named Sessions (resume project conversations with full history), Background Processing (which skills support it and how), Memory Ownership (how Dex's four memory layers work together), and Vault Maintenance (scan for stale files, broken links, orphaned pages).

---

### 🙏 Community

This is the first time Dex has received contributions from the community, and I'm genuinely humbled. Three people independently found things to improve, built the fixes, and shared them back. All four contributions are now live.

**@fonto — Calendar setup now works.** Previously, running `/calendar-setup` didn't do anything — Dex couldn't find it. On top of that, when it tried to ask your Mac for permission to read your calendar, it would fail silently. Both issues are fixed. If you had trouble connecting your calendar before, try `/calendar-setup` again — it should just work now.

**@fonto — Tasks no longer get mixed up.** Every task in Dex gets a short reference number (like the `003` at the end of a task). Previously, that number could accidentally be the same for tasks created on different days — so when you said "mark 003 as done", Dex might match the wrong one. Now every task gets a number that's unique across your entire vault. No more mix-ups.

**@acottrell — "How do I connect my Google Calendar?" answered.** If you use Google Calendar on a Mac, you probably wondered how to get your meetings into Dex. The answer turns out to be surprisingly simple — add your Google account to Apple's Calendar app (the one already on your Mac), then let Cursor access it. Two steps, no accounts to create, no passwords to enter anywhere. @acottrell wrote this up as a clear guide so nobody else has to figure it out from scratch. Even better — your calendar now asks for permission automatically the first time you need it, instead of requiring a separate setup step.

**@mekuhl — Capture tasks from your phone with Siri.** This is the big one. You're in a meeting, someone asks you to do something, and you don't want to open your laptop. Now you can just say:

> **"Hey Siri, add to Dex Inbox: follow up with Sarah about pricing"**

That's it. Siri adds it to a Reminders list on your phone called "Dex Inbox." Next morning when you run `/daily-plan`, Dex finds it and asks you to triage it — assign a pillar, set the priority, and it becomes a proper task in your vault. The Reminder disappears from your phone automatically.

It works the other direction too. After your daily plan generates, your most important focus tasks appear on your phone as Reminders with notifications. Complete something on your phone? Dex picks that up during your evening review. Complete it in Dex? The phone notification clears itself.

Your phone and your vault stay in sync — without opening a laptop, without any new apps, without any setup beyond saying "Hey Siri" for the first time.

If you've made improvements to your Dex setup that could help others, Dave would love to see them. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to share — no technical background required.

---

## [1.10.0] - 2026-02-17

### 🩺 Dex Now Tells You When Something's Wrong

**Before:** When something failed — your calendar couldn't connect, a task couldn't be created, meeting processing hit an error — you'd get a vague message in the conversation and then... nothing. The error disappeared when the chat ended. If something was quietly broken for days, you wouldn't know until you needed it and wondered why it stopped working.

**Now:** Dex watches its own health. Every tool across all 12 background services captures failures the moment they happen — in plain language, not technical jargon. The next time you start a conversation, you'll see anything that went wrong:

```
--- ⚠️ Recent Errors (2) ---
  [Task Manager] Feb 17 09:30 — Task creation failed (×3)
  [Calendar] Feb 16 14:00 — Calendar couldn't connect
Say: 'health check' to investigate
---
```

If everything is fine? Complete silence. No "all systems go" noise.

**Say `/health-check` anytime** to get a full diagnostic: which services are running, what's failed recently, and — for most issues — a suggested fix. Missing something? It tells you the exact command. Config issue? It offers to repair it.

**What this means for you:** Instead of discovering something's been broken for a week, you find out at your next conversation. Instead of a cryptic error, you get "Calendar couldn't connect" with a clear next step. Dex is becoming the kind of system that takes care of itself — and tells you when it needs your help.

**Platform note:** Automatic startup checks work in Claude Code. In Cursor, the error capture still works behind the scenes — just run `/health-check` manually to see the same diagnostic.

---

## [1.9.1] - 2026-02-17

### Automatic Update Notifications

Previously, you had to remember to run `/dex-update` to check for new versions. Now Dex checks once a day automatically and lets you know if there's something new — a quiet one-liner at the end of your first chat, once per day. No nagging, no blocking. Run `/dex-update` when you're ready, or ignore it.

**One catch:** You need to run `/dex-update` manually one time to get this feature. That update pulls in the automatic checking. From that point on, you'll be notified whenever something new is available — no more remembering to check.

---

## [1.9.0] - 2026-02-17

### 🔍 Optional: Smarter Search for Growing Vaults

You might be thinking: "Dex already uses AI — doesn't it search intelligently?" Good question. Here's what's actually happening under the hood.

When you ask Dex something like "what do I know about customer retention?", two things happen:

1. **Finding the files** — Dex searches your vault for relevant notes
2. **Making sense of them** — Claude reads those notes and gives you a smart answer

Step 2 has always been intelligent — that's Claude doing what it does best. But Step 1? Until now, that's been basic keyword matching. Dex literally searches for the word "retention" in your files. If you wrote about the same topic using different words — "churn", "users leaving", "cancellation patterns" — those notes never made it to Claude's desk. It can't reason about things it never sees.

**That's what semantic search fixes.** It upgrades Step 1 — the finding — so the right notes reach Claude even when the words don't match.

It's also significantly faster and lighter. Instead of Claude reading entire files to find what's relevant (thousands of tokens each), the search engine returns just the relevant snippets. One developer measured a 96% reduction in the amount of context needed per search.

**When does this matter?** Honestly, if your vault has fewer than 50 notes, keyword matching works fine. As your vault grows into the hundreds of files, keyword search starts missing things — and that's where this upgrade earns its keep.

---

This is powered by [QMD](https://github.com/tobi/qmd), an open-source local search engine created by Tobi Lütke (founder and CEO of Shopify). Everything runs on your machine — no data leaves your computer.

> "I think QMD is one of my finest tools. I use it every day because it's the foundation of all the other tools I build for myself. A local search engine that lives and executes entirely on your computer. Both for you and agents." — [Tobi Lütke](https://x.com/tobi/status/2013217570912919575)

**Setup required.** Semantic search is available but requires running `/enable-semantic-search` to set it up (5 min, 2.5GB download). New users are offered this during onboarding. Once enabled, all vault searches automatically use semantic matching instead of keyword-only — skills don't change, the AI routing layer gets smarter and uses QMD when available.

**What gets better when you enable it:**

- **Planning & Reviews** — `/daily-plan`, `/week-plan`, `/daily-review`, `/week-review`, and `/quarter-review` all become meaning-aware. Your morning plan surfaces notes related to today's meetings by theme ("onboarding" pulls in "activation rates"). Your weekly review detects which tasks contributed to which goals — even when they weren't explicitly linked. Stale goals get flagged with hidden activity you didn't know about.

- **Meeting Intelligence** — `/meeting-prep` finds past discussions related to the meeting topic, not just meetings with the same people. `/process-meetings` catches implicit commitments like "we should circle back on pricing" — soft language that keyword extraction would miss.

- **Search & People** — All vault searches become meaning-aware. Person lookup finds references by role ("the VP of Sales asked about..."), not just by name.

- **Smarter Dedup** — Task creation detects semantic duplicates ("Review Q1 metrics" matches "Check quarterly pipeline numbers"). Same for improvement ideas in your backlog.

- **Natural Task Completion** — Say "I finished the pricing thing" and Dex matches it to the right task, even when your words don't match the title exactly.

- **Career Tracking** — If you use the career system, skill demonstration is now detected without explicit `# Career:` tags. "Designed the API migration strategy" automatically matches your "System Design" competency.

**If you don't enable it,** nothing changes — everything continues to work with keyword matching, just as it always has.

Part of the philosophy with Dex is to stay on top of the best open-source tools so you don't have to. When something like QMD comes along that genuinely makes the experience better, Dave integrates it — you run one command and your existing workflows get smarter.

**Smart setup, not generic indexing.** When you run `/enable-semantic-search`, Dex scans your vault and recommends purpose-built search collections based on what you've actually built — people pages, meeting notes, projects, goals. Each collection gets semantic context that tells the search engine what the content IS, dramatically improving result relevance. Generic tools dump everything into one index. Dex gives your search engine a mental model of your information architecture.

As your vault grows, Dex notices. Created your first few company pages? Next time you run `/daily-plan`, it'll suggest: "You've got enough accounts for a dedicated collection now — want me to create one?" Your search setup evolves with your vault.

**To enable:** `/enable-semantic-search` (one-time setup, ~5 minutes)

---

## [1.8.0] - 2026-02-16

### 📊 Your Usage Now Shapes What Gets Built Next

**Before:** If you opted in to help improve Dex, your anonymous usage data wasn't being captured consistently across all features. Some areas were tracked, others weren't — so the picture of which features people find most valuable was incomplete.

**Now:** Every Dex feature — all 30 skills and 6 background services — now reports usage when you've opted in. You'll also notice the opt-in prompt appears at the start of each session (instead of only during planning), so you won't miss it. Say "yes" or "no" once and it's settled — if you're not ready to decide, it'll gently ask again next time.

When you run `/dex-update`, any new features automatically appear in your usage log without losing your existing data. And as new capabilities ship in the future, they'll always include tracking from day one.

**Result:** If you've opted in, you're directly influencing which features get priority. The most-used capabilities get more investment — your usage data is the signal.

---

## [1.7.0] - 2026-02-16

### ✨ Smoother Onboarding — Clickable Choices & Cross-Platform Support

**Before:** During setup, picking your role meant scrolling through a wall of 31 numbered options and typing a number. If your Mac's Calendar app was running in the background (but not in the foreground), Dex couldn't detect your calendars — silently skipping calendar optimization. And if you onboarded in Cursor vs Claude Code, the question prompts might not work because each platform has a different tool for presenting clickable options.

**Now:** Role selection, company size, and other choices are presented as clickable lists — just pick from the menu. Dex detects your platform once at the start (Cursor vs Claude Code vs terminal) and uses the right question tool throughout. Calendar detection works regardless of whether Calendar.app is in the foreground or background. QA testing uses dry-run mode so nothing gets overwritten.

**Result:** Onboarding feels polished — fewer things to type, fewer silent failures, works correctly whether you're in Cursor or Claude Code.

---

## [1.6.0] - 2026-02-16

### ✨ Dex Now Discovers Its Own Improvements

**Before:** When new Claude Code features shipped or you had ideas for how Dex could work better, it was up to you to remember them and add them to your backlog. Keeping track of what could be improved meant extra manual work.

**Now:** Dex watches for opportunities to get better and weaves them into your existing routines:

- `/dex-whats-new` spots relevant Claude Code releases and turns them into improvement ideas in your backlog
- `/daily-plan` highlights the most timely idea as an "Innovation Spotlight" when something new is relevant (e.g., "Claude just shipped native memory — here's how that could help")
- `/daily-review` connects today's frustrations to ideas already in your backlog
- `/week-review` shows your top 3 highest-scored improvement ideas
- Say "I wish Dex could..." in conversation and it's captured automatically — no duplicates

**Result:** Your improvement backlog fills itself. Ideas arrive from AI discoveries and your own conversations, get ranked by impact, and surface at the right moment during planning and reviews.

---

## [1.5.0] - 2026-02-15

### 🔧 All Your Granola Meetings Now Show Up

**Before:** Some meetings recorded on mobile or edited in Granola's built-in editor wouldn't appear in Dex — they'd be invisible during meeting prep and search.

**Now:** Dex handles all the ways Granola stores your notes, so every meeting comes through — regardless of how or where you recorded it.

**Result:** If Granola has your notes, Dex will find them. No meetings slip through the cracks.

---

## [1.4.0] - 2026-02-15

### 🔧 Dex Now Always Knows What Day It Is

**Before:** Dex relied entirely on the host platform (Cursor, Claude Code) to tell Claude the current date. If the platform didn't surface it prominently, Claude could lose track of what day it was — especially frustrating during daily planning or scheduling conversations.

**Now:** The session-start hook explicitly outputs today's date at the very top of every session context injection, so it's front-and-center regardless of platform behavior.

**Result:** No more "what day is it?" confusion. Dex always knows the date, every session, every platform.

---

## [1.3.0] - 2026-02-05

### 🎯 Smart Pillar Inference for Task Creation

**What was frustrating:** Every time you asked to create a task ("Remind me to prep for the Acme demo"), Dex would stop and ask: "Which pillar is this for?" This added friction to quick captures and broke your flow.

**What's different now:** Dex analyzes your request and infers the most likely pillar based on keywords:
- "Prep demo for Acme Corp" → **Deal Support** (demo + customer keywords)
- "Write blog post about AI" → **Thought Leadership** (content keywords)
- "Review beta feedback" → **Product Feedback** (feedback keywords)

Then confirms with a quick one-liner:
> "Creating under Product Feedback pillar (looks like data gathering). Sound right, or should it be Deal Support / Thought Leadership?"

**Why you'll care:** Fast task capture with data quality. No more back-and-forth just to add a reminder. But your tasks still have proper strategic alignment.

**Customization options:** Want different behavior? You can customize this in your CLAUDE.md:
- **Less strict:** Remove the pillar requirement entirely and use a default pillar
- **Triage flow:** Route quick captures to `00-Inbox/Quick_Captures.md`, then sort them during `/triage` (skill you can build yourself or request)
- **Your own keywords:** Edit `System/pillars.yaml` to add custom keywords for better inference

**Technical:** Updated task creation behavior in `.claude/CLAUDE.md` to include pillar inference logic. The work-mcp validation still requires a pillar (maintains data integrity), but Dex now handles the inference and confirmation before calling the MCP.

---

### ⚡ Calendar Queries Are Now 30x Faster (30s → <1s)

**Before:** Asking "what meetings do I have today?" meant waiting up to 30 seconds for a response. Old events from weeks ago sometimes appeared in today's results too.

**Now:** Calendar queries respond in under a second and only show events for the dates you asked about. No more waiting, no more ghost events.

**One-time setup:** After updating, run `/calendar-setup` to grant calendar access. This unlocks the faster queries. If you skip this step, everything still works — just slower.

---

### 🐛 Paths Now Work on Any Machine

**Before:** A few features — Obsidian integration and background automations — didn't work correctly on some setups.

**Now:** All paths resolve dynamically based on where your vault lives. Everything works regardless of your username or folder structure.

**How to update:** In Cursor, just type `/dex-update` — that's it!

**Thank you** to the community members who reported this. Your feedback makes Dex better for everyone.

---

### 🔬 X-Ray Vision: Learn AI by Seeing What Just Happened

**What was frustrating:** Dex felt like a black box. You knew it was helping, but you had no idea what was actually happening — which tools were firing, how context was loaded, or how you could customize the system. Learning AI concepts felt abstract and disconnected from your actual experience.

**What's new:** Run `/xray` anytime to understand what just happened in your conversation.

**Default mode (just `/xray`):** Shows the work from THIS conversation:
- What files were read and why
- What tools/MCPs were used
- What context was loaded at session start (and how)
- How each action connects to underlying AI concepts

**Deep-dive modes:**
- `/xray ai` — First principles: context windows, tokens, statelessness, tools
- `/xray dex` — The architecture: CLAUDE.md, hooks, MCPs, skills, vault structure
- `/xray boot` — The session startup sequence in detail
- `/xray today` — ScreenPipe-powered analysis of your day
- `/xray extend` — How to customize: edit CLAUDE.md, create skills, write hooks, build MCPs

**The philosophy:** The best way to learn AI is by examining what just happened, not reading abstract explanations. Every `/xray` session connects specific actions (I read this file because...) to general concepts (...CLAUDE.md tells me where files live).

**Where you'll see it:**
- Run `/xray` after any conversation to see "behind the scenes"
- Educational concepts are tied to YOUR vault and YOUR actions
- End with practical customization opportunities

**The goal:** You're not just a user — you're empowered to extend and personalize your AI system because you understand the underlying mechanics.

---

### 🔌 Productivity Stack Integrations (Notion, Slack, Google Workspace)

**What was frustrating:** Your work context is scattered across Notion, Slack, and Gmail. When prepping for meetings, you manually search each tool. When looking up a person, you don't see your communication history with them.

**What's new:** Connect your productivity tools to Dex for richer context everywhere:

1. **Notion Integration** (`/integrate-notion`)
   - Search your Notion workspace from Dex
   - Meeting prep pulls relevant Notion docs
   - Person pages link to shared Notion content
   - Uses official Notion MCP (`@notionhq/notion-mcp-server`)

2. **Slack Integration** (`/integrate-slack`)
   - "What did Sarah say about the Q1 budget?" → Searches Slack
   - Meeting prep includes recent Slack context with attendees
   - Person pages show communication history
   - Easy cookie auth (no bot setup required) or traditional bot tokens

3. **Google Workspace Integration** (`/integrate-google`)
   - Gmail thread context in person pages
   - Email threads with meeting attendees during prep
   - Calendar event enrichment
   - One-time OAuth setup (~5 min)

**Where you'll see it:**
- `/meeting-prep` — Pulls context from all enabled integrations
- Person pages — Integration Context section with Slack/Notion/Email history
- New users — Onboarding Step 9 offers integration setup
- Existing users — `/dex-update` announces new integrations, detects your existing MCPs

**Smart detection for existing users:**
If you already have Notion/Slack/Google MCPs configured, Dex detects them and offers to:
- Keep your existing setup (it works!)
- Upgrade to Dex recommended packages (better maintained, more features)
- Skip and configure later

**Setup commands:**
- `/integrate-notion` — 2 min setup (just needs a token)
- `/integrate-slack` — 3 min setup (cookie auth or bot token)
- `/integrate-google` — 5 min setup (OAuth through Google Cloud)

---

### 🔔 Ambient Commitment Detection (ScreenPipe Integration) [BETA]

**What was frustrating:** You say "I'll send that over" in Slack or get asked "Can you review this?" in email. These micro-commitments don't become tasks — they fall through the cracks until someone follows up (awkward) or they're forgotten (worse).

**What's new:** Dex now detects uncommitted asks and promises from your screen activity:

1. **Commitment Detection** — Scans apps like Slack, Email, Teams for commitment patterns
   - Inbound asks: "Can you review...", "Need your input...", "@you"
   - Outbound promises: "I'll send...", "Let me follow up...", "Sure, I'll..."
   - Deadline extraction: "by Friday", "by EOD", "ASAP", "tomorrow"

2. **Smart Matching** — Connects commitments to your existing context
   - Matches people mentioned to your People pages
   - Matches topics to your Projects
   - Matches keywords to your Goals

3. **Review Integration** — Surfaces during your rituals
   - `/daily-review` shows today's uncommitted items
   - `/week-review` shows commitment health stats
   - `/commitment-scan` for standalone scanning anytime

**Example during daily review:**
```
🔔 Uncommitted Items Detected

1. Sarah Chen (Slack, 2:34 PM)
   > "Can you review the pricing proposal by Friday?"
   📎 Matches: Q1 Pricing Project
   → [Create task] [Already handled] [Ignore]
```

**Privacy-first:**
- Requires ScreenPipe running locally (all data stays on your machine)
- Sensitive apps excluded by default (1Password, banking, etc.)
- You decide what becomes a task — nothing auto-created

**Beta activation required:**
- Run `/beta-activate DEXSCREENPIPE2026` to unlock ScreenPipe features
- Then asked once during `/daily-plan` or `/daily-review` to enable
- Must explicitly enable before any screen data is accessed
- New users can also run `/screenpipe-setup` after beta activation

**New skills:**
- `/commitment-scan` — Scan for uncommitted items anytime
- `/screenpipe-setup` — Enable/disable ScreenPipe with privacy configuration

**Why you'll care:** Never forget a promise or miss an ask again. The things you commit to in chat apps now surface in your task system automatically.

**Requirements:** ScreenPipe must be installed and opted-in. See `06-Resources/Dex_System/ScreenPipe_Setup.md` for setup.

---

### 🤖 AI Model Flexibility: Budget Cloud & Offline Mode

**What was frustrating:** Dex only worked with Claude, which costs money and requires internet. Heavy users faced high API bills, and travelers couldn't use Dex on planes or trains.

**What's new:** Two new ways to use Dex:

1. **Budget Cloud Mode** — Use cheaper AI models like Kimi K2.5 or DeepSeek when online
   - Save 80-97% on API costs for routine tasks
   - Requires ~$5-10 upfront via OpenRouter
   - Quality is great for daily tasks (summaries, planning, task management)

2. **Offline Mode** — Download an AI to run locally on your computer
   - Works on planes, trains, anywhere without internet
   - Completely free forever
   - Requires 8GB+ RAM (16GB+ recommended)

3. **Smart Routing** — Let Dex automatically pick the best model
   - Claude for complex tasks
   - Budget models for simple tasks
   - Local model when offline

**New skills:**
- `/ai-setup` — Guided setup for budget cloud and offline mode
- `/ai-status` — Check your AI configuration and credits

**Why you'll care:** Reduce your AI costs by 80%+ for everyday tasks, or work completely offline during travel — your choice.

**User-friendly:** The setup is fully guided with plain-language explanations. Dex handles the technical parts (starting services, downloading models) automatically.

---

### 📊 Help Dave Improve Dex (Optional Analytics)

**What's this about?**

Dave could use your help making Dex better. This release adds optional, privacy-first analytics that lets you share which Dex features you use — not what you do with them, just that you used them.

**What gets tracked (if you opt in):**
- Which Dex built-in features you use (e.g., "ran /daily-plan")
- Nothing about what you DO with features
- No content, names, notes, or conversations — ever

**What's NOT tracked:**
- Custom skills or MCPs you create
- Any content you write or manage
- Who you meet with or what you discuss

**The ask:**

During onboarding (new users) or your next planning session (existing users), Dex will ask once:

> "Dave could use your help improving Dex. Help improve Dex? [Yes, happy to help] / [No thanks]"

Say yes, and you help Dave understand which features work and which need improvement. Say no, and nothing changes — Dex works exactly the same.

**Technical:**
- Added `analytics_helper.py` in `core/mcp/`
- Consent tracked in `System/usage_log.md`
- Events only fire if `analytics.enabled: true` in user-profile.yaml
- 20+ skills now have analytics hooks

**Beta only:** This feature is currently in beta testing.

---

## [1.2.0] - 2026-02-03

### 🧠 Planning Intelligence: Your System Now Thinks Ahead

**What's this about?**

Until now, daily and weekly planning showed you information — your tasks, calendar, priorities. But you had to connect the dots yourself. 

Now Dex actively thinks ahead and surfaces things you might have missed.

This is the biggest upgrade to Dex's intelligence since launch. Based on feedback from early users, Dave rebuilt the planning skills to be proactive rather than passive. Dex now does the mental work of connecting your calendar to your tasks, tracking your commitments, and warning you when things are slipping — so you can focus on actually doing the work.

---

**Midweek Awareness**

**Before:** You'd set weekly priorities on Monday, then forget about them until Friday's review. By then it's too late — Priority 3 never got touched.

**Now:** When you run `/daily-plan` midweek, Dex knows where you stand:

> "It's Wednesday. You've completed 1 of 3 weekly priorities. Priority 2 is in progress (2 of 5 tasks done). Priority 3 hasn't been touched yet — you have 2 days left."

**Result:** Course-correct while there's still time. No more end-of-week surprises.

---

**Meeting Intelligence**

**Before:** You'd see "Acme call" on your calendar and have to manually check: what's the status of that project? Any outstanding tasks? What did you discuss last time?

**Now:** For each meeting, Dex automatically connects the dots:

> "You have the Acme call Thursday. Looking at that project: the proposal is still in draft, and you owe Sarah the pricing section. Want to block time for prep?"

**Result:** Walk into every meeting prepared. Related tasks and project status surface automatically.

---

**Commitment Tracking**

**Before:** You'd say "I'll get back to you Wednesday" in a meeting, write it in your notes... and forget. It lived in a meeting note you never looked at again.

**Now:** Dex scans your meeting notes for things you said you'd do:

> "You told Mike you'd get back to him by Wednesday. That's today."

**Result:** Keep your promises. Nothing slips through because it was buried in notes.

---

**Smart Scheduling**

**Before:** All tasks were equal. A 3-hour strategy doc and a 5-minute email sat on the same list with no guidance on when to tackle them.

**Now:** Dex classifies tasks by effort and matches them to your calendar:

> "You have a 3-hour block Wednesday morning — perfect for 'Write Q1 strategy doc' (deep work). Thursday is stacked with meetings — good for quick tasks only."

It even warns you when you have more deep work than available focus time.

**Result:** Stop fighting your calendar. Know which tasks fit which days.

---

**Intelligent Priority Suggestions**

**Before:** `/week-plan` asked "What are your priorities?" and waited. You had to figure it out yourself.

**Now:** Dex suggests priorities based on your goals, task backlog, and calendar shape:

> "Based on your goals, tasks, and calendar, I suggest:
> 1. Complete pricing proposal — Goal 1 needs this for milestone 3
> 2. Customer interviews — Goal 2 hasn't had activity in 3 weeks
> 3. Follow up on Acme — You committed to Sarah by Friday"

You still decide. But now you have a thinking partner who's done the analysis.

**Result:** Start each week with intelligent suggestions, not a blank page.

---

**Concrete Progress (Not Fake Percentages)**

**Before:** "Goal X is at 55%." What does that even mean? Percentages feel precise but communicate nothing.

**Now:** "Goal X: 3 of 5 milestones complete. This week you finished the pricing page and scheduled the customer interviews."

**Result:** Weekly reviews that actually show what you accomplished and what's left.

---

**How it works (under the hood):**

Six new capabilities power the intelligence:

| What Dex can now do | Why it matters |
|---------------------|----------------|
| Check your week's progress | Knows which priorities are on track vs slipping |
| Understand meeting context | Connects each meeting to related projects and people |
| Find your commitments | Scans notes for promises you made and when they're due |
| Judge task effort | Knows a strategy doc needs focus time, an email doesn't |
| Read your calendar shape | Sees which days have deep work time vs meeting chaos |
| Match tasks to time | Suggests what to work on based on available blocks |

**What to try:**

- Run `/daily-plan` on a Wednesday — see midweek awareness in action
- Check `/week-plan` — get intelligent priority suggestions instead of a blank page
- Before a big meeting, run `/meeting-prep` — watch it pull together everything relevant

---

## [1.1.0] - 2026-02-03

### 🎉 Personalize Dex Without Losing Your Changes

**What's this about?**

Many of you have been making Dex your own — adding personal instructions, connecting your own tools like Gmail or Notion, tweaking how things work. That's exactly what Dex is designed for.

But until now, there was a tension: when I release updates to Dex with new features and improvements, your personal changes could get overwritten. Some people avoided updating to protect their setup. Others updated and had to redo their customizations.

This release fixes that. Your personalizations and my updates now work together.

---

**What stays protected:**

**Your personal instructions**

If you've added notes to yourself in the CLAUDE.md file — reminders about how you like things done, specific workflows, preferences — those are now protected. Put them between the clearly marked `USER_EXTENSIONS` section, and they'll never be touched by updates.

**Your connected tools**

If you've connected Dex to other apps (like your email, calendar, or note-taking tools), those connections are now protected too. When you add a tool, Dex automatically names it in a way that keeps it safe from updates.

**New command: `/dex-add-mcp`** — When you want to connect a new tool, just run this command. It handles the technical bits and makes sure your connection is protected. No config files to edit.

---

**What happens when there's a conflict?**

Sometimes my updates will change a file that you've also changed. When that happens, Dex now guides you through it with simple choices:

- **"Keep my version"** — Your changes stay, skip this part of the update
- **"Use the new version"** — Take the update, replace your changes
- **"Keep both"** — Dex will keep both versions so nothing is lost

No technical knowledge needed. Dex explains what changed and why, then you decide.

---

**Why this matters**

I want you to make Dex truly yours. And I want to keep improving it with new features you'll find useful. Now both can happen. Update whenever you like, knowing your personal setup is safe.

---

### 🔄 Background Meeting Sync (Granola Users)

**Before:** To get your Granola meetings into Dex, you had to manually run `/process-meetings`. Each time, you'd wait for it to process, then continue your work. Easy to forget, tedious when you remembered.

**Now:** A background job syncs your meetings from Granola every 30 minutes automatically. One-time setup, then it just runs.

**To enable:** Run `.scripts/meeting-intel/install-automation.sh`

**Result:** Your meeting notes are always current. When you run `/daily-plan` or look up a person, their recent meetings are already there — no manual step needed.

---

### ✨ Prompt Improvement Works Everywhere

**Before:** The `/prompt-improver` command required extra configuration. In some setups, it just didn't work.

**Now:** It automatically uses whatever AI is available — no special configuration needed.

**Result:** Prompt improvement just works, regardless of your setup.

---

### 🚀 Easier First-Time Setup

**Before:** New users sometimes hit confusing error messages during setup, with no clear guidance on what to do next.

**Now:**
- Clear error messages explain exactly what's wrong and how to fix it
- Requirements are checked upfront with step-by-step instructions
- Fewer manual steps to get everything working

**Result:** New users get up and running faster with less frustration.

---

## [1.0.0] - 2026-01-25

### 📦 Initial Release

Dex is your AI-powered personal knowledge system. It helps you organize your professional life — meetings, projects, people, ideas, and tasks — with an AI assistant that learns how you work.

**Core features:**
- **Daily planning** (`/daily-plan`) — Start each day with clear priorities
- **Meeting capture** — Extract action items, update person pages automatically
- **Task management** — Track what matters with smart prioritization
- **Person pages** — Remember context about everyone you work with
- **Project tracking** — Keep initiatives moving forward
- **Weekly and quarterly reviews** — Reflect and improve systematically

**Requires:** Cursor IDE with Claude, Python 3.10+, Node.js
