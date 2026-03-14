#!/bin/bash
set -euo pipefail

if [ "${GITHUB_EVENT_NAME:-}" != "pull_request" ] || [ ! -f "${GITHUB_EVENT_PATH:-}" ]; then
  echo "Skipping PR governance check outside pull_request events."
  exit 0
fi

PR_BODY=$(python3 - <<'PY'
import json
import os
from pathlib import Path

event_path = Path(os.environ["GITHUB_EVENT_PATH"])
event = json.loads(event_path.read_text(encoding="utf-8"))
print((event.get("pull_request") or {}).get("body") or "")
PY
)

if [ -z "$PR_BODY" ]; then
  echo "PR body is empty. Fill in .github/pull_request_template.md sections."
  exit 1
fi

required_sections=(
  "## Linked Issue"
  "## Test Plan"
  "## Risk & Rollback"
  "## Docs Impact"
)

# Optional: present in /ao-generated PRs only
optional_sections=(
  "## Ralph Wiggum Loop"
)

required_checks=(
  "- [x] I implemented the change."
  "- [x] I self-reviewed for defects and edge cases."
  "- [x] I addressed review findings and re-ran checks."
  "- [x] I added/updated tests or documented why no tests are needed."
  "- [x] I added a regression test for bug fixes, or this PR is not a bug fix."
  "- [x] I validated failure modes / edge cases."
  "- [x] I updated docs or confirmed no docs impact."
)

for section in "${required_sections[@]}"; do
  if ! printf "%s\n" "$PR_BODY" | grep -Fq -- "$section"; then
    echo "Missing required section in PR body: $section"
    exit 1
  fi
done

for check in "${required_checks[@]}"; do
  if ! printf "%s\n" "$PR_BODY" | grep -Fq -- "$check"; then
    echo "Required checklist item not completed: $check"
    exit 1
  fi
done

if ! printf "%s\n" "$PR_BODY" | grep -Eq 'DEX-[0-9]+'; then
  echo "Linked issue missing. Include a DEX ticket in '## Linked Issue'."
  exit 1
fi

echo "PR governance check passed."
