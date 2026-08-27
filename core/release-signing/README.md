# Release signing trust anchor

This folder holds one file that matters: **`allowed_signers`**.

It is the list of public keys allowed to sign a Dex release. Dex reads the copy
already installed on your machine and uses it to check the *next* release before
installing it. If the signature is missing, or made with a key that is not on
this list, the update is refused and nothing on your computer changes.

## Why the file lives here

`core/` is release-owned, so every update replaces this file wholesale with the
copy from the release being installed. That is exactly the behavior a trust
anchor needs: a key can only be added or removed by publishing a release signed
by a key that is *already* trusted.

## The bootstrap caveat, stated plainly

`allowed_signers` travels through the same channel it protects. The first
release that carries a real key is therefore trusted the old way — by integrity
checks alone. From the next update onward the protection is real, because the
list being consulted is the one already on disk from a release the user
previously accepted, not the one sitting inside the candidate.

## Key rotation

Rotation is not a special mechanism. Ship a new `allowed_signers` inside a
release signed by the **old** key. Every rotation is therefore authenticated by
the key it replaces. Keep the old key listed for one release so an install that
skipped a version can still verify.

## Where the procedure lives

`docs/release-signing-runbook.md` — creating the key, configuring Git, signing a
release tag, verifying it before pushing, and rotating keys.

## Where the checking code lives

- `core/utils/update_verifier.py` — `load_allowed_signers`,
  `assert_signature_verifiable`, `UpdateVerifier._verify_tag_signature`
- `core/update/apply_update.py` — `_verify_release_publisher`, the last gate
  before a release can be previewed or applied
