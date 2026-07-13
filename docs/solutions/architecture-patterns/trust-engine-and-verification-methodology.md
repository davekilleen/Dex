---
title: "The Trust Engine and its verification methodology"
date: 2026-07-13
problem_type: architecture_pattern
track: knowledge
category: architecture-patterns
component: testing
module: core
tags:
  - testing
  - verification
  - trust
  - self-diagnostics
  - security-review
  - coverage
---

# The Trust Engine and its verification methodology

## Context

Dex's entire premise is "let an AI run the admin of your professional life." A product
with that pitch lives or dies on trust, and trust cannot be *claimed* — it has to be
*demonstrated*, repeatedly and honestly. Between v1.28 and v1.58 (July 2026) we built the
machinery that lets Dex prove it works rather than hope it does, and — importantly — the
methodology that machinery is verified with. This doc captures the reusable pattern and the
two testing practices that earned their place, so a future session extending Dex's quality
surfaces starts from the pattern instead of rediscovering it.

## Guidance

### 1. The Trust Engine is a layered progression, not a feature

Build "prove it works" capability in this order — each layer answers a question the previous
one couldn't, and each is independently shippable:

1. **Test like a user, not like a developer.** CI must drive the *real* journeys (create a
   task through the actual tool, walk the onboarding state machine, boot every MCP server
   over stdio) — not assert on hand-written strings. The original "golden journey" test wrote
   markdown and asserted on its own writes; it exercised zero product code. Replacing it with
   real journeys immediately surfaced three shipping bugs. *(core/tests/test_golden_journeys.py,
   core/tests/test_mcp_stdio_startup.py)*
2. **Diagnose the user's own customizations.** `/dex-doctor` names the exact file the *user*
   broke, and never blames Dex for a user change or vice versa. *(core/utils/doctor.py)*
3. **Stop waiting to be asked.** A nightly self-check runs the smoke journeys and keeps a
   ledger; the next session surfaces only *actionable* breakage, and the doctor attributes it
   ("broke between t1 and t2; in that window pillars.yaml changed"). Detection beats reporting;
   attribution beats detection. *(core/utils/smoke.py, .scripts/nightly-smoke.sh)*
4. **Pool the signal (opt-in).** Anonymous, counts-only nightly verdicts — behind their own
   explicit opt-in, never the analytics consent — let a bad release be caught across the fleet
   in hours instead of weeks. *(core/utils/health_telemetry.py)*

### 2. The honest-verdict contract

Every diagnostic returns one of exactly four verdicts, and the distinction is the whole point:

- **OK** — verified working.
- **OFF** — a feature the user never enabled. *Healthy, not a problem.* Never report "off" as
  broken; that is the single most common way a health check erodes trust.
- **BROKEN** — verified failing, with a plain-English "what stopped working" and a fix path.
- **UNKNOWN / "couldn't check"** — a probe that could not run. *Never hide this.* An unknown
  presented as a pass is how a watchdog goes blind.

Any published "health page" or status surface must carry the same honesty: a check that
didn't run on this build reads "not applicable — not run", never a green tick; missing
evidence reads "unknown", never "passed".

### 3. Two verification practices that repeatedly paid off

**Coverage is a bug-detector, not a vanity metric — point it at file-mutating code.**
Writing *characterization* tests (tests that assert the behavior a user *needs*, over the
existing fixture vault) for untested code that mutates user files surfaced 8 real bugs in one
session — including task completion matching the *wrong* task by substring, and a completion
rewriting every line ending on a Windows-edited file. The technique: for each untested
mutating path, write the test asserting *correct* behavior; if the code fails it, mark the
test `xfail` with a `BUG:` reason (suite stays green, bug is documented as an executable
spec), then fix the code so the xfail flips to a real pass. Do **not** raise a coverage
percentage blindly — rank uncovered code by *business risk* (silent data corruption / silent
loss / core daily journey), and skip loud-failure code (platform/network paths fail visibly).

**For code-execution or security-sensitive changes, run two independent adversarial reviews.**
When the change lets Dex run user-supplied code (the "bless your own MCP server" feature), a
single review is not enough. Run two independent skeptics (e.g. an Opus reasoning subagent and
a separate Codex pass), each told to *refute*. Twice during this work the two reviews **split**
— one "ship", one "do-not-ship" — and **the paranoid verdict was correct both times**,
catching a genuine TOCTOU flaw (hashed bytes could differ from executed bytes) that the
optimistic review accepted. Rule: on a security boundary, a split verdict is a "do-not-ship";
converge both to clean before merging. Fail *closed* on every uncertain branch, and never
describe monkeypatch-level isolation as a "sandbox".

## Why This Matters

The caution *is* the product. A personal-AI assistant that once loses data or runs something
it shouldn't does not get its trust back. Over this effort the rigour didn't just guard future
work — it flushed out ~15 real bugs (in Dex, in the new machinery itself, and one
adversarially-confirmed data-loss hole) *before any user hit them*, and grew the suite from
232 to 723 tests that exercise real journeys. That is coverage-as-bug-detector and
honest-verdict diagnostics doing exactly their job.

## When to Apply

- Extending any Dex quality/diagnostic surface (doctor checks, smoke journeys, telemetry) —
  reuse the honest-verdict contract and the layered progression; don't invent a parallel one.
- Touching code that mutates a user's files (tasks, priorities, notes, configs) — write the
  characterization test first; expect it to find a bug.
- Any change that executes user-supplied code, handles credentials, or crosses a security
  boundary — run the two-independent-review pattern and treat a split as do-not-ship.

## Examples

Characterization-test-then-fix loop (the pattern that found 8 bugs):

```python
# 1. Write the test asserting CORRECT behavior, marked xfail if the code fails it:
@pytest.mark.xfail(
    reason="BUG: legacy title lookup uses substring matching and completes an "
           "earlier longer task instead of the later exact-title task",
    strict=False,
)
def test_legacy_completion_prefers_exact_title_over_earlier_substring_match(...):
    # assert the RIGHT task is completed, not whatever the code currently does
    ...

# 2. Fix the production code (exact-match, refuse ambiguity rather than guess):
exact_matching = [t for t in matching if t['title'].lower() == task_title.lower()]
if exact_matching:
    matching = exact_matching
elif len(matching) > 1:
    return _error(f"Multiple tasks found matching '{task_title}'")

# 3. Remove the xfail marker — the test now asserts-passes and guards the fix.
```

Honest-verdict rendering (never a false green tick):

```text
Test suites + coverage        Passed
Security gate                 Passed
Diff-aware test gate          Not applicable — not run (PR-only)
Some probe that couldn't run  Unknown — couldn't verify
```
