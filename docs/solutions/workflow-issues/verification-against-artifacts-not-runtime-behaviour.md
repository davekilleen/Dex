---
title: "Green tests are not evidence — verify the first run a real user makes"
date: 2026-07-27
problem_type: workflow_issue
track: knowledge
category: workflow-issues
component: development_workflow
module: core
severity: critical
root_cause: missing_workflow_step
resolution_type: workflow_improvement
related_components:
  - testing_framework
  - documentation
applies_when:
  - "shipping any user-facing command, skill, or first-run path"
  - "a review has read every diff line but no one has run the product"
  - "quoting a number or claim from a PR description into user-facing docs"
  - "measuring an exit code from a piped shell command"
symptoms:
  - "216/216 tests green while the first command a real user types fails immediately"
  - "\"Error: User presence is required for this credential operation.\" on a clean vault first run"
  - "a dramatic figure taken from a PR description that never occurred for any user"
  - "a false defect reported because $? read the exit status of head, not the program"
tags:
  - verification
  - definition-of-done
  - first-run
  - end-to-end
  - provenance
  - release-gate
---

# Green tests are not evidence — verify the first run a real user makes

## Context

On 2026-07-27, Dex Core shipped v1.77.0 with `/connect`, the feature that lets a user
connect roughly 775 third-party tools. Before release it passed everything a careful team
knows to do: a line-by-line review of the diff, an explicit check that no security-engine
file had been touched, an independent security gate that swept five distinct attack
vectors, and a test suite reporting 216 of 216 passing.

It would still have shipped completely non-functional for every command-line user. The
first command a person types on a clean vault:

```
$ node core/integrations/connection-manager/connect.cjs set-key linear
Error: User presence is required for this credential operation.
```

Every user, every app, first attempt. The cause was not a bug in the diff. The feature had
been designed to run only inside a signed desktop app that supplies a fingerprint check.
When the decision was made *that same morning* to also ship it to command-line users,
everyone assumed a command-line presence path existed. It did not — nobody had built one,
because until that morning nobody had needed one.

The common thread across every check that passed: all of them verified **code artifacts** —
diffs, test output, PR descriptions, security reasoning — and none verified **observed
runtime behaviour**. "216/216 green" was simultaneously true and irrelevant, because no test
exercised the first-run path a human takes. The break was caught by an unrelated session
writing the public help page, for the specific reason that writing user instructions forces
you to simulate a user following them.

Two more instances of the same failure mode surfaced the same day, which is what turned a
single near-miss into a documented practice:

1. A striking statistic — "1,008 meeting hours where the real figure was 120" — was lifted
   from a PR description and nearly published verbatim in the public changelog. It had never
   affected a single user: the function producing it was defined at line 400 and called from
   nowhere, and the code it depended on called a function that does not exist. It was caught
   only because the PR's own author went back and re-checked their own headline claim.
2. The orchestrator reported a defect that did not exist — "a refusal exits 0" — because it
   read `$?` immediately after piping output into `head`, and so measured `head`'s exit
   status. A builder spent real time hunting a bug that was never there.

## Guidance

Treat a claim as unverified until someone has *observed the behaviour it describes*. Reading
the code that would produce the behaviour, reading a green test summary, and reading someone
else's report of the behaviour are three different and weaker things.

**A. An end-to-end run as a real user is part of "done" for user-facing work.** Not a test
suite — the literal command a human types, on clean state, with output captured verbatim. A
test suite proves the paths someone thought to write; a first-run transcript proves the path
everyone assumed existed.

**B. Bucket documentation claims by provenance, not by topic.** Before publishing anything
user-facing, sort every factual claim by *how it was established*:

- *Confirmed by a real run* — a command was executed and this output observed.
- *Read from source but never observed* — the code says so; nobody watched it happen.
- *Untested* — asserted from a PR description, a plan, or memory.
- *Failure paths* — what the user sees when things go wrong, confirmed by breaking it.

Topic grouping hides weak claims among strong ones. Provenance grouping makes the second and
third buckets impossible to miss, and that is where the wrong claims live. On this project
the split caught three wrong claims immediately. The fourth bucket was added after testing
error paths, which revealed a bad key produced the entire user-facing output
`linear: needs_reauth` — two words, one of them jargon.

**C. Pass raw terminal output between collaborators, not summaries.** Summaries were the
exact vector by which every wrong claim propagated: the 1,008-hour figure travelled from a
PR description into a draft changelog without anyone re-running what produced it.

**D. When reporting a defect, state how you measured it.** "Here is the command I ran, here
is what I observed, here is the conclusion I drew" — never just the conclusion. Had the
exit-code report included its pipeline, the recipient would have spotted the `head` problem
in seconds instead of hunting a phantom.

## Why This Matters

The cost is not "some bugs slip through." It is that **the strongest-looking evidence is the
evidence most likely to be wrong in this particular way.**

- **Total feature failure passing every gate.** Every signal was honest. None could see that
  the first command any command-line user types returns an error. Confidence was at maximum
  exactly where coverage was zero.
- **Wrong facts published under the project's name.** The 1,008-hour figure was vivid,
  quantified, and sourced from a PR — all the surface markers of a solid claim — and
  described damage to zero users. A number that specific in a public document is a
  credibility loss no later correction fully recovers.
- **Engineering time spent on defects that do not exist.** A sincere report, wrong by one
  shell construct, sent a builder hunting nothing.
- **The catch was luck, not process.** `/connect` was saved by a session writing a help page;
  the false statistic by an author voluntarily re-checking themselves. Neither is a gate.

## When to Apply

Apply the full set when:

- The deliverable is something a human invokes directly — a command, setup flow, onboarding
  step, first-run experience.
- **The change crosses an environment boundary that was not in the original design** —
  desktop-only shipped to CLI, server-only to local, authenticated to anonymous. This is
  precisely where "someone must have built that" assumptions live, and exactly what broke
  `/connect`.
- You are writing anything public — changelog, help page, release notes, README.
- You are relaying a defect, statistic, or behavioural claim to someone who will act on it.
- **The decision to ship down a new path was made recently.** Recency is the risk signal: the
  assumption has had no time to be tested by anyone.

Apply the reporting discipline (C and D) always — nearly free, highest ratio of cost avoided
to effort spent.

Overkill when the change is internal with no user-invoked entry point, when the claim is
trivially self-verifying by the recipient, or when a first-run transcript already exists for
this exact path and state and nothing between the user and the behaviour has changed.

**Not an exemption: extensive test coverage.** `/connect` had it. Coverage and a first-run
transcript answer different questions; neither substitutes for the other.

## Examples

### 1. Definition of done — before and after

**Before** — diff reviewed line by line, no security-engine file touched, independent security
gate across five attack vectors, 216/216 passing. Every item true. Feature non-functional for
every command-line user.

**After** — the above, **plus** a captured transcript of the first command a real user types,
on clean state, verbatim. That transcript is the artifact that fails the gate. No amount of
green test output produces it.

### 2. The exit-code measurement trap

**Wrong** — `$?` in a pipeline holds the status of the *last* command, and `head` exits 0
essentially always:

```bash
node get-token.cjs linear --full 2>&1 | head -2; echo "exit=$?"   # always exit=0
```

**Correct:**

```bash
node get-token.cjs linear --full >/dev/null 2>&1; echo "exit=$?"
```

**And the reporting rule (D) that catches it anyway.** Instead of "Defect: a refusal exits 0",
write: "Defect: a refusal *appears* to exit 0. Measured with: `<pipeline>`. Observed:
`exit=0`." The second form is falsifiable on sight and the bug hunt never starts.

### 3. Provenance buckets — worked example

**Before (grouped by topic):** every claim reads with equal authority. Two were never
observed; one was false at the time of writing.

**After (grouped by provenance):**

```markdown
### Confirmed by a real run
- `connect.cjs set-key linear` on a clean vault returns, verbatim:
      Error: User presence is required for this credential operation.
  (Not the documented behaviour. Blocks release.)

### Read from source but never observed
- `get-token.cjs linear` is documented to refresh an expired token.
  Source path exists; no run observed. Do not publish as fact.

### Untested — sourced from a PR description
- "1,008 meeting hours affected." Traced to a function called from nowhere.
  Real figure 120. Zero users affected. Do not publish.

### Failure paths (what the user actually sees)
- Bad key. Entire output observed:
      linear: needs_reauth
  Two words, one jargon. Not shippable as a user-facing error.
```

Identical information content. The second form makes weak claims structurally impossible to
overlook.

## Related

- [The Trust Engine and its verification methodology](../architecture-patterns/trust-engine-and-verification-methodology.md)
  — the prior art this **amends**. Its rule "run two independent adversarial reviews and
  converge both to clean" is necessary but not sufficient: on `/connect`, a line-by-line
  review *and* a five-vector independent security review both converged clean while the
  product was broken for every user. Independent reviews are still artifact-level evidence.
- [Connection manager: live account gate](../connection-manager-live-account-gate.md) — prior
  art in the same subsystem, already asserting "no automated fixture substitutes for that
  result." This learning is the case that proves it.
- `docs/Dex_System/Distribution_Checklist.md` — states "what used to be manual verification is
  now automated gates on every push." True **for artifact properties** (secrets, PII, path
  classification); it never covered observed runtime behaviour. Needs that qualifier.
