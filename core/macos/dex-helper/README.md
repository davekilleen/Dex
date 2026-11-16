# Dex Helper source

Mac app that asks for Calendar and Reminders permission under
`ai.heydex.DexHelper`. Dex opens this app through LaunchServices so the
permission ask belongs to the helper, not the editor.

## Local (dev) build — ad-hoc sign

From the Dex checkout root:

```
bash core/macos/dex-helper/build.sh
python3 -m core.utils.macos_privacy_helper install
```

`build.sh` is macOS only and skips elsewhere. It ad-hoc signs with
`codesign --sign -`. Rebuilding resets the Calendar and Reminders grant.

## Developer ID sign + notarise (this Mac only)

This does **not** publish, tag, or create a GitHub release. It needs the
Developer ID certificate and the `dex-notary` keychain profile on this Mac.
Secrets stay in the keychain — never in git.

From the Dex checkout root (replace `~/Dex` with your clone):

```
cd ~/Dex
bash core/macos/dex-helper/sign-and-notarize.sh
```

That script: (1) builds the helper, (2) codesigns it with the hardened
runtime, the Developer ID Application identity named in the script, and
Calendar/Reminders entitlements, (3) zips it and notarises with
`xcrun notarytool submit --keychain-profile dex-notary --wait`, (4) staples
it, (5) verifies with `spctl` and `codesign --verify`.

See `docs/macos-privacy-helper.md`.
