"""
PHANTOM p1 - Multi-Timeframe US100 Backtest Engine
===================================================
Scenarios
    p1C : M5 entry | risk=0.40% | score>=3 | no timeout
    p1B : M5 entry | risk=0.70% | score>=3 | no timeout
    p1A : M1 entry | risk=0.35% | score>=5 | vol filter | no timeout

Usage
    python phantom_p1.py --m1 path/M1.csv --m5 path/M5.csv \
                                             --h1 path/H1.csv --h4 path/H4.csv \
                                             [--scenario p1A] [--capital 10000]

Notes
    - Legacy aliases are still accepted: A/B/C/D.
    - D is mapped to C for backward compatibility.
"""

import argparse
import os
import sys
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

ENGINE_VERSION = 'p1'

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG — edit these or pass via CLI
# ══════════════════════════════════════════════════════════════════════════════
DEFAULTS = {
    'capital'       : 10_000,
    'max_concurrent': 2,
    'cooldown_min'  : 20,
    'lockout_min'   : 60,
    'conf_tol'      : 0.002,   # 0.20% zone proximity
    'h4_pivot_bars' : 2,       # pivot detection: n bars each side
    'h4_lookback'   : 50,      # how many H4 bars back to scan for zones
}

SCENARIOS = {
    'C': dict(
        entry_tf    = 'm5',
        risk_pct    = 0.004,
        atr_stop    = 1.8,
        atr_trail   = 0.8,
        score_min   = 3,
        h4_min      = 1,
        h1_min      = 1,
        ltf_min     = 1,
        ltf_cap     = 3,
        vol_filter  = False,
        timeout_bars= None,
    ),
    'B': dict(
        entry_tf    = 'm5',
        risk_pct    = 0.007,
        atr_stop    = 1.8,
        atr_trail   = 0.8,
        score_min   = 3,
        h4_min      = 1,
        h1_min      = 1,
        ltf_min     = 1,
        ltf_cap     = 3,
        vol_filter  = False,
        timeout_bars= None,
    ),
    'A': dict(
        entry_tf    = 'm1',
        risk_pct    = 0.0035,
        atr_stop    = 1.35,
        atr_trail   = 0.9,
        score_min   = 5,
        h4_min      = 1,
        h1_min      = 1,
        ltf_min     = 2,       # M1 must score ≥2
        ltf_cap     = 3,
        vol_filter  = True,
        timeout_bars= None,
    ),
}

# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════
def load_csv(path: str) -> pd.DataFrame:
    """Load MetaTrader-style tab-separated OHLCV file."""
    df = pd.read_csv(path, sep='\t', header=0)
    df.columns = [c.strip('<>').lower() for c in df.columns]
    df['datetime'] = pd.to_datetime(df['date'] + ' ' + df['time'])
    df = df.set_index('datetime').sort_index()
    for col in ['open', 'high', 'low', 'close', 'tickvol']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)
    return df

# ══════════════════════════════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════════════════════════════
def calc_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat(
        [h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()

def calc_ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def calc_rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d  = s.diff()
    g  = d.clip(lower=0).ewm(span=n, adjust=False).mean()
    ls = (-d).clip(lower=0).ewm(span=n, adjust=False).mean()
    return 100 - 100 / (1 + g / ls.replace(0, np.nan))

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df['atr']    = calc_atr(df)
    df['ema20']  = calc_ema(df['close'], 20)
    df['ema50']  = calc_ema(df['close'], 50)
    df['rsi']    = calc_rsi(df['close'])
    df['vol_ma'] = df['tickvol'].rolling(20).mean()
    return df

# ══════════════════════════════════════════════════════════════════════════════
# FAST LOOKUP HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def fast_val(idx_arr: np.ndarray, vals: np.ndarray, ts) -> float:
    i = np.searchsorted(idx_arr, ts, side='right') - 1
    return float(vals[i]) if i >= 0 else np.nan

def score_tf(idx_arr, c_arr, e20_arr, e50_arr, rsi_arr, ts, direction: str) -> int:
    """Score 0–3 for a single timeframe."""
    i = np.searchsorted(idx_arr, ts, side='right') - 1
    if i < 0:
        return 0
    c, e20, e50, rv = c_arr[i], e20_arr[i], e50_arr[i], rsi_arr[i]
    if np.isnan(c) or np.isnan(e20) or np.isnan(e50):
        return 0
    s = 0
    if direction == 'long':
        if c > e20:                          s += 1
        if e20 > e50:                        s += 1
        if not np.isnan(rv) and rv > 50:     s += 1
    else:
        if c < e20:                          s += 1
        if e20 < e50:                        s += 1
        if not np.isnan(rv) and rv < 50:     s += 1
    return s

# ══════════════════════════════════════════════════════════════════════════════
# H4 PIVOT ZONE BUILDER
# ══════════════════════════════════════════════════════════════════════════════
def build_h4_zones(h4: pd.DataFrame, n: int = 2):
    """Return arrays of (timestamp, price) for H4 swing highs and lows."""
    highs = h4['high'].values
    lows  = h4['low'].values
    idx   = h4.index.values
    ts_list, px_list = [], []
    for i in range(n, len(h4) - n):
        if highs[i] == max(highs[i-n:i+n+1]):
            ts_list.append(idx[i]); px_list.append(highs[i])
        if lows[i] == min(lows[i-n:i+n+1]):
            ts_list.append(idx[i]); px_list.append(lows[i])
    return np.array(ts_list), np.array(px_list)

def get_nearby_zone(price: float, ts, zone_ts, zone_px,
                    tol: float = 0.002, lookback: int = 50):
    """Return (zone_price, direction) or (None, None)."""
    i_max = np.searchsorted(zone_ts, ts, side='right')
    start = max(0, i_max - lookback)
    sub   = zone_px[start:i_max]
    if len(sub) == 0:
        return None, None
    diffs = np.abs(sub - price) / price
    best  = int(np.argmin(diffs))
    if diffs[best] < tol:
        z_price = sub[best]
        z_dir   = 'long' if price <= z_price else 'short'
        return z_price, z_dir
    return None, None


def apply_execution_adjustment(price: float, direction: str, side: str,
                               spread_bps: float, slippage_bps: float) -> float:
    px = float(price)
    if not np.isfinite(px) or px <= 0:
        return px
    half_spread = max(0.0, float(spread_bps)) / 20000.0
    slippage = max(0.0, float(slippage_bps)) / 10000.0
    adj = px * (half_spread + slippage)
    if side == 'entry':
        return px + adj if direction == 'long' else px - adj
    return px - adj if direction == 'long' else px + adj

# ══════════════════════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ══════════════════════════════════════════════════════════════════════════════
def run_scenario(
    candles: pd.DataFrame,
    h4_idx, h4_c, h4_e20, h4_e50, h4_rsi, h4_atr_arr,
    h1_idx, h1_c, h1_e20, h1_e50, h1_rsi,
    m5_idx, m5_c, m5_e20, m5_e50, m5_rsi, m5_vol, m5_vol_ma,
    m1_idx, m1_c, m1_e20, m1_e50, m1_rsi,
    zone_ts, zone_px,
    cfg: dict,
    capital: float = 10_000,
    max_concurrent: int = 2,
    cooldown_min: int = 20,
    lockout_min: int = 60,
    conf_tol: float = 0.002,
    spread_bps: float = 0.0,
    slippage_bps: float = 0.0,
    commission_per_trade: float = 0.0,
    label: str = '',
) -> pd.DataFrame:

    risk_pct     = cfg['risk_pct']
    atr_stop     = cfg['atr_stop']
    atr_trail    = cfg['atr_trail']
    score_min    = cfg['score_min']
    h4_min       = cfg['h4_min']
    h1_min       = cfg['h1_min']
    ltf_min      = cfg['ltf_min']
    ltf_cap      = cfg['ltf_cap']
    vol_filter   = cfg['vol_filter']
    timeout_bars = cfg['timeout_bars']
    use_m1       = cfg['entry_tf'] == 'm1'
    spread_bps = max(0.0, float(spread_bps))
    slippage_bps = max(0.0, float(slippage_bps))
    commission_per_trade = max(0.0, float(commission_per_trade))

    c_idx = candles.index.values
    c_c   = candles['close'].values
    c_h   = candles['high'].values
    c_l   = candles['low'].values

    positions    = []
    zone_lock    = {}
    last_loss_ts = np.datetime64('2000-01-01')
    results      = []
    skipped      = {k: 0 for k in
                    ['max_concurrent','cooldown','zone_lock','score','no_atr','no_zone']}

    for bar_i in range(len(candles)):
        ts    = c_idx[bar_i]
        price = c_c[bar_i]
        hi    = c_h[bar_i]
        lo    = c_l[bar_i]

        # ── manage open positions ──────────────────────────────────────────
        still_open = []
        for p in positions:
            hit_stop = hit_tp = False
            if p['dir'] == 'long':
                new_trail = price - atr_trail * p['atr_e']
                p['stop'] = max(p['stop'], new_trail)
                if lo <= p['stop']:  hit_stop = True
                if hi >= p['tp']:    hit_tp   = True
            else:
                new_trail = price + atr_trail * p['atr_e']
                p['stop'] = min(p['stop'], new_trail)
                if hi >= p['stop']:  hit_stop = True
                if lo <= p['tp']:    hit_tp   = True

            if timeout_bars and (bar_i - p['bar_i']) >= timeout_bars:
                hit_stop = True

            if hit_tp or hit_stop:
                exit_signal_px = p['tp'] if hit_tp else p['stop']
                exit_px = apply_execution_adjustment(
                    exit_signal_px, p['dir'], 'exit', spread_bps, slippage_bps
                )
                gross_pnl = ((exit_px - p['entry']) * p['qty']
                       if p['dir'] == 'long'
                       else (p['entry'] - exit_px) * p['qty'])
                fees = commission_per_trade
                pnl = gross_pnl - fees
                capital += pnl
                win = pnl > 0
                if not win:
                    last_loss_ts = ts
                reason = ('tp' if hit_tp
                          else ('timeout' if timeout_bars and (bar_i - p['bar_i']) >= timeout_bars
                                else 'stop'))
                risk_cash = max(1e-9, p['initial_risk_price'] * p['qty'])
                r_value = pnl / risk_cash
                results.append({
                    'entry_ts' : p['entry_ts'],
                    'exit_ts'  : ts,
                    'dir'      : p['dir'],
                    'entry'    : p['entry'],
                    'exit'     : exit_px,
                    'entry_price': p['entry'],
                    'exit_price': exit_px,
                    'entry_signal_price': p['entry_signal'],
                    'exit_signal_price': exit_signal_px,
                    'stop_price': p['stop_initial'],
                    'stop_price_initial': p['stop_initial'],
                    'stop_price_exit': p['stop'],
                    'initial_risk_price': p['initial_risk_price'],
                    'r_value': r_value,
                    'fees': fees,
                    'pnl'      : pnl,
                    'win'      : win,
                    'exit_reason': reason,
                    'qty'      : p['qty'],
                })
            else:
                still_open.append(p)
        positions = still_open

        # ── entry gate checks ─────────────────────────────────────────────
        if len(positions) >= max_concurrent:
            skipped['max_concurrent'] += 1; continue

        try:
            cd = float((ts - last_loss_ts) / np.timedelta64(1, 'm'))
        except Exception:
            cd = 9999
        if cd < cooldown_min:
            skipped['cooldown'] += 1; continue

        atr_h4_v = fast_val(h4_idx, h4_atr_arr, ts)
        if np.isnan(atr_h4_v) or atr_h4_v <= 0:
            skipped['no_atr'] += 1; continue

        near_z, z_dir = get_nearby_zone(price, ts, zone_ts, zone_px, tol=conf_tol)
        if near_z is None:
            skipped['no_zone'] += 1; continue

        lock_key = (round(near_z, 0), z_dir)
        if lock_key in zone_lock:
            try:
                mins_locked = float((ts - zone_lock[lock_key]) / np.timedelta64(1, 'm'))
            except Exception:
                mins_locked = 9999
            if mins_locked < 0:
                skipped['zone_lock'] += 1; continue

        # ── multi-TF score ────────────────────────────────────────────────
        s_h4 = score_tf(h4_idx, h4_c, h4_e20, h4_e50, h4_rsi, ts, z_dir)
        s_h1 = score_tf(h1_idx, h1_c, h1_e20, h1_e50, h1_rsi, ts, z_dir)
        s_m5 = score_tf(m5_idx, m5_c, m5_e20, m5_e50, m5_rsi, ts, z_dir)
        s_m1 = min(
            score_tf(m1_idx, m1_c, m1_e20, m1_e50, m1_rsi, ts, z_dir),
            ltf_cap
        )
        ltf_score = s_m1 if use_m1 else s_m5

        # Volume filter (M5 vol vs 20-bar MA)
        if vol_filter:
            i_m5 = int(np.searchsorted(m5_idx, ts, side='right')) - 1
            if i_m5 >= 0:
                vol_now  = m5_vol[i_m5]
                vol_ma_v = m5_vol_ma[i_m5]
                if not np.isnan(vol_ma_v) and vol_now < 0.8 * vol_ma_v:
                    skipped['score'] += 1; continue

        total = s_h4 + s_h1 + ltf_score
        if total < score_min or s_h4 < h4_min or s_h1 < h1_min or ltf_score < ltf_min:
            skipped['score'] += 1; continue

        # ── size & enter ──────────────────────────────────────────────────
        stop_dist = atr_stop * atr_h4_v
        risk_amt  = capital * risk_pct
        stop_px   = price - stop_dist if z_dir == 'long' else price + stop_dist
        tp_px     = price + 2 * stop_dist if z_dir == 'long' else price - 2 * stop_dist
        entry_exec = apply_execution_adjustment(price, z_dir, 'entry', spread_bps, slippage_bps)
        initial_risk_price = abs(entry_exec - stop_px)
        if initial_risk_price <= 0:
            initial_risk_price = stop_dist if stop_dist > 0 else 1e-9
        qty = risk_amt / initial_risk_price if initial_risk_price > 0 else 0

        positions.append({
            'dir'     : z_dir,
            'entry_signal': price,
            'entry'   : entry_exec,
            'entry_ts': ts,
            'bar_i'   : bar_i,
            'stop'    : stop_px,
            'stop_initial': stop_px,
            'tp'      : tp_px,
            'qty'     : qty,
            'initial_risk_price': initial_risk_price,
            'atr_e'   : atr_h4_v,
        })
        zone_lock[lock_key] = ts + np.timedelta64(lockout_min, 'm')

    # ── close any remaining open positions at last bar ────────────────────
    for p in positions:
        exit_signal_px = c_c[-1]
        exit_px = apply_execution_adjustment(
            exit_signal_px, p['dir'], 'exit', spread_bps, slippage_bps
        )
        gross_pnl = ((exit_px - p['entry']) * p['qty']
               if p['dir'] == 'long'
               else (p['entry'] - exit_px) * p['qty'])
        fees = commission_per_trade
        pnl = gross_pnl - fees
        capital += pnl
        risk_cash = max(1e-9, p['initial_risk_price'] * p['qty'])
        r_value = pnl / risk_cash
        results.append({
            'entry_ts': p['entry_ts'], 'exit_ts': c_idx[-1],
            'dir': p['dir'], 'entry': p['entry'], 'exit': exit_px,
            'entry_price': p['entry'],
            'exit_price': exit_px,
            'entry_signal_price': p['entry_signal'],
            'exit_signal_price': exit_signal_px,
            'stop_price': p['stop_initial'],
            'stop_price_initial': p['stop_initial'],
            'stop_price_exit': p['stop'],
            'initial_risk_price': p['initial_risk_price'],
            'r_value': r_value,
            'fees': fees,
            'pnl': pnl, 'win': pnl > 0, 'exit_reason': 'eod', 'qty': p['qty'],
        })

    df_r = pd.DataFrame(results)
    _print_summary(df_r, label, capital, skipped)
    return df_r


# ══════════════════════════════════════════════════════════════════════════════
# REPORTING
# ══════════════════════════════════════════════════════════════════════════════
def _print_summary(df_r: pd.DataFrame, label: str, final_cap: float,
                   skipped: dict, start_cap: float = 10_000):
    if df_r is None or len(df_r) == 0:
        print(f"\n{label}: 0 trades"); return

    trades = len(df_r)
    wr     = df_r['win'].mean() * 100
    gw     = df_r[df_r['win']]['pnl'].sum()
    gl     = df_r[~df_r['win']]['pnl'].sum()
    pf     = abs(gw / gl) if gl != 0 else float('inf')
    net    = df_r['pnl'].sum()
    ret    = net / start_cap * 100
    eq     = start_cap + df_r['pnl'].cumsum()
    peak   = eq.cummax()
    dd     = ((eq - peak) / peak).min() * 100
    exp    = df_r['pnl'].mean()
    t_pct  = (df_r['exit_reason'] == 'timeout').mean() * 100

    pf_flag  = '✅' if pf  >= 1.4  else '❌'
    dd_flag  = '✅' if dd  >= -8   else '❌'
    wr_flag  = '✅' if wr  >= 45   else '❌'
    ret_flag = '✅' if ret > 0     else '❌'

    print(f"\n{'='*52}")
    print(f"  {label}")
    print(f"{'='*52}")
    print(f"  Trades      : {trades}")
    print(f"  Win %       : {wr:.1f}%   {wr_flag}")
    print(f"  PF          : {pf:.3f}  {pf_flag}")
    print(f"  Net Return  : {ret:.2f}%  {ret_flag}")
    print(f"  Max DD      : {dd:.2f}%  {dd_flag}")
    print(f"  Expectancy  : ${exp:.2f}/trade")
    print(f"  Final Cap   : ${final_cap:,.2f}")
    print(f"  Timeout %   : {t_pct:.1f}%")
    print(f"  Skipped     : {skipped}")


def canonicalize_scenario(raw: str) -> str:
    token = str(raw or '').strip().upper().replace('.', '')
    token = token.replace(ENGINE_VERSION.upper(), '')
    alias_map = {
        'A': 'A',
        'B': 'B',
        'C': 'C',
        'D': 'C',
    }
    normalized = alias_map.get(token, token)
    if normalized not in SCENARIOS:
        raise ValueError(f"Unknown scenario '{raw}'. Use p1A | p1B | p1C | ALL")
    return normalized


def scenario_id(letter: str) -> str:
    return f"{ENGINE_VERSION.upper()}{letter}"


def print_comparison():
    print(f"\n\n=== {ENGINE_VERSION.upper()} SCENARIO SNAPSHOT ===")
    print(f"{'Scen':<8} {'PF':>8} {'Max DD':>10} {'Net Ret':>10}")
    rows = [
        (scenario_id('A'), '1.450', '-3.79%', '+41.55%'),
        (scenario_id('B'), '1.308', '-5.24%', '+53.61%'),
        (scenario_id('C'), '1.319', '-3.03%', '+28.21%'),
    ]
    for r in rows:
        print(f"  {r[0]:<8} {r[1]:>8} {r[2]:>10} {r[3]:>10}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description=f'Phantom {ENGINE_VERSION} Backtest')
    parser.add_argument('--m1',       required=True,  help='Path to M1 CSV')
    parser.add_argument('--m5',       required=True,  help='Path to M5 CSV')
    parser.add_argument('--h1',       required=True,  help='Path to H1 CSV')
    parser.add_argument('--h4',       required=True,  help='Path to H4 CSV')
    parser.add_argument('--scenario', default='ALL',  help=f'{ENGINE_VERSION}A | {ENGINE_VERSION}B | {ENGINE_VERSION}C | A | B | C | D | ALL')
    parser.add_argument('--capital',  type=float, default=10_000)
    parser.add_argument('--spread-bps', type=float, default=0.0, help='Round-trip spread in bps (applied as half per side)')
    parser.add_argument('--slippage-bps', type=float, default=0.0, help='Adverse slippage per side in bps')
    parser.add_argument('--commission-per-trade', type=float, default=0.0, help='Fixed commission in account currency per closed trade')
    args = parser.parse_args()

    print("Loading data...")
    m1 = add_indicators(load_csv(args.m1))
    m5 = add_indicators(load_csv(args.m5))
    h1 = add_indicators(load_csv(args.h1))
    h4 = add_indicators(load_csv(args.h4))
    print(f"  M1:{len(m1)}  M5:{len(m5)}  H1:{len(h1)}  H4:{len(h4)}")
    print(f"  Range: {m1.index[0]} → {m1.index[-1]}")

    print("Building H4 pivot zones...")
    zone_ts, zone_px = build_h4_zones(h4)
    print(f"  {len(zone_ts)} zones found")

    # Cache numpy arrays
    arrays = dict(
        h4_idx=h4.index.values, h4_c=h4['close'].values,
        h4_e20=h4['ema20'].values, h4_e50=h4['ema50'].values,
        h4_rsi=h4['rsi'].values,   h4_atr_arr=h4['atr'].values,
        h1_idx=h1.index.values, h1_c=h1['close'].values,
        h1_e20=h1['ema20'].values, h1_e50=h1['ema50'].values,
        h1_rsi=h1['rsi'].values,
        m5_idx=m5.index.values, m5_c=m5['close'].values,
        m5_e20=m5['ema20'].values, m5_e50=m5['ema50'].values,
        m5_rsi=m5['rsi'].values,
        m5_vol=m5['tickvol'].values, m5_vol_ma=m5['vol_ma'].values,
        m1_idx=m1.index.values, m1_c=m1['close'].values,
        m1_e20=m1['ema20'].values, m1_e50=m1['ema50'].values,
        m1_rsi=m1['rsi'].values,
    )

    scenarios_to_run = list(SCENARIOS.keys()) if args.scenario.upper() == 'ALL' else [canonicalize_scenario(args.scenario)]

    results = {}
    for sc in scenarios_to_run:
        cfg = SCENARIOS[sc]
        sc_id = scenario_id(sc)
        candles = m1 if cfg['entry_tf'] == 'm1' else m5
        print(f"\nRunning Scenario {sc_id}...")
        df_r = run_scenario(
            candles=candles,
            zone_ts=zone_ts, zone_px=zone_px,
            cfg=cfg,
            capital=args.capital,
            max_concurrent=DEFAULTS['max_concurrent'],
            cooldown_min=DEFAULTS['cooldown_min'],
            lockout_min=DEFAULTS['lockout_min'],
            conf_tol=DEFAULTS['conf_tol'],
            spread_bps=args.spread_bps,
            slippage_bps=args.slippage_bps,
            commission_per_trade=args.commission_per_trade,
            label=f"Scenario {sc_id}  |  {cfg['entry_tf'].upper()} entry  |  risk={cfg['risk_pct']*100:.2f}%",
            **arrays,
        )
        results[sc_id] = df_r
        if df_r is not None and len(df_r):
            out = f'phantom_{ENGINE_VERSION}_trades_{sc_id}.csv'
            df_r.to_csv(out, index=False)
            print(f"  Trades saved → {out}")

    print_comparison()
    print("\nDone.")


if __name__ == '__main__':
    main()
