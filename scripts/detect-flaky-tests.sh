#!/bin/bash
set -euo pipefail

REPORT_DIR="${1:-.logs/flaky}"
mkdir -p "$REPORT_DIR"

RUN1_OUT="$REPORT_DIR/run1.txt"
RUN2_OUT="$REPORT_DIR/run2.txt"
RUN1_FAIL="$REPORT_DIR/run1_failed.txt"
RUN2_FAIL="$REPORT_DIR/run2_failed.txt"
DIFF_OUT="$REPORT_DIR/flaky_diff.txt"

run_pytest_pass() {
  local label="$1"
  local output="$2"
  local status

  if pytest core/tests core/mcp/tests core/migrations/tests -q -m "not fuzz" --maxfail=0 >"$output" 2>&1; then
    status=0
  else
    status=$?
  fi

  # pytest exit 1 means tests ran and at least one failed, which this detector
  # intentionally tolerates so it can compare deterministic vs flaky failures.
  if [ "$status" -eq 5 ]; then
    echo "Flaky-test detector $label collected no tests; refusing a false green." >&2
    cat "$output" >&2
    return 1
  fi

  if [ "$status" -ne 0 ] && [ "$status" -ne 1 ]; then
    echo "Flaky-test detector $label could not run pytest successfully (exit $status)." >&2
    cat "$output" >&2
    return 1
  fi

  local outcome_count
  outcome_count="$(
    awk '
      {
        for (i = 1; i < NF; i++) {
          if ($i ~ /^[0-9]+$/ && $(i + 1) ~ /^(passed|failed|skipped|xfailed|xpassed|error|errors)$/) {
            total += $i
          }
        }
      }
      END { print total + 0 }
    ' "$output"
  )"

  if [ "$outcome_count" -le 0 ]; then
    echo "Flaky-test detector $label collected no tests; refusing a false green." >&2
    cat "$output" >&2
    return 1
  fi
}

echo "Running flaky-test detector (pass 1)..."
run_pytest_pass "pass 1" "$RUN1_OUT"
grep -E '^FAILED ' "$RUN1_OUT" | awk '{print $2}' | sort -u >"$RUN1_FAIL" || true

echo "Running flaky-test detector (pass 2)..."
run_pytest_pass "pass 2" "$RUN2_OUT"
grep -E '^FAILED ' "$RUN2_OUT" | awk '{print $2}' | sort -u >"$RUN2_FAIL" || true

if diff -u "$RUN1_FAIL" "$RUN2_FAIL" >"$DIFF_OUT"; then
  echo "No flaky test signature detected across two runs."
  exit 0
fi

echo "Potential flaky tests detected. See $DIFF_OUT"
cat "$DIFF_OUT"
exit 1
