# Connect Google Calendar to Dex (Mac)

This guide is for **Mac users** who use **Google Calendar** and want Dex to show their real meetings—including recurring ones like weekly 1:1s—when they run `/daily-plan` or ask "what's on my calendar today?"

**Windows users:** Calendar connection is supported on Mac via Apple Calendar. This repo doesn't include Windows instructions yet.

If `/google-workspace-setup` already set your calendar source to Google, skip this guide — Dex reads Google Calendar through that connection. This page is only for reading Google events through the Mac Calendar app.

---

## How it works in one sentence

Dex reads your calendar from the **Calendar app** that came with your Mac. So you add your Google account to that app once, let the app Dex is running in use it, and Dex sees your meetings.

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

### Step 2: Let the app Dex is running in use your calendar

macOS only lets an app see your calendar if you allow **that** app. VS Code and Cursor are first-class Calendar surfaces — grant Calendar for the app you are in.

1. Open **System Settings** (or **System Preferences** on older macOS).
2. Go to **Privacy & Security** → **Calendars**.
3. Find **VS Code** or **Cursor** — whichever app Dex is running in — and turn it **On**.
4. Click that app and set access to **Full** (not "Add Only") so Dex can read your events.

Do not wait for a Mac permission popup. It often never appears when Dex runs inside VS Code or Cursor. A grant given to Terminal does **not** transfer to the editor. Reinstalling Dex does **not** fix a missing grant.

**Done.** Run `/daily-plan` or ask "what's on my calendar today?" — your Google meetings (including recurring ones) should show on the right days.

---

## If something's not working

| What you see | What to do |
|--------------|------------|
| **"Calendar access denied"** | Go to **System Settings** → **Privacy & Security** → **Calendars**, turn **VS Code** or **Cursor** on (the app Dex is running in), then click that app and set access to **Full** (not "Add Only"). Quit the editor and open it again. Do not switch to Terminal as the only fix, and do not reinstall Dex. |
| **No meetings or wrong dates for recurring events** | Make sure you did both steps above. If you installed Dex without running the installer (e.g. you installed Python packages yourself), open Terminal and run: `pip3 install --user pyobjc-framework-EventKit`, then restart the editor. |
| **Calendar is empty or very slow** | Same as above: both setup steps, and if you didn't run the installer, run the `pip3 install` line above. |

---

## If Dex is running inside VS Code or Cursor

macOS grants calendar access **per app** — it looks at which app is asking. When Dex runs inside **VS Code** or **Cursor**, that editor is the app that needs Calendar access.

What to do:

1. Open **System Settings** → **Privacy & Security** → **Calendars**.
2. Turn on **VS Code** or **Cursor** — the app you are in — and set access to **Full**.
3. Quit that app and open it again, then ask Dex to check your calendar.

A grant given to Terminal does **not** carry over to the editor. Reinstalling Dex or redoing setup will not change that. Do not treat a standalone terminal as the only path, and do not wait for a permission popup — it often never appears from inside the editor.

Apple Reminders is a separate toggle in the same **Privacy & Security** list. Grant it for the same editor app if you use those features. If Reminders tools still fail after that, Dex skips them — that is not a Calendar failure, and reinstalling will not fix it.

This was verified directly (August 2026): the same calendar check can succeed from Terminal.app and fail from both VS Code's built-in terminal and the editor's own process after access was granted in Terminal.app first. That is why the editor grant in System Settings is the path.

---

## Optional: Tell Dex which calendar is "work"

If you have several calendars and want Dex to focus on one (e.g. your work calendar) for faster answers, you can set it in **System/user-profile.yaml** under a `calendar` section with `work_calendar: "your.email@example.com"` (use the exact name as it appears in the Calendar app). You can skip this—Dex will still show your events without it.

---

## Summary

1. **Add Google to the Calendar app** — Calendar → Add Account → Google → sign in.
2. **Allow the app Dex is running in to access Calendars** — System Settings → Privacy & Security → Calendars → turn on VS Code or Cursor, then choose **Full** access (not "Add Only").

After that, your Google Calendar meetings show up in Dex on the right days, including recurring events.
