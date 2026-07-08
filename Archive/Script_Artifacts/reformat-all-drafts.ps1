Add-Type -AssemblyName System.Web

$outlook = New-Object -ComObject Outlook.Application
$namespace = $outlook.GetNamespace("MAPI")
$drafts = $namespace.GetDefaultFolder(16)

# Load signature HTML
$sigPath = "$env:APPDATA\Microsoft\Signatures\Standard (CBarsanti@midatlanticmachinery.com).htm"
$sigHtml = Get-Content $sigPath -Raw -Encoding UTF8

$items = $drafts.Items
$total = $items.Count
Write-Host "Found $total drafts to process..." -ForegroundColor Yellow

$updated = 0
$skipped = 0

# Collect items first to avoid COM collection mutation issues
$itemList = @()
foreach ($item in $items) { $itemList += $item }

foreach ($item in $itemList) {
    try {
        # Get plain text body - always reliable regardless of existing format
        $plainBody = $item.Body
        if ([string]::IsNullOrWhiteSpace($plainBody)) {
            Write-Host "SKIP (empty): $($item.Subject)" -ForegroundColor DarkGray
            $skipped++
            continue
        }

        # Strip common signature patterns to avoid duplication
        $plainBody = $plainBody -replace "(?s)Best Regards,.*", ""
        $plainBody = $plainBody -replace "(?s)Chris Barsanti[\s\S]*?Mid Atlantic Machinery[\s\S]*?$", ""
        $plainBody = $plainBody -replace "Chris Barsanti\s*\|?\s*Mid Atlantic Machinery", ""
        $plainBody = $plainBody -replace "Mid Atlantic Machinery\s*$", ""
        $plainBody = $plainBody.Trim()

        # Convert lines to Calibri 12pt HTML paragraphs
        $lines = $plainBody -split "`r`n|`n"
        $htmlLines = foreach ($line in $lines) {
            $escaped = [System.Web.HttpUtility]::HtmlEncode($line)
            if ([string]::IsNullOrWhiteSpace($line)) {
                "<p style='margin:0;font-family:Calibri,sans-serif;font-size:12pt'>&nbsp;</p>"
            } else {
                "<p style='margin:0;font-family:Calibri,sans-serif;font-size:12pt'>$escaped</p>"
            }
        }
        $bodyHtml = $htmlLines -join "`n"

        $fullHtml = @"
<html><body>
$bodyHtml
<p style='margin:0;font-family:Calibri,sans-serif;font-size:12pt'>&nbsp;</p>
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
Write-Host "Done: $updated updated, $skipped skipped/failed." -ForegroundColor Cyan
