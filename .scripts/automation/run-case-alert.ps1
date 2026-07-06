# run-case-alert.ps1 -- Daily check for new/updated Salesforce Cases on Chris's accounts.
#
# Wraps `python .scripts/case-alert.py`. Read-only against Salesforce: pulls open Cases
# on owned accounts, diffs against yesterday's snapshot, and flags:
#   - Cases that are brand new
#   - Cases whose Status or Priority changed
#
# On a hit, writes Inbox/Alerts/case-alert-YYYY-MM-DD.md AND pops a Windows toast
# notification (balloon tip via System.Windows.Forms -- no extra module required).
#
# Run manually:  . .scripts/automation/run-case-alert.ps1
# Scheduled via: register-automation.ps1  (Dex-Daily-Case-Alert, daily 07:15)

. (Join-Path $PSScriptRoot '_env.ps1')

Set-Location $DexVault
$script = Join-Path $DexVault '.scripts\case-alert.py'

$ErrorActionPreference = 'Continue'

Write-DexLog 'case-alert' 'START case-alert.py'
$output = & $DexPython $script 2>&1
$code = $LASTEXITCODE
$output | ForEach-Object { Write-DexLog 'case-alert' ($_.ToString()) }

if ($code -ne 0) {
    Write-DexLog 'case-alert' "ERROR: case-alert.py exited $code"
    exit 1
}

$summaryLine = ($output | Where-Object { $_ -match '^ALERT:' } | Select-Object -First 1)
if ($summaryLine) {
    Write-DexLog 'case-alert' "Firing toast: $summaryLine"
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $notify = New-Object System.Windows.Forms.NotifyIcon
        $notify.Icon = [System.Drawing.SystemIcons]::Information
        $notify.Visible = $true
        $notify.BalloonTipTitle = 'Dex — Service Case Alert'
        $notify.BalloonTipText = $summaryLine -replace '^ALERT:\s*', ''
        $notify.ShowBalloonTip(15000)
        Start-Sleep -Seconds 16
        $notify.Dispose()
    } catch {
        Write-DexLog 'case-alert' "WARN: toast notification failed: $_"
    }
} else {
    Write-DexLog 'case-alert' 'No alert-worthy changes today'
}

Write-DexLog 'case-alert' 'DONE'
