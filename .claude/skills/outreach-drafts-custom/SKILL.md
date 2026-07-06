---
name: outreach-drafts-custom
description: Generate targeted Outlook draft emails for sales events and promotions — pulls matching contacts from Salesforce, writes personalized emails, and pushes them to Outlook Drafts via PowerShell.
---

# Outreach Drafts

Generate a batch of personalized outreach emails and push them directly to your Outlook Drafts folder in one shot. Works for events, promotions, availability alerts, product launches, or any targeted campaign.

## Process

### Step 1: Define the Campaign

Ask the user:
1. **What's the event or promotion?** (e.g., "Press Brake Training Course, August 26 at MAM showroom")
2. **Who should receive it?** Describe the targeting criteria — examples:
   - "Accounts with open press brake deals"
   - "TRUMPF customers and prospects"
   - "Anyone I've talked to about lasers in the last 6 months"
   - "All good customers — relationship outreach"
3. **Any specific accounts or contacts to include or exclude?**

### Step 2: Pull Matching Accounts from Salesforce

Use Salesforce MCP tools to find matching contacts based on the criteria:
- `get_opportunities` (salesforce-remote) — filter by account name or stage
- `search_accounts` (salesforce-remote) — get contacts for specific accounts
- `get_account_contacts` (salesforce-remote) — get all contacts under an account
- `search_contacts` (salesforce-remote) — search by name or role
- `sf_get_recent_activity` (local salesforce MCP) — find accounts with recent activity on relevant topics
- `sf_search_assets` (local salesforce MCP) — search assets across all accounts by machine type, builder/manufacturer, sale-or-lease status, or other criteria

Build a tiered target list:
- **Tier 1** — Actively in-market (open opp matching the topic, hot stage)
- **Tier 2** — Have discussed it / have related equipment / recent signals
- **Tier 3** — Good customers / strategic relationship touches

For each contact, collect: Name, Email, Account, relevant context (deal stage, what they're working on).

### Step 3: Draft Personalized Emails

Write one email per contact. Each email should:
- Open with a personal reference (recent call, active deal, tooling discussion, etc.)
- State the event/offer clearly and concisely
- Include a specific call to action (hold spots, reply to confirm, call this week)
- Sign off as Chris Barsanti, Mid Atlantic Machinery

Vary the opening line per contact — never send identical emails to different people.

Show the user the draft list before generating the script. Let them approve, remove contacts, or tweak language.

### Step 4: Generate and Run the PowerShell Script

Generate a `.ps1` script at `.scripts/outreach-[event-slug]-[YYYY-MM-DD].ps1` using this pattern:

```powershell
$outlook = New-Object -ComObject Outlook.Application

$emails = @(
    @{
        To      = "contact@company.com"
        CC      = "optional@company.com"   # omit if not needed
        Subject = "Subject line here"
        Body    = "Email body here.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    # ... more emails
)

$created = 0
$skipped = 0

foreach ($email in $emails) {
    try {
        $mail = $outlook.CreateItem(0)
        $mail.To = $email.To
        if ($email.CC) { $mail.CC = $email.CC }
        $mail.Subject = $email.Subject
        $mail.Body = $email.Body
        $mail.Save()
        Write-Host "OK: $($email.Subject)" -ForegroundColor Green
        $created++
    } catch {
        Write-Host "FAIL: $($email.Subject) - $_" -ForegroundColor Red
        $skipped++
    }
}

Write-Host ""
Write-Host "Done: $created drafts created, $skipped failed." -ForegroundColor Cyan
```

**Critical rules for the script:**
- Use only ASCII characters — no em dashes (—), smart quotes, or Unicode. Use plain hyphens (-) instead.
- Use `"string with `n for newlines"` syntax for email bodies — NOT PowerShell here-strings (`@"..."@`) which cause encoding issues.
- Do NOT use `-File` to run the script (spawns a child process that can't access Outlook COM).

**Tell the user to run it by dot-sourcing in a regular PowerShell window:**
```
. "c:\Users\Chris\Documents\GitHub\dex\.scripts\outreach-[event-slug].ps1"
```

**Requirements before running:**
- Classic Outlook desktop app must be open
- PowerShell must be opened normally (NOT as Administrator)
- Use dot-source syntax (`. ` with a space) not `powershell -File`

### Step 5: Flag Missing Contacts

If any target accounts don't have an email address in Salesforce, note them clearly:
- List them at the end of the draft review
- In the script, use `NEEDEMAIL@[company].com` as a placeholder and add a NOTE in the email body
- Remind the user to update before sending

## Notes

- Scripts are saved to `.scripts/` and can be re-run or modified anytime
- One script per campaign — keeps outreach organized and auditable
- The `-custom` suffix protects this skill from Dex updates
- To edit this skill: `.claude/skills/outreach-drafts-custom/SKILL.md`
- **Prefer `email-drafts-custom`** for most campaigns now — it queues drafts in the same review dashboard as task-sourced outreach (edit, then push as an Outlook draft or send directly, per email) instead of generating a one-off script. Use this skill's standalone-script path only for a quick one-off push with no review step needed.
