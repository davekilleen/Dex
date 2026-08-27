#!/bin/bash
# Dex Safety Guard — PreToolUse hook
#
# Best-effort guard that catches common catastrophic accidents in Bash commands
# and redirects disallowed scraper MCPs. It is a pattern denylist, not a security
# boundary — the host permission system remains the real control. Anything that
# deliberately obfuscates a command (variables, encoding, indirection) will pass.
#
# Exit 0 = allow, Exit 2 = block

INPUT=$(cat)

# Extract tool name and command from input
TOOL_NAME=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    print(data.get('tool_name', ''))
except:
    print('')
" 2>/dev/null)

COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    print(data.get('tool_input', {}).get('command', ''))
except:
    print('')
" 2>/dev/null)
TOOL_LOWER=$(echo "$TOOL_NAME" | tr '[:upper:]' '[:lower:]')

# === MCP TOOL PREFERENCE GUARDS ===
# Scrapling is the preferred configured scraper. Block unsafe scraper MCPs while
# leaving native WebFetch available as the fallback when Scrapling is absent.

case "$TOOL_LOWER" in
    mcp__firecrawl__*|mcp__rag-web-browser__*|mcp__rag_web_browser__*)
        echo "WRONG SCRAPER: Scrapling is the configured default. Use scrapling get/fetch/stealthy_fetch instead of $TOOL_NAME."
        exit 2
        ;;
esac

# Nothing further to check for non-Bash tools
if [ -z "$COMMAND" ]; then
    exit 0
fi

# A live brain/vault migration owns the shared mutation lock. Raw Git writes
# during that window can turn a recoverable pause into a corrupted topology.
MIGRATION_LOCK="System/.dex/mutation.lock"
MIGRATION_LOCK_LIVE=""
if [ -f "$MIGRATION_LOCK" ]; then
    MIGRATION_LOCK_LIVE=$(python3 -c '
import json
import os
import sys


def process_is_running(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        # os.kill is NOT a liveness probe on Windows: CPython documents that
        # any sig other than the console-control events unconditionally kills
        # the target via TerminateProcess. Use a query-only process handle.
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(0x1000 | 0x00100000, False, pid)  # QUERY_LIMITED | SYNCHRONIZE
        if not handle:
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED: exists
        try:
            return kernel32.WaitForSingleObject(handle, 0) != 0  # 0 = exited
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        lock = json.load(handle)
    if lock.get("kind") != "migration":
        raise ValueError("not a migration")
    if process_is_running(lock["pid"]):
        print("yes")
except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
    pass
' "$MIGRATION_LOCK" 2>/dev/null)
fi
if [ "$MIGRATION_LOCK_LIVE" = "yes" ] \
    && echo "$COMMAND" | grep -qE '(^|[;&|[:space:]])git[[:space:]]+(add|am|apply|bisect[[:space:]]+(good|bad|reset|start)|branch[[:space:]].*(-[dDmM]|--delete|--move)|checkout|cherry-pick|clean|commit|merge|mv|rebase|reset|restore|revert|rm|stash|switch|tag)([[:space:];&|]|$)'; then
    echo '{"decision":"block","reason":"A brain/vault migration is active. Do not use raw Git repair commands. Run the migrator with --resume to continue or --restore to return to the pre-split layout."}'
    exit 2
fi

# === HARD BLOCKS (exit 2) ===

# Catastrophic filesystem destruction.
#
# Quotes are stripped first so `"$HOME"`, `'~'` and payloads carried inside
# `bash -c "..."` are seen the same way as the bare form. Matching is substring
# based on the whole command, so a catastrophic-looking string anywhere in the
# command blocks it. That is deliberate: a false positive costs a rephrase, a
# false negative costs a home directory.
COMMAND_UNQUOTED=$(printf '%s' "$COMMAND" | tr -d "\"'")

# `rm` invoked recursively, in any flag order: -rf, -fr, -r -f, -f -r, -Rf,
# --recursive --force. Trailing separator required so `remove`/`confirm` and
# similar words never match.
RM_RECURSIVE='(^|[^[:alnum:]_-])rm[[:space:]]+((-[a-zA-Z]+|--[a-z-]+)[[:space:]]+)*(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)([[:space:]]+(-[a-zA-Z]+|--[a-z-]+))*[[:space:]]+'
# Home directory in every spelling: ~, ~/…, $HOME, ${HOME}, $HOME/…
TARGET_HOME='(~|\$\{?HOME\}?)([[:space:]/]|[;&|)]|$)'
# Filesystem root: / and /*
TARGET_ROOT='/([[:space:]]|\*|[;&|)]|$)'
# Bare relative nukes that are only catastrophic in a dangerous working dir.
TARGET_HERE='(\.|\*|\./\*?)([[:space:]]|[;&|)]|$)'
# `cd` into home or root (with or without a trailing slash) in the same command.
CD_DANGEROUS='(^|[^[:alnum:]_-])cd[[:space:]]+(~|\$\{?HOME\}?|/)/?([[:space:]]|[;&|)]|$)'

if printf '%s' "$COMMAND_UNQUOTED" | grep -qE "${RM_RECURSIVE}(${TARGET_HOME}|${TARGET_ROOT})"; then
    echo '{"decision":"block","reason":"Blocked: recursive delete targeting your home directory or the filesystem root"}'
    exit 2
fi

# `cd ~ && rm -rf .` and friends — harmless-looking target, catastrophic place.
if printf '%s' "$COMMAND_UNQUOTED" | grep -qE "$CD_DANGEROUS" \
    && printf '%s' "$COMMAND_UNQUOTED" | grep -qE "${RM_RECURSIVE}${TARGET_HERE}"; then
    echo '{"decision":"block","reason":"Blocked: recursive delete of the current directory after switching to your home directory or the filesystem root"}'
    exit 2
fi

# Any rm reaching an absolute path (/Users/…, /etc/…, /opt/…). Preserved from
# the original guard: absolute-path deletes are always worth a second look.
if printf '%s' "$COMMAND_UNQUOTED" | grep -qE '(^|[^[:alnum:]_-])rm[[:space:]]+((-[a-zA-Z]+|--[a-z-]+)[[:space:]]+)*/'; then
    echo '{"decision":"block","reason":"Blocked: delete targeting an absolute system path"}'
    exit 2
fi

# Disk wiping
if echo "$COMMAND" | grep -qiE '(diskutil\s+eraseDisk|mkfs\s|dd\s+if=)'; then
    echo '{"decision":"block","reason":"Blocked: disk wipe/format command"}'
    exit 2
fi

# Force push to main/master
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*--force.*\s+(main|master)'; then
    echo '{"decision":"block","reason":"Blocked: force push to main/master"}'
    exit 2
fi
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*\s+(main|master).*--force'; then
    echo '{"decision":"block","reason":"Blocked: force push to main/master"}'
    exit 2
fi

# SQL destruction
if echo "$COMMAND" | grep -qiE '(DROP\s+TABLE|DROP\s+DATABASE)'; then
    echo '{"decision":"block","reason":"Blocked: SQL DROP command"}'
    exit 2
fi

# GitHub repo deletion
if echo "$COMMAND" | grep -qE 'gh\s+repo\s+delete'; then
    echo '{"decision":"block","reason":"Blocked: GitHub repo deletion"}'
    exit 2
fi

# === WARNINGS (allow but flag) ===

# chmod 777
if echo "$COMMAND" | grep -qE 'chmod\s+777'; then
    echo '{"decision":"allow","reason":"WARNING: chmod 777 grants full permissions to all users. Consider more restrictive permissions."}'
    exit 0
fi

# kill -9
if echo "$COMMAND" | grep -qE 'kill\s+-9'; then
    echo '{"decision":"allow","reason":"WARNING: kill -9 force-terminates without cleanup. Ensure this is the intended process."}'
    exit 0
fi

# === DEFAULT: ALLOW ===
exit 0
