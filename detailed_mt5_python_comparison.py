#!/usr/bin/env python3
"""
Detailed comparison of MT5 vs Python trading rule performance
"""
import csv
from datetime import datetime
from collections import defaultdict

def load_trades(filepath, delimiter=','):
    """Load trades from CSV file"""
    trades = []
    try:
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                trades.append(row)
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}")
        return []
    return trades

# Load MT5 trades
mt5_file = "/Users/niko/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/phantom_mql5_trade_log.csv"
mt5_trades = load_trades(mt5_file, delimiter=';')

# Load Python trades
python_file = "backtest_artifacts/high-vs-high2-20260429_154936/high/phantom_p2_trades_US100_P2B.csv"
python_trades = load_trades(python_file, delimiter=',')

# Test window
test_start = datetime(2025, 12, 1, 0, 0, 0)
test_end = datetime(2026, 3, 31, 23, 59, 59)

# Filter MT5 trades in test window
mt5_window = []
for trade in mt5_trades:
    try:
        entry_time = datetime.strptime(trade['entry_time_utc'], '%Y.%m.%d %H:%M:%S')
        if test_start <= entry_time <= test_end:
            mt5_window.append(trade)
    except:
        pass

# Filter Python trades in test window (check various date column formats)
python_window = []
date_col = None
for trade in python_trades:
    # Find the entry date column
    if not date_col:
        for key in trade.keys():
            if 'entry' in key.lower() and any(c.isdigit() for c in trade[key]):
                date_col = key
                break
    
    if date_col:
        try:
            # Try different date formats
            try:
                entry_time = datetime.strptime(trade[date_col], '%Y-%m-%d %H:%M:%S')
            except:
                entry_time = datetime.strptime(trade[date_col], '%Y-%m-%d')
            
            if test_start <= entry_time <= test_end:
                python_window.append(trade)
        except:
            pass

print("=" * 80)
print("COMPREHENSIVE MT5 vs PYTHON TRADING RULE ANALYSIS")
print("=" * 80)
print(f"\nTest Window: {test_start.date()} to {test_end.date()}")
print(f"Python Date Column: {date_col}")

# ========== TRADE COUNT ANALYSIS ==========
print("\n" + "=" * 80)
print("1. TRADE ENTRY ANALYSIS")
print("=" * 80)

# Count by direction
mt5_long = sum(1 for t in mt5_window if t.get('direction', '').lower() == 'long')
mt5_short = sum(1 for t in mt5_window if t.get('direction', '').lower() == 'short')

# Find Python direction column
py_dir_col = next((k for k in python_trades[0].keys() if 'direction' in k.lower() or 'side' in k.lower() or 'type' in k.lower()), None)
python_long = sum(1 for t in python_window if py_dir_col and (t.get(py_dir_col, '').lower() in ['long', 'buy', '1']))
python_short = sum(1 for t in python_window if py_dir_col and (t.get(py_dir_col, '').lower() in ['short', 'sell', '-1', '0']))

print(f"\nMT5 Trades (in test window):        {len(mt5_window)} total")
print(f"  - LONG trades:                  {mt5_long}")
print(f"  - SHORT trades:                 {mt5_short}")
print(f"\nPython Trades (in test window):     {len(python_window)} total")
print(f"  - LONG trades:                  {python_long}")
print(f"  - SHORT trades:                 {python_short}")
print(f"\nDifference:                         {len(python_window) - len(mt5_window)} fewer trades in MT5")
print(f"  - Missing LONG trades:          ~{max(0, python_long - mt5_long)}")
print(f"  - Missing SHORT trades:         ~{max(0, python_short - mt5_short)}")

# ========== PROFITABILITY ANALYSIS ==========
print("\n" + "=" * 80)
print("2. PROFITABILITY ANALYSIS")
print("=" * 80)

mt5_total_pnl = sum(float(t.get('net_profit', 0)) for t in mt5_window)
mt5_winning = sum(1 for t in mt5_window if float(t.get('net_profit', 0)) > 0)
mt5_losing = sum(1 for t in mt5_window if float(t.get('net_profit', 0)) < 0)
mt5_breakeven = len(mt5_window) - mt5_winning - mt5_losing

# Find Python PnL column
py_pnl_col = next((k for k in python_trades[0].keys() if 'profit' in k.lower() or 'pnl' in k.lower() or 'gain' in k.lower()), None)
python_total_pnl = sum(float(t.get(py_pnl_col, 0)) for t in python_window if py_pnl_col)
python_winning = sum(1 for t in python_window if py_pnl_col and float(t.get(py_pnl_col, 0)) > 0)
python_losing = sum(1 for t in python_window if py_pnl_col and float(t.get(py_pnl_col, 0)) < 0)
python_breakeven = len(python_window) - python_winning - python_losing

print(f"\nMT5 Performance:")
print(f"  Total PnL:                      ${mt5_total_pnl:,.2f}")
print(f"  Winning trades:                 {mt5_winning} ({100*mt5_winning/len(mt5_window):.1f}%)")
print(f"  Losing trades:                  {mt5_losing} ({100*mt5_losing/len(mt5_window):.1f}%)")
print(f"  Break-even trades:              {mt5_breakeven}")
avg_win_mt5 = sum(float(t['net_profit']) for t in mt5_window if float(t['net_profit']) > 0) / mt5_winning if mt5_winning > 0 else 0
avg_loss_mt5 = sum(float(t['net_profit']) for t in mt5_window if float(t['net_profit']) < 0) / mt5_losing if mt5_losing > 0 else 0
print(f"  Avg Winning Trade:              ${avg_win_mt5:,.2f}")
print(f"  Avg Losing Trade:               ${avg_loss_mt5:,.2f}")

print(f"\nPython Performance:")
print(f"  Total PnL:                      ${python_total_pnl:,.2f}")
print(f"  Winning trades:                 {python_winning} ({100*python_winning/len(python_window):.1f}%)")
print(f"  Losing trades:                  {python_losing} ({100*python_losing/len(python_window):.1f}%)")
print(f"  Break-even trades:              {python_breakeven}")
if py_pnl_col:
    avg_win_py = sum(float(t[py_pnl_col]) for t in python_window if float(t[py_pnl_col]) > 0) / python_winning if python_winning > 0 else 0
    avg_loss_py = sum(float(t[py_pnl_col]) for t in python_window if float(t[py_pnl_col]) < 0) / python_losing if python_losing > 0 else 0
    print(f"  Avg Winning Trade:              ${avg_win_py:,.2f}")
    print(f"  Avg Losing Trade:               ${avg_loss_py:,.2f}")

# ========== EXIT REASON ANALYSIS ==========
print("\n" + "=" * 80)
print("3. EXIT REASON ANALYSIS (Which Rules Are Triggered?)")
print("=" * 80)

mt5_exits = defaultdict(int)
for t in mt5_window:
    exit_reason = t.get('exit_reason', 'unknown').lower()
    mt5_exits[exit_reason] += 1

print(f"\nMT5 Exit Reasons:")
for reason, count in sorted(mt5_exits.items(), key=lambda x: -x[1]):
    print(f"  {reason:20} {count:4} trades ({100*count/len(mt5_window):5.1f}%)")

# Check entry_comment to identify which rule was active
mt5_rules = defaultdict(int)
for t in mt5_window:
    comment = t.get('entry_comment', '')
    # Extract rule identifier (e.g., "P2_B|LONG|S=6|...")
    if 'P2_B' in comment:
        mt5_rules['P2_B (Zone Entry)'] += 1
    elif 'P1' in comment:
        mt5_rules['P1'] += 1
    else:
        mt5_rules['Other/Unknown'] += 1

print(f"\nMT5 Entry Rules/Contexts:")
for rule, count in sorted(mt5_rules.items(), key=lambda x: -x[1]):
    print(f"  {rule:30} {count:4} trades ({100*count/len(mt5_window):5.1f}%)")

# ========== SCORE DISTRIBUTION ANALYSIS ==========
print("\n" + "=" * 80)
print("4. TRADE QUALITY METRICS")
print("=" * 80)

mt5_avg_score = sum(float(t.get('score', 0)) for t in mt5_window) / len(mt5_window) if mt5_window else 0
mt5_avg_confidence = sum(float(t.get('confidence_mult', 1)) for t in mt5_window) / len(mt5_window) if mt5_window else 0

print(f"\nMT5 Average Metrics:")
print(f"  Average Score:                  {mt5_avg_score:.2f}")
print(f"  Average Confidence Multiplier:  {mt5_avg_confidence:.2f}x")

# Check regime distribution
mt5_regimes = defaultdict(int)
for t in mt5_window:
    regime = t.get('regime', 'unknown').lower()
    mt5_regimes[regime] += 1

print(f"\nMT5 Market Regimes:")
for regime, count in sorted(mt5_regimes.items(), key=lambda x: -x[1]):
    print(f"  {regime:20} {count:4} trades ({100*count/len(mt5_window):5.1f}%)")

print("\n" + "=" * 80)
print("DIAGNOSIS SUMMARY")
print("=" * 80)
print(f"""
The MT5 EA is producing {len(python_window) - len(mt5_window)} FEWER trades than Python ({len(python_window)} vs {len(mt5_window)}).

Key Findings:
1. Entry Problem: MT5 is NOT entering on {len(python_window) - len(mt5_window)} trades that Python enters
   - Possible causes:
     a) Zone detection not matching (H4/M5 zone timing)
     b) Entry score/confidence thresholds too high
     c) Position sizing logic rejecting trades
     d) Regime filter (bull/bear) too restrictive

2. Exit Differences: MT5's primary exit is "{max(mt5_exits, key=mt5_exits.get)}" ({mt5_exits[max(mt5_exits, key=mt5_exits.get)]}/{len(mt5_window)} trades)

3. Rule Activity: MT5 is using:
""")
for rule, count in sorted(mt5_rules.items(), key=lambda x: -x[1])[:3]:
    print(f"   - {rule}: {count} trades")

print(f"""
4. Profitability Gap: 
   - Python: ${python_total_pnl:,.2f} ({python_winning} wins, {python_losing} losses)
   - MT5:    ${mt5_total_pnl:,.2f} ({mt5_winning} wins, {mt5_losing} losses)
   - PnL Gap: ${mt5_total_pnl - python_total_pnl:,.2f} (MT5 underperformance)

NEXT STEPS:
1. Enable detailed debug logging on entry filtering (score, confidence, regime checks)
2. Verify zone detection H4 vs M5 timing alignment
3. Check if entry_score logic is rejecting valid zone entries
4. Compare trade-by-trade: Which {len(python_window) - len(mt5_window)} trades is MT5 missing?
""")

print("=" * 80)
