#!/bin/bash
set -euo pipefail

BRANCH="${1:-main}"
REMOTE_URL="$(git remote get-url origin)"

if [[ "$REMOTE_URL" =~ github.com[:/](.+)/(.+)(\.git)?$ ]]; then
  OWNER="${BASH_REMATCH[1]}"
  REPO="${BASH_REMATCH[2]%.git}"
else
  echo "Unable to parse GitHub owner/repo from origin URL: $REMOTE_URL"
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI (gh) is required."
  exit 1
fi

echo "Configuring branch protection for $OWNER/$REPO:$BRANCH"

gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "repos/$OWNER/$REPO/branches/$BRANCH/protection" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["Dex CI / quality"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": false
}
JSON

echo "Branch protection configured."
