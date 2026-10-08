#!/bin/bash
# Advisory Windows install legs for .github/workflows/windows-install.yml.
# Git Bash on windows-latest. Each subcommand isolates its clone.
set -euo pipefail

PROVENANCE_REFUSAL='Dex could not prove that the local release branch contains only official release history'

usage() {
  echo "usage: $0 {install-cygwin-stub|install-msys-journey|install-ps1-negative|beginner-helpers}" >&2
  exit 2
}

windows_vault_path() {
  local leaf="$1"
  RUN_LEAF="$leaf" python -c "import os; from pathlib import Path; print(Path(os.environ['RUNNER_TEMP']) / 'Dex Vault' / os.environ['RUN_LEAF'])"
}

unix_path() {
  local win="$1"
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -u "$win"
  else
    WIN_PATH="$win" python -c "from pathlib import Path; print(Path(os.environ['WIN_PATH']).as_posix())"
  fi
}

make_store_stub() {
  local stub_dir
  stub_dir="$(unix_path "$(python -c "import os; from pathlib import Path; print(Path(os.environ['RUNNER_TEMP']) / 'windowsapps-stub')")")"
  mkdir -p "$stub_dir"
  # Microsoft Store app-execution alias: python3 is on PATH first and fails
  # with 9009 instead of launching a real interpreter.
  cat > "$stub_dir/python3" <<'STUB'
#!/bin/bash
echo "Python was not found; run without arguments to install from the Microsoft Store, or disable this shortcut from Settings > Apps > Advanced app settings > App execution aliases." >&2
exit 9009
STUB
  chmod +x "$stub_dir/python3"
  cp "$stub_dir/python3" "$stub_dir/python3.exe"
  printf '%s\n' "$stub_dir"
}

ensure_official_release_ref() {
  local dest="$1"
  if ! git -C "$dest" remote | grep -qx official; then
    git -C "$dest" remote add official https://github.com/davekilleen/Dex.git
  fi
  # A shallow PR checkout has no origin/release. Fetch the full official
  # release branch (not depth-1: P8 walks parents and reports a broken link).
  # --update-shallow lets a shallow clone receive those parent objects.
  # Never copy a release ref from the CI workspace: a leg must not pass
  # against a non-official ref. Official fetch failure is failure.
  if git -C "$dest" fetch --update-shallow official \
      +refs/heads/release:refs/remotes/official/release; then
    git -C "$dest" rev-parse --verify 'refs/remotes/official/release^{commit}'
    return 0
  fi
  echo "could not resolve official refs/heads/release (official fetch failed; refusing unofficial workspace fallback)" >&2
  return 1
}

clone_into() {
  local dest_unix="$1"
  rm -rf "$dest_unix"
  mkdir -p "$(dirname "$dest_unix")"
  git clone --local --no-hardlinks "$GITHUB_WORKSPACE" "$dest_unix"
  ensure_official_release_ref "$dest_unix"
}

# Official releases ship a generated catalog bound to that tree. A PR
# checkout does not, and planting the official catalog onto PR files fails
# the binding check. Add the generated paths to this tree's manifest, then
# generate a catalog that matches it.
ensure_generated_catalog() {
  local dest_win="$1"
  DEST_WIN="$dest_win" python - <<'PY'
from pathlib import Path
import os
dest = Path(os.environ["DEST_WIN"])
manifest = dest / "System" / ".installed-files.manifest"
required = (
    "System/.release-catalog.json",
    "core/lifecycle/catalog/release-hashes.json",
)
lines = manifest.read_bytes().decode("utf-8").splitlines() if manifest.is_file() else []
lines = [line for line in lines if line]
for item in required:
    if item not in lines:
        lines.append(item)
manifest.parent.mkdir(parents=True, exist_ok=True)
manifest.write_bytes(("\n".join(sorted(set(lines))) + "\n").encode("utf-8"))
PY
  PYTHONPATH="$GITHUB_WORKSPACE" \
    python "$GITHUB_WORKSPACE/scripts/generate-release-catalog.py" \
    --release-root "$dest_win" \
    --contract-root "$GITHUB_WORKSPACE"
}

run_install_sh() {
  local ostype_value="$1"
  # Close stdin so install.sh cannot hang on read -p.
  OSTYPE="$ostype_value" bash ./install.sh </dev/null
}

write_tracked_listing() {
  local root="$1"
  local out="$2"
  ROOT="$root" OUT="$out" python - <<'PY'
from pathlib import Path
import hashlib
import os
import subprocess

root = Path(os.environ["ROOT"])
out = Path(os.environ["OUT"])
names = subprocess.check_output(
    ["git", "-C", str(root), "ls-files", "-z"],
    stderr=subprocess.STDOUT,
).split(b"\0")
lines = []
for raw in names:
    if not raw:
        continue
    rel = raw.decode("utf-8")
    path = root / rel
    if not path.is_file() or path.is_symlink():
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    lines.append(f"{digest} {rel}")
out.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
PY
}

assert_ps1_vault_unsplit_and_unchanged() {
  local root="$1"
  local before="$2"
  ROOT="$root" BEFORE="$before" python - <<'PY'
from pathlib import Path
import hashlib
import os
import subprocess
import sys

root = Path(os.environ["ROOT"])
before = {}
for line in Path(os.environ["BEFORE"]).read_text(encoding="utf-8").splitlines():
    digest, rel = line.split(" ", 1)
    before[rel] = digest

# A completed or started split rewrites Git layout. Any of these means the
# unofficial checkout was treated as installable.
split_markers = (
    Path(".dex/brain.git"),
    Path("System/.dex/topology.json"),
    Path(".dex/pre-split-archive.git"),
)
for marker in split_markers:
    if (root / marker).exists():
        print(f"vault split artifact present: {marker.as_posix()}", file=sys.stderr)
        sys.exit(1)

git_dir = root / ".git"
if not git_dir.is_dir():
    print("vault .git is no longer a directory; split may have started", file=sys.stderr)
    sys.exit(1)

# install.ps1 may rewrite dest-absolute path constants before the migrator
# refuses. Every other tracked file must stay byte-for-byte identical.
allowed_rewrite = {"core/paths.json"}
changed = []
for rel, digest in before.items():
    path = root / rel
    if not path.is_file():
        changed.append(f"removed {rel}")
        continue
    now = hashlib.sha256(path.read_bytes()).hexdigest()
    if now != digest and rel not in allowed_rewrite:
        changed.append(f"changed {rel}")

after_names = subprocess.check_output(
    ["git", "-C", str(root), "ls-files", "-z"],
).split(b"\0")
for raw in after_names:
    if not raw:
        continue
    rel = raw.decode("utf-8")
    if rel in before or rel in allowed_rewrite:
        continue
    path = root / rel
    if path.is_file() and not path.is_symlink():
        changed.append(f"added tracked {rel}")

if changed:
    print(
        "vault tracked files changed; expected byte-for-byte original files after provenance refusal:",
        file=sys.stderr,
    )
    print("\n".join(changed), file=sys.stderr)
    sys.exit(1)
print("vault_unsplit_and_preexisting_bytes_unchanged=yes")
PY
}

run_beginner_helpers() {
  # Non-install check of the beginner Windows copy and isolation rails.
  cd "${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
  DEX_INSTALL_LIB_ONLY=1 HOME="/c/dex-journey-home" DEX_INSTALL_REF=release \
    bash -c '
      set -e
      . ./install.sh
      target=$(dex_default_target)
      case "$target" in
        */Dex) ;;
        *) echo "release default must end in /Dex: $target" >&2; exit 1 ;;
      esac
      if dex_is_branch_test; then
        echo "release install must not be branch-test mode" >&2
        exit 1
      fi
      line=$(dex_apps_line)
      case "$line" in
        *"Dex is in beta"*) echo "must not say Dex is in beta" >&2; exit 1 ;;
        *heydex.ai/beta*) ;;
        *) echo "apps line missing beta signup: $line" >&2; exit 1 ;;
      esac
      provider=$(dex_cloud_provider "/c/dex-journey-home/OneDrive/Documents/Dex" || true)
      [ "$provider" = "OneDrive" ]
      echo "beginner_helpers_ok=yes"
    '
  DEX_INSTALL_LIB_ONLY=1 HOME="/c/dex-journey-home" DEX_INSTALL_DIR="/c/dex-journey-home/Dex-test" \
    DEX_INSTALL_REF="feature/beginner-install-test" \
    bash -c '
      set -e
      . ./install.sh
      if ! dex_is_branch_test; then
        echo "DEX_INSTALL_DIR must be branch-test mode" >&2
        exit 1
      fi
      target=$(dex_default_target)
      case "$target" in
        */Dex-test) ;;
        *) echo "branch-test default must be Dex-test: $target" >&2; exit 1 ;;
      esac
      echo "beginner_helpers_branch_ok=yes"
    '
}

run_install_ps1_negative() {
  local dest_win dest_unix before_file output status
  dest_win="$(windows_vault_path install-ps1)"
  dest_unix="$(unix_path "$dest_win")"
  echo "vault_path_windows=$dest_win"
  echo "vault_path_unix=$dest_unix"
  # Shallow PR clone only. Do not fetch official/release: this leg must
  # prove install.ps1 refuses unofficial history and leaves the vault unsplit.
  rm -rf "$dest_unix"
  mkdir -p "$(dirname "$dest_unix")"
  git clone --local --no-hardlinks "$GITHUB_WORKSPACE" "$dest_unix"
  cd "$dest_unix"
  if [ ! -f ./install.ps1 ]; then
    echo "install.ps1 is missing from this checkout. The PowerShell install path cannot be exercised until that file lands." >&2
    exit 1
  fi
  if ! command -v pwsh >/dev/null 2>&1; then
    echo "pwsh is required for the install.ps1 negative leg" >&2
    exit 1
  fi
  before_file="$(unix_path "$(python -c "import os; from pathlib import Path; print(Path(os.environ['RUNNER_TEMP']) / 'install-ps1-before.txt')")")"
  write_tracked_listing "$dest_unix" "$before_file"
  set +e
  output="$(pwsh -NoProfile -NonInteractive -File ./install.ps1 </dev/null 2>&1)"
  status=$?
  set -e
  printf '%s\n' "$output"
  echo "install_ps1_exit=$status"
  if [ "$status" -eq 0 ]; then
    echo "install.ps1 succeeded; this shallow PR checkout must refuse" >&2
    exit 1
  fi
  case "$output" in
    *"$PROVENANCE_REFUSAL"*)
      ;;
    *)
      echo "install.ps1 failed without the provenance refusal message" >&2
      exit 1
      ;;
  esac
  assert_ps1_vault_unsplit_and_unchanged "$dest_unix" "$before_file"
}

cmd="${1:-}"
case "$cmd" in
  install-cygwin-stub)
    DEST_WIN="$(windows_vault_path install-cygwin)"
    DEST_UNIX="$(unix_path "$DEST_WIN")"
    echo "vault_path_windows=$DEST_WIN"
    echo "vault_path_unix=$DEST_UNIX"
    clone_into "$DEST_UNIX"
    STUB_DIR="$(make_store_stub)"
    export PATH="$STUB_DIR:$PATH"
    echo "store_stub=$STUB_DIR"
    echo "python3=$(command -v python3 || echo missing)"
    cd "$DEST_UNIX"
    echo "OSTYPE_OVERRIDE=cygwin native_OSTYPE=${OSTYPE:-unset}"
    run_install_sh cygwin
    ;;
  install-msys-journey)
    DEST_WIN="$(windows_vault_path install-msys)"
    DEST_UNIX="$(unix_path "$DEST_WIN")"
    echo "vault_path_windows=$DEST_WIN"
    echo "vault_path_unix=$DEST_UNIX"
    clone_into "$DEST_UNIX"
    cd "$DEST_UNIX"
    echo "OSTYPE_OVERRIDE=msys native_OSTYPE=${OSTYPE:-unset}"
    run_install_sh msys
    ensure_generated_catalog "$DEST_WIN"
    PYTHONPATH="$GITHUB_WORKSPACE" \
      python "$GITHUB_WORKSPACE/scripts/run-windows-lifecycle-journey.py" --vault-root "$DEST_WIN"
    ;;
  install-ps1-negative)
    run_install_ps1_negative
    ;;
  beginner-helpers)
    run_beginner_helpers
    ;;
  *)
    usage
    ;;
esac
