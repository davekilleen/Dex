# Release channels — build infrastructure

Dex uses the same distribution builder for both release channels:

* Pushes to `main` build the force-refreshed `release` branch with the existing stable CI job.
* Once a `beta` source branch exists, pushes to it build the force-refreshed `release-beta` branch with `scripts/build-release.sh --source beta --target release-beta`.

Both builds apply `.distignore`, remove development-only package metadata, and commit `System/.installed-files.manifest` from the exact distribution tree. The stable job continues to publish its versioned GitHub Release. The beta job does not create a GitHub Release, so it cannot become GitHub's latest release.

## Immutable distribution tags

Every completed distribution build creates an annotated tag with this scheme:

```text
dist/<target>/v<package-version>-<release-short-sha>
```

For example, stable and beta builds might create `dist/release/v1.61.0-a1b2c3d` and `dist/release-beta/v1.61.0-e4f5a6b`. The target segment keeps channel identities separate. Tags are pushed without force and never moved; each resolves to the exact generated release commit containing that build's installed-files manifest. This gives future rollback code a durable historical identity even though the channel branches themselves are force-refreshed.

Beta is build infrastructure only at this stage. Users cannot select the beta channel yet, and update and rollback behavior is unchanged.
