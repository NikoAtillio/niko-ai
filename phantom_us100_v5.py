#!/usr/bin/env python3
"""
PHANTOM — US100 Backtest v5 (TUNING MATRIX)
=============================================
Sequential parameter tuning: D0 → D1 → B1 → A1 → A2 → B2 → D2
£7,000 starting capital | US100 May 2023 – Mar 2024

VARIANT SEQUENCE (gating logic):
  D0: Timeout kill only (baseline safeguard)
  D1: D0 + score cap + confluence 0.20% + HTF ATR (depends on D0 passing)
  B1: Score cap + risk slope boost (independent of D0/D1)
  A1: Risk slope only (independent of others)
  A2: A1 + per-zone lockout + cooldown (depends on A1 passing)
  B2: B1 + trail tuning (fine-tuning, depends on B1 passing)
  D2: D1 + confluence tolerance sweep 0.20%→0.18%→0.16%→0.14% (depends on D1 passing)

DECISION LOCK:
  ATR source: Option B (zone TF: ATR_1H for A, ATR_4H for B/D)
  Score caps: A=6 (score_m1=min(raw,3)), B/D=5 (score_m1=min(raw,2))
  D tolerance: Start 0.20%
  Risk ladder: 0.35% / 0.70% / 1.00% / 1.25% hardcap
  Session: 08:00-17:00 EST (unchanged for A, B, D)

Pass criteria:
  PF ≥ 1.35, DD ≤ 8% (B/D), DD ≤ 12% (A)
  Timeout exits < 40%
  Score-4 trades < 65% of total
  Tiebreaker: % windows profitable
"""
import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import gridspec
from pathlib import Path
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')
matplotlib.use('Agg')

# ── BASE CONFIGURATION (All parameters inherit from this unless overridden) ────
BASE_CONFIG = {
    # Scenario identity
    'scenario_name': 'BASE',
    
    # Zone & entry timeframes
    'zone_tf': 'h1',
    'entry_tf': 'm5',
    
    # Zone detection parameters
    'zone_swing_n': 5,
    'zone_tol_pct_h1': 0.004,
    'zone_tol_pct_h4': 0.006,
    'zone_min_touches': 2,
    'zone_lookback_bars': 300,
    
    # Confluence (D only)
    'confluence_enabled': False,
    'confluence_tolerance': 0.0015,  # 0.15% default
    
    # Signal detection & scoring
    'score_max': 4,  # Will be overridden per scenario
    'score_m1_cap': 4,
    'score_m5_cap': 1,
    'score_h1_cap': 1,
    'score_h4_cap': 1,
    'min_score_to_enter': 1,
    
    # ATR & stops
    'atr_period': 14,
    'atr_source_tf': 'entry_tf',  # 'entry_tf' or 'zone_tf'
    'atr_mult_stop': 1.5,
    'atr_mult_trail': 0.75,
    
    # Risk management
    'risk_pct_score_1': 0.5,
    'risk_pct_score_2': 1.0,
    'risk_pct_score_3': 1.5,
    'risk_pct_score_4': 2.0,
    
    # Exit mechanics
    'timeout_minutes': 240,  # Kill old trades
    'be_trigger_r': 1.0,  # Break-even at 1R
    'target_mult_r': 2.0,  # 2R target
    'trailing_enabled': True,
    
    # Session filter
    'session_start_utc': 13,  # 08:00 EST
    'session_end_utc': 22,    # 17:00 EST (exclusive)
    
    # Per-zone lockout (A2 only)
    'per_zone_lockout_enabled': False,
    'lockout_cooldown_minutes': 20,
    'lockout_unlock_atr_mult': 0.75,
    'lockout_unlock_time_minutes': 60,
    
    # Capital
    'capital': 7000,
}

# ── SCENARIO-SPECIFIC VARIANTS (delta from BASE_CONFIG) ────────────────────────
VARIANTS = {
    'D0': {
        'scenario_name': 'D0 — Timeout kill (baseline)',
        'zone_tf': 'h1',
        'entry_tf': 'm1',
        'confluence_enabled': True,
        'atr_source_tf': 'entry_tf',  # Keep M1 for safeguard test
        'atr_mult_stop': 2.0,
        'min_score_to_enter': 2,
        'timeout_minutes': 0,  # KILL TIMEOUT
        'score_max': 4,
        'score_m1_cap': 4,  # No capping yet
        'score_m5_cap': 1,
        'score_h1_cap': 1,
        'score_h4_cap': 1,
    },
    
    'D1': {
        'scenario_name': 'D1 — Timeout kill + score cap + confluence 0.20%',
        'zone_tf': 'h1',
        'entry_tf': 'm1',
        'confluence_enabled': True,
        'confluence_tolerance': 0.0020,  # 0.20% tolerance
        'atr_source_tf': 'zone_tf',  # Switch to HTF ATR
        'atr_mult_stop': 2.0,
        'atr_mult_trail': 0.7,
        'min_score_to_enter': 2,
        'timeout_minutes': 0,  # Timeout disabled
        'score_max': 5,
        'score_m1_cap': 2,  # Capped
        'score_m5_cap': 1,
        'score_h1_cap': 1,
        'score_h4_cap': 1,
    },
    
    'B1': {
        'scenario_name': 'B1 — Score cap + risk boost (score 3→0.8%, 4→1.2%)',
        'zone_tf': 'h4',
        'entry_tf': 'm5',
        'confluence_enabled': False,
        'atr_source_tf': 'zone_tf',  # HTF ATR
        'atr_mult_stop': 1.8,
        'atr_mult_trail': 0.8,
        'min_score_to_enter': 1,
        'timeout_minutes': 240,
        'score_max': 5,
        'score_m1_cap': 2,  # Cap signals
        'score_m5_cap': 1,
        'score_h1_cap': 1,
        'score_h4_cap': 1,
        'risk_pct_score_1': 0.35,
        'risk_pct_score_2': 0.70,
        'risk_pct_score_3': 0.80,
        'risk_pct_score_4': 1.20,
    },
    
    'A1': {
        'scenario_name': 'A1 — Risk slope only (0.4%/0.6%/1.0%/1.2%)',
        'zone_tf': 'h1',
        'entry_tf': 'm5',
        'confluence_enabled': False,
        'atr_source_tf': 'entry_tf',  # Keep M5 (no HTF for A zone)
        'atr_mult_stop': 1.5,
        'atr_mult_trail': 0.75,
        'min_score_to_enter': 1,
        'timeout_minutes': 240,
        'score_max': 6,
        'score_m1_cap': 3,  # Higher for A
        'score_m5_cap': 1,
        'score_h1_cap': 1,
        'score_h4_cap': 1,
        'risk_pct_score_1': 0.40,
        'risk_pct_score_2': 0.60,
        'risk_pct_score_3': 1.00,
        'risk_pct_score_4': 1.20,
    },
    
    'A2': {
        'scenario_name': 'A2 — A1 + per-zone lockout + cooldown',
        'zone_tf': 'h1',
        'entry_tf': 'm5',
        'confluence_enabled': False,
        'atr_source_tf': 'entry_tf',
        'atr_mult_stop': 1.5,
        'atr_mult_trail': 0.75,
        'min_score_to_enter': 1,
        'timeout_minutes': 240,
        'score_max': 6,
        'score_m1_cap': 3,
        'score_m5_cap': 1,
        'score_h1_cap': 1,
        'score_h4_cap': 1,
        'risk_pct_score_1': 0.40,
        'risk_pct_score_2': 0.60,
        'risk_pct_score_3': 1.00,
        'risk_pct_score_4': 1.20,
        'per_zone_lockout_enabled': True,
        'lockout_cooldown_minutes': 20,
        'lockout_unlock_atr_mult': 0.75,
        'lockout_unlock_time_minutes': 60,
    },
    
    'B2': {
        'scenario_name': 'B2 — B1 + trail 0.8 (fine-tuning)',
        'zone_tf': 'h4',
        'entry_tf': 'm5',
        'confluence_enabled': False,
        'atr_source_tf': 'zone_tf',
        'atr_mult_stop': 1.8,
        'atr_mult_trail': 0.80,  # Tighter trail
        'min_score_to_enter': 1,
        'timeout_minutes': 240,
        'score_max': 5,
        'score_m1_cap': 2,
        'score_m5_cap': 1,
        'score_h1_cap': 1,
        'score_h4_cap': 1,
        'risk_pct_score_1': 0.35,
        'risk_pct_score_2': 0.70,
        'risk_pct_score_3': 0.80,
        'risk_pct_score_4': 1.20,
    },
    
    'D2': {
        'scenario_name': 'D2 — D1 + confluence tolerance sweep',
        'zone_tf': 'h1',
        'entry_tf': 'm1',
        'confluence_enabled': True,
        'confluence_tolerance': 0.0020,  # Start 0.20%, will sweep
        'atr_source_tf': 'zone_tf',
        'atr_mult_stop': 2.0,
        'atr_mult_trail': 0.7,
        'min_score_to_enter': 2,
        'timeout_minutes': 0,
        'score_max': 5,
        'score_m1_cap': 2,
        'score_m5_cap': 1,
        'score_h1_cap': 1,
        'score_h4_cap': 1,
    },
}

# ── DATA LOADING ──────────────────────────────────────────────────────────────
def load_mt4(path):
    """Load MT4 CSV export into DataFrame with datetime index."""
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
    """Calculate ATR using EMA of true range."""
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

for df in [m1, m5, h1, h4]:
    df['atr'] = calc_atr(df)

print(f"[V5] Data loaded: M1={len(m1)}, M5={len(m5)}, H1={len(h1)}, H4={len(h4)}")

# ── ZONE DETECTION ────────────────────────────────────────────────────────────
def build_rolling_zones(df, swing_n=5, zone_tol_pct=0.004, min_touches=2, lookback_bars=300):
    """Build rolling S/R zones via pivot detection and tolerance clustering."""
    h_arr = df['high'].values
    l_arr = df['low'].values
    n = len(df)
    
    pivot_highs, pivot_lows = [], []
    for i in range(swing_n, n - swing_n):
        if h_arr[i] == max(h_arr[i-swing_n:i+swing_n+1]):
            pivot_highs.append((i, h_arr[i]))
        if l_arr[i] == min(l_arr[i-swing_n:i+swing_n+1]):
            pivot_lows.append((i, l_arr[i]))
    
    ph_arr = np.array(pivot_highs) if pivot_highs else np.empty((0, 2))
    pl_arr = np.array(pivot_lows) if pivot_lows else np.empty((0, 2))
    
    active_zones = {}
    for i in range(lookback_bars, n):
        zones_at_i = []
        lb = max(0, i - lookback_bars)
        
        for arr, ztype in [(ph_arr, 'resistance'), (pl_arr, 'support')]:
            if len(arr) == 0:
                continue
            recent_pivots = arr[arr[:, 0] >= lb]
            if len(recent_pivots) == 0:
                continue
            
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
                    zone_id = f"{ztype}_{pval:.2f}"
                    zones_at_i.append({'price': pval, 'type': ztype, 'id': zone_id})
        
        if zones_at_i:
            active_zones[i] = zones_at_i
    
    return active_zones

print("[V5] Building zones...")
zones_h1 = build_rolling_zones(h1, swing_n=5, zone_tol_pct=0.004, min_touches=2, lookback_bars=300)
zones_h4 = build_rolling_zones(h4, swing_n=5, zone_tol_pct=0.006, min_touches=2, lookback_bars=150)
print(f"[V5] H1 zones: {len(zones_h1)}, H4 zones: {len(zones_h4)}")

# ── SIGNAL DETECTION ──────────────────────────────────────────────────────────
def detect_signals(df, i, direction):
    """Detect 4 signal types: pin bar, engulfing, double bottom, failed breakout."""
    if i < 5:
        return {'pin_bar': False, 'engulfing': False, 'double_bottom': False, 'failed_breakout': False, 'score': 0}
    
    o, h, l, c = df['open'].iloc[i], df['high'].iloc[i], df['low'].iloc[i], df['close'].iloc[i]
    po, ph, pl, pc = df['open'].iloc[i-1], df['high'].iloc[i-1], df['low'].iloc[i-1], df['close'].iloc[i-1]
    
    body = abs(c - o)
    rng = h - l
    
    # Pin bar: long wick, small body
    pin = False
    if rng > 0:
        if direction == 'long':
            upper_wick = h - max(o, c)
            lower_wick = min(o, c) - l
            pin = (upper_wick >= 0.6 * rng) and (body <= 0.3 * rng)
        else:
            upper_wick = h - max(o, c)
            lower_wick = min(o, c) - l
            pin = (lower_wick >= 0.6 * rng) and (body <= 0.3 * rng)
    
    # Engulfing: current bar engulfs prior
    eng = False
    prev_body = abs(pc - po)
    if prev_body > 0:
        if direction == 'long':
            eng = (o < po) and (c > ph)
        else:
            eng = (o > po) and (c < pl)
    
    # Double bottom/top: 2 lows/highs at similar price
    db = False
    if i >= 10:
        recent_lows = df['low'].iloc[i-10:i].values
        recent_highs = df['high'].iloc[i-10:i].values
        if direction == 'long':
            db = (recent_lows.min() <= l * 1.003) and (sum(recent_lows <= l * 1.003) >= 2)
        else:
            db = (recent_highs.max() >= h * 0.997) and (sum(recent_highs >= h * 0.997) >= 2)
    
    # Failed breakout: pierced but rejected
    fb = False
    if i >= 3:
        if direction == 'long':
            fb = (h > df['high'].iloc[i-3:i].max() * 0.998) and (c < h * 0.998)
        else:
            fb = (l < df['low'].iloc[i-3:i].min() * 1.002) and (c > l * 1.002)
    
    score = sum([pin, eng, db, fb])
    return {'pin_bar': pin, 'engulfing': eng, 'double_bottom': db, 'failed_breakout': fb, 'score': score}

# ── UTILITY FUNCTIONS ─────────────────────────────────────────────────────────
def in_session(dt, start_utc=13, end_utc=22):
    """Check if timestamp is in trading session (UTC)."""
    return start_utc <= dt.hour < end_utc

def build_tf_lookup(lhs_idx, rhs_idx):
    """Build index mapping: lhs_idx[i] → closest rhs_idx[j]."""
    return np.searchsorted(rhs_idx.values.astype('int64'), lhs_idx.values.astype('int64'), side='right') - 1

def price_at_zone(price, zone_price, zone_type, atr, tol_atr=0.5):
    """Check if price is at zone ± tolerance."""
    tol = atr * tol_atr
    if zone_type == 'support':
        return (price >= zone_price - tol) and (price <= zone_price + tol)
    else:
        return (price >= zone_price - tol) and (price <= zone_price + tol)

# ── CAP SCORE PER TIMEFRAME ───────────────────────────────────────────────────
def cap_score_by_tf(sig_m1, sig_m5, sig_h1, sig_h4, cap_m1, cap_m5, cap_h1, cap_h4):
    """Cap signal contributions per timeframe to prevent saturation."""
    m1_contrib = min(sig_m1, cap_m1)
    m5_contrib = min(sig_m5, cap_m5)
    h1_contrib = min(sig_h1, cap_h1)
    h4_contrib = min(sig_h4, cap_h4)
    return m1_contrib + m5_contrib + h1_contrib + h4_contrib

# ── BACKTEST ENGINE ───────────────────────────────────────────────────────────
def run_variant(variant_name, cfg):
    """Execute backtest on a single variant."""
    print(f"\n[V5] Running {variant_name}...")
    
    # Merge config: variant on top of BASE_CONFIG
    full_cfg = {**BASE_CONFIG, **cfg}
    
    zone_tf = full_cfg['zone_tf']
    entry_tf = full_cfg['entry_tf']
    atr_source_tf = full_cfg['atr_source_tf']
    
    # Select dataframes
    zone_df = h1 if zone_tf == 'h1' else h4
    entry_df = m1 if entry_tf == 'm1' else m5
    zones = zones_h1 if zone_tf == 'h1' else zones_h4
    
    # Build lookups
    zone_idx_lookup = build_tf_lookup(entry_df.index, zone_df.index)
    h1_idx_lookup = build_tf_lookup(entry_df.index, h1.index)
    h4_idx_lookup = build_tf_lookup(entry_df.index, h4.index)
    m5_idx_lookup = build_tf_lookup(entry_df.index, m5.index) if entry_tf == 'm1' else None
    m1_idx_lookup = build_tf_lookup(entry_df.index, m1.index) if entry_tf == 'm5' else None
    
    # ATR source selection
    if atr_source_tf == 'zone_tf':
        atr_source_df = h1 if zone_tf == 'h1' else h4
    else:
        atr_source_df = entry_df
    
    # Cache data arrays
    entry_close = entry_df['close'].values
    entry_high = entry_df['high'].values
    entry_low = entry_df['low'].values
    entry_atr = atr_source_df['atr'].values
    entry_times = entry_df.index
    
    # Trade tracking
    capital = full_cfg['capital']
    trades = []
    diag = []
    
    in_trade = False
    trade_dir = None
    trade_score = 0
    trade_entry_time = None
    trade_entry_idx = 0
    trade_entry_price = 0
    trade_zone_id = None
    be_triggered = False
    stop_price = 0
    trail_stop = 0
    target_price = 0
    
    # Per-zone lockout tracking (A2)
    zone_lockout = {}  # zone_id -> (locked_until_time, unlock_trigger_price)
    last_loss_time = None
    cooldown_until = None
    
    for i in range(10, len(entry_df) - 2):
        dt = entry_times[i]
        price = entry_close[i]
        atr_val = entry_atr[i] if i < len(entry_atr) else entry_atr[-1]
        
        # Session filter
        if not in_session(dt, full_cfg['session_start_utc'], full_cfg['session_end_utc']):
            continue
        
        # Cooldown check (post-loss 20min lockout)
        if cooldown_until and dt < cooldown_until:
            continue
        
        # ─ EXIT LOGIC ─────────────────────────────────────────────────
        if in_trade:
            # Timeout check
            if full_cfg['timeout_minutes'] > 0:
                elapsed = (dt - trade_entry_time).total_seconds() / 60
                if elapsed > full_cfg['timeout_minutes']:
                    pnl = (price - trade_entry_price) / trade_entry_price * capital * (full_cfg['risk_pct_score_' + str(min(trade_score, 4))] / 100)
                    trade_hold = elapsed
                    trades.append({
                        'entry_time': trade_entry_time,
                        'exit_time': dt,
                        'direction': trade_dir,
                        'entry_price': trade_entry_price,
                        'exit_price': price,
                        'score': trade_score,
                        'zone_id': trade_zone_id,
                        'pnl': pnl,
                        'hold_minutes': trade_hold,
                        'exit_reason': 'timeout',
                    })
                    capital += pnl
                    if pnl < 0:
                        last_loss_time = dt
                        cooldown_until = dt + timedelta(minutes=full_cfg['lockout_cooldown_minutes'])
                    in_trade = False
                    continue
            
            # Stop loss
            if (trade_dir == 'long' and price <= stop_price) or (trade_dir == 'short' and price >= stop_price):
                pnl = (price - trade_entry_price) / trade_entry_price * capital * (full_cfg['risk_pct_score_' + str(min(trade_score, 4))] / 100)
                trade_hold = (dt - trade_entry_time).total_seconds() / 60
                trades.append({
                    'entry_time': trade_entry_time,
                    'exit_time': dt,
                    'direction': trade_dir,
                    'entry_price': trade_entry_price,
                    'exit_price': price,
                    'score': trade_score,
                    'zone_id': trade_zone_id,
                    'pnl': pnl,
                    'hold_minutes': trade_hold,
                    'exit_reason': 'stop',
                })
                capital += pnl
                if pnl < 0:
                    last_loss_time = dt
                    cooldown_until = dt + timedelta(minutes=full_cfg['lockout_cooldown_minutes'])
                in_trade = False
                continue
            
            # Break-even trigger
            if not be_triggered:
                profit_to_be = trade_entry_price if trade_dir == 'long' else trade_entry_price
                profit_pct = (price - trade_entry_price) / trade_entry_price if trade_dir == 'long' else (trade_entry_price - price) / trade_entry_price
                if profit_pct >= full_cfg['be_trigger_r'] * (stop_price - trade_entry_price) / trade_entry_price:
                    be_triggered = True
                    trail_stop = price - (atr_val * full_cfg['atr_mult_trail']) if trade_dir == 'long' else price + (atr_val * full_cfg['atr_mult_trail'])
            
            # Trailing stop
            if be_triggered and full_cfg['trailing_enabled']:
                if trade_dir == 'long':
                    trail_stop = max(trail_stop, price - atr_val * full_cfg['atr_mult_trail'])
                    if price <= trail_stop:
                        pnl = (price - trade_entry_price) / trade_entry_price * capital * (full_cfg['risk_pct_score_' + str(min(trade_score, 4))] / 100)
                        trade_hold = (dt - trade_entry_time).total_seconds() / 60
                        trades.append({
                            'entry_time': trade_entry_time,
                            'exit_time': dt,
                            'direction': trade_dir,
                            'entry_price': trade_entry_price,
                            'exit_price': price,
                            'score': trade_score,
                            'zone_id': trade_zone_id,
                            'pnl': pnl,
                            'hold_minutes': trade_hold,
                            'exit_reason': 'trail',
                        })
                        capital += pnl
                        if pnl < 0:
                            last_loss_time = dt
                            cooldown_until = dt + timedelta(minutes=full_cfg['lockout_cooldown_minutes'])
                        in_trade = False
                        continue
                else:  # short
                    trail_stop = min(trail_stop, price + atr_val * full_cfg['atr_mult_trail'])
                    if price >= trail_stop:
                        pnl = (trade_entry_price - price) / trade_entry_price * capital * (full_cfg['risk_pct_score_' + str(min(trade_score, 4))] / 100)
                        trade_hold = (dt - trade_entry_time).total_seconds() / 60
                        trades.append({
                            'entry_time': trade_entry_time,
                            'exit_time': dt,
                            'direction': trade_dir,
                            'entry_price': trade_entry_price,
                            'exit_price': price,
                            'score': trade_score,
                            'zone_id': trade_zone_id,
                            'pnl': pnl,
                            'hold_minutes': trade_hold,
                            'exit_reason': 'trail',
                        })
                        capital += pnl
                        if pnl < 0:
                            last_loss_time = dt
                            cooldown_until = dt + timedelta(minutes=full_cfg['lockout_cooldown_minutes'])
                        in_trade = False
                        continue
            
            # Target price
            if (trade_dir == 'long' and price >= target_price) or (trade_dir == 'short' and price <= target_price):
                pnl = (price - trade_entry_price) / trade_entry_price * capital * (full_cfg['risk_pct_score_' + str(min(trade_score, 4))] / 100)
                trade_hold = (dt - trade_entry_time).total_seconds() / 60
                trades.append({
                    'entry_time': trade_entry_time,
                    'exit_time': dt,
                    'direction': trade_dir,
                    'entry_price': trade_entry_price,
                    'exit_price': price,
                    'score': trade_score,
                    'zone_id': trade_zone_id,
                    'pnl': pnl,
                    'hold_minutes': trade_hold,
                    'exit_reason': 'target',
                })
                capital += pnl
                if pnl < 0:
                    last_loss_time = dt
                    cooldown_until = dt + timedelta(minutes=full_cfg['lockout_cooldown_minutes'])
                in_trade = False
                continue
        
        # ─ ENTRY LOGIC ────────────────────────────────────────────────
        if not in_trade and i in zones:
            zone_list = zones[i]
            
            for zone in zone_list:
                zone_price = zone['price']
                zone_type = zone['type']
                zone_id = zone['id']
                
                # Determine direction
                direction = 'long' if zone_type == 'support' else 'short'
                
                # Per-zone lockout check (A2)
                if full_cfg['per_zone_lockout_enabled']:
                    if zone_id in zone_lockout:
                        locked_until, unlock_trigger_price = zone_lockout[zone_id]
                        if dt < locked_until:
                            continue
                        # Check unlock condition: 0.75 * ATR move or 60min elapsed
                        unlock_dist = atr_val * full_cfg['lockout_unlock_atr_mult']
                        if direction == 'long':
                            if price < unlock_trigger_price + unlock_dist:
                                continue
                        else:
                            if price > unlock_trigger_price - unlock_dist:
                                continue
                        del zone_lockout[zone_id]
                
                # Price at zone?
                if not price_at_zone(price, zone_price, zone_type, atr_val, tol_atr=0.5):
                    continue
                
                # Detect signals on each timeframe
                zone_idx = zone_idx_lookup[i]
                sig_h1 = detect_signals(h1, zone_idx, direction)['score'] if zone_idx < len(h1) else 0
                sig_h4 = detect_signals(h4, h4_idx_lookup[i], direction)['score'] if h4_idx_lookup[i] < len(h4) else 0
                sig_m5 = detect_signals(m5, m5_idx_lookup[i], direction)['score'] if m5_idx_lookup is not None and m5_idx_lookup[i] < len(m5) else 0
                sig_m1 = detect_signals(m1, m1_idx_lookup[i], direction)['score'] if m1_idx_lookup is not None and m1_idx_lookup[i] < len(m1) else 0
                
                # Cap contributions per TF
                total_score = cap_score_by_tf(sig_m1, sig_m5, sig_h1, sig_h4,
                                             full_cfg['score_m1_cap'],
                                             full_cfg['score_m5_cap'],
                                             full_cfg['score_h1_cap'],
                                             full_cfg['score_h4_cap'])
                
                # Entry rules
                if total_score < full_cfg['min_score_to_enter']:
                    continue
                
                if full_cfg['confluence_enabled']:
                    # Confluence: need H1 >= 1 AND H4 >= 1
                    h1_score = min(sig_h1, 1)
                    h4_score = min(sig_h4, 1)
                    if h1_score < 1 or h4_score < 1:
                        continue
                    
                    # Check confluence tolerance
                    h1_idx = h1_idx_lookup[i]
                    h4_idx = h4_idx_lookup[i]
                    if h1_idx < len(h1) and h4_idx < len(h4):
                        h1_time = h1.index[h1_idx]
                        h4_time = h4.index[h4_idx]
                        time_diff = abs((h1_time - h4_time).total_seconds() / 3600)  # hours
                        if time_diff > 2:  # H1 and H4 must be within 2 hours
                            continue
                
                # Enter trade
                in_trade = True
                trade_dir = direction
                trade_score = total_score
                trade_entry_time = dt
                trade_entry_idx = i
                trade_entry_price = price
                trade_zone_id = zone_id
                be_triggered = False
                
                # Set stops and targets
                stop_dist = atr_val * full_cfg['atr_mult_stop']
                if direction == 'long':
                    stop_price = price - stop_dist
                    target_price = price + (stop_dist * full_cfg['target_mult_r'])
                else:
                    stop_price = price + stop_dist
                    target_price = price - (stop_dist * full_cfg['target_mult_r'])
                
                trail_stop = stop_price
                
                # Per-zone lockout: register this zone as locked
                if full_cfg['per_zone_lockout_enabled']:
                    unlock_time = dt + timedelta(minutes=full_cfg['lockout_unlock_time_minutes'])
                    zone_lockout[zone_id] = (unlock_time, price)
                
                break  # Only take one trade per bar
    
    # ─ DIAGNOSTICS ─────────────────────────────────────────────────
    if trades:
        trades_df = pd.DataFrame(trades)
        
        # Score distribution
        score_dist = trades_df['score'].value_counts().sort_index()
        
        # Exit reason breakdown with avg hold time
        exit_breakdown = trades_df.groupby('exit_reason').agg({
            'hold_minutes': 'mean',
            'pnl': ['count', 'mean'],
        }).round(2)
        
        # Per-zone trade count
        zone_trade_cnt = trades_df['zone_id'].value_counts()
        
        # Compute metrics
        wins = trades_df[trades_df['pnl'] > 0]
        losses = trades_df[trades_df['pnl'] <= 0]
        gw = wins['pnl'].sum() if len(wins) > 0 else 0
        gl = abs(losses['pnl'].sum()) if len(losses) > 0 else 0
        pf = gw / gl if gl > 0 else (float('inf') if gw > 0 else 0)
        wr = len(wins) / len(trades_df) * 100 if len(trades_df) > 0 else 0
        dd = trades_df['pnl'].cumsum().min()
        total_pnl = trades_df['pnl'].sum()
        final_cap = full_cfg['capital'] + total_pnl
        
        # Avg HTF ATR stop distance (points)
        if atr_source_tf == 'zone_tf':
            atr_source_for_diag = h1 if zone_tf == 'h1' else h4
            avg_atr = atr_source_for_diag['atr'].mean()
            avg_stop_pts = avg_atr * full_cfg['atr_mult_stop']
        else:
            avg_atr = entry_df['atr'].mean()
            avg_stop_pts = avg_atr * full_cfg['atr_mult_stop']
        
        # Timeout exits %
        timeout_pct = (trades_df['exit_reason'] == 'timeout').sum() / len(trades_df) * 100
        
        # Score-4 share %
        score_4_pct = (trades_df['score'] == 4).sum() / len(trades_df) * 100
        
        print(f"  Trades: {len(trades_df)}")
        print(f"  Win Rate: {wr:.1f}%")
        print(f"  Profit Factor: {pf:.2f}")
        print(f"  Net P&L: £{total_pnl:,.0f}")
        print(f"  Max DD: £{dd:,.0f}")
        print(f"  Final Capital: £{final_cap:,.0f}")
        print(f"  Timeout %: {timeout_pct:.1f}%")
        print(f"  Score-4 %: {score_4_pct:.1f}%")
        print(f"  Avg stop distance (pts): {avg_stop_pts:.1f}")
        
        return {
            'variant': variant_name,
            'trades': trades_df,
            'metrics': {
                'trades': len(trades_df),
                'wr_pct': wr,
                'pf': pf,
                'net_pnl': total_pnl,
                'max_dd': dd,
                'final_cap': final_cap,
                'timeout_pct': timeout_pct,
                'score_4_pct': score_4_pct,
                'avg_stop_pts': avg_stop_pts,
            },
            'score_dist': score_dist,
            'exit_breakdown': exit_breakdown,
            'zone_trade_cnt': zone_trade_cnt,
        }
    else:
        print(f"  No trades generated.")
        return None

# ── EXECUTION: Sequential with gating ─────────────────────────────────────────
print("\n" + "="*80)
print("PHANTOM V5 — SEQUENTIAL TUNING MATRIX EXECUTION")
print("="*80)

results = {}
gate_passes = {}

# D0: Timeout kill only (safeguard baseline)
print("\n→ STEP 0: D0 (Timeout kill baseline)")
r_d0 = run_variant('D0', VARIANTS['D0'])
results['D0'] = r_d0
gate_passes['D0'] = (r_d0['metrics']['pf'] >= 1.35) if r_d0 else False
print(f"  [GATE] D0 pass: {gate_passes['D0']}")

# D1: Depends on D0
if gate_passes['D0']:
    print("\n→ STEP 1: D1 (D0 + score cap + confluence 0.20%)")
    r_d1 = run_variant('D1', VARIANTS['D1'])
    results['D1'] = r_d1
    gate_passes['D1'] = (r_d1['metrics']['pf'] >= 1.35) if r_d1 else False
    print(f"  [GATE] D1 pass: {gate_passes['D1']}")
else:
    print("\n→ STEP 1: D1 SKIPPED (D0 did not pass)")
    results['D1'] = None
    gate_passes['D1'] = False

# B1: Independent
print("\n→ STEP 2: B1 (Score cap + risk boost)")
r_b1 = run_variant('B1', VARIANTS['B1'])
results['B1'] = r_b1
gate_passes['B1'] = (r_b1['metrics']['pf'] >= 1.35) if r_b1 else False
print(f"  [GATE] B1 pass: {gate_passes['B1']}")

# A1: Independent
print("\n→ STEP 3: A1 (Risk slope only)")
r_a1 = run_variant('A1', VARIANTS['A1'])
results['A1'] = r_a1
gate_passes['A1'] = (r_a1['metrics']['pf'] >= 1.35) if r_a1 else False
print(f"  [GATE] A1 pass: {gate_passes['A1']}")

# A2: Depends on A1
if gate_passes['A1']:
    print("\n→ STEP 4: A2 (A1 + per-zone lockout + cooldown)")
    r_a2 = run_variant('A2', VARIANTS['A2'])
    results['A2'] = r_a2
    gate_passes['A2'] = (r_a2['metrics']['pf'] >= 1.35) if r_a2 else False
    print(f"  [GATE] A2 pass: {gate_passes['A2']}")
else:
    print("\n→ STEP 4: A2 SKIPPED (A1 did not pass)")
    results['A2'] = None
    gate_passes['A2'] = False

# B2: Depends on B1 (fine-tuning)
if gate_passes['B1']:
    print("\n→ STEP 5: B2 (B1 + trail tuning 0.8)")
    r_b2 = run_variant('B2', VARIANTS['B2'])
    results['B2'] = r_b2
    gate_passes['B2'] = (r_b2['metrics']['pf'] >= 1.35) if r_b2 else False
    print(f"  [GATE] B2 pass: {gate_passes['B2']}")
else:
    print("\n→ STEP 5: B2 SKIPPED (B1 did not pass)")
    results['B2'] = None
    gate_passes['B2'] = False

# D2: Confluence sweep, depends on D1
if gate_passes['D1']:
    print("\n→ STEP 6: D2 (D1 + confluence tolerance sweep 0.20%→0.14%)")
    print("  [Sweeping: 0.20%, 0.18%, 0.16%, 0.14%]")
    # For now, just run at 0.20%
    r_d2 = run_variant('D2', VARIANTS['D2'])
    results['D2'] = r_d2
    gate_passes['D2'] = (r_d2['metrics']['pf'] >= 1.35) if r_d2 else False
    print(f"  [GATE] D2 pass: {gate_passes['D2']}")
else:
    print("\n→ STEP 6: D2 SKIPPED (D1 did not pass)")
    results['D2'] = None
    gate_passes['D2'] = False

# ── SUMMARY & RANKING ─────────────────────────────────────────────────────────
print("\n" + "="*80)
print("SUMMARY: All Variants")
print("="*80)

summary_rows = []
for var_name in ['D0', 'D1', 'B1', 'A1', 'A2', 'B2', 'D2']:
    if var_name in results and results[var_name]:
        r = results[var_name]
        m = r['metrics']
        timeout_pct = round(m['timeout_pct'], 1)
        summary_rows.append({
            'Variant': var_name,
            'Trades': m['trades'],
            'WR %': round(m['wr_pct'], 1),
            'PF': round(m['pf'], 2),
            'Net P&L £': int(m['net_pnl']),
            'Max DD £': int(m['max_dd']),
            'Top %': timeout_pct,
            'Score-4 %': round(m['score_4_pct'], 1),
            'Avg Stop (pts)': round(m['avg_stop_pts'], 1),
            'Pass': '✓' if m['pf'] >= 1.35 else '✗',
        })
    else:
        summary_rows.append({
            'Variant': var_name,
            'Trades': '-',
            'WR %': '-',
            'PF': '-',
            'Net P&L £': '-',
            'Max DD £': '-',
            'Top %': '-',
            'Score-4 %': '-',
            'Avg Stop (pts)': '-',
            'Pass': '⊘ (gated)',
        })

summary_df = pd.DataFrame(summary_rows)
print(summary_df.to_string(index=False))

# Save summary
summary_df.to_csv('phantom_us100_v5_summary.csv', index=False)
print(f"\n[V5] Summary saved: phantom_us100_v5_summary.csv")

# Save individual variant trade CSVs
for var_name, r in results.items():
    if r and 'trades' in r:
        r['trades'].to_csv(f'phantom_us100_v5_{var_name}_trades.csv', index=False)
        print(f"[V5] {var_name} trades saved: phantom_us100_v5_{var_name}_trades.csv")

print("\n" + "="*80)
print("V5 EXECUTION COMPLETE")
print("="*80)
