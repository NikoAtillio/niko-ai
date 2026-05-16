#!/usr/bin/env python3
import csv
from datetime import datetime

# Read MT5 trades
mt5_trades = []
mt5_file = "/Users/niko/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/phantom_mql5_trade_log.csv"

with open(mt5_file, 'r') as f:
    reader = csv.DictReader(f, delimiter=';')
    for row in reader:
        mt5_trades.append(row)

# Test window: Dec 1, 2025 00:00 to Mar 31, 2026 23:59
test_start = datetime(2025, 12, 1, 0, 0, 0)
test_end = datetime(2026, 3, 31, 23, 59, 59)

# Filter trades in test window (by entry time)
in_window = []
for trade in mt5_trades:
    entry_time = datetime.strptime(trade['entry_time_utc'], '%Y.%m.%d %H:%M:%S')
    if test_start <= entry_time <= test_end:
        in_window.append(trade)

print("=" * 60)
print("MT5 vs Python Trade Analysis")
print("=" * 60)
print("\nMT5 Trade Summary:")
print("  Total MT5 trades:", len(mt5_trades))
print("  MT5 trades in test window (Dec 1, 2025 - Mar 31, 2026):", len(in_window))

if mt5_trades:
    print("  First trade in MT5:", mt5_trades[0]['entry_time_utc'])
    print("  Last trade in MT5:", mt5_trades[-1]['entry_time_utc'])

pnl_in_window = sum(float(t['net_profit']) for t in in_window)
print("  MT5 PnL in test window:", round(pnl_in_window, 2), "USD")

# Read Python trades
python_file = "backtest_artifacts/high-vs-high2-20260429_154936/high/phantom_p2_trades_US100_P2B.csv"
python_trades = []
try:
    with open(python_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            python_trades.append(row)
    print("\nPython Trade Summary:")
    print("  Python total trades:", len(python_trades))
    
    # Calculate Python PnL in test window (trades with entry date in window)
    python_in_window = []
    for trade in python_trades:
        # Parse date - format appears to be varied, let me check
        entry_col = next((k for k in trade.keys() if 'entry' in k.lower()), None)
        if entry_col:
            try:
                entry_time = datetime.strptime(trade[entry_col], '%Y-%m-%d %H:%M:%S')
                if test_start <= entry_time <= test_end:
                    python_in_window.append(trade)
            except:
                pass
    
    print("  Python trades in test window:", len(python_in_window))
    
except FileNotFoundError:
    print("\nPython trade file not found at:", python_file)

print("\n" + "=" * 60)
print("Summary:")
print("  MT5 in window: {} trades, PnL: ${:.2f}".format(len(in_window), pnl_in_window))
print("  Python in window: {} trades".format(len(python_in_window) if 'python_in_window' in locals() else 'N/A'))
print("=" * 60)
