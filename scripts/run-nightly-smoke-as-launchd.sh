#!/bin/bash
# Run the nightly smoke worker with the environment the shipped Launch Agent
# would use. This Linux/dev VM cannot load launchd, so CI on macos-latest
# (and local proof) simulates the job: render the plist, create the log
# folders launchd requires before start, then exec ProgramArguments with
# only the environment the job definition lists plus the few keys launchd
# itself supplies (TMPDIR, USER, LOGNAME).
#
# Usage: scripts/run-nightly-smoke-as-launchd.sh [--vault PATH] [--home PATH]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VAULT="$REPO_ROOT"
HOME_DIR="${HOME:-}"

while [ "${1:-}" != "" ]; do
    case "$1" in
        --vault)
            VAULT="${2:?--vault requires a path}"
            shift 2
            ;;
        --home)
            HOME_DIR="${2:?--home requires a path}"
            shift 2
            ;;
        *)
            echo "Usage: $0 [--vault PATH] [--home PATH]" >&2
            exit 2
            ;;
    esac
done

if [ -z "$HOME_DIR" ]; then
    echo "run-nightly-smoke-as-launchd: HOME is required (pass --home)" >&2
    exit 2
fi

TEMPLATE="$REPO_ROOT/.scripts/com.dex.smoke-nightly.plist.template"
WORKER="$VAULT/.scripts/nightly-smoke.sh"
if [ ! -f "$TEMPLATE" ]; then
    echo "missing $TEMPLATE" >&2
    exit 2
fi
if [ ! -f "$WORKER" ]; then
    echo "missing $WORKER" >&2
    exit 2
fi

RENDERED="$(mktemp)"
trap 'rm -f "$RENDERED"' EXIT
sed -e "s|__VAULT_PATH__|$VAULT|g" -e "s|__HOME__|$HOME_DIR|g" \
    "$TEMPLATE" > "$RENDERED"

if command -v plutil >/dev/null 2>&1; then
    plutil -lint "$RENDERED" >/dev/null
fi

# The installer creates these. launchd exits 78 if StandardOutPath's parent
# is missing, so refuse to pretend the job would start without them.
mkdir -p "$VAULT/.scripts/logs" "$HOME_DIR/Library/Logs/Dex"

EVAL_SCRIPT="$(python3 - "$RENDERED" <<'PY'
import plistlib
import shlex
import sys
from pathlib import Path

data = plistlib.loads(Path(sys.argv[1]).read_bytes())
env = data.get("EnvironmentVariables") or {}
args = data.get("ProgramArguments") or []
if len(args) != 2 or args[0] != "/bin/bash" or not args[1]:
    raise SystemExit("ProgramArguments must be ['/bin/bash', '<vault>/.scripts/nightly-smoke.sh']")
stdout = data.get("StandardOutPath") or ""
stderr = data.get("StandardErrorPath") or ""
wd = data.get("WorkingDirectory") or ""
print("LAUNCHD_PATH=" + shlex.quote(env.get("PATH", "")))
print("LAUNCHD_HOME=" + shlex.quote(env.get("HOME", "")))
print("LAUNCHD_VAULT=" + shlex.quote(env.get("VAULT_PATH", "")))
print("LAUNCHD_WD=" + shlex.quote(wd))
print("LAUNCHD_STDOUT=" + shlex.quote(stdout))
print("LAUNCHD_STDERR=" + shlex.quote(stderr))
print("LAUNCHD_ARGV0=" + shlex.quote(args[0]))
print("LAUNCHD_ARGV1=" + shlex.quote(args[1]))
PY
)"
eval "$EVAL_SCRIPT"

for required in LAUNCHD_PATH LAUNCHD_HOME LAUNCHD_VAULT LAUNCHD_WD \
        LAUNCHD_STDOUT LAUNCHD_ARGV0 LAUNCHD_ARGV1; do
    eval "value=\${$required:-}"
    if [ -z "$value" ]; then
        echo "rendered plist is missing $required" >&2
        exit 2
    fi
done

for log_path in "$LAUNCHD_STDOUT" "$LAUNCHD_STDERR"; do
    parent="$(dirname "$log_path")"
    if [ ! -d "$parent" ]; then
        echo "launchd would exit 78: StandardOut/Error parent missing: $parent" >&2
        exit 1
    fi
done

if [ ! -d "$LAUNCHD_WD" ]; then
    echo "launchd would exit 78: WorkingDirectory missing: $LAUNCHD_WD" >&2
    exit 1
fi

if [ ! -x "$LAUNCHD_ARGV0" ]; then
    echo "launchd would exit 78: ProgramArguments[0] is not executable: $LAUNCHD_ARGV0" >&2
    exit 1
fi

if [ ! -f "$LAUNCHD_ARGV1" ]; then
    echo "launchd would exit 78: ProgramArguments[1] is missing: $LAUNCHD_ARGV1" >&2
    exit 1
fi

cd "$LAUNCHD_WD"
# env -i is the launchd-shaped environment: only what the plist lists, plus
# the keys launchd itself supplies on a real Mac (TMPDIR, USER, LOGNAME).
# No inherited CI PATH, no interactive-shell Homebrew profile.
exec env -i \
    PATH="$LAUNCHD_PATH" \
    HOME="$LAUNCHD_HOME" \
    VAULT_PATH="$LAUNCHD_VAULT" \
    TMPDIR="${TMPDIR:-/tmp}" \
    USER="${USER:-$(id -un)}" \
    LOGNAME="${LOGNAME:-${USER:-$(id -un)}}" \
    LANG=C \
    LC_ALL=C \
    "$LAUNCHD_ARGV0" "$LAUNCHD_ARGV1"
