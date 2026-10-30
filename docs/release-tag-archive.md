# Bridge-and-archive procedure for `dist/release` tags

This is the operator procedure for retiring a live distribution tag so old
installs keep seeing updates. It is the procedure the reachability gate means
when it says to use the verified bridge-and-archive path before old installs
go silent.

Do not invent a new tag object. Do not force-update, retag, or rewrite history.
The only allowed change is a new `dist/archive/v<version>-<sha>` *name* for the
same annotated tag object, then deletion of the old `dist/release` name.

## Why this exists

Installs on v1.62.0, v1.68.0, and v1.74.0 list every `dist/release/v*` tag
newer than themselves and then fail closed if that list is longer than 32. They
do not take a subset. A 32nd newer live tag makes those installs stop noticing
updates.

The quality job encodes that limit in `scripts/check-release-tag-reachability.sh`:

- shipped bound: 32 newer live tags
- pre-publication margin: 31, because the current stable CI run may publish
  one more tag

Archiving a live tag under `dist/archive/` removes it from that window without
discarding the historic tree. Fleet discovery still starts from the archive
name. The updater foundation (`dist/release/v1.81.16-281202d` at the time this
was written) must stay live so those old installs still have a path to the
self-delivering updater.

## What earlier retirements actually did

Earlier waves (including the v1.74.0-eb50463 and v1.75.1-784fabe moves named
in PRs #408 and #409, and the later 1.81.17–1.84 and 1.86–1.91 range
retirements) copied the existing annotated tag object to the archive
namespace and then deleted only the `dist/release` ref.

Proof that the object was not rewritten: the archive ref
`dist/archive/v1.74.0-eb50463` still peels to commit `eb50463…`, and the tag
object's own `tag` header is still `dist/release/v1.74.0-eb50463`. The
historic-fleet runner describes this as renaming `dist/release/` to
`dist/archive/` without moving the object.

## What must stay live

Never retire a tag that is still required as a live advertisement:

- the pinned foundation / bridge release (today:
  `dist/release/v1.81.16-281202d`)
- the current latest canonical release
- a canary start that is still listed as `dist/release/…` in
  `scripts/run-historic-fleet-darwin.sh` (today:
  `dist/release/v1.61.0-dc7d332`)
- any version with no remaining higher `dist/release` tag, unless a different
  live hop has been proven

Archiving a version that is older than the sentinels (for example v1.61.0)
does not free a sentinel slot. Only tags newer than v1.74.0 shrink the
reachability count.

After the archive, every version that is still a live `dist/release` tag, and
every version just retired, must still see at least one higher live
`dist/release` tag. Leave enough unused slots for several more publishes
(target at least eight free slots after the next intended publish).

## Preflight

Record identities before touching any remote ref. For each candidate tag:

```bash
TAG=dist/release/vX.Y.Z-abcdefg
ARCHIVE=dist/archive/vX.Y.Z-abcdefg

git rev-parse --verify "refs/tags/$TAG"
git cat-file -t "refs/tags/$TAG"          # must print: tag
git rev-parse --verify "refs/tags/$TAG^{}"
git rev-parse --verify "refs/tags/$TAG^{tree}"
git cat-file tag "refs/tags/$TAG" | sed -n '1,8p'
```

Confirm:

1. The object type is `tag` (annotated).
2. The peeled commit prefix matches the suffix in the tag name.
3. `git ls-remote --exit-code origin "refs/tags/$ARCHIVE"` fails. If the
   archive name already exists, stop. Do not overwrite it.
4. The destination is absent on origin and the source still points at the
   recorded tag object.

Simulate first in a local bare mirror that is **not** origin. Copy the tag
object, delete only the mirror's `dist/release` name, point a throwaway
checkout's `origin` at that mirror, then run:

```bash
bash scripts/check-release-tag-reachability.sh
bash scripts/check-release-tag-uniqueness.sh
```

Also run the existing uniqueness / fleet / historic-bridge tests. Do not push
any tag to origin until those gates are green against the simulated post-archive
list, including one extra unpublished-then-published next-version tag.

## Archive on origin (human-approved only)

Create the archive names first. Delete the live names only after origin
advertises the archive refs with the same tag-object SHA.

```bash
# Copy the existing annotated object to the archive name. Do not git tag -a.
git push origin \
  "refs/tags/$TAG:refs/tags/$ARCHIVE"

# Prove origin now has the same object under the archive name.
test "$(git ls-remote origin "refs/tags/$ARCHIVE" | awk '{print $1}')" \
  = "$(git rev-parse "refs/tags/$TAG")"

# Only then remove the live name.
git push origin ":refs/tags/$TAG"
```

Never use `--force`, `tag -f`, or `update-ref -d` against origin. Never create
a second annotated tag for the same version: a new `git tag -a` would mint a
new tag object and break the "same object" rule used by earlier retirements.

If several tags are being retired in one wave, finish every archive push and
every origin identity check before deleting any `dist/release` ref.

## After the remote rename

1. Re-run `bash scripts/check-release-tag-reachability.sh` and
   `bash scripts/check-release-tag-uniqueness.sh` against origin.
2. If a canary start moved from `dist/release/` to `dist/archive/`, update
   `CANARY_STARTS` in `scripts/run-historic-fleet-darwin.sh` to the archive
   name. Do not drop the start.
3. Leave the GitHub Release, assets, and semantic `v*` tag alone. This
   procedure only renames the immutable distribution ref.

## Reversibility

The archive ref is the original annotated object. Restoring the live name is
the inverse copy, and only if that live name is still absent:

```bash
git push origin \
  "refs/tags/$ARCHIVE:refs/tags/$TAG"
```

Do not delete the archive name as part of a restore unless a separate, reviewed
decision says the historic start is no longer required.
