param(
    [switch]$SendImmediately = $false,
    [switch]$ShowPreview = $true
)

# Meeting Details for Winholt Equipment
$title = "Winholt Equipment - Equipment Review | Mid Atlantic Machinery"
$startTime = [datetime]"2026-07-15 10:00:00"
$durationMinutes = 60
$requiredAttendees = @(
    "JPapeika@winholt.com",
    "mlines@winholt.com"
)
$optionalAttendees = @()
$location = "Winholt Equipment, 7028 Snowdrift Rd, Allentown, PA 18106"
$body = @"
Hi Jim and Malcolm,

As discussed, I'll stop by next Wednesday morning to discuss your capax opportunities and how Mid Atlantic Machinery can support Winholt Equipment.

Topics to cover:
• Robotic Laser Welding solutions
• Auto end deburring of cut tubes and profiles
• Service and support capabilities

Looking forward to meeting you, Jim, and learning more about your needs.

Best regards,
Chris Barsanti
Mid Atlantic Machinery
Cell: 610-256-0711
Email: cbarsanti@midatlanticmachinery.com
"@

# Load the generic create-meeting-invite.ps1 script
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
. "$scriptPath\create-meeting-invite.ps1" -Title $title -StartTime $startTime -DurationMinutes $durationMinutes -RequiredAttendees $requiredAttendees -OptionalAttendees $optionalAttendees -Location $location -Body $body -SendImmediately:$SendImmediately -ShowPreview:$ShowPreview
