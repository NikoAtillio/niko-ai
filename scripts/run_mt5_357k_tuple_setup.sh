#!/usr/bin/env bash
set -euo pipefail

# Exact 357k reproduction tuple:
# - Bridge source from commit cc58db2
# - Signal source from commit cc58db2
# This avoids mixing older v2 absolute-loss bridge variants.

ROOT="/Users/niko/Documents/projects/niko-ai"
SYNC_SCRIPT="${ROOT}/scripts/sync_mt5_ea.sh"
VERIFY_SCRIPT="${ROOT}/scripts/verify_357k_signal_hash.sh"
TUPLE_COMMIT="cc58db2c0bba24ef1a038e8fd217e09189498fa7"
BRIDGE_PATH_IN_REPO="phantom/mql5/PhantomBridge_v2.mq5"
SIGNAL_PATH_IN_REPO="signals/phantom_signals.jsonl"
TMP_DIR="${ROOT}/tmp"
TMP_BRIDGE="${TMP_DIR}/PhantomBridge_v2.mq5"
TMP_SIGNAL="${TMP_DIR}/phantom_signals_357k_tuple.jsonl"
WINEPREFIX_DEFAULT="/Users/niko/Library/Application Support/net.metaquotes.wine.metatrader5"
WINEPREFIX="${WINEPREFIX:-${WINEPREFIX_DEFAULT}}"

mkdir -p "${TMP_DIR}"

if [[ ! -f "${SYNC_SCRIPT}" ]]; then
  echo "Sync script missing: ${SYNC_SCRIPT}"
  exit 2
fi

if [[ ! -f "${VERIFY_SCRIPT}" ]]; then
  echo "Verify script missing: ${VERIFY_SCRIPT}"
  exit 2
fi

echo "[1/5] Exporting bridge and signal from tuple commit ${TUPLE_COMMIT}..."
git show "${TUPLE_COMMIT}:${BRIDGE_PATH_IN_REPO}" > "${TMP_BRIDGE}"
git show "${TUPLE_COMMIT}:${SIGNAL_PATH_IN_REPO}" > "${TMP_SIGNAL}"

echo "[2/5] Syncing and compiling tuple bridge into MT5 Experts..."
bash "${SYNC_SCRIPT}" "${TMP_BRIDGE}"

echo "[3/5] Detecting MT5 Common/Files targets..."
TARGET_DIRS=()
while IFS= read -r d; do
  TARGET_DIRS+=("${d}")
done < <(find "${WINEPREFIX}/drive_c" -type d -path "*/AppData/Roaming/MetaQuotes/Terminal/Common/Files" 2>/dev/null)

if [[ ${#TARGET_DIRS[@]} -eq 0 ]]; then
  echo "No MT5 Common/Files directories found under: ${WINEPREFIX}"
  exit 3
fi

for d in "${TARGET_DIRS[@]}"; do
  echo "  - ${d}"
done

echo "[4/5] Copying tuple signal to each Common/Files path..."
for d in "${TARGET_DIRS[@]}"; do
  cp "${TMP_SIGNAL}" "${d}/phantom_signals.jsonl"
  echo "  copied -> ${d}/phantom_signals.jsonl"
done

echo "[5/5] Verifying canonical 357k hash at each destination..."
for d in "${TARGET_DIRS[@]}"; do
  echo "  checking ${d}/phantom_signals.jsonl"
  bash "${VERIFY_SCRIPT}" "${d}/phantom_signals.jsonl"
done

echo
echo "Tuple setup complete."
echo "In MT5 Strategy Tester use Expert: PhantomBridge_v2"
echo "This tuple should expose v2 inputs like InpDailyLossPct/InpMaxLossPct (not MaxDailyLoss/MaxOverallLoss)."
