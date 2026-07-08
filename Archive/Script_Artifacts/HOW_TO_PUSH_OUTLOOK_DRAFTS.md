# How to Push Email Drafts to Outlook

## Quick Start

### Option 1: Automatic (Recommended)

1. **Open Outlook** (classic Outlook, not web)
2. **Open PowerShell** (NOT as admin)
3. **Run this command:**
   ```powershell
   . "C:\Users\Chris\Documents\GitHub\dex\.scripts\push-outreach-to-outlook.ps1"
   ```
4. **Check your Outlook Drafts folder** — all emails will appear there

---

### Option 2: Manual Copy-Paste

Open `Inbox\Outreach_Drafts_Week_July_7-11_2026.md` and manually copy each email template into a new Outlook draft.

---

## What Gets Created

The PowerShell script creates **8 key emails** as Outlook drafts:

✅ **URGENT** (Monday AM):
- Aaron Fry — Myers EPS (Cidan Folder)

✅ **HIGH PRIORITY**:
- Kelly Iron Works (Padraig)
- Gambone Steel (Ralph) — ALLtra Plasma
- Mark B — Plasma upgrade
- Roy Shelton — Reconnect
- Whitney — Press brake training
- Vito — Plasma upgrade
- Todd — Plasma upgrade

---

## After Pushing to Outlook

1. **Review each draft** in Outlook Drafts folder
2. **Personalize with Salesforce data:**
   - Company names (should auto-fill)
   - Quote numbers
   - Machine types
   - Specific opportunity details
3. **Update contact emails** if different from script
4. **Schedule sending** based on priority:
   - 🔴 Monday AM: Aaron Fry, Cidan calls
   - 🔥 Mon-Wed: High priority (Hanwha, Hadco, Precision)
   - ✅ Tue-Thu: Medium priority sweep

---

## Customizing the Script

To add more emails, edit `push-outreach-to-outlook.ps1`:

1. Add a new block in the `$emails` array:
   ```powershell
   @{
       To      = "email@company.com"
       Subject = "Your Subject"
       Body    = @"
   Your email body here
   "@
   },
   ```

2. Re-run the script (Outlook creates new drafts)

---

## Troubleshooting

**"Cannot find Outlook"**
- Make sure Outlook (classic) is open before running the script
- PowerShell must NOT be run as admin

**"Script cannot be run"**
- Run: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
- Then re-run the push script

**Emails not appearing**
- Check Outlook Drafts folder (may need to refresh)
- Check PowerShell output for error messages

---

## Full Email List

For all 41+ email templates (including P1 tasks, ALLtra Randy campaign, event outreach), see:
- **Primary file:** `Inbox\Outreach_Drafts_Week_July_7-11_2026.md`

This script covers the top 8 priority emails. To push additional emails, edit the `$emails` array or run the script multiple times with different email sets.
