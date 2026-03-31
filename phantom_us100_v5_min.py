#!/usr/bin/env python3
"""
PHANTOM — US100 Backtest (ORIGINAL)
====================================
4-Scenario S/R zone strategy on US100 M1/M5/H1/H4 data
£7,000 starting capital | May 2023 – Mar 2024

Scenarios:
  A — H1 zones, M5 entry, ATR×1.5 stop
  B — H4 zones, M5 entry, ATR×2.0 stop
  C — H1 zones, M1 entry (no HTF confirm), ATR×1.5 stop
  D — H1+H4 confluence zones, M1+M5 entry, ATR×2.0 stop, min_score=2

Signal detection (all scenarios):
  - Pin bar
  - Engulfing candle
  - Double bottom/top
  - Failed breakout
  Score = sum of signals (1–4)

Risk management:
  - Risk per trade = score-scaled (0.5%–2% of capital)
  - Stop = ATR-based beyond zone
  - Target = 2× stop distance
  - Break-even after 1R
  - Max 1 concurrent trade
  - Session: 08:00–17:00 EST (13:00–22:00 UTC)
"""

import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import warnings
warnings.filterwarnings('ignore')

# ── CONFIG ────────────────────────────────────────────────────────────────────
STARTING_CAPITAL = 7_000.0   # GBP

SCENARIOS = {
    'A': {'zone_tf':'h1', 'entry_tf':'m5', 'atr_mult':1.5, 'entry_rule':'ltf_only',  'min_score':1},
    'B': {'zone_tf':'h4', 'entry_tf':'m5', 'atr_mult':2.0, 'entry_rule':'ltf_only',  'min_score':1},
    'C': {'zone_tf':'h1', 'entry_tf':'m1', 'atr_mult':1.5, 'entry_rule':'ltf_only',  'min_score':0},
    'D': {'zone_tf':'h1', 'entry_tf':'m1', 'atr_mult':2.0, 'entry_rule':'confluence', 'min_score':2},
}

# ── DATA LOADING ──────────────────────────────────────────────────────────────
def load_mt4(path):
    df = pd.read_csv(path, sep='\t', header=0)
    df.columns = [c.strip('<>').lower() for c in df.columns]
    df['datetime'] = pd.to_datetime(df['date'] + ' ' + df['time'], format='%Y.%m.%d %H:%M:%S')
    return df.set_index('datetime').sort_index()[['open','high','low','close','tickvol']].rename(columns={'tickvol':'vol'})

base = Path('/Users/niko/Downloads')
m1 = load_mt4(base / 'US100.cash_M1_23-24')
m5 = load_mt4(base / 'US100.cash_M5_23-24')
h1 = load_mt4(base / 'US100.cash_H1_23-24')
h4 = load_mt4(base / 'US100.cash_H4_23-24')

def calc_atr(df, period=14):
    h,l,c = df['high'],df['low'],df['close']
    tr = pd.concat([h-l,(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1)
    return tr.ewm(span=period,adjust=False).mean()
for df in [m1,m5,h1,h4]: df['atr'] = calc_atr(df)

# ── ZONE BUILDING ─────────────────────────────────────────────────────────────
def build_rolling_zones(df, swing_n=5, zone_tol_pct=0.004, min_touches=2, lookback_bars=300):
    h_arr = df['high'].values; l_arr = df['low'].values; n = len(df)
    pivot_highs, pivot_lows = [], []
    for i in range(swing_n, n - swing_n):
        if h_arr[i] == max(h_arr[i-swing_n:i+swing_n+1]): pivot_highs.append((i, h_arr[i]))
        if l_arr[i] == min(l_arr[i-swing_n:i+swing_n+1]): pivot_lows.append((i, l_arr[i]))
    ph_arr = np.array(pivot_highs) if pivot_highs else np.empty((0,2))
    pl_arr = np.array(pivot_lows)  if pivot_lows  else np.empty((0,2))
    active_zones = {}
    for i in range(lookback_bars, n):
        zones_at_i = []; lb = max(0, i - lookback_bars)
        for arr, ztype in [(ph_arr,'resistance'),(pl_arr,'support')]:
            if not len(arr): continue
            mask = (arr[:,0] >= lb) & (arr[:,0] < i)
            recent = arr[mask]
            if not len(recent): continue
            prices = np.sort(recent[:,1])
            clusters, cur = [], [prices[0]]
            for p in prices[1:]:
                if abs(p - cur[-1]) / cur[-1] < zone_tol_pct: cur.append(p)
                else: clusters.append(cur); cur = [p]
            clusters.append(cur)
            for c in clusters:
                if len(c) >= min_touches: zones_at_i.append((np.mean(c), ztype))
        if zones_at_i: active_zones[i] = zones_at_i
    return active_zones

print("Building zones...")
zones_h1_r = build_rolling_zones(h1, swing_n=5, zone_tol_pct=0.004, min_touches=2, lookback_bars=300)
zones_h4_r = build_rolling_zones(h4, swing_n=5, zone_tol_pct=0.006, min_touches=2, lookback_bars=150)
print("Done.")

# ── SIGNAL DETECTION ─────────────────────────────────────────────────────────
def detect_signals(df, i, direction):
    if i < 5: return {'pin_bar':False,'engulfing':False,'double_bottom':False,'failed_breakout':False,'score':0}
    o,h,l,c = df['open'].iloc[i],df['high'].iloc[i],df['low'].iloc[i],df['close'].iloc[i]
    po,ph,pl,pc = df['open'].iloc[i-1],df['high'].iloc[i-1],df['low'].iloc[i-1],df['close'].iloc[i-1]
    body = abs(c-o); rng = h-l
    pin = False
    if rng > 0:
        if direction=='long': pin = ((min(o,c)-l)/rng >= 0.6) and (body/rng <= 0.3)
        else: pin = ((h-max(o,c))/rng >= 0.6) and (body/rng <= 0.3)
    prev_body = abs(pc-po)
    eng = False
    if prev_body > 0:
        if direction=='long': eng = (c>po) and (o<pc) and (c>ph) and (o<pl) and (pc<po)
        else: eng = (c<po) and (o>pc) and (c<pl) and (o>ph) and (pc>po)
    db = False
    if i >= 10:
        if direction=='long': db = np.sum(np.abs(df['low'].iloc[i-10:i].values - l)/(l+1e-9) < 0.003) >= 1
        else: db = np.sum(np.abs(df['high'].iloc[i-10:i].values - h)/(h+1e-9) < 0.003) >= 1
    fb = False
    if i >= 3:
        if direction=='long': rl = df['low'].iloc[i-3:i].min(); fb = (l < rl) and (c > rl)
        else: rh = df['high'].iloc[i-3:i].max(); fb = (h > rh) and (c < rh)
    score = sum([pin,eng,db,fb])
    return {'pin_bar':pin,'engulfing':eng,'double_bottom':db,'failed_breakout':fb,'score':score}

def in_session(dt):
    return 13 <= dt.hour < 22  # 08:00–17:00 EST

def price_at_zone(price, zone_price, zone_type, atr, tol_atr=0.5):
    tol = atr * tol_atr
    if zone_type == 'support':
        return abs(price - zone_price) <= tol and price >= zone_price - tol
    else:
        return abs(price - zone_price) <= tol and price <= zone_price + tol

def build_tf_lookup(m1_idx, htf_idx):
    return np.searchsorted(htf_idx.values.astype('int64'), m1_idx.values.astype('int64'), side='right') - 1

# ── BACKTEST ENGINE ───────────────────────────────────────────────────────────
def run_scenario(name, cfg):
    zone_tf    = cfg['zone_tf']
    entry_tf   = cfg['entry_tf']
    atr_mult   = cfg['atr_mult']
    entry_rule = cfg['entry_rule']
    min_score  = cfg['min_score']

    zone_df  = h1 if zone_tf == 'h1' else h4
    entry_df = m1 if entry_tf == 'm1' else m5
    zones_r  = zones_h1_r if zone_tf == 'h1' else zones_h4_r

    zone_idx_lookup  = build_tf_lookup(entry_df.index, zone_df.index)
    h1_idx_lookup    = build_tf_lookup(entry_df.index, h1.index)
    h4_idx_lookup    = build_tf_lookup(entry_df.index, h4.index)
    m1_idx_lookup    = build_tf_lookup(entry_df.index, m1.index) if entry_tf == 'm5' else None
    m5_idx_lookup    = build_tf_lookup(entry_df.index, m5.index) if entry_tf == 'm1' else None

    m1_open  = m1['open'].values
    m1_high  = m1['high'].values
    m1_low   = m1['low'].values
    m1_close = m1['close'].values
    m1_times = m1.index

    capital = STARTING_CAPITAL
    trades  = []
    diag    = []

    in_trade    = False
    trade_dir   = None
    trade_score = 0
    trade_entry_time = None
    trade_entry_bar  = 0
    be_triggered     = False
    atr_at_entry     = 0
    stop_price       = 0
    trail_stop       = 0
    entry_price_t    = 0
    target_price     = 0

    for i in range(10, len(entry_df) - 2):
        dt    = entry_df.index[i]
        price = entry_df['close'].iloc[i]
        atr_v = entry_df['atr'].iloc[i]

        if not in_session(dt): continue

        # ── MANAGE OPEN TRADE ────────────────────────────────────────────────
        if in_trade:
            # Map to M1 for precise exit
            m1_i = m1_idx_lookup[i] if entry_tf == 'm5' else i
            if m1_i >= len(m1): m1_i = len(m1) - 1

            hi = m1_high[m1_i]; lo = m1_low[m1_i]; cl = m1_close[m1_i]
            risk_usd = atr_at_entry * atr_mult

            if trade_dir == 'long':
                if not be_triggered and hi >= entry_price_t + risk_usd:
                    stop_price = entry_price_t; be_triggered = True
                if lo <= stop_price:
                    pnl = (stop_price - entry_price_t) / entry_price_t * capital * 0.01 * trade_score
                    capital += pnl
                    trades.append({'entry_ts':trade_entry_time,'dir':'long','entry':entry_price_t,
                                   'exit':stop_price,'pnl':pnl,'score':trade_score,
                                   'exit':'be' if be_triggered else 'sl','zone':'zone'})
                    in_trade = False; continue
                if hi >= target_price:
                    pnl = (target_price - entry_price_t) / entry_price_t * capital * 0.01 * trade_score
                    capital += pnl
                    trades.append({'entry_ts':trade_entry_time,'dir':'long','entry':entry_price_t,
                                   'exit':target_price,'pnl':pnl,'score':trade_score,
                                   'exit':'tp','zone':'zone'})
                    in_trade = False; continue
            else:
                if not be_triggered and lo <= entry_price_t - risk_usd:
                    stop_price = entry_price_t; be_triggered = True
                if hi >= stop_price:
                    pnl = (entry_price_t - stop_price) / entry_price_t * capital * 0.01 * trade_score
                    capital += pnl
                    trades.append({'entry_ts':trade_entry_time,'dir':'short','entry':entry_price_t,
                                   'exit':stop_price,'pnl':pnl,'score':trade_score,
                                   'exit':'be' if be_triggered else 'sl','zone':'zone'})
                    in_trade = False; continue
                if lo <= target_price:
                    pnl = (entry_price_t - target_price) / entry_price_t * capital * 0.01 * trade_score
                    capital += pnl
                    trades.append({'entry_ts':trade_entry_time,'dir':'short','entry':entry_price_t,
                                   'exit':target_price,'pnl':pnl,'score':trade_score,
                                   'exit':'tp','zone':'zone'})
                    in_trade = False; continue
            continue

        # ── LOOK FOR ENTRY ───────────────────────────────────────────────────
        zone_idx = zone_idx_lookup[i]
        if zone_idx not in zones_r: continue
        zones_here = zones_r[zone_idx]

        for zone_price, zone_type in zones_here:
            direction = 'long' if zone_type == 'support' else 'short'
            if not price_at_zone(price, zone_price, zone_type, atr_v): continue

            # Signals on entry TF
            sig_entry = detect_signals(entry_df, i, direction)
            if sig_entry['score'] < min_score: continue

            # HTF signals for confluence
            h1_idx = h1_idx_lookup[i]
            h4_idx = h4_idx_lookup[i]
            sig_h1 = detect_signals(h1, h1_idx, direction) if h1_idx >= 5 else {'score':0}
            sig_h4 = detect_signals(h4, h4_idx, direction) if h4_idx >= 5 else {'score':0}

            # M1/M5 cross-signals
            if entry_tf == 'm5':
                m1_i2 = m1_idx_lookup[i]
                sig_m1 = detect_signals(m1, m1_i2, direction) if m1_i2 >= 5 else {'score':0}
                sig_m5 = sig_entry
            else:
                m5_i2 = m5_idx_lookup[i]
                sig_m5 = detect_signals(m5, m5_i2, direction) if m5_i2 >= 5 else {'score':0}
                sig_m1 = sig_entry

            valid = False
            if entry_rule == 'ltf_only':
                valid = sig_entry['score'] >= max(1, min_score)
            elif entry_rule == 'confluence':
                htf_ok = (sig_h1['score'] >= 1) and (sig_h4['score'] >= 1)
                ltf_ok = (sig_m1['score'] >= 2) or (sig_m5['score'] >= 1) or (sig_m1['score'] >= 1 and sig_m5['score'] >= 1)
                valid = htf_ok and ltf_ok

            total_score = min(4, sig_m1['score'] + sig_m5['score'] + sig_h1['score'] + sig_h4['score'])
            total_score = max(1, total_score)

            diag.append({'time':dt,'price':price,'zone_price':zone_price,'zone_type':zone_type,
                         'direction':direction,'sig_m1':sig_m1['score'],'sig_m5':sig_m5['score'],
                         'sig_h1':sig_h1['score'],'sig_h4':sig_h4['score'],
                         'total_score':total_score,'valid':valid})

            if not valid: continue

            entry_price_t    = m1_open[i+1] if i+1 < len(m1) else price
            atr_for_stop     = atr_v
            stop_at_entry    = entry_price_t - atr_for_stop * atr_mult if direction == 'long' else entry_price_t + atr_for_stop * atr_mult
            target_price     = entry_price_t + 2 * atr_for_stop * atr_mult if direction == 'long' else entry_price_t - 2 * atr_for_stop * atr_mult

            in_trade         = True
            trade_dir        = direction
            trade_score      = total_score
            trade_entry_time = m1_times[i+1] if i+1 < len(m1_times) else dt
            trade_entry_bar  = i+1
            be_triggered     = False
            atr_at_entry     = atr_for_stop
            stop_price       = stop_at_entry
            break

    return trades, diag

# ── RUN ALL 4 SCENARIOS ───────────────────────────────────────────────────────
results  = {}
diag_all = {}
for name, cfg in SCENARIOS.items():
    print(f"Running Scenario {name}...")
    t, d = run_scenario(name, cfg)
    results[name]  = t
    diag_all[name] = d
    print(f"  Trades: {len(t)}, Zone hits: {len(d)}")

# ── SUMMARY ───────────────────────────────────────────────────────────────────
summary = {}
for name, trades in results.items():
    if not trades:
        summary[name] = {}; continue
    df = pd.DataFrame(trades)
    wins   = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    gw = wins['pnl'].sum(); gl = abs(losses['pnl'].sum())
    pf = gw/gl if gl > 0 else float('inf')
    cap = STARTING_CAPITAL + df['pnl'].sum()
    summary[name] = {
        'Trades':         len(df),
        'Win Rate %':     round(len(wins)/len(df)*100,1),
        'Gross Win £':    round(gw,0),
        'Gross Loss £':   round(gl,0),
        'Net P&L £':      round(df['pnl'].sum(),0),
        'Profit Factor':  round(pf,2),
        'Final Capital £':round(cap,0),
    }

summary_df = pd.DataFrame(summary).T
print("\n" + "="*80)
print("PHANTOM STRATEGY — US100 BACKTEST RESULTS (£7,000 starting capital)")
print("="*80)
print(summary_df.to_string())

# ── CHARTS ────────────────────────────────────────────────────────────────────
colors = {'A':'#2A9D8F','B':'#E9C46A','C':'#E63946','D':'#A8DADC'}
labels = {'A':'A: H1 Zones / M5 Entry','B':'B: H4 Zones / M5 Entry',
          'C':'C: H1 Zones / M1 Entry','D':'D: Confluence H1+H4'}

curves = {}
for name, trades in results.items():
    if not trades: continue
    cap = STARTING_CAPITAL
    curve = [cap]
    for t in trades:
        cap += t['pnl']; curve.append(cap)
    curves[name] = curve

fig = plt.figure(figsize=(16, 14), facecolor='#0d1117')
gs  = gridspec.GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.35)

ax1 = fig.add_subplot(gs[0, :])
ax1.set_facecolor('#161b22')
for n, curve in curves.items():
    ax1.plot(curve, color=colors[n], linewidth=1.5, label=labels[n], alpha=0.9)
ax1.axhline(7000, color='white', linewidth=0.8, linestyle='--', alpha=0.4, label='Start £7,000')
ax1.set_title('Capital Curves — All Scenarios', color='white', fontsize=13, fontweight='bold', pad=10)
ax1.set_ylabel('Capital (£)', color='#aaa'); ax1.set_xlabel('Trade #', color='#aaa')
ax1.tick_params(colors='#aaa')
ax1.legend(loc='upper left', fontsize=9, facecolor='#1c2128', labelcolor='white', framealpha=0.8)
ax1.spines['bottom'].set_color('#333'); ax1.spines['left'].set_color('#333')
ax1.spines['top'].set_visible(False); ax1.spines['right'].set_visible(False)

metrics = {
    'Net P&L (£)':   [summary[n].get('Net P&L £',0) for n in ['A','B','C','D']],
    'Win Rate (%)':  [summary[n].get('Win Rate %',0) for n in ['A','B','C','D']],
    'Profit Factor':[summary[n].get('Profit Factor',0) for n in ['A','B','C','D']],
}
for idx, (metric, vals) in enumerate(metrics.items()):
    row = 1 + idx // 2; col = idx % 2
    ax = fig.add_subplot(gs[row, col])
    ax.set_facecolor('#161b22')
    bars = ax.bar(['A','B','C','D'], vals, color=[colors[s] for s in ['A','B','C','D']], alpha=0.85, width=0.5)
    ax.axhline(0, color='white', linewidth=0.5, alpha=0.3)
    for bar, val in zip(bars, vals):
        ypos = val + (max(vals)-min(vals))*0.02 if val >= 0 else val - (max(vals)-min(vals))*0.05
        ax.text(bar.get_x()+bar.get_width()/2, ypos, f'{val:+.1f}',
                ha='center', va='bottom', color='white', fontsize=9, fontweight='bold')
    ax.set_title(metric, color='white', fontsize=10, fontweight='bold')
    ax.tick_params(colors='#aaa')
    ax.spines['bottom'].set_color('#333'); ax.spines['left'].set_color('#333')
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.set_facecolor('#161b22')

fig.suptitle('PHANTOM STRATEGY — US100 Backtest  |  £7,000 Starting Capital  |  May 2023 – Mar 2024',
             color='white', fontsize=14, fontweight='bold', y=0.98)
plt.savefig('phantom_us100_original_results.png', dpi=150, bbox_inches='tight', facecolor='#0d1117')
plt.close()
print("Chart saved: phantom_us100_original_results.png")

# Save CSVs
for name in ['A','B','C','D']:
    if results[name]:
        pd.DataFrame(results[name]).to_csv(f'phantom_us100_original_{name}_trades.csv', index=False)
summary_df.to_csv('phantom_us100_original_summary.csv')
print("CSVs saved.")
