$outlook = New-Object -ComObject Outlook.Application
$namespace = $outlook.GetNamespace("MAPI")
$drafts = $namespace.GetDefaultFolder(16) # 16 = olFolderDrafts

# Load signature HTML
$sigPath = "$env:APPDATA\Microsoft\Signatures\Standard (CBarsanti@midatlanticmachinery.com).htm"
$sigHtml = Get-Content $sigPath -Raw -Encoding UTF8

# Get today's drafts that contain our marker
$today = (Get-Date).Date
$items = $drafts.Items
$items.Sort("[ReceivedTime]", $true)

$updated = 0
$skipped = 0

foreach ($item in $items) {
    try {
        # Only process items saved today with our plain text signature marker
        $createdDate = $item.CreationTime.Date
        if ($createdDate -ne $today) { continue }
        if ($item.Body -notmatch "Chris Barsanti\s*\|?\s*Mid Atlantic Machinery") { continue }

        # Get plain text body, strip our simple text signature
        $plainBody = $item.Body
        $plainBody = $plainBody -replace "Chris Barsanti\s*\|?\s*Mid Atlantic Machinery\s*", ""
        $plainBody = $plainBody.Trim()

        # Convert each line to HTML paragraph in Calibri 11pt
        $lines = $plainBody -split "`r`n|`n"
        $htmlLines = foreach ($line in $lines) {
            $escaped = [System.Web.HttpUtility]::HtmlEncode($line)
            if ([string]::IsNullOrWhiteSpace($line)) {
                "<p style='margin:0;font-family:Calibri,sans-serif;font-size:11pt'>&nbsp;</p>"
            } else {
                "<p style='margin:0;font-family:Calibri,sans-serif;font-size:11pt'>$escaped</p>"
            }
        }
        $bodyHtml = $htmlLines -join "`n"

        # Build full HTML body: message + blank line + signature
        $fullHtml = @"
<html><body>
$bodyHtml
<p style='margin:0;font-family:Calibri,sans-serif;font-size:11pt'>&nbsp;</p>
$sigHtml
</body></html>
"@

        $item.HTMLBody = $fullHtml
        $item.Save()
        Write-Host "OK: $($item.Subject)" -ForegroundColor Green
        $updated++
    } catch {
        Write-Host "FAIL: $($item.Subject) - $_" -ForegroundColor Red
        $skipped++
    }
}

Write-Host ""
Write-Host "Done: $updated updated, $skipped failed." -ForegroundColor Cyan
