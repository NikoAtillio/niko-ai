#!/usr/bin/env bash
#
# Robust MQL5 compile script for MT5 under Wine/macOS
# Tries multiple approaches to locate the compiled EX5
#

set -euo pipefail

FILE="${1:?Usage: $0 <file.mq5>}"

if [ ! -f "$FILE" ]; then
  echo "Error: source file not found: $FILE"
  exit 1
fi

WINEPREFIX="${WINEPREFIX:-/Users/niko/Library/Application Support/net.metaquotes.wine.metatrader5}"
ME_EXE="$WINEPREFIX/drive_c/Program Files/MetaTrader 5/MetaEditor64.exe"
WINE_BIN="/usr/local/bin/wine"

if [ ! -f "$ME_EXE" ]; then
  echo "Error: MetaEditor not found at $ME_EXE"
  exit 2
fi

echo "[Compile] Input file: $FILE"
echo "[Compile] MetaEditor: $ME_EXE"

# Kill any stray wineserver
killall -9 wineserver 2>/dev/null || true
sleep 1

# Run compile
echo "[Compile] Running MetaEditor compile..."
WINEPREFIX="$WINEPREFIX" "$WINE_BIN" "$ME_EXE" /compile:"$FILE" 2>&1 | tail -30 || true

sleep 2

# Determine expected output paths
BASENAME=$(basename "$FILE")
STEM="${BASENAME%.mq5}"
REPO_EX5="${FILE%.mq5}.ex5"
MT5_EX5="$WINEPREFIX/drive_c/Program Files/MetaTrader 5/MQL5/Experts/$STEM.ex5"

# Search for recently created EX5 files in common locations
echo "[Compile] Searching for compiled EX5..."

FOUND_EX5=""

# Check direct locations
for path in "$MT5_EX5" "$REPO_EX5"; do
  if [ -f "$path" ]; then
    echo "[Compile] Found: $path"
    FOUND_EX5="$path"
    break
  fi
done

# If not found, search more broadly
if [ -z "$FOUND_EX5" ]; then
  echo "[Compile] Direct paths not found, searching MT5 folder..."
  RECENT_EX5=$(find "$WINEPREFIX/drive_c/Program Files/MetaTrader 5" -name "*$STEM*.ex5" -type f -newermt "-10 minutes" 2>/dev/null | head -1 || true)
  if [ -n "$RECENT_EX5" ]; then
    echo "[Compile] Found recent: $RECENT_EX5"
    FOUND_EX5="$RECENT_EX5"
  fi
fi

if [ -z "$FOUND_EX5" ]; then
  echo "[Compile] ERROR: Compiled EX5 not found after compile"
  echo "[Compile] Searched:"
  echo "  $MT5_EX5"
  echo "  $REPO_EX5"
  echo ""
  echo "[Compile] NOTE: MetaEditor under Wine may have issues compiling via command-line."
  echo "[Compile] WORKAROUND: Manually compile in MetaEditor GUI:"
  echo "  1. Open MetaEditor (from Terminal within MT5)"
  echo "  2. File -> Open -> $FILE"
  echo "  3. Compile button or Ctrl+F5"
  echo "  4. Wait for compile to finish"
  echo "  5. EX5 should appear at: $MT5_EX5"
  exit 5
fi

echo "[Compile] SUCCESS: $FOUND_EX5"
echo "[Compile] Size: $(stat -f%z "$FOUND_EX5" 2>/dev/null || stat -c%s "$FOUND_EX5") bytes"
exit 0
