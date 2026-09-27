#!/bin/bash
# Advisory Windows install legs for .github/workflows/windows-install.yml.
# Git Bash on windows-latest. Each subcommand isolates its clone.
set -euo pipefail

usage() {
  echo "usage: $0 {install-cygwin-stub|install-msys-journey}" >&2
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
  local workspace="${GITHUB_WORKSPACE:-}"
  if ! git -C "$dest" remote | grep -qx official; then
    git -C "$dest" remote add official https://github.com/davekilleen/Dex.git
  fi
  # A shallow PR checkout has no origin/release. Fetch the full official
  # release branch (not depth-1: P8 walks parents and reports a broken link).
  # --update-shallow lets a shallow clone receive those parent objects.
  if git -C "$dest" fetch --update-shallow official \
      +refs/heads/release:refs/remotes/official/release; then
    git -C "$dest" rev-parse --verify 'refs/remotes/official/release^{commit}'
    return 0
  fi
  # Origin on this clone is the GHA workspace, which also has no release
  # branch. Reuse a release ref already present on the workspace, or fetch
  # official release into the workspace and copy it across.
  if [ -n "$workspace" ] && git -C "$workspace" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if ! git -C "$workspace" remote | grep -qx official; then
      git -C "$workspace" remote add official https://github.com/davekilleen/Dex.git
    fi
    git -C "$workspace" fetch --update-shallow official \
      +refs/heads/release:refs/remotes/official/release || true
    if git -C "$workspace" rev-parse --verify 'refs/remotes/official/release^{commit}' >/dev/null 2>&1; then
      git -C "$dest" fetch --update-shallow "$workspace" \
        +refs/remotes/official/release:refs/remotes/official/release
      git -C "$dest" rev-parse --verify 'refs/remotes/official/release^{commit}'
      return 0
    fi
    if git -C "$workspace" rev-parse --verify 'refs/heads/release^{commit}' >/dev/null 2>&1; then
      git -C "$dest" fetch --update-shallow "$workspace" \
        +refs/heads/release:refs/remotes/official/release
      git -C "$dest" rev-parse --verify 'refs/remotes/official/release^{commit}'
      return 0
    fi
  fi
  echo "could not resolve official refs/heads/release (origin has no release branch)" >&2
  return 1
}

clone_into() {
  local dest_unix="$1"
  rm -rf "$dest_unix"
  mkdir -p "$(dirname "$dest_unix")"
  git clone --local --no-hardlinks "$GITHUB_WORKSPACE" "$dest_unix"
  ensure_official_release_ref "$dest_unix"
}

run_install_sh() {
  local ostype_value="$1"
  # Close stdin so install.sh cannot hang on read -p.
  OSTYPE="$ostype_value" bash ./install.sh </dev/null
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
    # Official releases ship the generated catalog. A PR checkout does not.
    # Activate needs that file; generate it from this tree so the journey
    # matches a real release without changing install.sh.
    if [ ! -f "$DEST_UNIX/System/.release-catalog.json" ]; then
      PYTHONPATH="$GITHUB_WORKSPACE" \
        python "$GITHUB_WORKSPACE/scripts/generate-release-catalog.py" \
        --release-root "$DEST_WIN" \
        --contract-root "$GITHUB_WORKSPACE"
    fi
    PYTHONPATH="$GITHUB_WORKSPACE" \
      python "$GITHUB_WORKSPACE/scripts/run-windows-lifecycle-journey.py" --vault-root "$DEST_WIN"
    ;;
  *)
    usage
    ;;
esac
