param(
    [string]$Title = "Meeting",
    [datetime]$StartTime = (Get-Date).AddDays(1),
    [int]$DurationMinutes = 60,
    [string[]]$RequiredAttendees = @(),
    [string[]]$OptionalAttendees = @(),
    [string]$Location = "",
    [string]$Body = "",
    [switch]$SendImmediately = $false,
    [switch]$ShowPreview = $true
)

function Create-OutlookMeetingInvite {
    param(
        [string]$Title,
        [datetime]$StartTime,
        [int]$DurationMinutes,
        [string[]]$RequiredAttendees,
        [string[]]$OptionalAttendees,
        [string]$Location,
        [string]$Body,
        [bool]$SendNow,
        [bool]$Preview
    )

    try {
        # Create Outlook COM object
        Write-Host "Connecting to Outlook..." -ForegroundColor Cyan
        $outlook = New-Object -ComObject Outlook.Application
        $namespace = $outlook.GetNamespace("MAPI")

        # Create a new meeting/appointment item
        # Type 1 = olAppointmentItem
        $meetingItem = $outlook.CreateItem(1)

        # Set basic properties
        $meetingItem.Subject = $Title
        $meetingItem.Start = $StartTime
        $meetingItem.Duration = $DurationMinutes
        $meetingItem.Body = $Body
        if ($Location) {
            $meetingItem.Location = $Location
        }

        # Add required attendees
        $recipients = $meetingItem.Recipients
        foreach ($email in $RequiredAttendees) {
            if ($email) {
                Write-Host "Adding required: $email" -ForegroundColor Green
                $recipients.Add($email) | Out-Null
                $recipient = $recipients.Item($recipients.Count)
                $recipient.Type = 1  # 1 = olRequired
                $recipient.Resolve()
            }
        }

        # Add optional attendees
        foreach ($email in $OptionalAttendees) {
            if ($email) {
                Write-Host "Adding optional: $email" -ForegroundColor Yellow
                $recipients.Add($email) | Out-Null
                $recipient = $recipients.Item($recipients.Count)
                $recipient.Type = 2  # 2 = olOptional
                $recipient.Resolve()
            }
        }

        # Show preview if requested
        if ($Preview) {
            Write-Host "`n=== MEETING INVITE PREVIEW ===" -ForegroundColor Cyan
            Write-Host "Title: $Title"
            Write-Host "Date: $($StartTime.ToString('dddd, MMMM dd, yyyy'))"
            Write-Host "Time: $($StartTime.ToString('h:mm tt')) - $($StartTime.AddMinutes($DurationMinutes).ToString('h:mm tt'))"
            if ($Location) {
                Write-Host "Location: $Location"
            }
            Write-Host "Required Attendees: $($RequiredAttendees.Count)"
            $RequiredAttendees | ForEach-Object { Write-Host "  - $_" }
            if ($OptionalAttendees.Count -gt 0) {
                Write-Host "Optional Attendees: $($OptionalAttendees.Count)"
                $OptionalAttendees | ForEach-Object { Write-Host "  - $_" }
            }
            if ($Body) {
                Write-Host "Description: $($Body.Substring(0, [Math]::Min(100, $Body.Length)))..."
            }
            Write-Host "==============================`n" -ForegroundColor Cyan
        }

        # Save as draft or send
        if ($SendNow) {
            Write-Host "Sending meeting invite..." -ForegroundColor Green
            $meetingItem.Send()
            Write-Host "Meeting invite sent successfully!" -ForegroundColor Green
        } else {
            Write-Host "Saving meeting invite as draft..." -ForegroundColor Green
            $meetingItem.Save()
            Write-Host "Meeting invite saved to Drafts. Review and send from Outlook." -ForegroundColor Green
        }

        return $true
    }
    catch {
        Write-Host "ERROR: $_" -ForegroundColor Red
        return $false
    }
}

# Execute the function
$success = Create-OutlookMeetingInvite -Title $Title -StartTime $StartTime -DurationMinutes $DurationMinutes -RequiredAttendees $RequiredAttendees -OptionalAttendees $OptionalAttendees -Location $Location -Body $Body -SendNow $SendImmediately -Preview $ShowPreview

if ($success) {
    exit 0
} else {
    exit 1
}
