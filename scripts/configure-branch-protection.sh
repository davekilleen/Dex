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

# The checks this script insists on. This list is a floor, never a ceiling:
# "quality" runs no pytest, so "test-results" -- which carries the Python suite
# verdict and both coverage gates -- has to be named here too. An earlier
# version listed only the first, and because this is a PUT it would have
# silently removed the second from a correctly configured branch.
#
# These are JOB names, not the "Workflow / job" strings GitHub prints in the
# checks UI. A required context is matched against the name a check run reports,
# which for these is bare. An earlier version of this file said
# "Dex CI / quality"; nothing ever reports that name, so requiring it would have
# left every pull request waiting on a status that can never arrive. Verify any
# addition against a real run before adding it here:
#
#   gh api repos/<owner>/<repo>/commits/main/check-runs --jq '.check_runs[].name'
REQUIRED_CONTEXTS=(
  "quality"
  "test-results"
)

# Protection is replaced wholesale by a PUT, so read what is live first and
# submit the union. Running this script can then only ever add a required
# check. If the branch is unprotected, or this token cannot read protection,
# the floor above is used on its own.
LIVE_CONTEXTS_JSON="$(
  gh api "repos/$OWNER/$REPO/branches/$BRANCH/protection" \
    --jq '.required_status_checks.contexts // []' 2>/dev/null || echo '[]'
)"

CONTEXTS_JSON="$(
  REQUIRED="$(printf '%s\n' "${REQUIRED_CONTEXTS[@]}")" \
  LIVE="$LIVE_CONTEXTS_JSON" \
  python3 <<'PY'
import json
import os

required = [line for line in os.environ["REQUIRED"].splitlines() if line]
try:
    live = json.loads(os.environ["LIVE"])
except json.JSONDecodeError:
    live = []
if not isinstance(live, list):
    live = []

merged: list[str] = []
for context in [*required, *(str(value) for value in live)]:
    if context not in merged:
        merged.append(context)

preserved = [context for context in merged if context not in required]
if preserved:
    print(
        "Preserving required checks already configured on the branch: "
        + ", ".join(preserved),
        file=__import__("sys").stderr,
    )
print(json.dumps(merged))
PY
)"

echo "Required checks after this run: $CONTEXTS_JSON"

# A required context that nothing reports blocks every pull request forever on
# "Expected — waiting for status". Check the names against what the branch has
# actually reported recently, and say so rather than writing it silently.
OBSERVED_CHECKS_JSON="$(
  gh api "repos/$OWNER/$REPO/commits/$BRANCH/check-runs" \
    --jq '[.check_runs[].name]' 2>/dev/null || echo 'null'
)"
CONTEXTS="$CONTEXTS_JSON" OBSERVED="$OBSERVED_CHECKS_JSON" python3 <<'PY'
import json
import os
import sys

contexts = json.loads(os.environ["CONTEXTS"])
try:
    observed = json.loads(os.environ["OBSERVED"])
except json.JSONDecodeError:
    observed = None

if not isinstance(observed, list):
    print(
        "Could not read recent check runs, so the required names are unverified.",
        file=sys.stderr,
    )
else:
    unmatched = [name for name in contexts if name not in set(observed)]
    if unmatched:
        print(
            "WARNING: nothing on this branch has reported: "
            + ", ".join(unmatched)
            + "\n         Requiring a name no check run reports leaves every pull "
            "request waiting on a status that never arrives."
            "\n         Observed recently: " + ", ".join(sorted(set(observed))),
            file=sys.stderr,
        )
PY
# This script also re-enables admin enforcement. If an owner-run auto-merge
# depends on bypassing required checks, that will stop working until it is
# turned off again deliberately.

gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "repos/$OWNER/$REPO/branches/$BRANCH/protection" \
  --input - <<JSON
{
  "required_status_checks": {
    "strict": true,
    "contexts": $CONTEXTS_JSON
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
