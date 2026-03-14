#!/bin/bash
set -euo pipefail

REPORT_DIR="${1:-.logs/flaky}"
mkdir -p "$REPORT_DIR"

RUN1_OUT="$REPORT_DIR/run1.txt"
RUN2_OUT="$REPORT_DIR/run2.txt"
RUN1_FAIL="$REPORT_DIR/run1_failed.txt"
RUN2_FAIL="$REPORT_DIR/run2_failed.txt"
DIFF_OUT="$REPORT_DIR/flaky_diff.txt"

echo "Running flaky-test detector (pass 1)..."
pytest core/tests core/mcp/tests core/migrations/tests -q --maxfail=0 >"$RUN1_OUT" 2>&1 || true
grep -E '^FAILED ' "$RUN1_OUT" | awk '{print $2}' | sort -u >"$RUN1_FAIL" || true

echo "Running flaky-test detector (pass 2)..."
pytest core/tests core/mcp/tests core/migrations/tests -q --maxfail=0 >"$RUN2_OUT" 2>&1 || true
grep -E '^FAILED ' "$RUN2_OUT" | awk '{print $2}' | sort -u >"$RUN2_FAIL" || true

if diff -u "$RUN1_FAIL" "$RUN2_FAIL" >"$DIFF_OUT"; then
  echo "No flaky test signature detected across two runs."
  exit 0
fi

echo "Potential flaky tests detected. See $DIFF_OUT"
cat "$DIFF_OUT"
exit 1
