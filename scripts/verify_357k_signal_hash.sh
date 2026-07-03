#!/usr/bin/env bash
set -euo pipefail

# Canonical 357k provenance signal artifact (commit: cc58db2)
EXPECTED_HASH="ab1a6829f11f87d90405fd009d42e8b5fce2c0bc0dc56ca3a5cbce305f511756"
EXPECTED_COMMIT="cc58db2c0bba24ef1a038e8fd217e09189498fa7"
DEFAULT_SIGNAL_FILE="signals/phantom_signals.jsonl"

TARGET_FILE="${1:-$DEFAULT_SIGNAL_FILE}"

if [[ ! -f "$TARGET_FILE" ]]; then
  echo "ERROR: file not found: $TARGET_FILE"
  echo "Usage: $0 [path/to/signal.jsonl]"
  exit 2
fi

ACTUAL_HASH="$(shasum -a 256 "$TARGET_FILE" | awk '{print $1}')"

echo "Target file   : $TARGET_FILE"
echo "Actual hash   : $ACTUAL_HASH"
echo "Expected hash : $EXPECTED_HASH"
echo "Expected src  : commit $EXPECTED_COMMIT :: signals/phantom_signals.jsonl"

if [[ "$ACTUAL_HASH" == "$EXPECTED_HASH" ]]; then
  echo "RESULT: PASS (exact canonical 357k signal artifact)"
  exit 0
fi

echo "RESULT: FAIL (not the canonical 357k signal artifact)"
exit 1
