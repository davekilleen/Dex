# register-automation.ps1 -- Install Dex's scheduled data-refresh jobs on Windows.
#
# Replaces the macOS launchd assumption with Windows Task Scheduler. Registers three
# idempotent tasks (re-running overwrites cleanly). Each runs a read-only Python job
# under the current user, ONLY while logged on (InteractiveToken -- the Windows
# equivalent of launchd's "Aqua" session guard). No elevation required.
#
#   Dex-Weekly-SF-Sync        Mondays 06:00   refresh local Salesforce cache
#   Dex-Weekly-Lease-Alert    Mondays 06:30   short-lookback lease-expiry report
#   Dex-Monthly-Intel-Report  1st @ 08:00     full customer-intelligence report
#
# GUARDRAIL: every job only REFRESHES DATA and GENERATES REPORTS. None of them send
# email or write to Salesforce. All outreach stays draft-and-approve; activity logging
# stays manual via /pipeline-review.
#
# Usage:
#   pwsh .scripts/automation/register-automation.ps1            # install / update
#   pwsh .scripts/automation/register-automation.ps1 -Status    # show registered tasks
#   pwsh .scripts/automation/register-automation.ps1 -WhatIf    # print without registering

[CmdletBinding()]
param(
    [switch]$Status,
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'
$AutoDir = $PSScriptRoot

if ($Status) {
    Get-ScheduledTask -TaskName 'Dex-*' -ErrorAction SilentlyContinue |
        Select-Object TaskName, State,
            @{ N = 'NextRun'; E = { (Get-ScheduledTaskInfo $_.TaskName).NextRunTime } },
            @{ N = 'LastRun'; E = { (Get-ScheduledTaskInfo $_.TaskName).LastRunTime } } |
        Format-Table -AutoSize
    return
}

$ns = 'http://schemas.microsoft.com/windows/2004/02/mit/task'

function New-TaskXml {
    param(
        [string]$Description,
        [string]$ScriptFile,     # wrapper .ps1 under .scripts/automation
        [string]$ScriptArgs,     # extra args for the wrapper (may be empty)
        [string]$TriggerXml,     # ScheduleByWeek / ScheduleByMonth fragment
        [string]$StartBoundary
    )
    $wrapper = Join-Path $AutoDir $ScriptFile
    $argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$wrapper`""
    if ($ScriptArgs) { $argLine += " $ScriptArgs" }
    # Escape XML-significant characters in the argument line.
    $argLine = $argLine.Replace('&', '&amp;').Replace('<', '&lt;').Replace('>', '&gt;')
    @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="$ns">
  <RegistrationInfo>
    <Description>$Description</Description>
    <Author>Dex</Author>
    <URI>\Dex\$($ScriptFile)</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$StartBoundary</StartBoundary>
      <Enabled>true</Enabled>
      $TriggerXml
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>$argLine</Arguments>
    </Exec>
  </Actions>
</Task>
"@
}

$weekly = @'
      <ScheduleByWeek>
        <DaysOfWeek><Monday /></DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
'@

$monthly = @'
      <ScheduleByMonth>
        <DaysOfMonth><Day>1</Day></DaysOfMonth>
        <Months><January /><February /><March /><April /><May /><June /><July /><August /><September /><October /><November /><December /></Months>
      </ScheduleByMonth>
'@

$jobs = @(
    @{ Name = 'Dex-Weekly-SF-Sync'
       Desc = 'Refresh local Salesforce cache (read-only). Mondays 06:00.'
       File = 'run-sf-sync.ps1'; Args = ''
       Trigger = $weekly; Start = 'T06:00:00' }
    @{ Name = 'Dex-Weekly-Lease-Alert'
       Desc = 'Short-lookback customer-intelligence / lease-expiry report. Mondays 06:30.'
       File = 'run-customer-intel-report.ps1'; Args = '--days 7 --months 6'
       Trigger = $weekly; Start = 'T06:30:00' }
    @{ Name = 'Dex-Monthly-Intel-Report'
       Desc = 'Full customer-intelligence report to Inbox/Reports. 1st of month 08:00.'
       File = 'run-customer-intel-report.ps1'; Args = ''
       Trigger = $monthly; Start = 'T08:00:00' }
)

$dateStr = (Get-Date -Format 'yyyy-MM-dd')

foreach ($j in $jobs) {
    $xml = New-TaskXml -Description $j.Desc -ScriptFile $j.File -ScriptArgs $j.Args `
        -TriggerXml $j.Trigger -StartBoundary ("{0}{1}" -f $dateStr, $j.Start)

    if ($WhatIf) {
        Write-Host "---- $($j.Name) ----"
        Write-Host $xml
        continue
    }

    Register-ScheduledTask -TaskName $j.Name -Xml $xml -Force | Out-Null
    Write-Host "[ok] Registered $($j.Name)"
}

if (-not $WhatIf) {
    Write-Host ''
    Write-Host 'Done. Verify with:  Get-ScheduledTask -TaskName Dex-*'
    Write-Host 'Or:                 pwsh .scripts/automation/register-automation.ps1 -Status'
    Write-Host 'Teardown:           pwsh .scripts/automation/unregister-automation.ps1'
}
