#!/usr/bin/env python3
"""
PHANTOM V5 — US100 Backtest (SEQUENTIAL TUNING MATRIX)
======================================================
Based on original script with parameter variants:
  D0: Timeout kill only (safeguard baseline)
  D1: D0 + score cap + confluence 0.20%
  B1: Score cap + risk slope boost
  A1: Risk slope only
  A2: A1 + per-zone lockout
  B2: B1 + trail tuning
  D2: D1 + confluence tolerance sweep

Capital: £7,000 | Data: US100 May 2023–Mar 2024
"""
import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from pathlib import Path
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')
matplotlib.use('Agg')

# ── DATA LOADING ──────────────────────────────────────────────────────────────
def load_mt4(path):
    df = pd.read_csv(path, sep='\t', header=0)
    df.columns = [c.strip('<>').lower() for c in df.columns]
    df['datetime'] = pd.to_datetime(df['date'] + ' ' + df['time'], format='%Y.%m.%d %H:%M:%S')
    return df.set_index('datetime').sort_index()[['open','high','low','close','tickvol']].rename(columns={'tickvol':'vol'})

print("[V5] Loading data...")
base = Path('/Users/niko/Downloads')
m1 = load_mt4(base / 'US100.cash_M1_23-24')
m5 = load_mt4(base / 'US100.cash_M5_23-24')
h1 = load_mt4(base / 'US100.cash_H1_23-24')
h4 = load_mt4(base / 'US100.cash_H4_23-24')

def calc_atr(df, period=14):
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

for df in [m1, m5, h1, h4]:
    df['atr'] = calc_atr(df)

print(f"[V5] Data loaded: M1={len(m1)}, M5={len(m5)}, H1={len(h1)}, H4={len(h4)}")

# ── ZONE BUILDING ─────────────────────────────────────────────────────────────
def build_rolling_zones(df, swing_n=5, zone_tol_pct=0.004, min_touches=2, lookback_bars=300):
    h_arr = df['high'].values
    l_arr = df['low'].values
    n = len(df)
    pivot_highs, pivot_lows = [], []
    for i in range(swing_n, n - swing_n):
        if h_arr[i] == max(h_arr[i-swing_n:i+swing_n+1]):
            pivot_highs.append((i, h_arr[i]))
        if l_arr[i] == min(l_arr[i-swing_n:i+swing_n+1]):
            pivot_lows.append((i, l_arr[i]))
    
    ph_arr = np.array(pivot_highs) if pivot_highs else np.empty((0,2))
    pl_arr = np.array(pivot_lows) if pivot_lows else np.empty((0,2))
    
    active_zones = {}
    for i in range(lookback_bars, n):
        zones_at_i = []
        lb = max(0, i - lookback_bars)
        for arr, ztype in [(ph_arr,'resistance'),(pl_arr,'support')]:
            if len(arr) == 0: continue
            recent_pivots = arr[arr[:, 0] >= lb]
            if len(recent_pivots) == 0: continue
            for pidx, pval in recent_pivots:
                tol = pval * zone_tol_pct
                touches = 0
                for j in range(max(lb, int(pidx)), i):
                    h, l = h_arr[j], l_arr[j]
                    if ztype == 'resistance':
                        if l <= pval + tol and h >= pval - tol:
                            touches += 1
                    else:
                        if h >= pval - tol and l <= pval + tol:
                            touches += 1
                if touches >= min_touches:
                    zones_at_i.append({'price': pval, 'type': ztype, 'id': f"{ztype}_{pval:.2f}"})
        if zones_at_i:
            active_zones[i] = zones_at_i
    return active_zones

print("[V5] Building zones...")
zones_h1 = build_rolling_zones(h1, swing_n=5, zone_tol_pct=0.004, min_touches=2, lookback_bars=300)
zones_h4 = build_rolling_zones(h4, swing_n=5, zone_tol_pct=0.006, min_touches=2, lookback_bars=150)
print(f"[V5] Zones built: H1={len(zones_h1)}, H4={len(zones_h4)}")

# ── SIGNAL DETECTION ──────────────────────────────────────────────────────────
def detect_signals(df, i, direction):
    if i < 5: return {'pin_bar':False,'engulfing':False,'double_bottom':False,'failed_breakout':False,'score':0}
    o, h, l, c = df['open'].iloc[i], df['high'].iloc[i], df['low'].iloc[i], df['close'].iloc[i]
    po, ph, pl, pc = df['open'].iloc[i-1], df['high'].iloc[i-1], df['low'].iloc[i-1], df['close'].iloc[i-1]
    body = abs(c-o); rng = h-l
    
    pin = False
    if rng > 0:
        if direction == 'long':
            pin = ((min(o,c)-l) >= 0.6*rng) and (body <= 0.3*rng)
        else:
            pin = ((h-max(o,c)) >= 0.6*rng) and (body <= 0.3*rng)
    
    eng = False
    prev_body = abs(pc-po)
    if prev_body > 0:
        if direction == 'long':
            eng = (o < po) and (c > ph)
        else:
            eng = (o > po) and (c < pl)
    
    db = False
    if i >= 10:
        if direction == 'long':
            db = (min(df['low'].iloc[i-10:i+1]) <= l*1.003)
        else:
            db = (max(df['high'].iloc[i-10:i+1]) >= h*0.997)
    
    fb = False
    if i >= 3:
        if direction == 'long':
            fb = (h > max(df['high'].iloc[i-3:i])*0.998) and (c < h*0.998)
        else:
            fb = (l < min(df['low'].iloc[i-3:i])*1.002) and (c > l*1.002)
    
    score = int(pin) + int(eng) + int(db) + int(fb)
    return {'pin_bar':pin, 'engulfing':eng, 'double_bottom':db, 'failed_breakout':fb, 'score':score}

def in_session(dt):
    return 13 <= dt.hour < 22

def build_tf_lookup(m1_idx, htf_idx):
    return np.searchsorted(htf_idx.values.astype('int64'), m1_idx.values.astype('int64'), side='right') - 1


def signed_return_pct(entry_price, exit_price, direction):
    if direction == 'long':
        return (exit_price - entry_price) / entry_price
    return (entry_price - exit_price) / entry_price

# ── SCENARIO VARIANTS ─────────────────────────────────────────────────────────
VARIANTS = {
    'D0': {
        'scenario_name': 'D0: Timeout kill (safeguard)',
        'zone_tf':'h1', 'entry_tf':'m1', 'atr_mult':2.0, 'confluence':True,
        'atr_src':'entry', 'timeout_min':0, 'trail_mult':0.75,
        'min_score': 2,
        'risk_1':0.5, 'risk_2':1.0, 'risk_3':1.5, 'risk_4':2.0,
        'score_m1_cap':4, 'score_m5_cap':1, 'score_h1_cap':1, 'score_h4_cap':1,
    },
    'D1': {
        'scenario_name': 'D1: D0 + score cap + conf 0.20%',
        'zone_tf':'h1', 'entry_tf':'m1', 'atr_mult':2.0, 'confluence':True, 'conf_tol':0.0020,
        'atr_src':'zone', 'timeout_min':0, 'trail_mult':0.7,
        'min_score': 2,
        'risk_1':0.35, 'risk_2':0.70, 'risk_3':1.00, 'risk_4':1.25,
        'score_m1_cap':2, 'score_m5_cap':1, 'score_h1_cap':1, 'score_h4_cap':1,
    },
    'B1': {
        'scenario_name': 'B1: Score cap + risk boost',
        'zone_tf':'h4', 'entry_tf':'m5', 'atr_mult':1.8, 'confluence':False,
        'atr_src':'zone', 'timeout_min':240, 'trail_mult':0.8,
        'min_score': 1,
        'risk_1':0.35, 'risk_2':0.70, 'risk_3':0.80, 'risk_4':1.20,
        'score_m1_cap':2, 'score_m5_cap':1, 'score_h1_cap':1, 'score_h4_cap':1,
    },
    'A1': {
        'scenario_name': 'A1: Risk slope only',
        'zone_tf':'h1', 'entry_tf':'m5', 'atr_mult':1.5, 'confluence':False,
        'atr_src':'entry', 'timeout_min':240, 'trail_mult':0.75,
        'min_score': 1,
        'risk_1':0.40, 'risk_2':0.60, 'risk_3':1.00, 'risk_4':1.20,
        'score_m1_cap':3, 'score_m5_cap':1, 'score_h1_cap':1, 'score_h4_cap':1,
    },
    'A2': {
        'scenario_name': 'A2: A1 + lockout',
        'zone_tf':'h1', 'entry_tf':'m5', 'atr_mult':1.5, 'confluence':False,
        'atr_src':'entry', 'timeout_min':240, 'trail_mult':0.75,
        'min_score': 1,
        'risk_1':0.40, 'risk_2':0.60, 'risk_3':1.00, 'risk_4':1.20,
        'score_m1_cap':3, 'score_m5_cap':1, 'score_h1_cap':1, 'score_h4_cap':1,
        'lockout_enabled':True,
    },
    'B2': {
        'scenario_name': 'B2: B1 + trail 0.80',
        'zone_tf':'h4', 'entry_tf':'m5', 'atr_mult':1.8, 'confluence':False,
        'atr_src':'zone', 'timeout_min':240, 'trail_mult':0.80,
        'min_score': 1,
        'risk_1':0.35, 'risk_2':0.70, 'risk_3':0.80, 'risk_4':1.20,
        'score_m1_cap':2, 'score_m5_cap':1, 'score_h1_cap':1, 'score_h4_cap':1,
    },
    'D2': {
        'scenario_name': 'D2: D1 + tolerance sweep',
        'zone_tf':'h1', 'entry_tf':'m1', 'atr_mult':2.0, 'confluence':True, 'conf_tol':0.0020,
        'atr_src':'zone', 'timeout_min':0, 'trail_mult':0.7,
        'min_score': 2,
        'risk_1':0.35, 'risk_2':0.70, 'risk_3':1.00, 'risk_4':1.25,
        'score_m1_cap':2, 'score_m5_cap':1, 'score_h1_cap':1, 'score_h4_cap':1,
    },
}

# ── BACKTEST ENGINE ───────────────────────────────────────────────────────────
def run_scenario(name, cfg):
    print(f"\n[V5] Running {name}: {cfg['scenario_name']}...")
    
    zone_tf = cfg['zone_tf']
    entry_tf = cfg['entry_tf']
    zone_df = h1 if zone_tf == 'h1' else h4
    entry_df = m1 if entry_tf == 'm1' else m5
    zones = zones_h1 if zone_tf == 'h1' else zones_h4
    
    # ATR source
    if cfg['atr_src'] == 'zone':
        atr_df = h1 if zone_tf == 'h1' else h4
    else:
        atr_df = entry_df
    
    # Build lookups
    zone_idx_lookup = build_tf_lookup(entry_df.index, zone_df.index)
    h1_idx_lookup = build_tf_lookup(entry_df.index, h1.index)
    h4_idx_lookup = build_tf_lookup(entry_df.index, h4.index)
    m1_idx_lookup = build_tf_lookup(entry_df.index, m1.index)
    m5_idx_lookup = build_tf_lookup(entry_df.index, m5.index)
    
    capital = 7000
    trades = []
    in_trade, trade_dir, trade_score, trade_entry_time = False, None, 0, None
    trade_entry_price, stop_price, trail_stop, be_triggered = 0, 0, 0, False
    trade_stop_dist = 0
    zone_lockout = {}
    
    for i in range(10, len(entry_df)-2):
        dt = entry_df.index[i]
        price = entry_df['close'].iloc[i]
        zone_i = zone_idx_lookup[i]
        if zone_i < 0:
            continue
        if cfg['atr_src'] == 'zone':
            atr_v = atr_df['atr'].iloc[min(zone_i, len(atr_df)-1)]
        else:
            atr_v = atr_df['atr'].iloc[min(i, len(atr_df)-1)]
        
        if not in_session(dt):
            continue
        
        # ─ EXIT LOGIC ─────────────────────────────────────────────────
        if in_trade:
            # Timeout
            if cfg['timeout_min'] > 0:
                elapsed = (dt - trade_entry_time).total_seconds() / 60
                if elapsed > cfg['timeout_min']:
                    ret_pct = signed_return_pct(trade_entry_price, price, trade_dir)
                    pnl = ret_pct * capital * (cfg[f'risk_{trade_score}'] / 100)
                    trades.append({
                        'entry_time': trade_entry_time, 'exit_time': dt, 'direction': trade_dir,
                        'entry_price': trade_entry_price, 'exit_price': price,
                        'score': trade_score, 'pnl': pnl, 'hold_min': elapsed, 'exit_reason': 'timeout',
                        'stop_dist_pts': trade_stop_dist,
                    })
                    capital += pnl
                    in_trade = False
                    continue
            
            # Stop loss
            if (trade_dir == 'long' and price <= stop_price) or (trade_dir == 'short' and price >= stop_price):
                ret_pct = signed_return_pct(trade_entry_price, price, trade_dir)
                pnl = ret_pct * capital * (cfg[f'risk_{trade_score}'] / 100)
                trades.append({
                    'entry_time': trade_entry_time, 'exit_time': dt, 'direction': trade_dir,
                    'entry_price': trade_entry_price, 'exit_price': price,
                    'score': trade_score, 'pnl': pnl, 'hold_min': (dt-trade_entry_time).total_seconds()/60, 'exit_reason': 'stop',
                    'stop_dist_pts': trade_stop_dist,
                })
                capital += pnl
                in_trade = False
                continue
            
            # BE + Trail
            if not be_triggered:
                profit_pct = (price - trade_entry_price) / trade_entry_price if trade_dir == 'long' else (trade_entry_price - price) / trade_entry_price
                stop_dist = abs(stop_price - trade_entry_price)
                if profit_pct >= stop_dist / trade_entry_price:
                    be_triggered = True
                    trail_stop = price
            
            if be_triggered:
                if trade_dir == 'long':
                    trail_stop = max(trail_stop, price - atr_v * cfg['trail_mult'])
                    if price <= trail_stop:
                        ret_pct = signed_return_pct(trade_entry_price, price, trade_dir)
                        pnl = ret_pct * capital * (cfg[f'risk_{trade_score}'] / 100)
                        trades.append({
                            'entry_time': trade_entry_time, 'exit_time': dt, 'direction': trade_dir,
                            'entry_price': trade_entry_price, 'exit_price': price,
                            'score': trade_score, 'pnl': pnl, 'hold_min': (dt-trade_entry_time).total_seconds()/60, 'exit_reason': 'trail',
                            'stop_dist_pts': trade_stop_dist,
                        })
                        capital += pnl
                        in_trade = False
                        continue
                else:
                    trail_stop = min(trail_stop, price + atr_v * cfg['trail_mult'])
                    if price >= trail_stop:
                        ret_pct = signed_return_pct(trade_entry_price, price, trade_dir)
                        pnl = ret_pct * capital * (cfg[f'risk_{trade_score}'] / 100)
                        trades.append({
                            'entry_time': trade_entry_time, 'exit_time': dt, 'direction': trade_dir,
                            'entry_price': trade_entry_price, 'exit_price': price,
                            'score': trade_score, 'pnl': pnl, 'hold_min': (dt-trade_entry_time).total_seconds()/60, 'exit_reason': 'trail',
                            'stop_dist_pts': trade_stop_dist,
                        })
                        capital += pnl
                        in_trade = False
                        continue
        
        # ─ ENTRY LOGIC ────────────────────────────────────────────────
        zone_list = zones.get(zone_i, [])
        if not in_trade and zone_list:
            for zone in zone_list:
                zone_price, zone_type, zone_id = zone['price'], zone['type'], zone['id']
                direction = 'long' if zone_type == 'support' else 'short'
                
                # Lockout check
                if cfg.get('lockout_enabled'):
                    if zone_id in zone_lockout and dt < zone_lockout[zone_id]:
                        continue
                
                # Price at zone?
                if abs(price - zone_price) / zone_price > 0.005:
                    continue
                
                # Signal detection
                sig_h1 = detect_signals(h1, h1_idx_lookup[i], direction)['score'] if h1_idx_lookup[i] >= 0 and h1_idx_lookup[i] < len(h1) else 0
                sig_h4 = detect_signals(h4, h4_idx_lookup[i], direction)['score'] if h4_idx_lookup[i] >= 0 and h4_idx_lookup[i] < len(h4) else 0
                sig_m5 = detect_signals(m5, m5_idx_lookup[i], direction)['score'] if m5_idx_lookup[i] >= 0 and m5_idx_lookup[i] < len(m5) else 0
                sig_m1 = detect_signals(m1, m1_idx_lookup[i], direction)['score'] if m1_idx_lookup[i] >= 0 and m1_idx_lookup[i] < len(m1) else 0
                
                # Cap per TF
                score_m1_contrib = min(sig_m1, cfg['score_m1_cap'])
                score_m5_contrib = min(sig_m5, cfg['score_m5_cap'])
                score_h1_contrib = min(sig_h1, cfg['score_h1_cap'])
                score_h4_contrib = min(sig_h4, cfg['score_h4_cap'])
                total_score = score_m1_contrib + score_m5_contrib + score_h1_contrib + score_h4_contrib
                
                if total_score < cfg.get('min_score', 1):
                    continue
                
                # Confluence check
                if cfg['confluence']:
                    if sig_h1 < 1 or sig_h4 < 1:
                        continue
                
                # ENTER
                in_trade = True
                trade_dir = direction
                trade_score = min(int(total_score), 4)
                trade_entry_time = dt
                trade_entry_price = price
                be_triggered = False
                
                stop_dist = atr_v * cfg['atr_mult']
                trade_stop_dist = stop_dist
                if direction == 'long':
                    stop_price = price - stop_dist
                    trail_stop = stop_price
                else:
                    stop_price = price + stop_dist
                    trail_stop = stop_price
                
                if cfg.get('lockout_enabled'):
                    zone_lockout[zone_id] = dt + timedelta(minutes=60)
                
                break
    
    if not trades:
        print(f"  ✗ No trades generated")
        return None
    
    trades_df = pd.DataFrame(trades)
    
    # Metrics
    wins = trades_df[trades_df['pnl'] > 0]
    losses = trades_df[trades_df['pnl'] <= 0]
    gw = wins['pnl'].sum() if len(wins) > 0 else 0
    gl = abs(losses['pnl'].sum()) if len(losses) > 0 else 0
    pf = gw / gl if gl > 0 else (float('inf') if gw > 0 else 0)
    wr = len(wins) / len(trades_df) * 100
    dd = trades_df['pnl'].cumsum().min()
    
    timeout_pct = (trades_df['exit_reason'] == 'timeout').sum() / len(trades_df) * 100
    score_4_pct = (trades_df['score'] == 4).sum() / len(trades_df) * 100
    dd_pct = abs(dd) / 7000 * 100
    dd_limit = 12 if name.startswith('A') else 8
    pass_flag = (pf >= 1.35) and (timeout_pct < 40) and (score_4_pct < 65) and (dd_pct <= dd_limit)
    avg_stop_pts = trades_df['stop_dist_pts'].mean() if 'stop_dist_pts' in trades_df else 0
    hold_by_exit = trades_df.groupby('exit_reason')['hold_min'].mean().round(1).to_dict()
    
    print(f"  Trades: {len(trades_df)} | WR: {wr:.1f}% | PF: {pf:.2f} | P&L: £{gw-gl:,.0f} | DD: £{dd:,.0f}")
    print(f"  Timeout: {timeout_pct:.0f}% | Score-4: {score_4_pct:.0f}%")
    print(f"  Avg stop distance: {avg_stop_pts:.1f} pts")
    print(f"  Avg hold by exit: {hold_by_exit}")
    print(f"  Pass criteria: {pass_flag} (DD%={dd_pct:.2f}, limit={dd_limit}%)")
    
    # Save CSV
    trades_df.to_csv(f'phantom_us100_v5_{name}_trades.csv', index=False)
    
    return {
        'trades': len(trades_df),
        'wr': wr,
        'pf': pf,
        'pnl': gw-gl,
        'dd': dd,
        'timeout_pct': timeout_pct,
        'score_4_pct': score_4_pct,
        'avg_stop_pts': avg_stop_pts,
        'dd_pct': dd_pct,
        'pass': pass_flag,
    }

# ── SEQUENTIAL EXECUTION ──────────────────────────────────────────────────────
print("\n" + "="*80)
print("PHANTOM V5 — SEQUENTIAL TUNING MATRIX")
print("="*80)

results = {}
gates = {}

# D0
r = run_scenario('D0', VARIANTS['D0'])
results['D0'] = r
gates['D0'] = r['pass'] if r else False
print(f"  [GATE: {gates['D0']}]")

# D1
r = run_scenario('D1', VARIANTS['D1'])
results['D1'] = r
gates['D1'] = r['pass'] if r else False
print(f"  [GATE: {gates['D1']}]")

# B1
r = run_scenario('B1', VARIANTS['B1'])
results['B1'] = r
gates['B1'] = r['pass'] if r else False
print(f"  [GATE: {gates['B1']}]")

# A1
r = run_scenario('A1', VARIANTS['A1'])
results['A1'] = r
gates['A1'] = r['pass'] if r else False
print(f"  [GATE: {gates['A1']}]")

# A2
r = run_scenario('A2', VARIANTS['A2'])
results['A2'] = r
gates['A2'] = r['pass'] if r else False
print(f"  [GATE: {gates['A2']}]")

# B2
r = run_scenario('B2', VARIANTS['B2'])
results['B2'] = r
gates['B2'] = r['pass'] if r else False
print(f"  [GATE: {gates['B2']}]")

# D2
if gates['D1']:
    r = run_scenario('D2', VARIANTS['D2'])
    results['D2'] = r
    gates['D2'] = r['pass'] if r else False
    print(f"  [GATE: {gates['D2']}]")
else:
    print(f"\n[V5] D2 SKIPPED (D1 failed)")
    results['D2'] = None
    gates['D2'] = False

# ── SUMMARY ───────────────────────────────────────────────────────────────────
print("\n" + "="*80)
print("SUMMARY")
print("="*80)

rows = []
for var in ['D0', 'D1', 'B1', 'A1', 'A2', 'B2', 'D2']:
    if results.get(var):
        r = results[var]
        rows.append({
            'Variant': var,
            'Trades': r['trades'],
            'WR %': f"{r['wr']:.1f}",
            'PF': f"{r['pf']:.2f}",
            'P&L £': f"£{r['pnl']:,.0f}",
            'Max DD £': f"£{r['dd']:,.0f}",
            'DD %': f"{r['dd_pct']:.2f}",
            'Timeout %': f"{r['timeout_pct']:.0f}",
            'Score-4 %': f"{r['score_4_pct']:.0f}",
            'Avg Stop pts': f"{r['avg_stop_pts']:.1f}",
            'Pass': '✓' if r['pass'] else '✗',
        })
    else:
        rows.append({'Variant': var, 'Trades': '—', 'WR %': '—', 'PF': '—', 'P&L £': '—', 'Max DD £': '—', 'DD %': '—', 'Timeout %': '—', 'Score-4 %': '—', 'Avg Stop pts': '—', 'Pass': '⊘'})

summary_df = pd.DataFrame(rows)
print(summary_df.to_string(index=False))
summary_df.to_csv('phantom_us100_v5_summary.csv', index=False)

print(f"\n[V5] Complete! Summary: phantom_us100_v5_summary.csv")
print("="*80)
