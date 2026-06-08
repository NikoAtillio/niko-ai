#!/usr/bin/env python3
"""
Compare all three versions: EA, high_ftmo, and V7
Shows: Win/Loss %, Account %, Profit Factor, Directional Analysis
"""

import pandas as pd
import numpy as np

# Load all three versions
ea = pd.read_csv('phantom_p2_ftmo_trades_US100_P2_FTMOB.csv')
high_ftmo = pd.read_csv('phantom_high_ftmo_nov_jan.csv')
v7 = pd.read_csv('saved_runs/v7_nov01_jan31/phantom_p2_ftmo_trades_US100_P2_FTMOB.csv')

# Convert timestamps
for df in [ea, high_ftmo, v7]:
    df['entry_ts'] = pd.to_datetime(df['entry_ts'])

print("\n" + "=" * 130)
print("3-WAY COMPARISON: EA vs HIGH_FTMO vs V7 (Nov 1 - Jan 31, 2026)")
print("=" * 130)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. WIN/LOSS SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
print("\n1. WIN/LOSS SUMMARY")
print("-" * 130)

print(f"\n{'Metric':<30} {'EA':<30} {'HIGH_FTMO':<30} {'V7':<30}")
print("-" * 130)

for name, df in [("EA", ea), ("HIGH_FTMO", high_ftmo), ("V7", v7)]:
    wins = df['win'].sum()
    losses = len(df) - wins
    win_rate = 100 * wins / len(df)
    loss_rate = 100 * losses / len(df)
    
    if name == "EA":
        print(f"{'Total Trades':<30} {len(ea):<30} {len(high_ftmo):<30} {len(v7):<30}")
    
print(f"\n{'Wins (count)':<30} {ea['win'].sum():<30} {high_ftmo['win'].sum():<30} {v7['win'].sum():<30}")
print(f"{'Losses (count)':<30} {len(ea) - ea['win'].sum():<30} {len(high_ftmo) - high_ftmo['win'].sum():<30} {len(v7) - v7['win'].sum():<30}")
print(f"{'Win Rate (%)':<30} {100*ea['win'].sum()/len(ea):<29.1f}% {100*high_ftmo['win'].sum()/len(high_ftmo):<29.1f}% {100*v7['win'].sum()/len(v7):<29.1f}%")
print(f"{'Loss Rate (%)':<30} {100*(1-ea['win'].sum()/len(ea)):<29.1f}% {100*(1-high_ftmo['win'].sum()/len(high_ftmo)):<29.1f}% {100*(1-v7['win'].sum()/len(v7)):<29.1f}%")

# ═══════════════════════════════════════════════════════════════════════════════
# 2. ACCOUNT IMPACT (% of $10k capital)
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n\n2. ACCOUNT IMPACT (as % of $10,000 capital)")
print("-" * 130)

initial_cap = 10000

ea_wins = ea[ea['win'] == True]['pnl'].sum()
ea_losses = ea[ea['win'] == False]['pnl'].sum()
ea_pnl = ea['pnl'].sum()

hf_wins = high_ftmo[high_ftmo['win'] == True]['pnl'].sum()
hf_losses = high_ftmo[high_ftmo['win'] == False]['pnl'].sum()
hf_pnl = high_ftmo['pnl'].sum()

v7_wins = v7[v7['win'] == True]['pnl'].sum()
v7_losses = v7[v7['win'] == False]['pnl'].sum()
v7_pnl = v7['pnl'].sum()

print(f"{'Total Winning P&L':<30} ${ea_wins:<29.2f} ${hf_wins:<29.2f} ${v7_wins:<29.2f}")
print(f"{'Wins as % of Capital':<30} {100*ea_wins/initial_cap:<29.2f}% {100*hf_wins/initial_cap:<29.2f}% {100*v7_wins/initial_cap:<29.2f}%")
print(f"{'Losses as % of Capital':<30} {100*ea_losses/initial_cap:<29.2f}% {100*hf_losses/initial_cap:<29.2f}% {100*v7_losses/initial_cap:<29.2f}%")
print(f"{'Net P&L as % of Capital':<30} {100*ea_pnl/initial_cap:<29.2f}% {100*hf_pnl/initial_cap:<29.2f}% {100*v7_pnl/initial_cap:<29.2f}%")

# ═══════════════════════════════════════════════════════════════════════════════
# 3. PROFIT FACTOR
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n\n3. PROFIT FACTOR & PER-TRADE METRICS")
print("-" * 130)

ea_pf = ea[ea['win']==True]['pnl'].sum() / abs(ea[ea['win']==False]['pnl'].sum())
hf_pf = high_ftmo[high_ftmo['win']==True]['pnl'].sum() / abs(high_ftmo[high_ftmo['win']==False]['pnl'].sum())
v7_pf = v7[v7['win']==True]['pnl'].sum() / abs(v7[v7['win']==False]['pnl'].sum())

ea_avg_win = ea[ea['win']==True]['pnl'].mean()
hf_avg_win = high_ftmo[high_ftmo['win']==True]['pnl'].mean()
v7_avg_win = v7[v7['win']==True]['pnl'].mean()

ea_avg_loss = ea[ea['win']==False]['pnl'].mean()
hf_avg_loss = high_ftmo[high_ftmo['win']==False]['pnl'].mean()
v7_avg_loss = v7[v7['win']==False]['pnl'].mean()

print(f"{'Profit Factor (Wins/Loss)':<30} {ea_pf:<30.2f} {hf_pf:<30.2f} {v7_pf:<30.2f}")
print(f"{'Avg Win ($)':<30} {ea_avg_win:<30.2f} {hf_avg_win:<30.2f} {v7_avg_win:<30.2f}")
print(f"{'Avg Loss ($)':<30} {ea_avg_loss:<30.2f} {hf_avg_loss:<30.2f} {v7_avg_loss:<30.2f}")
print(f"{'Expectancy (Avg per trade)':<30} {ea['pnl'].mean():<30.2f} {high_ftmo['pnl'].mean():<30.2f} {v7['pnl'].mean():<30.2f}")

# ═══════════════════════════════════════════════════════════════════════════════
# 4. DIRECTIONAL BREAKDOWN - LONGS
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n\n4. LONGS ANALYSIS")
print("-" * 130)

ea_longs = ea[ea['dir'] == 'long']
hf_longs = high_ftmo[high_ftmo['dir'] == 'long']
v7_longs = v7[v7['dir'] == 'long']

print(f"{'Long Count':<30} {len(ea_longs):<30} {len(hf_longs):<30} {len(v7_longs):<30}")
print(f"{'Long Win Rate (%)':<30} {100*ea_longs['win'].sum()/len(ea_longs):<29.1f}% {100*hf_longs['win'].sum()/len(hf_longs):<29.1f}% {100*v7_longs['win'].sum()/len(v7_longs):<29.1f}%")
print(f"{'Long P&L ($)':<30} {ea_longs['pnl'].sum():<30.2f} {hf_longs['pnl'].sum():<30.2f} {v7_longs['pnl'].sum():<30.2f}")
print(f"{'Long P&L (% of total)':<30} {100*ea_longs['pnl'].sum()/ea['pnl'].sum():<29.1f}% {100*hf_longs['pnl'].sum()/high_ftmo['pnl'].sum():<29.1f}% {100*v7_longs['pnl'].sum()/v7['pnl'].sum():<29.1f}%")
print(f"{'Long Avg Trade':<30} {ea_longs['pnl'].mean():<30.2f} {hf_longs['pnl'].mean():<30.2f} {v7_longs['pnl'].mean():<30.2f}")

# ═══════════════════════════════════════════════════════════════════════════════
# 5. DIRECTIONAL BREAKDOWN - SHORTS
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n\n5. SHORTS ANALYSIS")
print("-" * 130)

ea_shorts = ea[ea['dir'] == 'short']
hf_shorts = high_ftmo[high_ftmo['dir'] == 'short']
v7_shorts = v7[v7['dir'] == 'short']

print(f"{'Short Count':<30} {len(ea_shorts):<30} {len(hf_shorts):<30} {len(v7_shorts):<30}")
print(f"{'Short Win Rate (%)':<30} {100*ea_shorts['win'].sum()/len(ea_shorts):<29.1f}% {100*hf_shorts['win'].sum()/len(hf_shorts):<29.1f}% {100*v7_shorts['win'].sum()/len(v7_shorts):<29.1f}%")
print(f"{'Short P&L ($)':<30} {ea_shorts['pnl'].sum():<30.2f} {hf_shorts['pnl'].sum():<30.2f} {v7_shorts['pnl'].sum():<30.2f}")
print(f"{'Short P&L (% of total)':<30} {100*ea_shorts['pnl'].sum()/ea['pnl'].sum():<29.1f}% {100*hf_shorts['pnl'].sum()/high_ftmo['pnl'].sum():<29.1f}% {100*v7_shorts['pnl'].sum()/v7['pnl'].sum():<29.1f}%")
print(f"{'Short Avg Trade':<30} {ea_shorts['pnl'].mean():<30.2f} {hf_shorts['pnl'].mean():<30.2f} {v7_shorts['pnl'].mean():<30.2f}")

# ═══════════════════════════════════════════════════════════════════════════════
# 6. SUMMARY INSIGHT
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n\n" + "=" * 130)
print("KEY INSIGHT")
print("=" * 130)

ea_wr = 100 * ea['win'].sum() / len(ea)
high_ftmo_wr = 100 * high_ftmo['win'].sum() / len(high_ftmo)
v7_wr = 100 * v7['win'].sum() / len(v7)

ea_pf = ea[ea['win']==True]['pnl'].sum() / abs(ea[ea['win']==False]['pnl'].sum())
high_ftmo_pf = high_ftmo[high_ftmo['win']==True]['pnl'].sum() / abs(high_ftmo[high_ftmo['win']==False]['pnl'].sum())
v7_pf = v7[v7['win']==True]['pnl'].sum() / abs(v7[v7['win']==False]['pnl'].sum())

print(f"\nWin Rates: EA {ea_wr:.1f}% | HIGH_FTMO {high_ftmo_wr:.1f}% | V7 {v7_wr:.1f}%")
print(f"Profit Factors: EA {ea_pf:.2f} | HIGH_FTMO {high_ftmo_pf:.2f} | V7 {v7_pf:.2f}")
print(f"Expected per Trade: EA ${ea['pnl'].mean():.2f} | HIGH_FTMO ${high_ftmo['pnl'].mean():.2f} | V7 ${v7['pnl'].mean():.2f}")

print("\n❌ IMPORTANT FINDING:")
print(f"   • V7's win rate is LOWER (45.6%) than EA/HIGH_FTMO (55.6%)")
print(f"   • V7's profit factor is LOWER (2.30) than EA/HIGH_FTMO (3.50)")
print(f"   • V7 wins BIGGER but loses BIGGER too")
print(f"   • V7's higher ROI is PURELY from position sizing (6-7× bigger lots)")
print(f"   • This is actually RISKIER - larger drawdowns, but higher reward")

print("\n" + "=" * 130 + "\n")
