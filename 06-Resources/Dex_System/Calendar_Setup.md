# Connect Google Calendar to Dex (Mac)

This guide is for **Mac users** who use **Google Calendar** and want Dex to show their real meetings—including recurring ones like weekly 1:1s—when they run `/daily-plan` or ask "what's on my calendar today?"

**Windows users:** Calendar connection is supported on Mac via Apple Calendar. This repo doesn't include Windows instructions yet.

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

The first time Cursor tries to read your calendar, macOS may show a popup: **"Cursor would like to access your calendars"**. Click **Allow**.

**Done.** Run `/daily-plan` or ask "what's on my calendar today?" — your Google meetings (including recurring ones) should show on the right days.

---

## If something's not working

| What you see | What to do |
|--------------|------------|
| **"Calendar access denied"** | Go to **System Settings** → **Privacy & Security** → **Calendars** and turn **Cursor** on. Then quit Cursor and open it again. |
| **No meetings or wrong dates for recurring events** | Make sure you did both steps above. If you installed Dex without running the installer (e.g. you installed Python packages yourself), open Terminal and run: `pip3 install --user pyobjc-framework-EventKit`, then restart Cursor. |
| **Calendar is empty or very slow** | Same as above: both setup steps, and if you didn't run the installer, run the `pip3 install` line above. |

---

## Optional: Tell Dex which calendar is "work"

If you have several calendars and want Dex to focus on one (e.g. your work calendar) for faster answers, you can set it in **System/user-profile.yaml** under a `calendar` section with `work_calendar: "your.email@company.com"` (use the exact name as it appears in the Calendar app). You can skip this—Dex will still show your events without it.

---

## Summary

1. **Add Google to the Calendar app** — Calendar → Add Account → Google → sign in.
2. **Allow Cursor to access Calendars** — System Settings → Privacy & Security → Calendars → Cursor On.

After that, your Google Calendar meetings show up in Dex on the right days, including recurring events.
