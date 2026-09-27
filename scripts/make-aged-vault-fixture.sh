#!/bin/bash
set -euo pipefail

SCRIPT_PATH="$0"
if command -v cygpath >/dev/null 2>&1; then
  SCRIPT_PATH="$(cygpath -u "$SCRIPT_PATH")"
fi
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

WITH_MERGE=false
NO_GIT=false
HUGE=false
ROOMS_OFF=false
for argument in "$@"; do
  case "$argument" in
    --with-merge-in-progress) WITH_MERGE=true ;;
    --no-git) NO_GIT=true ;;
    --huge) HUGE=true ;;
    --rooms-off) ROOMS_OFF=true ;;
    *) echo "Unknown fixture flag: $argument" >&2; exit 2 ;;
  esac
done

if [ "$WITH_MERGE" = true ] && [ "$NO_GIT" = true ]; then
  echo "--with-merge-in-progress and --no-git cannot describe the same fixture" >&2
  exit 2
fi

# Git Bash sets TMPDIR=/tmp, which Python's pathlib cannot open on Windows.
# Prefer the native TEMP folder, then print a Windows path at the end.
if command -v cygpath >/dev/null 2>&1; then
  _tmp="$(cygpath -u "${TEMP:-${TMP:-${TMPDIR:-/tmp}}}")"
else
  _tmp="${TMPDIR:-${TEMP:-/tmp}}"
fi
FIXTURE_ROOT="$(mktemp -d "${_tmp}/dex-aged-vault.XXXXXX")"
UPSTREAM="$FIXTURE_ROOT/upstream"
VAULT="$FIXTURE_ROOT/Dex Vault - Aged"

# Use Git's local transport instead of the direct object-directory copier. Node's
# test runner builds several fixtures in parallel; --no-local gives each fixture
# an independently received object store without touching the network.
# A clone of a detached/shallow checkout can land on the default branch tip
# (not the worktree HEAD). Pin to the live commit so CLAUDE.md still has
# USER_EXTENSIONS markers.
SOURCE_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
git clone --no-local --quiet "$REPO_ROOT" "$UPSTREAM"
if ! git -C "$UPSTREAM" cat-file -e "$SOURCE_HEAD^{commit}" 2>/dev/null; then
  git -C "$UPSTREAM" fetch --no-tags "$REPO_ROOT" "$SOURCE_HEAD"
fi
# Windows Git may rewrite checked-out text to CRLF; the fixture editor
# looks for USER_EXTENSIONS markers and must see the worktree bytes.
git -C "$UPSTREAM" config core.autocrlf false
git -C "$UPSTREAM" checkout --force -B main "$SOURCE_HEAD" --quiet
git -C "$UPSTREAM" config user.name "Dex Fixture Builder"
git -C "$UPSTREAM" config user.email "fixture-builder@example.com"

# Include the live migrator even while it is still uncommitted in this worktree.
# The contract, tracked-ignore policy, and transition metadata come from v1.63.
# CLAUDE.md is copied from the live worktree so USER_EXTENSIONS markers match
# this checkout when the clone otherwise lands on another tip.
D1_FILES=(
  CLAUDE.md
  core/data/sync-folder-markers.json
  core/migrations/sync-folder-detector.cjs
  core/migrations/v1-to-v2-brain-vault-split.cjs
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

# Always collapse to a single complete root. A shallow PR merge commit's
# parents are not in the object store; copying that commit into a new repo
# drops .git/shallow and P8 fsck reports broken links.
_tree="$(git -C "$UPSTREAM" rev-parse 'HEAD^{tree}')"
_root="$(git -C "$UPSTREAM" commit-tree "$_tree" -m "fixture: self-contained source tree")"
git -C "$UPSTREAM" checkout --force -B main "$_root" --quiet
git -C "$UPSTREAM" branch -f release HEAD

if [ "$NO_GIT" = true ]; then
  mkdir -p "$VAULT"
  RELEASE_ARCHIVE="$FIXTURE_ROOT/release.tar"
  git -C "$UPSTREAM" archive --output="$RELEASE_ARCHIVE" release
  tar -xf "$RELEASE_ARCHIVE" -C "$VAULT"
else
  git clone --no-local --quiet --branch release "$UPSTREAM" "$VAULT"
  git -C "$VAULT" config user.name "Long-time Dex User"
  git -C "$VAULT" config user.email "user@example.com"
  git -C "$VAULT" config core.autocrlf false
  git -C "$VAULT" remote rename origin upstream
  git -C "$VAULT" remote set-url upstream https://github.com/davekilleen/Dex.git
  git -C "$VAULT" remote add private-backup https://example.invalid/private-dex-vault.git
fi

# Post-retirement releases no longer track slack.yaml; a real aged vault has it
# as LOCAL user state (preserved by the untrack capture). Model that.
if [ ! -f "$VAULT/System/integrations/slack.yaml" ]; then
  mkdir -p "$VAULT/System/integrations"
  printf 'enabled: false\nchannels: []\n' > "$VAULT/System/integrations/slack.yaml"
fi

# Current releases ship a profile template, never a live profile. An aged user
# already has a profile, so recreate that installed state before adding fixture
# choices below.
if [ ! -f "$VAULT/System/user-profile.yaml" ]; then
  cp "$VAULT/System/user-profile-template.yaml" "$VAULT/System/user-profile.yaml"
fi

mkdir -p \
  "$VAULT/04-Projects" \
  "$VAULT/05-Areas/People/External" \
  "$VAULT/.claude/skills-custom/foo" \
  "$VAULT/System/credentials"

if [ "$ROOMS_OFF" = false ]; then
  mkdir -p "$VAULT/01-Quarter_Goals" "$VAULT/05-Areas/Career" "$VAULT/05-Areas/Companies"
  printf '# Quarter Goals\n' > "$VAULT/01-Quarter_Goals/Quarter_Goals.md"
  printf '# Career room user note\n' > "$VAULT/05-Areas/Career/private-note.md"
  printf '# Companies room user note\n' > "$VAULT/05-Areas/Companies/private-note.md"
  VAULT="$VAULT" node <<'NODE'
const fs = require('node:fs');
const path = require('node:path');
const profile = path.join(process.env.VAULT, 'System', 'user-profile.yaml');
const source = fs.readFileSync(profile, 'utf8');
const start = source.indexOf('capabilities:');
const end = source.indexOf('\nquarterly_planning:', start);
if (start < 0 || end < 0) throw new Error('Fixture profile has no capabilities block');
fs.writeFileSync(profile, source.slice(0, start) + source.slice(start, end).replaceAll('enabled: false', 'enabled: true') + source.slice(end));
NODE
fi

printf '\n- [ ] User-edited task seed\n' >> "$VAULT/03-Tasks/Tasks.md"
if [ "$ROOMS_OFF" = false ]; then
  printf '\n- User-edited quarterly goal\n' >> "$VAULT/01-Quarter_Goals/Quarter_Goals.md"
else
  rm -rf "$VAULT/01-Quarter_Goals" "$VAULT/05-Areas/Career" "$VAULT/05-Areas/Companies"
fi
printf '\n- User-edited weekly priority\n' >> "$VAULT/02-Week_Priorities/Week_Priorities.md"
printf '# A project ignored by the v1 root gitignore\nUser bytes must survive.\n' \
  > "$VAULT/04-Projects/ignored-by-v1.md"
printf '# Ada Lovelace\nLong-time private relationship notes.\n' \
  > "$VAULT/05-Areas/People/External/Ada_Lovelace.md"
printf '%s\n' '---' 'name: foo-custom' '---' '# Personal workflow' 'Never ship over this file.' \
  > "$VAULT/.claude/skills-custom/foo/SKILL.md"

VAULT="$VAULT" node <<'NODE'
const fs = require('node:fs');
const path = require('node:path');
const vault = process.env.VAULT;
const claudePath = path.join(vault, 'CLAUDE.md');
const source = fs.readFileSync(claudePath, 'utf8');
const start = '## USER_EXTENSIONS_START';
const end = '## USER_EXTENSIONS_END';
const before = source.indexOf(start);
const after = source.indexOf(end, before + start.length);
if (before < 0 || after < 0) throw new Error('Fixture source CLAUDE.md has no extension markers');
let insertAt = before + start.length;
if (source.startsWith('\r', insertAt)) insertAt += 1;
if (source.startsWith('\n', insertAt)) insertAt += 1;
const custom = 'Always answer with the fixture sentinel: café.\nKeep  two spaces.  \n';
fs.writeFileSync(claudePath, source.slice(0, insertAt) + custom + source.slice(after));
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
    02-Week_Priorities/Week_Priorities.md \
    03-Tasks/Tasks.md \
    .claude/skills-custom/foo/SKILL.md
  if [ "$ROOMS_OFF" = false ]; then
    git -C "$VAULT" add -f -- 01-Quarter_Goals/Quarter_Goals.md
  fi
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

if command -v cygpath >/dev/null 2>&1; then
  printf 'Fixture ready: %s\n' "$(cygpath -w "$VAULT")"
else
  printf 'Fixture ready: %s\n' "$VAULT"
fi
