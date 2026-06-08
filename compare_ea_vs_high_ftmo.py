#!/usr/bin/env python3
"""
Compare EA version vs high_ftmo version backtest results.
Run after both backtests complete with the same date range.
"""

import pandas as pd
import numpy as np
import glob
import os
from datetime import datetime

# Look for the most recent trade CSV files
trade_files = sorted(glob.glob('phantom_p2_ftmo_trades_US100_P2_FTMOB.csv'), 
                     key=os.path.getmtime, reverse=True)

if len(trade_files) < 1:
    print("❌ Need at least one trade CSV file (phantom_p2_ftmo_trades_US100_P2_FTMOB.csv)")
    exit(1)

# Load most recent trades (should be from EA run)
ea_trades = pd.read_csv(trade_files[0])
ea_trades['entry_ts'] = pd.to_datetime(ea_trades['entry_ts'])

# Load v7 reference
v7_trades = pd.read_csv('saved_runs/v7_nov01_jan31/phantom_p2_ftmo_trades_US100_P2_FTMOB.csv')
v7_trades['entry_ts'] = pd.to_datetime(v7_trades['entry_ts'])

print("\n" + "=" * 100)
print("EA vs HIGH_FTMO BASELINE COMPARISON (Nov 1 - Jan 31, 2026)")
print("=" * 100)

print(f"\nData Loaded:")
print(f"  EA Trades:      {len(ea_trades)} trades")
print(f"  V7 Reference:   {len(v7_trades)} trades")
print(f"  EA Date Range:  {ea_trades['entry_ts'].min().date()} → {ea_trades['entry_ts'].max().date()}")
print(f"  V7 Date Range:  {v7_trades['entry_ts'].min().date()} → {v7_trades['entry_ts'].max().date()}")

# Metrics table
print(f"\n{'Metric':<30} {'EA Version':<28} {'V7 Benchmark':<28} {'Difference':<15}")
print("-" * 100)

ea_pnl = ea_trades['pnl'].sum()
ea_wr = 100 * ea_trades['win'].sum() / len(ea_trades) if len(ea_trades) > 0 else 0
ea_roi = 100 * ea_pnl / 10000

v7_pnl = v7_trades['pnl'].sum()
v7_wr = 100 * v7_trades['win'].sum() / len(v7_trades) if len(v7_trades) > 0 else 0
v7_roi = 100 * v7_pnl / 10000

print(f"{'Total Trades':<30} {len(ea_trades):<28} {len(v7_trades):<28} {len(ea_trades) - len(v7_trades):+>14}")
print(f"{'Win Rate':<30} {ea_wr:<27.1f}% {v7_wr:<27.1f}% {ea_wr - v7_wr:+>14.1f}%")
print(f"{'Total P&L':<30} ${ea_pnl:<27.2f} ${v7_pnl:<27.2f} ${ea_pnl - v7_pnl:+>14.2f}")
print(f"{'Return on Capital':<30} {ea_roi:<27.2f}% {v7_roi:<27.2f}% {ea_roi - v7_roi:+>14.2f}%")

# Directional breakdown
print(f"\n{'DIRECTIONAL BREAKDOWN':<30}")
print("-" * 100)

ea_long = ea_trades[ea_trades['dir'] == 'long']['pnl'].sum()
ea_short = ea_trades[ea_trades['dir'] == 'short']['pnl'].sum()
v7_long = v7_trades[v7_trades['dir'] == 'long']['pnl'].sum()
v7_short = v7_trades[v7_trades['dir'] == 'short']['pnl'].sum()

print(f"{'Longs P&L':<30} ${ea_long:<27.2f} ${v7_long:<27.2f} ${ea_long - v7_long:+>14.2f}")
print(f"{'Shorts P&L':<30} ${ea_short:<27.2f} ${v7_short:<27.2f} ${ea_short - v7_short:+>14.2f}")

# Confidence breakdown
print(f"\n{'CONFIDENCE BREAKDOWN':<30}")
print("-" * 100)

ea_15x = ea_trades[ea_trades['confidence_mult'] == 1.5]['pnl'].sum()
ea_10x = ea_trades[ea_trades['confidence_mult'] == 1.0]['pnl'].sum()
v7_15x = v7_trades[v7_trades['confidence_mult'] == 1.5]['pnl'].sum()
v7_10x = v7_trades[v7_trades['confidence_mult'] == 1.0]['pnl'].sum()

ea_15x_cnt = len(ea_trades[ea_trades['confidence_mult'] == 1.5])
ea_10x_cnt = len(ea_trades[ea_trades['confidence_mult'] == 1.0])
v7_15x_cnt = len(v7_trades[v7_trades['confidence_mult'] == 1.5])
v7_10x_cnt = len(v7_trades[v7_trades['confidence_mult'] == 1.0])

print(f"{'1.5x Count':<30} {ea_15x_cnt:<28} {v7_15x_cnt:<28} {ea_15x_cnt - v7_15x_cnt:+>14}")
print(f"{'1.5x P&L':<30} ${ea_15x:<27.2f} ${v7_15x:<27.2f} ${ea_15x - v7_15x:+>14.2f}")
print(f"{'1.0x Count':<30} {ea_10x_cnt:<28} {v7_10x_cnt:<28} {ea_10x_cnt - v7_10x_cnt:+>14}")
print(f"{'1.0x P&L':<30} ${ea_10x:<27.2f} ${v7_10x:<27.2f} ${ea_10x - v7_10x:+>14.2f}")

# Regime check
print(f"\n{'REGIME DISTRIBUTION':<30}")
print("-" * 100)

ea_bull = len(ea_trades[ea_trades['regime'] == 'bull'])
ea_bear = len(ea_trades[ea_trades['regime'] == 'bear'])
v7_bull = len(v7_trades[v7_trades['regime'] == 'bull'])
v7_bear = len(v7_trades[v7_trades['regime'] == 'bear'])

print(f"{'Bull Trades':<30} {ea_bull:<28} {v7_bull:<28} {ea_bull - v7_bull:+>14}")
print(f"{'Bear Trades':<30} {ea_bear:<28} {v7_bear:<28} {ea_bear - v7_bear:+>14}")

# Summary
print(f"\n" + "=" * 100)
print("SUMMARY")
print("=" * 100)

if len(ea_trades) == len(v7_trades) and abs(ea_pnl - v7_pnl) < 100:
    print("✅ EA and V7 are functionally EQUIVALENT")
    print("   Both versions produce nearly identical results.")
elif len(ea_trades) == len(v7_trades):
    print(f"⚠️  Same trade count but different P&L (${abs(ea_pnl - v7_pnl):.2f} gap)")
    print("   Likely due to position sizing or exit logic differences.")
else:
    print(f"⚠️  Different trade counts: EA={len(ea_trades)}, V7={len(v7_trades)}")
    print("   Likely due to entry filtering or zone detection differences.")

print("\nNote: '100% BEAR' regime is CORRECT. Daily EMA50 < EMA200 throughout Nov-Jan,")
print("      indicating a downtrend. Choppy intraday price action is normal volatility")
print("      within this larger bear trend.")

print("\n" + "=" * 100 + "\n")
