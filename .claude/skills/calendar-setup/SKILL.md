---
name: calendar-setup
description: "Grant Python calendar access for ~30x faster calendar queries. Use when the user says 'connect my calendar', 'calendar is slow', 'set up calendar access'. Not for connecting Google Workspace as a whole; use `google-workspace-setup`."
---

# Calendar Setup - Enable Fast Queries

**Purpose:** Grant calendar access for 30x faster calendar queries (30s → <1s)

**When to run:**
- After initial Dex installation
- If calendar queries feel slow
- If you see "Calendar access denied" errors

---

## Process

0. **Primary path: Dex will open a small helper so macOS can ask.**
   - On a Mac, build and install Dex Helper. The local build ad-hoc signs with `codesign -s -`:
     ```
     bash core/macos/dex-helper/build.sh
     python3 -m core.utils.macos_privacy_helper install
     ```
   - Rebuilding that app resets the Calendar and Reminders grant. The person will need to allow Dex Helper again.
   - Dex updates the helper in place only when the Team ID and bundle id match. If they do not, say a re-grant is needed. Do not replace it silently.
   - Developer ID signing and notarization are a later release step that needs explicit founder approval. Do not add signing secrets.
   - If `python3 -m core.utils.macos_privacy_helper status` says the helper is installed, Calendar and Reminders permission belong to **Dex Helper**. Ask the person to grant Calendar (Full) and Reminders to Dex Helper in System Settings if needed.

1. **Check current permission status:**
   - Run the permission checker: `python3 core/mcp/scripts/check_calendar_permission.py`
   - Show the user what status was returned
   - When the helper is missing: Do not promise that a Mac permission dialog will appear from the editor. When Dex runs inside VS Code or Cursor without the helper, that dialog often never shows. Terminal is the fallback, not the only path.

2. **If Already Authorized:**
   - Great! Calendar queries are already optimized.
   - No action needed.

3. **If NotDetermined or Denied and the helper is not installed:**
   - VS Code and Cursor are first-class Calendar surfaces. Send the person to System Settings for the app Dex is running in. Do not send them to a standalone terminal as the only path. Do not tell them to wait for a popup. Do not tell them that granting Terminal, Python, or python3 is enough.
   - Show clear instructions:
     ```
     To enable fast calendar queries:

     1. Open System Settings (Command+Space, type "System Settings")
     2. Click "Privacy & Security" in the sidebar
     3. Click "Calendars"
     4. Find the app Dex is running in — VS Code or Cursor — and turn it on
     5. Click that app and set access to Full (not "Add Only")
     6. Quit the editor and open it again
     7. Run /calendar-setup again to verify
     ```
   - A Terminal grant does not transfer to the editor. Reinstalling Dex does not fix a missing editor grant.

4. **If Restricted:**
   - Explain: "Calendar access is blocked by system policies (parental controls or enterprise MDM)"
   - Calendar queries will use AppleScript (slower but functional)
   - No user action possible

5. **After Success:**
   - Confirm: "✅ Calendar access granted! Queries are now 30x faster."
   - Explain: "Calendar queries now use native EventKit instead of AppleScript"
   - No need to run this again - permission is persistent for that app

---

## Technical Notes

- **EventKit vs AppleScript:** EventKit uses database queries (fast), AppleScript loads all events then filters (slow)
- **Permission is per app:** macOS grants Calendar access to the app that is asking. When Dex Helper is installed, Dex will open a small helper so macOS can ask — grant that app. When Dex runs inside VS Code or Cursor without the helper, grant that editor. A Terminal grant does not carry over.
- **Permission is persistent:** Once granted to the helper or the editor, access lasts until it is revoked. Rebuilding the helper resets the grant.
- **Privacy:** All calendar data stays local - Dex never sends calendar data anywhere
- **Fallback:** If Dex Helper is not installed, Dex uses the existing EventKit scripts (and AppleScript to create events). If EventKit isn't available, create still uses AppleScript.

---

## Troubleshooting

**"Module EventKit not found":**
- Run: `pip3 install pyobjc-framework-EventKit`
- This should have been installed during Dex setup

**No permission popup / access still denied:**
- If Dex Helper is installed, grant Calendar (Full) and Reminders to **Dex Helper**, then try again. Dex will open a small helper so macOS can ask.
- If it is not installed, do not wait for a dialog, and do not switch to Terminal as the only fix
- Open System Settings → Privacy & Security → Calendars
- Turn on VS Code or Cursor (the app Dex is running in) and set Full access
- A grant already given to Terminal, Python, or python3 does not transfer
- Reinstalling Dex does not fix this

**Still seeing slow queries after granting access:**
- Restart the app Dex is running in (VS Code or Cursor) to reload the calendar connection
- Verify permission: `python3 core/mcp/scripts/check_calendar_permission.py`
