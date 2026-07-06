# Push queued email drafts to Outlook via COM automation.
# Reads a JSON array of {id, to, cc, subject, body, sendMode} from -DraftsFile,
# creates one Outlook mail item per entry, saves it as a draft (sendMode=draft)
# or sends it immediately (sendMode=send), and writes a JSON results array to stdout.
#
# Usage:
#   powershell -NoProfile -Command "& 'C:\path\push-to-outlook.ps1' -DraftsFile 'C:\path\batch.json'"
#
# Requirements: classic Outlook desktop app must be open.

param(
    [Parameter(Mandatory = $true)]
    [string]$DraftsFile
)

$ErrorActionPreference = "Stop"

$results = @()

try {
    $json = Get-Content -Path $DraftsFile -Raw -Encoding UTF8
    $items = $json | ConvertFrom-Json
} catch {
    Write-Output (@{ error = "Failed to read or parse DraftsFile: $_" } | ConvertTo-Json)
    exit 1
}

# ConvertFrom-Json returns a single object (not an array) when the file has one item.
if ($items -isnot [System.Array]) {
    $items = @($items)
}

try {
    $outlook = New-Object -ComObject Outlook.Application
} catch {
    foreach ($item in $items) {
        $results += [ordered]@{ id = $item.id; status = "failed"; error = "Could not connect to Outlook: $_" }
    }
    Write-Output ($results | ConvertTo-Json)
    exit 1
}

foreach ($item in $items) {
    try {
        $mail = $outlook.CreateItem(0)
        $mail.To = $item.to
        if ($item.cc) { $mail.CC = $item.cc }
        $mail.Subject = $item.subject
        $mail.Body = $item.body

        if ($item.sendMode -eq "send") {
            $mail.Send()
            $results += [ordered]@{ id = $item.id; status = "sent"; error = $null }
        } else {
            $mail.Save()
            $results += [ordered]@{ id = $item.id; status = "pushed_draft"; error = $null }
        }
    } catch {
        $results += [ordered]@{ id = $item.id; status = "failed"; error = "$_" }
    }
}

Write-Output ($results | ConvertTo-Json)
