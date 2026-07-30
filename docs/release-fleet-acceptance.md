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
  --foundation-tag dist/release/v1.80.0-EXACTFOUNDATION \
  --follow-up-tag dist/release/v1.80.5-EXACTFOLLOWUP
```

The repository has the canonical protocol source at
`core/update/journey-protocol-v1.json`, with a strict parser in
`core/update/journey_protocol.py`. It is a closed operation vocabulary, not a
shell-command format. Version 1 permits only:

- the reviewed pinned-foundation bridge, with its exact source SHA-256 and up
  to two conditional `APPLY` approvals (topology and delivery previews are
  requested only when the actual fixture state requires them);
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

The protocol and executor are currently LOCAL. Public v1.80.5 contains neither,
so its surface remains `machine_executable: false`. Publishing both is one
prerequisite, not fleet acceptance: the real follow-up release must exist and
every historic case must still run on every declared platform.

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
