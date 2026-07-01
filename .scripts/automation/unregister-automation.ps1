# unregister-automation.ps1 -- Remove Dex's scheduled data-refresh jobs.
#
# Tears down everything register-automation.ps1 created. Safe to run repeatedly.
#
# Usage:
#   pwsh .scripts/automation/unregister-automation.ps1

$ErrorActionPreference = 'Stop'

$names = @('Dex-Weekly-SF-Sync', 'Dex-Weekly-Lease-Alert', 'Dex-Monthly-Intel-Report')

foreach ($name in $names) {
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "[removed] $name"
    } else {
        Write-Host "[skip] $name (not registered)"
    }
}

Write-Host ''
Write-Host 'Dex automation removed. Local data and reports are untouched.'
