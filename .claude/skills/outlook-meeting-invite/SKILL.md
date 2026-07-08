---
name: outlook-meeting-invite
description: Create and send Outlook calendar invites from meeting details, with attendee lookup from Salesforce and email search.
---

# Create Outlook Meeting Invite

Use this skill when you need to create and send a calendar invite for a meeting.

## Process

### Step 1: Define the Meeting

Ask the user for (if not provided):
1. **Meeting title** (e.g., "Winholt Equipment - Equipment Demo")
2. **Date and time** (e.g., "Next Tuesday, 2:00 PM")
3. **Duration** (default 1 hour if not specified)
4. **Location** (optional, can be virtual/Zoom link)
5. **Meeting description/agenda** (optional)

### Step 2: Search for Attendees

Use multiple sources to build the attendee list:

**From Salesforce:**
- `search_accounts` — find the company by name
- `get_account_contacts` — get all contacts for that account
- `get_account_details` — get account info for context
- `search_contacts` — search by name if needed

**From Email/Vault:**
- Use grep/find to search `Inbox/Meetings/`, `People/`, and `Projects/` for references to the contact/company
- Look for recent emails mentioning the contact
- Extract email addresses from person pages (`People/Internal/` or `People/External/`)

**Build attendee list with:**
- Full name
- Email address
- Role/title (from Salesforce)
- Account name

Ask the user to confirm the attendee list before proceeding.

### Step 3: Create Calendar Invite Data

Generate a structured meeting invite with:
- Title
- Date/time (in ISO format)
- Duration (minutes)
- Attendees (name, email)
- Description
- Location
- Organizer (barsantc@gmail.com)

### Step 4: Generate PowerShell Script

Create `.scripts/create-meeting-invite-YYYYMMDD.ps1` that:
1. Connects to Outlook COM object
2. Creates a new meeting item (APPOINTMENT or MEETING_REQUEST)
3. Sets all properties (title, time, attendees, body, location)
4. Adds attendees via the Recipients collection
5. Sets RequiredAttendees vs. OptionalAttendees based on user input
6. Saves to Drafts or sends directly (user choice)

### Step 5: Execute & Confirm

Run the PowerShell script with instructions:
```powershell
. ".scripts\create-meeting-invite-YYYYMMDD.ps1"
```

Display what will be created:
- Title
- Date/Time
- Attendees (required + optional)
- Location
- Description preview

Offer options:
- [ ] Create as draft in Outlook (review first)
- [ ] Send immediately (requires confirmation)
- [ ] Schedule for later

### Step 6: Capture in Vault

After creation:
- Create/update meeting note: `Inbox/Meetings/YYYY-MM-DD - Meeting Title.md`
- Update attendee person pages with meeting reference
- Log activity in Salesforce if account/contact related
- Link to related project/opportunity in vault

## Example Flow

**User:** "Create a meeting with Winholt Equipment for next week, discuss their equipment demo needs"

**Claude:**
1. Searches Salesforce for Winholt Equipment account
2. Finds contacts: Steve Malaro, John Doe
3. Searches email for recent Winholt conversations
4. Proposes: "I found 3 contacts at Winholt. Here's who I'll invite..."
5. Asks for date/time confirmation
6. Generates PowerShell script
7. Shows preview of what will be created
8. Executes when user confirms
9. Updates vault with meeting note

## Technical Details

### PowerShell Template Structure

```powershell
# Create new Outlook session
$outlook = New-Object -ComObject Outlook.Application
$namespace = $outlook.GetNamespace("MAPI")

# Create meeting request
$meetingItem = $outlook.CreateItem(1) # 1 = appointment

# Set properties
$meetingItem.Subject = $title
$meetingItem.Start = [datetime]$startTime
$meetingItem.Duration = $durationMinutes
$meetingItem.Location = $location
$meetingItem.Body = $description

# Add attendees
$recipients = $meetingItem.Recipients
foreach ($attendee in $attendees) {
    $recipients.Add($attendee.Email) | Out-Null
    $recipient = $recipients.Item($recipients.Count)
    $recipient.Type = 1 # 1=Required, 2=Optional
    $recipient.Resolve()
}

# Save or send
$meetingItem.Save()  # Draft
# OR $meetingItem.Send()  # Send immediately
```

### Attendee Format

```
Name: John Doe
Email: john.doe@winholt.com
Type: Required
Account: Winholt Equipment
Title: Operations Manager
```

## Notes

- Search Salesforce first, then vault, then ask user
- Always show attendee list for confirmation
- Default to Draft mode (safer than auto-send)
- Log meeting creation to related Salesforce account/opportunity
- Support both required and optional attendees
- Handle timezone awareness (Outlook vs. system)

## See Also

- `/email-queue-manager` — for email outreach workflow
- `/meeting-prep` — for pre-meeting preparation
- `/process-meetings` — for capturing meeting notes
