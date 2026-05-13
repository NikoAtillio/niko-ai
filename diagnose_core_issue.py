#!/usr/bin/env python3
"""
Core issue diagnosis: Check for specific MQL5 bugs by comparing expected behavior
"""

import pandas as pd
import numpy as np

trades = pd.read_csv('/tmp/phantom_zones/phantom_p2_ftmo_trades_US100_P2_FTMOB.csv')
trades['entry_ts'] = pd.to_datetime(trades['entry_ts'])
trades['exit_ts'] = pd.to_datetime(trades['exit_ts'])

print("=" * 100)
print("CORE ISSUE DIAGNOSIS")
print("=" * 100)

# Issue 1: Check if MQL5 might be stopping out immediately
print("\n1. STOP LOSS ANALYSIS (R-value distribution)")
print("-" * 100)
print(f"Average R-value (stop distance as multiples):  {trades['r_value'].mean():.3f}")
print(f"Min R-value:  {trades['r_value'].min():.3f}")
print(f"Max R-value:  {trades['r_value'].max():.3f}")
print(f"Median R-value:  {trades['r_value'].median():.3f}")

print("\nR-value distribution:")
bins = [-np.inf, -2, -1, 0, 1, 2, np.inf]
labels = ['< -2R', '-2R to -1R', '-1R to 0', '0 to 1R', '1R to 2R', '> 2R']
dist = pd.cut(trades['r_value'], bins=bins, labels=labels).value_counts().sort_index()
for label, count in dist.items():
    pct = count / len(trades) * 100
    print(f"  {label:15s}: {count:3d} trades ({pct:5.1f}%)")

# Issue 2: Check if entries are too aggressive (high quantity)
print("\n2. POSITION SIZE ANALYSIS")
print("-" * 100)
print(f"Average trade quantity:   {trades['qty'].mean():.3f}")
print(f"Min quantity:             {trades['qty'].min():.3f}")
print(f"Max quantity:             {trades['qty'].max():.3f}")
print(f"Median quantity:          {trades['qty'].median():.3f}")
print(f"Std dev:                  {trades['qty'].std():.3f}")

# Check if size is correlated with win rate
trades['size_category'] = pd.qcut(trades['qty'], q=3, labels=['Small', 'Medium', 'Large'], duplicates='drop')
print("\nWin rate by position size:")
for cat in ['Small', 'Medium', 'Large']:
    subset = trades[trades['size_category'] == cat]
    win_pct = subset['win'].mean() * 100
    avg_pnl = subset['pnl'].mean()
    print(f"  {cat:8s}: {win_pct:5.1f}% WR, avg PnL ${avg_pnl:8.2f}, {len(subset)} trades")

# Issue 3: Check exit behavior
print("\n3. EXIT BEHAVIOR ANALYSIS")
print("-" * 100)
exit_reasons = trades['exit_reason'].value_counts()
for reason, count in exit_reasons.items():
    pct = count / len(trades) * 100
    subset = trades[trades['exit_reason'] == reason]
    win_pct = subset['win'].mean() * 100
    print(f"  {reason:12s}: {count:3d} trades ({pct:5.1f}%) | WR: {win_pct:5.1f}%")

# Issue 4: Check if there's a confidence multiplier issue
print("\n4. CONFIDENCE MULTIPLIER ANALYSIS")
print("-" * 100)
print(f"Average confidence_mult:  {trades['confidence_mult'].mean():.3f}")
print(f"Min:                      {trades['confidence_mult'].min():.3f}")
print(f"Max:                      {trades['confidence_mult'].max():.3f}")
print("\nTrade count by confidence:")
for mult in sorted(trades['confidence_mult'].unique()):
    subset = trades[trades['confidence_mult'] == mult]
    win_pct = subset['win'].mean() * 100
    count = len(subset)
    print(f"  {mult}x: {count:3d} trades, {win_pct:5.1f}% WR")

# Issue 5: Time-based analysis
print("\n5. TIME-BASED ANALYSIS (Entry patterns)")
print("-" * 100)
trades['entry_hour'] = trades['entry_ts'].dt.hour
trades['entry_day'] = trades['entry_ts'].dt.dayofweek
hourly = trades.groupby('entry_hour')['win'].agg(['sum', 'count'])
hourly['wr'] = hourly['sum'] / hourly['count'] * 100
hourly = hourly[hourly['count'] > 0]
print("Win rate by entry hour (UTC):")
for hour in range(13, 22):  # Session is 13-21 UTC
    if hour in hourly.index:
        row = hourly.loc[hour]
        print(f"  {hour:02d}:00 UTC: {row['wr']:5.1f}% WR ({int(row['count'])} trades)")

print("\n" + "=" * 100)
print("HYPOTHESIS: Most likely causes of 86% loss in MQL5:")
print("=" * 100)
print("""
A. ENTRIES NOT HAPPENING AT ALL
   - Zones detected but entry filters block all trades
   - Session/confirmation/score filters working too hard
   - ACTION: Enable full debug logging and check for 'SkipZone' patterns
   
B. ENTRIES HAPPENING BUT IMMEDIATE STOPS
   - Stop loss is too tight (less than 1.5x H4 ATR being used)
   - Entry prices are wrong, stops are placed backwards
   - ACTION: Check stop distance formula and verify ATR calculation
   
C. OVERSIZED POSITIONS
   - Sizing formula is calculating wrong volume (off by 10x?)
   - Margin calls liquidating all positions
   - ACTION: Log SizingDebug and verify volume makes sense
   
D. WRONG ENTRY/EXIT PRICES
   - Using wrong price source (bid vs ask, wrong candle)
   - Executing on wrong bar (delayed entry)
   - ACTION: Compare first MQL5 trade with Python trade at same time
   
E. TIMEZONE/DATA MISALIGNMENT
   - MQL5 and Python using different UTC offsets
   - MQL5 analyzing different bars than Python
   - ACTION: Verify both systems show same bar times/prices for first zone
""")

print("\n" + "=" * 100)
print("NEXT IMMEDIATE STEP:")
print("=" * 100)
print("""
1. Run a SHORT backtest in MQL5 (just 1 week: Dec 5-12, 2025) with DEBUG ENABLED
2. Export the MT5 backtest report and look for:
   - How many trades were made in that week? (Python had 3-4 trades per week)
   - What were entry times, sizes, exits?
   - Any pattern in skip reasons?
3. Compare side-by-side with Python trades CSV for the same week
4. This will immediately reveal if issue is "no entries" vs "wrong entries"
""")
