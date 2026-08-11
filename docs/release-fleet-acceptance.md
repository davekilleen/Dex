# Release-fleet acceptance for Dex updates

This is the release gate for the promise that no existing Dex installation is
left behind. It is deliberately stricter than the normal unit tests: a green
test of the updater source does not prove that a person running an old,
published Dex can reach it.

## What must pass

Every distinct tree behind a published release tag is a starting case. This
means the `dist/release/v*` packages, historic `dist/archive/v*` distribution
tags, and the older public `v*` release tags that predate that format. Archive
tags preserve an immutable historic starting tree after its canonical
distribution ref is retired; their version-and-commit suffix must still match
the tagged commit. If two tags point at different trees—even when they share
the same version number—they are separate cases. Byte-identical trees are one
case. A canonical and archive tag that claim the same version-and-commit
identity but resolve to different commits are rejected as ambiguous.

Each case must complete two real update hops:

1. **Historic release to the foundation release.** The foundation is the first
   public release containing the self-delivering updater. Use the old vault's
   own `/dex-update` instructions. If that old route safely refuses, follow
   only its documented one-time rescue route. Record the user-visible wording,
   approval prompts, final release identity, and `/dex-doctor` verdict.
2. **Foundation release to a follow-up release.** From the same fixture, run
   `/dex-update` again. This hop must use the foundation release's delivery
   path: fetch the exact verified release, show the exact preview, collect a
   fresh approval, and commit the receipt-backed update. Record the same
   evidence.

For both hops, the fixture's user-owned hashes must be identical before and
after. A changed hash, an unknown result, a missing transcript, a missing
receipt, or an unhealthy Doctor result is a failure—not something to explain
away.

## Discover and build the historic fixtures

Discover the whole historic set first. This creates no copies, so it is safe to
run as part of ordinary release preparation.

```bash
python3 scripts/release_fleet.py manifest --repo . > historic-release-manifest.json
```

The manifest records the generated count and every immutable starting tag,
commit, and tree. It is the source for the required fleet case count—never a
hand-maintained number. The starting source must be a public release tag; never
use `main`, a working tree, or an untagged release candidate as a historical
starting point.

## Non-acceptance discovery sweep

Before an executable update protocol exists, survey the real historic set with
disposable fixtures. This runs each shipped installer and a Doctor preflight,
hashes the shipped `/dex-update` and rescue material, then deletes the fixture.
It never runs an update, a rescue command, a manual Git substitute, or an
acceptance check.

The fixture process has an isolated home, Git configuration, and minimal PATH.
Its only Node and Python capabilities are pre-approved local runtimes (currently
the exact `/opt/homebrew/bin/node` and `/opt/homebrew/bin/python3` installations);
the discovery map records their resolved paths, versions, and hashes. The survey
fails closed if either runtime is absent or unsupported—it never falls back to
the caller's PATH.

```bash
survey_root=$(mktemp -d /private/tmp/dex-historic-survey.XXXXXX)
python3 scripts/release_fleet.py survey --repo . \
  --starting-manifest historic-release-manifest.json \
  --output "$survey_root" --jobs 2
```

`$survey_root/historic-discovery-map.json` is explicitly labeled
`NON_ACCEPTANCE_DISCOVERY`. It groups fixture-install and Doctor preflight
failures by root cause and retains no cloned fixture after each case.

Build and exercise one fixture at a time, retaining only its small report and
transcript after it passes. The builder never copies a founder's vault and
refuses to overwrite an existing case.

```bash
fleet_root=$(mktemp -d /private/tmp/dex-release-fleet.XXXXXX)
python3 scripts/release_fleet.py build --repo . --output "$fleet_root" \
  --starting-tag dist/release/v1.61.0-EXACTTAG
```

Its output records the fixture path and the exact hashes of the synthetic user
content that must survive. Processing one case at a time keeps the release
gate bounded rather than storing 120 full repositories on disk.

## Establish the executable-journey prerequisite

The `journey` command executes one case only when the follow-up distribution
publishes the closed protocol and its catalog points to exact source bytes for
the runner, executor, and pinned bridge. A release missing any of those pieces
fails before a fixture is built. The command never promotes the historic
Markdown `/dex-update` instructions into an API.

```bash
python3 scripts/release_fleet.py journey --repo . --output "$fleet_root" \
  --starting-tag dist/release/v1.74.0-EXACTSTART \
  --foundation-tag dist/release/v1.81.16-281202d \
  --follow-up-tag dist/release/v1.81.17-EXACTFOLLOWUP \
  --bridge-asset /path/to/dex-update-bridge-v1.81.17.py \
  --bridge-checksum /path/to/dex-update-bridge-v1.81.17.py.sha256
```

Historic semantic `v*` starting tags have a narrower evidence-only rule. Their
tag object, commit, tree, version, and channel identity remain exact. When Git
positively confirms that `System/.release-catalog.json` is absent, the runner
may record a valid journey protocol only after its runner, executor, and bridge
hashes match the exact semantic source commit. That surface is labelled
`present-unbound` and `machine_executable: false`; it cannot grant execution
authority or substitute a similarly versioned distribution package. A catalog
that exists but is malformed or unreadable fails closed, as does any source
hash mismatch. Immutable journey targets, including the foundation and
follow-up, never receive this evidence exception: their release catalogs and
publisher-source bindings remain mandatory.

The bridge paths must be the separately downloaded GitHub Release asset and
its checksum. The runner verifies their exact names, checksum, protocol digest,
and released source bytes before it creates the fixture. A bridge available
only in the controller checkout cannot satisfy this gate.

The formal macOS fleet controller takes that same asset pair explicitly and
re-proves it against the immutable follow-up protocol before it creates its
private run directory or starts a journey. The follow-up tag must be the exact
public stable `dist/release/v*` tag that the foundation updater will deliver.
The controller first proves that the canonical public remote advertises that
exact annotated tag object. It then makes an anonymous GET to GitHub's canonical
`/davekilleen/Dex/releases/latest` route and accepts exactly one HTTPS redirect
to the exact canonical `/davekilleen/Dex/releases/tag/v<version>` URL followed
by HTTP 200. A missing or additional redirect, an off-host or non-HTTPS hop, any
variation in host, repository, path, case, port, user information, query,
fragment, encoding, prefix, suffix, or trailing slash, or an unavailable route
fails closed. This proof uses no API token, local cache, retry-based acceptance,
or HTML parsing. The controller then downloads the published bridge and
checksum from that release and compares both byte-for-byte to the submitted
pair. Neither a local tag nor a controller copy of the bridge can stand in for
it.

The first-party `historic-fleet-darwin` GitHub Actions workflow is the release
operator for this gate. Its formal job is manual: after the updater change is
merged and the follow-up GitHub Release is public, provide the exact immutable
foundation and follow-up tags. The job refreshes the public tags, freezes the
cohort, downloads and verifies the public bridge pair, and runs all starts
sequentially on macOS. It retains the evidence and exact
discovered/started/completed/passed/failed counts on both success and failure.
The job is time-bounded to six hours and monitors a 50 GiB working-set limit.

The formal controller continues after an isolated case has crossed the journey
execution boundary and then fails. It retains every such failure in
`platform-failures.json`, groups matching diagnostics by a stable signature, and
finishes the frozen cohort before returning a non-zero result. This lets one
exhaustive run expose all version-specific failure families instead of stopping
at the first one. A shared protocol, released-identity, public-route, evidence,
runtime, filesystem, disk-budget, or other infrastructure/integrity failure
still stops the job immediately. A collected failure report is diagnostic
evidence only: it cannot mint a platform receipt or acceptance result. If the
exhaustive run has no failures, its ordinary receipt remains valid acceptance
evidence; otherwise all grouped fixes need targeted proof before one final full
acceptance run.

Pull requests that touch the updater route get a separate non-publishing
macOS canary. It builds a local release-shaped candidate and runs real journeys
from these exact twelve starts:

- semantic `v1.51.0`;
- `dist/release/v1.61.0-dc7d332`;
- `dist/archive/v1.61.0-1ec1387`;
- semantic `v1.62.0`;
- `dist/archive/v1.63.0-08ce719`;
- `dist/archive/v1.65.0-c5ec161`;
- `dist/archive/v1.72.0-7d75da9`;
- `dist/archive/v1.76.0-d0bb932`;
- semantic `v1.81.1`;
- `dist/archive/v1.81.1-b17ef02`;
- semantic `v1.81.7`; and
- semantic `v1.81.11`.

These journeys cover the old dependency fixture, split-topology and retired
manifest variants, archived releases, and the recent Mac final-fetch path
before merge. They remain explicitly non-acceptance evidence and cannot replace
the freshly generated public fleet.

### One start also starts the bridge as a process

A journey drives the bridge's lifecycle *functions* in-process, so `main` — the
environment scrub, the `os.execve` into the vault virtualenv, and the
clean-runtime equality check — was for a long time executed by no gate at all.
Two consecutive user-blocking defects lived in that entry path and shipped
through a green canary.

The oldest start (`v1.51.0`, set by `BRIDGE_PROCESS_ENTRY_START` in the runner
and passed to `release_fleet.py journey` as `--bridge-process-entry`) therefore
also runs `probe_bridge_process_entry` against its freshly installed fixture,
before its journey. That launches the published asset the way a stuck user
does — the trusted system Python, the asset path, `--vault`, from the vault
root, stdin closed — and `assert_bridge_process_entry` requires that it
finished inside its bound, relaunched exactly once, never stopped on a
runtime-entry refusal, printed something at all, and reached the first `APPLY`
gate. stdout, stderr and a JSON record are retained beside the fixture in
`<case>.bridge-process-entry/` whether it passes or fails, because silence was
the original symptom. The runner fails closed if the designated start ever
leaves `CANARY_STARTS`.

`core/tests/test_dex_update_bridge.py` carries the cheap counterpart:
`test_the_bridge_can_be_started_as_a_process_by_a_stuck_user` builds a minimal
vault with a real virtualenv and launches the real bridge in about three
seconds, so the entry path is covered on Linux and on every pull request rather
than only by the macOS job.

Within a journey, the foundation updater proves the exact follow-up identity
before its final fetch into the private brain store. If and only if that final
fetch raises `OfflineError`, the updater waits for the fixed 100 ms backoff and
retries once. The sole retry receives a fresh bounded five-second attempt and
uses the same proved tag and channel refspecs and the same remote URL. After a
successful fetch, the updater rechecks the fetched tag object, commit, tree,
channel target, manifest, and package metadata against the proved identity
before it can return a preview.

Evidence, topology, origin, identity, cancellation, filesystem, and all other
non-offline failures are not retried. A second `OfflineError` fails closed.
This is not a retry of the controller's public-route proof above, and this
bounded transport retry does not make the PR canary acceptance evidence.

```bash
python3 scripts/release_fleet_acceptance.py platform --repo . \
  --cohort historic-cohort.json \
  --foundation-tag dist/release/v1.81.16-281202d \
  --follow-up-tag dist/release/v1.81.17-EXACTFOLLOWUP \
  --session acceptance-session.json --key acceptance.key \
  --bridge-asset /path/to/dex-update-bridge-v1.81.17.py \
  --bridge-checksum /path/to/dex-update-bridge-v1.81.17.py.sha256 \
  --output "$fleet_root/darwin"
```

The repository has the canonical protocol source at
`core/update/journey-protocol-v1.json`, with a strict parser in
`core/update/journey_protocol.py`. It is a closed operation vocabulary, not a
shell-command format. Version 1 permits only:

- the reviewed pinned-foundation bridge, with its exact source SHA-256 and up
  to three conditional `APPLY` approvals (topology, delivery, and a missing
  current MCP registration are requested only when the fixture state requires
  them);
- `deliver_latest_release`, `build_and_preview_delivered_release`, then
  `execute_approved_delivered_release`, with one fresh `APPLY` approval; and
- the fixed evidence order needed for refusal, bridge provenance, preview,
  receipt, installed identity, Doctor, and released-platform smoke proof.

The root binds the fleet runner, executor, and bridge bytes in the immutable
release catalog's publisher `source_commit`. A release that merely carries a
plausible JSON file, points at unavailable source, changes an adapter or
operation, or has a mismatched hash is invalid.

The executor at `scripts/release_fleet_executor.py` verifies those released
bytes before calling the pinned bridge. It then invokes only the three declared
lifecycle operations, captures their real previews and receipts, verifies the
installed release markers after each hop, runs the installed Doctor and smoke
suite, and hashes user-owned content before and after. It writes the evidence
files and transcript itself. The bridge approval count in the transcript is the
number of prompts that actually occurred, never a fixed or inferred claim.

The executor returns a process-local authority object. Its JSON artifacts are
review material, not authority: reserializing, editing, or independently
constructing the same documents cannot unlock acceptance. The resulting
`<case>.evidence/` directory is beside—not inside—the disposable fixture. Its
content-addressed manifest records the exact executor identity, release
identities, ordered operations, and artifact hashes.

The v1.81.17 protocol and executor pin the exact public v1.81.16 foundation.
That publication is one prerequisite, not fleet acceptance: the distinct
follow-up release must exist and every historic case must still complete the
two-hop journey on macOS.

## Validate the finished evidence

After both release tags are public and every case has its journey transcript
and report entry, validate the report against the full tag set:

```bash
python3 scripts/release_fleet.py check-report --repo . \
  --starting-manifest historic-release-manifest.json REPORT.json
```

The command first verifies the generated starting manifest against the current
immutable release trees, then requires that many cases on every declared
platform. It remains fail-closed for a report read from disk: no internally
consistent report, manifest, transcript, receipt, or artifact set can recreate
the executor's live process authority. Fleet orchestration must keep each
`ExecutorRun` in the process that performs the corresponding journey and pass
those live results into the validator. Finished evidence still requires ordered
operations and SHA-256-bound artifacts: the transcript, release-surface
snapshots, receipts, Doctor reports, and smoke/platform evidence. Paths,
symlinks, malformed JSON, mismatched identities, incomplete platform coverage,
and unknown/broken Doctor results all fail the report.

## Claim language

Before this check passes, say only that the updater is implemented and locally
tested. After it passes against the two actual public tags on every supported
platform, it is accurate to say that historical Dex installations have a
proven path to the normal `/dex-update` experience.
