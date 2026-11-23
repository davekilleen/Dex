---
name: calendar-setup
description: "Install Dex Helper and grant Calendar access for ~30x faster calendar queries. Use when the user says 'connect my calendar', 'calendar is slow', 'set up calendar access'. Not for connecting Google Workspace as a whole; use `google-workspace-setup`."
---

<!-- Generated from `.claude/skills/calendar-setup/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

# Calendar Setup - Enable Fast Queries

**Purpose:** Install Dex Helper and grant calendar access for 30x faster calendar queries (30s → <1s)

**When to run:**
- After initial Dex installation
- If calendar queries feel slow
- If you see "Calendar access denied" or "Dex Helper is not installed" errors

---

## Process

0. **Primary path: Dex will open a small helper so macOS can ask.**
   - On a Mac, install the signed Dex Helper from this Dex:
     ```
     python3 -m core.utils.macos_privacy_helper install
     ```
     Use the vault Python when it exists (`.venv/bin/python`). This downloads the signed helper pinned in this Dex, checks it, and replaces `~/Applications/Dex Helper.app` as a whole app. If it says the signed helper is not in this Dex yet, say that calmly and stop — do not build a local copy unless the person is building Dex themselves.
   - People building Dex locally may use `DEX_HELPER_DEV=1`. That path builds and ad-hoc signs with `codesign -s -`:
     ```
     DEX_HELPER_DEV=1 bash core/macos/dex-helper/build.sh
     DEX_HELPER_DEV=1 python3 -m core.utils.macos_privacy_helper install --dev
     ```
   - Rebuilding that app resets the Calendar and Reminders grant. The person will need to allow Dex Helper again.
   - Dex updates the helper in place only when the Team ID and bundle id match. If they do not, say a re-grant is needed. Do not replace it silently.
   - Developer ID signing and notarization are a local Mac step: `bash core/macos/dex-helper/sign-and-notarize.sh`. That still needs explicit founder approval before a signed copy is published. Do not add signing secrets.
   - If `python3 -m core.utils.macos_privacy_helper status` says the helper is installed, Calendar and Reminders permission belong to **Dex Helper**. Ask the person to grant Calendar (Full) and Reminders to Dex Helper in System Settings if needed.

1. **Check current permission status:**
   - Run the permission checker: `python3 core/mcp/scripts/check_calendar_permission.py`
   - Show the user what status was returned
   - When the helper is missing: Do not promise that a Mac permission dialog will appear from the editor. When Dex runs inside VS Code or Cursor without the helper, that dialog often never shows. Do not send them to a standalone terminal as the only path. Calendar and Reminders stay unavailable until Dex Helper is installed.

2. **If Already Authorized:**
   - Great! Calendar queries are already optimized.
   - No action needed.

3. **If NotDetermined or Denied and the helper is not installed:**
   - VS Code and Cursor are first-class Calendar surfaces. Send the person to install Dex Helper, then to System Settings for **Dex Helper**. Do not send them to a standalone terminal as the only path. Do not tell them to wait for a popup. Do not tell them that granting Terminal, Python, or python3 is enough.
   - Show clear instructions:
     ```
     To enable fast calendar queries:

     1. Run /calendar-setup or /dex-update so Dex Helper is installed
     2. Open System Settings (Command+Space, type "System Settings")
     3. Click "Privacy & Security" in the sidebar
     4. Click "Calendars"
     5. Find Dex Helper and turn it on
     6. Click Dex Helper and set access to Full (not "Add Only")
     7. Quit the editor and open it again
     8. Run /calendar-setup again to verify
     ```
   - A Terminal grant does not transfer to Dex Helper. Reinstalling Dex does not fix a missing helper or a missing Dex Helper grant.

4. **If Restricted:**
   - Explain: "Calendar access is blocked by system policies (parental controls or enterprise MDM)"
   - Calendar queries cannot use Dex Helper until that restriction is lifted
   - No user action possible inside Dex

5. **After Success:**
   - Confirm: "✅ Calendar access granted! Queries are now 30x faster."
   - Explain: "Calendar queries now go through Dex Helper."
   - No need to run this again - permission is persistent for Dex Helper until it is rebuilt or revoked

---

## Technical Notes

- **Dex Helper vs AppleScript:** Dex Helper uses fast native calendar queries. AppleScript is not a fallback on a Mac.
- **Permission is per app:** macOS grants Calendar access to the app that is asking. Dex will open a small helper so macOS can ask — grant **Dex Helper**. When Dex runs inside VS Code or Cursor, grant Dex Helper, not the editor. A Terminal grant does not carry over.
- **Permission is persistent:** Once granted to the helper, access lasts until it is revoked. Rebuilding the helper resets the grant.
- **Privacy:** All calendar data stays local - Dex never sends calendar data anywhere
- **Fail closed:** If Dex Helper is not installed on a Mac, Calendar and Reminders stay unavailable. Do not install extra Python calendar packages, and do not grant Python as the fix.

---

## Troubleshooting

**"Dex Helper is not installed" / "not in this Dex yet":**
- Run `/calendar-setup` or `/dex-update`
- If Dex says the signed helper is not in this Dex yet, wait for that copy — do not treat a Terminal grant as the fix

**No permission popup / access still denied:**
- If Dex Helper is installed, grant Calendar (Full) and Reminders to **Dex Helper**, then try again. Dex will open a small helper so macOS can ask.
- If it is not installed, do not wait for a dialog, and do not switch to Terminal as the only fix
- Open System Settings → Privacy & Security → Calendars
- Turn on Dex Helper and set Full access
- A grant already given to Terminal, Python, or python3 does not transfer
- Reinstalling Dex does not fix this

**Still seeing slow queries after granting access:**
- Restart the app Dex is running in (VS Code or Cursor) to reload the calendar connection
- Verify permission: `python3 core/mcp/scripts/check_calendar_permission.py`
