#!/bin/bash
# Test MT5 EA with corrected UTC offset for US100/NYSE timezone

TESTER_DIR="/Users/niko/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/Tester"
AGENT_LOGS="$TESTER_DIR/Agent-127.0.0.1-3000/logs"
MT5_BIN="/Users/niko/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/terminal64.exe"

# Create logs directory if needed
mkdir -p "$AGENT_LOGS"

echo "=========================================="
echo "MT5 Strategy Tester - Timezone Fix Test"
echo "=========================================="
echo "Period: 2026-01-28 to 2026-01-30 (3 days including target divergence date)"
echo "Symbol: US100.cash"
echo "Model: Every tick"
echo "Configuration: FTMO profile with CORRECTED UTC offset (-5/-4 for EST/EDT)"
echo ""
echo "Key Fix: Changed InpBrokerUTCOffset from 2 to -5 (EST), InpSummerUTCOffset to -4 (EDT)"
echo ""
echo "Expected Results:"
echo "  - 14:40 EST (19:40 UTC) should now be INSIDE session (13-21 UTC)"
echo "  - Should see 6 trades on 2026-01-29 matching Python execution times"
echo "=========================================="
echo ""

# Run tester (set very specific params for this test)
echo "Starting tester..."
wine "$MT5_BIN" /skipupdate /portable /config:"$TESTER_DIR/tester.ini" 2>&1 | grep -E "Strategy Tester|Pass:|Test completed" &

# Give it time to start
sleep 3

# Wait for tester to complete (check if new log appears)
echo "Waiting for test results..."
sleep 60

# Decode and analyze results
if [ -f "$AGENT_LOGS/20260515.log" ]; then
   echo ""
   echo "Extracting session debug for 2026-01-29..."
   iconv -f UTF-16LE -t UTF-8 "$AGENT_LOGS/20260515.log" 2>/dev/null | grep -E "2026.01.29.*(14:40|15:10|15:35|16:40|17:00|17:20)" | grep "SessionDebug" | head -10
   
   echo ""
   echo "Session Summary (14:40-17:20):"
   iconv -f UTF-16LE -t UTF-8 "$AGENT_LOGS/20260515.log" 2>/dev/null | grep -E "2026.01.29.*(14:40|14:45|15:10|15:15|15:35|15:40|16:40|16:45|17:00|17:05|17:20|17:25)" | grep "EntryScanSummary" | head -10
   
   echo ""
   echo "Tolerance Rejections (sample):"
   iconv -f UTF-16LE -t UTF-8 "$AGENT_LOGS/20260515.log" 2>/dev/null | grep "2026.01.29.*reason=tolerance" | wc -l
   echo "  ...tolerance rejections found (should be same as before - this is secondary issue)"
else
   echo "Log file not found at $AGENT_LOGS/20260515.log"
   echo "Check tester manually or run again."
fi

echo ""
echo "Done. Check SessionDebug output above - should show utcHour=19 (19:40 UTC) at 14:40 display time"
