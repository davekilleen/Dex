
# Changelog

All notable changes to Dex will be documented in this file.

**For users:** Each entry explains what was frustrating before, what's different now, and why you'll care.

---

## [1.96.7] — 🧰 Dex still knows who you are after an update (2026-08-20)

After the first setup, an update could greet you like a stranger. Your name, role, company size, working style, and focus areas snapped back to “Not yet configured,” even though the settings file from setup still had the real values. Nothing warned you.

**What this fixes for you:**

* **Your profile stays after an update.** Dex rereads the settings you already filled in and puts your name, role, company size, working style, and focus areas back into the main instructions. It no longer pretends you never finished setup.
* **A brand-new folder still starts blank.** Until you finish the first setup, those lines stay empty. Dex does not invent a profile.
* **The notes you added for yourself still survive.** The personal-instructions block is unchanged.

Amit Godbole caught this by reading the update preview before approving it.

## [1.96.6] — 🧰 Your promotion score uses real evidence, and Mail search checkup tells the truth (2026-08-17)

The promotion score could look confident while using made-up points. Skills were always 15. Growth was always 5. Evidence sitting in the Evidence folder — the place career setup itself uses — counted as nothing. Separately, Mail search checkup could look healthy when it could not actually see Mail, or when the search index was missing, empty, or unreadable. And if you record meetings with Wispr, Dex already understood those notes, but settings still refused the word Wispr.

**What this fixes for you:**

* **The promotion score now uses your real evidence.** Files in the Evidence folder count. Skills and growth come from that same evidence, not from made-up points. An empty folder scores 0, not 15 or 5.
* **Mail search checkup tells the truth.** If the checkup cannot see your Mail folder, or the search index is missing, empty, or unreadable, it says so. It no longer calls that healthy.
* **You can name Wispr as where meetings come from.** If that is your recorder, you can say so in settings. This does not connect Dex to Wispr or pull meetings on its own. It only stops rejecting the name.

Two people reported the score and the Mail checkup. A contributor found the Wispr name after Dex already recognised their notes.

## [1.96.5] — 🧰 A brand-new Dex folder can finish setup even if first install left no history (2026-08-14)

A person who had just installed Dex could get stuck in the first setup chat. Dex thought it had finished separating its own files from their notes, but the notes folder had no working history, and the safety copy that should have undone that step was damaged. Continue failed. Undo failed. Setup stopped before they could start.

**What this fixes for you:**

* **Dex can rebuild the notes history from the files still in the folder.** Your notes stay put. Dex does not try to put a damaged safety copy back, and it does not invent a history it cannot prove.
* **Install no longer says it is finished when that history is missing.** If the notes folder still has no working history, install stops and tells you the one repair command to run.
* **Undo tells the truth when it cannot go back.** If the old copy is damaged and the notes history is already gone, Dex says the files are still there and that continuing will rebuild from those files. It no longer claims nothing was moved.

A new user found this minutes after installing. Their notes were never deleted.

## [1.96.4] — 🧰 A clean Mac install finishes, and the desktop app can take over one background job (2026-08-14)

A brand-new Mac could stop during first setup because Dex asked the computer for
a helper it had not installed yet. Separately, the Dex Solo desktop app could not
safely take over one existing Dex background job, so two copies of the same job
could try to run.

**What this fixes for you:**

* **A clean install no longer depends on a leftover extra library.** First-time
  setup checks its own files with tools that are already there, then installs
  everything else in the right order.
* **The desktop app can take over one existing background job without running it
  twice.** It has to prove the old job is stopped first. Giving the job back
  works the same way in reverse.
* **Dex's own checkup stays honest about that handoff.** It ignores the
  handed-over job only while the proof is still valid. If the proof goes stale,
  the normal checkup takes over again.

## [1.96.3] — 🩺 Honest checkups, safer meetings, and releases you can verify (2026-08-13)

This is a reliability release built from ten fixes that were tested together. The theme is
simple: Dex should not guess when evidence is missing, call a broken connection “empty,” or
claim a release identity that does not exist.

### 🩺 Checkups now preserve the useful diagnosis

Several health checks were flattening very different problems into the same generic answer.
A missing Dex module could become package-reinstall advice, a slow semantic-search probe could
make the whole checkup look broken, and Apple Mail list/read could look healthy while its
separate search index was absent or stale.

**What this fixes for you:**

* **The original diagnosis survives.** Missing Dex files, missing third-party packages, and
  optional components now get different explanations and different repair steps.
* **“Could not tell” stays different from “broken.”** A timed-out search probe is reported as
  unknown without contaminating the rest of the checkup.
* **Apple Mail search is checked where search really lives.** Dex validates the configured
  index, its searchable structure, every indexed mailbox's freshness, and safe file
  permissions. The health check reads structural metadata, not message text.

### 📅 Meeting work uses evidence instead of assumptions

Four related faults could make meeting preparation and follow-up look confident while using
the wrong attendee, recorder, calendar state, or event. The fixes now meet at the real
execution seams instead of repeating hopeful instructions in several prompts.

**What this fixes for you:**

* **Meeting prep reads the calendar invite first.** Structured attendee identity is preserved
  through delegated research, so two people with similar names are not silently collapsed.
* **A broken calendar is never presented as an empty day.** Optional absence degrades calmly;
  missing installation, permission failure, and unknown tool errors keep their real guidance.
* **Configured meeting sources are honoured.** Granola is no longer assumed. Provider-neutral
  capture IDs are used when safe, with the full vault-relative Markdown path as the
  collision-safe fallback when two notes share a filename.
* **Capture-to-calendar matching is deterministic and conservative.** A capture can inherit a
  calendar identity only inside the five-minute window, with timezone-aware timestamps and
  title/participant corroboration. Ties, naive timestamps, and events beyond the boundary stay
  unmatched. Join links, dial-ins, access codes, locations, descriptions, conferencing data,
  notes, and raw payloads never cross that boundary.

### 🔒 Local receipts stay private, and malformed tasks stop at the door

Dex can keep a small local record that a capability was attempted, but the helper doing that
work could hang beyond the session-start budget. Separately, a leaked tool-call delimiter could
be accepted as ordinary task text and saved as a corrupted task.

**What this fixes for you:**

* **Usage-attempt receipts are local, bounded, and content-free.** The complete helper process
  is stopped after three seconds, including child processes. Its output is never relayed, it
  does not retry, and this adds no endpoint, token, consent screen, or data collection.
* **Corrupted task payloads are refused before any write.** Known delimiter shapes are rejected
  at the Work tool boundary, while normal task text still round-trips unchanged.

### 🧭 Fresh installs use the right capability identities

The recent brain/vault split left three first-install checks looking for capability sources
under their old identity. Existing upgraded vaults could work while a clean install stopped
before Career, Companies, or Quarter Goals was provisioned.

**What this fixes for you:**

* **A brand-new install completes against the exact current vault sources.** The repair updates
  the identities without weakening provenance checks or accepting a merely similar file.

### 🧾 The permanent release name is finally honest

Dex 1.96.2's catalog promised a permanent download tag derived from the source commit, but the
release is built into a later sanitized commit. The promised name could not exist, and changing
the real tag would have broken older updaters that correctly require the suffix to match the
released commit.

**What this fixes for you:**

* **Published catalog v1 stays frozen and readable.** Existing installations keep the exact
  contract they already understand.
* **New releases use catalog v2's honest pattern.** The exact permanent tag is derived only
  after the release commit exists, then checked locally and again after it is pushed.
* **An empty or unreadable tag observation fails closed.** A release cannot pass merely because
  the remote returned no evidence.
* **Old update paths were tested, not assumed.** Twelve historic Dex versions completed the
  release-shaped Mac journey against this change before it merged.

Thanks to Chris Jackson for the detailed Doctor, Mail, Calendar, and meeting reports and source
patches that exposed most of these trust failures.

## [1.96.2] — 🛡️ Your history saves again, and company networks get an honest answer (2026-08-13)

If you're on a corporate network that intercepts secure connections — Zscaler, Netskope, most large enterprises — or on a hotel or airport captive portal, Dex's daily update check could fail and report that the release evidence was **invalid**. That wording means something specific and alarming: that the version of Dex being offered looks tampered with. It was never true. What had actually happened is that Dex couldn't verify it was really talking to GitHub, because something on your network was sitting in the middle of the connection. Worse, Dex treated it as a permanent verdict and didn't try again, so the check stayed broken for exactly the people most likely to hit it.

**What this fixes for you:**

* **Dex now says what actually happened.** "Dex couldn't verify a secure connection to GitHub. This usually means a network proxy is inspecting traffic." No implication that anything is wrong with the release itself.
* **Dex tries again.** A certificate failure is now treated like a dropped connection: up to three attempts, backing off in between. A transient proxy hiccup no longer ends your update check.
* **Dex still refuses to trust a certificate it can't verify, and there is no way to turn that off.** This release changes what Dex *tells* you and whether it *retries* — it does not change what Dex is willing to trust. There is no setting, visible or hidden, that makes Dex skip certificate checking, and there deliberately never will be: if something really is intercepting your connection to GitHub, that is exactly the moment Dex should stop.
* **When something does go wrong, it's now diagnosable.** Update failures were being recorded as a bare category with the underlying error thrown away, which is why this particular fault took hours to track down. The underlying message is now kept — trimmed, single-line, and with anything credential-shaped stripped out before it's written anywhere.
* **Several other failures stop being mislabelled too.** A missing file, a permissions problem, or a timed-out command were all being filed under the same "invalid evidence" heading as a genuinely bad release. Each now reports as itself.

Chris Jackson found a second regression before this release went out: the rules Dex ships for its own source repository were also being copied into people's vaults. Those rules told Git to ignore the folders where their inbox, goals, tasks, projects, areas, resources, and archives live. The session snapshot hook could sometimes force past that rule, but an ordinary Git save refused the files outright — exactly when someone needed their local history as a safety net.

**What this fixes for you:**

* **Every personal working folder is tracked again.** Your inbox, goals, priorities, tasks, projects, areas, resources, and archives can all be saved in your local Git history after an install or update.
* **Dex's own files stay out of your personal history.** Product files delivered inside Resources are still excluded, while your own notes beside them remain trackable.
* **Secrets remain excluded.** Files such as `.env` stay ignored; repairing personal history does not weaken the privacy boundary.
* **The release now proves the real recovery path.** The test installs the shipped rules through Dex's updater, creates real user and product files, commits them with Git, and inspects the resulting history. Removing the fix makes that test fail at the same command users hit.

Thanks to Chris, who traced the missing-history symptom back to the generated vault rules and contributed both halves of the correction.

## [1.96.1] — 🔎 Lens can read every role and planning capability (2026-08-13)

The v1.96.0 catalogue was correctly signed but Lens refused it before deployment: two quarterly-planning requirements used Dex's internal underscore spelling instead of the public catalogue's hyphenated ID format. The canonical Lens URL stayed on the already-proven v1.95.2 catalogue, so nobody received the rejected file.

**What this fixes for you:**

* **The complete 55-capability catalogue now uses the exact contract Lens reads.** Quarterly planning and review keep their real room dependency, expressed as the valid `quarter-goals-room-enabled` requirement.
* **The producer now catches this class of mismatch before signing.** Host requirements must use Lens catalogue IDs, duplicates are refused, and the exported cross-repository schema carries the same identifier and uniqueness rules as Lens's runtime verifier.
* **The correction supersedes the rejected signed file honestly.** Catalogue version 3 replaces version 2 rather than rewriting the published v1.96.0 artifact.

## [1.96.0] — 🧭 Lens can now find the Dex built for your role (2026-08-12)

Dex Lens is the private guide that looks at your own AI setup and suggests useful Dex capabilities without changing anything. Its first expansion covered the everyday work almost everyone shares. This release adds the next layer: thirty adoptable capabilities for sales, product, marketing, engineering, finance, customer success, operations, design, career development, and quarterly planning.

**What this changes for you:**

* **Lens can recommend a role pack instead of a generic pile of commands.** It now understands work such as account planning, campaign review, architecture decisions, month-end close, customer health, operational metrics, and design-system review. Those skills remain off until you choose to adopt them.
* **Optional rooms are visible without pretending they are standalone switches.** Career and quarterly-planning skills are presented as the bundles they really are, including the setup and connected tools each room needs.
* **Every new recommendation says what is and is not proved.** All thirty additions have shipped instructions and adoption support, but none is labelled behaviourally verified yet. Lens will show them as *supported* until a real workflow test earns the stronger label.
* **The thinner role skills now have real working methods.** Seventeen short prompts were expanded with source discipline, explicit uncertainty, role-specific calculations or review methods, human authority boundaries, and recovery checks. Thirteen already-deep skills had their remaining evidence and safety gaps closed.
* **A changed dormant skill can no longer slip into the catalogue or an optional room.** Role packs resolve through Dex's release catalogue, while room skills carry exact current and published prior-release identities so a legitimate upgrade works without treating custom bytes as Dex-owned. Activation checks every source and target before changing anything, records the exact mutations, and rolls its bounded changes back if a later step fails.
* **Career evidence and resume exports now stop at the human boundary.** The career hook surfaces a sourced candidate instead of silently saving it, and asks before any evidence is added. Resume exports use a new filename when one already exists, verify the saved bytes, and never overwrite the earlier file.
* **Setup now survives an interruption without pretending it finished.** Onboarding and room changes reject links or malformed paths before touching the vault and refuse to continue when the lifecycle authority cannot run. Each bounded stage uses Dex's durable transaction record: a hard stop is recovered on restart, the completion marker appears only after the substantive setup is in place, and a committed catalogue adoption can rebuild a receipt lost in the final instant. Receipts name every committed transaction and every path that actually changed.

Lens still works the same way at the trust boundary: it reads the signed public catalogue, examines the person's own system locally, and offers advice. It does not receive their private working material or apply a recommendation for them.

## [1.95.2] — 🔎 Dex Lens now sees more of the work Dex can help with (2026-08-12)

Dex Lens is the private guide that looks at your own AI setup and suggests useful Dex capabilities without changing anything. It previously knew about six things Dex can do. It now knows about twenty-five: the everyday work around reviews, meetings, commitments, decisions, market thinking, and keeping your work recoverable.

**What this changes for you:**

* **Lens can make much more useful suggestions.** It can now recognise the routines around closing a day or week, preparing for and closing a meeting, following through on commitments, recording decisions, starting an initiative, understanding your market, and recovering your work when something goes wrong.
* **The proof labels now mean what they say.** A capability is called *verified* only when a test exercises that capability itself. Tests that check its instructions or a related safety mechanism are still useful, but Lens calls them *supported* instead. A missing or vague evidence link stops the catalogue from being published at all.
* **Nothing starts changing your own setup.** Lens remains a private, read-only guide. It does not send your working material to Dex or apply a recommendation for you.

### 🧪 The catalogue is tested before a release can burn a version number

The signed list that Lens downloads is now rehearsed in the same release environment before a version is created. Dex also checks its update-repair route from the messy kind of terminal environment a real person uses, rather than only from an unusually clean test setup. Those checks make a failed release stop before it can appear ready to download.

## [1.95.1] — 💾 Session snapshots actually save now — plus first-party backups, Pipedrive, and roomier daily rituals (2026-08-12)

A larger release than usual: six pieces of work landed together, four of them from Chris, who has been running Dex hard and reporting what broke. Each is written up in full below.

### 💾 If you switched on session snapshots, they never once saved. They do now.

There is an optional setting that saves your vault to its own local history at the end of every session, so you can go back through your own edits. If you turned it on, it has never worked — not once, for anyone, since it arrived on 21 July. Dex's own list of files to leave alone covers the folders your notes actually live in, and the save step gives up completely the moment it touches one of them. It reported that failure honestly every single time, at the one moment nothing was listening: as the session closed.

**What this fixes for you:**

* **Session snapshots save your notes, including the ones you wrote today.** Both halves of the fault are fixed: the save no longer refuses on your own folders, and it now finds notes you have only just created rather than silently skipping them. A snapshot that quietly saved nothing new was the more dangerous half, because it looked like it had worked.
* **Nothing private got swept in to make that work.** Your keys, saved sign-ins, deal caches from connected tools, and per-tool settings are still deliberately left out, and a new check exists purely to keep it that way. Only the folders your notes live in were opened up.

Found by Chris, who spotted the feature enabled, no history being written, and no error anywhere — then traced it to the exact cause. Nothing you saved before this release was lost; the snapshots simply never happened, and your notes were untouched throughout.


### ⚡ Big vaults get ready to update in seconds instead of minutes

Before Dex updates itself, it reads through your vault to find everything you have personally changed or added, so that your own work is protected rather than overwritten. On a big vault that step had been taking far longer than its size warranted: doubling the number of files made it four to eight times slower rather than twice as slow, so it got worse the more you put in. On a vault of around a hundred thousand files it was spending about four minutes on that one step.

**What this fixes for you:**

* **The check before an update finishes far quicker.** Measured on a vault of about a hundred thousand files, the slow step went from roughly four minutes to roughly twenty seconds. The larger your vault, the larger the saving — small vaults were never really affected.
* **It now slows down in step with your vault instead of ahead of it.** Dex was re-reading the same long list from the beginning once for every file it considered. It now looks that list up directly, so the time grows steadily with your vault rather than running away as the vault fills up.
* **Nothing it decides has changed.** The step examines exactly the same files and reaches exactly the same conclusions as before — only the waiting is different.

Found by Dex's own overnight performance check, which had been reporting this step as over its time limit every night since it was introduced.

### 🗄️ Your notes now back themselves up, and Dex tells you loudly if that ever stops

Until now, everything in your vault lived on exactly one computer. That's the right privacy posture, but it made a failed disk a total-loss scenario, and the only alternative on offer (a private code-hosting account) was the wrong ask for most people. Worse, backups have a cruel failure mode: on a real vault that pioneered this feature, the scheduled backup quietly stopped for ten days and nothing noticed. This release is built around never letting that happen silently again.

**What this fixes for you:**

* **Backups to anywhere that looks like a folder.** Run `/backup-setup` once and Dex archives your whole vault, on a daily schedule, to OneDrive, iCloud Drive, Dropbox, an external disk, or (for those who want it) directly to a cloud storage service. Recent copies are kept for accidents, weekly and monthly copies for problems you only notice late, and old copies are tidied away automatically. The newest copy is never deleted, no matter what.
* **Every backup is provable, not hopeful.** Each copy is checked as it's made, your vault's full edit history travels with it and is verified as complete, and fingerprints are stored so damage in storage is detectable. Dex checks the fingerprints belong to the copy in front of it, so a mix-up in a busy synced folder can't make a damaged backup look sound. `/backup-restore` goes further: its test mode fully unpacks a backup into a throwaway folder to prove a restore actually works, without touching anything of yours.
* **A backup that stops working — or quietly stores less than it should — can no longer hide.** Every run, good or bad, writes a record, and `/dex-doctor` reads it: if the last backup failed, if the newest good one is more than two days old, or if a run saved your notes but couldn't save something else, you're told plainly what happened and how to fix it. Silence now means healthy, not unchecked. Your notes are always saved even when another part of the backup can't be, because they're the part you can't rebuild.
* **Restoring never gambles with your live vault.** A restore always lands in a fresh folder you choose, for you to inspect and move into place yourself. If unpacking can't finish, Dex says why in a plain sentence and clears away the half-finished folder, so you're never left with something that looks like your restored vault but isn't all of it.
* **Nothing sensitive rides along to the cloud.** Your AI keys, saved sign-ins (such as a connected Google account), and any key or certificate files are deliberately left out of every backup, so none of it ever sits in a synced folder. The short restore guide travels inside the backup itself and covers what to re-enter on a new machine.

Very large vaults are handled a piece at a time rather than loaded whole, so size isn't a barrier.

Thanks to Chris, who proposed this, built it, ran it on his own vault first, and whose ten silent days shaped the design.


### 🤝 Dex can work with your Pipedrive deals, and never behind your back

If you keep deals in Pipedrive, you have been keeping them twice: once in the system your company reports from, and once in the notes where you actually think about the deal. The two drift apart within days, and reconciling them by hand is exactly the admin nobody does on a Friday afternoon. Chris built this to solve it for himself and offered it back.

**What this adds for you:**

* **Ask Dex what is really in your pipeline.** Connect Pipedrive once (`/pipedrive-setup`) and Dex can read your live deals: stage, value, likelihood, close date, owner, and recent activity. Your weekly review, meeting prep and daily plan can all draw on the real numbers instead of whatever was last typed into a note.
* **One reconciliation instead of two arguments.** `/pipeline-sync` puts your deal notes and Pipedrive side by side, shows you every place they disagree, and lets you choose which one is right, deal by deal. The principle throughout: Pipedrive is trusted for the numbers, your notes are trusted for the strategy, and neither is ever silently overwritten by the other.
* **Nothing reaches your company's system without you saying yes.** Every change Dex could make to Pipedrive is shown to you in full first, exactly as it would be sent, and goes nowhere until you approve that specific change. This is deliberate: for most people Pipedrive is a shared company system where a surprise edit is a real problem. Showing you the change is also what happens by default, so the safe path is the one Dex takes when anything is unclear — a muddled instruction or a retry after a hiccup costs you a second look at a preview, never a surprise edit.
* **Dex will never delete one of your deals.** It can move a deal to won or lost when you ask, because that is ordinary pipeline upkeep. Removing a deal from your company's system is not something Dex will do on your behalf at all, whatever it is asked — that one stays yours, in Pipedrive.
* **A slow or blocked connection can't turn a half-read pipeline into a false all-clear.** If Dex can only reach some of your deals, or your pipeline is longer than one look can cover, it says so plainly and names what it couldn't see. It will not tell you a deal is up to date when it never managed to read it.
* **Creating new deals stays switched off until you decide otherwise.** Dex can update existing deals out of the box, but creating new ones is off by default and takes a deliberate change to your settings to enable. Same reasoning: adding a deal to a shared company system is a bigger step than updating one, and it should be your call, not a side effect.
* **Your access key is kept in your Mac's keychain,** not in a file in your notes, and never appears in any note, log or report Dex writes.

Thanks to Chris, who built and hardened this before offering it upstream (requested in issue #360).


### 🧺 Your daily plan stops running out of room as your vault grows

The big daily rituals (planning your day, reviewing it, closing the week, prepping a meeting, processing your meetings) work by reading a lot first: your calendar, your tasks, your notes, your mail, your meeting history. In a young vault that reading is light. In a vault with a year or two of history, it can be so much material that Dex fills up on the reading alone and has nothing left for the part you actually came for. The failure is quiet: sessions get slower and shallower, and on the worst days a review dies halfway through and has to be rebuilt the next morning. One long-time user measured a single day of these rituals and found that of everything Dex read, less than two percent actually needed to stay in the conversation.

**What this fixes for you:**

* **The reading now happens in a side room, not in your conversation.** Each of the five heavy skills sends a helper off to do the bulk reading and come back with just the findings. The helper's workspace is cleared the moment it finishes, so your conversation keeps its room for the thinking, the writing, and the back-and-forth with you.
* **The conversation itself doesn't change.** These skills still run right where you're talking, still see what you've already discussed and decided this session, and still ask you every question they used to ask. Only the silent bulk reading moved.
* **If the helper ever fails, you still get your plan.** Dex says so plainly and does the reading the old way in the conversation instead. A hiccup in the new route never means a missing plan or review.
* **Meeting processing keeps updating your people pages.** Dex can't count on its usual automatic bookkeeping for work done in the side room, so the helper is told to do that bookkeeping itself. Two new automatic checks now guard the arrangement: one makes sure the two halves of each skill can never quietly drift apart in a future release, and one makes sure the helper is only ever told to use tools Dex actually has — a wrong name would have meant a whole source, such as your calendar, going missing with no error shown.
* **Nothing gets written into your vault on trust.** Where the helper adds tasks from your meeting notes, it now has to confirm each one landed correctly before it marks that meeting finished, and anything you'd normally be asked about — a commitment you mentioned in passing, a focus item that isn't a task yet — comes back to you for a yes before it becomes real.

The same steps run in the same order on a small or young vault, with more headroom for the day the vault gets big. Being honest about what's measured: the reading cost above was measured on a real, mature vault; the improvement to your conversation's headroom follows from moving that reading out of it, and hasn't been measured side by side.


### 🧹 Your list of changes stays yours — Dex's own files stop showing up in it

Chris found his vault's change list crowded with dozens of files he never touched — Dex's own product files, freshly rewritten by an update and showing up as if they were his edits. The cause: the file that tells your vault what to overlook is written for the team that builds Dex, and it deliberately keeps Dex's own files visible there. Inside *your* vault that's backwards — one broad "save everything" moment quietly folds hundreds of Dex files into your private history, and every update after that dirties them all again.

**What this fixes for you:**

* **Dex's files no longer masquerade as your changes.** When an update refreshes that overlook-list in a vault, Dex now appends a clearly marked section telling your vault to disregard its product files — while everything of yours, including your custom skills and custom connections, stays visible and versioned exactly as before. The section is rebuilt from Dex's own ownership rules on every update, so it can never drift out of date.
* **A background bookkeeping file stops appearing as something new to save.** The small timestamp Dex keeps to know when your search index was last refreshed is now overlooked like the rest of Dex's working state.
* **If Dex's files were already folded into your history, no more will join them.** This change stops the leak; it can't undo what a past update already captured, so those particular files keep appearing as changed for now. Releasing them — without deleting a single file from your folder — is the next piece of work.

Thanks to Chris for the report, traced from a single noisy update all the way to the root cause.


### 📦 A new version is never announced before the files you download exist

When Dex put out a new version, the announcement page appeared within seconds — but the files your copy of Dex actually downloads to update or repair itself were prepared separately, after the full test suite had run, and attached only afterwards. So there was always a window where the newest version was announced and undownloadable, and if those tests failed or got stuck waiting behind another long-running check, the window never closed. That is what happened on 11 August: version 1.94.0 sat at the top of the releases page for about ninety minutes with nothing attached to it, while Dex's own emergency repair instructions pointed at a file that came back "not found". The person most likely to hit that is someone whose update is already broken.

**What this fixes for you:**

* **"Newest version" now means the files are actually there.** The release page is created hidden. The downloads are attached to it, each one fetched back off the page and compared against what was prepared, and only then does the page become visible. There is no longer a moment where you can see a version you cannot download.
* **A release that goes wrong now leaves nothing published at all.** If any part of it fails, the release simply stays hidden until someone fixes it. Before, a failure left a half-finished release sitting at the top of the page looking like the current version.
* **Your download is verified before it is offered, not after.** Each release includes small companion files that let you confirm a download arrived complete and unaltered. Dex now checks those against the real files before the release goes public, so the verification step in the repair instructions cannot fail on something Dex itself published.
* **Something now keeps checking the real download links.** A standing check fetches the newest release exactly the way your copy of Dex would — including the precise links written into the emergency repair instructions — and raises the alarm if any of them is missing or damaged. It runs hourly on the machine that watches Dex's releases, with a second, slower copy running on GitHub itself in case that machine is off. A half-published release is caught in minutes to an hour or so, rather than whenever someone unlucky runs into it.
* **A release waiting its turn now says so.** Before releases go out, Dex runs a long rehearsal that replays real historic updates, and that rehearsal occupies the release lane for several hours. A release queued behind it now explains that on its own page, so it reads as waiting rather than broken.

### 🔍 Dex stops blaming your settings file for something else being missing

When a supporting component Dex relies on was absent, Dex reported that your settings
file was damaged. Two completely different problems wearing the same message, and the
one you would have gone looking for was the wrong one. The missing component is now
named as exactly that, everywhere that message can reach you.

Thanks to Amit Godbole, reporting for the first time.

### 🩺 Doctor stops giving an all-clear that an update would refuse

Doctor's update-readiness check worked out its own answer instead of asking the part of
Dex that actually performs updates. So it could tell you that you were ready at the very
moment a real update would have refused. It now asks the same gate the update itself
uses, and reports a problem when there is one.

Also thanks to Amit for this one.

### 📅 A ritual confirmed on Sunday morning no longer loses Sunday evening

When you confirmed a recurring session, Dex decided which upcoming ones to prepare for
using a window that stopped at the current time of day rather than the end of the day.
On a Sunday that collapsed the window onto the moment you confirmed, so a session later
the same day quietly got no preparation at all.

### 🔒 A safety check that could not start now starts

Dex's automatic behaviours — including the guard that refuses dangerous commands — were
found using a location relative to wherever you happened to be working. Run something
from a subfolder and the guard could not launch: a safety control that was quietly not
there. Every one is now anchored to the project itself, and a test stops a relative path
coming back.

### 🧭 One place to look when something seems wrong

The guide now says plainly what to reach for: `/dex-doctor` first when something seems
broken, `/feedback` when it looks like a genuine Dex bug — with the privacy promise
spelled out, so you know what does and does not leave your machine.

**A note on version numbers.** 1.95.0 was withdrawn before anyone could download it: its files were built from the wrong snapshot of the code, and a safety check caught that before the release became visible. Nothing was ever published under that number. Everything described in this section reached you in 1.95.1 instead.

---

## [1.94.0] — 📦 Moving your Dex folder no longer locks you out of updating (2026-08-11)

Dex writes down where your vault lives. Move that folder, rename it, or work from a copy of it, and the note still points at the old place — and Dex was reading that mismatch as damage. It refused to update at all, with a message that didn't say why. A user hit this while rehearsing the rescue route on a duplicate of his own vault, and spent an hour reading Dex's code to work out which of its nine checks had failed.

**What this fixes for you:**

* **A vault you moved, renamed, or copied updates normally again.** Dex now treats that note for what it is — a stale reminder of where the folder used to be — and writes the new location down the next time it updates. You don't have to put the folder back, and nothing about your files or your history has to change. Anything that would signal real damage is still refused exactly as strictly as before; only the out-of-date location became forgivable.
* **When Dex does refuse, it tells you which thing is wrong.** These refusals used to end with "Dex will not guess how to convert it" and nothing more. Each one now names the specific file or folder that didn't check out, and says what it expected to find there — so the next step is obvious in a minute rather than an hour.
* **Trying the rescue tool without answering it no longer looks like a crash.** Starting it with its input closed — the ordinary way to watch how far it gets before you commit to anything — produced a page of programmer error text. It now stops with the same single plain sentence as every other stop, saying that nothing was changed because it couldn't read an answer.
* **A stray warning about task numbering no longer interrupts a rescue.** The rescue tool's output opened with an alarming note that had nothing to do with updating: a different part of Dex talking over the top of it. It no longer reaches you there, and the rescue tool's own messages are unaffected.
* **The rescue route now says up front that it takes two runs.** Finishing the rescue tool puts you on a release from 4 August, not the newest one; a second, ordinary `/dex-update` covers the rest. The guide now says that before you start and the tool says it when it finishes, instead of hinting at it afterwards.

Thanks to Jim, who checked all nine conditions by hand against both his real vault and the duplicate, found that only the recorded location differed, then proved everything behind that check was sound by correcting that one line and re-running.

---

## [1.93.3] — 🗣️ Tell Dex something's broken however you like (2026-08-11)

Setup now promises that if something goes wrong you can just say so in your own words. That promise needed the other half: Dex reliably recognising a description of a fault as a fault. Until now it leaned on you using the words "report this" or running the command — which is exactly the homework the whole feature was built to remove.

**What this fixes for you:**

* **"The meeting sync is doing something weird" is enough.** Ordinary descriptions — this keeps breaking, it stopped working, that's not what I asked for, it did that again — now get treated the way the magic words always were: Dex looks into it on your machine and, if the cause is a fault in Dex, offers to write it up for you.
* **A fault and a wish go to different places.** "I wish Dex could do X" still becomes an idea in your own list. "X stopped working" goes to the team as a bug. If you say both in one breath, Dex handles the fault first and keeps the idea.
* **It won't file a report about your life.** "My calendar is a mess" or "this project is a disaster" is about your work, not a fault in Dex, and never becomes a report. Neither does an outside tool having a slow day, unless Dex's own handling of it is at fault.
* **A setup problem gets fixed, not filed.** If the cause turns out to be something not yet connected on your machine, Dex fixes it with you — or points you at the checkup — instead of sending the team a report about your own setup.
* **Nothing is sent without you seeing it.** Reports that start this way follow exactly the same rules as any other: you see the whole thing first, and it can only contain the same fixed list of ingredients.

Dex now offers once per problem, and drops it if you say no.

---

## [1.93.2] — 🔗 Two dead links in your first-week reminders now go somewhere (2026-08-11)

If you accepted the optional calendar reminders during setup, two of them — the one teaching the HARVEST trick, and the one about making Dex argue against your decision — linked to guide pages that don't exist. Clicking either gave you a "page not found" in your first week, which is the worst possible moment to look unfinished.

**What this fixes for you:**

* **Both links now land on the prompt they're teaching.** They point at the "prompts to steal" page, at the exact section holding that prompt — the HARVEST wording in one case, the argue-against-me wording in the other. That page was always the right home; the reminders just pointed at page names that were never built.
* **It can't happen again quietly.** A check now runs with every change and fails if a reminder links to a guide page that isn't published, naming the page.

Nothing else changed, and your calendar reminders are untouched — reminders already in your calendar keep their old text until you regenerate them.

---

## [1.93.1] — 💬 Setup now shows you how to get something fixed (2026-08-11)

Dex finished setting itself up without ever telling you what to do when Dex itself goes wrong. There was one line about it in the sign-off, easy to miss and gone forever once the screen scrolled. So people hit a problem, assumed it was theirs to live with, and never said anything — and a fault nobody reports stays broken for everyone who has it.

**What this fixes for you:**

* **You learn you can just say it.** Setup now explains, near the end, that if something misbehaves you describe it however you like — "the meeting sync is doing something weird" is plenty. Dex looks into it on your machine, writes the report for you, and shows it to you before anything is sent. If Dex doesn't pick it up as a bug, saying "report this" gets you there.
* **You find out what happens after you send one.** Your report arrives on the Dex team's private desk with a reference number. If they need one more detail, the question comes back to you the next time you open Dex, and Dex can go and find the answer and show it to you before it goes. You can ask how your reports are doing whenever you like, and when a release contains your fix, Dex opens with the news and the version that has it.
* **The privacy line is said out loud, with the full list a click away.** Nothing from your notes, meetings, people or your conversations with Dex ever goes into a report. Setup says so plainly and links the guide that lists every single thing a report is allowed to contain.
* **You meet the checkup before you need it.** Setup introduces `/dex-doctor` for the times when nothing looks broken but something feels off — it tells you honestly what's working, what's switched off, what's broken and what it couldn't check, then repairs what it can without touching your notes.

Every promise in that new part of setup was checked against the code that has to keep it, so what Dex tells you at the start is what actually happens later.

---

## [1.93.0] — 🌉 The rescue bridge for stuck installs actually starts now (2026-08-11)

Dex's rescue bridge — the one-time tool that gets a very old install updating again — clears out its surroundings before it runs, so nothing already on your machine can quietly steer the update. The last release taught it to stop safely instead of spinning forever when that clean start didn't take. It duly stopped, and told a user it couldn't continue. The cause turned out to be the cleaning itself.

**What this fixes for you:**

* **The bridge gets past its own front door.** Clearing the surroundings removed the setting that tells a program which characters and alphabet to expect, and the language Dex runs on quietly put its own replacement back. The bridge saw a setting it hadn't put there, assumed something had interfered, and stopped. It now asks for that replacement not to happen, and pins character handling directly instead — so the clean start it asks for is the clean start it gets.
* **Two harmless leftovers no longer halt an update.** Apple's system stamps a text-encoding marker onto every program it runs, and there is no way to switch that off. The bridge now recognises that marker, and the character setting above, for what they are — the machine's own housekeeping, not something that arrived with you — while still refusing anything that could genuinely redirect an update somewhere else.
* **If it ever does stop, the message is worth something.** The single line it prints now says plainly that your vault is untouched and that the line itself is everything the Dex team needs in order to fix it.

Thanks to Jim, whose measurements pinned the cause exactly — including that it would have happened on any Mac, not only his.

## [1.92.0] — 🔢 Task numbers no longer stop counting at 999 (2026-08-10)

A user with a well-used vault found that once his tasks passed number 999, every new task got the same number — four collisions in one day. His report arrived with the diagnosis already done (thank you, Martin), and it checked out exactly.

**What this fixes for you:**

* **Task numbers now count past 999, forever.** Every part of Dex that reads a task's ID assumed the number part is exactly three digits, so the ID generator couldn't see anything above 999 and kept handing out 1000. The assumption is gone from all sixteen places it lived — the generator, the task sync layers, and the automation helpers — and numbering simply continues: 1000, 1001, and onward. Existing task IDs don't change.
* **Task 100 can no longer be mistaken for task 1000.** Looking up a task matched partial numbers, so acting on one task could quietly touch another whose number merely started the same. Matching is now exact — this one was waiting to bite anyone the moment they crossed a thousand tasks.

## [1.91.0] — 🔐 The file holding your AI keys is now private — and the checkup finally sees it (2026-08-10)

If you gave Dex an AI key so meetings get analyzed in the background, that key sat in a small file at the top of your vault that other accounts on the same computer could read — and Dex's own checkup couldn't see the key at all, so it reported "no key" and recommended you put one exactly where it already was.

**What this fixes for you:**

* **Only you can read your key file now.** Every place Dex creates or updates that file makes it private to your account, and the checkup (`/dex-doctor`) safely tightens an existing file that was left open — without reading or changing anything inside it. In the two cases where fixing it automatically would be wrong — the file belongs to a different account, or it's a shortcut-style link to a file elsewhere — the checkup reports the problem and gives you the exact command instead of guessing.
* **The checkup stops calling a configured key "missing."** The health check now looks in the same place the background features actually read the key from, so a key you've already set up is recognised instead of reported absent. The key itself never appears in any report or log — the check only confirms one exists.
* **Advice that no longer points you wrong.** Wherever Dex tells you to add an AI key, it now also tells you to keep that file private — and it's honest that Dex's encrypted credential storage doesn't yet feed these background features, so the file is still the right place for now. Moving those keys into encrypted storage is a separate, deliberately unhurried piece of work.

Thanks to Chris, whose report mapped the whole problem — including the parts this release fixes and the deeper move it defers.

## [1.90.0] — 🧭 Clearer rescue directions for stuck older installs (2026-08-10)

The update-rescue guide (the page that helps when `/dex-update` refuses) sent some stuck installs down a road that couldn't work — and, in one rare case, a road that could cost files.

**What this fixes for you:**

* **The guide now checks your vault's shape first.** Installs where Dex's code already lives in its own private store were being pointed at a manual Git route that cannot work for them (its first command fails on those vaults); they're now sent straight to the supported one-time bridge, whatever version they're on.
* **The oldest versions go to the bridge, never the old manual route.** A detailed report showed that versions before v1.62 hit a safety refusal the manual route can never satisfy — and that forcing past that refusal silently deleted three of the reporter's personal files (recovered from their own backup, nothing lost). The guide now says plainly: if you see that refusal, stop and use the bridge, which recognises those exact older versions and protects personal files by design.

## [1.89.0] — 🪟 Windows stops raising false alarms (2026-08-10)

Two detailed reports from the community, one theme: on Windows, Dex's health checkup declared a perfectly healthy install broken. Both were false alarms — Dex behaved slightly differently on Windows than on Mac in a handful of invisible places — and both are fixed. Thank you to the Windows user who filed them.

**What this fixes for you:**

* **The checkup stops insisting your install doesn't match its release.** On Windows, the standard way of keeping files on disk quietly stores text in Windows' own format. Dex's integrity checks compared those files against the original release and reported a mismatch — every time, on every Windows machine — which cascaded into a whole page of "broken" verdicts across the update and adoption tools, and could brand files you never touched as "modified by you". Everywhere Dex checks its own files against a release — the install record, optional capability files, and the modified-or-not verdict on each file — it now recognizes Windows formatting for what it is: the same content, stored the Windows way. Files you actually edited are still caught exactly as before.
* **The doctor stops blocking itself.** While running its checkup on Windows, Dex could trip over its own safety lock and refuse to finish, reporting "another Dex process is already changing this vault" — where the "other process" was the checkup itself. The cause was one internal bookkeeping step that works on Mac but simply doesn't exist on Windows; it turned out to be attempted in ten different places, so fixing only the first would have moved the failure one step down the line. All ten now handle Windows properly, and a failed attempt cleans up after itself instead of leaving a confusing leftover behind.
* **Checking on another Dex process can no longer harm it.** The way Dex asked "is that other process still running?" was safe on Mac but on Windows could actually shut the other process down. Dex now only looks — it can never touch.

These fixes were verified with tests that simulate the Windows behavior, not on a live Windows machine — if you're on Windows and still see either symptom after updating, please run `/feedback`.

## [1.88.0] — 🔄 An update now clears its own stale paperwork (2026-08-10)

A wonderfully thorough field report (reproduced twice, traced to the exact line) showed that after every update, a small internal note recording "this version is active here" still named the old version, so the next planning or undo request was refused until a separate repair ran.

**What this fixes for you:**

* **An update now clears the outdated note as its final step.** The moment the new files are safely in place, the note the old version left behind is removed — and the very next thing you do writes a fresh one for the new version. Plans, undo, and unattended nightly updates no longer trip over the previous version's paperwork, and there's no gap where your install disagrees with itself.
* **Clearing the note can never block an update.** If the note is unreadable or can't be cleared, the update still completes exactly as before — tidying up is never allowed to veto an update that already succeeded — and Dex's existing self-repair still fixes the note the next time it's read.

## [1.87.0] — 🔄 Note-syncing survives busy days, and calendar permissions work again on newer Macs (2026-08-10)

A community member sent in two unusually sharp bug reports, each diagnosed right down to the fix. Both are in this release — thank you, Chris.

**What this fixes for you:**

* **The helper that syncs your ticked checkboxes stops dying on busy days.** The background helper that notices when you tick a task done in Obsidian and updates it everywhere could crash whenever lots of files changed at once — a big meeting-processing run, a reorganization, any burst of activity. Your Mac restarted it each time, so it limped along for months looking healthy while quietly missing changes at exactly the busiest moments. It now takes a calm snapshot of what's waiting, works through that, and anything that changes while it's working is simply picked up in the next pass — nothing crashes, nothing gets dropped.
* **Dex can actually ask for calendar and reminders permission on newer Macs.** Apple changed how apps must request calendar access, and Dex was still asking the old way — which newer Macs refuse instantly without ever showing you the permission window. So anyone on a recent Mac, a new machine, or who had reset their privacy settings could never grant Dex calendar access, no matter how many times they tried. Dex now asks the new way on Macs that support it, and the old way still works on older ones.
* **When calendar access is denied, you're told what to do about it — not "Exit code: 1".** Dex has always written a helpful explanation when access is refused ("Calendar access denied. Enable in System Settings → Privacy & Security → Calendars…"), but the part of Dex that relays errors was looking for it in the wrong place, so all you ever saw was a bare "Exit code: 1". The real guidance now reaches you — which matters twice over, because it's how you'd discover the permission problem above.

## [1.86.0] — 🧭 The checkup now sees all your background jobs — and stops crying wolf (2026-08-10)

Three community bug reports showed the same pattern from different angles: Dex's health checkup could miss real problems with background jobs while flagging healthy things as broken. This release makes the checkup match reality in both directions. Thanks to the three reporters whose unusually precise write-ups made these fixes straightforward.

**What this fixes for you:**

* **Background jobs you set up yourself are now watched.** The checkup used to recognize only the background jobs Dex ships. If you scheduled your own Dex automations under your own names, they were invisible — a silently dead job read as "healthy, nothing to monitor," the exact failure the check exists to catch. Now any background job that works on this vault is checked no matter what you named it (jobs from Dex's earlier name are recognized too), and the checkup says plainly which jobs it can audit for freshness and which it can only confirm are running. Other products' background jobs are never touched — even a damaged one can't confuse Dex's own checkup.
* **Moving your Dex folder no longer strands background jobs in limbo.** After a folder move or rename, Dex would warn at session start that background jobs still pointed at the old location and send you to /dex-doctor — which then reported everything fine, because it treated those very jobs as belonging to some other install. Now the session-start warning and the doctor use one shared detector, so anything the warning fires on the doctor can see: it reports the job as broken and offers to repoint or remove it with your approval — including jobs only half-fixed by an earlier move. (In the report that surfaced this, seven jobs had been running against a dead folder for a day while the checkup said nothing was broken.)
* **"Modified shipped files" stops accusing files you never touched.** The checkup compared your files against an out-of-date reference point, so files that were exactly what your installed version ships could be flagged as modified — alarmingly, including the files that handle credentials — and real changes got lost in the noise. The comparison now uses the version you actually have installed, so the list only names things you actually changed — and a vault accidentally carrying files from a version you haven't installed yet is still called out rather than waved through.
* **When the one-time file-bookkeeping cleanup is blocked, it now tells you why.** Its safety gate used to refuse with a bare count mismatch, leaving you to guess which files were responsible. It now lists the exact files, notes which expected files never existed in your vault at all, and shows the one command that clears each extra file — the gate itself stays just as strict.

## [1.85.0] — 🫀 Health checks that ask "did it work?" — and don't wait until tomorrow to tell you (2026-08-10)

Yesterday's release fixed a background sync that had been failing silently for six days while every health check stayed green. Today's release fixes the deeper problem: health checks that measured the wrong thing, and health news that only arrived when you started a fresh session.

**What this fixes for you:**

* **Every background job now makes a promise Dex can audit.** Each of Dex's recurring background jobs — meeting sync, the nightly self-check, the update watcher, and the rest — now declares how often it should succeed and where it leaves its receipt when it does. The health checkup reads the receipts. A job that keeps running but never succeeding now shows up as broken, not busy. And Dex refuses to ship any new background job that doesn't make this promise, so the next feature is watched from day one.
* **Bad health news finds you mid-session.** Health used to speak only at the start of a fresh session — if you lived in one long conversation for days, you heard nothing. Now Dex takes a tiny glance at its own latest checkup as you work (a glance, not a checkup — it adds no noticeable time) and tells you at most once a day if the checkup is overdue or found something serious.
* **Every update proves the doors still open.** The bug fixed yesterday broke Dex's planning and undo features at the exact moment an update finished — and nothing noticed until a person tried them days later. Now, the moment an update applies, Dex walks through those same doors itself and tells you immediately if one is stuck.
* **Dex checks that your meeting-notes setup still matches reality.** If you've told Dex where your meeting notes land, the checkup now verifies that the folder actually exists and is actually receiving notes — so a broken export from your meeting tool gets caught by the checkup, not by a wrong meeting summary.

## [1.84.0] — 🩺 Updates stop quietly breaking things, and plans stop "forgetting" (2026-08-10)

Two users sent unusually detailed bug reports this week. Between them they uncovered six real problems — including one that silently affected every install that had ever taken an update. This release fixes all of them.

**What this fixes for you:**

* **Taking an update no longer quietly locks parts of Dex.** Dex keeps a small internal note recording which version it first activated. That note was written once and never refreshed, so from your first update onward, anything that read your install's plan, adoption choices, or undo history refused with an error — forever — while updates themselves kept working, hiding the damage. Dex now refreshes the note automatically, and installs already stuck this way heal themselves the first time they do anything after taking this update.
* **Planning and review commands can see your conversation again.** Eleven commands — daily and weekly planning and reviews, meeting prep and processing, decisions, delegations, reflections, and more — used to run in a separate workspace that could not see what you'd already discussed. That's why a morning plan could resurface items you had settled minutes earlier: it wasn't forgetting, it never had the information. These commands now run inside your conversation by default; you can still ask for a background run.
* **The update-rescue tool can no longer spin silently.** On some Macs the standalone recovery script restarted itself in an endless loop, burning CPU for minutes with nothing on screen. It now gets that restart right on Macs, stops with one plain sentence if it genuinely can't proceed, and narrates every stage as it works — so silence now means something is wrong, and the rescue guide says so. The guide also now makes clear it covers versions v1.74 through v1.79.
* **Meeting closeouts only use notes you trust.** One user's meeting wrap-up couldn't find the notes in their vault and quietly fell back to auto-generated notes from a different tool — which had invented an action item and assigned it to their client. Dex now records where your meeting notes come from during setup, looks there first, and is forbidden from fishing in outside services for notes it can't find — it asks you for them instead. Thanks to the reporter who caught this before it reached their client.
* **Background sync can't be hijacked by a temporary folder — and Dex now checks it actually succeeds.** Setup helpers could accidentally point background meeting sync (and the shared record of where your Dex lives) at a temporary working copy that later disappears, leaving sync failing quietly every half hour while every health check stayed green. Installers now refuse to run from temporary copies, the Doctor calls out a hijacked job instead of ignoring it, and health checks now ask "when did this last *succeed*?" rather than "is it still making noise?".
* **Filing feedback checks your connection first.** /feedback now confirms this computer is linked to your heydex.ai account before it writes anything, so you're never asked to approve a finished report only to learn it can't be sent yet. Reported by the same user who stress-tested the whole flow — thank you.

## [1.83.0] — 📣 Updates now introduce themselves (2026-08-08)

The last release quietly gave Dex a capability many of you may not have
noticed: say "report this" when something misbehaves and Dex writes the bug
report for you, shows it to you before it goes, and tells you when the fix
ships. Run `/feedback`, or read the guide at https://heydex.ai/help/feedback.html.
The fact that you could miss a feature like that was itself a bug. Fixed today.

**What this fixes for you:**

* **Your next session after an update opens with what's new.** One short note,
  once per version: the headline and the few things worth knowing, with a link
  to the full story. No more silent updates.
* **"Update available" now tells you why you'd care.** The session-start nudge
  lists the headlines waiting for you, newest first, instead of asking you to
  update on faith. It checks quickly and quietly, and if the network is slow it
  simply shows the plain nudge rather than delaying your session.
* **New users meet the bug reporter on day one.** Onboarding now ends by
  introducing `/feedback`, so nobody has to discover it by accident.

## [1.82.0] — 💬 Found a bug? Dex reports it for you — and tells you when it's fixed (2026-08-08)

Until now, when something in Dex misbehaved, telling the Dex team meant writing it
up yourself — so most problems went unreported, and the ones that arrived were too
thin to act on. Now Dex has a proper way to raise its hand on your behalf: the new
`/feedback` command.

**What this fixes for you:**

* **Report a bug with zero homework.** Say "report this" (or run `/feedback`) and
  Dex investigates the problem on your machine, writes the report itself, and gives
  you a reference number. The Doctor checkup offers the same thing when it finds
  something that's genuinely a Dex problem rather than a setup problem.
* **Nothing private ever leaves your machine.** Reports are built only from a fixed
  list of safe ingredients — Dex's version, which feature misbehaved, and error
  details from Dex's own workings. Your notes, meetings, people, and conversations
  are never part of a report, and Dex shows you the exact report before anything is
  sent. A copy of every attempt is also kept on your machine so you can always see
  what went.
* **You choose how involved to be.** Review every report before it goes (that's the
  default), or — once you've seen what a report looks like — tell Dex to just send
  future ones automatically. You can switch back anytime.
* **You hear back.** When your bug is fixed in a release, your next session opens
  with the good news and a thank-you — along with which version has the fix. If the
  team needs one more detail, Dex relays the question, gathers the answer with your
  approval, and sends it back. You can ask "what happened to my bug report?" anytime.
* **One connection, thirty seconds, once.** The first report asks you to connect
  this terminal to your heydex.ai account (the same quick sign-in the DexDiff
  publishing flow uses). After that, reporting is invisible.

---

## [1.81.19] — 💌 Your feedback, fixed — and updates that shrug off network blips (2026-08-07)

One of Dex's longest-running users spent a day putting her whole setup through
its paces and sent back a detailed list of everything that fought her. Almost
all of it turned out to be real for everyone, not just her — so this release
fixes the lot. Thank you, Michelle. Alongside that, updates now survive brief
network outages instead of giving up.

**What this fixes for you:**

* **Putting events on your calendar works again.** Dex was accidentally running
  its calendar helpers the wrong way, so creating or deleting an event failed
  with a confusing error. Fixed, with a safeguard so it can't quietly come back.
* **Evening journaling actually starts when you've turned it on.** The end-of-day
  review used to mention reflection and move straight on. Now it genuinely walks
  you through your evening journal — and quietly stays out of the way if you've
  left journaling off.
* **Ticking a task done finally updates everywhere.** Focus items on your daily
  plan were written in a format the task tracker couldn't see, so completing
  them never synced. Plans now carry each task's identity, and completion flows
  both directions.
* **Weekly cleanup can't mangle your task list.** Clearing finished tasks used
  to risk leaving behind orphaned fragments of multi-line tasks. Cleanup now
  removes each finished task whole, and tells you what it's clearing first.
* **People's names link properly in your notes.** Every mention of a person now
  becomes a link (not just the first), and links point to the person's name
  rather than a long internal location.
* **Honest guidance when Apple Reminders can't work.** Running Dex inside
  VS Code means the Mac never offers the Reminders permission — that's now
  documented plainly, Dex skips those steps quietly, and nobody gets told to
  reinstall for something reinstalling can't fix.
* **New installs point you to the right folder.** The install instructions now
  say exactly which folder to open in your chat app — a small thing that
  tripped up a lot of first days.
* **Your health checkup counts adopted improvements correctly.** Dex Doctor
  was overlooking items you'd already accepted, making your system look less
  up to date than it really was.

* **Older installations retry the exact foundation fetch once.** Temporary DNS
  or connection failures get a second attempt inside one fixed deadline; the
  bridge still accepts only the pre-declared immutable release.
* **Current installations retry a closed offline release proof once.** Dex uses
  only the time left inside the original proof window, then rechecks the tag,
  commit, tree, channel, catalogue, and package identity before any preview.
* **Every other failure still stops safely.** Wrong identities, changed
  evidence, filesystem problems, and a second network failure are never
  explained away or turned into an update.
* **Historic support still has to be earned.** This release establishes the
  hardened foundation. A distinct public follow-up and one fresh complete Mac
  fleet must still pass before Dex claims universal two-hop coverage.

## [1.81.18] — 🩺 Proactive health summaries (2026-08-05)

Dex used to make it hard to know whether background checks were current without
asking for a full Doctor run. This release keeps the latest complete health
summary visible while keeping session starts calm.

**What this changes for you:**

* **Health summaries stay trustworthy.** Reporter results are normalized into
  immutable snapshots, so an incomplete refresh cannot replace the last known
  complete status.
* **Critical problems surface at the right moment.** A newly critical result
  can interrupt the session; warnings, staleness, and recoveries stay quiet or
  unobtrusive.
* **Doctor can resume context safely.** A structured handoff preserves the
  relevant issue and check identities, while stale or malformed context falls
  back safely to general Doctor.
* **Existing installations get it automatically.** The first refresh stays
  quietly in a preparing state, with no new notification controls to configure.

## [1.81.17] — 🧭 Historic checks now recognise what older releases actually shipped (2026-08-05)

The final public Mac fleet stopped before testing one old semantic release because
that release predates Dex's release catalogue. The adjacent immutable package
completed both update hops, showing that the stop was in the fleet proof rather
than the customer update path.

**What this fixes for you:**

* **Older semantic releases are judged by the files they actually shipped.** When
  an exact historic release genuinely predates the catalogue, Dex can use its
  verified updater files as evidence instead of requiring a file that never
  existed.
* **The newest public release joins the historic proof set.** Both v1.81.16
  identities are tested through the exact immutable v1.81.16 first hop before
  the distinct v1.81.17 follow-up.
* **Missing or altered proof still stops safely.** An unreadable or malformed
  catalogue, changed updater files, or a mismatched release identity is still
  rejected before a journey starts.
* **Historic support still has to be earned.** This release removes the narrow
  proof-controller blocker, but Dex will claim support only after the freshly
  generated public Mac fleet completes with zero failures.

## [1.81.16] — 🧭 Historic updates now aim at the selected public foundation (2026-08-04)

Dex's historic-update bridge previously used the original v1.81.0 foundation,
even after newer releases had hardened the real two-hop journey. This follow-up
closes the first hop to the exact public v1.81.15 release instead.

**What this changes for you:**

* **Old installations enter through the selected public foundation.** The bridge
  verifies the exact annotated tag, commit, and tree before it can preview or
  change anything.
* **The second hop stays genuinely separate.** v1.81.16 is the distinct
  follow-up release used to prove that v1.81.15 can deliver its successor.
* **Fleet support is not assumed.** Dex will claim historic two-hop support only
  after the freshly generated public Mac fleet completes with zero failures.

## [1.81.15] — 🛡️ Temporary GitHub limits no longer stop a safe update (2026-08-04)

During the formal historic Mac run, one healthy update reached its public
foundation and then GitHub temporarily refused the second release proof. Dex
stopped safely before previewing or writing anything, but the route had to be
run again after the temporary limit cleared.

**What this fixes for you:**

* **One explicit GitHub rate-limit response gets one bounded retry.** Dex uses
  only the time left inside the existing ten-second proof window; it does not
  extend or loop the check.
* **Every safety boundary stays closed.** Wrong release identities, invalid or
  generic evidence, other HTTP failures, and a final download rejection still
  stop immediately without previewing or changing your files.
* **Fleet acceptance still requires the complete public run.** This release
  hardens the exact transient seam that stopped the previous run, but Dex will
  not claim historic two-hop support until a fresh retained 170-case Mac run
  completes with zero failures.

## [1.81.14] — (2026-08-04)

## [1.81.13] — 🧷 v1.63 updates keep your saved profile intact (2026-08-03)

The formal historic Mac fleet reached an exact v1.63 installation, then stopped
because that release's built-in split helper rewrote its saved user profile while
entering the protected update foundation. Dex's preservation guard caught the
change and refused to continue, so no unsafe result was accepted.

**What this fixes for you:**

* **Exact affected v1.63 releases use the verified foundation migrator.** The
  updater replaces only the known faulty helper for four immutable historic
  release identities; unfamiliar or altered installations still stop safely.
* **Your profile and other protected content remain byte-for-byte unchanged.** A
  retained macOS canary proved the saved profile, notes, tasks, and custom skill
  survive both update hops exactly.
* **Fleet acceptance still requires the complete public run.** This release fixes
  the v1.63 blocker, but Dex will not claim every historic release is upgradeable
  until a fresh retained 170-case Mac run completes with zero failures.

## [1.81.12] — (2026-08-03)

## [1.81.11] — (2026-08-03)

## [1.81.10] — 🛡️ Fleet proof no longer spends GitHub's shared API allowance (2026-08-03)

The formal Mac fleet re-derived all 170 public starting cases, then GitHub refused
the controller's unauthenticated release-metadata request because the shared public
API allowance had been exhausted. The bridge and its checksum were already public
and valid, but the gate correctly stopped before starting any journeys.

**What this fixes for you:**

* **Stable-release proof uses GitHub's public latest-release route.** The controller
  requires one exact redirect to this version's canonical release page instead of
  consuming the rate-limited metadata API.
* **The updater assets remain independently verified.** Dex still downloads the
  public bridge and checksum anonymously and requires their bytes to match the
  submitted release artifacts exactly.
* **Unexpected release routes still stop safely.** A missing redirect, extra hop,
  different host, different version, query, fragment, or non-success response is
  rejected before a historic installation starts.
* **Fleet acceptance is still earned by journeys.** This release removes the
  controller blocker; the freshly generated 170-case Mac run must still complete
  before Dex claims historic two-hop acceptance.

## [1.81.9] — 🧹 Oldest Dex installs clear one dormant search registration (2026-08-03)

The formal Mac fleet began with v1.20.1 and reached the public foundation with
personal files unchanged. Doctor then found that this oldest release still
advertised the optional qmd search server even though qmd was not installed, so
the updater correctly stopped before claiming a healthy result.

**What this fixes for you:**

* **The exact dormant qmd entry is removed during the protected bridge.** A proven
  v1.20.1 install can replace that obsolete registration while adding Dex's current
  lifecycle server, using the normal preview, approval, transaction, and receipt.
* **Your other connections and settings stay untouched.** The compatibility route
  removes only the exact legacy qmd shape; every unrelated MCP server and top-level
  setting is preserved.
* **The exception remains narrowly closed.** Dex requires the exact oldest-release
  origin, the exact dormant registration, and an absent qmd executable. Any altered
  or unfamiliar state still stops safely.
* **Fleet acceptance is still earned by journeys.** This release repairs the first
  formal failure; the freshly generated public 170-case run must restart and finish
  before Dex claims universal historic support.

## [1.81.8] — 🧭 Historic Mac installs enter a verified update route (2026-08-03)

The historic updater sweep found real published Mac installs whose trustworthy
release shapes predated today's metadata. Dex correctly stopped rather than
guessing, but those known installs still needed an exact route into the protected
two-step updater and a real Mac gate to prove it.

**What this fixes for you:**

* **Known historic releases are recognised by their exact identities.** Dex can
  accept the verified v1.51, v1.61, v1.62, and archived v1.65 shapes used by the
  release fleet, while unfamiliar or altered installs still stop safely.
* **Each update hop is exercised on a real Mac.** The release gate runs the
  foundation and follow-up updates, checks Doctor and smoke health, and confirms
  protected personal-file hashes did not change.
* **Fleet acceptance is counted from public history, never assumed.** The formal
  controller freshly derives every immutable starting case, retains evidence,
  and stops on failure. This release enables that public run; it does not claim
  the full fleet has passed before those journeys complete.

## [1.81.7] — 🛟 Stranded older installs can obtain the update bridge (2026-08-01)

Jim's clean 1.79.0 package correctly detected the newest release, but its private
Dex history contained only the installed version. The protected updater could
verify new release bytes only after another component supplied them, while the
one-time bridge existed solely inside the release it was meant to help install.

**What this fixes for you:**

* **The one-time bridge is now a real download.** Every release publishes the
  reviewed compatibility bridge as its own versioned asset beside an exact
  SHA-256 checksum, rather than hiding it inside the full Dex bundle.
* **The rescue instructions are complete.** They name the immutable release
  URLs, verify the downloaded bytes, and only then run the pinned bridge.
* **Clean package installs are a required acceptance case.** A test controller
  may no longer count a journey that silently lends the old install unreleased
  updater code. Personal files remain outside the bridge's write boundary.

## [1.81.6] — 🪜 Historic Mac upgrades recognise every known release shape (2026-07-31)

The full historic sweep found eight exact older Mac release shapes where the
updater stopped safely. This release teaches the bridge those verified layouts
without turning unknown installations into guesses.

**What this fixes for you:**

* **The eight known historic layouts have a supported route forward.** Dex
  recognises their exact release identities and can move them onto the protected
  two-step update path.
* **Unknown layouts still stop before personal files change.** Compatibility is
  granted only to the old release shapes proven by the fleet evidence.
* **The release safety gate keeps a recovery slot available.** It now blocks the
  release history one step before an older updater would run out of room to
  discover its bridge.
* **Fleet acceptance remains evidence-led.** The published journeys must still
  pass before Dex claims these repairs are live for every historic starting point.

## [1.81.5] — 🧾 Historic installs receive matching migration metadata (2026-07-31)

The public 1.49.0 journey crossed the repaired history proof, then found that
the read-only migration marker still named 1.20.1. The foundation migrator
correctly refused that mismatch before changing the fixture.

**What this fixes for you:**

* **Each historic install receives its own version marker.** The compatibility
  layer derives the read-only transition metadata from the installed package.
* **Malformed metadata still stops safely.** Missing, symlinked, or invalid
  package versions are refused before the migration can begin.
* **No compatibility file is written into the old vault.** The marker exists
  only inside the verified migration process and personal files remain guarded.

## [1.81.4] — 🏷️ Historic installs no longer need every old tag label (2026-07-31)

The first formal fleet run passed the oldest supported Dex release, then found
that later historic installers retained the trusted code history but not the
old `v1.20.1` tag label. The bridge stopped safely before changing the fixture.

**What this fixes for you:**

* **Later historic Dex versions can reach the bridge.** The updater can prove
  the exact trusted foundation from its commit and tree even when the old label
  was pruned by the installer.
* **The safety boundary remains exact.** A different commit, tree, object type,
  or unrelated history is still refused before personal files change.
* **The full Mac fleet can continue.** The fix addresses the shared blocker
  exposed by 1.49.0 without widening support to unknown repository layouts.

## [1.81.3] — 🧭 The oldest supported Dex can cross its local-history bridge (2026-07-31)

The full historic Mac journey reached the oldest published starting package,
1.20.1, and found that its one-time migration was blocked from reading its own
verified local Git history. It stopped safely before changing the fixture.

**What this fixes for you:**

* **The legacy bridge can build its private update history.** Only the exact,
  verified 1.20.1 migration process may read the vault's existing local Git
  store during the split.
* **The exception cannot reach the network.** The migration child switches from
  HTTPS-only to local-file-only access; it does not widen the bridge to accept
  both.
* **Machine-wide Git security remains untouched.** No global setting is written,
  and every other bridge operation keeps the existing HTTPS-only boundary.
* **Interrupted upgrades finish their health setup on retry.** If the foundation
  is already installed but Dex's current customization connection is still
  missing, the bridge shows the exact add-only change and asks before adding it.
* **Health checks see QMD only when it is really installed.** The sealed fleet
  journey exposes that one optional executable without inheriting other ambient
  machine commands.
* **Failures still stop before personal files change.** The original fleet
  attempt failed closed, and the journey continues to verify every protected
  user-file hash across both update hops.

## [1.81.2] — 🔗 The update bridge stays valid when a newer release goes live (2026-07-31)

The first public journey from Amit's 1.77.2 release found that the bridge still
compared its exact 1.81.0 foundation with the moving public release pointer.
Once 1.81.1 went live, that extra comparison stopped the journey even though the
verified foundation package itself was unchanged.

**What this fixes for you:**

* **A newer release no longer breaks the first hop.** Dex now verifies the exact
  immutable foundation package and gives that verified commit to the protected
  update lifecycle, without requiring the public “latest” pointer to stay frozen.
* **The bridge can continue to the second hop.** Its compatibility adapter now
  exposes the foundation's verified “fetch the next release” operation instead
  of stopping after the first healthy install.
* **The safety boundary is unchanged.** The tag object, commit, and tree must all
  match the declared foundation before Dex creates the private update pointer.
* **Failures still stop before your files are changed.** The public journey that
  exposed this issue failed closed; this patch changes only how the already
  verified foundation is handed into the lifecycle.

## [1.81.1] — ✅ The update bridge proves it can deliver its own follow-up (2026-07-31)

Dex 1.81.0 gave recent older installations a safe bridge back onto the protected
update route. This deliberately separate follow-up proves that the bridge
foundation can recognise, fetch, and deliver its own successor from the public
release channel.

**What this means for you:**

* **The bridge is a real route, not a one-off repair.** Recent older Dex versions
  can move through the 1.81.0 foundation and continue to this release using the
  same guided update journey.
* **Every handoff is pinned to one exact release.** Dex verifies the immutable
  public identity of the bridge before trusting it, so a similarly named tag or
  changed package cannot silently replace the tested foundation.
* **Your own files remain outside the release.** Both update hops use Dex's
  protected transaction boundary, with Doctor checking the result before the
  journey is allowed to count as complete.

## [1.81.0] — 🛟 Older Dex installations have a safe way forward again (2026-07-31)

Some people on recent older versions of Dex could see that an update existed but
still could not reach it through the normal guided route. Amit hit this on 1.77.2;
Jim hit it on a clean 1.79.0 install. Both stopped safely, but neither should have
needed a technical rescue.

**What this fixes for you:**

* **Recent older Dex versions can cross the update bridge.** Dex now has the
  missing, pinned handoff that lets those installations reach the protected
  self-updating foundation without asking you to use Git or replace files by hand.
* **Your files remain the hard boundary.** I exercised every distinct Mac release
  tree from 1.77.0 through 1.80.5 through two complete update hops. All 26 finished
  healthy, with every seeded user file unchanged.
* **The checkup uses the environment Dex actually installed.** Doctor and smoke
  now inspect the vault's own Python environment, so an installed dependency is
  no longer reported missing just because a different system Python was found
  first.
* **Retired empty skill folders stop looking broken.** If an update correctly
  removes an old built-in skill and leaves an empty folder behind, Doctor ignores
  that harmless shell. Linked, malformed, custom, or non-empty folders still fail
  closed.
* **Customized setups get useful, honest guidance.** Dex can show the safe evidence
  it verified and explain each excluded item separately, while still refusing to
  write a Capsule when the full safety contract is not met.
* **Daily review stays in the conversation you started.** It no longer forces a
  second thread, and it recognises a review that already exists for the day.
* **Meeting closeout can find notes from more than one provider.** Notes such as
  ClickUp AI are found wherever they legitimately live, and the closeout is written
  back to that source note rather than copied into a competing record.

This is the bridge foundation. The immediately following release is deliberately
separate so this version can prove it can fetch and deliver its own successor
through the same public route.

## [1.80.5] — 🔒 Your personal profile never ships in Dex (2026-07-29)

Dex's download package used to include a default profile file. It was not your
live profile, but it made the boundary between Dex's product files and your
personal information less clear than it should be. This release removes that
file from the package entirely.

**What this means for you:**

* **Your actual profile is never part of a Dex release.** Updating Dex leaves
  the profile you have already made for yourself alone.
* **New installs start from a safe template.** Dex creates your personal
  profile locally during setup, rather than carrying one in the download.
* **The protected update path stays the same.** Your notes, tasks, custom
  skills, and connections remain yours throughout an update.

## [1.80.4] — 🔒 Your profile stays exactly as you left it (2026-07-29)

During the one-time internal change that separates Dex from your own notes, Dex used to add a small internal marker to your profile. Your choices stayed safe, but it was still a change to a file that belongs to you. This release stops that entirely.

**What this means for you:**

* **Your profile remains byte-for-byte yours.** Dex no longer adds internal setup information to it while completing an update.
* **Dex keeps its own records in its protected internal area.** The update still knows what it needs to know, without borrowing space in your profile.
* **Nothing else about the update becomes less safe.** Your notes, tasks, custom skills, and existing connections continue through the same protected update path.

## [1.80.3] — 🔄 The complete update release (2026-07-29)

This is the fully checked package for the update improvement above. It makes the
safe, one-time final connection check available to older Dex installations through
the normal `/dex update` journey.

**What this means for you:**

* **One update command, wherever you are starting from.** Older Dex copies can fetch this package through the normal guided route.
* **The final setup step stays safe and clear.** Dex shows the one Dex-owned connection it may add, waits for a fresh yes, and never changes anything you already set up.
* **No silent half-finish.** The update reaches a healthy checkup rather than claiming success while leaving its own required connection missing.

## [1.80.2] — 🔄 Updating Dex now finishes the connection step (2026-07-29)

An older Dex could safely bring itself up to date, but one small part of its local setup could still be left behind. That meant the update looked complete while Dex's own checkup reported one missing Dex connection afterwards. This release closes that gap.

**What this changes for you:**

* **Dex checks the last missing step after an update.** If an older setup needs one Dex-owned local connection, Dex explains it plainly and shows you the exact change before doing anything.
* **Your own connections stay yours.** Dex only adds its one missing connection. It never replaces, removes, or edits any connection or setting you already have.
* **You stay in control.** This is a separate step with a fresh yes. If your settings change while Dex is waiting for your answer, it stops rather than guessing.
* **A completed update is genuinely healthy.** The old-version update journey now reaches a clean Doctor result instead of leaving that avoidable warning behind.

## [1.80.0] — 🔄 Updating Dex no longer needs Git (2026-07-29)

Updating Dex should be a normal, guided thing to do — not a technical recovery project. This release gives Dex the missing delivery step: from this version onward, `/dex-update` can fetch a verified new release itself, show you exactly what it found, and use the same protected update route that already keeps your notes safe.

**What this changes for you:**

* **Dex can bring the next release to you.** When an update is available, `/dex-update` no longer relies on you knowing Git or finding the right release by hand. Dex fetches the published release, checks that it is the real one, and prepares it locally before anything in your workspace changes.
* **You approve the exact update, not a vague promise.** Dex shows the files and changes in the specific release it fetched. It only applies that same checked release after a fresh yes. If the available release changes in the meantime, your earlier approval is not reused.
* **Your notes still go through one protected door.** Downloading an update is read-only. The eventual write remains inside Dex's existing transaction system, which protects user-owned material and can refuse rather than guess.
* **A new Dex starts setup reliably.** A first session now enters the one canonical setup flow, even if your first message is simply “hi”; an interrupted setup resumes safely instead of dropping you into a half-configured workspace.
* **Changing your role uses that same safe setup flow.** Dex asks first, previews the result honestly, and leaves your existing notes where they are — no second set of hand-written folder-moving instructions.
* **Older releases stay visible to the update check.** A release guard now stops duplicate release markers from quietly silencing older Dex copies again.

This is the foundation release for the simpler update experience. The complete historical-fleet proof continues separately: every old release will be exercised through this foundation and a following release before we claim universal update coverage.

## [1.79.0] — 📋 Your meetings get dealt with without you asking (2026-07-28)

Your meetings did arrive in Dex on their own — but turning them into something useful (updated pages for the people you met, tasks from what you agreed to do, tidy notes) still waited for you to ask. If you never asked, meetings quietly piled up half-done. The docs promised meetings "flow in on their own" — this release makes that promise true.

**What this fixes for you:**

* **Waiting meetings get handled when you start a session.** When you open Dex and there are meetings that haven't been dealt with yet, Dex notices and processes them in the background — person pages updated, tasks pulled out, notes filed — while you get on with whatever you came to do. It tells you in one line that it's happening.
* **It doesn't matter how the meeting got there.** Meetings synced from Granola, notes you pasted in and saved, files you dropped into your meetings folder yourself — Dex treats them all the same. You don't need Granola, or any connected service, for this to work.
* **Nothing gets done twice.** A meeting that's already been processed is never picked up again, and if you have several Dex windows open at once they won't trip over each other — the check stands down for half an hour once one of them has taken the job.
* **You stay in charge of individual notes.** If there's a meeting note you'd rather Dex never touched, one small marker in the note tells Dex to leave it alone permanently.
* **Meetings set aside for "manual processing" stop being lost.** If you'd chosen to process meetings by hand, Dex was setting each one aside in a waiting pile — and then nothing ever looked at that pile. Those meetings are now picked up, turned into proper notes, and handled with the rest.
* **Silence when there's nothing to do.** No message when everything's up to date.

### 🧭 Setting up Dex for the first time gets to the finish line

* **A brand-new setup no longer stops at its very last step.** Depending on how your computer was set up, the final step of a first install could fail and leave you with a half-finished Dex. It now uses the tools the installer has just prepared for it, so it finishes properly.

## [1.78.0] — 🛡️ The trust release: updating Dex works again, for everyone (2026-07-28)

### 📓 Your goals and career pages come back

Last week I made Quarter Goals and Career optional — off unless you asked for them — and retired the starter pages that came with each one. That was the wrong call, and one user found out the hard way. They had written a quarter's worth of real goals into the goals page Dex had given them. When that page stopped being part of Dex, their update stopped working. The safety check did its job and refused to run rather than touch the file — but nothing had ever warned them that a page they'd come to rely on was being taken away, and they had to dig their goals out of an old copy themselves.

**What this fixes for you:**

* **Goals and Career come with Dex again.** Both are set up from the start for a new vault, starter pages included. If you'd never expressed a preference either way, they're switched back on for you too.
* **A choice you made stays your choice.** If you ever turned either one on or off — during setup or afterwards — that decision stands, and nothing here overrides it in either direction. You can still switch any of them off with `/manage-capabilities`, and switching one off never deletes what you've already written.
* **Dex recognises its own pages again.** The starter goals page and the career evidence page ship with Dex once more, so when you write into them, an update knows what it's looking at instead of treating your work as a stray file it daren't touch.
* **Setup stops asking.** It used to put three yes/no questions to you about rooms you hadn't seen yet, right when you were trying to get started. All three now simply come with Dex, and setup tells you so in a sentence.

Thanks to Amit, who reported this and worked out exactly what had happened.

### 🔧 Updating Dex actually works again

This one is humbling. To find out why updates felt untrustworthy, I took five real copies of Dex — today's version, and installs frozen at four older moments, loaded with real notes and real customisations — and ran each one's genuine update against the live product, step by step, the way you would. The reassuring part first: **across all five, not one byte of anyone's notes was ever at risk.** Every time something hard-stopped, it was the safety machinery correctly refusing to guess. The embarrassing part: nearly everything *around* that machinery was failing people.

**What this fixes for you:**

* **The guided update runs again.** Since mid-June, an internal label deep in the update engine was never moved forward — so on every copy of Dex installed or updated since then, running the update crashed before it did anything. Technically-minded people worked around it by hand, which is exactly why nobody reported it. The label now moves automatically with every release, a check refuses to publish a release where it hasn't, and if that check ever does fire on your machine, it explains itself in plain words instead of a wall of code.
* **A far-behind Dex can always hear about updates.** Older versions gave up if too many releases had come out since theirs, and a second, deeper limit was weeks away from silencing *every* copy, including brand-new ones. Both limits are gone from this version onwards — being years behind will never again mean being told nothing. I'm also cleaning up the leftover duplicate release markers from the old build bug, which is what lets older installs start hearing announcements again on their own.
* **The checkup stops telling healthy setups they're broken.** This was a chorus of false alarms, several firing on every install in the world: an overnight check that flagged a file which wasn't missing, a demand for a software piece the installer never provides, six of Dex's own files reported as suspiciously modified when they were untouched, your own task list described as a "modified Dex file", and two "broken skills" that have never existed — with advice to run an update that couldn't fix them. After a successful update, this chorus would tell you the update had *failed* and offer to undo it. Every one of these now tells the truth.
* **One bad moment no longer haunts you.** If a single update check failed — say you were offline — the checkup reported Dex as broken forever after, even once everything was fine. A later success now clears the old failure on its own.
* **Machines with unusual setups are believed.** If your tools live somewhere non-standard, Dex's checkup used to declare the whole setup broken. It now finds your tools where they actually are, checks them properly, and only then passes judgement.
* **Updating from an old Dex finishes the job.** An older copy updating the old way used to land "half-arrived": the new machinery present but not switched on, features silently off, five skills gone without a word — under a message saying "✅ Update successful!". The checkup now notices that state and completes it, reconnecting what you had, without ever touching your notes.

Thanks again to Amit, whose three precise bug reports started all of this — every one of them is fixed in this release.

### ✨ Also new in this release

* **An optional calendar that teaches Dex your rhythm** over your first few weeks, and Dex now **learns which days you actually work** rather than assuming Monday to Friday.
* **Company pages arrive switched on for new vaults** — existing setups stay exactly as they are.
* **Setup got smarter**: it recognises more of the tools you already use, offers meeting notes earlier, and mentions `/connect` so you know it exists.
* **The connections list tells the truth**: a wrongly-claimed "reviewed" integration and inflated tool counts on the live page are corrected.
* **Installing Dex is one line**: the front page now leads with a single command that sets everything up.

## [1.77.2] — 🔔 Dex can tell you about updates again (2026-07-27)

Yesterday's fix was half the story. Chasing it properly — by testing against the real thing rather than a stand-in — turned up something considerably worse: **Dex had stopped telling almost anyone that updates existed.**

**What this fixes for you:**

* **You get told when there's a new version.** Dex checks for updates by looking at what's been published. Every time I merged any piece of work, a duplicate marker was created for the version already released — so Dex would find several different things all claiming to be the same version, sensibly conclude it couldn't tell which was real, and say nothing at all. That happened within minutes of every release, so for most people the update notice had quietly stopped working entirely. Each version now produces exactly one published copy, and Dex can read it again.
* **Being a long way behind no longer makes it worse.** Dex would give up if too many versions had come out since yours — so the further behind you were, the more certain it became that you'd never hear about an update. It now simply looks at the newest one.
* **The "release notes" link goes to the release notes.** It pointed at an internal build reference where nothing is written. It now takes you to the page that actually explains what changed.

**Why I didn't see it:** my tests built a small pretend copy of the project with two or three versions in it, where none of this can happen. The real thing has over a hundred published markers, duplicates going back several versions, and a page that wasn't where the code assumed. Nothing was wrong with the tests — they were just testing a world that doesn't exist. Dex is now checked against the real published releases before any of this is called working, and there's a new guard that refuses to publish a second copy of a version that's already out.

If you've been on an older version for a while and never saw an update prompt, this is why — and it should now appear on its own.

## [1.77.1] — 🩺 Dex stops crying wolf, and older setups can find their updates again (2026-07-27)

Both of these came from one user's bug report, and both only affect people who've been using Dex for a while — which is exactly why neither had been spotted.

**What this fixes for you:**

* **Old problems stop being reported as though they're happening right now.** Dex keeps a log of things that have gone wrong. Nothing ever cleared it, so a checkup could tell you your setup was broken because of something that failed weeks ago and was fixed long since. Problems now fade into history after 30 days — and anything that went wrong on a version of Dex you've already moved past is treated as history immediately. When Dex does report a problem, it now tells you the date it happened, so you can see at a glance whether it's news.
* **Dex admits when it couldn't look, instead of reporting all clear.** If that log couldn't be read at all, the checkup used to come back clean. It now says plainly that it couldn't check — a checkup that can't see something should say so, not reassure you.
* **Setups on an older version can find updates again.** If you were on an older version of Dex, the update check could get permanently stuck: no version, no explanation, nothing useful, every single time. It was looking for a small file that older versions never had. Dex now recognises an older setup for what it is and gets on with the check.
* **The update message is finally readable.** It used to open with a warning that Dex "has not authenticated its publisher", followed by two forty-character codes. It now simply tells you a newer version is available, links you to the release notes, and says to run `/dex-update` when you're ready. The technical detail is still there in `/dex-doctor` for anyone who wants it. Dex still never updates itself without you.

**Why this slipped past me:** every test I had imagined someone who'd installed Dex that morning — current, with no history behind them. Both of these problems only bite people with months of real use. Dex is now tested against genuinely old versions, and against a clock wound forward, so this kind of thing gets caught before you ever see it.

## [1.77.0] — 🔌 Connect Dex to your tools (2026-07-27)

Dex could always work with a handful of tools it was wired into directly. Connecting anything else was a manual job, and mostly you didn't bother.

Now Dex knows how **831 different tools handle signing in**, and can connect you to **627 of them** today. You say "connect Notion" and Dex works out what that one needs and walks you through it.

**What this gives you:**

* **Paste a key, and you're done.** For around 350 tools it's that quick — I timed it at **one second**, no forms, no browser, nothing to approve.
* **Browser sign-ins take one setup, once.** For the other 279, Dex doesn't arrive with a pre-arranged identity at Google or Slack — deliberately, because that would mean your sign-in passing through us. So the first time, you register Dex yourself in that tool's settings. It's the most technical thing I'll ever ask of you, it's once per tool ever, and I'll talk you through it.
* **Logins that renew themselves.** Sign-ins expire — that's the app being careful, not something breaking. I renew them quietly before they lapse. You'll never see it.
* **I fix what I can before you notice.** At the start of a session I check your connections and repair what I'm able to, speaking up only when something genuinely needs you.
* **Encrypted, and never off your machine.** On a Mac the key that unlocks your sign-ins sits in the macOS Keychain. Nothing is sent to us — there's no server holding your logins, because there's no server.
* **Leaving is clean.** Disconnect a tool and I delete its sign-in from your machine, and remind you to remove Dex in that tool's own settings too.

One honest note: on the command line these sign-ins aren't shielded from other software already running as you — the same as any tool that keeps logins on your computer. The Dex desktop app adds a fingerprint check on top of that.

### 🚪 Setting up Dex — four things that tripped people up on day one

* **Your email is accepted however you type it.** "@acme.com" or your whole address — I work out what you meant.
* **Working solo no longer stops you.** Setup told you to leave the company field blank, then refused blank. That dead end is gone.
* **I now ask your company's name.** I always had somewhere to put it but never actually asked.
* **The time estimate is honest.** It claimed 5 minutes and took 10. It now says 10.

### 📅 Your first week, and a workload count that adds up

* **Setup now ends by showing you your actual week**, rather than an optional tour most people skipped.
* **Your daily plan stops counting days off as meetings.** Flights, holidays and out-of-office were each landing as a meeting in your workload — enough to make a quiet week look stacked. This reaches everyone on update, with no re-setup needed.
* **I tell the truth when I can't see your calendar**, instead of a confusing error.
* **I no longer claim to have built person pages I never built.**

## [1.76.1] — 🔧 A quiet strengthening under the hood (2026-07-27)

Nothing changes in what you see or do. This is internal hardening of the customisation-rebuild feature that shipped in 1.76.0.

**What changed, honestly:**

* **The rebuild now goes through the same single safety gate as everything else.** Every change Dex makes to your vault is meant to pass through one guarded door, so a single place can back it up, check it, and (in future) ask your permission. The new rebuild step had been reaching the file-writing engine through a second path; it now goes through the one door like everything else — which means any future safety, consent, or audit check automatically covers the rebuild too.
* **An interrupted rebuild now has a proper recovery route.** If a rebuild step is stopped partway, Dex can now converge it safely through that same door. Previously that recovery only existed in internal tests.

I re-proved the whole rebuild end to end on a real, heavily-customised vault through the actual update journey before shipping. No behaviour changed for you — this only makes the foundation harder to get wrong later.

## [1.76.0] — 🪄 Dex can now rebuild your customisations on a new version — with your say-so at every step (2026-07-27)

Yesterday gave customised setups a guided update with a protected snapshot (the Capsule). Today the rebuild goes live: `/dex-update` can now carry your customisations forward onto the new version — proven end-to-end on a real, heavily-customised vault before being offered to anyone.

**What this does for you:**

* **Dex rebuilds what you built.** After an update, Dex proposes how each of your customisations maps onto the new version, rebuilds them in a safe staging area, and checks them — showing you the verdict for each one honestly: verified, needs your eyes, or can't be safely verified.
* **You approve every step, freshly.** Nothing goes live until you've seen exactly what will be written and said yes to *that exact* preview. An earlier yes never counts for a later step.
* **It's undoable while its snapshot is retained.** Every activation is snapshotted first (Dex keeps your three most recent) and can be rewound byte-for-byte, as long as the rebuilt files haven't been changed since. Dex tells you plainly when a rewind is and isn't available.
* **Upfront about its limits.** Anything Dex can't verify — a script it can't safely test, a customisation whose contents it isn't allowed to read — is marked for your review, never silently "migrated". And if a step is interrupted mid-flight, Dex now knows exactly how to recover it.

## [1.75.2] — 🏠 Your notes get their own home, and Dex learns to guide customised setups through it (2026-07-26)

This is the release I asked heavily-customised users to wait for. Two big things land together: the move that separates Dex itself (the part updates replace) from your notes (the part updates must never touch) is now proven and guided — and if you've customised Dex, `/dex-update` now walks you through updating without losing track of anything you've built.

**The move, proven on a real vault:**

* **Tested on a real vault before being offered to anyone.** Before this reached users, I rehearsed the whole move on full copies of a genuine, seven-month-old working vault — including deliberately pulling the plug halfway through — and confirmed the undo put every file back exactly as it was. That rehearsal caught four real problems, all fixed here: Dropbox users were wrongly turned away, very large vaults could fail near the finish line, file names with accents (like "Häfele") could wrongly stop the move, and on the rare setup where Dex does have to say no, it now explains the quick fix instead of just refusing.

**The guided journey for customised setups:**

* **`/dex-update` now offers a guided path if you've customised Dex.** It shows you the full inventory of what you've changed, explains what the update will touch, and walks you through step by step. Plain setups keep the same quick update as before.
* **Your customisations get a protected snapshot first.** Before anything changes, Dex offers to create a **Capsule** — a protected local record of the evidence of every customisation. It lives inside your vault, is never uploaded, survives the update, and is only created after a fresh, explicit yes — with a receipt.
* **Dex Doctor watches over it.** The deep checkup verifies your Capsule is intact, says so honestly when it can't, and any future session knows how to resume an interrupted journey properly.
* **What this deliberately doesn't do yet:** Dex does not rebuild your customisations automatically on the new version. That ships only after it passes rehearsals on genuinely heavily-customised real setups — your Capsule is the foundation it will build on.

**A second look at how your app sign-ins are stored** (the connections feature is still closed to users; this is groundwork):

* **Dex now tells you where the key to your credentials is kept.** Normally it lives in your Mac's Keychain, sealed away from your notes. On the rare setup where that isn't available, it sits in your vault folder instead — which means a copy of that folder is a copy of your sign-ins. Dex used to look identical either way. Now it just says which, so you can see it rather than assume.
* **"Disconnect" no longer overpromises.** It removes the credential from your machine — but the app itself can still have permission in your account until you remove it there. Dex now says so, and points you at the right place, instead of leaving you to assume you were fully unhooked.
* **A disconnect leaves nothing behind.** If a credential file had previously been set aside as damaged, disconnecting didn't clear it. Now it does, so removing a connection really removes it.
* **Nothing an outside service says gets written down unexamined.** If a connected app sent back an error message, Dex saved it as-is for troubleshooting. A misbehaving service could have used that to get something sensitive written into a plain-text log. Dex now strips anything sensitive out first.
* **A stray browser tab can't interrupt you mid-connect.** While you were connecting an app, another page open in your browser could quietly cancel it and leave you wondering what went wrong. That window is closed.
* **Sturdier under odd setups.** If your credentials folder or key arrived from a backup with loose permissions, Dex now tightens them before use rather than trusting them, and refuses outright if something looks tampered with. And account names that could have collided into the same file — quietly breaking one of two connections — are now rejected up front.

Still no change to day-to-day use for connections — and the `/connect` doorway stays deliberately closed until it passes an independent security review. Also in this release: a fix so DexDiff workflow sharing publishes to the right place.

## [1.75.1] — 🔍 Dex Doctor now knows exactly what you've customised (2026-07-24)

*(This is the v1.75.0 feature release, re-cut: v1.75.0's packaging step was incomplete, so its update bundle never published. Nothing else changed.)*

If you've made Dex your own — edited a built-in skill, added your own scripts or instructions, wired up your own connections — updating has always carried a quiet worry: *what will this touch?* Until now, Dex could promise not to overwrite your files, but it couldn't tell you what you'd actually changed. Now it can.

**What this does for you:**

* **A full inventory of your customisations, on demand.** Run `/dex-doctor` and its deep check now works out — file by file, against the exact version you installed — what's standard Dex, what you changed, what you added, and what depends on what (a skill you edited that calls a script you wrote, which reads from a folder you renamed).
* **It changes nothing.** This is a read-only report. Doctor never edits, moves, or "fixes" your customisations — it shows you the map so you can update with your eyes open.
* **It refuses to guess.** If Dex can't verify exactly which version you're on, it says "I can't tell you what you've changed" instead of showing a falsely reassuring zero. I'd rather Dex admit uncertainty than hand you a wrong all-clear right before an update.
* **Your secrets stay out of it.** Credential files and keys are excluded before they're ever read — nothing sensitive appears in the report, and I attacked this with independent adversarial reviews (which caught and closed a real leak path before release) to make sure.

This is step one of the guided upgrade for customised setups I posted about — the piece that rebuilds your tailoring on new versions is coming behind its own safety gates.

## [1.74.0] — 🔌 Groundwork: connecting your other tools, tested against the real world (2026-07-24)

Dex is getting a built-in way to connect the other tools you use — starting with Google Calendar and Linear — so it can work with what's in them instead of asking you to copy-paste. That doorway isn't open yet, but this release lands the machinery behind it, after a security review and live end-to-end testing with real Google and Linear accounts.

**What this gets ready for you:**

* **Your sign-ins will be stored sealed.** Keys and tokens are kept encrypted on your machine, and Dex refuses to save them at all if the safety wrapper around them can't be set up.
* **Nothing gets trusted without proof.** A connection only counts as working after Dex has checked it live. And if you ever replace a key or reconnect an account, the new credential has to prove itself from scratch — it inherits nothing from the old one.
* **Dead connections fail loudly, not quietly.** If a key is revoked or a sign-in expires, Dex tells you and stops using it, instead of limping along half-working.
* **Google is asked for the minimum.** Calendar connections request read-only access to your calendar — the smallest permission that does the job. (Live testing caught Google rejecting the request because it didn't say what access it wanted; that's fixed and locked in with a test.)

Nothing changes in day-to-day use yet — this is the foundation the connections feature will stand on.

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
* **Every change comes with an undo.** Each applied change produces a receipt, and Dex can restore things to exactly how they were, down to the last detail. If you've edited a file since, Dex refuses to undo over your edit and tells you which file, instead of destroying your work.
* **A crash can never leave you half-changed.** Pull the plug at any instant during an apply or an undo and you end up either fully done or exactly where you started. This was independently attack-tested at every possible interruption point.
* **Databases get real protection.** Some tools keep your data in database files that a straightforward copy can silently corrupt. Dex now backs these up the one safe way, verifies the result, and — after a security reviewer proved a subtle power-loss risk — restores them in an order that no crash timing can corrupt.
* **A heads-up if your vault lives in Dropbox, iCloud, or OneDrive.** Sync services can corrupt databases mid-write, so Dex now asks before backing up a database inside one.
* **Honest housekeeping.** Dex keeps the last three undo points (about the last three changes), warns if they ever grow past about 2GB of disk, and tells you plainly when something is too old to undo.

Every piece of this release passed an independent security review, deliberately trying to break it, before it shipped.

---

## [1.65.0] — 🔍 Dex now knows exactly what an update would change — before it changes anything (2026-07-21)

Until now, updating Dex meant trusting that the new version and your vault would get along. This release gives Dex full sight before any future update touches anything.

**What this changes for you:**

* **Every release now carries a complete packing list.** Each new version of Dex ships with an exact inventory of what's inside, and the release build fails if that list is ever incomplete — so "what's in this update?" always has a precise answer.
* **Dex can now read your vault like a map — without touching it.** It can tell what came from Dex, what you've customized (so updates will respect it), what's yours alone, and what it doesn't recognize. Anything unrecognized is reported honestly instead of guessed at.
* **You'll be able to skip parts of an update safely.** The planning engine guarantees that saying "not this one" to any piece never changes what happens to the rest — each piece is decided completely on its own.
* **`/dex-doctor` gained two new checks** that report on all of the above, in the same honest working / off / broken / couldn't-check language as everything else.

This completes the "look, don't touch" phase of the update-safety program. Next up: applying updates through this map, with automatic backups and undo in a single step.

---

## [1.64.0] — 🛡️ Updates that can no longer harm your files, and the last of the leftovers cleared out (2026-07-21)

This release finishes two stories that began yesterday: making Dex updates fundamentally safe, and getting the last of the maker's own files out of your install.

**What this changes for you:**

* **Updates now run through a protected engine.** For vaults on the new layout, updating no longer mixes Dex's changes into your files the old way. Instead: Dex backs everything up, applies the new version, checks its own work, and can undo the whole thing exactly. If your machine crashes mid-update, you end up either fully updated or exactly where you started — never in between.
* **Your vault can become fully yours.** New machinery (not yet switched on by default) can separate Dex's code from your content entirely, so your notes live in their own private space, with its own history, that updates physically cannot touch — with a practice run first and a single step to change your mind.
* **A few old files from the maker's setup are being retired the safe way.** If you ever edited them, your copies are preserved exactly; nothing of yours is touched.
* **Fresh installs land in the right shape automatically**, with plain-English guidance if anything needs a decision.

---

## [1.63.0] — 🏠 Dex only sets up the rooms you actually need (2026-07-20)

Until now every Dex install arrived fully furnished — career coaching, company pages, quarterly goals — whether or not any of that matched your working life.

**What this changes for you:**

* **Dex asks what your work life actually looks like.** New setups keep the core always on — meetings, people and tasks — then ask three quick yes-or-no questions: do you want a Career room, a Companies room, a Quarterly Goals room? Say no and they simply don't exist in your vault, so you're not left with empty folders about a job you don't have. You can switch any room on or off later, and switching one off never deletes anything you wrote.
* **If you already use those features, nothing changes.** Existing setups keep every room exactly as it is.
* **The foundations for worry-free updates are in place.** Dex now has a single rulebook saying, for every file, whether it belongs to Dex or to you — plus a new update engine that backs up before touching anything, checks its own work, and can undo it exactly. If an update is ever interrupted, even by a crash, your files end up either completely untouched or completely updated — never half-done. You'll feel this properly in the next few releases, as updating becomes a single step with one-click undo.
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

Behind the scenes, I can now build a test version of Dex alongside the normal one, and every version gets a permanent marker pointing at exactly what was in it. Nothing changes for you yet.

**What this changes today:**

* **The normal version is unaffected.** Stable releases are still tidied up and published on GitHub exactly as before.
* **Test builds are ready internally.** Once a test line of Dex exists, it can be built with the same tidying and the same packing list as the stable one — without being published, and without becoming the version people get by default.
* **Every version Dex builds keeps a permanent identity.** Each one is marked so its exact contents and packing list can still be found later — which is what lets a rollback reach an older version reliably.
* **You can't choose the test version yet.** Updating, rolling back, and switching between the stable and test versions all behave exactly as before; the controls come later.

---

## [1.60.0] — 🧪 Behind the scenes: more test-version groundwork (nothing changes for you yet) (2026-07-13)

Dex now has the internal groundwork needed for a future opt-in test version. Its health check understands which line of Dex an installation is on, so future test users will not get false "couldn't verify" warnings from being compared against the stable version.

**What this changes for you today:**

* **Stable updates work exactly as before.** Existing installations still use the stable release path, including profiles that do not yet contain the new internal setting.
* **Unverifiable channels fail safely.** Health checks report that they could not verify a missing beta release or invalid channel instead of treating it as broken or silently trusting stable code.
* **Beta is not selectable yet.** This release adds only the safety foundation; update, rollback, and channel-switching controls will arrive separately.

---

## [1.59.0] — ⏱️ Dex stops calling a working feature "broken" just because your Mac was slow to start it (2026-07-13)

Dex's health check gave built-in services just 1.5 seconds to wake up. On a slower or busy machine, a service could still be starting normally when Dex labelled it broken. Those services now get a fair eight-second window, with enough room in the overall check for the slower start to finish without changing the usual quick path.

**What this fixes for you:**

* **Slow starts no longer look like failures.** `/dex-doctor` and nightly health checks wait long enough for working built-in services to answer, even when your machine is under load.
* **Unusually slow setups can choose a longer window.** If your built-in services genuinely need more than the standard eight seconds, you can set `DEX_MCP_HANDSHAKE_TIMEOUT` to the number of seconds you want; if it's missing or doesn't make sense, Dex safely keeps the standard eight.

---

## [1.58.0] — ✅ Your tasks and priorities are handled more carefully (2026-07-13)

A close review of the code that edits your task and priority files turned up eight ways Dex could quietly mishandle them. All eight are now fixed, each locked in by a test so they can't come back.

**What this fixes for you:**

* **Completing a task marks the *right* one.** If two tasks had similar wording — one title sitting word-for-word inside the other — and neither had an ID, saying "done" could flip the wrong task. Dex now matches the exact task, and refuses to guess when it's genuinely ambiguous rather than picking wrong.
* **"Done" actually completes an open task.** If an already-completed copy of a task sat above an open one, Dex could report success without ticking the open one. It now finds the open task and completes it.
* **A file you've edited on Windows stays as you left it.** Completing a task in one no longer quietly rewrites every line in the file — only the one task line changes.
* **Checkbox text inside a task title is safe.** A task whose title happened to contain checkbox characters is no longer mangled when completed.
* **Weekly priorities stay in order.** New "Top 3" priorities are added at the bottom, numbered in sequence — no more entries landing out of order or two items sharing a number.
* **A fourth priority is handled gracefully.** Adding beyond three no longer corrupts the list; the item is numbered correctly and Dex gently notes that "Top 3" is meant to keep your focus tight.
* **Backlog ideas rank correctly.** A captured idea now sorts into the right spot by score instead of jumping ahead of higher-scored ones, and marking an idea implemented no longer alters its title.

---

## [1.57.0] — 📡 Help catch a bad update early — without sharing a word of your content (2026-07-13)

Opt in to help catch bad releases across all vaults — anonymous nightly health counts, no content ever.

**What this fixes for you:**

* **Bad releases can show up within hours.** If you explicitly opt in, Dex shares one tiny verdict after its nightly self-check so maintainers can see when the same update starts breaking across installations.
* **Your work never joins the report.** The verdict contains only counts of what passed and failed, the name of the failing check when something is wrong (drawn from a fixed list), which version of Dex you're on and which line of it, and a random installation number. It never includes names, notes, filenames, paths, or file contents.
* **This choice is separate and defaults to no.** Existing analytics consent does not enable health sharing. Missing, pending, or malformed consent sends nothing, and you can turn health telemetry on or off in plain language anytime.
* **You can inspect every attempt yourself.** Dex keeps a private record on your own machine, line by line, of exactly what it would send — including the times it sent nothing because you hadn't opted in, and the times a send was dropped because the connection failed.

---

## [1.56.0] — 👀 Dex notices the apps you actually have installed (2026-07-13)

When Dex suggests connecting a tool, it now leans on real evidence — is the app sitting in your Applications folder? Is the connector already half set up? — instead of just scanning your notes for mentions. A tool you actually have installed is a far better signal than a passing reference to one.

**What this fixes for you:**

* **"Installed on your Mac" beats a guess.** When Dex offers to connect Things, Trello, Todoist, Zoom, or Teams, it now checks whether the app is actually installed and leads with that — so its suggestions feel observant, not random. An installed app is strong enough to surface on its own.
* **Half-finished setups get noticed.** If a tool's connector is already configured but sync was never switched on, Dex spots the loose end and offers to finish it, rather than treating it as brand new.
* **Suggestions say why.** Each recommendation now comes with its reason in plain words — "installed on your Mac", "already set up but not switched on yet", or how many times you mentioned it — so you understand where the nudge came from.
* **Nothing leaves your machine.** The check is a quick look at your Applications folder and your own settings files — nothing is sent anywhere, and it quietly does nothing on computers that aren't Macs, where those apps don't apply.

---

## [1.55.0] — 🤝 Contributing to Dex is now safer (2026-07-13)

Contributing to Dex is now safer — automatic checks catch personal data before it's shared, and tell contributors in plain English what their change touches.

**What this fixes for you:**

* **Personal details are stopped before a change is accepted.** The automatic checks look only at newly added lines, and name the exact file and line when they find a real email address, a filled-in personal profile or connection identity, personal vault content, or someone's own Dex instructions.
* **Every contribution gets a product map.** A report pinned to the change translates the files touched into recognizable parts of Dex, the things people use them for, and the checks that apply. Outside contributors get exactly the same report on the results page when GitHub won't let me post it as a comment.
* **Messy real-world content gets tested.** The throwaway practice vaults now include accented characters and spaces in filenames, half-written notes, duplicate task headings, and settings files with recoverable mistakes in them — backed by fast automated tests and larger overnight stress tests.
* **A busy machine no longer makes one of my own checks look broken.** One release check now gets more breathing room and a single retry if it simply ran out of time. What Dex promises you at run time is unchanged.

---

## [1.54.0] — 🧾 See exactly what Dex checked before a release reached you (2026-07-13)

Dex's release checks were rigorous but invisible once a release reached you. Each successful release build now publishes a small public page showing the evidence for that exact version, without turning checks that did not run into reassuring green ticks.

* **The proof is tied to one release.** The page names the exact version, the exact snapshots of the code it was built from and published as, when it was checked, and which build produced it.
* **Every check tells the truth.** Checks the successful build actually ran are marked passed; checks that only apply while a change is being proposed are marked plainly as not applicable and not run. Missing evidence stays unknown.
* **A failed later build cannot rewrite history.** The published page remains labelled as the last successful release build, so it never claims to describe newer code that failed.

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

Tools you build yourself used to sit permanently at "can't tell", because Dex won't run your own code during a checkup without permission. You can now ask `/create-mcp` to prove, once, that one of your tools starts up properly — and, as a separate choice that stays off unless you turn it on, tell Dex it may trust one exact file of yours during nightly and deeper checkups.

* **Your permission is specific and honest.** Dex first shows you exactly which file in your vault it means, along with a fingerprint of its contents, and says plainly that this runs that file as you, and trusts everything the file pulls in.
* **Changed code never inherits old permission.** The name, the location, and the file's fingerprint must all still match. Dex takes both the fingerprint and its own private copy from the very same file it opened — nothing can be swapped underneath it — and only ever runs that copy.
* **Everything else is only checked from the outside.** Anything Dex can't safely vouch for — a missing file, a shortcut standing in for the real one, changed contents, a broken settings list, unusual start-up options, anything that runs over the internet or as a ready-made program, or an entry someone typed in by hand — is refused, with the exact reason.
* **Your trust choices remain yours.** `System/trusted-mcps.yaml` is never shared or shipped, and it's on the list of your own files that an update has to preserve — so an update from me can never add or change what you've trusted.

---

## [1.51.0] — 🔁 Things 3 and Trello sync join the party (2026-07-13)

Real two-way sync landed for Todoist in the last release. This one brings your Mac's Things 3 and your Trello boards onto the same engine — so whichever task app you actually live in, Dex keeps step with it.

**What this fixes for you:**

* **Things 3, fully local, now syncs.** Ask Dex to sync and your pending tasks appear in the right Things Area (mapped from your pillars), the urgent ones land in Today, completions flow both ways, and anything you drop into your Things Inbox comes back for review in your morning plan. No accounts, no network — it all happens on your Mac through Things' own scripting.
* **Trello boards stay in step.** New Dex tasks become cards in the right list, finishing a task moves its card to Done, and cards you add or move on the board come back to you for review — matched to the exact lists you picked during setup, not guessed from their names.
* **Tasks from either tool arrive through your review, never behind your back.** Whatever you created in Things or Trello queues up in your daily plan, where you decide what becomes a Dex task — with duplicate checks and pillar linking — instead of it silently appearing in your backlog.
* **A task title with an apostrophe can't break things anymore.** The Things connection was rebuilt to hand your task text to macOS safely, so quotes, apostrophes, and punctuation in a task name just work instead of causing a failure.
* **Your pillars, not someone else's.** Both connections now read the Areas and lists from your own setup rather than falling back to a fixed built-in set of categories that only fit one person's vault.
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
  task creation, built-in services, skills, and its automatic background steps in temporary copies without writing
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
* **Meetings nobody has turned into tasks get a nudge.** If meetings are sitting with action items nobody turned into tasks, the plan says so and points at `/process-meetings`.
* **Quiet when there's nothing to review.** No "0 tasks from meetings" noise on quiet days.

## [1.47.0] — 🔧 Behind the scenes: my own checks stopped tripping over themselves (2026-07-12)

The automated checks that run on every proposed change could fail with a confusing "cannot find a common ancestor" error that had nothing to do with the change itself — a self-inflicted glitch in how the checks fetched the project's main line.

**What this fixes for you:**

* **Contributor and update checks stop flaking.** The checks now download the project's main line in full instead of a partial copy, so they can always compare your change against it. The earlier partial-fetch was the actual cause of the spurious "no common ancestor" failures — not, as first suspected, anything rewriting the project history.
* **A guard keeps it from coming back.** A new test stops the release if any check goes back to the partial copy.

---

## [1.46.0] — 🔧 Two recent fixes, finished properly (2026-07-12)

An independent review of this week's safety fixes caught two cases where a fix didn't fully deliver what it promised. Both are now closed.

**What this fixes for you:**

* **Checking a task off directly in your task list now updates everywhere.** A recent change meant that ticking a box straight in `Tasks.md` (rather than through chat or a person page) quietly stopped updating the linked person and meeting pages. Those updates flow through again.
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
* **Deep checks exercise real journeys without risking your vault.** Dex loads settings files,
  creates and updates a task, starts only Dex's own built-in services, and checks every skill
  and background step in temporary copies. It never runs skills you wrote yourself, contacts the network,
  or writes into your live vault.
* **Updates and rollbacks verify the result.** Both flows run the doctor and its quick
  self-tests before declaring success, and rollback cleanup uses Dex's own list of the files
  it shipped, so files you created remain yours.
* **Changes to shipped Dex files are visible before an update.** The doctor warns which
  modified files may conflict while leaving the places you're meant to customize alone.

## [1.44.0] — 🧠 Person pages now get smarter, not just longer (2026-07-12)

Dex started building person pages by itself — meetings, tasks, dates piling up. But accumulation isn't understanding: a page that only grows becomes a list nobody reads. A new tidying pass fixes that.

**What this fixes for you:**

* **Every active person page keeps a living summary.** A short "who this person is to you right now" section — role, what you've been meeting about, open threads — distilled from their recent meetings and tasks, refreshed as things change.
* **It never touches your own writing.** The summary lives in its own clearly marked block. If you ever edit inside that block, Dex takes the hint and permanently stops maintaining that page's summary (and the doctor checkup tells you it did).
* **Costs stay small and predictable.** At most five pages per sync, each page at most weekly, and only when something new actually happened for that person. It runs only if you already use an AI key for meeting processing, and one settings line (`entity_gardener: enabled: false`) turns it off.
* **Nothing is written on a bad day.** If the AI returns nothing useful, the page is left exactly as it was — and failures now print the actual reason instead of just an error count.

---

## [1.43.0] — ✅ Adding a task never fails just because a priority is busy (2026-07-12)

When a priority level was already full, Dex used to refuse to create the task at all — and that refusal was easy to miss in a wall of on-screen text, so the task either vanished or landed at the wrong priority.

**What this fixes for you:**

* **Your task always gets created.** If a priority level is over its guideline, Dex still adds the task there and simply notes that the level is getting crowded — it never silently drops the task or quietly downgrades it.
* **The nudge is gentle, not a wall.** You see a one-line heads-up with the current count, so you can rebalance when you choose to — not mid-thought.
* **A pillar keyword like `1:1` no longer breaks task filing.** Certain shorthand written in your pillar settings could crash the step that guesses which pillar a task belongs to; it's now handled safely. Thanks to stevegranshaw for reporting.

---

## [1.42.0] — 💬 Dex now tells the truth about what your setup can do (2026-07-12)

Some setup and recovery guidance could promise features that never reached your active Dex, point you to skills that did not exist, or treat an optional choice as a failure.

**What this fixes for you:**

* **Model setup no longer leads you into a dead end.** Dex used to offer budget and offline settings that only ever configured Pi — a separate tool Dex no longer ships — so they did nothing. They're gone, and Dex no longer guesses how much memory your computer has.
* **Parked meeting experiments stay out of your way.** A leftover beta handout for meeting rituals, never wired up, no longer tells testers that `/daily-plan` will surface recurring-meeting previews when that feature is not connected.
* **Integration prompts now open a skill that exists.** Setup and post-update guidance sends you to `/integrate-mcp` for Notion, Slack, and Google Workspace instead of naming skills Dex cannot run.
* **Calendar onboarding fits your operating system.** macOS users still get the permission steps they need; Windows and Linux users now get a clear explanation that calendar sync is macOS-only and can continue setup without looping on impossible instructions.
* **Optional features are described consistently.** A feature that is off stays calm and healthy, a missing or broken feature includes the real fix, and an uncertain check simply admits it could not verify the state.
* **Developer-only test tools no longer clutter your install.** One-off diagnostics and an obsolete background-job repair tool are gone; `/dex-doctor` remains the supported place to check background-job health.

---

## [1.41.0] — 🩺 Your checkup now tells the truth on a brand-new Dex (2026-07-12)

A fresh install could mistake other Dex products or optional features for failures, miss one of its own services, and inherit integration choices that belonged to the release builder.

**What this fixes for you:**

* **Other Dex products stay out of your checkup.** Background jobs belonging to a different Dex installation are skipped in one quiet note instead of being reported as broken against the wrong vault.
* **Calendar access tells you exactly what is missing.** Write-only access is now explained as insufficient for reading your calendar, with the right guidance to grant full access; unfamiliar permission states include the value Dex actually received.
* **Every built-in service is checked.** The session-memory service is included on fresh installs, and an automatic consistency check prevents future services from being added without being checked.
* **Checkup totals add up.** Status summaries now use the numbers from the checkup that just ran instead of copying contradictory example totals.
* **Career features stay quietly optional.** If career tracking is not set up, Dex offers the setup skill calmly without an error, a missing-file warning, or a private path from your Mac.
* **New installs start genuinely clean.** Slack and every related meeting or planning automation begin off, so a new vault no longer inherits someone else's connected-tool state or gets noisy connection warnings.
---

## [1.40.0] — 🎙️ Granola setup now tells you the truth (2026-07-12)

Granola could be fully connected while Dex said it was missing, look ready without the key it needed, or ignore your choice to process meetings manually.

**What this fixes for you:**

* **Connected now means ready to sync.** Setup and the background checks now look for the actual Granola key that meeting sync needs, so simply having the app installed — or an old leftover file — can no longer produce a false green light.
* **Manual processing stays manual.** Choosing manual mode now saves the setting in the right form, and existing vaults with the older form are still understood instead of silently switching to automatic processing.
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
* **Name a person, get the right link.** Say "task about the pricing deck for Sarah" and Dex matches "Sarah" against your people directory — by email, alias, or name. If two Sarahs match, it asks instead of picking one. It never invents a link to a page that doesn't exist.
* **Companies match from a name, a web address, or even a link.** "acme.com", "Acme", or a pasted link all find the same company page.
* **Tasks find their goal.** When a new task clearly serves one of your quarterly goals, it links itself. When the match is only likely, it links with a visible "(?)" you can confirm or clear — uncertain never masquerades as certain.
* **Old meeting notes heal instead of breaking.** If an old note already carries one of the legacy made-up IDs, Dex adopts it rather than creating a rival one, so nothing you have is left stranded.
* **Pillar names just work.** You can refer to a pillar by its display name ("Deal Support") or its internal ID — both work.

## [1.37.0] — 👥 Your people and company pages now build themselves (2026-07-12)

Dex has always said your person and company pages would look after themselves. Until now they didn't. Nothing actually created a page, four different page layouts had grown up side by side, and the step meant to update someone after a meeting had quietly been doing nothing since the day it shipped. This is the release where the promise becomes real.

**What this changes for you:**

* **Pages appear on their own.** When someone turns up in your meetings often enough to matter, Dex creates their page — their role, the company they're at, and the history of when you've met. Same for the companies behind them. You choose whether this happens automatically, gets suggested to you first, or stays off.
* **Colleagues and outsiders get filed correctly.** Dex tells them apart by their email address rather than guessing, so customers stop landing in your internal folder.
* **One page layout, at last.** Pages in any of the older formats still open and still work — Dex reads them all. Anything it genuinely can't make sense of is set aside untouched rather than overwritten.
* **Your own writing is off limits.** Dex only ever edits inside its own clearly marked section of a page. Anything you wrote yourself it leaves exactly as it found it.
* **Finding the right person got much better.** Dex works through email, then nickname, then full name, then first name — and when two people could both be the match, it asks you instead of picking one.

## [1.36.0] — ✅ Every promise about tasks is now one Dex keeps (2026-07-12)

A few task features described things that didn't actually happen: the Todoist, Things, and Trello setups promised automatic two-way sync that was never built, the inbox triage helper read planning files from locations that no longer exist, and some flows quietly wrote tasks in a way the rest of the system couldn't track. This release makes every promise honest, and every way of capturing a task creates a real, tracked task.

**What this fixes for you:**

* **Todoist, Things, and Trello setups now tell the truth.** They connect Dex so you can check, create, and complete tasks in those apps *on request, in conversation* — and they say plainly that there's no automatic background sync. Before, setup walked you through configuring "auto-sync" choices that did nothing.
* **Inbox triage reads your real plans again.** `/triage` was reading your weekly priorities and quarterly goals from folders that were reorganized long ago, so its routing suggestions ignored your actual priorities.
* **Every captured task is now a real task.** Triage and end-of-day follow-ups used to write plain checkboxes into files; those never got a task ID, so completion tracking, duplicate detection, and goal progress couldn't see them. Both now create tasks properly, carrying the person, company, due date, and goal details they learned along the way.
* **Phone-captured items are handled honestly.** The morning-plan flow claimed one tool both checked and created your captured tasks; it only checked. The instructions now match reality, and the misleading option was removed from the tool itself.

## [1.35.0] — 🗂️ Tasks now remember what you told them (2026-07-11)

When you created a task and confirmed its pillar and priority, Dex wrote them down — and then never read them back, re-guessing both from the task's wording every time it listed your tasks. A P0 could show up as P2 unless its title happened to sound urgent. This release makes task details stick, and adds the fields tasks always needed.

**What this fixes for you:**

* **The priority and pillar you confirm are the ones you see.** Lists, focus suggestions, and limits now read the stored values instead of guessing from the title.
* **Tasks linked to a weekly priority finally count.** Goal and week progress now include tasks you created through Dex — before, those links were written where nothing could read them, so those totals showed zero.
* **Tasks can carry a due date, a project, and a quarterly goal.** All optional, all checked when set — an unknown goal or missing project file gets a helpful error listing what's available instead of a silent dead link.
* **Duplicate detection stops teaching the wrong habit.** When Dex flags a similar task, you can now say "create it anyway" — before, the suggested workaround was to reword the title, which defeated the duplicate check entirely.
* **A rare data-loss bug is gone.** Adding a task to a section whose heading appeared twice in your task file could silently delete everything after the second heading. Inserts are now safe no matter what your file looks like.
* **Completed tasks stay clickable in Obsidian.** The completion timestamp used to be written where it broke Obsidian's link-to-this-line feature; it now goes before the link marker.
* **Meeting prep sees all your meetings again.** Synced meetings are stored in dated folders that the meeting memory never looked inside — daily plans and meeting prep were blind to them. Both now scan the full folder tree.

## [1.34.1] — 🤝 Dex's release checks no longer break contributor setups (2026-07-12)

Release checks now leave the copy of the project's history on your machine intact, and explain when they cannot compare it.

**What this fixes for you:**

* **My checks no longer trim down the copy of the project history on your machine.** They now leave it intact when you run them yourself.
* **A failed history comparison now explains how to fix it.** Instead of stopping with no output, Dex tells you to fetch the full project history and try again.

## [1.34.0] — 🔗 People in your notes now link themselves — safely (2026-07-11)

People auto-linking was promised but never shipped (issue #46); this release finally delivers it with safeguards that keep links accurate.

**What this fixes for you:**

* **People become connected on their first useful mention.** Full names, unique aliases, and safe unique first names now create links back to the right person page without cluttering every mention.
* **Dex never guesses on ambiguous names.** Shared first names, common English words, and names that could refer to someone unknown stay as plain text.
* **Your identity and carefully formatted text stay untouched.** Your own name, existing links, note metadata, code, and Markdown links are preserved, and running the feature again adds nothing extra.

---

## [1.33.0] — 🚦 'Off' and 'broken' now mean different things — everywhere (2026-07-11)

Dex could describe an optional feature as broken in one place and merely disconnected in another; this release gives those responses one shared meaning.

**What this fixes for you:**

* **Optional features stay peacefully off.** If you deliberately did not enable or configure something, Dex treats it as healthy, never uses an error tone, and never nags you to fix it.
* **Real failures stand out.** “Broken” is reserved for a feature that is configured and expected to work but is failing, so genuine problems no longer look like personal setup choices.
* **Missing software has its own answer.** When a required app, or a piece of software it depends on, is missing, Dex says that directly instead of calling the feature broken.
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

Empty calendar results were traced back to onboarding guessing a work calendar name that did not match the names Apple Calendar actually uses.

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
* **Release checks now use Dex the way you do.** They complete real onboarding and task journeys, confirm meeting updates are written back, start every built-in service, validate every shipped skill, and run every automatic background step in a separate test vault. Packaging and startup failures should be caught before an update reaches you.

*Version note: Dex's own version number jumps from 1.26.0 to 1.28.0 to catch up with the already-published 1.27.0 changelog entry.*

---

## [1.27.0] — 🩺 /dex-doctor: a real system checkup that tells the truth (2026-07-11)

Replaces `/health-check` with a rigorous whole-system diagnostic that knows the difference between "off", "broken", "couldn't check", and "fine" — built against the exact ways things broke in the July 2026 audit.

**What this fixes for you:**

* **One honest answer to "is my Dex actually working?"** Run `/dex-doctor` and get a clear report: what's healthy, what's broken, what's switched off by choice, and what the doctor itself couldn't verify. Nothing is hidden, nothing is collapsed.
* **It heals what's safe to heal, silently.** Missing standard folders, an out-of-date settings file, helper scripts that lost permission to run — it fixes these before reporting and tells you it did. For riskier fixes (starting a background job, repairing a broken setting) it proposes one at a time and only acts on your yes.
* **Background jobs are checked honestly — freshness, not just presence.** The doctor confirms each installed Dex job actually ran recently, says when it last ran if it's stale, and spots a job that can no longer start before it becomes your problem.
* **Replaces `/health-check`**, which diagnosed Granola by looking at a file the connector never reads and had other stale assumptions. All references now point at `/dex-doctor`.
* **Deep scan available.** Ask for the deep scan and Dex will actually contact the tools you've connected — Granola, your calendar, and the rest — to confirm the real lookups work, not just that the settings look right.

---

## [1.26.0] — 🧹 A tidy-up, and one missing piece finally shipped (2026-07-11)

The final batch from the dex-core audit — removing things that looked real but were wired to nothing, and shipping one thing that was real but never left the developer's machine.

**What this changes for you:**

* **The integration concierge actually ships.** The vault scanner that recommends which tools to connect (used by onboarding and `/getting-started`) existed only on the developer's Mac — it was never included in the release, so the tour silently skipped it for everyone. It's now included, with its setup-skill references corrected.
* **People auto-linking is paused instead of broken.** Dex's instructions required running a helper that was never shipped (issue #46) — failing with an error on every meeting note and daily plan. The instruction is removed; the real auto-linking feature is queued to be built properly.
* **Deleted two settings files nobody was reading** — they looked official, were wired to nothing, and were behind the whole family of "this service can't be reached" bugs.
* **Removed a dead installer step and a settings file** nothing ever read.

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

The last batch of fixes from my top-to-bottom review of Dex.

**What this fixes for you:**

* **"Task marked done" now means it.** If updating a completed task failed in some of its locations, Dex used to report success anyway. It now tells you exactly which locations updated and which failed.
* **No more phantom "something's failing" warning for search you never enabled.** Search-by-meaning is no longer switched on for everyone in advance; it's set up when you actually enable it (`/enable-semantic-search`), or automatically at install if it's already on your machine.
* **Empty calendar results now explain themselves.** If your configured work calendar doesn't match any real calendar, Dex says so and lists the calendars it can see — instead of silently returning nothing.
* **The safety guard actually guards.** A safeguard that blocks damaging actions on your computer had never been switched on, so it had never once run. It's now active.

---

## [1.23.0] — 🩺 The health system tells the truth (2026-07-11)

Fixes from my top-to-bottom review of Dex (every finding independently confirmed before fixing).

**What this fixes for you:**

* **Dex's per-session health check now actually runs.** It was silently skipped on every real install — it looked for a folder layout that only existed on the developer's machine. It now runs when you start a session, stays silent when everything is healthy, and says so if it can't run at all.
* **The background-job checker no longer looks away from real breakage.** It used to skip over Dex's own folders entirely, which hid exactly the failure people were hitting (a background job pointing at a piece of software that isn't there). It now checks directly that every Dex background job can actually start.
* **The changelog-checker background job works on Apple Silicon.** It was looking for a piece of software in a location that only exists on older Intel Macs, so on modern Macs it failed every six hours, forever, without a word. Dex now finds where that software actually lives — and refuses to set up a background job that can't run.
* **Instructions match reality (shipped in 1.22.x line).** Ten places where Dex's own instructions described things that weren't true — search tools named wrongly in the daily skills, the Granola check looking at a file nothing reads, optional Apple Reminders steps that weren't marked optional, and references to files that don't exist.

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

* **No more false "your install is broken" alarm.** On startup, Dex sometimes warned that none of its connected tools were ready and that it "may need reinstalling" — even when everything was working perfectly. It was looking in the wrong folder. Fixed.
* **Tasks won't get wrongly rejected.** Adding a task could fail with "priority limit exceeded" even when you only had a couple of tasks at that level, because Dex was miscounting and reading the priority from the wrong place. It now reads your real backlog correctly.
* **The budget AI model works again.** The low-cost option still pointed at a Google model that has since been retired, so it could fail. It now uses the current Gemini 2.5 Flash (still around 90% cheaper than Claude).
* **Behind the scenes:** the automatic checks that run on every release no longer fail for no reason, so Dex's own release process is healthy again.

Nothing to do on your end — just update.

---

## [1.20.0] - Granola Meetings Now Sync the Official Way (2026-06-01)

For a while, Dex pulled your Granola meetings by reading Granola's local files on your machine. That worked until Granola encrypted those files in v7.162.6, and the local route quietly stopped being viable.

Dex now connects to Granola the supported way: through the official connection Granola offers. It pulls both your notes and your transcripts directly from Granola, so nothing depends on poking around in files on your machine anymore.

**What this means for you:**

* Meeting sync uses Granola's official, supported connection, so there is no more reading of files on your machine
* Both your notes and full transcripts come through
* It keeps working through Granola updates, including encryption changes

**To connect:** Run `/granola-setup` and Dex will walk you through adding your Granola access key — a long password Granola gives you. That access comes with Granola's Business plan, which is available to individuals, not just companies, at $14 a month. You do not need a big corporate plan.

---

## [1.19.0] — Semantic Search Now Covers Your Entire Vault (2026-03-23)

### 🔍 Semantic Search Now Covers Your Entire Vault

**Before:** Smart search only covered 6 folders — meetings, people, projects,
accounts, tasks, and goals. Finding anything in your product briefs, plans, or
session notes required remembering exact keywords.

**Now:** Search by meaning — finding notes by what they're about, not the exact
words — covers 14 areas across your whole vault. Product briefs, plans, session
notes, and reference docs are all searchable this way.

**Result:** Ask "what did we decide about notifications?" or "find past work
on connecting other tools" — Dex finds the right content wherever it lives.

**To pick up the new areas:** Run `/enable-semantic-search`.

---

## [1.18.3] — Setup No Longer Fails on Modern Macs + Jira/Confluence Connects Properly (2026-03-21)

**Setup fix (affects most Mac users):**

Installing Dex and running `/dex-update` used to stop partway through on modern Macs. Some of Dex's helpers are written in a language called Python, and newer Macs refuse to let anything add extra pieces to the copy of Python your computer already relies on.

Dex now keeps its own private set of those helpers inside your vault folder instead. That works on every kind of computer and never touches the one your machine depends on.

**What changed:**
* Installing Dex sets up its own private helper folder inside your vault — no more failures partway through
* Dex's connected tools now use those private helpers instead of your computer's
* `/dex-update` uses the same private helpers, and sets them up first if you're coming from an older Dex
* Windows is handled automatically

**Jira + Confluence fix:**

`/atlassian-setup` pointed at a piece of software that doesn't exist, so connecting Jira and Confluence could never work. Atlassian's official route is a hosted connection — there's nothing to install.

**What changed:**
* Dex now points at Atlassian's official hosted connection
* Nothing to paste in — you just sign in to Atlassian in your browser

**What you need to do:** Run `/dex-update` to get these fixes. If your setup previously stopped partway through, run `./install.sh` again.

---

## [1.18.2] — Fix Background Meeting Sync Installation (2026-03-12)

Setting up automatic meeting sync failed, because it was looking for two files that no longer exist: an old Granola sign-in helper (Granola now saves your sign-in by itself) and a second version of the sync script that was never finished. The original one works fine.

**What changed:**

* The background job now points at the sync script that actually exists
* Setup now checks that Granola has saved your sign-in, instead of calling the removed helper
* No more separate browser sign-in step — Granola handles it automatically
* The sign-in check now simply reports whether you're signed in, instead of running a script that isn't there

**What you need to do:** Run `./install-automation.sh` again — it should complete without errors now.

---

## [1.18.1] — Meeting Sync Now Works Reliably Again (2026-03-05)

In v1.17.0, I switched background meeting sync to Granola's official connection — thinking the "official" route would be more reliable. Turns out that route sends meetings back as free-form writing, meant for an AI to read in conversation, not as tidy data a background job can work with. The sync couldn't make sense of it and quietly fell back to the older meetings already saved on your machine. Meetings were going missing with no error message.

I've switched to connecting to Granola directly instead. It sends back tidy data, includes mobile recordings, and uses the sign-in Granola already keeps on your machine — no separate sign-in needed.

**What this means for you:**

* Meeting sync is reliable again — no more silent failures
* Mobile recordings still sync (that wasn't the problem — the data source was)
* One fewer thing to sign in to: no separate Granola sign-in step
* If you previously went through that extra sign-in setup, you don't need to do anything — the new approach uses your existing Granola sign-in automatically

**What changed under the hood:**

* Background sync now connects to Granola directly instead of going through the official middle layer
* Three helper files that are no longer needed have been removed
* Meetings already saved on your machine are still used when you're offline

---

## [1.18.0] — Skills Now Ask for the Right-Sized AI + Safer Skill Updates (2026-03-02)

Dex skills now say what size of AI they need, so cheap, fast models handle the simple work and the more expensive ones stay reserved for heavy thinking.

**What this means for you:**
- Many built-in skills now state which model they'd prefer
- That preference is written the same way across all the built-in skills
- Updating Dex now knows how to handle those preferences when your version and mine differ

**Conflict handling improvement:**
- During `/dex-update`, when a skill has changed on both sides, Dex can now settle it for you by:
  - keeping your own edits to that skill
  - taking only the new model preference from my version
  - leaving your `*-custom` skills completely alone

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
- Background sync now uses Granola's official connection instead of a homemade one
- If that connection drops for a while, Dex falls back to the meetings already saved on your machine
- Migration detection tells you when the upgrade is available — no guesswork

**If you set up Dex before this update:** Run `/dex-update` and Dex will detect the upgrade opportunity. When you next run `/process-meetings`, it'll offer to connect you to Granola's official connection.

---

## [1.16.0] — 🕷️ Scrapling is your default web scraper (2026-03-01)

When you share a URL with Dex — an article, a blog post, a page you want summarized — it now uses **Scrapling** every time. Scrapling is free, runs on your machine, and handles sites that block other tools (including Cloudflare-protected pages).

**What this means for you:**
- Share a URL, get the content. No accounts, no credits, no limits.
- Sites that used to come back empty (anti-bot protection) now work out of the box.
- Your data never leaves your machine — Scrapling fetches locally, not through a cloud service.

**What changed under the hood:** Dex now has a safety guard that enforces Scrapling as the default. If the AI ever tries to use a different scraper, the guard catches it and redirects to Scrapling automatically. You don't need to do anything — it just works.

**If you set up Dex before this update:** Run `/dex-update` and Scrapling will be added to your tools automatically. If it asks you to install it, just run: `pip install "scrapling[ai]" && scrapling install`

---

## [1.15.0] — 🔌 The Integrations Release (2026-02-19)

This is a big one. Dex now connects to 8 tools where your real work happens — and it goes both ways. Complete a task in Dex and it's done in Todoist. Get an email flagged in your morning plan because someone hasn't replied in 3 days. See your Jira sprint status right next to your weekly priorities.

Some of you have already been building your own integrations using `/create-mcp` and `/integrate-mcp` — and honestly, that's impressive. But I kept hearing the same thing: "I just want to get up and running without figuring out the plumbing." So it's built in now.

---

### 🔗 8 integrations, ready to go

Each one takes a few minutes to set up. Run the skill, answer a couple of questions, and you're connected. Dex tells you exactly what changed — which skills got smarter, what new capabilities unlocked.

**Communication:**
- **Slack** (`/slack-setup`) — Chat context in your daily plan and meeting prep. Unread DMs, mentions, active threads. No admin approval needed — just Slack open in Chrome. 2-minute setup.
- **Google Workspace** (`/google-workspace-setup`) — Gmail, Google Calendar, and Docs in one connection. Email digest in your morning plan. Follow-up detection flags emails waiting for replies: "Sarah hasn't replied to your pricing email from Monday." Meeting prep shows recent email exchanges with attendees. 3-minute setup.
- **Microsoft Teams** (`/ms-teams-setup`) — Same as Slack but for Teams users. Works alongside Slack — both digests appear, clearly labeled. If your company uses both, Dex handles both.

**Task Management:**
- **Todoist** (`/todoist-setup`) — Two-way task sync. Create in Dex, appears in Todoist. Complete on your phone, done in Dex. Your pillars map to Todoist projects. 1-minute setup.
- **Things 3** (`/things-setup`) — Two-way sync for Mac users. No account needed, works offline, everything stays on your own Mac. Your pillars map to Things Areas, P0/P1 tasks go straight to Today. 30-second setup.
- **Trello** (`/trello-setup`) — Board sync. Cards become tasks. Move a card to "Done" and it's complete in Dex. Your Trello board and your task list stay in sync.

**Meetings & Knowledge:**
- **Zoom** (`/zoom-setup`) — Access recordings, schedule meetings. Smart enough to know if Granola already handles your meeting capture so they don't step on each other.
- **Jira + Confluence** (`/atlassian-setup`) — Sprint status in your daily plan. Project health from Jira. Confluence docs surfaced during meeting prep.

### 🔄 Two-way task sync

This is the headline feature. Connect Todoist, Things 3, Trello, or Jira and your tasks flow between systems automatically. One task in Todoist maps to one task in Dex — even though Dex shows it in meeting notes, person pages, and project pages. Complete anywhere, done everywhere.

The sync is safe by design — it creates, completes, and archives. It never deletes anything.

### 👋 New users: pick your stack during onboarding

When new users set up Dex, Step 8 now asks what tools they use. Pick Gmail and Todoist? You'll be walked through connecting both, and at the end Dex shows you exactly what changed: "Your daily plan now includes an email digest. Meeting prep shows recent emails with attendees. Tasks sync both ways with Todoist." Each tool connection ends with a clear summary of what just got smarter.

### ⚡ Existing users: add integrations anytime

Already using Dex? Just run the setup skill for any tool:

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

Some corporate IT policies restrict access for third-party tools. If you hit a wall during setup — a blocked consent screen, a missing permission — just ask Dex about it. There are often creative workarounds: personal access keys that don't need admin approval, or tools like Things 3 that stay entirely on your own machine and never touch corporate systems. Dex generally finds a way if you give it a go.

### 📋 Smarter daily plans and meeting prep

Every skill that touches your day got more useful:

- **`/daily-plan`** now includes email digest, Slack/Teams digest, external task status, Jira sprint progress, and Trello card updates — all in one view.
- **`/meeting-prep`** pulls in recent email exchanges, Slack/Teams messages, Zoom recordings, Confluence docs, and Jira/Trello context for every attendee.
- **`/week-review`** shows email stats, Zoom meeting time, tasks completed across all your tools, and how fast work is moving in Jira, alongside your existing review.
- **`/project-health`** surfaces Trello board status and Jira sprint health for connected projects.
- **`/dex-level-up`** spots unused integration capabilities — "You connected Gmail but haven't enabled email follow-up detection. Try it."

### 🩺 Integration health

Dex checks whether your connected tools are healthy each time you start a session. If something's gone stale — a sign-in that's expired, a service that's dropped out — you'll know right away with a friendly nudge to reconnect, instead of discovering it mid-meeting-prep.

---

## [1.14.0] — 🧠 Dex Got a Brain Upgrade (2026-02-19)

This is the biggest single release since semantic search. Dex remembers things now. It gets smarter each day you use it. Sessions stay fast all day. And your skills take care of their own housekeeping instead of leaving it to you.

---

### 🧠 Memory

**Cross-session memory.** When you start a new chat, Dex now opens with context from previous sessions — what you decided, what's been escalating, what commitments are due. No more re-explaining where you left off. Your daily plan opens with "Based on previous sessions: you discussed Acme Corp 3 times last week, decided to move to negotiation, and Sarah committed to send pricing by Friday — that's today." That context was invisible before. Now it's automatic.

**Critical decisions persist.** When you make an important decision in a session — "decided to move Acme to negotiation by March" — it now survives across sessions. Critical decisions appear at every session start for 30 days, so you never lose track of what you committed to.

**Meetings kept as summaries.** Every meeting you process now gets saved as a short summary instead of the full transcript. Meeting prep and daily planning are dramatically faster — same intelligence, fraction of the processing time.

**Memory that compounds.** The six agents that power your morning intelligence — deals, commitments, people, projects, focus, and pillar balance — now remember what they found in previous sessions. First run, they scan everything. Second run, they know what they already told you. Resolved items quietly drop off. New issues are clearly marked. And things you've been ignoring? Dex notices. "I've flagged this three sessions running. Still no action. This is a pattern, not a blip."

**Faster people lookups.** Dex now keeps a lightweight directory of everyone you know. Instead of scanning dozens of files every time you mention someone, it reads one small index. Looking up "Paul" instantly returns the right person with their role, company, and context. The index stays fresh automatically — it rebuilds during your daily plan and self-heals if it goes stale.

**Memory ownership, clarified.** With multiple memory layers now active, I've documented exactly what owns what. Claude's built-in memory handles your preferences and communication style. Dex's memory handles your work — who said what in which meeting, what you committed to, which deals need attention. They stack, not compete. See the new Memory Ownership guide in your Dex System docs.

---

### 🔍 Intelligence

**Pattern detection.** After 2+ weeks of use, Dex starts noticing your patterns. "You've prepped for deal calls 8 times this month but checked MEDDPICC gaps only twice." Recurring mistakes get surfaced before you make them. Emerging workflows get noticed so you can turn them into skills.

**Identity snapshot.** Dex now automatically builds a living profile of how you actually work — your goals, priorities, task patterns, learnings, and skill ratings all feed into it. Not self-reported traits — observed patterns. What pillar gets neglected under pressure. Which skills you rate highest. Where your blind spots are. It refreshes during weekly reviews and Dex reads it when making prioritization suggestions. You can also run `/identity-snapshot` anytime to see it on demand.

**Skill quality signals.** After key workflows like daily plans, meeting prep, and reviews, Dex asks one optional question: "Quick rating, 1-5?" Your ratings accumulate over time. During weekly reviews, if a skill has been trending down, Dex surfaces it with context — "Your meeting prep averaged 2.8 this week, common note: missing context from last meeting." If everything's fine, you hear nothing. Ratings also feed into anonymous product analytics so I know which skills to invest in.

---

### ⚡ Performance & Safety

**Sessions that last all day.** Your heaviest skills — daily plan, weekly review, meeting prep, and seven others — now run in their own space instead of loading everything into your main conversation. Previously, running `/daily-plan` then staying in that chat all day meant things got slower and muddier by the afternoon. Now each skill does its work separately and hands back just the result. Stay in one chat from morning planning through end-of-day review without penalty.

**A safety net for risky actions.** A protective layer quietly watches everything Dex runs on your computer and stops the catastrophic ones before they happen — wiping a disk, deleting a project outright, overwriting shared work. Everything normal passes straight through, with no slowdown. You never notice it until the one time it saves you.

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

If you've made improvements to your Dex setup that could help others, I'd love to see them. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to share — no technical background required.

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

**Say `/health-check` anytime** to get a full diagnostic: which services are running, what's failed recently, and — for most issues — a suggested fix. Missing something? It tells you exactly what to run. A setting wrong? It offers to repair it.

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

It's also significantly faster and lighter. Instead of Claude reading entire files to find what's relevant, the search engine hands back just the relevant snippets. One developer measured a 96% cut in how much text Claude has to read per search.

**When does this matter?** Honestly, if your vault has fewer than 50 notes, keyword matching works fine. As your vault grows into the hundreds of files, keyword search starts missing things — and that's where this upgrade earns its keep.

---

This is powered by [QMD](https://github.com/tobi/qmd), an open-source local search engine created by Tobi Lütke (founder and CEO of Shopify). Everything runs on your machine — no data leaves your computer.

> "I think QMD is one of my finest tools. I use it every day because it's the foundation of all the other tools I build for myself. A local search engine that lives and executes entirely on your computer. Both for you and agents." — [Tobi Lütke](https://x.com/tobi/status/2013217570912919575)

**Setup required.** Semantic search is available but requires running `/enable-semantic-search` to set it up (5 min, 2.5GB download). New users are offered this during onboarding. Once enabled, all vault searches automatically find things by meaning instead of exact words — the skills don't change, Dex simply gets smarter about how it searches and uses QMD whenever it's there.

**What gets better when you enable it:**

- **Planning & Reviews** — `/daily-plan`, `/week-plan`, `/daily-review`, `/week-review`, and `/quarter-review` all become meaning-aware. Your morning plan surfaces notes related to today's meetings by theme ("onboarding" pulls in "activation rates"). Your weekly review detects which tasks contributed to which goals — even when they weren't explicitly linked. Stale goals get flagged with hidden activity you didn't know about.

- **Meeting Intelligence** — `/meeting-prep` finds past discussions related to the meeting topic, not just meetings with the same people. `/process-meetings` catches implicit commitments like "we should circle back on pricing" — soft language that keyword extraction would miss.

- **Search & People** — All vault searches become meaning-aware. Person lookup finds references by role ("the VP of Sales asked about..."), not just by name.

- **Fewer duplicate tasks** — Dex spots when a new task means the same thing as one you already have ("Review Q1 metrics" matches "Check quarterly pipeline numbers"). Same for improvement ideas in your backlog.

- **Natural Task Completion** — Say "I finished the pricing thing" and Dex matches it to the right task, even when your words don't match the title exactly.

- **Career Tracking** — If you use the career system, skill demonstration is now detected without explicit `# Career:` tags. "Designed the data migration strategy" automatically matches your "System Design" competency.

**If you don't enable it,** nothing changes — everything continues to work with keyword matching, just as it always has.

Part of the philosophy with Dex is to stay on top of the best open-source tools so you don't have to. When something like QMD comes along that genuinely makes the experience better, I build it in — you run one skill and your existing workflows get smarter.

**Smart setup, not one big pile.** When you run `/enable-semantic-search`, Dex looks through your vault and recommends purpose-built search areas based on what you've actually built — people pages, meeting notes, projects, goals. Each area comes with a short description of what that content is, which sharpens the results a lot. Generic tools dump everything into one big pile. Dex tells your search engine how your vault is actually organised.

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

**Now:** Role selection, company size, and other choices are presented as clickable lists — just pick from the menu. Dex detects your platform once at the start (Cursor vs Claude Code vs terminal) and uses the right question tool throughout. Calendar detection works regardless of whether Calendar.app is in the foreground or background. Testing now runs in a practice mode, so nothing of yours gets overwritten.

**Result:** Onboarding feels polished — fewer things to type, fewer silent failures, works correctly whether you're in Cursor or Claude Code.

---

## [1.6.0] - 2026-02-16

### ✨ Dex Now Discovers Its Own Improvements

**Before:** When new Claude Code features shipped or you had ideas for how Dex could work better, it was up to you to remember them and add them to your backlog. Keeping track of what could be improved meant extra manual work.

**Now:** Dex watches for opportunities to get better and weaves them into your existing routines:

- `/dex-whats-new` spots relevant Claude Code releases and turns them into improvement ideas in your backlog
- `/daily-plan` highlights the most timely idea as an "Innovation Spotlight" when something new is relevant (e.g., "Claude just added built-in memory — here's how that could help")
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

**Before:** Dex relied entirely on the app you run it in (Cursor, Claude Code) to tell Claude the current date. If that app didn't say it clearly enough, Claude could lose track of what day it was — especially frustrating during daily planning or scheduling conversations.

**Now:** Dex states today's date at the very top of everything it loads when a session starts, so it's front-and-center no matter which app you're in.

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

**Behind the scenes:** Dex's own instructions in `.claude/CLAUDE.md` now cover how to work out the pillar. Every task still has to have a pillar (that's what keeps your data clean) — Dex just works it out and confirms it with you first.

---

### ⚡ Calendar Queries Are Now 30x Faster (30s → <1s)

**Before:** Asking "what meetings do I have today?" meant waiting up to 30 seconds for a response. Old events from weeks ago sometimes appeared in today's results too.

**Now:** Calendar queries respond in under a second and only show events for the dates you asked about. No more waiting, no more ghost events.

**One-time setup:** After updating, run `/calendar-setup` to grant calendar access. This unlocks the faster queries. If you skip this step, everything still works — just slower.

---

### 🐛 Dex Now Works Wherever Your Vault Lives

**Before:** A few features — Obsidian integration and background automations — didn't work correctly on some setups.

**Now:** Dex finds your vault wherever you keep it. Everything works no matter your username or how your folders are arranged.

**How to update:** In Cursor, just type `/dex-update` — that's it!

**Thank you** to the community members who reported this. Your feedback makes Dex better for everyone.

---

### 🔬 X-Ray Vision: Learn AI by Seeing What Just Happened

**What was frustrating:** Dex felt like a black box. You knew it was helping, but you had no idea what was actually happening — which tools were firing, how context was loaded, or how you could customize the system. Learning AI concepts felt abstract and disconnected from your actual experience.

**What's new:** Run `/xray` anytime to understand what just happened in your conversation.

**Default mode (just `/xray`):** Shows the work from THIS conversation:
- What files were read and why
- Which tools Dex used
- What context was loaded at session start (and how)
- How each action connects to underlying AI concepts

**Deep-dive modes:**
- `/xray ai` — The basics of how AI works: how much it can hold in mind at once, why it forgets between chats, and how it uses tools
- `/xray dex` — How Dex is put together: its instructions, its automatic triggers, its connected tools, its skills, and your vault structure
- `/xray boot` — The session startup sequence in detail
- `/xray today` — ScreenPipe-powered analysis of your day
- `/xray extend` — How to make it yours: edit Dex's instructions, create skills, add automatic triggers, connect new tools

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
   - Uses Notion's own official connection

2. **Slack Integration** (`/integrate-slack`)
   - "What did Sarah say about the Q1 budget?" → Searches Slack
   - Meeting prep includes recent Slack context with attendees
   - Person pages show communication history
   - Signs in using the Slack session already open in your browser (nothing to register), or a Slack app key if you prefer

3. **Google Workspace Integration** (`/integrate-google`)
   - Gmail thread context in person pages
   - Email threads with meeting attendees during prep
   - Calendar event enrichment
   - One-time sign-in through Google (~5 min)

**Where you'll see it:**
- `/meeting-prep` — Pulls context from all enabled integrations
- Person pages — Integration Context section with Slack/Notion/Email history
- New users — Onboarding Step 9 offers integration setup
- Existing users — `/dex-update` announces new integrations and spots the tools you've already connected

**Smart detection for existing users:**
If you've already connected Notion, Slack or Google yourself, Dex spots that and offers to:
- Keep your existing setup (it works!)
- Switch to the versions Dex recommends (better maintained, more features)
- Skip and configure later

**Setup skills:**
- `/integrate-notion` — 2 min setup (just needs an access key from Notion)
- `/integrate-slack` — 3 min setup (uses your browser sign-in, or a Slack app key)
- `/integrate-google` — 5 min setup (sign in through Google)

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

**What was frustrating:** Dex only worked with Claude, which costs money and requires internet. Heavy users faced high AI bills, and travelers couldn't use Dex on planes or trains.

**What's new:** Two new ways to use Dex:

1. **Budget Cloud Mode** — Use cheaper AI models like Kimi K2.5 or DeepSeek when online
   - Save 80-97% on AI costs for routine tasks
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
- Custom skills or tool connections you create
- Any content you write or manage
- Who you meet with or what you discuss

**The ask:**

During onboarding (new users) or your next planning session (existing users), Dex will ask once:

> "Dave could use your help improving Dex. Help improve Dex? [Yes, happy to help] / [No thanks]"

Say yes, and you help Dave understand which features work and which need improvement. Say no, and nothing changes — Dex works exactly the same.

**Behind the scenes:**
- Your answer is recorded in `System/usage_log.md`
- Nothing is ever sent unless `analytics.enabled: true` in `System/user-profile.yaml`
- 20+ skills now report their usage when you've opted in

**Beta only:** This feature is currently in beta testing.

---

## [1.2.0] - 2026-02-03

### 🧠 Planning Intelligence: Your System Now Thinks Ahead

**What's this about?**

Until now, daily and weekly planning showed you information — your tasks, calendar, priorities. But you had to connect the dots yourself. 

Now Dex actively thinks ahead and surfaces things you might have missed.

This is the biggest upgrade to Dex's intelligence since launch. Based on feedback from early users, I rebuilt the planning skills to be proactive rather than passive. Dex now does the mental work of connecting your calendar to your tasks, tracking your commitments, and warning you when things are slipping — so you can focus on actually doing the work.

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

**New skill: `/dex-add-mcp`** — When you want to connect a new tool, just run it. It handles the technical bits and makes sure your connection is protected. No settings files to edit.

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

**Before:** The `/prompt-improver` skill required extra setup. In some setups, it just didn't work.

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

**Requires:** Cursor (with Claude), plus Python 3.10 or newer and Node.js installed on your computer.
