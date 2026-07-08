# Winholt Equipment - Meeting Invite Example

**Status:** Example/Template  
**Date Created:** 2026-07-07  
**Related Branch:** `claude/winholt-meeting-invite-12y163`

## Context

This file demonstrates the new `/outlook-meeting-invite` skill for creating and sending Outlook calendar invites through Dex.

## Meeting Details

**Company:** Winholt Equipment  
**Location:** Bensalem, PA  
**Type:** Equipment Demo & Needs Assessment

## Attendees (from Salesforce)

### Required
- **Steve Malaro** (Equipment Manager) — steve.malaro@winholt.com
- **John Winholt** (Owner) — john@winholt.com

### Optional
- Your Salesforce rep if applicable

## How to Create the Invite

### Using the Skill

```
/outlook-meeting-invite

Prompt: Create a meeting invite for Winholt Equipment

The skill will:
1. Search Salesforce for Winholt Equipment account
2. Extract all contacts and their emails
3. Pull recent communication history from vault
4. Generate a list of suggested attendees
5. Ask for date, time, and location
6. Create PowerShell script to generate the Outlook invite
7. Send or save as draft
```

### Manual PowerShell (Advanced)

If you want to create the invite directly via PowerShell:

```powershell
# PowerShell example
$meeting = @{
    Title = "Winholt Equipment - Equipment Demo & Needs Assessment"
    StartTime = [datetime]"2026-07-15 14:00"  # Next Tuesday 2:00 PM
    DurationMinutes = 60
    RequiredAttendees = @("steve.malaro@winholt.com", "john@winholt.com")
    Location = "Winholt Equipment - Bensalem, PA"
    Body = @"
Hi Steve and John,

Following up on our recent conversations about equipment modernization.
I'd like to schedule a time to discuss your current equipment situation
and how we might help optimize your production workflow.

Looking forward to connecting.

Best regards,
Chris Barsanti
Mid Atlantic Machinery
"@
}

# Run the script
. ".scripts\create-meeting-invite.ps1" @meeting -ShowPreview -SendImmediately:$false
```

## Technical Stack

- **Skill Definition:** `.claude/skills/outlook-meeting-invite/SKILL.md`
- **PowerShell Helper:** `.scripts/create-meeting-invite.ps1`
- **Data Gatherer:** `.scripts/gather-meeting-data.py`
- **Integration Points:**
  - Salesforce MCP (for account/contact lookup)
  - Vault search (for context and recent activity)
  - Outlook COM object (for calendar invite creation)

## Features

✅ Search Salesforce for attendees  
✅ Extract email addresses from person pages  
✅ Find recent communication history  
✅ Support for required and optional attendees  
✅ Create as draft or send immediately  
✅ Timezone-aware scheduling  
✅ Location and description support  
✅ Auto-logging to vault and Salesforce (future)

## Next Steps

1. Run `/outlook-meeting-invite`
2. Follow prompts to define meeting details
3. Review attendee list
4. Select date/time
5. Confirm creation
6. Check Outlook Drafts or sent items

## Related Files

- Planning notes: `Planning/Week_Priorities.md`
- Winholt tasks: `Planning/Tasks.md`
- Equipment: Any project pages with Winholt mentioned

---

*Created as part of the Winholt meeting invite feature implementation.*
