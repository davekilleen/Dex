#!/bin/bash
# Dex PKM - Installation Script
# This script sets up your development environment

# Quiet Node's noisy upstream deprecation warnings (e.g. DEP0040 "punycode is
# deprecated") so first-run install output stays clean. These originate from
# transitive dependencies / npm internals on newer Node versions, not from Dex,
# and are harmless. Preserves any NODE_OPTIONS the user already set.
export NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--no-deprecation"

# ---------------------------------------------------------------------------
# Helpers (sourced by tests when DEX_INSTALL_LIB_ONLY=1)
# ---------------------------------------------------------------------------

dex_is_windows() {
    # Prefer a concrete Windows venv layout over OSTYPE alone. Git Bash on
    # Windows 11 often reports OSTYPE=cygwin (Joe, 2026-09-26), which the old
    # msys/win32-only check missed.
    if [ -f ".venv/Scripts/pip.exe" ] || [ -f ".venv/Scripts/python.exe" ]; then
        return 0
    fi
    case "${OSTYPE:-}" in
        msys*|cygwin*|win32*|mingw*) return 0 ;;
    esac
    if [ -n "${WINDIR:-}" ]; then
        return 0
    fi
    return 1
}

dex_resolve_venv_paths() {
    if [ -f ".venv/Scripts/pip.exe" ] || [ -f ".venv/Scripts/python.exe" ]; then
        VENV_PYTHON=".venv/Scripts/python.exe"
        VENV_PIP=".venv/Scripts/pip.exe"
    elif [ -f ".venv/bin/pip" ] || [ -f ".venv/bin/python" ]; then
        VENV_PYTHON=".venv/bin/python"
        VENV_PIP=".venv/bin/pip"
    elif dex_is_windows; then
        VENV_PYTHON=".venv/Scripts/python.exe"
        VENV_PIP=".venv/Scripts/pip.exe"
    else
        VENV_PYTHON=".venv/bin/python"
        VENV_PIP=".venv/bin/pip"
    fi
}

dex_parse_python_version() {
    local text="$1"
    local rest
    case "$text" in
        *Python\ 3.*)
            rest="${text#*Python }"
            rest="${rest%%[!0-9.]*}"
            printf '%s\n' "$rest"
            return 0
            ;;
    esac
    return 1
}

dex_is_windows_apps_stub() {
    # Microsoft Store aliases live under a WindowsApps folder and open the
    # Store instead of running Python. Match a path segment only, so a
    # nearby folder name that merely contains those letters is left alone.
    case "$1" in
        *[\\/][Ww]indows[Aa]pps[\\/]*|*[\\/][Ww]indows[Aa]pps)
            return 0
            ;;
    esac
    return 1
}

dex_to_posix_path() {
    local raw="$1"
    if command -v cygpath >/dev/null 2>&1; then
        case "$raw" in
            [A-Za-z]:\\*|[A-Za-z]:/*)
                raw=$(cygpath -u "$raw" 2>/dev/null || printf '%s' "$raw")
                ;;
        esac
    fi
    printf '%s\n' "$raw"
}

dex_python_version_ok() {
    local output version major minor
    output=$("$@" --version 2>&1) || return 1
    version=$(dex_parse_python_version "$output") || return 1
    major="${version%%.*}"
    minor="${version#*.}"
    minor="${minor%%.*}"
    if [ "$major" != "3" ]; then
        return 1
    fi
    if [ "$minor" -lt 10 ]; then
        return 1
    fi
    printf '%s\n' "$version"
}

dex_python_executable() {
    local resolved=""
    resolved=$("$@" -c "import sys; print(sys.executable)") || return 1
    if [ -z "$resolved" ]; then
        return 1
    fi
    dex_to_posix_path "$resolved"
}

dex_accept_python() {
    local version resolved first="$1"
    shift
    local found="$first"

    found=$(dex_to_posix_path "$found")
    if [ ! -e "$found" ]; then
        found=$(command -v "$first") || return 1
        found=$(dex_to_posix_path "$found")
    fi
    if dex_is_windows_apps_stub "$found"; then
        return 1
    fi
    if ! version=$(dex_python_version_ok "$found" "$@"); then
        return 1
    fi
    if ! resolved=$(dex_python_executable "$found" "$@"); then
        return 1
    fi
    if dex_is_windows_apps_stub "$resolved"; then
        return 1
    fi
    PYTHON_CMD="$resolved"
    PYTHON_VERSION="$version"
    return 0
}

dex_resolve_python() {
    PYTHON_CMD=""
    PYTHON_VERSION=""

    if [ -n "${DEX_INSTALL_PYTHON:-}" ]; then
        if dex_accept_python "$DEX_INSTALL_PYTHON"; then
            return 0
        fi
    fi

    if command -v python3 >/dev/null 2>&1; then
        if dex_accept_python python3; then
            return 0
        fi
    fi

    if command -v py >/dev/null 2>&1; then
        if dex_accept_python py -3; then
            return 0
        fi
    fi

    if command -v python >/dev/null 2>&1; then
        if dex_accept_python python; then
            return 0
        fi
    fi

    return 1
}

dex_granola_locator_present() {
    [ -n "${PYTHON_CMD:-}" ] && [ -f "core/integrations/granola_paths.py" ]
}

dex_granola_via_shared_module() {
    # Shared locator from the Granola Windows-sync work. If that module is not
    # in this checkout yet, return quietly so install can skip with a note.
    if ! dex_granola_locator_present; then
        return 1
    fi
    local path
    path=$("$PYTHON_CMD" -m core.integrations.granola_paths --json | "$PYTHON_CMD" -c '
import json, sys
try:
    payload = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
if not payload.get("installed"):
    raise SystemExit(1)
print(payload.get("app_path_posix") or payload.get("app_path") or payload.get("data_path_posix") or payload.get("data_path") or "")
') || return 1
    [ -n "$path" ] || return 1
    printf '%s\n' "$path"
}

dex_install_log_path() {
    if [ -n "${DEX_INSTALL_LOG:-}" ]; then
        printf '%s\n' "$DEX_INSTALL_LOG"
        return 0
    fi
    printf '%s\n' "$(pwd)/System/.dex/install.log"
}

dex_init_install_log() {
    INSTALL_LOG="$(dex_install_log_path)"
    mkdir -p "$(dirname "$INSTALL_LOG")"
    {
        echo "===== Dex install log $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
        echo "pwd=$(pwd)"
        echo "OSTYPE=${OSTYPE:-}"
        echo "WINDIR=${WINDIR:-}"
        echo "PATH=$PATH"
    } >> "$INSTALL_LOG"
}

dex_log() {
    if [ -n "${INSTALL_LOG:-}" ]; then
        printf '%s\n' "$*" >> "$INSTALL_LOG"
    fi
}

dex_run_logged() {
    local label="$1"
    shift
    local status=0
    {
        echo "----- $label -----"
        printf '+ '
        printf '%q ' "$@"
        echo
    } >> "$INSTALL_LOG"
    "$@" >> "$INSTALL_LOG" 2>&1 || status=$?
    echo "exit $status" >> "$INSTALL_LOG"
    return "$status"
}

dex_show_logged_failure() {
    echo "❌ $1"
    echo "   See the install log for the exact error: $INSTALL_LOG"
}

dex_prompt_continue() {
    if [ -t 0 ] && [ -z "${DEX_INSTALL_NONINTERACTIVE:-}" ]; then
        read -r -p "Press Enter to continue setup (you can fix this later)..."
    fi
}

if [ "${DEX_INSTALL_LIB_ONLY:-}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi

# Native Windows CI (windows-install-journey) sets CI=true and closes stdin.
# Never wait for a keypress on that path.
if [ -n "${CI:-}" ] && [ -z "${DEX_INSTALL_NONINTERACTIVE:-}" ]; then
    export DEX_INSTALL_NONINTERACTIVE=1
fi

set -e

# ---------------------------------------------------------------------------
# Main install
# ---------------------------------------------------------------------------

dex_init_install_log
dex_log "starting install"

echo "🚀 Setting up Dex..."
echo ""

# Check for Command Line Tools on macOS (required for git)
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! xcode-select -p >/dev/null 2>&1; then
        echo "⚠️  Command Line Developer Tools not found"
        echo ""
        echo "macOS will now prompt you to install them - this is required for git."
        echo "Click 'Install' when the dialog appears (takes 2-3 minutes)."
        echo ""
        echo "Press Enter to continue..."
        read -r
        
        # Trigger the install prompt
        xcode-select --install >/dev/null 2>&1 || true
        
        echo ""
        echo "⏳ Waiting for Command Line Tools installation..."
        echo "   (This window will continue once installation completes)"
        echo ""
        
        # Wait for installation to complete
        until xcode-select -p >/dev/null 2>&1; do
            sleep 5
        done
        
        echo "✅ Command Line Tools installed!"
        echo ""
    fi
fi

# Silently fix git remote to avoid Claude Desktop confusion
if git remote -v >/dev/null 2>&1 && git remote -v | grep -q "davekilleen/[Dd]ex"; then
    git remote rename origin upstream >/dev/null 2>&1 || true
fi

# Check Git first (required for repo operations)
if ! command -v git >/dev/null 2>&1; then
    echo "❌ Git is not installed"
    echo ""
    echo "Git is required to clone the repository and manage updates."
    echo ""
    if dex_is_windows; then
        echo "Download Git for Windows from: https://git-scm.com/download/win"
        echo "After installing, restart your terminal and run ./install.sh again"
    else
        echo "Download Git from: https://git-scm.com"
        echo "After installing, restart your terminal and run ./install.sh again"
    fi
    exit 1
fi
echo "✅ Git $(git --version | cut -d' ' -f3)"

# Check Node.js
if ! command -v node >/dev/null 2>&1; then
    echo "❌ Node.js is not installed"
    echo "   Please install Node.js 18+ from https://nodejs.org/"
    exit 1
fi

NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "❌ Node.js version must be 18 or higher (found v$NODE_VERSION)"
    echo "   Please upgrade from https://nodejs.org/"
    exit 1
fi
echo "✅ Node.js $(node -v)"

# Check Python (required for Work MCP - task sync)
# Windows python.org installs often expose `py -3` and `python`, not `python3`.
if dex_resolve_python; then
    echo "✅ Python $PYTHON_VERSION"

    dex_resolve_venv_paths
else
    echo "❌ Python 3.10+ not found"
    echo ""
    echo "Python 3.10+ is required for MCP servers (task sync across all files)."
    echo "Without it, tasks won't sync between meeting notes, person pages, and Tasks.md."
    echo ""
    if dex_is_windows; then
        echo "Install Python 3.10+:"
        echo "  1. Download from https://www.python.org/downloads/"
        echo "  2. Run the installer"
        echo "  3. ⚠️  IMPORTANT: Check 'Add Python to PATH' during installation"
        echo "  4. Restart your terminal"
        echo "  5. Run ./install.sh again"
        echo "  The installer also looks for the Windows 'py -3' launcher."
        echo "  The Microsoft Store python3 placeholder is ignored."
    else
        echo "Install Python 3.10+:"
        echo "  Mac: Download from https://www.python.org/downloads/"
        echo "  Or use Homebrew: brew install python3"
        echo ""
        echo "After installing, run ./install.sh again"
    fi
    exit 1
fi

# Check npx (required for MCP servers)
if ! command -v npx >/dev/null 2>&1; then
    echo "⚠️  npx not found (usually bundled with Node.js)"
    echo "   Some MCP servers may not work without npx."
    echo "   Try reinstalling Node.js from https://nodejs.org/"
fi

# Install Node dependencies. Keep the live output on screen (this step can
# take a minute) and record the same lines in the install log.
echo ""
echo "📦 Installing dependencies..."
if command -v pnpm >/dev/null 2>&1; then
    dex_log "----- pnpm install -----"
    if ! pnpm install > >(tee -a "$INSTALL_LOG") 2>&1; then
        dex_show_logged_failure "Could not install Node dependencies"
        exit 1
    fi
elif command -v npm >/dev/null 2>&1; then
    dex_log "----- npm install -----"
    if ! npm install > >(tee -a "$INSTALL_LOG") 2>&1; then
        dex_show_logged_failure "Could not install Node dependencies"
        exit 1
    fi
else
    echo "❌ Neither npm nor pnpm found"
    exit 1
fi

# Skip .env creation - it is created during /setup if needed.
# Most Dex workflows use the local vault and MCP services without API keys.

# Bootstrap-only configuration is owned by the sanctioned provision contract.
# This is the one legitimate pre-lifecycle write window: a fresh bundle does
# not yet have an activated lifecycle engine. Post-install adoption below uses
# the frozen lifecycle service.
echo ""
echo "📝 Converging bootstrap configuration through the provision contract..."
PROVISION_ARGS=(--path "$(pwd)" --install-config-only --json)
if command -v qmd >/dev/null 2>&1; then
    PROVISION_ARGS+=(--enable-qmd)
fi
if ! DEX_CAPABILITY_PYTHON="$PYTHON_CMD" DEX_PROVISION_PYTHON="$PYTHON_CMD" DEX_HARNESS_PYTHON="$PYTHON_CMD" DEX_LIFECYCLE_PYTHON="$PYTHON_CMD" dex_run_logged "provision-bootstrap" node core/provision.cjs "${PROVISION_ARGS[@]}"; then
    dex_show_logged_failure "Dex could not finish the first-run setup"
    exit 1
fi
if command -v qmd >/dev/null 2>&1; then
    echo "   qmd MCP server added when configuration was absent"
else
    echo "   semantic search not installed — run /enable-semantic-search to add it later"
fi
echo "   MCP servers configured for: $(pwd)"

# Check for the optional Granola app. API access is connected separately.
# Path resolution lives in core.integrations.granola_paths (Windows-sync PR).
# If that module is not here yet, skip the check with a note and continue.
echo ""
GRANOLA_PATH=""
if ! dex_granola_locator_present; then
    echo "ℹ️  Granola app check skipped — shared locator not in this checkout yet"
    echo "   Run /granola-setup later to connect it (needs a Granola Business API key)"
    dex_log "granola locator missing; skipped detection"
elif GRANOLA_PATH=$(dex_granola_via_shared_module); then
    echo "✅ Granola app detected — run /granola-setup to connect it (needs a Granola Business API key)"
    dex_log "granola detected at $GRANOLA_PATH"
else
    echo "ℹ️  Granola app not detected"
    echo "   Install Granola from https://granola.ai for meeting transcription"
    echo "   Then run /granola-setup to connect it (needs a Granola Business API key)"
fi

# Install Python dependencies for Work MCP in a virtual environment
echo ""
echo "📦 Setting up Python environment for Work MCP..."

if [ -n "$PYTHON_CMD" ]; then
    # Create venv if it doesn't exist
    if [ ! -d ".venv" ]; then
        echo "   Creating virtual environment..."
        if ! dex_run_logged "python -m venv" "$PYTHON_CMD" -m venv .venv; then
            dex_show_logged_failure "Could not create virtual environment"
            echo ""
            echo "Try manually:"
            echo "  \"$PYTHON_CMD\" -m venv .venv"
            echo "  $VENV_PIP install -r core/mcp/requirements.txt"
            echo ""
            dex_prompt_continue
        fi
    fi

    dex_resolve_venv_paths

    # Install dependencies into venv
    if [ -f "$VENV_PIP" ] && dex_run_logged "pip install" "$VENV_PIP" install -r core/mcp/requirements.txt --quiet; then
        echo "✅ Work MCP dependencies installed"
    else
        if [ ! -f "$VENV_PIP" ]; then
            dex_log "venv pip missing at $VENV_PIP"
        fi
        dex_show_logged_failure "Could not install Python dependencies"
        echo ""
        echo "Work MCP is critical - it syncs tasks across all your files."
        echo "Without it, checking off a task in one place won't update others."
        echo ""
        echo "Try manually:"
        echo "  \"$PYTHON_CMD\" -m venv .venv"
        echo "  $VENV_PIP install -r core/mcp/requirements.txt"
        echo ""
        dex_prompt_continue
    fi
fi

# Verify Work MCP setup
echo ""
echo "🔍 Verifying Work MCP setup..."
if [ -n "$PYTHON_CMD" ] && [ -f "$VENV_PYTHON" ]; then
    if dex_run_logged "import mcp, yaml" "$VENV_PYTHON" -c "import mcp, yaml"; then
        echo "✅ Work MCP verified - task sync will work"
        WORK_MCP_STATUS="✅ Working"

        # Path constants were generated by the sanctioned provision contract.
        echo "Path constants generated"
    else
        dex_show_logged_failure "Work MCP not working - task sync won't function"
        WORK_MCP_STATUS="⚠️  Needs attention"
    fi
else
    WORK_MCP_STATUS="⚠️  Needs attention"
    dex_log "Work MCP skipped: PYTHON_CMD='$PYTHON_CMD' VENV_PYTHON='$VENV_PYTHON'"
fi

# Converge Git clones to the split Brain/Vault topology through the migration
# engine that also handles existing installs. A bounded migration may ask to
# resume, so keep routing back to that engine until it reaches a terminal state.
echo ""
echo "🔀 Separating the Dex brain from your vault..."
MIGRATOR="core/migrations/v1-to-v2-brain-vault-split.cjs"
if [ ! -f "$MIGRATOR" ]; then
    echo "❌ Dex cannot finish the brain/vault setup because the migrator is missing."
    echo "   Get a complete Dex release and run ./install.sh again."
    exit 1
fi

MIGRATION_SYNC_FOLDER_ARGUMENT=""
for INSTALL_ARGUMENT in "$@"; do
    if [ "$INSTALL_ARGUMENT" = "--allow-synced-folder" ]; then
        MIGRATION_SYNC_FOLDER_ARGUMENT="--allow-synced-folder"
    fi
done

MIGRATION_MODE="--auto"
while true; do
    if [ -n "$MIGRATION_SYNC_FOLDER_ARGUMENT" ]; then
        if node "$MIGRATOR" "$MIGRATION_MODE" "$MIGRATION_SYNC_FOLDER_ARGUMENT"; then
            MIGRATION_STATUS=0
        else
            MIGRATION_STATUS=$?
        fi
    elif node "$MIGRATOR" "$MIGRATION_MODE"; then
        MIGRATION_STATUS=0
    else
        MIGRATION_STATUS=$?
    fi

    if [ "$MIGRATION_STATUS" -eq 75 ]; then
        MIGRATION_MODE="--resume"
        continue
    fi
    if [ "$MIGRATION_STATUS" -ne 0 ]; then
        echo "❌ Dex could not finish the brain/vault split."
        echo "   Read System/migration-report-v2.md, fix the reported issue, then run ./install.sh again."
        echo "   Install log: $INSTALL_LOG"
        exit "$MIGRATION_STATUS"
    fi
    break
done

if [ -f "System/.dex/topology.json" ] && [ -d ".dex/brain.git" ] && [ -d ".git" ]; then
    echo "✅ Your vault and the Dex brain now have separate Git histories"
elif [ -f "System/.dex/topology.json" ] && [ -d ".dex/brain.git" ]; then
    echo "❌ Dex could not finish the brain/vault split."
    echo "   The notes folder has no working Git history. Your files are still here."
    echo "   Run: node core/migrations/v1-to-v2-brain-vault-split.cjs --resume"
    echo "   Then run ./install.sh again."
    exit 1
else
    echo "⚠️  This folder has no Git clone history, so the brain/vault split was not started."
    echo "   Your files are unchanged, and Dex will keep using the combined layout."
    echo "   Read System/migration-report-v2.md for the safe manual-update choices."
fi

# Any catalog adoption after bootstrap crosses the frozen lifecycle service;
# the provisioner only collects the vault path and renders its receipt.
DEX_ADOPTION_PYTHON="$PYTHON_CMD"
if [ -n "$VENV_PYTHON" ] && [ -f "$VENV_PYTHON" ]; then
    DEX_ADOPTION_PYTHON="$VENV_PYTHON"
fi
if ! DEX_LIFECYCLE_PYTHON="$DEX_ADOPTION_PYTHON" DEX_PROVISION_PYTHON="$DEX_ADOPTION_PYTHON" DEX_CAPABILITY_PYTHON="$DEX_ADOPTION_PYTHON" DEX_HARNESS_PYTHON="$DEX_ADOPTION_PYTHON" dex_run_logged "provision-adopt" node core/provision.cjs --path "$(pwd)" --adopt --lifecycle-only; then
    dex_show_logged_failure "Dex could not finish the last setup step"
    exit 1
fi

# Detect likely agent harnesses through the same capability registry onboarding and
# Doctor use. This is a suggestion only: /setup shows the capability preview and lets
# the user confirm one or several harnesses before anything is recorded.
if ! DEX_HARNESSES_JSON=$("$PYTHON_CMD" -m core.harnesses.registry detect --format json 2>>"$INSTALL_LOG"); then
    dex_log "harness detection failed; continuing with an empty list"
    DEX_HARNESSES_JSON="[]"
fi
DEX_CHAT_APPS="$(node -e '
  try {
    const profiles = JSON.parse(process.argv[1]);
    const names = profiles.map(profile => (
      typeof profile === "string" ? profile : (profile.display_name || profile.name || profile.id)
    )).filter(Boolean);
    process.stdout.write(names.join(", "));
  } catch (_) {
    process.stdout.write("");
  }
' "$DEX_HARNESSES_JSON")"
if [ -z "$DEX_CHAT_APPS" ]; then
    DEX_CHAT_APPS="a supported AI app"
fi

# Success
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Dex installation complete!"
echo ""
echo "Status:"
echo "  • Node.js: ✅ Working"
echo "  • Work MCP: $WORK_MCP_STATUS"
if [[ "$WORK_MCP_STATUS" == *"Needs"* ]]; then
    echo ""
    echo "⚠️  IMPORTANT: Work MCP enables task sync across all files."
    echo "   Without it, Dex works but tasks won't sync automatically."
    echo "   See troubleshooting above to fix."
    echo "   Install log: $INSTALL_LOG"
fi
echo ""
echo "Dex detected: $DEX_CHAT_APPS"
echo "Setup will let you confirm one or several harnesses and show exactly what each supports."
echo ""
echo "Next steps:"
echo "  1. Open one of these apps in this folder: $DEX_CHAT_APPS"
echo "     (the folder you just installed into — not somewhere else)"
echo "  2. In that app's chat, type: /setup"
echo "  3. Answer the setup questions (~5 minutes)"
echo "  4. Start using Dex!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
