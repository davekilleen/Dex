# Which of our gates cannot fail — audit, 11 August 2026

**In plain words.** A test that can never fail is worse than no test, because it
makes us confident. We just found one: the macOS release canary that exists to
protect the rescue bridge stayed green while two separate versions of the same
bug reached a real user. This document is the result of going looking for its
relatives across the rest of this repository's automated checks.

**The headline:** ten more places where a check is weaker than its name. Two of
them are serious — a performance budget that is structurally incapable of
failing, and a nightly test run that reports success when it runs no tests at
all. A third is a script in this repository that has never been run against the
repository it configures: run it today and it would first drop the test suite
from the checks required to merge, then block every pull request forever on a
status that nothing reports.

**Good news worth stating plainly:** merge protection on `main` is real and
stronger than this repository's own documents describe. An earlier draft of this
audit said otherwise; it was wrong, and F3 records the correction.

Three are fixed in the pull request that carries this document: F1, one line;
F3, the booby-trapped protection script; and F10, which that pull request's own
CI surfaced. Everything else is written down here deliberately: several are
policy calls, and turning them on could make an existing pipeline go red for
reasons unrelated to the change that shipped this audit.

The canary gap that prompted this audit was closed separately, in #458.

---

## Method and scope

Bounded to `dex-core`. Read: every job and every `run:` step in the four
workflows (`ci.yml`, `nightly-quality.yml`, `historic-fleet-darwin.yml`,
`release.yml`); every script those steps invoke, with particular attention to
`scripts/check-*`, `scripts/*-gate*`, `scripts/verify-*`, `scripts/detect-*`;
the `package.json` scripts CI calls; and the pytest/coverage configuration,
including shard splitting and junit merging.

Looking for one thing: a check whose failure cannot reach the exit code of the
job that runs it, or whose file selection does not cover what its name claims.

`dex-desktop`'s dead end-to-end suite is a known instance of the same pattern
and lives in another repository; it is out of scope here.

Confidence is stated per finding. **Confirmed** means reproduced or read
directly. One finding (F3) turns on live GitHub settings that the authoring
session could not read; it was checked afterwards with an admin-scoped token and
is marked accordingly.

---

## F1 — The 100k-file performance budget cannot fail *(confirmed; fixed here)*

`.github/workflows/nightly-quality.yml:83-86`

```yaml
      - name: 100k-file adoption performance budget
        run: |
          python scripts/benchmark_adoption_engine.py --files 100000 \
            | tee .logs/adoption-gates/benchmark-100k.json
```

`scripts/benchmark_adoption_engine.py` exits non-zero three ways, including
`"Performance budget exceeded"`. GitHub runs a step as `bash -e {0}` — `-e` but
**not** `pipefail` — so the step's exit code is `tee`'s, which is always `0`.
The budget can be blown by any margin and the step stays green.

Reproduced directly:

```
$ bash -e -c 'python3 scripts/benchmark_adoption_engine.py --files notanumber | tee /tmp/b.json'; echo $?
0
$ bash -e -c 'python3 scripts/benchmark_adoption_engine.py --files notanumber >/tmp/b.json'; echo $?
2
```

It also fails quietly: on the argument/crash path nothing reaches stdout, so
`tee` writes an **empty** evidence file, and the upload at
`nightly-quality.yml:90-94` uses `if-no-files-found: warn`, so the empty
artifact raises nothing either.

The sibling benchmark two steps earlier (`:47-48`) is unpiped and does gate
correctly, which is what makes this an accident rather than a decision.

**Fixed in this PR** by adding `set -o pipefail` to the step. Note for the
reviewer: if the 100k budget is currently being exceeded, the next nightly will
go red. That is the gate working for the first time, not a regression
introduced here.

---

## F2 — The nightly flaky-test detector passes when it runs no tests *(confirmed)*

`scripts/detect-flaky-tests.sh:14-19`, invoked at `nightly-quality.yml:41-42`

```bash
pytest core/tests core/mcp/tests core/migrations/tests -q -m "not fuzz" --maxfail=0 >"$RUN1_OUT" 2>&1 || true
grep -E '^FAILED ' "$RUN1_OUT" | awk '{print $2}' | sort -u >"$RUN1_FAIL" || true
```

Both pytest exit codes are discarded. The verdict is only
`diff -u "$RUN1_FAIL" "$RUN2_FAIL"`. If pytest cannot collect at all — an import
error, a missing dependency, a renamed test root — both runs produce zero
`FAILED` lines, the diff is empty, and the script prints *"No flaky test
signature detected across two runs."* and exits 0.

This is the same shape as `dex-desktop`'s five-week-dead e2e suite: a step that
would report success indefinitely while executing nothing. It matters more than
it looks, because this script is also the only place the nightly job runs the
Python suite at all.

*Discarding a **deterministic** failure is defensible for a flakiness detector.
The hole is the absence of a floor: nothing asserts that either run collected
anything.*

**Suggested fix (not applied):** assert a minimum collected-test count from each
run's pytest summary line before comparing, and fail closed if the summary is
missing. Left out of this PR because it can turn the nightly red on its first
run for reasons unrelated to the bridge canary.

---

## F3 — The branch-protection script had never been run against reality *(confirmed; fixed here)*

**The live setting is good — better than this repository claims.** Checked with
an admin-scoped token: `main` is protected, `strict` mode is on, and the
required contexts are **both `quality` and `test-results`**. Since
`test-results` carries the Python suite verdict (`ci.yml:198-200`) and both
coverage gates (`:218-230`), a pull request with a red test suite genuinely
cannot merge.

*An earlier draft of this document claimed the opposite. That was wrong. The
`404` from `gh api …/branches/main/protection` in the authoring session was a
missing administration scope, not missing protection — a reminder that "the API
says no" and "the setting says no" are different sentences.*

What remains is real, and it is the inverse of the original claim:

**The checked-in script is stale and would downgrade the live setting.**
`scripts/configure-branch-protection.sh:28-31`:

```json
  "required_status_checks": {
    "strict": true,
    "contexts": ["Dex CI / quality"]
  },
```

Two things are wrong with those four lines, and the second is worse.

**It shrinks.** The live configuration requires two contexts; this names one.
The call is a `PUT`, so running it replaces the live value — anyone who executes
the repository's own protection script **removes `test-results` from the
required checks**, and from that moment a red Python suite no longer blocks a
merge.

**It names checks that do not exist.** A required context is matched against the
name a check run *reports*, not the "Workflow / job" string the checks UI
displays. What this branch actually reports:

```
$ gh api repos/davekilleen/Dex/commits/main/check-runs --jq '.check_runs[].name'
build-release
build-release-beta
deploy-health
pr-report
quality
test-results
tests (1)
tests (2)
tests (3)
```

There is no `Dex CI / quality`. Requiring it would leave every pull request
waiting forever on *Expected — waiting for status*. So the script does not
merely weaken protection when run — **it bricks merging**, and the fact that
nobody has hit that is proof it has never been run against this repository. A
protection script that has never been executed is not a control; it is a
document that looks like one.

That second half was caught in review of this very pull request, after a first
fix that kept the prefixed names and would have shipped the brick. Recorded
here rather than quietly corrected, because it is the sharpest instance of this
audit's own thesis: the failure was not in the logic, it was in never having
checked the logic against the live system.

**Fixed here, three ways.**

1. The floor is now the names checks actually report — bare `quality` and
   `test-results` — with the reason and the verifying command in a comment
   beside them.
2. The script `GET`s the live contexts and submits the **union** with its floor,
   so a run can only ever add a required check. If the branch is unprotected, or
   the token cannot read protection, the floor is applied on its own; anything
   live but outside the floor is reported as preserved.
3. Before writing, it compares every name it is about to require against the
   check runs the branch has actually reported, and warns loudly about any that
   nothing produces — so the next person to add a context cannot repeat the
   mistake silently.

`core/tests/test_branch_protection_script.py` pins all of it: the floor is read
from the array itself and must equal the reported job names, no floor entry may
contain a `/`, the script must consult `check-runs`, and the merge must never
shrink, never duplicate, and still apply the floor when the live value is
unreadable.

One surprise is left in place deliberately: the script sets
`enforce_admins: true`, while live is `false`. That is a strengthening rather
than a weakening, so it is not silently changed here — but it would stop an
owner-run auto-merge from bypassing checks, so the script now says so on
stdout before it writes.

**Two residual gaps in the live configuration:**

- `allow_force_pushes: true` on `main`. History on the default branch can be
  rewritten. An attempt to disable it via the API was accepted but did not
  change the flag, which suggests a repository ruleset is governing it above the
  branch-protection object. Needs a look in **Settings → Branches** rather than
  another API call.
- `enforce_admins: false`. The owner token can bypass the required checks. This
  is plausibly deliberate — the agent auto-merge workflow runs as the owner — so
  it is recorded here as a **documented trade-off, not a defect**. It does mean
  "required checks" is a statement about everyone except the owner.

**Doc drift, still true:** `docs/merge-gates.md:4-6` names `quality` and
`pr-report` as the required checks; live is `quality` and `test-results`.
`pr-report` is not required and `test-results` is not documented.

**Follow-up, needing the same admin path:** add
`historic-fleet-darwin-pr-canary` to the required contexts. The real-process
bridge leg landed in #458 and reports its verdict, but it does not block a
merge — a weaker position than the gate deserves. The script's union behaviour
means adding it by hand is now safe: a later run will preserve it rather than
remove it.

### Two additions worth making to the merged bridge probe

Recorded here rather than bundled into this pull request, because #458's gate is
already merged and sound and this document should not become a second
implementation of it:

- **Assert the vault is untouched.** The probe halts at the first `APPLY` gate,
  so nothing should have been written. Hashing the user-owned fixture files
  before and after would turn "it stopped at the gate" into "it stopped at the
  gate *and wrote nothing*", which is the property a user actually cares about.
- **Report the leg in the job summary, defaulting to `not-run`.** The runner
  already fails closed if the designated start leaves `CANARY_STARTS`, which
  covers the likeliest way it stops running. A summary line would also make a
  reader of the run page able to tell, without downloading the evidence
  artifact, whether the leg executed at all.

---

## F4 — Four Node test suites in `core/tests/` are run by nothing *(confirmed)*

| file | `test(` calls |
|---|---|
| `core/tests/brain-vault-migrator-integration.test.cjs` | 28 |
| `core/tests/brain-vault-migrator-unit.test.cjs` | 24 |
| `core/tests/provision-working-week.test.cjs` | 4 |
| `core/tests/sync-folder-detector.test.cjs` | 3 |

`package.json`'s three `test:*` scripts glob `.claude/hooks/tests/`,
`.scripts/lib/tests/`, `.scripts/meeting-intel/__tests__/` and
`core/integrations/connection-manager/` — none of them `core/tests/`. pytest
does not collect `.cjs`. Roughly fifty-nine assertions covering the v1→v2
brain/vault split migrator, which is the code the rescue bridge's *first*
approval gate executes, have never run in CI.

They are correctly excluded from the release branch
(`verify-distribution.sh:355-358`), so the only missing piece is a runner.

**Suggested fix (not applied):** a `test:migrations` script globbing
`core/tests/*.test.cjs`, wired into the `quality` job. Left out because adding a
previously-unrun suite to a blocking job is a maintainer's call on both redness
and runtime.

---

## F5 — The fleet's path filter misses most of the update path it protects *(likely)*

`.github/workflows/historic-fleet-darwin.yml:15-27` lists eleven paths. These
are consumed by the exact build and journey the canary runs, and are absent:

| missing path | consumed by |
|---|---|
| `core/update/apply_update.py`, `core/update/journey_protocol.py` | the update itself; only the *generated* `journey-protocol-v1.json` is listed |
| `install.sh` | the fixture install inside every journey |
| `.distignore`, `scripts/resolve-distignore-files.sh` | `build-release.sh`, `build-vault-bundle.sh` |
| `scripts/generate-update-journey-protocol.py` | both build scripts |
| `scripts/generate-release-catalog.py`, `scripts/check-catalog-coverage.py` | both build scripts |
| `core/utils/manifest.py` | `build-release.sh` |
| `scripts/check-tau-removal.py` | both build scripts |

A pull request that changes only `core/update/apply_update.py` — the code that
applies the update — triggers neither the canary nor the fleet.

Marked *likely* rather than confirmed because this may be a deliberate trade
against a 150-minute macOS job. Nothing in the workflow or in
`core/tests/test_historic_fleet_darwin_workflow.py` says so, which is the actual
problem: an intentional cost decision and an oversight look identical here.

**Suggested fix (not applied):** either add the paths, or record the exclusion
and its reason in the workflow so the next reader can tell which it is.

---

## F6 — The "Security gate" never runs a dependency audit *(confirmed)*

`scripts/security-gate.sh:20` reads `SECURITY_STRICT_AUDIT`, defaulting to `0`.
`ci.yml:96-97` sets nothing. `nightly-quality.yml:16` sets it explicitly to
`"0"` — the one place strict mode would be expected. `SECURITY_STRICT_AUDIT=1`
appears nowhere in the repository, so the `pip-audit` and `npm audit` branch
(`security-gate.sh:30-45`) is unreachable in CI.

What the gate does run — the tracked-file secret scan and the tau-removal check
— is sound and fails closed (`security-scan.py:147-151`), and the allowlist at
`scripts/security-allowlist.txt` is comments-only, so nothing is exempted.
`docs/testing-governance.md:23` describes it honestly as "secret leakage
detection". `docs/merge-gates.md:18`'s bare "security gate" reads considerably
broader than what runs.

---

## F7 — Two "Required Merge Gates" always exit 0, and their documented exception process does not exist *(confirmed)*

`scripts/check-test-delta.sh:41-45` and `scripts/check-doc-drift.sh:41-45` are
the same shape, and both say so:

```bash
# Advisory only: warn, never block. Quality relies on reviewer judgment.
```

Advisory by design is not a finding. The finding is the framing around it:

- `docs/testing-governance.md:14-20` lists both under **"Required Merge
  Gates"**, as *"passes **or approved exception label exists**"*.
- `docs/testing-governance.md:160-164` documents `test-exception-approved` and
  `docs-exception-approved` labels, requiring *"rationale in PR body and
  reviewer approval"*.
- Those two label strings appear nowhere else in the repository. No workflow,
  action or script reads a pull-request label.

There is a documented exception process for a gate that cannot fail — so there
is nothing to except, and a reader of the governance doc believes in a control
that is not there. Either the doc should describe them as advisory, or the
scripts should block.

---

## F8 — Six per-PR gates do not run in the merge queue *(likely)*

`ci.yml:11` enables `merge_group`. Six checks are conditioned on
`github.event_name == 'pull_request'` and therefore skip in the queue: the
diff-aware test gate (`:59`), the **PII gate** (`:62`), the **path-contract
usage gate** (`:65`), the doc-drift gate (`:68`), the **touched-file coverage
gate** (`:229`), and the whole `pr-report` job (`:257`).

`docs/testing-governance.md:14-19` calls PII and path-contract "Required Merge
Gates". The batch that actually lands on `main` is never PII-scanned. Modest in
practice, since each pull request was scanned individually against its own merge
base, but a semantic conflict introduced by a queue rebase is uncovered.

---

## F9 — Coverage thresholds documented at 15%, configured at 25% *(confirmed; cosmetic)*

`docs/testing-governance.md:44-46` says total ≥ 15%. `ci.yml:195-196` sets
`COVERAGE_MIN_TOTAL: "25"` and `COVERAGE_MIN_TOUCHED: "10"`. Both are genuinely
enforced. The doc has drifted in the safe direction; noted only because it is
the number a reader would trust.

---

## F10 — Six executor tests could fail for reasons unrelated to the executor *(confirmed; fixed here)*

Found by this pull request's own CI, which is the only reason it is in the list:
`test_non_network_bridge_failure_is_never_retried` failed on shard 3 while
passing locally and on `main`.

`core/tests/test_release_fleet_executor.py` had six tests that replaced
**`time.sleep` for the whole process** and then asserted on what got called:

```python
monkeypatch.setattr(
    executor.time, "sleep",
    lambda _delay: pytest.fail("a non-network bridge failure must not back off"),
)
```

`executor.time` *is* the `time` module, so this is a global substitution. Every
one of those tests then runs `execute_journey`, which shells out to Git through
`subprocess.run(..., timeout=90)` — and `subprocess.run` with a timeout ends in
`Popen.wait(timeout=...)`, a busy-wait loop that calls `time.sleep` whenever the
child's pipes reach EOF before the child is reapable. That window is pure
scheduling luck, so on a loaded runner an unrelated Git call trips an assertion
about the executor's backoff.

Measured directly, with a child that closes its pipes and then lingers:

```
OLD pattern — stray sleeps seen by the tripwire: 80264 -> FAILS
NEW pattern — backoffs seen by the tripwire:         0 -> ok
```

Two of the six also *recorded* sleeps and asserted
`slept == [10.0, 30.0]`, so a stray entry corrupted the expected value rather
than merely adding noise.

This is the mirror image of the rest of this document. Everything else here is a
check that cannot fail; this is a check that can fail without its subject having
done anything wrong. Both teach the same lesson — assert on the thing you name.

**Fixed here.** Two helpers replace the six global patches.
`_forbid_backoff` substitutes `executor._transient_delivery_backoff` itself, so
only a real backoff can trip it. `_recorded_backoff` wraps the *real* backoff
function and narrows the `time.sleep` substitution to the moment it executes —
which keeps the original coverage of the actual delay table (`10.0`, `30.0`)
rather than reimplementing it in the test.

Nothing about the executor changed; only what the tests watch.

---

## Follow-ups opened after this audit

Recorded here so the next gate-health pass starts from the current state rather
than from 11 August.

- **F11 — the revived release smoke journeys are flaky under the CI sandbox.**
  [#477](https://github.com/davekilleen/Dex/issues/477). This audit's family had
  one more member, found on 12 August during an open-PR triage: the release
  smoke comparison built its expected-file list from `git ls-tree` while the
  trusted snapshot came from `git archive`, which honours `export-ignore`.
  Fifteen `core` paths were therefore expected and permanently missing, so
  *every* vault-mutating journey skipped with "Dex-owned core differs" no matter
  which ref was used — the F1/F2/F4 mechanism exactly: the check ran, produced
  output, and reported without exercising the thing it names. Fixed in
  [#367](https://github.com/davekilleen/Dex/pull/367) (`c260582`), whose new
  test derives its expectation from git itself (`ls-tree` vs `archive`) so the
  exclusion list cannot silently drift.

  **What is still open:** now that the journeys actually execute, one fails
  roughly one run in three with a bare `EPERM` from inside the harness
  (`mcp_startup` → verdict `UNKNOWN`, `harness_failed`, exit 2). That is the
  harness failing to run under the runner's sandbox, not the product breaking —
  and it lands on this document's own closing lesson: noise is how a suite earns
  the reputation that makes people re-run it instead of reading it. A gate people
  re-run until green is worth no more than the dead gate it replaced. #477 has
  the three run links showing identical code green, red, then green, and argues
  against the tempting non-fix (loosening the `exit_code == 0` assertion), which
  would recreate the unfailable gate #367 just removed.

---

## Smaller gaps, no action proposed

- `scripts/check-path-consistency.sh:21` globs `*.py *.ts *.cjs *.sh` and so
  never checks `.js` or `.mjs` — for example `scripts/*.mjs`. Same omission at
  `verify-distribution.sh:237`.
- `scripts/verify-distribution.sh:406-408` exits 0 with warnings. Four checks
  are warning-only: tracked user-data folders (`:57`), personal email addresses
  (`:70`), `install.sh` not executable (`:98`), and `package.json` version
  disagreeing with the changelog (`:256`). Stated in its summary, so
  intentional — but "Distribution safety check" reads stronger than it is on
  those four.
- `scripts/build-health-json.py:103-122` marks all ten `MAIN_PUSH_GATES` as
  passed from the single `--quality-conclusion` argument, and `ci.yml:493`
  passes the literal `success`. Safe today because `deploy-health` is guarded by
  `needs.quality.result == 'success'`, but it is a hardcoded literal one
  condition-edit away from publishing a claim it did not check — and the page
  attributes the Python suite to the `quality` job, which does not run it.

---

## Checked and sound

Recording these so the next reader does not repeat the work.

**Failure propagation that looks wrong but is not.** `ci.yml:222`
(`coverage combine | tee`) is the same missing-`pipefail` shape as F1 but is
neutralised by the explicit `COMBINED == 3` assertion immediately after.
`ci.yml:240`'s `grep -c` pipeline is backstopped by the shard-count comparison
at `:243`. `ci.yml:191`'s `if: ${{ !cancelled() }}` plus the explicit
`needs.tests.result == 'success'` check correctly handles the trap where GitHub
treats a *skipped* required check as satisfied. Every `if: always()` in the four
workflows is on an artifact upload, never on a verdict. `ci.yml:498`'s
`continue-on-error` is scoped to a Pages configuration step.

**`scripts/run-historic-fleet-darwin.sh` is sound.** It sets
`set -euo pipefail`, so its `| tee` pipelines do propagate; every `|| true` in
it is on cleanup, `tail`, or `kill`, never on a verdict; and `finish()`
preserves the exit status through the `EXIT` trap.

**The strongest gate in the repository** is `ci.yml:237-243`: a fresh
`--collect-only` count compared against the merged junit count, which retires
the whole silent-test-drop class for the Python suite.

**No deselection holes in the Python configuration.** `pyproject.toml:25-30`
has no `addopts`, no `-k`, no `--exitfirst`, no `norecursedirs`, no deselects.
Both `@pytest.mark.fuzz` tests live in the one file the nightly runs with
`-m fuzz`, so `-m "not fuzz"` excludes nothing that goes unrun. Shard splitting
only rebalances. `scripts/merge-junit.py:28,33` fails on a missing input and on
a report with no testsuite. The coverage denominator is honest.

**Gates that genuinely fail closed:** `security-scan.py`,
`check-founder-content.py`, `check-portable-contract.py`, `pii_gate.py`,
`check-instructed-tools.py`, `check-tracked-ignored.py`,
`generate-health-promises.py --check`, `check-architecture-inventory.sh`,
`check-connections-contract.mjs`, `check-catalog-coverage.py`,
`check-release-tag-uniqueness.sh`, `check-release-tag-reachability.sh`, and the
`build-release-beta` prerelease guards.

---

## The pattern worth naming

Four of these (F1, F2, F4, and the canary this audit came from) share one
mechanism: **the check runs, produces output, and reports success without ever
having exercised the thing it names.** Nobody sees a skip. The job is green, the
evidence artifact exists, the summary line is printed.

The cheapest defence is the one #458 applied to the bridge canary: make every
gate state, in its own evidence, what it actually did — a count, a transcript,
a retained stdout — and assert a floor on that rather than on the absence of
failures. A gate that cannot say what it ran cannot be trusted to have run.

F3's fix is the same instinct pointed at configuration rather than evidence: the
protection script now reads the live state, can only add to it, and checks the
names it is about to require against the names the branch actually reports. The
failure mode is gone by construction rather than by remembering to keep a list
correct.

F3 also earned the audit's bluntest lesson, and earned it twice — the second
time from this document's own first fix, which corrected the missing check and
kept the unreportable names. **Configuration that has never been executed
against the live system is not a control.** It reads like one in review, which
is exactly what makes it dangerous.

F10 is the same lesson from the other side. There the check *could* fail, but
for something it never meant to watch: it substituted `time.sleep` for the whole
process when what it cared about was one function in one module. A check that
watches more than it names is not stricter, it is noisier — and noise is how a
suite earns the reputation that makes people re-run it instead of reading it.

Both halves reduce to one rule: **name the thing, then watch exactly that thing
— no less, and no more.**
