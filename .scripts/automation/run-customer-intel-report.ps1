# run-customer-intel-report.ps1 -- Generate the Customer Intelligence report.
#
# Wraps `python .scripts/customer-intel/generate-report.py`. Writes a markdown report
# to Inbox/Reports/Customer_Intel_YYYY-MM.md. Read-only against Salesforce.
#
# Run manually:  . .scripts/automation/run-customer-intel-report.ps1
# Scheduled via: register-automation.ps1
#   - Dex-Weekly-Lease-Alert   (Mondays 06:30, short look-back)
#   - Dex-Monthly-Intel-Report (1st of month 08:00, full report)
#
# Args: pass through to generate-report.py (e.g. --days 7 --months 6).

param([Parameter(ValueFromRemainingArguments = $true)] $PassThrough)

. (Join-Path $PSScriptRoot '_env.ps1')

Set-Location $DexVault
$script = Join-Path $DexVault '.scripts\customer-intel\generate-report.py'

# generate-report.py writes progress to stderr; under powershell.exe (5.1) with
# ErrorActionPreference=Stop that would falsely terminate. Trust the exit code instead.
$ErrorActionPreference = 'Continue'

Write-DexLog 'customer-intel' "START generate-report.py $PassThrough"
$output = & $DexPython $script @PassThrough 2>&1
$code = $LASTEXITCODE
$output | ForEach-Object { Write-DexLog 'customer-intel' ($_.ToString()) }
if ($code -ne 0) {
    Write-DexLog 'customer-intel' "ERROR: generate-report.py exited $code"
    exit 1
}
# generate-report.py prints the saved report path on stdout (last line).
$reportPath = ($output | Where-Object { "$_" -match 'Customer_Intel_.*\.md$' } | Select-Object -Last 1)
Write-DexLog 'customer-intel' "DONE -> $reportPath"
