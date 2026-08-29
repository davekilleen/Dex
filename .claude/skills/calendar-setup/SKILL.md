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

1. **Check current permission status:**
   - Run the permission checker: `python3 core/mcp/scripts/check_calendar_permission.py`
   - Show the user what status was returned
   - Do not promise that a Mac permission dialog will appear. When Dex runs inside VS Code or Cursor, that dialog often never shows.

2. **If Already Authorized:**
   - Great! Calendar queries are already optimized.
   - No action needed.

3. **If NotDetermined or Denied:**
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
- **Permission is per app:** macOS grants Calendar access to the app that is asking. When Dex runs inside VS Code or Cursor, grant that editor. A Terminal grant does not carry over.
- **Permission is persistent:** Once granted to the editor, access lasts until it is revoked
- **Privacy:** All calendar data stays local - Dex never sends calendar data anywhere
- **Fallback:** If EventKit isn't available, Dex falls back to AppleScript (works but slower)

---

## Troubleshooting

**"Module EventKit not found":**
- Run: `pip3 install pyobjc-framework-EventKit`
- This should have been installed during Dex setup

**No permission popup / access still denied:**
- Do not wait for a dialog, and do not switch to Terminal as the only fix
- Open System Settings → Privacy & Security → Calendars
- Turn on VS Code or Cursor (the app Dex is running in) and set Full access
- A grant already given to Terminal, Python, or python3 does not transfer
- Reinstalling Dex does not fix this

**Still seeing slow queries after granting access:**
- Restart the app Dex is running in (VS Code or Cursor) to reload the calendar connection
- Verify permission: `python3 core/mcp/scripts/check_calendar_permission.py`
