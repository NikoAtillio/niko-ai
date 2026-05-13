#!/usr/bin/env python3
"""
Diagnostic tool to identify why MQL5 results differ from Python backtest.
Compare zone detection, entry triggers, and sizing logic.
"""

import pandas as pd
import numpy as np
from pathlib import Path

# Load Python backtest results
python_trades_file = Path('/tmp/phantom_backtest/phantom_p2_ftmo_trades_US100_P2_FTMOB.csv')
if python_trades_file.exists():
    python_trades = pd.read_csv(python_trades_file)
    python_trades['entry_ts'] = pd.to_datetime(python_trades['entry_ts'])
    python_trades['exit_ts'] = pd.to_datetime(python_trades['exit_ts'])
    python_trades = python_trades.sort_values('entry_ts')
else:
    python_trades = None
    print("❌ Python trades file not found")

# Load data
data_dir = Path('/Users/niko/Documents/projects/niko-ai/data/US100')
h4_file = data_dir / 'US100.cash_H4_2021.01.21-2026.03.31'
m5_file = data_dir / 'US100.cash_M5_2021.01.21-2026.03.31'

print("=" * 80)
print("DIAGNOSTIC REPORT: MQL5 vs Python Discrepancy")
print("=" * 80)
print(f"\nPython backtest period: 2025-12-05 to 2026-03-25")
print(f"MQL5 reported period: 2025-12-22 to 2026-01-15")
print(f"\n⚠️  NOTE: Different date ranges being tested!")

if python_trades is not None:
    print(f"\n{'='*80}")
    print(f"PYTHON BACKTEST RESULTS")
    print(f"{'='*80}")
    print(f"Total trades:         {len(python_trades)}")
    print(f"Win rate:             {(python_trades['win'].sum() / len(python_trades) * 100):.1f}%")
    print(f"Avg profit/trade:     ${python_trades['pnl'].mean():.2f}")
    print(f"Total PnL:            ${python_trades['pnl'].sum():.2f}")
    print(f"Max consecutive loss:  (calculating...)")
    
    # Calculate max consecutive losses
    losses = python_trades[~python_trades['win']]
    if len(losses) > 0:
        max_consec_loss = 0
        current_loss_count = 0
        for win in python_trades['win']:
            if not win:
                current_loss_count += 1
                max_consec_loss = max(max_consec_loss, current_loss_count)
            else:
                current_loss_count = 0
        print(f"Max consecutive loss:  {max_consec_loss} trades")
    
    # Analyze by month
    python_trades['month'] = python_trades['entry_ts'].dt.to_period('M')
    print(f"\nMonthly breakdown:")
    for month, group in python_trades.groupby('month'):
        pnl = group['pnl'].sum()
        wins = group['win'].sum()
        print(f"  {month}: {len(group):3d} trades, {wins:3d} wins ({wins/len(group)*100:5.1f}%), PnL: ${pnl:8.2f}")

print(f"\n{'='*80}")
print(f"KEY DIAGNOSTIC QUESTIONS")
print(f"{'='*80}")

questions = [
    ("Zone Detection", "Are H4 pivot zones being detected at the same prices/times?"),
    ("Entry Timing", "Is MQL5 entering on time, or delayed/skipped?"),
    ("Entry Direction", "Is MQL5 taking shorts when Python takes longs (or vice versa)?"),
    ("Position Sizing", "Is MQL5 sizing drastically smaller/larger than Python?"),
    ("Stop Loss", "Are stops being triggered immediately or at reasonable prices?"),
    ("Exit Management", "Are positions exiting at TP or taking max loss?"),
    ("Session Filtering", "Is session gate blocking too many/all entries?"),
    ("FTMO Guards", "Are FTMO loss limits being hit early?"),
    ("ATR Calculation", "Is H4 ATR calculation the same in both systems?"),
    ("Data Synchronization", "Are both systems using same historical data source?"),
]

print("\nInvestigation Steps:")
for i, (category, question) in enumerate(questions, 1):
    print(f"\n{i:2d}. {category:20s}: {question}")

print(f"\n{'='*80}")
print(f"RECOMMENDATIONS")
print(f"{'='*80}")

recommendations = [
    "1. Run MQL5 with InpEnableDebugPrint=true to capture zone detection and entry logs",
    "2. Export MQL5 trades (use MT5 Navigator → History → export as CSV)",
    "3. Compare first 10 trades: entry time, direction, size, stop distance",
    "4. Check if the 2 systems are analyzing the same date range",
    "5. Verify H4 ATR values at entry points match between systems",
    "6. Check if session filtering (13:00-21:00 UTC) is working in MQL5",
    "7. Verify FTMO loss limits didn't trigger early (check logs for 'FTMO block')",
    "8. Manually check if Python zones exist in data for dates when MQL5 didn't trade",
]

for rec in recommendations:
    print(rec)

print(f"\n{'='*80}")
print("NEXT STEP: Enable debug output in MQL5 and re-run a shorter backtest")
print("Then compare the debug logs with Python backtest trades CSV")
print(f"{'='*80}\n")
