#!/usr/bin/env python3
from __future__ import annotations

"""
PHANTOM v4.1 — Surgical fixes on V4 walk-forward engine
=========================================================

CHANGES FROM V4:
  FIX 1 — Remove stop_be entirely
    - Trades now run to full 2R target or stop loss only
    - No partial exit at 1R, no stop move to break-even
    - Rationale: stop_be was clipping winners at ~$10 avg while losses ran to ~$28
    - Expected impact: avg winner rises from $21 → ~$35+, R:R improves above 1.2:1

  FIX 2 — Enforce minimum R:R at entry
    - Skip trade if stop distance > entry_price * MAX_STOP_PCT
    - Ensures we only take trades where the math works before entry
    - Default: skip if stop > 0.35% of price (keeps stops tight on gold)

  FIX 3 — ATR volatility regime filter
    - Compute 14-period ATR and its 50-period rolling average
    - Only trade when current ATR >= ATR_REGIME_MULT * 50-bar ATR average
    - Rationale: W12 (0% WR, 7 trades) and other dead windows occur in
      low-volatility compression — the micro-trap signal has no edge there
    - Default: ATR must be >= 0.85x its 50-bar average (skip compressed markets)

  UNCHANGED:
    - All 5 entry layers (H1 EMA trend, micro-trap, volume, momentum, session)
    - Walk-forward engine (90d train / 30d test, 21 windows)
    - Local MT5 CSV data loader (no yfinance dependency)
    - Position sizing (BASE_RISK_PCT of capital)
    - MAX_CONCURRENT = 2
    - Daily loss circuit breaker
    - All reporting and charting

RUN COMMAND:
  python phantom_v4_1_backtest.py \
    --data /path/to/XAUUSD_M1_202404010105_202603302033.csv \
    --capital 10000 \
    --risk 0.003 \
    --skip-plots

WALK-FORWARD RUN (default, recommended):
  python phantom_v4_1_backtest.py \
    --data /Users/niko/Downloads/XAUUSD_M1_202404010105_202603302033.csv

SINGLE WINDOW TEST (last 30 days):
  python phantom_v4_1_backtest.py \
    --data /path/to/XAUUSD_M1.csv \
    --no-walkforward --days 30
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# CONFIGURATION
# ============================================================

# Capital & Risk
STARTING_CAPITAL     = 10_000.0
BASE_RISK_PCT        = 0.003       # 0.3% risk per trade

# Layer 2 — Micro Trap
SWING_LOOKBACK       = 10          # candles to define swing high/low
SWEEP_TICK_MIN       = 0.10        # min sweep beyond swing (USD)
SWEEP_TICK_MAX       = 20.0        # max sweep — larger = messy
WICK_RATIO_MIN       = 0.50        # wick must be >= 50% of candle range

# Layer 3 — Volume
VOLUME_ZSCORE_MIN    = 0.5         # volume z-score threshold

# Layer 5 — Session (UTC)
SESSION_START_UTC    = 7           # London open
SESSION_END_UTC      = 16          # NY afternoon

# Stop & Target — V4.1 CHANGES
ATR_PERIOD           = 14
ATR_STOP_MULT        = 0.8
FULL_EXIT_R          = 2.0         # single exit at 2R (no partial)

# FIX 1: No partial exit, no stop_be
PARTIAL_EXIT_ENABLED = False       # ← CHANGED from True in V4
MOVE_STOP_TO_BE      = False       # ← CHANGED from True in V4

# FIX 2: Minimum R:R enforcement at entry
MIN_RR_ENFORCE       = True
MAX_STOP_PCT         = 0.0035      # skip if stop > 0.35% of entry price
                                   # on gold ~$3000 this = $10.50 max stop

# FIX 3: ATR regime filter
ATR_REGIME_FILTER    = True
ATR_REGIME_PERIOD    = 50          # rolling average of ATR over 50 bars
ATR_REGIME_MULT      = 0.85        # current ATR must be >= 85% of 50-bar avg
                                   # skips dead/compressed low-vol markets

# Position limits
MAX_CONCURRENT       = 2
DAILY_LOSS_LIMIT_PCT = 0.02        # -2% daily circuit breaker

# Fees
FEE_PCT_PER_SIDE     = 0.00007    # 0.007% per side

# Walk-forward settings
TRAIN_DAYS           = 90
TEST_DAYS            = 30

# Adaptive risk multiplier (based on train window win rate)
ADAPTIVE_RISK        = True
ADAPTIVE_MULT_HIGH   = 1.0         # WR >= 55%: full risk
ADAPTIVE_MULT_MID    = 0.75        # WR 45-55%: reduced risk
ADAPTIVE_MULT_LOW    = 0.5         # WR < 45%: half risk

# H1 EMA
H1_EMA_PERIOD        = 21

# ============================================================
# ARGUMENT PARSER
# ============================================================

def parse_args():
    p = argparse.ArgumentParser(description="PHANTOM v4.1 XAUUSD 1M Walk-Forward Backtest")
    p.add_argument("--data",        type=str,   required=True,
                   help="Path to MT5 XAUUSD M1 CSV file")
    p.add_argument("--capital",     type=float, default=STARTING_CAPITAL)
    p.add_argument("--risk",        type=float, default=BASE_RISK_PCT,
                   help="Base risk per trade (0.003 = 0.3%%)")
    p.add_argument("--outdir",      type=str,   default="phantom_v4_1_output")
    p.add_argument("--skip-plots",  action="store_true")
    p.add_argument("--no-walkforward", action="store_true",
                   help="Run single window (last --days days) instead of walk-forward")
    p.add_argument("--days",        type=int,   default=30,
                   help="Days for single-window mode (ignored in walk-forward)")
    p.add_argument("--symbol",      type=str,   default="XAUUSD")
    return p.parse_args()

# ============================================================
# DATA LOADER — MT5 CSV FORMAT
# ============================================================

def load_mt5_csv(filepath: str) -> pd.DataFrame:
    """Load MT5 exported M1 CSV. Handles tab or comma delimiters."""
    print(f"\nLoading MT5 data: {filepath}")

    # Try tab first, then comma
    for sep in ['\t', ',']:
        try:
            df = pd.read_csv(filepath, sep=sep)
            if len(df.columns) >= 6:
                break
        except Exception:
            continue

    # Normalise column names
    df.columns = [c.strip().upper().replace('<', '').replace('>', '') for c in df.columns]

    col_map = {
        'DATE': 'date', 'TIME': 'time',
        'OPEN': 'open', 'HIGH': 'high', 'LOW': 'low', 'CLOSE': 'close',
        'TICKVOL': 'volume', 'VOL': 'volume2', 'SPREAD': 'spread'
    }
    df = df.rename(columns=col_map)

    # Build datetime index
    df['datetime'] = pd.to_datetime(df['date'] + ' ' + df['time'],
                                    format='%Y.%m.%d %H:%M:%S', utc=True)
    df = df.set_index('datetime').sort_index()

    # Use TICKVOL as volume proxy if VOL is all zeros
    if 'volume2' in df.columns and df.get('volume', pd.Series([0])).sum() == 0:
        df['volume'] = df['volume2']

    df = df[['open', 'high', 'low', 'close', 'volume']].dropna()
    df = df[~df.index.duplicated(keep='first')]

    print(f"  Loaded {len(df):,} 1M candles")
    print(f"  Range : {df.index[0].date()} → {df.index[-1].date()}")
    return df

# ============================================================
# INDICATORS
# ============================================================

def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df['high'], df['low'], df['close']
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def compute_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def resample_to_h1(df_1m: pd.DataFrame) -> pd.DataFrame:
    df_h1 = df_1m.resample('1h').agg({
        'open': 'first', 'high': 'max',
        'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()
    df_h1['ema21'] = compute_ema(df_h1['close'], H1_EMA_PERIOD)
    return df_h1

# ============================================================
# LAYER 2 — MICRO TRAP DETECTION
# ============================================================

def detect_trap(df: pd.DataFrame, i: int) -> dict | None:
    if i < SWING_LOOKBACK + 1:
        return None

    candle   = df.iloc[i]
    lookback = df.iloc[i - SWING_LOOKBACK: i]

    swing_low  = lookback['low'].min()
    swing_high = lookback['high'].max()

    candle_range = candle['high'] - candle['low']
    if candle_range < 1e-6:
        return None

    body_low  = min(candle['open'], candle['close'])
    body_high = max(candle['open'], candle['close'])

    # Bullish trap: wick sweeps below swing_low, body closes above it
    sweep_below = swing_low - candle['low']
    if (SWEEP_TICK_MIN <= sweep_below <= SWEEP_TICK_MAX
            and body_low >= swing_low
            and candle['close'] > candle['open']):
        wick_ratio = sweep_below / candle_range
        if wick_ratio >= WICK_RATIO_MIN:
            return {
                'direction': 'long',
                'trap_low':  candle['low'],
                'swing_ref': swing_low,
                'sweep':     sweep_below,
                'wick_ratio': wick_ratio,
            }

    # Bearish trap: wick sweeps above swing_high, body closes below it
    sweep_above = candle['high'] - swing_high
    if (SWEEP_TICK_MIN <= sweep_above <= SWEEP_TICK_MAX
            and body_high <= swing_high
            and candle['close'] < candle['open']):
        wick_ratio = sweep_above / candle_range
        if wick_ratio >= WICK_RATIO_MIN:
            return {
                'direction': 'short',
                'trap_high': candle['high'],
                'swing_ref': swing_high,
                'sweep':     sweep_above,
                'wick_ratio': wick_ratio,
            }

    return None

# ============================================================
# TRADE CLASS — V4.1: single exit at 2R, no stop_be
# ============================================================

class PhantomTrade:
    _id_counter = 0

    def __init__(self, direction, entry_price, entry_time, stop_loss,
                 target2, risk_usd, position_size):
        PhantomTrade._id_counter += 1
        self.trade_id      = PhantomTrade._id_counter
        self.direction     = direction
        self.entry_price   = entry_price
        self.entry_time    = entry_time
        self.stop_loss     = stop_loss
        self.target2       = target2       # single exit at 2R
        self.risk_usd      = risk_usd
        self.position_size = position_size
        self.remaining     = position_size
        self.status        = 'open'
        self.exit_price    = None
        self.exit_time     = None
        self.exit_reason   = None
        self.realised_pnl  = 0.0
        self.fees_paid     = 0.0

    def check_and_update(self, candle):
        """Returns list of (pnl, fee, reason) events. No partial, no stop_be."""
        events = []
        h, l = candle['high'], candle['low']

        if self.direction == 'long':
            if l <= self.stop_loss:
                pnl, fee = self._close(self.remaining, self.stop_loss)
                events.append((pnl, fee, 'stop_loss'))
            elif h >= self.target2:
                pnl, fee = self._close(self.remaining, self.target2)
                events.append((pnl, fee, 'full_2r'))
        else:
            if h >= self.stop_loss:
                pnl, fee = self._close(self.remaining, self.stop_loss)
                events.append((pnl, fee, 'stop_loss'))
            elif l <= self.target2:
                pnl, fee = self._close(self.remaining, self.target2)
                events.append((pnl, fee, 'full_2r'))

        return events

    def _close(self, qty, price):
        if self.direction == 'long':
            pnl = (price - self.entry_price) * qty
        else:
            pnl = (self.entry_price - price) * qty
        fee = (self.entry_price + price) * qty * FEE_PCT_PER_SIDE
        self.remaining    -= qty
        self.realised_pnl += pnl - fee
        self.fees_paid    += fee
        if self.remaining <= 1e-9:
            self.status     = 'closed'
            self.exit_price = price
        return pnl, fee

    def force_close(self, price, time, reason='end_of_data'):
        pnl, fee = self._close(self.remaining, price)
        self.exit_time   = time
        self.exit_reason = reason
        return pnl, fee

# ============================================================
# SINGLE WINDOW BACKTEST ENGINE
# ============================================================

def run_window(df_1m: pd.DataFrame, df_h1: pd.DataFrame,
               starting_capital: float, risk_pct: float) -> tuple:
    """
    Run backtest on a single data window.
    Returns (closed_trades, equity_curve, skip_reasons, final_capital, total_fees)
    """
    df_1m = df_1m.copy()
    df_1m['atr']       = compute_atr(df_1m, ATR_PERIOD)
    df_1m['vol_ma20']  = df_1m['volume'].rolling(20).mean()
    df_1m['vol_std20'] = df_1m['volume'].rolling(20).std()
    df_1m['hour_utc']  = df_1m.index.hour

    # FIX 3: ATR regime — rolling 50-bar average of ATR
    df_1m['atr_avg50'] = df_1m['atr'].rolling(ATR_REGIME_PERIOD).mean()

    h1_ema_series = df_h1['ema21']

    def get_h1_ema(ts):
        idx = h1_ema_series.index.searchsorted(ts, side='right') - 1
        if idx < 0:
            return None
        return h1_ema_series.iloc[idx]

    capital       = starting_capital
    peak_capital  = capital
    day_start_cap = capital
    current_day   = None
    day_halted    = False

    open_trades   = []
    closed_trades = []
    equity_curve  = []
    skip_reasons  = defaultdict(int)
    total_fees    = 0.0

    PhantomTrade._id_counter = 0

    for i in range(max(SWING_LOOKBACK + 2, ATR_REGIME_PERIOD + 1), len(df_1m)):
        candle = df_1m.iloc[i]
        ts     = df_1m.index[i]
        close  = candle['close']

        # Daily reset
        day = ts.date()
        if day != current_day:
            current_day   = day
            day_start_cap = capital
            day_halted    = False

        # Process exits
        trades_to_close = []
        for trade in open_trades:
            events = trade.check_and_update(candle)
            for pnl, fee, reason in events:
                capital      += pnl - fee
                total_fees   += fee
                trade.exit_time   = ts
                trade.exit_reason = reason
                trades_to_close.append(trade)
        for t in trades_to_close:
            open_trades.remove(t)
            closed_trades.append(t)

        equity_curve.append({'ts': ts, 'equity': capital})
        if capital > peak_capital:
            peak_capital = capital

        # Daily circuit breaker
        if (capital - day_start_cap) / day_start_cap <= -DAILY_LOSS_LIMIT_PCT:
            day_halted = True
        if day_halted:
            skip_reasons['daily_loss_limit'] += 1
            continue

        # Layer 5: Session gate
        hour = candle['hour_utc']
        if not (SESSION_START_UTC <= hour < SESSION_END_UTC):
            skip_reasons['outside_session'] += 1
            continue

        # Max concurrent
        if len(open_trades) >= MAX_CONCURRENT:
            skip_reasons['max_concurrent'] += 1
            continue

        # FIX 3: ATR regime filter
        if ATR_REGIME_FILTER:
            atr_now = candle['atr']
            atr_avg = candle['atr_avg50']
            if pd.isna(atr_avg) or atr_avg == 0:
                skip_reasons['no_atr_avg'] += 1
                continue
            if atr_now < ATR_REGIME_MULT * atr_avg:
                skip_reasons['low_volatility_regime'] += 1
                continue

        # Layer 2: Micro trap
        trap = detect_trap(df_1m, i)
        if trap is None:
            skip_reasons['no_micro_trap'] += 1
            continue

        direction = trap['direction']

        # Layer 1: H1 EMA trend bias
        h1_ema = get_h1_ema(ts)
        if h1_ema is None:
            skip_reasons['no_h1_ema'] += 1
            continue
        if direction == 'long'  and close < h1_ema:
            skip_reasons['counter_trend'] += 1
            continue
        if direction == 'short' and close > h1_ema:
            skip_reasons['counter_trend'] += 1
            continue

        # Layer 3: Volume z-score
        vol_ma  = candle['vol_ma20']
        vol_std = candle['vol_std20']
        if pd.isna(vol_ma) or vol_ma == 0:
            skip_reasons['volume_fail'] += 1
            continue
        vol_zscore = (candle['volume'] - vol_ma) / (vol_std + 1e-9)
        if vol_zscore < VOLUME_ZSCORE_MIN:
            skip_reasons['volume_fail'] += 1
            continue

        # Layer 4: Momentum confirmation (next candle)
        if i + 1 >= len(df_1m):
            skip_reasons['no_next_candle'] += 1
            continue
        next_candle = df_1m.iloc[i + 1]
        if direction == 'long'  and next_candle['close'] <= next_candle['open']:
            skip_reasons['momentum_fail'] += 1
            continue
        if direction == 'short' and next_candle['close'] >= next_candle['open']:
            skip_reasons['momentum_fail'] += 1
            continue

        # Calculate entry
        entry_price = next_candle['open']
        entry_time  = df_1m.index[i + 1]
        atr         = candle['atr']
        if pd.isna(atr) or atr == 0:
            skip_reasons['no_atr'] += 1
            continue

        if direction == 'long':
            stop_loss  = trap['trap_low'] - atr * ATR_STOP_MULT
            risk_price = entry_price - stop_loss
        else:
            stop_loss  = trap['trap_high'] + atr * ATR_STOP_MULT
            risk_price = stop_loss - entry_price

        if risk_price <= 0:
            skip_reasons['invalid_risk'] += 1
            continue

        # FIX 2: Enforce minimum R:R — skip if stop is too wide
        if MIN_RR_ENFORCE:
            stop_pct = risk_price / entry_price
            if stop_pct > MAX_STOP_PCT:
                skip_reasons['stop_too_wide'] += 1
                continue

        # Position sizing
        risk_usd      = capital * risk_pct
        position_size = risk_usd / risk_price

        # Single target at 2R
        if direction == 'long':
            target2 = entry_price + risk_price * FULL_EXIT_R
        else:
            target2 = entry_price - risk_price * FULL_EXIT_R

        # Entry fee
        entry_fee  = entry_price * position_size * FEE_PCT_PER_SIDE
        capital   -= entry_fee
        total_fees += entry_fee

        trade = PhantomTrade(
            direction     = direction,
            entry_price   = entry_price,
            entry_time    = entry_time,
            stop_loss     = stop_loss,
            target2       = target2,
            risk_usd      = risk_usd,
            position_size = position_size,
        )
        open_trades.append(trade)

    # Force-close remaining
    final_price = df_1m.iloc[-1]['close']
    final_time  = df_1m.index[-1]
    for trade in open_trades:
        pnl, fee = trade.force_close(final_price, final_time, 'end_of_data')
        capital    += pnl - fee
        total_fees += fee
        closed_trades.append(trade)

    return closed_trades, equity_curve, skip_reasons, capital, total_fees

# ============================================================
# WALK-FORWARD ENGINE
# ============================================================

def run_walkforward(df_full: pd.DataFrame, starting_capital: float,
                    base_risk_pct: float, outdir: str, skip_plots: bool,
                    symbol: str):
    """
    Walk-forward: 90d train → 30d test, rolling by 30d.
    Train window determines adaptive risk multiplier.
    """
    print("\n" + "="*70)
    print("  PHANTOM v4.1 — WALK-FORWARD BACKTEST")
    print("="*70)
    print(f"  Train: {TRAIN_DAYS}d  |  Test: {TEST_DAYS}d  |  Symbol: {symbol}")
    print(f"  Capital: ${starting_capital:,.0f}  |  Base risk: {base_risk_pct*100:.2f}%")
    print(f"  Fixes: no_stop_be=True | min_rr={MAX_STOP_PCT*100:.2f}% | atr_regime={ATR_REGIME_FILTER}")

    df_full = df_full.copy()
    start_dt = df_full.index[0]
    end_dt   = df_full.index[-1]

    # Build window list
    windows = []
    window_start = start_dt + timedelta(days=TRAIN_DAYS)
    while window_start + timedelta(days=TEST_DAYS) <= end_dt:
        train_start = window_start - timedelta(days=TRAIN_DAYS)
        test_end    = window_start + timedelta(days=TEST_DAYS)
        windows.append((train_start, window_start, test_end))
        window_start += timedelta(days=TEST_DAYS)

    print(f"  Windows: {len(windows)}\n")

    capital       = starting_capital
    all_trades    = []
    window_stats  = []
    equity_curve  = [{'ts': df_full.index[0], 'equity': capital}]

    for w_idx, (train_start, test_start, test_end) in enumerate(windows):
        # Slice data
        df_train = df_full[(df_full.index >= train_start) & (df_full.index < test_start)]
        df_test  = df_full[(df_full.index >= test_start)  & (df_full.index < test_end)]

        if len(df_train) < 1000 or len(df_test) < 100:
            continue

        # Train window: compute win rate to set adaptive risk
        if ADAPTIVE_RISK:
            df_h1_train = resample_to_h1(df_train)
            train_trades, _, _, _, _ = run_window(
                df_train, df_h1_train, capital, base_risk_pct
            )
            train_wr = (sum(1 for t in train_trades if t.realised_pnl > 0)
                        / max(len(train_trades), 1) * 100)

            if train_wr >= 55:
                adaptive_mult = ADAPTIVE_MULT_HIGH
            elif train_wr >= 45:
                adaptive_mult = ADAPTIVE_MULT_MID
            else:
                adaptive_mult = ADAPTIVE_MULT_LOW
        else:
            train_wr      = 0
            adaptive_mult = 1.0

        effective_risk = base_risk_pct * adaptive_mult

        # Test window
        df_h1_test = resample_to_h1(df_test)
        trades, eq_curve, skip_reasons, final_cap, fees = run_window(
            df_test, df_h1_test, capital, effective_risk
        )

        # Window stats
        n = len(trades)
        wins = sum(1 for t in trades if t.realised_pnl > 0)
        wr   = wins / n * 100 if n > 0 else 0
        net_pnl = final_cap - capital
        gross_profit = sum(t.realised_pnl for t in trades if t.realised_pnl > 0)
        gross_loss   = abs(sum(t.realised_pnl for t in trades if t.realised_pnl <= 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else (1.0 if gross_profit > 0 else 0.0)
        exp = net_pnl / n if n > 0 else 0
        ret_pct = net_pnl / capital * 100

        # Max DD in window
        eq_vals = [e['equity'] for e in eq_curve]
        peak = capital
        max_dd = 0.0
        for v in eq_vals:
            if v > peak:
                peak = v
            dd = (v - peak) / peak * 100
            if dd < max_dd:
                max_dd = dd

        # Degraded: WR < 35% OR PF < 0.5
        degraded = wr < 35 or pf < 0.5

        window_stats.append({
            'window':        w_idx + 1,
            'test_start':    test_start.date(),
            'test_end':      test_end.date(),
            'trades':        n,
            'win_rate':      round(wr, 1),
            'profit_factor': round(pf, 2),
            'net_pnl':       round(net_pnl, 2),
            'total_fees':    round(fees, 2),
            'expectancy':    round(exp, 2),
            'return_pct':    round(ret_pct, 2),
            'max_dd_pct':    round(max_dd, 2),
            'train_wr':      round(train_wr, 1),
            'adaptive_mult': adaptive_mult,
            'degraded':      degraded,
            'capital_start': round(capital, 2),
            'capital_end':   round(final_cap, 2),
        })

        for t in trades:
            t.window = w_idx + 1
        all_trades.extend(trades)
        equity_curve.extend(eq_curve)
        capital = final_cap

        status = "⚠ DEGRADED" if degraded else "✓"
        print(f"  W{w_idx+1:02d} [{test_start.date()} → {test_end.date()}] "
              f"T:{n:3d} WR:{wr:5.1f}% PF:{pf:.2f} "
              f"PnL:${net_pnl:+8.2f} DD:{max_dd:.1f}% "
              f"Risk:{effective_risk*100:.2f}% {status}")

    return all_trades, equity_curve, window_stats, capital

# ============================================================
# REPORTING
# ============================================================

def build_report(all_trades, window_stats, equity_curve,
                 starting_capital, final_capital, symbol,
                 outdir, skip_plots, base_risk_pct):

    os.makedirs(outdir, exist_ok=True)

    n = len(all_trades)
    wins   = [t for t in all_trades if t.realised_pnl > 0]
    losses = [t for t in all_trades if t.realised_pnl <= 0]
    n_win  = len(wins)
    n_loss = len(losses)
    wr     = n_win / n * 100 if n > 0 else 0

    avg_win  = np.mean([t.realised_pnl for t in wins])   if wins   else 0
    avg_loss = np.mean([t.realised_pnl for t in losses]) if losses else 0
    gross_profit = sum(t.realised_pnl for t in wins)
    gross_loss   = abs(sum(t.realised_pnl for t in losses))
    pf           = gross_profit / gross_loss if gross_loss > 0 else 0
    net_pnl      = final_capital - starting_capital
    ret_pct      = net_pnl / starting_capital * 100
    expectancy   = np.mean([t.realised_pnl for t in all_trades]) if all_trades else 0
    total_fees   = sum(t.fees_paid for t in all_trades)

    # R:R ratio
    rr_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    be_wr    = abs(avg_loss) / (avg_win + abs(avg_loss)) * 100 if (avg_win + abs(avg_loss)) > 0 else 0

    # Drawdown
    eq_vals = [e['equity'] for e in equity_curve]
    peak = starting_capital
    max_dd = 0.0
    for v in eq_vals:
        if v > peak:
            peak = v
        dd = (v - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd

    # Degraded windows
    ws_df = pd.DataFrame(window_stats)
    n_degraded = ws_df['degraded'].sum() if len(ws_df) > 0 else 0
    pct_degraded = n_degraded / len(ws_df) * 100 if len(ws_df) > 0 else 0

    print("\n" + "="*70)
    print("  PHANTOM v4.1 — OVERALL RESULTS")
    print("="*70)
    print(f"\n  Symbol          : {symbol}")
    print(f"  Starting capital: ${starting_capital:>12,.2f}")
    print(f"  Final capital   : ${final_capital:>12,.2f}")
    print(f"  Net P&L         : ${net_pnl:>+12,.2f}  ({ret_pct:+.2f}%)")
    print(f"  Total fees      : ${total_fees:>12,.2f}")
    print(f"\n  Total trades    : {n}")
    print(f"  Win rate        : {wr:.1f}%")
    print(f"  Avg winner      : ${avg_win:>+10,.2f}")
    print(f"  Avg loser       : ${avg_loss:>+10,.2f}")
    print(f"  Reward:Risk     : {rr_ratio:.2f}:1")
    print(f"  Break-even WR   : {be_wr:.1f}%  (actual: {wr:.1f}%)")
    print(f"  Profit factor   : {pf:.3f}")
    print(f"  Expectancy/trade: ${expectancy:>+10,.2f}")
    print(f"  Max drawdown    : {max_dd:.2f}%")
    print(f"\n  Windows tested  : {len(ws_df)}")
    print(f"  Degraded windows: {n_degraded} ({pct_degraded:.0f}%)")

    # Exit reasons
    exit_reasons = defaultdict(int)
    for t in all_trades:
        exit_reasons[t.exit_reason] += 1
    print(f"\n  Exit reasons:")
    for r, c in sorted(exit_reasons.items(), key=lambda x: -x[1]):
        print(f"    {r:<25}: {c}")

    # Save trades CSV
    rows = []
    for t in all_trades:
        rows.append({
            'direction':   t.direction,
            'entry_time':  t.entry_time,
            'entry_price': t.entry_price,
            'exit_time':   t.exit_time,
            'exit_price':  t.exit_price,
            'exit_reason': t.exit_reason,
            'qty':         t.position_size,
            'pnl':         t.realised_pnl,
            'fees':        t.fees_paid,
            'win':         t.realised_pnl > 0,
            'window':      getattr(t, 'window', 0),
        })
    trade_df = pd.DataFrame(rows)
    csv_path = os.path.join(outdir, "phantom_v4_1_trades.csv")
    trade_df.to_csv(csv_path, index=False)
    print(f"\n  Trades saved    : {csv_path}")

    # Save windows CSV
    if len(ws_df) > 0:
        wcsv = os.path.join(outdir, "phantom_v4_1_windows.csv")
        ws_df.to_csv(wcsv, index=False)
        print(f"  Windows saved   : {wcsv}")

    # Save markdown report
    report_lines = [
        f"# PHANTOM v4.1 Walk-Forward Report\n",
        f"- Data: {symbol} 1M",
        f"- Train/Test: {TRAIN_DAYS}d / {TEST_DAYS}d",
        f"- Capital: ${starting_capital:,.2f}",
        f"- Base risk: {base_risk_pct*100:.2f}%",
        f"- **FIX 1**: No stop_be — single exit at 2R or stop",
        f"- **FIX 2**: Max stop size: {MAX_STOP_PCT*100:.2f}% of entry price",
        f"- **FIX 3**: ATR regime filter: ATR >= {ATR_REGIME_MULT}x 50-bar ATR avg\n",
        f"## Overall Results\n",
        f"- total_trades: {n}",
        f"- win_rate: {wr:.1f}%",
        f"- avg_winner: ${avg_win:.2f}",
        f"- avg_loser: ${avg_loss:.2f}",
        f"- reward_risk: {rr_ratio:.2f}:1",
        f"- breakeven_wr_needed: {be_wr:.1f}%",
        f"- profit_factor: {pf:.2f}",
        f"- expectancy: ${expectancy:.2f}",
        f"- total_fees: ${total_fees:.2f}",
        f"- total_return: {ret_pct:.2f}%",
        f"- final_capital: ${final_capital:.2f}",
        f"- max_drawdown: {max_dd:.2f}%",
        f"- windows_tested: {len(ws_df)}",
        f"- windows_degraded: {pct_degraded:.0f}%\n",
        f"## Per-Window Results\n",
        f"| Window | Period | Trades | WR% | PF | PnL | DD% | Degraded |",
        f"|----|----|----|----|----|----|----|----|",
    ]
    for row in window_stats:
        flag = "⚠" if row['degraded'] else "✓"
        pnl_str = f"${row['net_pnl']:+.2f}"
        report_lines.append(
            f"| {row['window']} | {row['test_start']} → {row['test_end']} "
            f"| {row['trades']} | {row['win_rate']} | {row['profit_factor']} "
            f"| {pnl_str} | {row['max_dd_pct']}% | {flag} |"
        )

    report_lines += [
        f"\n## Hyperparameters\n",
        f"- SWING_LOOKBACK: {SWING_LOOKBACK}",
        f"- WICK_RATIO_MIN: {WICK_RATIO_MIN}",
        f"- VOLUME_ZSCORE_MIN: {VOLUME_ZSCORE_MIN}",
        f"- ATR_STOP_MULT: {ATR_STOP_MULT}",
        f"- FULL_EXIT_R: {FULL_EXIT_R}",
        f"- PARTIAL_EXIT_ENABLED: {PARTIAL_EXIT_ENABLED}  ← V4.1 fix",
        f"- MOVE_STOP_TO_BE: {MOVE_STOP_TO_BE}  ← V4.1 fix",
        f"- MAX_STOP_PCT: {MAX_STOP_PCT}  ← V4.1 fix",
        f"- ATR_REGIME_FILTER: {ATR_REGIME_FILTER}  ← V4.1 fix",
        f"- ATR_REGIME_MULT: {ATR_REGIME_MULT}",
        f"- ATR_REGIME_PERIOD: {ATR_REGIME_PERIOD}",
        f"- BASE_RISK_PCT: {base_risk_pct}",
        f"- MAX_CONCURRENT: {MAX_CONCURRENT}",
        f"- FEE_PCT_PER_SIDE: {FEE_PCT_PER_SIDE}",
        f"- SESSION_START_UTC: {SESSION_START_UTC}",
        f"- SESSION_END_UTC: {SESSION_END_UTC}",
    ]

    report_path = os.path.join(outdir, "phantom_v4_1_report.md")
    with open(report_path, 'w') as f:
        f.write('\n'.join(report_lines))
    print(f"  Report saved    : {report_path}")

    # ---- Plots ----
    if not skip_plots and len(all_trades) > 0:
        _plot_results(all_trades, equity_curve, window_stats,
                      starting_capital, outdir, symbol, wr, pf, max_dd)

    return {
        'n_trades': n, 'win_rate': wr, 'profit_factor': pf,
        'expectancy': expectancy, 'net_pnl': net_pnl,
        'return_pct': ret_pct, 'max_drawdown': max_dd,
        'rr_ratio': rr_ratio, 'be_wr': be_wr,
    }

def _plot_results(all_trades, equity_curve, window_stats,
                  starting_capital, outdir, symbol, wr, pf, max_dd):
    eq_df = pd.DataFrame(equity_curve).set_index('ts')
    eq_df['peak'] = eq_df['equity'].cummax()
    eq_df['dd']   = (eq_df['equity'] - eq_df['peak']) / eq_df['peak'] * 100

    ws_df = pd.DataFrame(window_stats)
    trade_df = pd.DataFrame([{
        'pnl': t.realised_pnl,
        'win': t.realised_pnl > 0,
        'exit_reason': t.exit_reason,
    } for t in all_trades])

    fig = plt.figure(figsize=(20, 16))
    fig.suptitle(f"PHANTOM v4.1 — {symbol} Walk-Forward Results\n"
                 f"WR: {wr:.1f}%  |  PF: {pf:.2f}  |  Max DD: {max_dd:.1f}%",
                 fontsize=14, fontweight='bold')

    # 1. Equity curve
    ax1 = fig.add_subplot(3, 2, 1)
    colors_eq = ['green' if not ws_df.empty and
                 any(ws_df['degraded'].values) else 'blue']
    ax1.plot(eq_df.index, eq_df['equity'], color='#2E86AB', lw=1.2)
    ax1.axhline(starting_capital, color='gray', ls='--', alpha=0.5)
    ax1.fill_between(eq_df.index, starting_capital, eq_df['equity'],
                     where=eq_df['equity'] >= starting_capital, alpha=0.15, color='green')
    ax1.fill_between(eq_df.index, starting_capital, eq_df['equity'],
                     where=eq_df['equity'] < starting_capital, alpha=0.15, color='red')
    ax1.set_title('Walk-Forward Equity (green=OK, red=degraded window)')
    ax1.set_ylabel('Capital ($)')
    ax1.grid(alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax1.tick_params(axis='x', rotation=30)

    # Shade degraded windows
    if len(ws_df) > 0:
        for _, row in ws_df.iterrows():
            color = 'red' if row['degraded'] else 'green'
            try:
                ax1.axvspan(pd.Timestamp(row['test_start']),
                            pd.Timestamp(row['test_end']),
                            alpha=0.06, color=color)
            except Exception:
                pass

    # 2. Per-window WR & PF
    ax2 = fig.add_subplot(3, 2, 2)
    if len(ws_df) > 0:
        x = range(len(ws_df))
        bar_colors = ['#D85A30' if d else '#1D9E75' for d in ws_df['degraded']]
        ax2.bar(x, ws_df['win_rate'], color=bar_colors, alpha=0.8, label='Win Rate %')
        ax2_r = ax2.twinx()
        ax2_r.plot(x, ws_df['profit_factor'], 'o-', color='orange',
                   lw=1.5, ms=5, label='Profit Factor')
        ax2.axhline(40, color='orange', ls='--', alpha=0.5, lw=1)
        ax2.axhline(50, color='green',  ls=':', alpha=0.4, lw=1)
        ax2.set_title('Per-Window Win Rate & Profit Factor')
        ax2.set_ylabel('Win Rate (%)')
        ax2_r.set_ylabel('Profit Factor')
        ax2.set_xticks(list(x))
        ax2.set_xticklabels([str(d)[:7] for d in ws_df['test_start']],
                             rotation=45, fontsize=7)

    # 3. Trade PnL bars
    ax3 = fig.add_subplot(3, 1, 2)
    if len(trade_df) > 0:
        colors = ['#1D9E75' if w else '#D85A30' for w in trade_df['win']]
        ax3.bar(range(len(trade_df)), trade_df['pnl'], color=colors, alpha=0.7)
        ax3.axhline(0, color='black', lw=0.8)
        ax3.set_title('Trade PnL (all out-of-sample windows)')
        ax3.set_xlabel('Trade #')
        ax3.set_ylabel('PnL ($)')
        ax3.grid(alpha=0.3, axis='y')

    # 4. Drawdown
    ax4 = fig.add_subplot(3, 2, 5)
    ax4.fill_between(eq_df.index, 0, eq_df['dd'], color='red', alpha=0.4)
    ax4.plot(eq_df.index, eq_df['dd'], color='darkred', lw=0.8)
    ax4.set_title(f'Drawdown (Max: {max_dd:.1f}%)')
    ax4.set_ylabel('DD %')
    ax4.grid(alpha=0.3)
    ax4.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax4.tick_params(axis='x', rotation=30)

    # 5. Exit reason
    ax5 = fig.add_subplot(3, 2, 6)
    if len(trade_df) > 0:
        er = trade_df['exit_reason'].value_counts()
        bar_c = ['#1D9E75' if 'target' in l or '2r' in l else '#D85A30'
                 for l in er.index]
        ax5.barh(er.index, er.values, color=bar_c, alpha=0.8)
        ax5.set_title('Exit Reason Breakdown')
        ax5.set_xlabel('Count')
        ax5.grid(alpha=0.3, axis='x')

    plt.tight_layout()
    plot_path = os.path.join(outdir, "phantom_v4_1_results.png")
    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Chart saved     : {plot_path}")

    # Heatmap
    if len(ws_df) >= 3:
        try:
            metrics = ['win_rate', 'profit_factor', 'return_pct', 'max_dd_pct', 'trades']
            hm_data = ws_df[metrics].T
            hm_data.columns = [f"W{i+1:02d}\n{str(r['test_start'])[:7]}"
                                for i, r in ws_df.iterrows()]
            fig2, ax = plt.subplots(figsize=(max(14, len(ws_df)*0.7), 5))
            import seaborn as sns
            sns.heatmap(hm_data.astype(float), annot=True, fmt='.1f',
                        cmap='RdYlGn', ax=ax, linewidths=0.5,
                        cbar_kws={'label': 'Value'})
            ax.set_title('PHANTOM v4.1 — Window Metrics Heatmap')
            plt.tight_layout()
            hm_path = os.path.join(outdir, "phantom_v4_1_heatmap.png")
            plt.savefig(hm_path, dpi=130, bbox_inches='tight')
            plt.close()
            print(f"  Heatmap saved   : {hm_path}")
        except Exception as e:
            print(f"  Heatmap skipped : {e}")

# ============================================================
# MAIN
# ============================================================

def main():
    args = parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    # Load data
    df_full = load_mt5_csv(args.data)

    if args.no_walkforward:
        # Single window mode
        cutoff = df_full.index[-1] - timedelta(days=args.days)
        df_test = df_full[df_full.index >= cutoff]
        df_h1   = resample_to_h1(df_test)
        print(f"\nSingle window mode: last {args.days} days")
        trades, eq_curve, skip_reasons, final_cap, fees = run_window(
            df_test, df_h1, args.capital, args.risk
        )
        print(f"\n  Trades: {len(trades)}")
        print(f"  WR: {sum(1 for t in trades if t.realised_pnl > 0)/max(len(trades),1)*100:.1f}%")
        print(f"  Net PnL: ${final_cap - args.capital:+.2f}")
        print(f"  Fees: ${fees:.2f}")
        print(f"\n  Skip reasons:")
        for r, c in sorted(skip_reasons.items(), key=lambda x: -x[1]):
            print(f"    {r:<30}: {c:,}")
    else:
        # Walk-forward mode
        all_trades, equity_curve, window_stats, final_capital = run_walkforward(
            df_full          = df_full,
            starting_capital = args.capital,
            base_risk_pct    = args.risk,
            outdir           = args.outdir,
            skip_plots       = args.skip_plots,
            symbol           = args.symbol,
        )

        build_report(
            all_trades       = all_trades,
            window_stats     = window_stats,
            equity_curve     = equity_curve,
            starting_capital = args.capital,
            final_capital    = final_capital,
            symbol           = args.symbol,
            outdir           = args.outdir,
            skip_plots       = args.skip_plots,
            base_risk_pct    = args.risk,
        )

    print("\n" + "="*70)
    print("  PHANTOM v4.1 COMPLETE")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
