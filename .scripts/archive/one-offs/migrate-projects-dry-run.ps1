# migrate-projects-dry-run.ps1
# Dry-run: shows proposed account-centric restructure WITHOUT moving any files.
# Review the output, fix any flagged issues, then run migrate-projects-execute.ps1

$projectsRoot = "C:\Users\Chris\Documents\GitHub\dex\Projects"
$outputCsv    = "C:\Users\Chris\Documents\GitHub\dex\.scripts\migration-plan.csv"

# ── helpers ──────────────────────────────────────────────────────────────────

function Get-FrontmatterValue($content, $key) {
    if ($content -match "(?m)^${key}:\s*(.+)$") { return $matches[1].Trim() } else { return $null }
}

function Get-MarkdownField($content, $label) {
    if ($content -match "\*\*${label}:\*\*\s*(.+)") { return $matches[1].Trim() } else { return $null }
}

# Extract account name from **Account:** field, stripping WikiLink syntax
function Get-AccountName($content) {
    $raw = Get-MarkdownField $content "Account"
    if (-not $raw) { return $null }
    # [[Account_Name|Display Name]] → Display Name
    if ($raw -match '\[\[.+\|(.+)\]\]') { return $matches[1].Trim() }
    # [[Account_Name]] → Account_Name (replace underscores)
    if ($raw -match '\[\[(.+)\]\]')     { return $matches[1].Replace('_', ' ').Trim() }
    return $raw
}

# Sanitize a string for use as a Windows folder/file name
function Sanitize-Name($name) {
    $name = $name -replace '[\\/:*?"<>|]', '-'
    $name = $name.Trim('. ')
    return $name
}

# Build a short opp file name: "{VendorCode} - {MachineName} - {Vendor}"
# Source: the folder name already has this structure after the first segment
function Get-OppFileName($folderName, $accountName) {
    # Current pattern: "{Account} - {OppSlug} - {Vendor}"
    # Strip the account prefix to get "{OppSlug} - {Vendor}"
    $escaped  = [regex]::Escape($accountName)
    $stripped = $folderName -replace "^${escaped}\s*-\s*", ''
    if (-not $stripped -or $stripped -eq $folderName) {
        # Fallback: drop first dash-separated segment
        $parts = $folderName -split ' - ', 2
        $stripped = if ($parts.Count -gt 1) { $parts[1] } else { $folderName }
    }
    return $stripped
}

# ── main ─────────────────────────────────────────────────────────────────────

$folders = Get-ChildItem $projectsRoot -Directory | Sort-Object Name
$plan    = @()
$issues  = @()

# Track: oppId → list of source folders (detects duplicate opp IDs)
$oppIdMap = @{}
# Track: proposed destination path → list of source folders (detects collisions)
$destMap  = @{}

foreach ($folder in $folders) {
    $mdFile = Get-ChildItem $folder.FullName -Filter "*.md" | Select-Object -First 1
    if (-not $mdFile) {
        $issues += [PSCustomObject]@{ Folder = $folder.Name; Issue = "No .md file found" }
        continue
    }

    $content   = Get-Content $mdFile.FullName -Raw -Encoding UTF8
    $oppId     = Get-FrontmatterValue $content "sf_opportunity_id"
    $accountRaw = Get-AccountName $content
    $stage     = Get-MarkdownField $content "Stage"
    $amount    = Get-MarkdownField $content "Amount"

    if (-not $accountRaw) {
        $issues += [PSCustomObject]@{ Folder = $folder.Name; Issue = "Could not parse Account name" }
        $accountRaw = "UNKNOWN"
    }

    $accountClean = Sanitize-Name $accountRaw
    $oppSlug      = Sanitize-Name (Get-OppFileName $folder.Name $accountRaw)
    $newFolder    = Join-Path $projectsRoot $accountClean
    $newFile      = "$oppSlug.md"
    $newPath      = Join-Path $newFolder $newFile
    $hubPath      = Join-Path $newFolder "$accountClean.md"

    # Flag duplicate opp IDs
    if ($oppId) {
        if ($oppIdMap.ContainsKey($oppId)) {
            $oppIdMap[$oppId] += $folder.Name
            $issues += [PSCustomObject]@{
                Folder = $folder.Name
                Issue  = "Duplicate sf_opportunity_id ($oppId) — also on: $($oppIdMap[$oppId][0])"
            }
        } else {
            $oppIdMap[$oppId] = @($folder.Name)
        }
    } else {
        $issues += [PSCustomObject]@{ Folder = $folder.Name; Issue = "No sf_opportunity_id in frontmatter" }
    }

    # Flag destination collisions
    if ($destMap.ContainsKey($newPath)) {
        $destMap[$newPath] += $folder.Name
        $issues += [PSCustomObject]@{
            Folder = $folder.Name
            Issue  = "Destination collision: '$newFile' in '$accountClean\' — also from: $($destMap[$newPath][0])"
        }
    } else {
        $destMap[$newPath] = @($folder.Name)
    }

    $plan += [PSCustomObject]@{
        Account      = $accountRaw
        Stage        = $stage
        Amount       = $amount
        OppId        = $oppId
        CurrentPath  = $folder.FullName.Replace($projectsRoot + '\', '')
        NewFolder    = $accountClean
        NewFile      = $newFile
        HubPage      = "$accountClean\$accountClean.md"
        Issues       = ""
    }
}

# ── output ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "=== MIGRATION PLAN (DRY RUN) ===" -ForegroundColor Cyan
Write-Host "Total project folders: $($folders.Count)" -ForegroundColor White
Write-Host "Total mapped:          $($plan.Count)" -ForegroundColor White
Write-Host ""

# Group by account to show the new structure
$grouped = $plan | Group-Object Account | Sort-Object Name
Write-Host "=== NEW FOLDER STRUCTURE ===" -ForegroundColor Cyan
foreach ($group in $grouped) {
    $acct = $group.Name
    Write-Host ""
    Write-Host "  $acct/" -ForegroundColor Yellow
    Write-Host "    $acct.md  [account hub - new]" -ForegroundColor DarkGray
    foreach ($item in ($group.Group | Sort-Object NewFile)) {
        $flag = if ($item.Issues) { " ⚠️" } else { "" }
        Write-Host "    $($item.NewFile)$flag" -ForegroundColor White
    }
}

Write-Host ""
Write-Host "=== ACCOUNTS WITH MULTIPLE OPPS ===" -ForegroundColor Cyan
foreach ($group in $grouped | Where-Object { $_.Count -gt 1 }) {
    Write-Host "  $($group.Name): $($group.Count) opps" -ForegroundColor White
    foreach ($item in $group.Group) {
        Write-Host "    - $($item.NewFile)  [$($item.Stage), $($item.Amount)]" -ForegroundColor Gray
    }
}

Write-Host ""
if ($issues.Count -gt 0) {
    Write-Host "=== ⚠️  ISSUES TO RESOLVE BEFORE MIGRATING ===" -ForegroundColor Red
    foreach ($issue in $issues) {
        Write-Host "  [$($issue.Folder)]" -ForegroundColor Yellow
        Write-Host "  → $($issue.Issue)" -ForegroundColor Red
        Write-Host ""
    }
} else {
    Write-Host "=== ✅ No issues found — safe to migrate ===" -ForegroundColor Green
}

# Export CSV for review
$plan | Export-Csv -Path $outputCsv -NoTypeInformation -Encoding UTF8
Write-Host ""
Write-Host "Full plan exported to: $outputCsv" -ForegroundColor DarkGray
Write-Host ""
Write-Host "When ready: run migrate-projects-execute.ps1 to perform the actual move." -ForegroundColor DarkGray
