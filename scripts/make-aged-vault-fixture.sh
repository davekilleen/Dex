#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

WITH_MERGE=false
NO_GIT=false
HUGE=false
for argument in "$@"; do
  case "$argument" in
    --with-merge-in-progress) WITH_MERGE=true ;;
    --no-git) NO_GIT=true ;;
    --huge) HUGE=true ;;
    *) echo "Unknown fixture flag: $argument" >&2; exit 2 ;;
  esac
done

if [ "$WITH_MERGE" = true ] && [ "$NO_GIT" = true ]; then
  echo "--with-merge-in-progress and --no-git cannot describe the same fixture" >&2
  exit 2
fi

FIXTURE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/dex-aged-vault.XXXXXX")"
UPSTREAM="$FIXTURE_ROOT/upstream"
VAULT="$FIXTURE_ROOT/Dex Vault - Aged"

git clone --local --no-hardlinks --quiet "$REPO_ROOT" "$UPSTREAM"
git -C "$UPSTREAM" checkout -B main HEAD --quiet
git -C "$UPSTREAM" config user.name "Dex Fixture Builder"
git -C "$UPSTREAM" config user.email "fixture-builder@dex.local"

# Include the live D1 files even while they are still uncommitted in the dispatch
# worktree. The source remains the current local repository and never uses a network.
D1_FILES=(
  core/update/ownership.json
  core/update/ownership.cjs
  core/migrations/v1-to-v2-brain-vault-split.cjs
  core/migrations/v1-to-v2-brain-vault-split.sh
)
for relative in "${D1_FILES[@]}"; do
  if [ -f "$REPO_ROOT/$relative" ]; then
    mkdir -p "$UPSTREAM/$(dirname "$relative")"
    cp "$REPO_ROOT/$relative" "$UPSTREAM/$relative"
    git -C "$UPSTREAM" add -f -- "$relative"
  fi
done
if ! git -C "$UPSTREAM" diff --cached --quiet; then
  git -C "$UPSTREAM" commit --quiet -m "release: seed brain vault migration"
fi

bash "$UPSTREAM/scripts/build-release.sh" >/dev/null

if [ "$NO_GIT" = true ]; then
  mkdir -p "$VAULT"
  RELEASE_ARCHIVE="$FIXTURE_ROOT/release.tar"
  git -C "$UPSTREAM" archive --output="$RELEASE_ARCHIVE" release
  tar -xf "$RELEASE_ARCHIVE" -C "$VAULT"
else
  git clone --local --no-hardlinks --quiet --branch release "$UPSTREAM" "$VAULT"
  git -C "$VAULT" config user.name "Long-time Dex User"
  git -C "$VAULT" config user.email "user@dex.local"
  git -C "$VAULT" remote rename origin upstream
  git -C "$VAULT" remote add private-backup https://example.invalid/private-dex-vault.git
fi

mkdir -p \
  "$VAULT/04-Projects" \
  "$VAULT/05-Areas/People/External" \
  "$VAULT/.claude/skills/foo-custom" \
  "$VAULT/System/credentials"

printf '\n- [ ] User-edited task seed\n' >> "$VAULT/03-Tasks/Tasks.md"
printf '\n- User-edited quarterly goal\n' >> "$VAULT/01-Quarter_Goals/Quarter_Goals.md"
printf '\n- User-edited weekly priority\n' >> "$VAULT/02-Week_Priorities/Week_Priorities.md"
printf '# A project ignored by the v1 root gitignore\nUser bytes must survive.\n' \
  > "$VAULT/04-Projects/ignored-by-v1.md"
printf '# Ada Lovelace\nLong-time private relationship notes.\n' \
  > "$VAULT/05-Areas/People/External/Ada_Lovelace.md"
printf '%s\n' '---' 'name: foo-custom' '---' '# Personal workflow' 'Never ship over this file.' \
  > "$VAULT/.claude/skills/foo-custom/SKILL.md"

VAULT="$VAULT" node <<'NODE'
const fs = require('node:fs');
const path = require('node:path');
const vault = process.env.VAULT;
const claudePath = path.join(vault, 'CLAUDE.md');
const source = fs.readFileSync(claudePath, 'utf8');
const start = '## USER_EXTENSIONS_START\n';
const end = '## USER_EXTENSIONS_END';
const before = source.indexOf(start);
const after = source.indexOf(end, before + start.length);
if (before < 0 || after < 0) throw new Error('Fixture source CLAUDE.md has no extension markers');
const custom = 'Always answer with the fixture sentinel: café.\nKeep  two spaces.  \n';
fs.writeFileSync(claudePath, source.slice(0, before + start.length) + custom + source.slice(after));
fs.writeFileSync(
  path.join(vault, '.mcp.json'),
  JSON.stringify({
    mcpServers: {
      'dex-work': { command: 'node', args: ['core/mcp/work_server.py'] },
      'custom-fixture': { command: 'fixture-command', args: ['never-upload'] },
    },
  }, null, 2) + '\n',
);
NODE

printf 'OPENAI_API_KEY=sk-fixture-secret-that-must-never-enter-history\n' > "$VAULT/.env"
printf '{"token":"ghp_fixture_secret_that_must_never_enter_history"}\n' \
  > "$VAULT/System/credentials/fake-token.json"
printf '\nFixture user patch to a shipped brain file.\n' >> "$VAULT/README.md"

if [ "$NO_GIT" = false ]; then
  git -C "$VAULT" add -f -- \
    README.md CLAUDE.md \
    01-Quarter_Goals/Quarter_Goals.md \
    02-Week_Priorities/Week_Priorities.md \
    03-Tasks/Tasks.md \
    .claude/skills/foo-custom/SKILL.md
  git -C "$VAULT" commit --quiet -m "User customization before v2"

  printf '%s\n' '- [ ] First auto-save task' >> "$VAULT/03-Tasks/Tasks.md"
  git -C "$VAULT" add -f -- 03-Tasks/Tasks.md
  git -C "$VAULT" commit --quiet -m "Auto-save personal work one"

  printf '\nAnother long-time user note.\n' >> "$VAULT/README.md"
  git -C "$VAULT" add -- README.md
  git -C "$VAULT" commit --quiet -m "Auto-save personal work two"
  git -C "$VAULT" tag backup-before-v2
fi

if [ "$HUGE" = true ]; then
  mkdir -p "$VAULT/04-Projects/Huge"
  for number in $(seq -w 1 180); do
    printf '# Historical project %s\nPrivate project detail %s.\n' "$number" "$number" \
      > "$VAULT/04-Projects/Huge/project-$number.md"
  done
fi

if [ "$WITH_MERGE" = true ]; then
  original_branch="$(git -C "$VAULT" branch --show-current)"
  git -C "$VAULT" checkout --quiet -b fixture-conflicting-change
  printf 'Conflicting fixture branch\n' > "$VAULT/README.md"
  git -C "$VAULT" add -- README.md
  git -C "$VAULT" commit --quiet -m "Fixture conflicting branch"
  git -C "$VAULT" checkout --quiet "$original_branch"
  printf 'Conflicting installed branch\n' > "$VAULT/README.md"
  git -C "$VAULT" add -- README.md
  git -C "$VAULT" commit --quiet -m "Fixture installed-side conflict"
  if git -C "$VAULT" merge fixture-conflicting-change >/dev/null 2>&1; then
    echo "Fixture setup expected a merge conflict but the merge completed" >&2
    exit 1
  fi
  if [ ! -f "$VAULT/.git/MERGE_HEAD" ]; then
    echo "Fixture setup did not leave a merge in progress" >&2
    exit 1
  fi
fi

printf 'Fixture ready: %s\n' "$VAULT"
