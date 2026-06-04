#!/usr/bin/env bash
set -euo pipefail
FILE="$1"
if [ -z "${FILE:-}" ]; then
  echo "Usage: compile_mq5_poll.sh <file.mq5>"
  exit 2
fi
WINEPREFIX="${WINEPREFIX:-/Users/niko/Library/Application Support/net.metaquotes.wine.metatrader5}"
STEM="$(basename "${FILE}" .mq5)"
ROOT_EX5="${WINEPREFIX}/drive_c/Program Files/MetaTrader 5/MQL5/Experts/${STEM}.ex5"
PHANTOM_EX5="${WINEPREFIX}/drive_c/Program Files/MetaTrader 5/MQL5/Experts/phantom/${STEM}.ex5"

echo "Invoking MetaEditor compile for ${FILE}..."
.vscode/scripts/compile_mq5.sh "${FILE}" || true

echo "Waiting up to 30s for EX5 to appear..."
for i in {1..30}; do
  if [ -f "${PHANTOM_EX5}" ] || [ -f "${ROOT_EX5}" ]; then
    echo "EX5 created after ${i}s"
    ls -la "${PHANTOM_EX5}" "${ROOT_EX5}" 2>/dev/null || true
    break
  fi
  sleep 1
done

if [ ! -f "${PHANTOM_EX5}" ] && [ ! -f "${ROOT_EX5}" ]; then
  echo "EX5 not found. Showing recent metaeditor.log lines (UTF-16 -> UTF-8):"
  LOG="${WINEPREFIX}/drive_c/Program Files/MetaTrader 5/logs/metaeditor.log"
  if [ -f "${LOG}" ]; then
    iconv -f utf-16 -t utf-8 "${LOG}" | tail -n 200
  else
    echo "metaeditor.log not found at ${LOG}"
  fi
  exit 5
fi

echo "Done."
