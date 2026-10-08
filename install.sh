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
    if [ "$minor" -lt 11 ]; then
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

# Phase 3 (#761) support-policy hooks. The shared module lives in
# core/utils/platform_support.py. If that file is not in this checkout yet,
# the Python probe is a no-op so #761 can rebase on top.
dex_support_uname() {
    if [ -n "${DEX_TEST_UNAME:-}" ]; then
        printf '%s\n' "$DEX_TEST_UNAME"
        return 0
    fi
    uname -s 2>/dev/null || true
}

dex_support_proc_version() {
    if [ -n "${DEX_TEST_PROC_VERSION+x}" ]; then
        printf '%s\n' "$DEX_TEST_PROC_VERSION"
        return 0
    fi
    if [ -f /proc/version ]; then
        cat /proc/version
    fi
}

dex_support_vault_path() {
    if [ -n "${DEX_TEST_VAULT_PATH:-}" ]; then
        printf '%s\n' "$DEX_TEST_VAULT_PATH"
        return 0
    fi
    pwd
}

dex_support_show_log() {
    local log="${INSTALL_LOG:-${DEX_INSTALL_LOG:-$(pwd)/System/.dex/install.log}}"
    echo " See the install log for the exact error: $log"
}

dex_support_shell_precheck() {
    # uname -s prefix CYGWIN ⇒ refuse. MINGW*/MSYS* ⇒ Git Bash launcher.
    # OSTYPE=cygwin on Git Bash is not a refuse (Joe, 2026-09-26).
    local uname_s proc vault
    uname_s=$(dex_support_uname)
    proc=$(dex_support_proc_version)
    vault=$(dex_support_vault_path)
    case "$uname_s" in
        CYGWIN*|cygwin*)
            echo "Dex on Windows runs in Git Bash with a Python from python.org. Cygwin isn't supported. Open Git Bash (installed with Git for Windows) in your Dex folder and run bash ./install.sh."
            return 1
            ;;
        MINGW*|mingw*|MSYS*|msys*)
            DEX_WINDOWS_LAUNCHER=1
            ;;
    esac
    case "$proc" in
        *[Mm]icrosoft*)
            case "$vault" in
                /mnt/[A-Za-z]|/mnt/[A-Za-z]/*)
                    echo "Your Dex folder is on the Windows side of WSL (/mnt/...). Dex can't keep its files safe there. Either keep the folder in Linux (for example ~/Dex) and use Dex from WSL, or clone the official Dex release on Windows and run bash ./install.sh from Git Bash."
                    return 1
                    ;;
            esac
            ;;
    esac
    return 0
}

dex_support_python_probe() {
    if [ ! -f "core/utils/platform_support.py" ] || [ -z "${PYTHON_CMD:-}" ]; then
        return 0
    fi
    local status=0
    if [ -n "${INSTALL_LOG:-}${DEX_INSTALL_LOG:-}" ]; then
        local log="${INSTALL_LOG:-$DEX_INSTALL_LOG}"
        "$PYTHON_CMD" -m core.utils.platform_support --json --vault "$(pwd)" >>"$log" || status=$?
    else
        "$PYTHON_CMD" -m core.utils.platform_support --json --vault "$(pwd)" >/dev/null || status=$?
    fi
    if [ "$status" -ne 0 ]; then
        dex_support_show_log
        return "$status"
    fi
    return 0
}

dex_support_verify_venv_python() {
    case "${DEX_WINDOWS_LAUNCHER:-}" in
        1) ;;
        *)
            case "${OSTYPE:-}" in
                msys*|cygwin*|win32*|mingw*) ;;
                *)
                    if [ -z "${WINDIR:-}" ]; then
                        return 0
                    fi
                    ;;
            esac
            ;;
    esac
    local python=""
    if [ -n "${VENV_PYTHON:-}" ] && [ -f "$VENV_PYTHON" ]; then
        python="$VENV_PYTHON"
    elif [ -f ".venv/Scripts/python.exe" ]; then
        python=".venv/Scripts/python.exe"
    else
        return 0
    fi
    local plat
    plat=$("$python" -c "import sys; print(sys.platform)" 2>/dev/null || true)
    if [ "$plat" != "win32" ]; then
        echo "Dex on Windows runs in Git Bash with a Python from python.org. Cygwin isn't supported. Open Git Bash (installed with Git for Windows) in your Dex folder and run bash ./install.sh."
        echo "The Python in .venv printed '$plat', not win32."
        dex_support_show_log
        return 1
    fi
    return 0
}

dex_hashed_requirements() {
    printf '%s\n' "core/mcp/requirements.hash.txt"
}

# ---------------------------------------------------------------------------
# Beginner-install helpers (prompts always read /dev/tty under curl | bash)
# ---------------------------------------------------------------------------

dex_is_interactive() {
    if [ -n "${DEX_INSTALL_NONINTERACTIVE:-}" ] || [ -n "${CI:-}" ]; then
        return 1
    fi
    # ./install.sh in a real terminal
    if [ -t 0 ]; then
        return 0
    fi
    # curl | bash: stdin is the script; the keyboard is /dev/tty.
    # A detached CI job may still have a /dev/tty node — opening it must work.
    if [ -e /dev/tty ] && { : < /dev/tty; } 2>/dev/null; then
        return 0
    fi
    return 1
}

dex_read_tty() {
    # Prompt on the keyboard even when stdin is the curl pipe. $1=prompt $2=default
    local prompt="$1"
    local default="${2:-}"
    REPLY=""
    if ! dex_is_interactive; then
        REPLY="$default"
        return 0
    fi
    if [ -e /dev/tty ]; then
        printf '%s' "$prompt" > /dev/tty
        IFS= read -r REPLY < /dev/tty || REPLY="$default"
    elif [ -t 0 ]; then
        printf '%s' "$prompt"
        IFS= read -r REPLY || REPLY="$default"
    else
        REPLY="$default"
    fi
    if [ -z "$REPLY" ]; then
        REPLY="$default"
    fi
}

dex_home_dir() {
    if [ -n "${HOME:-}" ]; then
        printf '%s\n' "$HOME"
        return 0
    fi
    if [ -n "${USERPROFILE:-}" ]; then
        dex_to_posix_path "$USERPROFILE"
        return 0
    fi
    printf '%s\n' "$(pwd)"
}

dex_expand_path() {
    local raw="$1"
    case "$raw" in
        "~") raw="$(dex_home_dir)" ;;
        "~/"*) raw="$(dex_home_dir)/${raw#"~/"}" ;;
    esac
    printf '%s\n' "$raw"
}

dex_display_path() {
    local raw="$1"
    if dex_is_windows && command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$raw" 2>/dev/null || printf '%s\n' "$raw"
        return 0
    fi
    printf '%s\n' "$raw"
}

dex_is_checkout() {
    local root="${1:-$(pwd)}"
    [ -f "$root/core/provision.cjs" ] && [ -f "$root/install.sh" ]
}

dex_cloud_provider() {
    local raw="$1"
    local resolved="$raw"
    if command -v realpath >/dev/null 2>&1; then
        resolved=$(realpath "$raw" 2>/dev/null || printf '%s' "$raw")
    fi
    case "$resolved" in
        *[Mm]obile\ [Dd]ocuments*|*CloudDocs*|*iCloud\ Drive*|*iCloudDrive*|*iCloud*)
            printf '%s\n' "iCloud Drive"
            return 0
            ;;
        *[Oo]ne[Dd]rive*)
            printf '%s\n' "OneDrive"
            return 0
            ;;
    esac
    return 1
}

dex_have_cmd() {
    command -v "$1" >/dev/null 2>&1
}

dex_have_claude() {
    dex_have_cmd claude && return 0
    [ -d "/Applications/Claude.app" ] && return 0
    [ -d "$(dex_home_dir)/Applications/Claude.app" ] && return 0
    return 1
}

dex_have_cursor() {
    dex_have_cmd cursor && return 0
    [ -d "/Applications/Cursor.app" ] && return 0
    [ -d "$(dex_home_dir)/Applications/Cursor.app" ] && return 0
    return 1
}

dex_open_url() {
    local url="$1"
    if [ -n "${DEX_INSTALL_NO_OPEN:-}" ] || ! dex_is_interactive; then
        return 0
    fi
    if [ "$(uname -s 2>/dev/null)" = "Darwin" ] && dex_have_cmd open; then
        open "$url" >/dev/null 2>&1 || true
    elif dex_have_cmd xdg-open; then
        xdg-open "$url" >/dev/null 2>&1 || true
    elif dex_is_windows; then
        cmd.exe /c start "" "$url" >/dev/null 2>&1 || true
    fi
}

dex_open_folder() {
    local raw="$1"
    if [ -n "${DEX_INSTALL_NO_OPEN:-}" ]; then
        return 1
    fi
    if [ "$(uname -s 2>/dev/null)" = "Darwin" ] && dex_have_cmd open; then
        open "$raw"
        return 0
    fi
    if dex_have_cmd xdg-open; then
        xdg-open "$raw"
        return 0
    fi
    if dex_is_windows; then
        explorer.exe "$(dex_display_path "$raw")" >/dev/null 2>&1 || true
        return 0
    fi
    return 1
}

dex_beta_line() {
    printf '%s\n' "Dex is in beta right now, and the desktop and mobile apps are coming shortly. Sign up at heydex.ai/beta to get them first."
}

dex_copy_user_log() {
    local target="${DEX_TARGET:-$(pwd)}"
    if [ -n "${INSTALL_LOG:-}" ] && [ -f "$INSTALL_LOG" ] && [ -d "$target" ]; then
        cp "$INSTALL_LOG" "$target/install-log.txt" 2>/dev/null || true
    fi
}

dex_repo_url() {
    printf '%s\n' "${DEX_INSTALL_REPO:-https://github.com/davekilleen/dex.git}"
}

dex_repo_ref() {
    printf '%s\n' "${DEX_INSTALL_REF:-release}"
}

dex_same_path() {
    local a="$1" b="$2"
    if command -v realpath >/dev/null 2>&1; then
        a=$(realpath -m "$a" 2>/dev/null || printf '%s' "$a")
        b=$(realpath -m "$b" 2>/dev/null || printf '%s' "$b")
    fi
    [ "$a" = "$b" ]
}

dex_dir_is_empty() {
    local raw="$1"
    if [ ! -e "$raw" ]; then
        return 0
    fi
    [ -d "$raw" ] || return 1
    [ -z "$(ls -A "$raw" 2>/dev/null)" ]
}

# Feature-branch / PR tests never default into ~/Dex. Product default stays ~/Dex.
dex_default_target() {
    if [ -n "${DEX_INSTALL_DIR:-}" ]; then
        dex_expand_path "$DEX_INSTALL_DIR"
        return 0
    fi
    case "$(dex_repo_ref)" in
        release|main)
            printf '%s\n' "$(dex_home_dir)/Dex"
            ;;
        *)
            printf '%s\n' "$(dex_home_dir)/Dex-test"
            ;;
    esac
}

dex_script_checkout() {
    local self="${BASH_SOURCE[0]:-}"
    case "$self" in
        ""|bash|sh|-bash|-sh)
            return 1
            ;;
    esac
    local dir
    dir=$(cd "$(dirname "$self")" 2>/dev/null && pwd) || return 1
    if dex_is_checkout "$dir"; then
        printf '%s\n' "$dir"
        return 0
    fi
    return 1
}

# Clone into DEX_INSTALL_DIR / the chosen folder. Never clone during CI
# in-place runs (no DEX_INSTALL_DIR). Never treat the current directory as
# the target when an explicit folder was requested.
dex_should_bootstrap() {
    local target="${1:-}"
    if [ -z "$target" ]; then
        return 1
    fi
    if dex_is_checkout "$target"; then
        return 1
    fi
    if ! dex_is_interactive && [ -z "${DEX_INSTALL_DIR:-}" ]; then
        return 1
    fi
    return 0
}

dex_pause() {
    # Empty string is allowed so the caller can print the prompt themselves.
    dex_read_tty "${1-Press Enter to continue. }"
}

dex_write_open_me_next() {
    local target="${1:-${DEX_TARGET:-$(pwd)}}"
    local display claude_line
    display=$(dex_display_path "$target")
    if dex_have_cmd claude; then
        claude_line="In Terminal, run:  cd \"$target\" && claude"
    else
        claude_line="Open this folder in Claude Code or Cursor."
    fi
    cat > "$target/Open me next.md" <<EOF
# Open me next

Dex is installed in:

$display

## What to do now

1. $claude_line
2. Type: hi
3. If nothing happens, type: /setup

Claude Code in this folder treats even "hi" as setup. Cursor does not run those automatic hooks — use /setup there.

$(dex_beta_line)

Welcome aboard. Dave & Dex
EOF
}

dex_print_welcome() {
    echo "👋 Welcome to Dex, your AI chief of staff."
    echo ""
    echo "Thanks for being here. An AI chief of staff keeps your meetings, people,"
    echo "and priorities in one place so you can spend time on the work that matters."
    echo ""
    echo "Dave and the Dex team are genuinely delighted you're on this journey."
    echo ""
    echo "Setup happens from this text window (the 'terminal') and usually takes 5–10 minutes."
    echo ""
    dex_beta_line
    echo ""
    echo "Nothing has been downloaded yet. Press Enter to begin."
    dex_pause ""
}

dex_warn_cloud_folder() {
    local target="$1"
    local provider
    if provider=$(dex_cloud_provider "$target"); then
        echo ""
        echo "⚠️  That folder looks like it is inside $provider."
        echo "   Dex works best in a regular folder on this computer — not a synced"
        echo "   cloud folder. Files can go missing or lock Dex out of later setup steps."
        echo ""
        dex_read_tty "Press Enter to choose a different folder, or type yes to use it anyway: "
        case "$REPLY" in
            yes|YES|Yes)
                return 0
                ;;
            *)
                return 1
                ;;
        esac
    fi
    return 0
}

dex_choose_target() {
    local suggested display reply existing
    suggested=$(dex_default_target)
    while true; do
        display=$(dex_display_path "$suggested")
        echo "Step 1 of 5 — Where should Dex live?"
        echo ""
        echo "Suggested folder: $display"
        echo "(That's ${suggested/#$(dex_home_dir)/~})"
        if [ -n "${DEX_INSTALL_DIR:-}" ] || { [ "$(dex_repo_ref)" != "release" ] && [ "$(dex_repo_ref)" != "main" ]; }; then
            echo ""
            echo "This is a separate test folder. Your existing Dex install will not be changed."
        fi
        echo ""
        dex_read_tty "Press Enter to use this folder, or type another path: " "$suggested"
        reply=$(dex_expand_path "$REPLY")
        if [ -z "$reply" ]; then
            reply="$suggested"
        fi
        # Isolated / branch-test installs must not retarget the live ~/Dex folder.
        if [ -n "${DEX_INSTALL_DIR:-}" ] && dex_same_path "$reply" "$(dex_home_dir)/Dex" && ! dex_same_path "$reply" "$(dex_expand_path "$DEX_INSTALL_DIR")"; then
            echo ""
            echo "That is your existing Dex folder. This test install will not change it."
            echo "Using $(dex_display_path "$suggested") instead."
            echo ""
            reply="$suggested"
        fi
        if ! dex_warn_cloud_folder "$reply"; then
            suggested=$(dex_default_target)
            echo ""
            continue
        fi
        if dex_is_checkout "$reply"; then
            echo ""
            echo "Dex is already in that folder."
            dex_read_tty "Update this folder [U] or Choose another folder [C]: " "C"
            case "$REPLY" in
                U|u|update|Update)
                    DEX_TARGET="$reply"
                    return 0
                    ;;
                *)
                    echo ""
                    dex_read_tty "Type a different folder path: " "$(dex_home_dir)/Dex-test"
                    suggested=$(dex_expand_path "$REPLY")
                    echo ""
                    continue
                    ;;
            esac
        fi
        if [ -e "$reply" ] && [ ! -d "$reply" ]; then
            echo "That path exists and is not a folder. Please choose another."
            echo ""
            continue
        fi
        if [ -d "$reply" ] && ! dex_dir_is_empty "$reply" && ! dex_is_checkout "$reply"; then
            echo "That folder already has files, and they are not a Dex install."
            echo "Please choose an empty folder so nothing else is touched."
            echo ""
            continue
        fi
        DEX_TARGET="$reply"
        return 0
    done
}

dex_resolve_install_target() {
    local script_root
    if [ -n "${DEX_INSTALL_DIR:-}" ]; then
        if dex_is_interactive; then
            dex_choose_target
        else
            DEX_TARGET=$(dex_expand_path "$DEX_INSTALL_DIR")
        fi
        return 0
    fi
    if script_root=$(dex_script_checkout); then
        DEX_TARGET="$script_root"
        return 0
    fi
    if ! dex_is_interactive; then
        DEX_TARGET=$(pwd)
        return 0
    fi
    dex_choose_target
}

dex_print_check() {
    local ok="$1"
    local label="$2"
    if [ "$ok" = "1" ]; then
        echo "  ✓ $label"
    else
        echo "  ✗ $label"
    fi
}

dex_ensure_macos_clt() {
    case "${OSTYPE:-}" in
        darwin*) ;;
        *) return 0 ;;
    esac
    if xcode-select -p >/dev/null 2>&1; then
        return 0
    fi
    echo "macOS needs a small Apple tool set (Command Line Tools) before Git will work."
    echo "A window may appear. Click Install. If you click Cancel, come back here and retry."
    echo ""
    dex_pause "Press Enter to open that window. "
    xcode-select --install >/dev/null 2>&1 || true
    local waited=0
    while ! xcode-select -p >/dev/null 2>&1; do
        sleep 5
        waited=$((waited + 5))
        if [ "$waited" -ge 180 ]; then
            echo ""
            echo "That install window was closed, or it is taking longer than expected."
            dex_read_tty "Press Enter to try again, or type skip to continue without it: "
            case "$REPLY" in
                skip|SKIP|Skip)
                    return 1
                    ;;
            esac
            xcode-select --install >/dev/null 2>&1 || true
            waited=0
        fi
    done
    echo "✓ Command Line Tools are installed."
    echo ""
    return 0
}

dex_guide_missing_git() {
    echo ""
    echo "Git is the tool Dex uses to download and update itself. It is not installed yet."
    echo ""
    if dex_is_windows; then
        echo "1. Open https://git-scm.com/download/win"
        echo "2. Install Git for Windows (this also adds Git Bash)"
        echo "3. Close this window, open Git Bash, and run the same command again"
        dex_open_url "https://git-scm.com/download/win"
    else
        echo "1. Open https://git-scm.com"
        echo "2. Install Git, then come back here"
        dex_open_url "https://git-scm.com"
    fi
    echo ""
    dex_pause "Press Enter when that is done and I will check again. "
}

dex_guide_missing_node() {
    echo ""
    echo "Node.js is the engine Dex uses in the background. It is not installed yet."
    echo ""
    echo "1. Open https://nodejs.org"
    echo "2. Download the LTS version (the one marked LTS)"
    echo "3. Install it, then come back here"
    echo ""
    dex_open_url "https://nodejs.org"
    dex_pause "Press Enter when that is done and I will check again. "
}

dex_guide_missing_python() {
    echo ""
    echo "Python 3.11 or newer is required. The copy that came with this computer"
    echo "is often too old — on a Mac that is commonly Python 3.9, which is not enough."
    echo ""
    echo "1. Open https://www.python.org/downloads/"
    echo "2. Download Python 3.11 or newer"
    echo "3. Install it, then come back here"
    if dex_is_windows; then
        echo "4. On Windows, tick 'Add Python to PATH' during the install"
    fi
    echo ""
    echo "Opening claude.ai or a website is not the same as installing Python."
    echo ""
    dex_open_url "https://www.python.org/downloads/"
    dex_pause "Press Enter when that is done and I will check again. "
}

dex_guide_missing_claude() {
    echo ""
    echo "Claude Code is the app most people use with Dex. It needs a paid Claude plan."
    echo "Opening claude.ai in a browser is not the same thing."
    echo ""
    echo "If you use Cursor instead, you can continue without Claude Code."
    echo ""
    dex_open_url "https://claude.ai/download"
    dex_pause "Press Enter to continue. "
}

dex_node_major() {
    local raw
    raw=$(node -v 2>/dev/null | cut -d'v' -f2 | cut -d'.' -f1)
    printf '%s\n' "$raw"
}

dex_guided_preflight() {
    local git_ok=0 node_ok=0 python_ok=0 claude_ok=0 node_major
    dex_ensure_macos_clt || true
    while true; do
        git_ok=0
        node_ok=0
        python_ok=0
        claude_ok=0
        dex_have_cmd git && git_ok=1
        if dex_have_cmd node; then
            node_major=$(dex_node_major)
            if [ -n "$node_major" ] && [ "$node_major" -ge 18 ]; then
                node_ok=1
            fi
        fi
        if dex_resolve_python; then
            python_ok=1
        fi
        dex_have_claude && claude_ok=1
        echo "Here is what this computer has:"
        echo ""
        if [ "$claude_ok" = "1" ]; then
            dex_print_check 1 "Claude Code"
        else
            dex_print_check 0 "Claude Code (optional if you use Cursor)"
        fi
        if [ "$git_ok" = "1" ]; then
            dex_print_check 1 "Git $(git --version 2>/dev/null | cut -d' ' -f3)"
        else
            dex_print_check 0 "Git"
        fi
        if [ "$node_ok" = "1" ]; then
            dex_print_check 1 "Node.js $(node -v 2>/dev/null)"
        else
            dex_print_check 0 "Node.js 18+"
        fi
        if [ "$python_ok" = "1" ]; then
            dex_print_check 1 "Python $PYTHON_VERSION"
        else
            dex_print_check 0 "Python 3.11+"
        fi
        echo ""
        if [ "$git_ok" != "1" ]; then
            dex_guide_missing_git
            continue
        fi
        if [ "$node_ok" != "1" ]; then
            dex_guide_missing_node
            continue
        fi
        if [ "$python_ok" != "1" ]; then
            dex_guide_missing_python
            continue
        fi
        if [ "$claude_ok" != "1" ] && ! dex_have_cursor; then
            dex_guide_missing_claude
        fi
        if [ "$python_ok" = "1" ] && ! dex_support_python_probe; then
            exit 1
        fi
        break
    done
}

dex_bootstrap_clone() {
    local target="$1"
    local repo ref
    repo=$(dex_repo_url)
    ref=$(dex_repo_ref)
    mkdir -p "$(dirname "$target")"
    if dex_is_checkout "$target"; then
        return 0
    fi
    if [ -e "$target" ] && ! dex_dir_is_empty "$target"; then
        echo "That folder already has files, and they are not a Dex install."
        echo "Nothing was changed there."
        return 1
    fi
    if ! dex_have_cmd git; then
        echo "Git is required to download Dex."
        return 1
    fi
    echo "Downloading Dex ($ref) into $(dex_display_path "$target")..."
    if [ -d "$target" ]; then
        if ! git clone --branch "$ref" --single-branch "$repo" "$target"; then
            echo "Could not download Dex. The folder was left as it was."
            return 1
        fi
    else
        if ! git clone --branch "$ref" --single-branch "$repo" "$target"; then
            echo "Could not download Dex. Nothing was left behind outside that folder."
            return 1
        fi
    fi
    if ! dex_is_checkout "$target"; then
        echo "The download finished, but this is not a complete Dex folder."
        return 1
    fi
    return 0
}

dex_print_interactive_finish() {
    local display next
    display=$(dex_display_path "${DEX_TARGET:-$(pwd)}")
    echo ""
    echo "🎉 Dex is installed!"
    echo ""
    echo "Your Dex folder is:"
    echo "  $display"
    echo ""
    echo "What to do next:"
    if dex_have_cmd claude; then
        echo "  1. In this window, run:  cd \"$DEX_TARGET\" && claude"
        echo "  2. Type: hi"
        echo "  3. If nothing happens, type: /setup"
        echo ""
        dex_read_tty "Start Claude Code in that folder now? [Y/n] " "Y"
        case "$REPLY" in
            Y|y|yes|Yes|"")
                (cd "$DEX_TARGET" && claude) || true
                ;;
        esac
    elif dex_have_claude || dex_have_cursor; then
        echo "  1. Open that folder in Claude or Cursor"
        echo "  2. Type: hi"
        echo "  3. If nothing happens, type: /setup"
        echo ""
        echo "Cursor does not run Claude Code's automatic setup hooks — /setup is the reliable next step there."
    else
        echo "  1. Open that folder in Claude Code or Cursor"
        echo "  2. Type: hi"
        echo "  3. If nothing happens, type: /setup"
    fi
    echo ""
    dex_beta_line
    echo ""
    dex_write_open_me_next "$DEX_TARGET"
    echo "A short reminder is saved in that folder as 'Open me next'."
    echo ""
    if dex_is_interactive; then
        dex_read_tty "Open your Dex folder now? [Y/n] " "Y"
        case "$REPLY" in
            Y|y|yes|Yes|"")
                dex_open_folder "$DEX_TARGET" || echo "Open this folder yourself: $display"
                ;;
        esac
    fi
    echo ""
    echo "Welcome aboard. Dave & Dex"
}

dex_print_legacy_finish() {
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
}

dex_install_on_error() {
    local status=$?
    trap - EXIT
    if [ "$status" -eq 0 ]; then
        return 0
    fi
    echo ""
    echo "Setup did not finish."
    dex_copy_user_log
    if [ -n "${DEX_TARGET:-}" ] && [ -f "$DEX_TARGET/install-log.txt" ]; then
        echo "Please send this file to dave@heydex.ai:"
        echo "  $(dex_display_path "$DEX_TARGET/install-log.txt")"
    elif [ -n "${INSTALL_LOG:-}" ] && [ -f "$INSTALL_LOG" ]; then
        echo "Please send this file to dave@heydex.ai:"
        echo "  $(dex_display_path "$INSTALL_LOG")"
    else
        echo "Please write to dave@heydex.ai and mention what you saw on screen."
    fi
    exit "$status"
}

if [ "${DEX_INSTALL_LIB_ONLY:-}" = "1" ] || [ "${DEX_SUPPORT_LIB_ONLY:-}" = "1" ]; then
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

DEX_TARGET=""
DEX_PREFLIGHT_DONE=""

if dex_is_interactive; then
    trap dex_install_on_error EXIT
    dex_print_welcome
fi

dex_resolve_install_target

if [ -n "${DEX_INSTALL_DIR:-}" ]; then
    echo "Isolated install folder: $(dex_display_path "$DEX_TARGET")"
    echo "Your existing Dex folder and global app settings are not changed."
    echo ""
fi

if dex_is_interactive; then
    echo ""
    echo "Step 2 of 5 — Checking your computer"
    echo ""
    dex_guided_preflight
    DEX_PREFLIGHT_DONE=1
fi

# Never download into a new folder when Git / Node / Python are missing.
if [ "${DEX_PREFLIGHT_DONE:-}" != "1" ] && dex_should_bootstrap "$DEX_TARGET"; then
    if ! command -v git >/dev/null 2>&1; then
        echo "❌ Git is not installed"
        echo "Git is required to clone the repository and manage updates."
        exit 1
    fi
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
    if ! dex_resolve_python; then
        echo "❌ Python 3.11+ not found"
        exit 1
    fi
fi

if dex_should_bootstrap "$DEX_TARGET"; then
    if dex_is_interactive; then
        echo ""
        echo "Step 3 of 5 — Downloading Dex"
        echo ""
    fi
    if ! dex_bootstrap_clone "$DEX_TARGET"; then
        exit 1
    fi
elif dex_is_interactive; then
    echo ""
    echo "Step 3 of 5 — Downloading Dex"
    echo "This folder already has Dex. Using the files that are here."
    echo ""
fi

cd "$DEX_TARGET"

dex_init_install_log
dex_log "starting install target=$DEX_TARGET ref=$(dex_repo_ref)"
if ! dex_support_shell_precheck; then
    exit 1
fi

if ! dex_is_interactive; then
    echo "🚀 Setting up Dex..."
    echo ""
fi

if dex_is_interactive; then
    echo "Step 4 of 5 — Setting up your workspace"
    echo "This part is quiet on purpose. A full log is saved if anything goes wrong."
    echo ""
fi

# Check for Command Line Tools on macOS (required for git)
if [[ "$OSTYPE" == "darwin"* ]] && [ "${DEX_PREFLIGHT_DONE:-}" != "1" ]; then
    if ! xcode-select -p >/dev/null 2>&1; then
        echo "⚠️  Command Line Developer Tools not found"
        echo ""
        echo "macOS will now prompt you to install them - this is required for git."
        echo "Click 'Install' when the dialog appears (takes 2-3 minutes)."
        echo ""
        if dex_is_interactive; then
            dex_pause "Press Enter to continue..."
        elif [ -z "${DEX_INSTALL_NONINTERACTIVE:-}" ]; then
            read -r
        fi

        # Trigger the install prompt
        xcode-select --install >/dev/null 2>&1 || true

        echo ""
        echo "⏳ Waiting for Command Line Tools installation..."
        echo "   (This window will continue once installation completes)"
        echo ""

        # Bounded wait — never hang if the user cancels the Apple dialog
        waited=0
        while ! xcode-select -p >/dev/null 2>&1; do
            sleep 5
            waited=$((waited + 5))
            if [ "$waited" -ge 180 ]; then
                echo "That install window was closed, or it is taking longer than expected."
                if dex_is_interactive; then
                    dex_read_tty "Press Enter to try again, or type skip: "
                    case "$REPLY" in
                        skip|SKIP|Skip)
                            break
                            ;;
                    esac
                    xcode-select --install >/dev/null 2>&1 || true
                    waited=0
                    continue
                fi
                echo "Run this installer again after Command Line Tools are installed."
                exit 1
            fi
        done

        if xcode-select -p >/dev/null 2>&1; then
            echo "✅ Command Line Tools installed!"
            echo ""
        fi
    fi
fi

# Only rename remotes inside the chosen Dex folder — never the caller's cwd
# when this script was piped from curl.
if git remote -v >/dev/null 2>&1 && git remote -v | grep -q "davekilleen/[Dd]ex"; then
    git remote rename origin upstream >/dev/null 2>&1 || true
fi

# Check Git first (required for repo operations)
if [ "${DEX_PREFLIGHT_DONE:-}" = "1" ]; then
    if ! dex_resolve_python; then
        echo "❌ Python 3.11+ not found"
        exit 1
    fi
    dex_resolve_venv_paths
elif ! command -v git >/dev/null 2>&1; then
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
    if ! dex_support_python_probe; then
        exit 1
    fi

    dex_resolve_venv_paths
else
    echo "❌ Python 3.11+ not found"
    echo ""
    echo "Python 3.11+ is required for MCP servers (task sync across all files)."
    echo "Without it, tasks won't sync between meeting notes, person pages, and Tasks.md."
    echo ""
    if dex_is_windows; then
        echo "Install Python 3.11+:"
        echo "  1. Download from https://www.python.org/downloads/"
        echo "  2. Run the installer"
        echo "  3. ⚠️  IMPORTANT: Check 'Add Python to PATH' during installation"
        echo "  4. Restart your terminal"
        echo "  5. Run ./install.sh again"
        echo "  The installer also looks for the Windows 'py -3' launcher."
        echo "  The Microsoft Store python3 placeholder is ignored."
    else
        echo "Install Python 3.11+:"
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

# Install Node dependencies from the committed lockfile only.
echo ""
echo "📦 Installing dependencies..."
if [ -f pnpm-lock.yaml ] && command -v pnpm >/dev/null 2>&1; then
    dex_log "----- pnpm install --frozen-lockfile -----"
    if dex_is_interactive; then
        if ! dex_run_logged "pnpm install --frozen-lockfile" pnpm install --frozen-lockfile; then
            dex_show_logged_failure "Could not install Node dependencies"
            exit 1
        fi
    elif ! pnpm install --frozen-lockfile > >(tee -a "$INSTALL_LOG") 2>&1; then
        dex_show_logged_failure "Could not install Node dependencies"
        exit 1
    fi
elif [ -f package-lock.json ] && command -v npm >/dev/null 2>&1; then
    dex_log "----- npm ci -----"
    if dex_is_interactive; then
        if ! dex_run_logged "npm ci" npm ci; then
            dex_show_logged_failure "Could not install Node dependencies"
            exit 1
        fi
    elif ! npm ci > >(tee -a "$INSTALL_LOG") 2>&1; then
        dex_show_logged_failure "Could not install Node dependencies"
        exit 1
    fi
else
    echo "❌ Need npm with package-lock.json, or pnpm with pnpm-lock.yaml"
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
            echo "  $VENV_PIP install --require-hashes -r core/mcp/requirements.hash.txt"
            echo ""
            dex_prompt_continue
        fi
    fi

    dex_resolve_venv_paths
    if ! dex_support_verify_venv_python; then
        exit 1
    fi

    HASHED_REQUIREMENTS="$(dex_hashed_requirements)"
    if [ ! -f "$HASHED_REQUIREMENTS" ]; then
        dex_show_logged_failure "Hashed Python requirements are missing ($HASHED_REQUIREMENTS)"
        exit 1
    fi

    # Install dependencies into venv from the hashed pin file only.
    if [ -f "$VENV_PIP" ] && dex_run_logged "pip install" "$VENV_PIP" install --require-hashes -r "$HASHED_REQUIREMENTS" --quiet; then
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
        echo "  $VENV_PIP install --require-hashes -r $HASHED_REQUIREMENTS"
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
    # ZIP bundles compose vault-mode .gitignore at packaging time. A cloned
    # product checkout still has the product ignore file, which hides notes
    # folders until the first /dex-update. Compose here so a fresh install
    # tracks user folders from the start. Doctor reports the same gap if
    # this step is skipped.
    GITIGNORE_COMPOSER="scripts/compose-vault-gitignore.py"
    if [ -f "$GITIGNORE_COMPOSER" ] && [ -f ".gitignore" ]; then
        COMPOSE_PYTHON="$PYTHON_CMD"
        if [ -n "$VENV_PYTHON" ] && [ -f "$VENV_PYTHON" ]; then
            COMPOSE_PYTHON="$VENV_PYTHON"
        fi
        if [ -n "$COMPOSE_PYTHON" ] && dex_run_logged "compose-vault-gitignore" "$COMPOSE_PYTHON" "$GITIGNORE_COMPOSER" ".gitignore"; then
            echo "   Your notes folders stay in your vault history from the start"
        else
            echo "⚠️  Dex could not finish making your notes folders trackable."
            echo "   Your files are still here. Run /dex-update, or run /dex-doctor to see the next step."
        fi
    fi
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
if dex_is_interactive; then
    echo ""
    echo "Step 5 of 5 — Final checks"
    echo ""
    trap - EXIT
    dex_print_interactive_finish
else
    dex_print_legacy_finish
fi
