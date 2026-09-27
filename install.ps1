# Dex PKM - Windows Installation Script
# PowerShell twin of install.sh. Run from a Dex folder:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
# Or from an empty folder / via irm | iex, this script clones Dex first
# and then runs the same install.

$ErrorActionPreference = "Stop"

function Get-DexInstallRoot {
    if ($PSScriptRoot -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot "core\provision.cjs"))) {
        return (Resolve-Path -LiteralPath $PSScriptRoot).Path
    }
    if (Test-Path -LiteralPath (Join-Path (Get-Location) "core\provision.cjs")) {
        return (Resolve-Path -LiteralPath (Get-Location)).Path
    }
    return $null
}

function Get-DexInstallLogPath {
    param([Parameter(Mandatory = $true)][string]$Root)
    if ($env:DEX_INSTALL_LOG) {
        return $env:DEX_INSTALL_LOG
    }
    return (Join-Path $Root "System\.dex\install.log")
}

function Initialize-DexInstallLog {
    param([Parameter(Mandatory = $true)][string]$Root)
    $script:InstallLog = Get-DexInstallLogPath -Root $Root
    $logDir = Split-Path -Parent $script:InstallLog
    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    }
    $stamp = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    @(
        "===== Dex install log $stamp ====="
        "pwd=$Root"
        "OS=$([System.Environment]::OSVersion.VersionString)"
        "WINDIR=$env:WINDIR"
        "PATH=$env:PATH"
    ) | Add-Content -LiteralPath $script:InstallLog
}

function Write-DexInstallLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    if ($script:InstallLog) {
        Add-Content -LiteralPath $script:InstallLog -Value $Message
    }
}

function Show-DexLoggedFailure {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "[X] $Message"
    Write-Host "    See the install log for the exact error: $script:InstallLog"
}

function Invoke-DexLogged {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @()
    )
    Write-DexInstallLog "----- $Label -----"
    Write-DexInstallLog ("+ " + (@($FilePath) + $ArgumentList) -join " ")
    $output = & $FilePath @ArgumentList 2>&1
    $status = $LASTEXITCODE
    if ($null -ne $output) {
        $output | ForEach-Object { Write-DexInstallLog "$_" }
    }
    Write-DexInstallLog "exit $status"
    return $status
}

function Test-DexPythonVersion {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$PrefixArgs = @()
    )
    try {
        $output = & $FilePath @PrefixArgs --version 2>&1 | Out-String
    } catch {
        return $null
    }
    if ($output -notmatch "Python (3)\.(\d+)") {
        return $null
    }
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    if ($major -ne 3 -or $minor -lt 10) {
        return $null
    }
    if ($output -match "Python (3\.\d+(?:\.\d+)?)") {
        return $Matches[1]
    }
    return "3.$minor"
}

function Resolve-DexPythonExecutable {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$PrefixArgs = @()
    )
    try {
        $resolved = & $FilePath @PrefixArgs -c "import sys; print(sys.executable)" 2>$null
        if ($resolved) {
            return "$resolved".Trim()
        }
    } catch {
    }
    return $FilePath
}

function Resolve-DexPython {
    $candidates = @(
        @{ File = "python3"; Prefix = @() },
        @{ File = "py"; Prefix = @("-3") },
        @{ File = "python"; Prefix = @() }
    )
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.File -ErrorAction SilentlyContinue
        if (-not $command) {
            continue
        }
        $version = Test-DexPythonVersion -FilePath $command.Source -PrefixArgs $candidate.Prefix
        if (-not $version) {
            continue
        }
        $executable = Resolve-DexPythonExecutable -FilePath $command.Source -PrefixArgs $candidate.Prefix
        return @{
            Command = $executable
            Version = $version
        }
    }
    return $null
}

function Test-DexGranolaPresent {
    $candidates = @()
    if ($env:APPDATA) {
        $candidates += (Join-Path $env:APPDATA "Granola")
    }
    if ($env:LOCALAPPDATA) {
        $candidates += @(
            (Join-Path $env:LOCALAPPDATA "Granola"),
            (Join-Path $env:LOCALAPPDATA "Programs\@granolaelectron"),
            (Join-Path $env:LOCALAPPDATA "Programs\Granola")
        )
    }
    if ($env:USERPROFILE) {
        $candidates += @(
            (Join-Path $env:USERPROFILE "AppData\Roaming\Granola"),
            (Join-Path $env:USERPROFILE "AppData\Local\Granola"),
            (Join-Path $env:USERPROFILE "AppData\Local\Programs\@granolaelectron"),
            (Join-Path $env:USERPROFILE "AppData\Local\Programs\Granola")
        )
    }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    return $null
}

function Resolve-DexVenvPaths {
    param([Parameter(Mandatory = $true)][string]$Root)
    $scriptsPython = Join-Path $Root ".venv\Scripts\python.exe"
    $scriptsPip = Join-Path $Root ".venv\Scripts\pip.exe"
    $binPython = Join-Path $Root ".venv\bin\python"
    $binPip = Join-Path $Root ".venv\bin\pip"
    if ((Test-Path -LiteralPath $scriptsPip) -or (Test-Path -LiteralPath $scriptsPython)) {
        return @{ Python = $scriptsPython; Pip = $scriptsPip }
    }
    if ((Test-Path -LiteralPath $binPip) -or (Test-Path -LiteralPath $binPython)) {
        return @{ Python = $binPython; Pip = $binPip }
    }
    return @{ Python = $scriptsPython; Pip = $scriptsPip }
}

function Install-DexRepository {
    param([Parameter(Mandatory = $true)][string]$Target)
    if (Test-Path -LiteralPath (Join-Path $Target "core\provision.cjs")) {
        return $Target
    }
    $parent = Split-Path -Parent $Target
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Write-Host "Cloning Dex into $Target ..."
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        Write-Host "[X] Git is not installed"
        Write-Host "Download Git for Windows from: https://git-scm.com/download/win"
        throw "git missing"
    }
    & $git.Source clone "https://github.com/davekilleen/dex.git" $Target
    if ($LASTEXITCODE -ne 0) {
        throw "git clone failed"
    }
    return (Resolve-Path -LiteralPath $Target).Path
}

if ($env:DEX_INSTALL_LIB_ONLY -eq "1") {
    return
}

$Root = Get-DexInstallRoot
if (-not $Root) {
    $defaultTarget = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Dex"
    $Root = Install-DexRepository -Target $defaultTarget
}

Set-Location -LiteralPath $Root
Initialize-DexInstallLog -Root $Root
Write-DexInstallLog "starting install"

Write-Host "Setting up Dex..."
Write-Host ""

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Write-Host "[X] Git is not installed"
    Write-Host ""
    Write-Host "Git is required to clone the repository and manage updates."
    Write-Host "Download Git for Windows from: https://git-scm.com/download/win"
    Write-Host "After installing, restart your terminal and run .\install.ps1 again"
    exit 1
}
$gitVersion = (& $git.Source --version)
Write-Host "[OK] $gitVersion"

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Host "[X] Node.js is not installed"
    Write-Host "    Please install Node.js 18+ from https://nodejs.org/"
    exit 1
}
$nodeVersionText = (& $node.Source -v)
$nodeMajor = 0
if ($nodeVersionText -match "v(\d+)") {
    $nodeMajor = [int]$Matches[1]
}
if ($nodeMajor -lt 18) {
    Write-Host "[X] Node.js version must be 18 or higher (found $nodeVersionText)"
    Write-Host "    Please upgrade from https://nodejs.org/"
    exit 1
}
Write-Host "[OK] Node.js $nodeVersionText"

$python = Resolve-DexPython
if (-not $python) {
    Write-Host "[X] Python 3.10+ not found"
    Write-Host ""
    Write-Host "Python 3.10+ is required for task sync across your files."
    Write-Host "Install Python 3.10+:"
    Write-Host "  1. Download from https://www.python.org/downloads/"
    Write-Host "  2. Run the installer"
    Write-Host "  3. IMPORTANT: Check 'Add Python to PATH' during installation"
    Write-Host "  4. Restart your terminal"
    Write-Host "  5. Run .\install.ps1 again"
    Write-Host "  The installer also looks for the Windows 'py -3' launcher."
    exit 1
}
$PythonCmd = $python.Command
Write-Host "[OK] Python $($python.Version)"

$npx = Get-Command npx -ErrorAction SilentlyContinue
if (-not $npx) {
    Write-Host "[!] npx not found (usually bundled with Node.js)"
    Write-Host "    Some connected tools may not work without npx."
    Write-Host "    Try reinstalling Node.js from https://nodejs.org/"
}

Write-Host ""
Write-Host "Installing dependencies..."
$npm = Get-Command pnpm -ErrorAction SilentlyContinue
$npmLabel = "pnpm"
if (-not $npm) {
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    $npmLabel = "npm"
}
if (-not $npm) {
    Write-Host "[X] Neither npm nor pnpm found"
    exit 1
}
Write-DexInstallLog "----- $npmLabel install -----"
$npmOutput = & $npm.Source install 2>&1
$npmStatus = $LASTEXITCODE
if ($null -ne $npmOutput) {
    $npmOutput | ForEach-Object {
        Write-Host $_
        Write-DexInstallLog "$_"
    }
}
if ($npmStatus -ne 0) {
    Show-DexLoggedFailure "Could not install Node dependencies"
    exit 1
}

Write-Host ""
Write-Host "Converging bootstrap configuration through the provision contract..."
$provisionArgs = @("core/provision.cjs", "--path", $Root, "--install-config-only", "--json")
$qmd = Get-Command qmd -ErrorAction SilentlyContinue
if ($qmd) {
    $provisionArgs += "--enable-qmd"
}
$provisionEnv = @{
    DEX_CAPABILITY_PYTHON = $PythonCmd
    DEX_PROVISION_PYTHON = $PythonCmd
    DEX_HARNESS_PYTHON = $PythonCmd
    DEX_LIFECYCLE_PYTHON = $PythonCmd
}
foreach ($name in $provisionEnv.Keys) {
    Set-Item -Path "Env:$name" -Value $provisionEnv[$name]
}
if ((Invoke-DexLogged -Label "provision-bootstrap" -FilePath $node.Source -ArgumentList $provisionArgs) -ne 0) {
    Show-DexLoggedFailure "Dex could not finish the first-run setup"
    exit 1
}
if ($qmd) {
    Write-Host "   qmd MCP server added when configuration was absent"
} else {
    Write-Host "   semantic search not installed — run /enable-semantic-search to add it later"
}
Write-Host "   MCP servers configured for: $Root"

Write-Host ""
$granolaPath = Test-DexGranolaPresent
if ($granolaPath) {
    Write-Host "[OK] Granola app detected — run /granola-setup to connect it (needs a Granola Business API key)"
    Write-DexInstallLog "granola detected at $granolaPath"
} else {
    Write-Host "[i] Granola app not detected"
    Write-Host "    Install Granola from https://granola.ai for meeting transcription"
    Write-Host "    Then run /granola-setup to connect it (needs a Granola Business API key)"
}

Write-Host ""
Write-Host "Setting up Python environment for Work MCP..."
$venvDir = Join-Path $Root ".venv"
if (-not (Test-Path -LiteralPath $venvDir)) {
    Write-Host "   Creating virtual environment..."
    if ((Invoke-DexLogged -Label "python -m venv" -FilePath $PythonCmd -ArgumentList @("-m", "venv", ".venv")) -ne 0) {
        Show-DexLoggedFailure "Could not create virtual environment"
        Write-Host ""
        Write-Host "Try manually:"
        Write-Host "  `"$PythonCmd`" -m venv .venv"
        Write-Host "  .venv\Scripts\pip.exe install -r core\mcp\requirements.txt"
    }
}
$venv = Resolve-DexVenvPaths -Root $Root
$VenvPython = $venv.Python
$VenvPip = $venv.Pip

$workMcpStatus = "[!] Needs attention"
if ((Test-Path -LiteralPath $VenvPip) -and ((Invoke-DexLogged -Label "pip install" -FilePath $VenvPip -ArgumentList @("install", "-r", "core/mcp/requirements.txt", "--quiet")) -eq 0)) {
    Write-Host "[OK] Work MCP dependencies installed"
} else {
    if (-not (Test-Path -LiteralPath $VenvPip)) {
        Write-DexInstallLog "venv pip missing at $VenvPip"
    }
    Show-DexLoggedFailure "Could not install Python dependencies"
    Write-Host ""
    Write-Host "Work MCP is critical - it syncs tasks across all your files."
    Write-Host "Without it, checking off a task in one place won't update others."
    Write-Host ""
    Write-Host "Try manually:"
    Write-Host "  `"$PythonCmd`" -m venv .venv"
    Write-Host "  $VenvPip install -r core\mcp\requirements.txt"
}

Write-Host ""
Write-Host "Verifying Work MCP setup..."
if ((Test-Path -LiteralPath $VenvPython) -and ((Invoke-DexLogged -Label "import mcp, yaml" -FilePath $VenvPython -ArgumentList @("-c", "import mcp, yaml")) -eq 0)) {
    Write-Host "[OK] Work MCP verified - task sync will work"
    $workMcpStatus = "[OK] Working"
    Write-Host "Path constants generated"
} else {
    Show-DexLoggedFailure "Work MCP not working - task sync won't function"
}

Write-Host ""
Write-Host "Separating the Dex brain from your vault..."
$migrator = "core/migrations/v1-to-v2-brain-vault-split.cjs"
if (-not (Test-Path -LiteralPath (Join-Path $Root $migrator))) {
    Write-Host "[X] Dex cannot finish the brain/vault setup because the migrator is missing."
    Write-Host "    Get a complete Dex release and run .\install.ps1 again."
    exit 1
}

$allowSynced = $false
foreach ($argument in $args) {
    if ($argument -eq "--allow-synced-folder") {
        $allowSynced = $true
    }
}

$migrationMode = "--auto"
while ($true) {
    $migrationArgs = @($migrator, $migrationMode)
    if ($allowSynced) {
        $migrationArgs += "--allow-synced-folder"
    }
    $null = & $node.Source @migrationArgs
    $migrationStatus = $LASTEXITCODE
    if ($migrationStatus -eq 75) {
        $migrationMode = "--resume"
        continue
    }
    if ($migrationStatus -ne 0) {
        Write-Host "[X] Dex could not finish the brain/vault split."
        Write-Host "    Read System/migration-report-v2.md, fix the reported issue, then run .\install.ps1 again."
        Write-Host "    Install log: $script:InstallLog"
        exit $migrationStatus
    }
    break
}

$topology = Join-Path $Root "System\.dex\topology.json"
$brainGit = Join-Path $Root ".dex\brain.git"
$vaultGit = Join-Path $Root ".git"
if ((Test-Path -LiteralPath $topology) -and (Test-Path -LiteralPath $brainGit) -and (Test-Path -LiteralPath $vaultGit)) {
    Write-Host "[OK] Your vault and the Dex brain now have separate Git histories"
} elseif ((Test-Path -LiteralPath $topology) -and (Test-Path -LiteralPath $brainGit)) {
    Write-Host "[X] Dex could not finish the brain/vault split."
    Write-Host "    The notes folder has no working Git history. Your files are still here."
    Write-Host "    Run: node core/migrations/v1-to-v2-brain-vault-split.cjs --resume"
    Write-Host "    Then run .\install.ps1 again."
    exit 1
} else {
    Write-Host "[!] This folder has no Git clone history, so the brain/vault split was not started."
    Write-Host "    Your files are unchanged, and Dex will keep using the combined layout."
    Write-Host "    Read System/migration-report-v2.md for the safe manual-update choices."
}

$adoptionPython = $PythonCmd
if (Test-Path -LiteralPath $VenvPython) {
    $adoptionPython = $VenvPython
}
$env:DEX_LIFECYCLE_PYTHON = $adoptionPython
$env:DEX_PROVISION_PYTHON = $adoptionPython
$env:DEX_CAPABILITY_PYTHON = $adoptionPython
$env:DEX_HARNESS_PYTHON = $adoptionPython
if ((Invoke-DexLogged -Label "provision-adopt" -FilePath $node.Source -ArgumentList @("core/provision.cjs", "--path", $Root, "--adopt", "--lifecycle-only")) -ne 0) {
    Show-DexLoggedFailure "Dex could not finish the last setup step"
    exit 1
}

$harnessJson = "[]"
try {
    $harnessJson = & $PythonCmd -m core.harnesses.registry detect --format json 2>> $script:InstallLog
    if ($LASTEXITCODE -ne 0 -or -not $harnessJson) {
        $harnessJson = "[]"
    }
} catch {
    Write-DexInstallLog "harness detection failed; continuing with an empty list"
    $harnessJson = "[]"
}

$chatApps = & $node.Source -e @"
  try {
    const profiles = JSON.parse(process.argv[1]);
    const names = profiles.map(profile => (
      typeof profile === "string" ? profile : (profile.display_name || profile.name || profile.id)
    )).filter(Boolean);
    process.stdout.write(names.join(", "));
  } catch (_) {
    process.stdout.write("");
  }
"@ $harnessJson
if (-not $chatApps) {
    $chatApps = "a supported AI app"
}

Write-Host ""
Write-Host "================================================="
Write-Host "[OK] Dex installation complete!"
Write-Host ""
Write-Host "Status:"
Write-Host "  - Node.js: [OK] Working"
Write-Host "  - Work MCP: $workMcpStatus"
if ($workMcpStatus -like "*Needs*") {
    Write-Host ""
    Write-Host "[!] IMPORTANT: Work MCP enables task sync across all files."
    Write-Host "    Without it, Dex works but tasks won't sync automatically."
    Write-Host "    See troubleshooting above to fix."
    Write-Host "    Install log: $script:InstallLog"
}
Write-Host ""
Write-Host "Dex detected: $chatApps"
Write-Host "Setup will let you confirm one or several harnesses and show exactly what each supports."
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Open one of these apps in this folder: $chatApps"
Write-Host "     (the folder you just installed into — not somewhere else)"
Write-Host "  2. In that app's chat, type: /setup"
Write-Host "  3. Answer the setup questions (~5 minutes)"
Write-Host "  4. Start using Dex!"
Write-Host "================================================="
