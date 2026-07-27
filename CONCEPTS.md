# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Verification and release

### Provenance bucket
A grouping of factual claims by *how each was established* — observed in a real run, read from source but never observed, or untested — rather than by what the claim is about.

Used when preparing anything user-facing. Topic grouping lets unverified claims inherit the authority of verified neighbours; provenance grouping isolates them. A fourth bucket covers failure paths — what a user sees when something goes wrong, confirmed by deliberately breaking it. A claim may only be promoted between buckets by observing the behaviour, never by re-reading the code that would produce it.

### First-run transcript
A captured, verbatim record of the first command a real user types against clean state, together with its actual output.

Distinct from a test result: a test proves the paths someone thought to write, a first-run transcript proves the path everyone assumed existed. Required evidence before user-facing work is considered done. A passing test suite does not substitute for it.

### Honest ceiling
The strongest protection a given installation can truthfully claim, together with the requirement that published wording never implies more than that.

Load-bearing when a capability exists in one environment but not another: the weaker environment ships with its limit stated plainly rather than being denied the feature or being allowed to imply the stronger guarantee. Naming the ceiling honestly is treated as a feature, not an apology.

## Connections

### Connection
A saved authorisation that lets Dex act with a third-party tool on the user's behalf, held on the user's own machine.

Disconnecting removes it locally but does not revoke the authorisation at the tool itself — full revocation requires action in that tool's own settings. This asymmetry is deliberate and must always be surfaced to the user.

### Presence
Evidence that the human is physically at the machine, required before a sensitive credential operation proceeds.

Presence is supplied by an environment capable of proving it; where no such environment exists, no amount of local code can manufacture it. A malformed or unavailable presence check fails closed — it never approves by default. Presence protects operations, not custody: it is not what keeps a credential secret.

### Standalone tier
The mode a command-line installation runs in when there is genuinely no host application present, in which presence is not required because it cannot be provided.

Engages only on the absence of any host evidence; ambiguity resolves to the stricter path. A credential provisioned under a host must never become readable by falling back to this tier — custody, not presence, is what prevents that.

### Reviewed provider
A third-party tool whose connection details this project has itself checked, as distinct from one carried in the catalogue but unexamined.

Connections to unreviewed providers are refused by default and require a deliberate opt-in, so the protection lives in the machinery rather than in an assistant remembering to ask. The reviewed set is deliberately small; catalogue membership is not review.

## Flagged ambiguities

- "Verified" had been used both for *a credential we checked against its provider just now* and for *a security assurance*. These are distinct; only the first meaning is used, and user-facing wording says "checked" to avoid implying the second.
