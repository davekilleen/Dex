# Dex Helper (Calendar and Reminders)

Dex Helper is a small Mac app with its own identity. Dex will open a small helper so macOS can ask for Calendar and Reminders permission even when Dex is running inside VS Code or the Claude app.

This file is for people building Dex. The user-facing steps live in [Calendar_Setup.md](Dex_System/Calendar_Setup.md).

## What ships in this change

- Source for Dex Helper at `core/macos/dex-helper/`
- Shared EventKit logic in `core/utils/eventkit_ops.py` (the same functions the fallback scripts use)
- A Python client at `core/utils/macos_privacy_helper.py` that launches the helper with:

  `open -W -n -a "Dex Helper.app" --args <op> <json-out-path> [json-in-path]`

- Install and update from `install.sh` on a Mac, with a clear fallback
- Tests that do not need a real Mac app

Titles and other event data stay in vault temp JSON files under `System/.dex/tmp/` (mode 0600, unique names, deleted after read). They are never put on argv.

## How Dex opens the helper

Permission-bearing Calendar and Reminders calls go through LaunchServices (`open -W -n -a`). Dex never starts the helper binary as a child of the MCP server for those calls. That is what makes Dex Helper the responsible app.

Host detection covers Claude desktop, VS Code, Cursor, and Terminal. When the helper app is present, Dex routes Calendar and Reminders through it. When it is not:

- VS Code keeps the existing Reminders message (the Mac never shows the ask in that app)
- Claude desktop gets the same kind of structured `feature_status` — never a bare denial loop
- Terminal stays the fallback if someone wants Reminders without the helper

## Local (dev) build — ad-hoc sign

On a Mac, `/calendar-setup` builds the app and ad-hoc signs it with `codesign -s -` (the script uses `codesign --force --sign -`):

```
bash core/macos/dex-helper/build.sh
python3 -m core.utils.macos_privacy_helper install
```

Rebuilding resets the Calendar and Reminders grant. You will need to allow Dex Helper again.

Dex updates an installed helper in place only when the Team ID and bundle id match. If they do not, Dex says a re-grant is needed and leaves the installed app alone.

On Linux CI those commands skip cleanly. `build.sh` never calls `notarytool` or `stapler`, and never reads signing secrets.

## Signing — later release step, needs explicit approval

Developer ID plus notarization is **not** part of this change. It needs a later, separately approved release step before a signed helper can be trusted on a new Mac.

That later step needs:

1. An explicit go-ahead from the founder
2. An Apple Developer account and a Developer ID Application certificate
3. A hardened-runtime signed copy of Dex Helper
4. Notarization and stapling of that copy
5. Secrets stored outside the repo — never in git, never in this helper's build script
6. A published signed app for `/dex-update` to install, plus a way to check it is the signed one

Do not add signing secrets to the repo, to CI, or to install scripts.

Until that happens, treat any built helper as a local ad-hoc copy. Gatekeeper may block first open; the fallback path still works.

## Fallback

If the helper is missing, cannot start, or this is not a Mac, Dex keeps the path that already shipped:

- Calendar reads and deletes still use the Python EventKit scripts
- Calendar create still uses the Calendar app script
- Reminders inside VS Code stay off and say to use the Claude app or Terminal
- Reminders inside Claude desktop stay off with the same kind of structured status

A helper that starts and then reports a permission error is a real answer. Dex does not fall back after that, because the fallback would ask the editor instead of Dex Helper.
