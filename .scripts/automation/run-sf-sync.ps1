# run-sf-sync.ps1 -- Refresh the local Salesforce cache (read-only against Salesforce).
#
# Wraps `python .scripts/sf-pull-sync.py`. Pulls Chris-owned opportunities, quotes,
# tasks, events, accounts, contacts into .scripts/salesforce-data/. This ONLY reads
# from Salesforce -- it never writes back.
#
# Run manually:  . .scripts/automation/run-sf-sync.ps1
# Scheduled via: register-automation.ps1  (Dex-Weekly-SF-Sync, Mondays 06:00)
#
# Args: any extra args pass through to sf-pull-sync.py (e.g. --group frequent).

param([Parameter(ValueFromRemainingArguments = $true)] $PassThrough)

. (Join-Path $PSScriptRoot '_env.ps1')

Set-Location $DexVault
$script = Join-Path $DexVault '.scripts\sf-pull-sync.py'

# The Python script writes progress to stderr; under powershell.exe (5.1) with
# ErrorActionPreference=Stop that would falsely terminate. Trust the exit code instead.
$ErrorActionPreference = 'Continue'

Write-DexLog 'sf-sync' "START sf-pull-sync.py $PassThrough"
$output = & $DexPython $script @PassThrough 2>&1
$code = $LASTEXITCODE
$output | ForEach-Object { Write-DexLog 'sf-sync' ($_.ToString()) }
if ($code -ne 0) {
    Write-DexLog 'sf-sync' "ERROR: sf-pull-sync.py exited $code"
    exit 1
}
Write-DexLog 'sf-sync' "DONE"
