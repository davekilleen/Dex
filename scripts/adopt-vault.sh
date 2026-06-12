#!/usr/bin/env bash
# Dex: adopt an existing vault (continue from Dex Desktop).
#
# Sets up open-source Dex AROUND an existing vault without moving, modifying,
# or deleting anything the user created. It downloads a pinned release archive
# into temporary staging OUTSIDE the vault, verifies its SHA-256 checksum
# before expanding anything, then copies in runtime scaffolding only:
#   core/  .claude/  .agents/  scripts/  docs/  root-level config files
#   plus two System templates the runtime needs
#     (System/user-profile-template.yaml, System/.mcp.json.example)
# It never copies anything from the release's numbered content folders
# (00- through 07-), never writes into .git, and never modifies or deletes
# an existing file: collisions are skipped and recorded.
#
# Usage (the Dex Desktop app renders this command with real values):
#   adopt-vault.sh --vault <path> --tag <release-tag> --checksum <sha256>
#
# Options:
#   --vault PATH        Target vault directory (required)
#   --tag TAG           Pinned dex-core release tag (required)
#   --checksum SHA256   Expected SHA-256 of the release archive (required)
#   --archive-url URL   Where to fetch the archive. Defaults to the GitHub
#                       archive URL for TAG. Accepts http(s) URLs, file://
#                       URLs, and plain local file paths.
#   --no-install        Skip running install.sh after the overlay
#   --help              Show this help
#
# Environment overrides:
#   DEX_ADOPT_REPO         GitHub repo slug (default: davekilleen/Dex)
#   DEX_ADOPT_ARCHIVE_URL  Same as --archive-url
#   DEX_ADOPT_LOG_DIR      Adoption log directory (default: ~/.dex/adopt).
#                          Must be outside the vault.
#
# Exit codes:
#   0 success (including verify-and-report no-op re-runs)
#   2 preflight refusal (target unrecognized or already a dex-core checkout)
#   3 download or fetch failure (vault untouched)
#   4 checksum mismatch (archive rejected before expansion, vault untouched)
#   5 release archive incomplete (vault untouched)
#   6 overlay or verification error
#   64 usage error
#
# Re-run behavior: after success it verifies and reports without downloading.
# After a partial failure it repairs by copying only what is missing from a
# fresh verified staging. Re-runs never duplicate or overwrite user content.

set -u

REPO_SLUG="${DEX_ADOPT_REPO:-davekilleen/Dex}"
LOG_DIR="${DEX_ADOPT_LOG_DIR:-$HOME/.dex/adopt}"
VAULT=""
TAG=""
CHECKSUM=""
ARCHIVE_URL="${DEX_ADOPT_ARCHIVE_URL:-}"
RUN_INSTALL=1

# Runtime scaffolding directories copied from the release. Release archives
# honor .gitattributes export-ignore, so some (scripts/) may be absent there;
# whatever the sealed release carries within these bounds is copied.
OVERLAY_DIRS="core .claude .agents scripts docs"
# System template files the runtime needs (config templates, never content).
SYSTEM_TEMPLATE_FILES="System/user-profile-template.yaml System/.mcp.json.example"
# Paths that must exist for the vault to count as a complete adoption,
# and for a release archive to count as complete after expansion. Matches
# what tag archives actually contain (dev-only paths are export-ignored).
REQUIRED_PATHS="core/paths.py core/mcp/onboarding_server.py install.sh requirements.txt .claude .agents docs"
# Numbered content folders. Nothing is ever copied into these.
CONTENT_DIRS="00-Inbox 01-Quarter_Goals 02-Week_Priorities 03-Tasks 04-Projects 05-Areas 06-Resources 07-Archives"

STAGING=""
LOG_FILE=""
COPIED=0
SKIPPED=0
SKIP_SHOWN=0

usage() {
    sed -n '2,45p' "$0" | sed 's/^# \{0,1\}//'
}

say() {
    printf '%s\n' "$*"
}

json_escape() {
    # Escape backslashes and double quotes for JSON string values.
    _s=${1//\\/\\\\}
    _s=${_s//\"/\\\"}
    printf '%s' "$_s"
}

log_event() {
    # log_event <action> <detail> [path]
    if [ -z "$LOG_FILE" ]; then
        return 0
    fi
    _ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    _action=$(json_escape "$1")
    _detail=$(json_escape "$2")
    _path=$(json_escape "${3:-}")
    printf '{"ts":"%s","action":"%s","detail":"%s","path":"%s"}\n' \
        "$_ts" "$_action" "$_detail" "$_path" >> "$LOG_FILE"
}

cleanup() {
    if [ -n "$STAGING" ] && [ -d "$STAGING" ]; then
        rm -rf "$STAGING"
    fi
}
trap cleanup EXIT

fail() {
    # fail <exit-code> <message>
    _code="$1"
    shift
    say ""
    say "$*"
    log_event "abort" "$*"
    exit "$_code"
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

while [ $# -gt 0 ]; do
    case "$1" in
        --vault)
            VAULT="${2:-}"
            shift 2 || { usage; exit 64; }
            ;;
        --tag)
            TAG="${2:-}"
            shift 2 || { usage; exit 64; }
            ;;
        --checksum)
            CHECKSUM="${2:-}"
            shift 2 || { usage; exit 64; }
            ;;
        --archive-url)
            ARCHIVE_URL="${2:-}"
            shift 2 || { usage; exit 64; }
            ;;
        --no-install)
            RUN_INSTALL=0
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            say "Unknown option: $1"
            say "Run with --help to see usage."
            exit 64
            ;;
    esac
done

if [ -z "$VAULT" ] || [ -z "$TAG" ] || [ -z "$CHECKSUM" ]; then
    say "Missing required options. This command needs --vault, --tag, and --checksum."
    say "The Dex Desktop app shows the full command with these filled in for you."
    exit 64
fi

CHECKSUM=$(printf '%s' "$CHECKSUM" | tr 'A-F' 'a-f')
case "$CHECKSUM" in
    *[!0-9a-f]*)
        say "The checksum does not look like a SHA-256 value (64 hex characters expected)."
        exit 64
        ;;
esac
if [ "${#CHECKSUM}" -ne 64 ]; then
    say "The checksum does not look like a SHA-256 value (64 hex characters expected)."
    exit 64
fi

# ---------------------------------------------------------------------------
# Preflight: never touches the vault, refuses anything unrecognizable
# ---------------------------------------------------------------------------

if [ ! -d "$VAULT" ]; then
    say "That folder does not exist: $VAULT"
    say "Nothing was changed. Check the path and try again."
    exit 2
fi
VAULT=$(cd "$VAULT" && pwd)

# Resolve the log location and make sure it lives outside the vault.
case "$LOG_DIR" in
    "$VAULT"|"$VAULT"/*)
        say "The adoption log location ($LOG_DIR) is inside the vault."
        say "The log must live outside your vault. Unset DEX_ADOPT_LOG_DIR or point it elsewhere."
        exit 64
        ;;
esac
mkdir -p "$LOG_DIR" || {
    say "Could not create the log folder at $LOG_DIR. Nothing was changed."
    exit 64
}
VAULT_KEY=$(printf '%s' "$VAULT" | cksum | awk '{print $1}')
LOG_FILE="$LOG_DIR/$(basename "$VAULT")-$VAULT_KEY.jsonl"
HAD_PRIOR_LOG=0
if [ -f "$LOG_FILE" ]; then
    HAD_PRIOR_LOG=1
fi

log_event "run-start" "tag=$TAG vault=$VAULT"
say "Dex vault adoption"
say "Vault: $VAULT"
say "Release: $TAG"
say "Adoption log: $LOG_FILE"
say ""

# Report whether Claude Code is installed. Information only, never a block.
if command -v claude >/dev/null 2>&1; then
    say "Claude Code: found on this machine."
    log_event "preflight" "claude-code-found"
else
    say "Claude Code: not found yet. The adoption still works; install Claude Code"
    say "afterwards from claude.com/claude-code to start talking to Dex."
    log_event "preflight" "claude-code-missing"
fi

MARKER_REL="System/.onboarding-complete"
MODE=""
if [ -f "$VAULT/$MARKER_REL" ] && grep -q '"adopted"[[:space:]]*:[[:space:]]*true' "$VAULT/$MARKER_REL" 2>/dev/null; then
    MODE="verify"
    log_event "preflight" "already-adopted-marker-found" "$MARKER_REL"
elif [ -e "$VAULT/System/routines" ]; then
    # What the desktop app reliably creates. Light-usage vaults (routines plus
    # as little as one content folder) are accepted here too.
    MODE="adopt"
    log_event "preflight" "desktop-vault-recognized" "System/routines"
elif [ "$HAD_PRIOR_LOG" -eq 1 ]; then
    # A previous adoption attempt was recorded for this exact folder, so a
    # partially copied overlay must not be mistaken for a dex-core checkout.
    MODE="adopt"
    log_event "preflight" "prior-adoption-log-found"
elif [ -f "$VAULT/core/paths.py" ] && [ -f "$VAULT/core/mcp/onboarding_server.py" ] && [ -f "$VAULT/install.sh" ]; then
    say ""
    say "This folder already contains the open-source Dex code itself (a dex-core"
    say "checkout), not a Dex Desktop vault. Adoption is for wrapping the open-source"
    say "machinery around a vault of notes, so there is nothing to do here."
    say "Nothing was changed."
    log_event "refuse" "target-is-dex-core-checkout"
    exit 2
else
    SHAPE_OK=0
    if [ -d "$VAULT/System" ]; then
        for _d in $CONTENT_DIRS; do
            if [ -d "$VAULT/$_d" ]; then
                SHAPE_OK=1
                break
            fi
        done
    fi
    if [ "$SHAPE_OK" -eq 1 ]; then
        MODE="adopt"
        log_event "preflight" "dex-vault-shape-recognized"
    else
        say ""
        say "This folder does not look like a Dex vault. A Dex Desktop vault has a"
        say "System folder (with routines inside) and numbered folders like 05-Areas."
        say "To be safe, nothing was changed."
        say "If you are sure this is your vault, check you pasted the command exactly"
        say "as the app showed it."
        log_event "refuse" "target-unrecognized"
        exit 2
    fi
fi

# ---------------------------------------------------------------------------
# Verification helper: which required pieces are missing from the vault?
# ---------------------------------------------------------------------------

missing_required() {
    _missing=""
    for _p in $REQUIRED_PATHS; do
        if [ ! -e "$VAULT/$_p" ]; then
            _missing="$_missing $_p"
        fi
    done
    printf '%s' "$_missing"
}

if [ "$MODE" = "verify" ]; then
    MISSING=$(missing_required)
    if [ -z "$MISSING" ]; then
        say ""
        say "This vault was already adopted and everything is in place."
        say "Verified: the open-source Dex machinery is present and your notes were"
        say "not touched by this check. Nothing needed to be downloaded or copied."
        log_event "verify" "already-adopted-complete"
        if [ "$RUN_INSTALL" -eq 1 ] && [ ! -d "$VAULT/.venv" ] && [ -f "$VAULT/install.sh" ]; then
            say ""
            say "Finishing setup (install step)..."
            log_event "install" "starting"
            if (cd "$VAULT" && bash install.sh < /dev/null); then
                log_event "install" "succeeded"
            else
                log_event "install" "failed"
                say ""
                say "The setup step did not finish. Your notes are untouched and the"
                say "adoption itself is complete. To finish setup, open Terminal in your"
                say "vault folder and run: bash install.sh"
            fi
        fi
        exit 0
    fi
    say ""
    say "This vault was adopted before, but some pieces are missing:"
    for _p in $MISSING; do
        say "  $_p"
    done
    say "Repairing from a fresh verified copy."
    log_event "verify" "gaps-found, repairing" "$MISSING"
fi

# ---------------------------------------------------------------------------
# Fetch the pinned release into staging OUTSIDE the vault, verify, expand
# ---------------------------------------------------------------------------

STAGING=$(mktemp -d "${TMPDIR:-/tmp}/dex-adopt.XXXXXX") || {
    say "Could not create a temporary staging folder. Nothing was changed."
    exit 3
}
case "$STAGING" in
    "$VAULT"/*)
        fail 3 "Temporary staging resolved inside the vault, stopping to be safe. Nothing was changed."
        ;;
esac

if [ -z "$ARCHIVE_URL" ]; then
    ARCHIVE_URL="https://github.com/$REPO_SLUG/archive/refs/tags/$TAG.tar.gz"
fi
ARCHIVE_FILE="$STAGING/release.tar.gz"

say ""
say "Fetching the sealed Dex release ($TAG)..."
log_event "fetch" "starting" "$ARCHIVE_URL"

FETCH_OK=0
case "$ARCHIVE_URL" in
    file://*)
        _local_path="${ARCHIVE_URL#file://}"
        if [ -f "$_local_path" ] && cp "$_local_path" "$ARCHIVE_FILE"; then
            FETCH_OK=1
        fi
        ;;
    http://*|https://*)
        if command -v curl >/dev/null 2>&1; then
            if curl -fsSL --retry 2 -o "$ARCHIVE_FILE" "$ARCHIVE_URL"; then
                FETCH_OK=1
            fi
        else
            fail 3 "curl is not available on this machine, so the release could not be downloaded. Nothing was changed."
        fi
        ;;
    *)
        if [ -f "$ARCHIVE_URL" ] && cp "$ARCHIVE_URL" "$ARCHIVE_FILE"; then
            FETCH_OK=1
        fi
        ;;
esac

if [ "$FETCH_OK" -ne 1 ] || [ ! -s "$ARCHIVE_FILE" ]; then
    log_event "fetch" "failed" "$ARCHIVE_URL"
    fail 3 "The download did not complete. Your vault was not touched. Check your internet connection and run the same command again; it picks up where it left off."
fi
log_event "fetch" "complete" "$ARCHIVE_URL"

# Verify the seal BEFORE expanding or executing anything from the archive.
say "Checking the seal (SHA-256 checksum)..."
if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL=$(sha256sum "$ARCHIVE_FILE" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
    ACTUAL=$(shasum -a 256 "$ARCHIVE_FILE" | awk '{print $1}')
else
    fail 3 "No checksum tool (sha256sum or shasum) was found, so the download could not be verified. Nothing was changed."
fi
ACTUAL=$(printf '%s' "$ACTUAL" | tr 'A-F' 'a-f')

if [ "$ACTUAL" != "$CHECKSUM" ]; then
    log_event "checksum" "mismatch expected=$CHECKSUM actual=$ACTUAL"
    fail 4 "The downloaded file did not match its seal (checksum mismatch), so it was thrown away without being opened. Your vault was not touched. Run the command again; if this keeps happening, the download may be tampered with or the app may need an update."
fi
log_event "checksum" "verified" "$ACTUAL"
say "Seal verified."

mkdir -p "$STAGING/extract"
if ! tar -xzf "$ARCHIVE_FILE" -C "$STAGING/extract"; then
    log_event "extract" "failed"
    fail 5 "The release archive could not be unpacked. Your vault was not touched. Run the command again."
fi

# GitHub tag archives expand to a single top-level folder.
RELEASE_ROOT="$STAGING/extract"
_top_entries=$(find "$STAGING/extract" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')
if [ "$_top_entries" = "1" ]; then
    _only=$(find "$STAGING/extract" -mindepth 1 -maxdepth 1)
    if [ -d "$_only" ]; then
        RELEASE_ROOT="$_only"
    fi
fi

# Completeness check: key files must be present before anything is copied.
for _p in $REQUIRED_PATHS; do
    if [ ! -e "$RELEASE_ROOT/$_p" ]; then
        log_event "staging-verify" "incomplete, missing" "$_p"
        fail 5 "The release archive is missing an expected piece ($_p), so nothing was copied. Your vault was not touched."
    fi
done
log_event "staging-verify" "complete"

# ---------------------------------------------------------------------------
# Additive overlay: copy runtime scaffolding only, skip every collision
# ---------------------------------------------------------------------------

say ""
say "Adding the open-source Dex machinery around your folders..."
say "(existing files are never modified; collisions are skipped and recorded)"

copy_one() {
    # copy_one <relative-path>
    _rel="$1"

    # Guard: nothing is ever planted inside the numbered content folders.
    case "$_rel" in
        0[0-7]-*)
            log_event "guard" "manifest item inside a numbered content folder was refused" "$_rel"
            return 0
            ;;
    esac
    # Guard: never write into .git.
    case "$_rel" in
        .git|.git/*|*/.git/*)
            log_event "guard" "manifest item inside .git was refused" "$_rel"
            return 0
            ;;
    esac

    _src="$RELEASE_ROOT/$_rel"
    _dst="$VAULT/$_rel"
    if [ -e "$_dst" ] || [ -L "$_dst" ]; then
        SKIPPED=$((SKIPPED + 1))
        log_event "skip-collision" "already exists, left untouched" "$_rel"
        if [ "$SKIP_SHOWN" -lt 10 ]; then
            say "  kept yours: $_rel"
            SKIP_SHOWN=$((SKIP_SHOWN + 1))
        fi
        return 0
    fi
    _parent=$(dirname "$_dst")
    if ! mkdir -p "$_parent"; then
        log_event "error" "could not create folder" "$_parent"
        fail 6 "Could not create a folder at $_parent. Your existing files are untouched. Run the same command again to finish the remaining copies."
    fi
    if ! cp -p "$_src" "$_dst"; then
        log_event "error" "copy failed" "$_rel"
        fail 6 "Could not copy $_rel. Your existing files are untouched. Run the same command again to finish the remaining copies."
    fi
    COPIED=$((COPIED + 1))
    log_event "copy" "added" "$_rel"
}

# Runtime directories (some may be absent from a release archive).
for _d in $OVERLAY_DIRS; do
    [ -d "$RELEASE_ROOT/$_d" ] || continue
    find "$RELEASE_ROOT/$_d" -type f \
        ! -path '*/.git/*' \
        ! -path '*/__pycache__/*' \
        ! -path '*/node_modules/*' \
        ! -path '*/.venv/*' \
        ! -name '.DS_Store' \
        ! -name '*.pyc' \
        -print | while IFS= read -r _f; do
        printf '%s\n' "${_f#"$RELEASE_ROOT"/}"
    done > "$STAGING/manifest-$_d.txt"
    while IFS= read -r _rel; do
        [ -n "$_rel" ] && copy_one "$_rel"
    done < "$STAGING/manifest-$_d.txt"
done

# Root-level config and runtime files (regular files only, never directories,
# so the release's numbered content folders and System content stay out).
find "$RELEASE_ROOT" -mindepth 1 -maxdepth 1 -type f ! -name '.DS_Store' -print | while IFS= read -r _f; do
    printf '%s\n' "${_f#"$RELEASE_ROOT"/}"
done > "$STAGING/manifest-root.txt"
while IFS= read -r _rel; do
    [ -n "$_rel" ] && copy_one "$_rel"
done < "$STAGING/manifest-root.txt"

# System template files the runtime needs. Templates only, never content,
# and never the release's own user-profile.yaml or pillars.yaml.
for _rel in $SYSTEM_TEMPLATE_FILES; do
    if [ -f "$RELEASE_ROOT/$_rel" ]; then
        copy_one "$_rel"
    fi
done

say ""
say "Copied $COPIED new files. Kept $SKIPPED of your existing files untouched."
if [ "$SKIPPED" -gt "$SKIP_SHOWN" ]; then
    say "(the full list of kept files is in the adoption log)"
fi

# ---------------------------------------------------------------------------
# Completion marker: record the adopted flag, preserving existing fields
# ---------------------------------------------------------------------------

write_marker() {
    _marker="$VAULT/$MARKER_REL"
    mkdir -p "$VAULT/System"
    if command -v python3 >/dev/null 2>&1; then
        if ADOPT_MARKER="$_marker" ADOPT_TAG="$TAG" python3 - <<'PYEOF'
import json
import os
from datetime import datetime

path = os.environ["ADOPT_MARKER"]
data = {}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            data = loaded
    except (json.JSONDecodeError, OSError):
        data = {}
data["adopted"] = True
data.setdefault("adopted_at", datetime.now().isoformat())
data["adopt_release_tag"] = os.environ.get("ADOPT_TAG", "")
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PYEOF
        then
            log_event "marker" "wrote adopted flag" "$MARKER_REL"
        else
            log_event "error" "marker write failed" "$MARKER_REL"
            fail 6 "Could not record the completion marker. Your notes are untouched. Run the same command again."
        fi
    else
        if [ ! -f "$_marker" ]; then
            printf '{\n  "adopted": true,\n  "adopt_release_tag": "%s"\n}\n' "$TAG" > "$_marker"
            log_event "marker" "wrote minimal adopted marker (python3 not found)" "$MARKER_REL"
        elif grep -q '"adopted"[[:space:]]*:[[:space:]]*true' "$_marker"; then
            log_event "marker" "existing marker already adopted (python3 not found)" "$MARKER_REL"
        else
            log_event "marker" "could not merge adopted flag without python3" "$MARKER_REL"
            say "Note: python3 was not found, so the completion marker could not be"
            say "updated. Install Python 3 and run the same command again."
        fi
    fi
}
write_marker

# ---------------------------------------------------------------------------
# Final verification
# ---------------------------------------------------------------------------

MISSING=$(missing_required)
if [ -n "$MISSING" ]; then
    log_event "final-verify" "incomplete" "$MISSING"
    fail 6 "Adoption finished copying but verification found missing pieces:$MISSING. Your notes are untouched. Run the same command again to repair."
fi
log_event "final-verify" "complete"

# ---------------------------------------------------------------------------
# Optional install step (creates .venv, .mcp.json, node modules; additive)
# ---------------------------------------------------------------------------

if [ "$RUN_INSTALL" -eq 1 ] && [ -f "$VAULT/install.sh" ]; then
    say ""
    say "Finishing setup (install step)..."
    log_event "install" "starting"
    if (cd "$VAULT" && bash install.sh < /dev/null); then
        log_event "install" "succeeded"
    else
        log_event "install" "failed"
        say ""
        say "The setup step did not finish. Your notes are untouched and the adoption"
        say "itself is complete. To finish setup, open Terminal in your vault folder"
        say "and run: bash install.sh"
    fi
fi

log_event "run-complete" "copied=$COPIED skipped=$SKIPPED"
say ""
say "Done. Your notes were not moved, changed, or converted."
say "Open-source Dex is now set up around your existing vault."
say "Next: open Claude Code in your vault folder and ask Dex something about"
say "your own notes to see it working."
say "Adoption log: $LOG_FILE"
exit 0
