#!/usr/bin/env bash
# Cloud Agent development environment setup for dex-core.
#
# Idempotent: safe to run repeatedly and on top of a prebuilt snapshot. It
# reproduces exactly what the CI workflow (.github/workflows/ci.yml) expects:
# Python 3.12 dev + runtime dependencies, Node dependencies, and the generated
# vault/path state, plus a few Cloud-Agent-specific fixes the macOS CI runners
# do not need.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- System packages ---------------------------------------------------------
# python3.12-venv: several tests build real virtualenvs and need ensurepip.
# rsync: scripts/build-vault-bundle.sh stages the release tree with it.
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends python3.12-venv rsync

# --- Trusted Node.js ---------------------------------------------------------
# scripts/dex_update_bridge.py only trusts executables found under /usr/bin,
# /bin, /usr/local/bin or /opt/homebrew/bin. Cloud Agents ship Node under
# /exec-daemon and ~/.nvm, so expose it in a trusted directory via symlink.
for bin in node npm npx; do
  target="$(command -v "$bin" || true)"
  [ -n "$target" ] && sudo ln -sf "$target" "/usr/local/bin/$bin"
done

# --- Python dependencies (global site) --------------------------------------
# Installed into the global interpreter (not --user) so that subprocesses which
# scrub HOME can still import them. --ignore-installed steps over the
# Debian-managed packages (PyJWT, cryptography) that pip cannot uninstall.
sudo pip install --break-system-packages --ignore-installed -r requirements-dev.txt
sudo pip install --break-system-packages --ignore-installed \
  "mcp>=1.0.0,<2.0.0" pyyaml python-dateutil requests

# --- Node dependencies -------------------------------------------------------
npm ci

# --- Developer environment defaults -----------------------------------------
# Match CI: point the vault at the test fixture, and pin an absolute interpreter
# for the Node script suite (dex-python.cjs rejects bare names like `python3`).
sudo tee /etc/profile.d/dex-dev.sh >/dev/null <<EOF
export VAULT_PATH="$REPO_ROOT/core/tests/fixtures/vault"
export DEX_PYTHON="/usr/bin/python3"
EOF

# --- Source-derived state ----------------------------------------------------
export VAULT_PATH="$REPO_ROOT/core/tests/fixtures/vault"
python3 -c "from core import paths; from pathlib import Path; [getattr(paths, n).mkdir(parents=True, exist_ok=True) for n in dir(paths) if n.endswith('_DIR') and isinstance(getattr(paths, n), Path)]"
python3 core/paths.py

echo "dex-core Cloud Agent environment ready."
