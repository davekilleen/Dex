# Email Triage Flow — Import Guide

## Quick Import (2 minutes)

### Step 1: Download the Flow File

File: `email-triage-flow.zip`

Contains a ready-to-import Power Automate cloud flow.

### Step 2: Import into Power Automate

1. Go to **Power Automate** → https://make.powerautomate.com
2. Click **+ Create** → **Cloud flows** → **Automated cloud flow**
3. Name it: `Email Triage`
4. Select trigger: **When a new email arrives** (Outlook)
5. Click **Create** (you'll finish configuration after import)

**Then import the flow:**

1. In the same cloud flow, click the **...** menu
2. Select **Import** (or **Upload**)
3. Choose `email-triage-flow.zip`
4. Power Automate will load the flow definition

### Step 3: Connect Your Account

Power Automate will ask to authenticate:
- **Office 365 (Outlook)** — Authorize your account
- Click **Save** when complete

### Step 4: Test the Flow

1. Send yourself a test email with subject: `URGENT: Test`
2. The email should be **flagged as high importance**
3. Check your inbox — the flag should appear within 30 seconds

---

## What This Flow Does

**Triggers:** When a new email arrives in your Inbox

**Classification Logic:**

| Keyword/Sender | Category | Action |
|---|---|---|
| URGENT, CRITICAL, EMERGENCY, DOWN, OUTAGE | urgent | 🚩 Flag + High Priority |
| oncall@, alerts@, emergency@ | urgent | 🚩 Flag + High Priority |
| please review, feedback, approval, by EOD | follow_up | 🚩 Flag for Review |
| manager@, director@ | follow_up | 🚩 Flag for Review |
| FYI, announcement, schedule, holiday | fyi | ℹ️ No action |
| newsletter@, promotions@, noreply@ | ignore | 🗑️ Move to Spam |
| marketing@ | ignore | 🗑️ Move to Spam |

---

## Customizing the Flow

### Add a New Category Rule

To add more keywords for **urgent**:

1. In Power Automate, open the flow editor
2. Find the **Check_URGENT** condition
3. Click **Edit in advanced mode**
4. Add to the `or` expression:
   ```json
   {
     "contains": [
       "@outputs('Compose_email_text')",
       "YOUR_KEYWORD"
     ]
   }
   ```
5. Click **Save**

### Change Actions

To modify what happens when an email is flagged:

1. Find the **Apply_Triage** switch action
2. In the **Urgent** case, click **Flag_urgent_email**
3. Modify the action:
   - **Flag** — Change to different flag status
   - **Importance** — Change to low/normal/high
   - **Add action** — Send alert, create task, add label, etc.

---

## Common Customizations

### 1. Create Task for Urgent Emails

In the **Urgent** case, add a new action:
- Action: **Create a task (V3)** (Microsoft To Do or Project for the web)
- Title: `@{triggerOutputs()['headers']['subject']}`
- Bucket: `Urgent`
- Priority: `High`

### 2. Send Email Alert for Critical Messages

In the **Urgent** case, add:
- Action: **Send an email (V2)**
- To: `your-backup-email@example.com`
- Subject: `🚨 URGENT EMAIL: @{triggerOutputs()['headers']['subject']}`
- Body: `From: @{triggerOutputs()['headers']['from']}`

### 3. Add Categories to Follow-Up Emails

In the **Follow_Up** case, add:
- Action: **Create a task (V3)**
- Title: `Review: @{triggerOutputs()['headers']['subject']}`
- Bucket: `Requires Response`
- Due date: Tomorrow

### 4. Apply Outlook Categories

In any case, add:
- Action: **Update message in mailbox** (Outlook)
- Categories: `Urgent` (or `Action Required`, `FYI`, etc.)

---

## Troubleshooting

### Flow didn't import

**Error: "Invalid flow definition"**
- Delete the flow and try again
- Ensure you're using the latest version of Power Automate

### Emails not being flagged

**Check:**
1. Is the flow enabled? (Toggle on the main flow page)
2. Are keywords matching? (Test with exact case-sensitivity)
3. Check the run history for errors

**Debug:**
- Click on a failed run to see error details
- Add debugging: Insert **Compose** actions to see variables at each step

### Trigger not firing

**Ensure:**
1. Flow is created as **Automated cloud flow** (not Scheduled)
2. Trigger is **"When a new email arrives"** (Outlook)
3. You're signed in with the correct Microsoft account
4. Folder is set to **Inbox** (or your preferred folder)

### Too many emails getting flagged

**Solution:**
- Add more specific conditions (combine multiple keywords)
- Use sender-based rules (e.g., only from manager@)
- Add time-based checks (e.g., only during business hours)

---

## Advanced: Switch to Rules.json Logic

If you want to use the exact `rules.json` patterns from the Cloudflare Worker:

1. **Create a Compose action** for each category
2. **Compose 1 — Urgent Patterns:**
   ```
   @{concat(
     'URGENT|CRITICAL|EMERGENCY|DOWN|OUTAGE|'
   )}
   ```
3. **Condition:** Check if email text contains any of these patterns
4. Repeat for follow_up, fyi, ignore

Or use the **Cloudflare Worker** endpoint instead (see `README.md`).

---

## Differences: Flow vs Cloudflare Worker

| Feature | Flow | Worker |
|---------|------|--------|
| **Setup time** | 2 min | 15 min |
| **Speed** | 2-3s | <10ms |
| **Cost** | Included | Free (100k/day) |
| **Customization** | UI drag-drop | JSON rules |
| **Reusable** | This flow only | Any system |
| **Scale** | ~500k/month quota | Unlimited |

---

## Next Steps

1. **Import the flow** (follow Step 1-3 above)
2. **Test with sample emails** containing keywords
3. **Customize actions** to fit your workflow
4. **Adjust rules** based on what you see
5. **(Optional)** Create subflow for reuse across multiple flows

---

## Support

**Questions?** See the full documentation:
- `README.md` — API reference and deployment
- `POWER_AUTOMATE.md` — All implementation options
- `INTEGRATION.md` — Integration with Gmail, Outlook, Zapier

