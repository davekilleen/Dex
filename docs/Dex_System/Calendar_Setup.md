# Connect Google Calendar to Dex (Mac)

**Execution boundary:** this route uses macOS Calendar permissions through Dex Helper. A plugin or folder grant alone does not grant calendar access. The portable read-only package does not bundle the calendar integration; new-app calendar journeys need their own verification.

This guide is for **Mac users** who use **Google Calendar** and want Dex to show their real meetings—including recurring ones like weekly 1:1s—when they run `/daily-plan` or ask "what's on my calendar today?"

**Windows users:** Calendar connection is supported on Mac via Apple Calendar. This repo doesn't include Windows instructions yet.

If `/google-workspace-setup` already set your calendar source to Google, skip this guide — Dex reads Google Calendar through that connection. This page is only for reading Google events through the Mac Calendar app.

---

## How it works in one sentence

Dex reads your calendar from the **Calendar app** that came with your Mac. So you add your Google account to that app once, let **Dex Helper** use it, and Dex sees your meetings. Dex will open a small helper so macOS can ask.

---

## One-time setup (two steps)

### Step 1: Add Google to your Mac's Calendar app

Dex doesn't talk to Google directly. It uses the built-in **Calendar** app on your Mac. So first we get your Google calendar into that app.

1. Open **Calendar** (search for it in Spotlight or find it in your Applications folder).
2. In the menu bar at the top, click **Calendar** → **Add Account…**  
   (On some versions of macOS it may say **File** → **New Account…** instead.)
3. Click **Google** and sign in with your Google account (work or personal).
4. Make sure **Calendars** is turned on and the calendars you want are checked in the sidebar.

Your Google events will now appear in the Calendar app. Once they're here, Dex can see them too.

### Step 2: Install Dex Helper and let it see that calendar

macOS only lets an app see your calendar if you allow **that** app. Calendar and Reminders on a Mac go through **Dex Helper**. Granting VS Code, Cursor, Terminal, Python, or python3 is not enough.

**Preferred:** Dex will open a small helper so macOS can ask. Install **Dex Helper** with `/calendar-setup` or `/dex-update` (the installer also tries). Then grant Calendar and Reminders to **Dex Helper**. Dex reads and writes through that small app, so the permission ask can appear even when you are in VS Code or the Claude app. Rebuilding that helper resets the grant — you will need to allow it again.

1. Open **System Settings** (or **System Preferences** on older macOS).
2. Go to **Privacy & Security** → **Calendars**.
3. Turn on **Dex Helper** and set access to **Full** (not "Add Only").
4. Do the same under **Reminders** if you use phone capture.

**If Dex Helper is not installed yet**, Calendar and Reminders stay unavailable. VS Code and Cursor are first-class Calendar surfaces in the sense that Dex still runs there — but the Mac will not show a Calendar or Reminders ask for those editors, and Dex will not use a hidden workaround. Run `/calendar-setup` or `/dex-update`, then grant **Dex Helper**.

Do not wait for a Mac permission popup from the editor itself. It often never appears when Dex runs inside VS Code or Cursor. A grant given to Terminal, VS Code, Cursor, Python, or python3 does **not** transfer to Dex Helper. Reinstalling Dex does **not** fix a missing helper or a missing grant.

**Done.** Run `/daily-plan` or ask "what's on my calendar today?" — your Google meetings (including recurring ones) should show on the right days.

---

## If something's not working

| What you see | What to do |
|--------------|------------|
| **"Dex Helper is not installed"** | Run `/calendar-setup` or `/dex-update`. Do not switch to Terminal as the only fix, and do not reinstall Dex. |
| **"Calendar access denied"** | Turn **Dex Helper** on under **System Settings** → **Privacy & Security** → **Calendars** and set **Full** access. Quit the editor and open it again. Do not switch to Terminal as the only fix, and do not reinstall Dex. |
| **"Calendar access is set to Add Events Only"** | macOS is letting Dex Helper add events but not read them. Go to **System Settings** → **Privacy & Security** → **Calendars**, click **Dex Helper**, and change it from "Add Events Only" to **Full Access**. Quit that app and open it again. Asking Dex again without changing the setting will not help. |
| **No meetings or wrong dates for recurring events** | Make sure you did both steps above, including installing Dex Helper and granting **Full** access. |
| **Calendar is empty or very slow** | Same as above: both setup steps, with Dex Helper installed and granted **Full** access. |

---

## If Dex is running inside VS Code or Cursor

macOS grants calendar access **per app** — it looks at which app is asking. Dex Helper is the app that needs Calendar and Reminders access. When Dex runs inside **VS Code** or **Cursor**, that editor is not a substitute grant.

What to do:

1. Install Dex Helper (`/calendar-setup` or `/dex-update`).
2. Open **System Settings** → **Privacy & Security** → **Calendars**.
3. Turn on **Dex Helper** and set access to **Full**.
4. Do the same under **Reminders** if you use phone capture.
5. Quit the editor and open it again, then ask Dex to check your calendar.

A grant given to Terminal, VS Code, or Cursor does **not** carry over to Dex Helper. Reinstalling Dex or redoing setup will not change that. Do not treat a standalone terminal as the only path, and do not wait for a permission popup — it often never appears from inside the editor.

Apple Reminders is a separate permission from Calendar. When Dex Helper is installed, grant Reminders to **Dex Helper** and Dex can use Reminders from VS Code or the Claude app. When Dex Helper is not installed and Dex is running inside **VS Code**, the Mac never shows the Reminders permission ask, and Reminders cannot be switched on from that app. That is not a Calendar failure, and reinstalling will not fix it.

If you want Reminders (phone capture and focus-task notifications), install Dex Helper and grant it Reminders. You can keep using Dex in VS Code for everything else.

This was verified directly (August 2026): the same calendar check can succeed from Terminal.app and fail from both VS Code's built-in terminal and the editor's own process after access was granted in Terminal.app first. That is why Dex Helper is the path, not a grant to the editor.

---

## Optional: Tell Dex which calendar is "work"

If you have several calendars and want Dex to focus on one (e.g. your work calendar) for faster answers, you can set it in **System/user-profile.yaml** under a `calendar` section with `work_calendar: "your.email@example.com"` (use the exact name as it appears in the Calendar app). You can skip this—Dex will still show your events without it.

---

## Summary

1. **Add Google to the Calendar app** — Calendar → Add Account → Google → sign in.
2. **Install Dex Helper and allow it to access Calendars** — `/calendar-setup` or `/dex-update`, then System Settings → Privacy & Security → Calendars → turn on Dex Helper and choose **Full** access (not "Add Only").

After that, your Google Calendar meetings show up in Dex on the right days, including recurring events.
