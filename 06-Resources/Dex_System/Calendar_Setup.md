# Connect Google Calendar to Dex (Mac)

This guide is for **Mac users** who use **Google Calendar** and want Dex to show their real meetings—including recurring ones like weekly 1:1s—when they run `/daily-plan` or ask "what's on my calendar today?"

**Windows users:** Calendar connection is supported on Mac via Apple Calendar. This repo doesn't include Windows instructions yet.

If `/google-workspace-setup` already set your calendar source to Google, skip this guide — Dex reads Google Calendar through that connection. This page is only for reading Google events through the Mac Calendar app.

---

## How it works in one sentence

Dex reads your calendar from the **Calendar app** that came with your Mac. So you add your Google account to that app once, let Cursor use it, and Dex sees your meetings.

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

### Step 2: Let Cursor use your calendar

macOS only lets apps see your calendar if you allow it.

1. Open **System Settings** (or **System Preferences** on older macOS).
2. Go to **Privacy & Security** → **Calendars**.
3. Find **Cursor** in the list and turn it **On**.
4. Click **Cursor** and set access to **Full** (not "Add Only") so Dex can read your events.

The first time Cursor tries to read your calendar, macOS may show a popup: **"Cursor would like to access your calendars"**. Click **Allow**.

**Done.** Run `/daily-plan` or ask "what's on my calendar today?" — your Google meetings (including recurring ones) should show on the right days.

---

## If something's not working

| What you see | What to do |
|--------------|------------|
| **"Calendar access denied"** | Go to **System Settings** → **Privacy & Security** → **Calendars**, turn **Cursor** on, then click **Cursor** and set access to **Full** (not "Add Only"). Quit Cursor and open it again. |
| **No meetings or wrong dates for recurring events** | Make sure you did both steps above. If you installed Dex without running the installer (e.g. you installed Python packages yourself), open Terminal and run: `pip3 install --user pyobjc-framework-EventKit`, then restart Cursor. |
| **Calendar is empty or very slow** | Same as above: both setup steps, and if you didn't run the installer, run the `pip3 install` line above. |

---

## Known limitation: the VS Code extension can't use Apple Reminders

macOS grants calendar and reminders access **per app** — it looks at which app is asking. When Dex runs through the **Claude Code extension inside VS Code** (rather than from a normal terminal window), macOS never shows the permission popup to that process at all, and access granted to Terminal does **not** carry over. The result: Apple Reminders features (phone capture via a "Dex Inbox" list, "Dex Today" sync) are simply unavailable in that setup — not misconfigured, unavailable. Reinstalling or redoing the setup steps will not change this.

What to do instead:

- **Run Dex from a standalone terminal window** (Terminal.app, or another terminal app launched on its own). The permission popup appears there, and access works after you click Allow.
- **Or keep using the VS Code extension without Reminders features.** Dex skips them silently when access is unavailable — daily planning and reviews work normally without them.

This was verified directly (August 2026): the same check succeeds from Terminal.app, and fails from both VS Code's built-in terminal and the extension's own process — even after access was granted in Terminal.app first.

---

## Optional: Tell Dex which calendar is "work"

If you have several calendars and want Dex to focus on one (e.g. your work calendar) for faster answers, you can set it in **System/user-profile.yaml** under a `calendar` section with `work_calendar: "your.email@example.com"` (use the exact name as it appears in the Calendar app). You can skip this—Dex will still show your events without it.

---

## Summary

1. **Add Google to the Calendar app** — Calendar → Add Account → Google → sign in.
2. **Allow Cursor to access Calendars** — System Settings → Privacy & Security → Calendars → Cursor On, then click Cursor and choose **Full** access (not "Add Only").

After that, your Google Calendar meetings show up in Dex on the right days, including recurring events.
