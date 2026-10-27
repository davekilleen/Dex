# Dex Helper (Calendar and Reminders)

Dex Helper is a small Mac app with its own identity. Dex calls it for Apple Calendar and Reminders reads and writes so the permission ask can appear when Dex is running inside VS Code or the Claude app.

This file is for people building Dex. The user-facing steps live in [Calendar_Setup.md](Dex_System/Calendar_Setup.md).

## What ships in this change

- Source for an unsigned app at `core/macos/dex-helper/`
- A Python client at `core/utils/macos_privacy_helper.py`
- Install and update from `install.sh` on a Mac, with a clear fallback
- Tests that do not need a real Mac app

The helper is **unsigned on purpose**. Do not sign, notarize, staple, or publish it from this change. Do not add signing secrets to the repo, to CI, or to install scripts.

## Fallback

If the helper is missing, cannot start, or this is not a Mac, Dex keeps the path that already shipped:

- Calendar reads and deletes still use the Python EventKit scripts
- Calendar create still uses the Calendar app script
- Reminders inside VS Code stay off and say to use the Claude app or Terminal

A helper that starts and then reports a permission error is a real answer. Dex does not fall back after that, because the fallback would ask the editor instead of Dex Helper.

## Unsigned local build

On a Mac with the Swift compiler:

```
bash core/macos/dex-helper/build.sh
python3 -m core.utils.macos_privacy_helper install
```

On Linux CI those commands skip cleanly. `build.sh` never calls a signing tool.

## Signing — later release step, needs explicit approval

Signing is **not** part of this change. It needs a later, separately approved release step before a signed helper can be trusted on a new Mac.

That later step needs:

1. An explicit go-ahead from the founder
2. An Apple Developer account and a Developer ID Application certificate
3. A hardened-runtime signed copy of Dex Helper
4. Notarization and stapling of that copy
5. Secrets stored outside the repo — never in git, never in this helper's build script
6. A published signed app for `/dex-update` to install, plus a way to check it is the signed one

Until that happens, treat any built helper as a local unsigned copy. Gatekeeper may block first open; the fallback path still works.
