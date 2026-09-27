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
  if git -C "$dest" rev-parse --verify 'refs/remotes/origin/release^{commit}' >/dev/null 2>&1; then
    return 0
  fi
  if git -C "$dest" rev-parse --verify 'refs/remotes/official/release^{commit}' >/dev/null 2>&1; then
    return 0
  fi
  # A shallow PR checkout has no origin/release. Fetch the official release
  # branch by URL so the brain/vault split can prove history.
  if ! git -C "$dest" remote | grep -qx official; then
    git -C "$dest" remote add official https://github.com/davekilleen/Dex.git
  fi
  git -C "$dest" fetch --depth=1 official release
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
    python "$GITHUB_WORKSPACE/scripts/run-windows-lifecycle-journey.py" --vault-root "$DEST_UNIX"
    ;;
  *)
    usage
    ;;
esac
