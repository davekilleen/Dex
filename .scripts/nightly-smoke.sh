#!/bin/bash
# Nightly smoke worker. This script is started by launchd with a bare
# environment: PATH may be just the system locations, HOME may be missing,
# and the log folder the job writes to may have been deleted since install.
# macOS launchd reports exit 78 as "this job's definition is wrong", so this
# script never returns 78.

set -e

# launchd user agents usually set HOME. Bootstrap, CI, and some SSH sessions
# do not. The breadcrumb, ~/Library/Logs, and Python's idea of a home folder
# all need it.
if [ -z "${HOME:-}" ]; then
    _user=""
    if [ -n "${LOGNAME:-}" ]; then
        _user="$LOGNAME"
    elif [ -n "${USER:-}" ]; then
        _user="$USER"
    elif command -v id >/dev/null 2>&1; then
        _user="$(id -un)"
    fi
    if [ -n "$_user" ]; then
        _home="$(eval echo "~${_user}")"
        if [ -n "$_home" ] && [ "$_home" != "~${_user}" ] && [ -d "$_home" ]; then
            HOME="$_home"
            export HOME
        fi
    fi
    unset _user _home
fi

# Prefer the vault the job definition already knows (the plist sets this),
# then the install breadcrumb, then this script's own location.
if [ -z "${VAULT_PATH:-}" ] || [ ! -d "${VAULT_PATH:-}" ]; then
    VAULT_PATH=""
    BREADCRUMB="${HOME:-}/.config/dex/vault-path"
    if [ -n "${HOME:-}" ] && [ -f "$BREADCRUMB" ]; then
        VAULT_PATH="$(tr -d '[:space:]' < "$BREADCRUMB")"
    fi
fi

if [ -z "${VAULT_PATH:-}" ] || [ ! -d "${VAULT_PATH:-}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    VAULT_PATH="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

# launchd opens StandardOutPath before this script starts. If that folder is
# missing the job never runs and launchd reports 78. Recreate both write
# locations so a later retry, a manual run, and the success receipt still
# work after someone deletes the logs folder.
mkdir -p "$VAULT_PATH/.scripts/logs"
if [ -n "${HOME:-}" ]; then
    mkdir -p "$HOME/Library/Logs/Dex"
fi

# Resolve an absolute Python 3.11+ interpreter. A bare "python3" depends on
# PATH; launchd's PATH puts /usr/bin first, where macOS ships an Xcode stub
# or an older CLT python. Pinning a machine path in the plist also goes
# stale after a Python upgrade. Resolve at runtime instead.
_python_supported() {
    [ -n "${1:-}" ] && [ -x "$1" ] && "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

PYTHON=""
if _python_supported "${DEX_PYTHON:-}"; then
    PYTHON="$DEX_PYTHON"
elif _python_supported "$VAULT_PATH/.venv/bin/python"; then
    PYTHON="$VAULT_PATH/.venv/bin/python"
else
    for _candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
        if _python_supported "$_candidate"; then
            PYTHON="$_candidate"
            break
        fi
    done
fi
if [ -z "$PYTHON" ]; then
    _from_path="$(command -v python3 2>/dev/null || true)"
    if _python_supported "$_from_path"; then
        PYTHON="$_from_path"
    fi
fi
unset _candidate _from_path

if [ -z "$PYTHON" ]; then
    echo "nightly smoke: no usable Python 3.11+ interpreter found" >&2
    exit 1
fi

# Make node discoverable, the same way PYTHON is resolved above.
#
# smoke.py syntax-checks Dex's .cjs hooks with node, and finds node by looking
# on the inherited PATH. launchd hands a scheduled job a minimal PATH that does
# not include either Homebrew prefix, so on a normal Mac node is invisible here
# even though it works in every terminal. The hooks journey then reports
# UNKNOWN rather than BROKEN, so nightly hook checking can be dead for months
# without anything looking wrong.
#
# Appending is deliberate: anything already on PATH keeps priority, and the
# validated-tool checks in core/utils/release_channel.py still decide what is
# safe to use. This only widens where node may be found, never what is trusted.
if ! command -v node >/dev/null 2>&1; then
    for NODE_DIR in /opt/homebrew/bin /usr/local/bin; do
        if [ -x "$NODE_DIR/node" ]; then
            PATH="$PATH:$NODE_DIR"
            export PATH
            break
        fi
    done
fi

_py_dir="$(dirname "$PYTHON")"
case ":$PATH:" in
    *":$_py_dir:"*) ;;
    *) PATH="$PATH:$_py_dir"; export PATH ;;
esac
unset _py_dir

# If HOME is still empty, give Python a writable home so Path.home() works.
if [ -z "${HOME:-}" ]; then
    HOME="$VAULT_PATH"
    export HOME
fi

cd "$VAULT_PATH"
export VAULT_PATH
set +e
"$PYTHON" core/utils/smoke.py --json --ledger
SMOKE_STATUS=$?
set -e

if [ -f "System/.smoke-last-run.json" ]; then
    "$PYTHON" core/utils/health_telemetry.py \
        --report "System/.smoke-last-run.json" \
        --vault "$VAULT_PATH" \
        --repo "$VAULT_PATH" \
        --channel "stable" >/dev/null 2>&1 || true
fi

# Never leak 78. launchd operators treat that as a broken job definition,
# which hides a real checkup failure (or a child that used the sysexits
# configuration code).
if [ "$SMOKE_STATUS" -eq 78 ]; then
    echo "nightly smoke: checkup returned 78; remapping to 1 so this is not reported as a configuration error" >&2
    exit 1
fi

if [ "$SMOKE_STATUS" -ne 0 ]; then
    exit "$SMOKE_STATUS"
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] nightly smoke completed" >> .scripts/logs/smoke-nightly.log

# Record completion separately from the report. SessionStart requires both a
# clean report and this post-success marker, so an interrupted/partial run can
# never suppress the next retry.
SUCCESS_MARKER="System/.dex/session-health-success.json"
SUCCESS_TEMP="System/.dex/.session-health-success.$$.json"
trap 'rm -f "$SUCCESS_TEMP"' EXIT
mkdir -p "$(dirname "$SUCCESS_MARKER")"
printf '{"schema_version":1,"local_date":"%s","completed_at":"%s"}\n' \
    "$(date +%Y-%m-%d)" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$SUCCESS_TEMP"
mv "$SUCCESS_TEMP" "$SUCCESS_MARKER"
trap - EXIT
