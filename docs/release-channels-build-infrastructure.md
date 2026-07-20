# Release channels — build infrastructure

Dex uses the same distribution builder for both release channels:

* Pushes to `main` build the force-refreshed `release` branch with the existing stable CI job.
* Once a `beta` source branch exists, pushes to it build the force-refreshed `release-beta` branch with `scripts/build-release.sh --source beta --target release-beta`.

Both builds apply `.distignore`, remove development-only package metadata, generate the canonical closed
`System/.release-evidence-profile.json`, and commit `System/.installed-files.manifest` from the exact distribution
tree. SR1 and pre-catalog builds declare `legacy-v1`; that profile intentionally has no release-catalog or
compatibility-metadata dependency. The stable job continues to publish its versioned GitHub Release. The beta job does
not create a GitHub Release, so it cannot become GitHub's latest release.

## Immutable distribution tags

Every completed distribution build creates an annotated tag with this scheme:

```text
dist/<target>/v<package-version>-<release-short-sha>
```

For example, stable and beta builds might create `dist/release/v1.61.0-a1b2c3d` and `dist/release-beta/v1.61.0-e4f5a6b`. The target segment keeps channel identities separate. Tags are pushed without force and never moved; each resolves to the exact generated release commit containing that build's installed-files manifest. This gives future rollback code a durable historical identity even though the channel branches themselves are force-refreshed.

Beta is build infrastructure only at this stage. Users cannot select the beta channel yet, and update and rollback behavior is unchanged.

## Bounded release awareness

SessionStart does not consume a moving release branch or the GitHub latest-release API. The verifier fetches only
immutable `dist/release/v<semver>-<short-sha>` annotated tags from the pinned canonical HTTPS repository into an
isolated bare cache. It selects the candidate's profile only from `System/.release-evidence-profile.json` in that
tagged commit and verifies tag, semantic version, package version, full commit/short suffix, exact tree, and exact
legacy installed-files manifest agreement.

The closed profiles are `legacy-v1` and `catalog-v1`. `catalog-v1` additionally requires its declared catalog and
compatibility artifacts. Missing, unknown, ambiguous, non-canonical, or contradictory evidence returns `UNKNOWN`;
declared `catalog-v1` never falls back to `legacy-v1`. SR1 selects no publisher authenticator, so the only higher
candidate notice is explicitly `release-appears-available-unverified` and never authorizes an automatic update.
