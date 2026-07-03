#!/usr/bin/env bash
set -euo pipefail

# One-shot setup for the legacy 357k reproduction tuple.
# It syncs the legacy PhantomBridge_v2.mq5 into MT5, copies the canonical
# signal file to all detected Common/Files locations, and verifies hash.

ROOT="/Users/niko/Documents/projects/niko-ai"
LEGACY_ROOT="/Users/niko/Documents/projects/niko-ai-legacy-v2"
SYNC_SCRIPT="${ROOT}/scripts/sync_mt5_ea.sh"
VERIFY_SCRIPT="${ROOT}/scripts/verify_357k_signal_hash.sh"
LEGACY_MQ5="${LEGACY_ROOT}/phantom/mql5/PhantomBridge_v2.mq5"
LEGACY_SIGNAL="${LEGACY_ROOT}/signals/phantom_signals.jsonl"
WINEPREFIX_DEFAULT="/Users/niko/Library/Application Support/net.metaquotes.wine.metatrader5"
WINEPREFIX="${WINEPREFIX:-${WINEPREFIX_DEFAULT}}"

if [[ ! -f "${SYNC_SCRIPT}" ]]; then
  echo "Sync script missing: ${SYNC_SCRIPT}"
  exit 2
fi

if [[ ! -f "${VERIFY_SCRIPT}" ]]; then
  echo "Verify script missing: ${VERIFY_SCRIPT}"
  exit 2
fi

if [[ ! -f "${LEGACY_MQ5}" ]]; then
  echo "Legacy MQ5 not found: ${LEGACY_MQ5}"
  exit 2
fi

if [[ ! -f "${LEGACY_SIGNAL}" ]]; then
  echo "Legacy signal not found: ${LEGACY_SIGNAL}"
  exit 2
fi

echo "[1/4] Syncing and compiling legacy bridge into MT5 Experts..."
bash "${SYNC_SCRIPT}" "${LEGACY_MQ5}"

echo "[2/4] Detecting MT5 Common/Files targets..."
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

echo "[3/4] Copying canonical legacy signal to each Common/Files path..."
for d in "${TARGET_DIRS[@]}"; do
  cp "${LEGACY_SIGNAL}" "${d}/phantom_signals.jsonl"
  echo "  copied -> ${d}/phantom_signals.jsonl"
done

echo "[4/4] Verifying canonical hash at each copied destination..."
for d in "${TARGET_DIRS[@]}"; do
  echo "  checking ${d}/phantom_signals.jsonl"
  bash "${VERIFY_SCRIPT}" "${d}/phantom_signals.jsonl"
done

echo
echo "Setup complete. In MT5 Strategy Tester use:"
echo "  Expert: PhantomBridge_v2"
echo "  Date range: 2023.01.01 -> 2026.01.01"
echo "  Signal file: phantom_signals.jsonl (already copied to Common/Files)"
