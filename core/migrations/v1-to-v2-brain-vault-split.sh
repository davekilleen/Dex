#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec node "$SCRIPT_DIR/v1-to-v2-brain-vault-split.cjs" "$@"
