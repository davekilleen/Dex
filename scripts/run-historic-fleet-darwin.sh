#!/bin/bash
# Run the first-party macOS historic fleet without carrying CI credentials.
# Formal mode accepts exact public releases; canary mode creates local refs only.

set -euo pipefail

CANONICAL_PUBLIC_REMOTE="https://github.com/davekilleen/Dex.git"
PINNED_FOUNDATION_TAG="dist/release/v1.81.16-281202d"
MAX_DISK_KIB=$((50 * 1024 * 1024))
# Every entry must still resolve on the public remote. The release-tag archive
# renames tags from dist/release/ to dist/archive/ without moving the object, so
# an archived start is updated here rather than dropped.
CANARY_STARTS=(
  "v1.51.0"
  "dist/release/v1.61.0-dc7d332"
  "dist/archive/v1.61.0-1ec1387"
  "v1.62.0"
  "dist/archive/v1.63.0-08ce719"
  "dist/archive/v1.65.0-c5ec161"
  "dist/archive/v1.72.0-7d75da9"
  "dist/archive/v1.76.0-d0bb932"
  "v1.81.1"
  "dist/archive/v1.81.1-b17ef02"
  "v1.81.7"
  "v1.81.11"
)
# One start also runs the published bridge the way a stuck user runs it: as a
# top-level process from the vault root, with stdin closed, which is the only
# way the environment scrub, the relaunch into the vault runtime, and the
# clean-runtime check are executed at all. The oldest start is the one a rescued
# user is most likely to be on. One bounded process run, not a thirteenth journey.
BRIDGE_PROCESS_ENTRY_START="v1.51.0"

MODE="${1:-}"
case "$MODE" in
  formal|canary) ;;
  *) echo "Usage: $0 formal|canary" >&2; exit 64 ;;
esac

if [ "$(uname -s)" != "Darwin" ]; then
  echo "historic-fleet-darwin requires a macOS runner" >&2
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
RUNNER_TEMP_ROOT="${RUNNER_TEMP:?RUNNER_TEMP is required}"
WORK_ROOT="${FLEET_WORK_ROOT:?FLEET_WORK_ROOT is required}"
case "$WORK_ROOT" in
  "$RUNNER_TEMP_ROOT"/*) ;;
  *) echo "FLEET_WORK_ROOT must be beneath RUNNER_TEMP" >&2; exit 1 ;;
esac
if [ -e "$WORK_ROOT" ] || [ -L "$WORK_ROOT" ]; then
  echo "fleet work root already exists: $WORK_ROOT" >&2
  exit 1
fi
mkdir -m 700 "$WORK_ROOT"

COUNTS_FILE="$WORK_ROOT/counts.json"
SUMMARY_FILE="$WORK_ROOT/summary.md"
LOG_FILE="$WORK_ROOT/controller.log"
SESSION_KEY="$WORK_ROOT/acceptance.key"
DISCOVERED=0
STARTED=0
COMPLETED=0
PASSED=0
FAILED=0

write_counts() {
  python3 - "$COUNTS_FILE" "$DISCOVERED" "$STARTED" "$COMPLETED" "$PASSED" "$FAILED" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
document = {
    "discovered": int(sys.argv[2]),
    "started": int(sys.argv[3]),
    "completed": int(sys.argv[4]),
    "passed": int(sys.argv[5]),
    "failed": int(sys.argv[6]),
}
temporary = path.with_suffix(".tmp")
temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(temporary, path)
PY
}

write_summary() {
  write_counts
  {
    echo "## $MODE historic-fleet-darwin"
    echo
    echo "| discovered | started | completed | passed | failed |"
    echo "|---:|---:|---:|---:|---:|"
    echo "| $DISCOVERED | $STARTED | $COMPLETED | $PASSED | $FAILED |"
    echo
    if [ "$MODE" = "formal" ]; then
      echo "Foundation: \`${FOUNDATION_TAG:-unset}\`"
      echo
      echo "Follow-up: \`${FOLLOW_UP_TAG:-unset}\`"
    else
      echo "This PR canary is release-shaped non-acceptance evidence. It cannot publish."
    fi
  } > "$SUMMARY_FILE"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    cat "$SUMMARY_FILE" >> "$GITHUB_STEP_SUMMARY"
  fi
}

finish() {
  status=$?
  rm -f "$SESSION_KEY"
  write_summary || true
  return "$status"
}
trap finish EXIT

refresh_public_tags() {
  while IFS= read -r tag; do
    [ -n "$tag" ] && git update-ref -d "refs/tags/$tag"
  done < <(git tag --list)
  git -c credential.helper= -c protocol.file.allow=never fetch \
    --force --prune --no-tags "$CANONICAL_PUBLIC_REMOTE" \
    '+refs/tags/*:refs/tags/*'
}

assert_public_annotated_tag() {
  local tag local_object advertised short commit
  tag="$1"
  if [ "$(git cat-file -t "$tag" 2>/dev/null || true)" != "tag" ]; then
    echo "public immutable tag is missing or is not annotated: $tag" >&2
    return 1
  fi
  local_object="$(git rev-parse --verify "$tag")"
  advertised="$(git -c credential.helper= -c protocol.file.allow=never ls-remote \
    --refs --tags "$CANONICAL_PUBLIC_REMOTE" "refs/tags/$tag")"
  if [ "$advertised" != "$local_object"$'\t'"refs/tags/$tag" ]; then
    echo "public immutable tag identity does not match: $tag" >&2
    return 1
  fi
  short="${tag##*-}"
  commit="$(git rev-parse --verify "$tag^{commit}")"
  case "$commit" in
    "$short"*) ;;
    *) echo "immutable tag suffix does not match its commit: $tag" >&2; return 1 ;;
  esac
}

disk_kib() {
  du -sk "$WORK_ROOT" | awk '{print $1}'
}

run_bounded() {
  budget_marker="$WORK_ROOT/disk-budget-exceeded"
  rm -f "$budget_marker"
  "$@" >> "$LOG_FILE" 2>&1 &
  command_pid=$!
  (
    while kill -0 "$command_pid" 2>/dev/null; do
      used="$(disk_kib)"
      if [ "$used" -gt "$MAX_DISK_KIB" ]; then
        printf 'historic fleet exceeded %s KiB (used %s KiB)\n' \
          "$MAX_DISK_KIB" "$used" > "$budget_marker"
        pkill -TERM -P "$command_pid" 2>/dev/null || true
        kill -TERM "$command_pid" 2>/dev/null || true
        exit 0
      fi
      sleep 30
    done
  ) &
  monitor_pid=$!
  if wait "$command_pid"; then
    command_status=0
  else
    command_status=$?
  fi
  kill "$monitor_pid" 2>/dev/null || true
  wait "$monitor_pid" 2>/dev/null || true
  if [ -f "$budget_marker" ]; then
    cat "$budget_marker" >&2
    return 75
  fi
  return "$command_status"
}

run_formal() {
  FOUNDATION_TAG="${FOUNDATION_TAG:?FOUNDATION_TAG is required}"
  FOLLOW_UP_TAG="${FOLLOW_UP_TAG:?FOLLOW_UP_TAG is required}"
  if [ "$FOUNDATION_TAG" != "$PINNED_FOUNDATION_TAG" ]; then
    echo "foundation must be the exact pinned public identity $PINNED_FOUNDATION_TAG" >&2
    return 1
  fi
  if ! [[ "$FOLLOW_UP_TAG" =~ ^dist/release/v[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{7,40}$ ]]; then
    echo "follow-up must be an exact immutable dist/release tag" >&2
    return 1
  fi
  if [ "$FOLLOW_UP_TAG" = "$FOUNDATION_TAG" ]; then
    echo "foundation and follow-up must differ" >&2
    return 1
  fi

  refresh_public_tags
  assert_public_annotated_tag "$FOUNDATION_TAG"
  assert_public_annotated_tag "$FOLLOW_UP_TAG"

  SOURCE_COMMIT="$(git show "$FOLLOW_UP_TAG:System/.release-catalog.json" | python3 -c '
import json, re, sys
document = json.load(sys.stdin)
value = document.get("release", {}).get("source_commit")
if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
    raise SystemExit("follow-up release has no canonical source commit")
print(value)
')"
  if [ "$(git rev-parse --verify "$SOURCE_COMMIT^{commit}")" != "$SOURCE_COMMIT" ]; then
    echo "follow-up publisher source commit is unavailable" >&2
    return 1
  fi
  git checkout --detach "$SOURCE_COMMIT"

  COHORT="$WORK_ROOT/historic-cohort.json"
  SESSION="$WORK_ROOT/acceptance-session.json"
  PLATFORM_ROOT="$WORK_ROOT/platform"
  ASSET_ROOT="$WORK_ROOT/public-assets"
  mkdir -m 700 "$ASSET_ROOT"

  python3 scripts/release_fleet_acceptance.py cohort \
    --repo . --output "$COHORT" | tee "$WORK_ROOT/cohort-result.json"
  DISCOVERED="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["case_count"])' "$COHORT")"
  if [ "$DISCOVERED" -lt 1 ]; then
    echo "fresh public cohort is empty" >&2
    return 1
  fi

  python3 scripts/release_fleet_acceptance.py session \
    --repo . --cohort "$COHORT" \
    --foundation-tag "$FOUNDATION_TAG" --follow-up-tag "$FOLLOW_UP_TAG" \
    --session-output "$SESSION" --key-output "$SESSION_KEY" \
    | tee "$WORK_ROOT/session-result.json"

  FOLLOW_UP_VERSION="$(printf '%s\n' "$FOLLOW_UP_TAG" | sed -E 's#^dist/release/v([0-9]+\.[0-9]+\.[0-9]+)-[0-9a-f]+$#\1#')"
  BRIDGE_ASSET="$ASSET_ROOT/dex-update-bridge-v$FOLLOW_UP_VERSION.py"
  BRIDGE_CHECKSUM="$BRIDGE_ASSET.sha256"
  PUBLIC_RELEASE="https://github.com/davekilleen/Dex/releases/download/v$FOLLOW_UP_VERSION"
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 --fail --location \
    --retry 3 --retry-all-errors --max-time 120 \
    "$PUBLIC_RELEASE/$(basename "$BRIDGE_ASSET")" --output "$BRIDGE_ASSET"
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 --fail --location \
    --retry 3 --retry-all-errors --max-time 120 \
    "$PUBLIC_RELEASE/$(basename "$BRIDGE_CHECKSUM")" --output "$BRIDGE_CHECKSUM"
  if [ "$(wc -c < "$BRIDGE_ASSET")" -gt $((16 * 1024 * 1024)) ] \
    || [ "$(wc -c < "$BRIDGE_CHECKSUM")" -gt 4096 ]; then
    echo "public bridge asset exceeds its bounded size" >&2
    return 1
  fi
  (cd "$ASSET_ROOT" && shasum -a 256 -c "$(basename "$BRIDGE_CHECKSUM")")

  export DEX_COUNTS_FILE="$COUNTS_FILE"
  export DEX_COHORT_FILE="$COHORT"
  export DEX_PLATFORM_ROOT="$PLATFORM_ROOT"
  export DEX_FOUNDATION_TAG="$FOUNDATION_TAG"
  export DEX_FOLLOW_UP_TAG="$FOLLOW_UP_TAG"
  export DEX_SESSION_FILE="$SESSION"
  export DEX_SESSION_KEY="$SESSION_KEY"
  export DEX_BRIDGE_ASSET="$BRIDGE_ASSET"
  export DEX_BRIDGE_CHECKSUM="$BRIDGE_CHECKSUM"

  if run_bounded python3 - <<'PY'
import json
import os
from pathlib import Path

from scripts import release_fleet_acceptance as acceptance

counts_path = Path(os.environ["DEX_COUNTS_FILE"])
platform_root = Path(os.environ["DEX_PLATFORM_ROOT"])
cohort = json.loads(Path(os.environ["DEX_COHORT_FILE"]).read_text(encoding="utf-8"))
discovered = int(cohort["case_count"])

def write(counts):
    counts_path.write_text(json.dumps(dict(counts), indent=2, sort_keys=True) + "\n", encoding="utf-8")

arguments = [
    "platform",
    "--repo", ".",
    "--cohort", os.environ["DEX_COHORT_FILE"],
    "--foundation-tag", os.environ["DEX_FOUNDATION_TAG"],
    "--follow-up-tag", os.environ["DEX_FOLLOW_UP_TAG"],
    "--session", os.environ["DEX_SESSION_FILE"],
    "--key", os.environ["DEX_SESSION_KEY"],
    "--bridge-asset", os.environ["DEX_BRIDGE_ASSET"],
    "--bridge-checksum", os.environ["DEX_BRIDGE_CHECKSUM"],
    "--output", os.environ["DEX_PLATFORM_ROOT"],
]
try:
    result = acceptance.main(arguments)
except acceptance.PlatformFleetFailure as error:
    write(error.counts)
    raise
except Exception:
    completed = sum(1 for _ in platform_root.glob("*.evidence/evidence-manifest.json"))
    write({
        "discovered": discovered,
        "started": completed,
        "completed": completed,
        "passed": completed,
        "failed": 0,
    })
    raise
else:
    write({
        "discovered": discovered,
        "started": discovered,
        "completed": discovered,
        "passed": discovered,
        "failed": 0,
    })
    raise SystemExit(result)
PY
  then
    platform_status=0
  else
    platform_status=$?
  fi

  if [ ! -f "$COUNTS_FILE" ]; then
    completed_evidence=0
    if [ -d "$PLATFORM_ROOT" ]; then
      completed_evidence="$(find "$PLATFORM_ROOT" -type f -name evidence-manifest.json | wc -l | tr -d ' ')"
      if [ "$completed_evidence" -lt "$DISCOVERED" ]; then
        STARTED=$((completed_evidence + 1))
        FAILED=1
      else
        STARTED="$completed_evidence"
      fi
    fi
    COMPLETED="$completed_evidence"
    PASSED="$completed_evidence"
    write_counts
  fi
  if [ -f "$COUNTS_FILE" ]; then
    read -r DISCOVERED STARTED COMPLETED PASSED FAILED < <(
      python3 - "$COUNTS_FILE" <<'PY'
import json, sys
value = json.load(open(sys.argv[1]))
print(*(value[name] for name in ("discovered", "started", "completed", "passed", "failed")))
PY
    )
  fi
  if [ "$platform_status" -ne 0 ]; then
    tail -200 "$LOG_FILE" >&2 || true
    return "$platform_status"
  fi

  python3 scripts/release_fleet_acceptance.py aggregate \
    --repo . --cohort "$COHORT" \
    --foundation-tag "$FOUNDATION_TAG" --follow-up-tag "$FOLLOW_UP_TAG" \
    --session "$SESSION" --key "$SESSION_KEY" \
    --receipt "$PLATFORM_ROOT/platform-receipt.json" \
    --manifest "$PLATFORM_ROOT/platform-manifest.json" \
    --output "$WORK_ROOT/aggregate.json" | tee "$WORK_ROOT/aggregate-result.json"
  [ "$(disk_kib)" -le "$MAX_DISK_KIB" ]
}

run_canary() {
  if [ "${GITHUB_EVENT_NAME:-}" != "pull_request" ]; then
    echo "the local release-shaped canary runs only for pull requests" >&2
    return 1
  fi
  if ! [[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]]; then
    echo "GITHUB_SHA must identify the exact pull-request candidate" >&2
    return 1
  fi

  refresh_public_tags
  assert_public_annotated_tag "$PINNED_FOUNDATION_TAG"
  bridge_process_entry_planned=0
  for start in "${CANARY_STARTS[@]}"; do
    if [ "$start" = "$BRIDGE_PROCESS_ENTRY_START" ]; then
      bridge_process_entry_planned=1
    fi
    if ! git rev-parse --verify "$start^{commit}" >/dev/null 2>&1; then
      echo "public canary start is unavailable: $start" >&2
      echo "if the release-tag archive renamed it, update CANARY_STARTS to the dist/archive/ name" >&2
      return 1
    fi
  done
  if [ "$bridge_process_entry_planned" -ne 1 ]; then
    echo "no canary start runs the bridge as a process: $BRIDGE_PROCESS_ENTRY_START is not in CANARY_STARTS" >&2
    return 1
  fi

  git config user.name "github-actions[bot]"
  git config user.email "github-actions[bot]@users.noreply.github.com"
  git branch -f candidate "$GITHUB_SHA"
  bash scripts/build-release.sh --source candidate --target release \
    | tee "$WORK_ROOT/candidate-release-build.log"
  CANDIDATE_COMMIT="$(git rev-parse --verify release^{commit})"
  candidate_tags=()
  while IFS= read -r tag; do
    [ -n "$tag" ] && candidate_tags+=("$tag")
  done < <(git tag --points-at "$CANDIDATE_COMMIT" --list 'dist/release/v*')
  if [ "${#candidate_tags[@]}" -ne 1 ]; then
    echo "candidate build did not create exactly one immutable release tag" >&2
    return 1
  fi
  CANDIDATE_TAG="${candidate_tags[0]}"
  CANDIDATE_IDENTITY="$(
    python3 scripts/check-release-catalog-tag-identity.py \
      --release-ref release --source-ref candidate
  )"
  if [ -z "$CANDIDATE_IDENTITY" ]; then
    echo "candidate release catalog identity observation was empty" >&2
    return 1
  fi
  printf '%s\n' "$CANDIDATE_IDENTITY"
  FOLLOW_UP_CACHE="$WORK_ROOT/candidate-release.git"
  git init --bare --quiet "$FOLLOW_UP_CACHE"
  chmod 700 "$FOLLOW_UP_CACHE"
  git -c credential.helper= -c protocol.file.allow=always \
    --git-dir="$FOLLOW_UP_CACHE" fetch --quiet --no-tags . \
    "refs/tags/$CANDIDATE_TAG:refs/tags/$CANDIDATE_TAG" \
    "+refs/heads/release:refs/heads/release"
  CANDIDATE_VERSION="$(python3 -c 'import json; print(json.load(open("package.json"))["version"])')"
  ASSET_ROOT="$WORK_ROOT/candidate-assets"
  mkdir -m 700 "$ASSET_ROOT"
  bash scripts/build-vault-bundle.sh "$ASSET_ROOT" \
    | tee "$WORK_ROOT/candidate-assets-build.log"
  BRIDGE_ASSET="$ASSET_ROOT/dex-update-bridge-v$CANDIDATE_VERSION.py"
  BRIDGE_CHECKSUM="$BRIDGE_ASSET.sha256"
  (cd "$ASSET_ROOT" && shasum -a 256 -c "$(basename "$BRIDGE_CHECKSUM")")

  JOURNEY_ROOT="$WORK_ROOT/journeys"
  mkdir -m 700 "$JOURNEY_ROOT"
  DISCOVERED="${#CANARY_STARTS[@]}"
  for start in "${CANARY_STARTS[@]}"; do
    STARTED=$((STARTED + 1))
    journey_options=(--controlled-approvals)
    if [ "$start" = "$BRIDGE_PROCESS_ENTRY_START" ]; then
      journey_options+=(--bridge-process-entry)
    fi
    if run_bounded python3 scripts/release_fleet.py journey \
      --repo . --output "$JOURNEY_ROOT" \
      --starting-tag "$start" \
      --foundation-tag "$PINNED_FOUNDATION_TAG" \
      --follow-up-tag "$CANDIDATE_TAG" \
      --bridge-asset "$BRIDGE_ASSET" \
      --bridge-checksum "$BRIDGE_CHECKSUM" \
      --follow-up-cache "$FOLLOW_UP_CACHE" \
      "${journey_options[@]}"
    then
      journey_status=0
    else
      journey_status=$?
    fi
    if [ "$journey_status" -ne 0 ]; then
      FAILED=$((FAILED + 1))
      tail -200 "$LOG_FILE" >&2 || true
      return "$journey_status"
    fi
    COMPLETED=$((COMPLETED + 1))
    PASSED=$((PASSED + 1))
    write_counts
  done
  [ "$(disk_kib)" -le "$MAX_DISK_KIB" ]
}

if [ "$MODE" = "formal" ]; then
  run_formal
else
  run_canary
fi
