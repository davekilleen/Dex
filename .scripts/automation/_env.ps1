# _env.ps1 -- Shared environment loader for Dex scheduled automation (Windows).
#
# Dot-sourced by the run-*.ps1 wrappers. Resolves the vault path, loads Salesforce
# OAuth client credentials out of .mcp.json into the process environment (the headless
# Python scripts read SF_CLIENT_ID / SF_CLIENT_SECRET / SF_OWNER_ID + VAULT_PATH), and
# locates a usable Python interpreter.
#
# Exposes:
#   $DexVault   - absolute vault root
#   $DexLogDir  - .scripts/logs
#   $DexPython  - path/command for Python
#   Write-DexLog <name> <message>   - timestamped append to a per-job log

$ErrorActionPreference = 'Stop'

# Vault root = two levels up from .scripts/automation
$DexVault  = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$DexLogDir = Join-Path $DexVault '.scripts\logs'
if (-not (Test-Path $DexLogDir)) { New-Item -ItemType Directory -Path $DexLogDir -Force | Out-Null }

$env:VAULT_PATH = $DexVault

# Load Salesforce creds from .mcp.json (so scheduled tasks work without a prior MCP session).
$mcpPath = Join-Path $DexVault '.mcp.json'
if (Test-Path $mcpPath) {
    try {
        $cfg = Get-Content $mcpPath -Raw | ConvertFrom-Json
        $servers = if ($cfg.mcpServers) { $cfg.mcpServers } else { $cfg.servers }
        foreach ($prop in $servers.PSObject.Properties) {
            $envBlock = $prop.Value.env
            if ($envBlock -and ($envBlock.SF_CLIENT_ID -or $envBlock.SF_OWNER_ID)) {
                if ($envBlock.SF_CLIENT_ID)     { $env:SF_CLIENT_ID     = $envBlock.SF_CLIENT_ID }
                if ($envBlock.SF_CLIENT_SECRET) { $env:SF_CLIENT_SECRET = $envBlock.SF_CLIENT_SECRET }
                if ($envBlock.SF_OWNER_ID)      { $env:SF_OWNER_ID      = $envBlock.SF_OWNER_ID }
                break
            }
        }
    } catch {
        Write-Warning "Could not read Salesforce creds from .mcp.json: $_"
    }
}

# Resolve a Python interpreter: prefer the launcher, then python/python3 on PATH.
$DexPython = $null
foreach ($candidate in @('py', 'python', 'python3')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) { $DexPython = $cmd.Source; break }
}
if (-not $DexPython) { throw "Python not found on PATH. Install Python 3.10+." }

function Write-DexLog {
    param([string]$Name, [string]$Message)
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -Path (Join-Path $DexLogDir "$Name.log") -Value $line
    Write-Host $line
}
