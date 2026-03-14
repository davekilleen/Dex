#!/bin/bash
set -euo pipefail

BASE_REF="${GITHUB_BASE_REF:-main}"
git fetch origin "$BASE_REF" --depth=1 >/dev/null 2>&1 || true
MERGE_BASE="$(git merge-base HEAD "origin/$BASE_REF")"
CHANGED_FILES="$(git diff --name-only "$MERGE_BASE...HEAD")"

if [ ! -f "docs/testing-governance.md" ]; then
  echo "Missing required governance document: docs/testing-governance.md"
  exit 1
fi

if [ -z "$CHANGED_FILES" ]; then
  echo "No changed files detected."
  exit 0
fi

SOURCE_CHANGED="$(printf "%s\n" "$CHANGED_FILES" | \
  grep -E '^(core/.*\.py|pi-extensions/.*\.(js|cjs|ts)|\.claude/hooks/.*\.(js|cjs))$' | \
  grep -Ev '^(core/tests/|core/mcp/tests/)' || true)"

DOC_CHANGED="$(printf "%s\n" "$CHANGED_FILES" | \
  grep -E '^(docs/|System/PRDs/)|^(README\.md|CHANGELOG\.md|CONTRIBUTING\.md)$' || true)"

if [ -z "$SOURCE_CHANGED" ]; then
  echo "No production-source delta requiring docs review."
  exit 0
fi

if [ -n "$DOC_CHANGED" ]; then
  echo "Doc drift check passed."
  exit 0
fi

LABEL_APPROVED=$(python3 - <<'PY'
import json
import os
from pathlib import Path

event_path = os.environ.get("GITHUB_EVENT_PATH")
if not event_path or not Path(event_path).is_file():
    print("0")
    raise SystemExit
event = json.loads(Path(event_path).read_text(encoding="utf-8"))
labels = {(label.get("name") or "").strip() for label in (event.get("pull_request") or {}).get("labels", [])}
print("1" if "docs-exception-approved" in labels else "0")
PY
)

if [ "$LABEL_APPROVED" = "1" ]; then
  echo "docs-exception-approved label found; bypassing docs drift gate."
  exit 0
fi

echo "Source files changed without documentation updates."
echo "Changed source files:"
printf "%s\n" "$SOURCE_CHANGED"
echo ""
echo "Update docs/System/PRDs or apply 'docs-exception-approved' label with rationale."
exit 1
