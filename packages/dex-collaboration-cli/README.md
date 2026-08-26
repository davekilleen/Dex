# Dex Core collaboration CLI artifact

This package owns the narrow B5 Core-artifact seam for Dex's Solo beta. It
builds a platform-labelled, installable archive containing a `core` executable
and the real native Buzz clients needed for:

- `core identity create --name NAME`
- `core rooms list [--as ID] --json`
- `core rooms create --name NAME [--description TEXT] [--as ID]`
- `core post --as ID --room UUID --text TEXT`
- `core timeline --room UUID [--as ID] [--limit N] --json`

The artifact is implemented and verifiable in this package. It is a CI
artifact only: it is not wired into Dex's installer, release workflow, or an
existing packaged app. That integration and packaged-app proof remain B5.4
work.

## Frozen boundary

`contract.json` pins the collaboration runtime to
`block/buzz@b2ac66cde81df7ce1afc50016e1571cb6e8b7779`. The builder compiles
`buzz-cli` and `buzz-admin` from that exact checkout with the locked dependency
graph. It rejects a dirty source tree and does not accept caller-provided
runtime binaries.

The artifact contains:

```text
dex-core-collaboration-cli-<platform>-<architecture>/
├── bin/core
├── libexec/buzz
├── libexec/buzz-admin
├── LICENSES/Buzz-LICENSE
├── manifest.json
└── SHA256SUMS
```

Supported labels are `linux` or `darwin` and `x86_64` or `arm64`. The verifier
checks the native executable headers against those labels, exact payload and
modes, every manifest/checksum entry, the pinned source revision, and that
`bin/core --artifact-info` runs with fresh homes and an empty caller `PATH`.
The `.tar.gz.sha256` sidecar is verified before the archive is safely extracted
and checked again.

`BUZZ_RELAY_URL` is the explicit service boundary and defaults to
`ws://127.0.0.1:34000`. The packaged artifact does not provide or start that
service.

Identity private keys remain in
`$DEX_STUDIO_HOME/keys/agents/<id>/key.json` (or
`$HOME/.dex-studio/...`) with `0700` directories and `0600` files. Existing
identities are never overwritten. Standard output is JSON-only; failures are
JSON on standard error, and native error details are scrubbed of the active
private key.

Buzz uses NIP-29 semantics: the selected creator identity signs the create
request, while canonical channel metadata returned by the relay is
relay-signed. The behavioral proof verifies the creator selection, the room
flags, and a post/timeline round-trip signed by that same identity without
misreporting the relay metadata signer as the creator.

## Build and verify

Use a Buzz checkout at the exact revision and Rust 1.95.0:

```bash
python3 packages/dex-collaboration-cli/build_artifact.py \
  --buzz-source /path/to/buzz \
  --output /tmp/dex-core-artifacts

python3 packages/dex-collaboration-cli/verify_artifact.py \
  /tmp/dex-core-artifacts/dex-core-collaboration-cli-linux-x86_64

python3 packages/dex-collaboration-cli/verify_artifact.py \
  /tmp/dex-core-artifacts/dex-core-collaboration-cli-linux-x86_64.tar.gz
```

The builder defaults to six Cargo jobs and refuses values above nine so it
cannot silently consume every core on shared build hosts.

With a development relay available, run the real behavioral proof against an
already verified extracted artifact:

```bash
python3 packages/dex-collaboration-cli/prove_real_runtime.py \
  /tmp/dex-core-artifacts/dex-core-collaboration-cli-linux-x86_64
```

The proof creates a uniquely named disposable room on that relay. It uses
fresh temporary homes and an empty caller `PATH`, checks identity persistence
and overwrite refusal, selected creator identity and room flags, signed kind-9
post/timeline semantics, newest-tail limiting, JSON failures for invalid and
unknown inputs, relay failure handling, and private-key non-disclosure.

## CI

`.github/workflows/b5-core-collaboration-artifact.yml` builds and verifies
native Linux and macOS archives, then uploads them as short-lived workflow
artifacts. It has no release trigger and publishes no GitHub Release assets.
