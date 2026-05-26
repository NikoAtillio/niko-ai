#!/usr/bin/env bash
set -euo pipefail

SOURCE="${1:-}"
if [[ -z "${SOURCE}" ]]; then
  echo "Usage: sync_mt5_ea.sh <source.mq5>"
  exit 2
fi

if [[ ! -f "${SOURCE}" ]]; then
  echo "Source file not found: ${SOURCE}"
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WINEPREFIX="${WINEPREFIX:-/Users/niko/Library/Application Support/net.metaquotes.wine.metatrader5}"
MT5_ROOT="${WINEPREFIX}/drive_c/Program Files/MetaTrader 5"
EXPERTS_ROOT="${MT5_ROOT}/MQL5/Experts"

BASENAME="$(basename "${SOURCE}")"
STEM="${BASENAME%.mq5}"

ROOT_SOURCE="${EXPERTS_ROOT}/${BASENAME}"
ROOT_EX5="${EXPERTS_ROOT}/${STEM}.ex5"
SOURCE_EX5="$(dirname "${SOURCE}")/${STEM}.ex5"
PHANTOM_ROOT="${EXPERTS_ROOT}/phantom"
PHANTOM_SOURCE="${PHANTOM_ROOT}/${BASENAME}"
PHANTOM_EX5="${PHANTOM_ROOT}/${STEM}.ex5"

mkdir -p "${EXPERTS_ROOT}"
cp "${SOURCE}" "${ROOT_SOURCE}"
mkdir -p "${PHANTOM_ROOT}"
cp "${SOURCE}" "${PHANTOM_SOURCE}"

echo "Synced source to MT5 folder:"
echo "  ${ROOT_SOURCE}"
echo "  ${PHANTOM_SOURCE}"

if [[ "${NO_COMPILE:-0}" == "1" ]]; then
  echo "NO_COMPILE=1 set; skipping MetaEditor compile."
  exit 0
fi

"${WORKSPACE_ROOT}/.vscode/scripts/compile_mq5.sh" "${PHANTOM_SOURCE}"

COMPILED_EX5=""
for candidate in "${PHANTOM_EX5}" "${ROOT_EX5}" "${SOURCE_EX5}"; do
  if [[ -f "${candidate}" ]]; then
    COMPILED_EX5="${candidate}"
    break
  fi
done

if [[ -z "${COMPILED_EX5}" ]]; then
  echo "Compiled EX5 not found after compile. Checked: ${ROOT_EX5}, ${SOURCE_EX5}"
  exit 5
fi

if [[ "${COMPILED_EX5}" != "${ROOT_EX5}" ]]; then
  cp "${COMPILED_EX5}" "${ROOT_EX5}"
fi

if [[ "${COMPILED_EX5}" != "${PHANTOM_EX5}" ]]; then
  cp "${COMPILED_EX5}" "${PHANTOM_EX5}"
fi

echo "Synced compiled EX5 to:"
echo "  ${ROOT_EX5}"
echo "  ${PHANTOM_EX5}"
