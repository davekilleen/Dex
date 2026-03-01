#!/bin/bash
# Dex Safety Guard — PreToolUse hook
# Guards both Bash commands AND MCP tool preferences.
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
# Scrapling is the default scraper. Block Firecrawl/WebFetch/Apify RAG browser.

BLOCKED_SCRAPERS="firecrawl_scrape firecrawl_search firecrawl_crawl firecrawl_map firecrawl_extract firecrawl_batch_scrape firecrawl_deep_research firecrawl_generate_llmstxt webfetch rag-web-browser rag_web_browser"

for scraper in $BLOCKED_SCRAPERS; do
    if echo "$TOOL_LOWER" | grep -q "$scraper"; then
        echo "WRONG SCRAPER: Scrapling is the configured default. Use scrapling get/fetch/stealthy_fetch instead of $TOOL_NAME."
        exit 2
    fi
done

# Nothing further to check for non-Bash tools
if [ -z "$COMMAND" ]; then
    exit 0
fi

# === HARD BLOCKS (exit 2) ===

# Catastrophic filesystem destruction
if echo "$COMMAND" | grep -qE 'rm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?(-[a-zA-Z]*r[a-zA-Z]*\s+)?(\/|~\/?\s|"\$HOME"|\/Users)'; then
    echo '{"decision":"block","reason":"Blocked: recursive delete targeting root, home, or /Users"}'
    exit 2
fi

if echo "$COMMAND" | grep -qE 'rm\s+-rf\s+/'; then
    echo '{"decision":"block","reason":"Blocked: rm -rf /"}'
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
