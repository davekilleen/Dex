# Dex Helper (Calendar and Reminders)

Dex Helper is a small compiled Mac app with its own identity. Dex will open a small helper so macOS can ask for Calendar and Reminders permission even when Dex is running inside VS Code or the Claude app.

This file is for people building Dex. The user-facing steps live in [Calendar_Setup.md](Dex_System/Calendar_Setup.md).

## What ships in this change

- Native Swift source for Dex Helper at `core/macos/dex-helper/`
- A Python client at `core/utils/macos_privacy_helper.py` that launches the helper with:

  `open -W -n -a "Dex Helper.app" --args <op> <json-out-path> [json-in-path]`

- Install from the signed zip pinned in `core/macos/dex-helper/release-manifest.json`
- Tests that do not need a live Calendar database

The helper executable is a compiled Mac binary, not a Python script. Dex never writes inside the app after copying it. Titles and other event data stay in vault temp JSON files under `System/.dex/tmp/` (mode 0600, unique names, deleted after read). They are never put on argv.

## How Dex opens the helper

Permission-bearing Calendar and Reminders calls go through LaunchServices (`open -W -n -a`). Dex never starts the helper binary as a child of the MCP server for those calls. That is what makes Dex Helper the responsible app. Success is judged from the out-file JSON, not from whether `open` itself returned 0.

Host detection covers Claude desktop, VS Code, Cursor, and Terminal. When a usable Dex Helper is installed, Dex routes Calendar and Reminders through it. When it is not:

- On a Mac, Calendar and Reminders stay unavailable with a next step (`/calendar-setup` or `/dex-update`)
- VS Code keeps a clear Reminders message (the Mac never shows the ask in that app without Dex Helper)
- Claude desktop gets the same kind of structured `feature_status` — never a bare denial loop
- Terminal without Dex Helper is not a supported Calendar or Reminders path

## How people using Dex get the helper

`python3 -m core.utils.macos_privacy_helper install` downloads the signed zip named in `release-manifest.json`, checks it, and replaces `~/Applications/Dex Helper.app` as a whole app. An empty checksum means that signed copy is not in this Dex yet — Dex refuses to download and says so. `/dex-update` runs the same install after a successful apply, before the post-update check. Installer failure does not undo the Dex code update.

Restoring the previous helper is `python3 -m core.utils.macos_privacy_helper rollback`. `/dex-rollback` does not undo the helper app.

Dex updates an installed helper in place only when the Team ID and bundle id match. If they do not, Dex says a re-grant is needed and leaves the installed app alone.

## Local (dev) build — ad-hoc sign

On a Mac, people building Dex can build the app and ad-hoc sign it with `codesign -s -` (the script uses `codesign --force --sign -`):

```
DEX_HELPER_DEV=1 bash core/macos/dex-helper/build.sh
DEX_HELPER_DEV=1 python3 -m core.utils.macos_privacy_helper install --dev
```

Rebuilding resets the Calendar and Reminders grant. You will need to allow Dex Helper again.

On Linux CI those commands skip cleanly. `build.sh` never calls `notarytool` or `stapler`, and never reads signing secrets. People using Dex install the signed copy, not this local build.

## Signing and notarizing on the Mac that holds the certificate

Developer ID plus notarization is a **local Mac script**, not CI, and it does not publish, tag, or create a GitHub release. Explicit approval is still required before a signed helper is shipped to other Macs. This remains a later, separately approved release step.

Do not add signing secrets to the repo, to CI, or to install scripts. The notary password lives in the keychain profile `dex-notary`.

One-time on that Mac:

```
xcrun notarytool store-credentials dex-notary
```

Then, from the Dex checkout root (replace `~/Dex` with the clone path):

```
cd ~/Dex
bash core/macos/dex-helper/sign-and-notarize.sh
```

The same script can be run from `core/macos/dex-helper/`:

```
cd ~/Dex/core/macos/dex-helper
bash sign-and-notarize.sh
```

That script:

1. Builds the helper (`bash core/macos/dex-helper/build.sh`) as a native universal app
2. Codesigns it with the hardened runtime (`--options runtime`), the Developer ID Application identity named in the script, and `DexHelper.entitlements` (Calendar and Reminders only)
3. Zips it with `ditto` and notarises with `xcrun notarytool submit --keychain-profile dex-notary --wait`
4. Staples the app
5. Writes `DexHelper-vVERSION.zip` and a checksum file
6. Verifies with `codesign --verify --deep --strict --verbose=2` and `spctl --assess --type execute -vv`

Until that script has been run on that Mac and the checksum is filled in, treat any built helper as a local ad-hoc copy. Gatekeeper may block first open. A published signed app for `/dex-update` is still a later, separately approved release step.

## Fail closed

If the helper is missing, is the old script copy, is unsigned without a local-dev override, or this is not a Mac:

- On a Mac, Calendar and Reminders stay unavailable. Dex does not fall back to Python calendar packages or to Terminal
- Reminders inside VS Code stay off and say to install Dex Helper
- Reminders inside Claude desktop stay off with the same kind of structured status

A helper that starts and then reports a permission error is a real answer. Dex does not fall back after that, because the fallback would ask the editor instead of Dex Helper.
