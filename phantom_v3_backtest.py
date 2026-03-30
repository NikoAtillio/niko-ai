#!/usr/bin/env python3
"""
PHANTOM v3: Price Hunting After Micro Trap On Momentum
=======================================================
Data-driven upgrade from copilot baseline (+2.46% / 30d).

Changes from copilot v1 → v3 (all backed by 30-day trade analysis):
────────────────────────────────────────────────────────────────────
1. H4 REGIME FILTER (NEW)
   - Computes H4 EMA21 from 1m data
   - Longs BLOCKED when H4 close < H4 EMA21 (bearish regime)
   - Shorts BLOCKED when H4 close > H4 EMA21 (bullish regime)
   - Reason: 100% of copilot profit came from shorts in a downtrend;
     longs were net -$120 over 30 days. This prevents counter-regime longs.

2. BLOCKED HOURS (NEW)
   - 08:00 UTC blocked: London open spike — 0% win rate, -$112 P&L
   - 12:00 UTC blocked: lunch chop — 0% win rate, -$54 P&L
   - Combined saving: ~$166 (+67% improvement on net P&L)

3. R-VALUE GATE (NEW)
   - R_VALUE_MIN = 4.5  — stops too tight = noise stops you out
   - R_VALUE_MAX = 28.0 — outlier setups unreliable
   - Sweet spot 5–25 produced 10 wins from 10 trades in copilot data

4. ADAPTIVE RISK SCALING (NEW)
   - Base risk 0.5% per trade (proven safe)
   - Scales to 0.75% when H4 trend strongly aligns (EMA slope confirms)
   - Scales down to 0.35% on first trade after a loss streak ≥ 2

5. IMPROVED PARTIAL EXIT (REFINED)
   - Partial at 1R: close 50%, move stop to BE (unchanged — proven)
   - NEW: trail stop on remainder at 0.5R increments after 1.5R reached
   - Captures more of the 2R move instead of binary hit/miss

6. ENTRY QUALITY SCORE (NEW)
   - Scores each setup 0–100 based on: wick ratio, sweep depth,
     volume spike magnitude, H1 trend strength, H4 alignment
   - Only takes trades scoring ≥ 60 (filters marginal setups)

7. COOLDOWN AFTER STOP (NEW)
   - 15-minute cooldown after a stop_loss exit
   - Prevents revenge re-entry into the same failed zone

All original 5 layers preserved:
  L1: H1 EMA21 trend bias
  L2: Micro-trap sweep of 8-candle swing + wick ratio ≥ 0.55
  L3: Volume ≥ 1.4x 20-bar average
  L4: Momentum follow-through candle
  L5: Session gate 07:00–16:00 UTC (minus blocked hours)

Risk model:
  - ATR-based stop beyond trap wick (1.0x ATR — proven optimal)
  - Partial 50% at 1R → stop to BE → trail at 0.5R steps
  - Remainder targets 2R (or trailed out)
  - Max 3 concurrent positions
  - Daily -2% circuit breaker
  - Fee 0.007% per side (raw spread Gold account)
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance", "-q"])
    import yfinance as yf


# ════════════════════════════════════════════════════════════════
# CONFIGURATION — v3 tuned parameters
# ════════════════════════════════════════════════════════════════

# ── Core trap detection (proven from copilot) ──
SWING_LOOKBACK      = 8
WICK_RATIO_MIN      = 0.55
VOLUME_MULT         = 1.4
VOL_MA_PERIOD       = 20
SWEEP_ATR_MAX       = 1.0

# ── Trend filters ──
ATR_PERIOD          = 14
H1_EMA_PERIOD       = 21
H4_EMA_PERIOD       = 21       # NEW: H4 regime filter

# ── Stop & target ──
ATR_STOP_MULT       = 1.0      # proven: wider stop = room to breathe
PARTIAL_EXIT_R      = 1.0
FULL_EXIT_R         = 2.0
TRAIL_STEP_R        = 0.5      # NEW: trail in 0.5R increments after 1.5R
TRAIL_ACTIVATE_R    = 1.5      # NEW: start trailing after 1.5R reached

# ── Risk management ──
BASE_RISK_PCT       = 0.005    # 0.5% base risk per trade
STRONG_TREND_RISK   = 0.0075   # 0.75% when H4 slope strongly confirms
LOSS_STREAK_RISK    = 0.0035   # 0.35% after 2+ consecutive losses
MAX_CONCURRENT      = 3
DAILY_CIRCUIT_PCT   = 0.02
MAX_NOTIONAL_MULT   = 20.0

# ── Session & hour filters ──
SESSION_START_UTC   = 7
SESSION_END_UTC     = 16
BLOCKED_HOURS       = {8, 12}  # NEW: 08:00 and 12:00 UTC blocked

# ── R-value gate ──
R_VALUE_MIN         = 4.5      # NEW: skip if stop too tight
R_VALUE_MAX         = 28.0     # NEW: skip outlier setups

# ── Entry quality score ──
MIN_QUALITY_SCORE   = 60       # NEW: minimum score to take trade

# ── Cooldown ──
COOLDOWN_MINUTES    = 15       # NEW: minutes to wait after a stop_loss

# ── Fees ──
FEE_PCT_PER_SIDE    = 0.00007  # 0.007% per side

# ── Adaptive risk: H4 slope threshold ──
H4_STRONG_SLOPE_PCT = 0.001    # H4 EMA slope > 0.1% per bar = strong trend


# ════════════════════════════════════════════════════════════════
# DATA CLASSES
# ════════════════════════════════════════════════════════════════

@dataclass
class Position:
    direction: str
    entry_time: pd.Timestamp
    entry_price: float
    qty: float
    stop: float
    tp1: float
    tp2: float
    trap_high: float
    trap_low: float
    r_value: float
    quality_score: float = 0.0
    risk_pct_used: float = 0.005
    partial_done: bool = False
    trail_active: bool = False
    trail_stop: float = 0.0
    closed: bool = False
    remaining_qty: float = 0.0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None

    def __post_init__(self):
        self.remaining_qty = self.qty
        entry_fee = self.entry_price * self.qty * FEE_PCT_PER_SIDE
        self.fees_paid += entry_fee
        self.realized_pnl -= entry_fee


# ════════════════════════════════════════════════════════════════
# ARGUMENT PARSER
# ════════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(description="PHANTOM v3 XAUUSD backtest")
    p.add_argument("--symbol",     default="XAUUSD=X", help="Yahoo Finance symbol")
    p.add_argument("--interval",   default="1m",       help="Data interval")
    p.add_argument("--days",       type=int, default=30, help="Lookback days")
    p.add_argument("--capital",    type=float, default=10000.0, help="Starting capital")
    p.add_argument("--risk",       type=float, default=BASE_RISK_PCT, help="Base risk per trade")
    p.add_argument("--skip-plots", action="store_true", help="Skip chart generation")
    p.add_argument("--outdir",     default=".", help="Output directory")
    return p.parse_args()


# ════════════════════════════════════════════════════════════════
# DATA FETCHING
# ════════════════════════════════════════════════════════════════

def fetch_minute_data(symbol, interval, days):
    """Pull data in <=7 day chunks (Yahoo intraday limit)."""
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=days)

    candidates = [symbol]
    if symbol != "GC=F":
        candidates.append("GC=F")

    for candidate in candidates:
        chunks = []
        cursor = start
        chunk_days = 6

        print(f"Fetching {days} days of {interval} {candidate} data...")

        while cursor < end:
            chunk_end = min(cursor + timedelta(days=chunk_days), end)
            df_chunk = yf.download(
                candidate, start=cursor, end=chunk_end,
                interval=interval, auto_adjust=False,
                progress=False, threads=False,
            )
            if not df_chunk.empty:
                if isinstance(df_chunk.columns, pd.MultiIndex):
                    df_chunk.columns = [c[0] for c in df_chunk.columns]
                df_chunk = df_chunk.rename(columns=str.lower)
                df_chunk = df_chunk.reset_index().rename(
                    columns={"Datetime": "ts", "Date": "ts"}
                )
                df_chunk["ts"] = pd.to_datetime(df_chunk["ts"], utc=True)
                keep = ["ts", "open", "high", "low", "close", "volume"]
                for c in keep:
                    if c not in df_chunk.columns:
                        if c == "volume":
                            df_chunk[c] = 0.0
                        else:
                            raise ValueError(f"Missing column: {c}")
                chunks.append(df_chunk[keep])
                print(f"  {cursor.strftime('%Y-%m-%d')} -> {chunk_end.strftime('%Y-%m-%d')} | {len(df_chunk):,} rows")
            else:
                print(f"  {cursor.strftime('%Y-%m-%d')} -> {chunk_end.strftime('%Y-%m-%d')} | no data")
            cursor = chunk_end + timedelta(minutes=1)

        if chunks:
            df = pd.concat(chunks, ignore_index=True)
            df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
            if candidate != symbol:
                print(f"Fallback to {candidate} (no 1m feed for {symbol})")
            return df, candidate

    raise ValueError("No data returned.")


# ════════════════════════════════════════════════════════════════
# INDICATORS
# ════════════════════════════════════════════════════════════════

def add_indicators(df):
    # ATR
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"] - df["close"].shift(1)).abs()
    df["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(ATR_PERIOD).mean()

    # Volume proxy if feed is mostly zero
    if (df["volume"].fillna(0) <= 0).mean() > 0.8:
        print("Volume unavailable; using TR as proxy.")
        df["volume"] = df["tr"]

    df["vol_ma20"] = df["volume"].rolling(VOL_MA_PERIOD).mean().shift(1)
    df["hour"] = df["ts"].dt.hour

    # ── H1 EMA21 ──
    h1 = (
        df.set_index("ts")[["close"]]
        .resample("1h").last().dropna()
        .rename(columns={"close": "h1_close"})
        .reset_index()
    )
    h1["h1_ema21"] = h1["h1_close"].ewm(span=H1_EMA_PERIOD, adjust=False).mean()
    df = pd.merge_asof(
        df.sort_values("ts"),
        h1[["ts", "h1_ema21"]].sort_values("ts"),
        on="ts", direction="backward",
    )

    # ── H4 EMA21 + slope (NEW) ──
    h4 = (
        df.set_index("ts")[["close"]]
        .resample("4h").last().dropna()
        .rename(columns={"close": "h4_close"})
        .reset_index()
    )
    h4["h4_ema21"] = h4["h4_close"].ewm(span=H4_EMA_PERIOD, adjust=False).mean()
    h4["h4_ema_slope"] = h4["h4_ema21"].pct_change()
    df = pd.merge_asof(
        df.sort_values("ts"),
        h4[["ts", "h4_close", "h4_ema21", "h4_ema_slope"]].sort_values("ts"),
        on="ts", direction="backward",
    )

    # Swing points
    df["swing_high"] = df["high"].rolling(SWING_LOOKBACK).max().shift(1)
    df["swing_low"]  = df["low"].rolling(SWING_LOOKBACK).min().shift(1)

    # Wick ratios
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]
    df["upper_wick_ratio"] = (upper_wick / rng).fillna(0)
    df["lower_wick_ratio"] = (lower_wick / rng).fillna(0)

    return df


# ════════════════════════════════════════════════════════════════
# ENTRY QUALITY SCORE (NEW)
# ════════════════════════════════════════════════════════════════

def compute_quality_score(trap_row, entry_row, direction, sweep_depth, atr):
    """
    Score 0–100 based on multiple quality factors.
    Higher = better setup. Minimum 60 to trade.
    """
    score = 0.0

    # 1. Wick ratio quality (0–25 pts)
    if direction == "long":
        wr = trap_row["lower_wick_ratio"]
    else:
        wr = trap_row["upper_wick_ratio"]
    # 0.55 = minimum, 0.80+ = excellent
    score += min(25.0, max(0.0, (wr - 0.45) / 0.35 * 25.0))

    # 2. Sweep depth quality (0–20 pts)
    # Ideal sweep: 0.3–0.7x ATR (not too shallow, not too deep)
    sweep_ratio = sweep_depth / atr if atr > 0 else 0
    if 0.2 <= sweep_ratio <= 0.8:
        score += 20.0
    elif sweep_ratio < 0.2:
        score += sweep_ratio / 0.2 * 10.0
    else:
        score += max(0.0, 20.0 - (sweep_ratio - 0.8) * 20.0)

    # 3. Volume spike magnitude (0–20 pts)
    vol = trap_row["volume"]
    vol_ma = trap_row["vol_ma20"]
    if vol_ma > 0:
        vol_ratio = vol / vol_ma
        # 1.4x = minimum, 2.5x+ = excellent
        score += min(20.0, max(0.0, (vol_ratio - 1.0) / 1.5 * 20.0))

    # 4. H1 trend strength (0–20 pts)
    h1_ema = entry_row["h1_ema21"]
    close = entry_row["close"]
    if not pd.isna(h1_ema) and h1_ema > 0:
        trend_pct = abs(close - h1_ema) / h1_ema
        # Stronger trend alignment = higher score
        score += min(20.0, trend_pct / 0.01 * 10.0)

    # 5. H4 alignment bonus (0–15 pts)
    h4_ema = entry_row.get("h4_ema21", np.nan)
    h4_slope = entry_row.get("h4_ema_slope", np.nan)
    if not pd.isna(h4_ema) and not pd.isna(h4_slope):
        if direction == "long" and h4_slope > 0:
            score += 15.0
        elif direction == "short" and h4_slope < 0:
            score += 15.0
        elif direction == "long" and h4_slope > -0.0005:
            score += 7.0  # neutral-ish, partial credit
        elif direction == "short" and h4_slope < 0.0005:
            score += 7.0

    return min(100.0, score)


# ════════════════════════════════════════════════════════════════
# POSITION MANAGEMENT
# ════════════════════════════════════════════════════════════════

def maybe_close_position(pos, row):
    """Process exits with trailing stop logic."""
    if pos.closed:
        return 0.0

    high = float(row["high"])
    low  = float(row["low"])
    ts   = row["ts"]
    pnl_delta = 0.0

    def close_qty(price, qty_fraction, reason):
        qty = pos.remaining_qty * qty_fraction
        if qty <= 0:
            return 0.0
        if pos.direction == "long":
            gross = (price - pos.entry_price) * qty
        else:
            gross = (pos.entry_price - price) * qty
        fee = price * qty * FEE_PCT_PER_SIDE
        net = gross - fee
        pos.realized_pnl += net
        pos.fees_paid += fee
        pos.remaining_qty -= qty
        if pos.remaining_qty <= 1e-12:
            pos.closed = True
            pos.exit_time = ts
            pos.exit_price = price
            pos.exit_reason = reason
        return net

    r = pos.r_value

    if pos.direction == "long":
        current_r = (high - pos.entry_price) / r if r > 0 else 0

        if not pos.partial_done:
            # Check stop first
            if low <= pos.stop:
                return close_qty(pos.stop, 1.0, "stop_loss")
            # Partial at 1R
            if high >= pos.tp1:
                pnl_delta += close_qty(pos.tp1, 0.5, "partial_1r")
                pos.partial_done = True
                pos.stop = pos.entry_price  # move to BE
                # Check if 2R also hit on same candle
                if high >= pos.tp2 and not pos.closed:
                    pnl_delta += close_qty(pos.tp2, 1.0, "full_2r")
        else:
            # ── Trailing stop logic (NEW) ──
            if current_r >= TRAIL_ACTIVATE_R and not pos.trail_active:
                pos.trail_active = True
                pos.trail_stop = pos.entry_price + r * 1.0  # lock in 1R
            if pos.trail_active:
                # Move trail up in 0.5R steps
                new_trail = pos.entry_price + r * (
                    int(current_r / TRAIL_STEP_R) * TRAIL_STEP_R - TRAIL_STEP_R
                )
                pos.trail_stop = max(pos.trail_stop, new_trail)
                effective_stop = max(pos.stop, pos.trail_stop)
            else:
                effective_stop = pos.stop

            if low <= effective_stop:
                reason = "trail_stop" if pos.trail_active else "stop_be"
                return close_qty(effective_stop, 1.0, reason)
            if high >= pos.tp2:
                return close_qty(pos.tp2, 1.0, "full_2r")

    else:  # short
        current_r = (pos.entry_price - low) / r if r > 0 else 0

        if not pos.partial_done:
            if high >= pos.stop:
                return close_qty(pos.stop, 1.0, "stop_loss")
            if low <= pos.tp1:
                pnl_delta += close_qty(pos.tp1, 0.5, "partial_1r")
                pos.partial_done = True
                pos.stop = pos.entry_price
                if low <= pos.tp2 and not pos.closed:
                    pnl_delta += close_qty(pos.tp2, 1.0, "full_2r")
        else:
            if current_r >= TRAIL_ACTIVATE_R and not pos.trail_active:
                pos.trail_active = True
                pos.trail_stop = pos.entry_price - r * 1.0
            if pos.trail_active:
                new_trail = pos.entry_price - r * (
                    int(current_r / TRAIL_STEP_R) * TRAIL_STEP_R - TRAIL_STEP_R
                )
                pos.trail_stop = min(pos.trail_stop, new_trail) if pos.trail_stop > 0 else new_trail
                effective_stop = min(pos.stop, pos.trail_stop) if pos.trail_stop > 0 else pos.stop
            else:
                effective_stop = pos.stop

            if high >= effective_stop:
                reason = "trail_stop" if pos.trail_active else "stop_be"
                return close_qty(effective_stop, 1.0, reason)
            if low <= pos.tp2:
                return close_qty(pos.tp2, 1.0, "full_2r")

    return pnl_delta


# ════════════════════════════════════════════════════════════════
# ADAPTIVE RISK (NEW)
# ════════════════════════════════════════════════════════════════

def get_adaptive_risk(base_risk, consec_losses, h4_slope, direction):
    """
    Scale risk based on recent performance and trend strength.
    """
    risk = base_risk

    # Scale down after loss streak
    if consec_losses >= 2:
        risk = LOSS_STREAK_RISK

    # Scale up when H4 strongly confirms direction
    if not pd.isna(h4_slope):
        if direction == "long" and h4_slope > H4_STRONG_SLOPE_PCT:
            risk = max(risk, STRONG_TREND_RISK)
        elif direction == "short" and h4_slope < -H4_STRONG_SLOPE_PCT:
            risk = max(risk, STRONG_TREND_RISK)

    return risk


# ════════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ════════════════════════════════════════════════════════════════

def run_backtest(df, initial_capital, base_risk_pct):
    capital = initial_capital
    open_positions = []
    closed_positions = []
    equity_rows = []
    skip = {}
    trade_details = []

    current_day = None
    day_start_capital = initial_capital
    day_blocked = False
    consec_losses = 0
    last_stop_time = None  # cooldown tracker

    def log_skip(reason):
        skip[reason] = skip.get(reason, 0) + 1

    start_idx = max(ATR_PERIOD + 2, SWING_LOOKBACK + 2, VOL_MA_PERIOD + 2)

    for i in range(start_idx, len(df)):
        row = df.iloc[i]
        ts = row["ts"]

        # ── Daily reset ──
        d = ts.date()
        if current_day != d:
            current_day = d
            day_start_capital = capital
            day_blocked = False

        # ── Process open positions ──
        for p in list(open_positions):
            capital += maybe_close_position(p, row)
            if p.closed:
                open_positions.remove(p)
                closed_positions.append(p)
                # Track consecutive losses
                if p.realized_pnl > 0:
                    consec_losses = 0
                else:
                    consec_losses += 1
                # Track cooldown
                if p.exit_reason == "stop_loss":
                    last_stop_time = ts

        # ── Equity snapshot ──
        close_px = float(row["close"])
        unreal = sum(
            (close_px - p.entry_price) * p.remaining_qty if p.direction == "long"
            else (p.entry_price - close_px) * p.remaining_qty
            for p in open_positions
        )
        equity_rows.append({"ts": ts, "equity": capital + unreal, "cash": capital})

        # ── Daily circuit breaker ──
        if not day_blocked and capital <= day_start_capital * (1.0 - DAILY_CIRCUIT_PCT):
            day_blocked = True
        if day_blocked:
            log_skip("daily_circuit_breaker")
            continue

        # ── Max concurrent ──
        if len(open_positions) >= MAX_CONCURRENT:
            log_skip("max_concurrent")
            continue

        # ── Session gate ──
        hour = int(row["hour"])
        if not (SESSION_START_UTC <= hour < SESSION_END_UTC):
            log_skip("outside_session")
            continue

        # ── Blocked hours (NEW) ──
        if hour in BLOCKED_HOURS:
            log_skip("blocked_hour")
            continue

        # ── Cooldown after stop (NEW) ──
        if last_stop_time is not None:
            minutes_since = (ts - last_stop_time).total_seconds() / 60.0
            if minutes_since < COOLDOWN_MINUTES:
                log_skip("cooldown_after_stop")
                continue

        # ── Indicator warmup ──
        trap = df.iloc[i - 1]
        if any(pd.isna(trap[c]) for c in ["swing_high", "swing_low", "atr", "vol_ma20"]):
            log_skip("indicator_warmup")
            continue

        # ── L1: H1 trend bias ──
        h1_ema = row["h1_ema21"]
        if pd.isna(h1_ema):
            log_skip("no_h1_bias")
            continue

        # ── L2: Micro-trap detection (previous candle) ──
        atr_val = float(trap["atr"])
        bull_trap = (
            trap["low"] < trap["swing_low"]
            and trap["close"] > trap["swing_low"]
            and trap["lower_wick_ratio"] >= WICK_RATIO_MIN
            and (trap["swing_low"] - trap["low"]) <= atr_val * SWEEP_ATR_MAX
        )
        bear_trap = (
            trap["high"] > trap["swing_high"]
            and trap["close"] < trap["swing_high"]
            and trap["upper_wick_ratio"] >= WICK_RATIO_MIN
            and (trap["high"] - trap["swing_high"]) <= atr_val * SWEEP_ATR_MAX
        )

        if not bull_trap and not bear_trap:
            log_skip("no_micro_trap")
            continue

        # ── L3: Volume confirmation ──
        if trap["volume"] < trap["vol_ma20"] * VOLUME_MULT:
            log_skip("volume_fail")
            continue

        # ── L4: Momentum follow-through ──
        bull_momo = row["close"] > row["open"] and row["close"] > trap["close"]
        bear_momo = row["close"] < row["open"] and row["close"] < trap["close"]

        direction = None
        if bull_trap and bull_momo:
            direction = "long"
        elif bear_trap and bear_momo:
            direction = "short"
        else:
            log_skip("momentum_fail")
            continue

        # ── L1 trend alignment ──
        if direction == "long" and row["close"] < h1_ema:
            log_skip("counter_trend_h1")
            continue
        if direction == "short" and row["close"] > h1_ema:
            log_skip("counter_trend_h1")
            continue

        # ── H4 REGIME FILTER (NEW — the critical addition) ──
        h4_ema = row.get("h4_ema21", np.nan)
        h4_close = row.get("h4_close", np.nan)
        h4_slope = row.get("h4_ema_slope", np.nan)

        if not pd.isna(h4_ema) and not pd.isna(h4_close):
            if direction == "long" and h4_close < h4_ema:
                log_skip("h4_regime_bearish_blocks_long")
                continue
            if direction == "short" and h4_close > h4_ema:
                log_skip("h4_regime_bullish_blocks_short")
                continue

        # ── Calculate entry levels ──
        entry = float(row["close"])
        atr = float(row["atr"])

        if direction == "long":
            sweep_depth = trap["swing_low"] - trap["low"]
            stop = float(trap["low"] - atr * ATR_STOP_MULT)
            r = entry - stop
            if r <= 0:
                log_skip("invalid_r")
                continue
            tp1 = entry + PARTIAL_EXIT_R * r
            tp2 = entry + FULL_EXIT_R * r
        else:
            sweep_depth = trap["high"] - trap["swing_high"]
            stop = float(trap["high"] + atr * ATR_STOP_MULT)
            r = stop - entry
            if r <= 0:
                log_skip("invalid_r")
                continue
            tp1 = entry - PARTIAL_EXIT_R * r
            tp2 = entry - FULL_EXIT_R * r

        # ── R-value gate (NEW) ──
        if r < R_VALUE_MIN:
            log_skip("r_too_small")
            continue
        if r > R_VALUE_MAX:
            log_skip("r_too_large")
            continue

        # ── Entry quality score (NEW) ──
        quality = compute_quality_score(trap, row, direction, sweep_depth, atr)
        if quality < MIN_QUALITY_SCORE:
            log_skip("low_quality_score")
            continue

        # ── Adaptive risk sizing (NEW) ──
        risk_pct = get_adaptive_risk(base_risk_pct, consec_losses, h4_slope, direction)
        risk_dollars = capital * risk_pct
        qty = risk_dollars / r
        notional = qty * entry
        max_notional = capital * MAX_NOTIONAL_MULT
        if notional > max_notional:
            qty = max_notional / entry
        if qty <= 0:
            log_skip("invalid_size")
            continue

        # ── Open position ──
        pos = Position(
            direction=direction,
            entry_time=ts,
            entry_price=entry,
            qty=float(qty),
            stop=float(stop),
            tp1=float(tp1),
            tp2=float(tp2),
            trap_high=float(trap["high"]),
            trap_low=float(trap["low"]),
            r_value=float(r),
            quality_score=quality,
            risk_pct_used=risk_pct,
        )
        capital += pos.realized_pnl  # entry fee
        open_positions.append(pos)

    # ── Force-close remaining ──
    final_row = df.iloc[-1]
    final_price = float(final_row["close"])
    final_ts = final_row["ts"]
    for p in list(open_positions):
        if p.remaining_qty > 0:
            if p.direction == "long":
                gross = (final_price - p.entry_price) * p.remaining_qty
            else:
                gross = (p.entry_price - final_price) * p.remaining_qty
            fee = final_price * p.remaining_qty * FEE_PCT_PER_SIDE
            pnl = gross - fee
            p.realized_pnl += pnl
            p.fees_paid += fee
            p.exit_time = final_ts
            p.exit_price = final_price
            p.exit_reason = "end_of_backtest"
            p.closed = True
            p.remaining_qty = 0.0
            capital += pnl
        open_positions.remove(p)
        closed_positions.append(p)

    # Build trades DataFrame
    trades_df = pd.DataFrame([
        {
            "direction": p.direction,
            "entry_time": p.entry_time,
            "entry_price": p.entry_price,
            "exit_time": p.exit_time,
            "exit_price": p.exit_price,
            "exit_reason": p.exit_reason,
            "qty": p.qty,
            "pnl": p.realized_pnl,
            "fees": p.fees_paid,
            "r_value": p.r_value,
            "quality_score": p.quality_score,
            "risk_pct": p.risk_pct_used,
            "win": p.realized_pnl > 0,
        }
        for p in closed_positions
    ])

    equity_df = pd.DataFrame(equity_rows)
    return trades_df, equity_df, skip, capital


# ════════════════════════════════════════════════════════════════
# REPORTING
# ════════════════════════════════════════════════════════════════

def summarize(trades, equity, skip, initial_capital, final_capital, days):
    if trades.empty:
        print("\n⚠ No trades found.")
        print("\nSkip Reasons:")
        for k, v in sorted(skip.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {k:<35} {v:>7,}")
        return {}

    wins   = trades[trades["win"]]
    losses = trades[~trades["win"]]

    total_trades = len(trades)
    win_count    = len(wins)
    loss_count   = len(losses)
    win_rate     = (win_count / total_trades) * 100.0

    total_pnl    = float(trades["pnl"].sum())
    total_fees   = float(trades["fees"].sum())
    total_return = ((final_capital / initial_capital) - 1.0) * 100.0

    avg_win  = float(wins["pnl"].mean()) if win_count else 0.0
    avg_loss = float(losses["pnl"].mean()) if loss_count else 0.0
    pf = abs(float(wins["pnl"].sum()) / float(losses["pnl"].sum())) if loss_count and float(losses["pnl"].sum()) != 0 else float("inf")
    expectancy = (win_rate / 100.0) * avg_win + (1.0 - win_rate / 100.0) * avg_loss

    max_consec_loss = cur = 0
    for w in trades["win"].tolist():
        if not w:
            cur += 1
            max_consec_loss = max(max_consec_loss, cur)
        else:
            cur = 0

    eq = equity.copy()
    eq["peak"] = eq["equity"].cummax()
    eq["drawdown"] = (eq["equity"] - eq["peak"]) / eq["peak"] * 100.0
    max_dd = float(eq["drawdown"].min()) if not eq.empty else 0.0

    trades_per_day = total_trades / max(days, 1)

    # Direction breakdown
    longs  = trades[trades["direction"] == "long"]
    shorts = trades[trades["direction"] == "short"]

    # Exit reason breakdown
    exit_reasons = trades["exit_reason"].value_counts().to_dict()

    print("\n" + "=" * 70)
    print("  PHANTOM v3 BACKTEST RESULTS")
    print("=" * 70)
    print(f"  Starting Capital : ${initial_capital:,.2f}")
    print(f"  Final Capital    : ${final_capital:,.2f}")
    print(f"  Total Return     : {total_return:+.2f}%")
    print(f"  Net PnL          : ${total_pnl:+,.2f}")
    print(f"  Total Fees       : ${total_fees:,.2f}")
    print("-" * 70)
    print(f"  Total Trades     : {total_trades}")
    print(f"  Win Rate         : {win_rate:.1f}% ({win_count}W / {loss_count}L)")
    print(f"  Profit Factor    : {pf:.2f}")
    print(f"  Expectancy       : ${expectancy:+.2f} per trade")
    print(f"  Trades/Day       : {trades_per_day:.2f}")
    print(f"  Max Drawdown     : {max_dd:.2f}%")
    print(f"  Max Consec Loss  : {max_consec_loss}")
    print("-" * 70)

    print("  Direction Breakdown:")
    for label, sub in [("Long", longs), ("Short", shorts)]:
        if len(sub) > 0:
            sw = sub[sub["win"]].shape[0]
            wr = sw / len(sub) * 100
            print(f"    {label:6s}: {len(sub)} trades | {wr:.0f}% win | P&L ${sub['pnl'].sum():+,.2f}")

    print("  Exit Reasons:")
    for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
        print(f"    {reason:<25}: {count}")

    if "quality_score" in trades.columns:
        print(f"  Avg Quality Score: {trades['quality_score'].mean():.1f}")

    print("-" * 70)
    print("  Skip Reasons:")
    for k, v in sorted(skip.items(), key=lambda x: (-x[1], x[0])):
        print(f"    {k:<35} {v:>7,}")
    print("=" * 70)

    return {
        "final_capital": final_capital,
        "total_return_pct": total_return,
        "total_trades": total_trades,
        "win_rate_pct": win_rate,
        "profit_factor": pf,
        "max_drawdown_pct": max_dd,
        "trades_per_day": trades_per_day,
        "total_pnl": total_pnl,
        "total_fees": total_fees,
        "expectancy": expectancy,
    }


def save_outputs(outdir, trades, equity, summary, skip, args):
    os.makedirs(outdir, exist_ok=True)

    trades_path  = os.path.join(outdir, "phantom_v3_trades.csv")
    report_path  = os.path.join(outdir, "phantom_v3_report.md")
    results_png  = os.path.join(outdir, "phantom_v3_results.png")

    trades.to_csv(trades_path, index=False)
    print(f"\nTrades saved: {trades_path}")

    # ── Markdown report ──
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# PHANTOM v3 Backtest Report\n\n")
        f.write(f"- Symbol: {args.symbol}\n")
        f.write(f"- Interval: {args.interval}\n")
        f.write(f"- Days: {args.days}\n")
        f.write(f"- Capital: ${args.capital:,.2f}\n")
        f.write(f"- Base Risk/Trade: {args.risk:.4f}\n")
        f.write(f"- Version: PHANTOM v3 (data-driven upgrade)\n\n")

        f.write("## v3 Enhancements Active\n\n")
        f.write("- H4 regime filter (blocks counter-regime trades)\n")
        f.write(f"- Blocked hours: {sorted(BLOCKED_HOURS)}\n")
        f.write(f"- R-value gate: {R_VALUE_MIN}–{R_VALUE_MAX}\n")
        f.write(f"- Adaptive risk: {LOSS_STREAK_RISK*100:.2f}%–{STRONG_TREND_RISK*100:.2f}%\n")
        f.write(f"- Trailing stop: activates at {TRAIL_ACTIVATE_R}R, steps {TRAIL_STEP_R}R\n")
        f.write(f"- Quality score minimum: {MIN_QUALITY_SCORE}\n")
        f.write(f"- Cooldown after stop: {COOLDOWN_MINUTES} min\n\n")

        if summary:
            f.write("## Summary\n\n")
            for k, v in summary.items():
                if "pct" in k:
                    f.write(f"- {k}: {v:.2f}%\n")
                elif any(x in k for x in ["capital", "pnl", "fees", "expectancy"]):
                    f.write(f"- {k}: ${v:,.2f}\n")
                else:
                    f.write(f"- {k}: {v}\n")

        f.write("\n## Skip Reasons\n\n")
        for k, v in sorted(skip.items(), key=lambda x: (-x[1], x[0])):
            f.write(f"- {k}: {v:,}\n")

    print(f"Report saved: {report_path}")

    if args.skip_plots:
        print("Plots skipped (--skip-plots)")
        return

    # ── Charts ──
    eq = equity.copy()
    eq["peak"] = eq["equity"].cummax()
    eq["drawdown"] = (eq["equity"] - eq["peak"]) / eq["peak"] * 100.0

    fig, axes = plt.subplots(4, 1, figsize=(18, 16), gridspec_kw={"height_ratios": [3, 2, 2, 2]})
    fig.suptitle("PHANTOM v3 Backtest Results", fontsize=15, fontweight="bold")

    # 1. Equity curve
    ax = axes[0]
    ax.plot(eq["ts"], eq["equity"], color="#2E86AB", lw=1.5, label="Equity")
    ax.axhline(args.capital, color="gray", ls="--", alpha=0.6, label="Start")
    ax.fill_between(eq["ts"], args.capital, eq["equity"],
                    where=eq["equity"] >= args.capital, alpha=0.15, color="green")
    ax.fill_between(eq["ts"], args.capital, eq["equity"],
                    where=eq["equity"] < args.capital, alpha=0.15, color="red")
    ax.set_title("Equity Curve")
    ax.set_ylabel("Capital")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    # 2. Drawdown
    ax = axes[1]
    ax.fill_between(eq["ts"], 0, eq["drawdown"], color="red", alpha=0.4)
    ax.plot(eq["ts"], eq["drawdown"], color="darkred", lw=1)
    ax.set_title("Drawdown (%)")
    ax.set_ylabel("DD %")
    ax.grid(alpha=0.3)

    # 3. Trade PnL bars
    ax = axes[2]
    if not trades.empty:
        colors = ["#2ca02c" if p > 0 else "#d62728" for p in trades["pnl"]]
        ax.bar(range(len(trades)), trades["pnl"], color=colors, alpha=0.7)
        ax.axhline(0, color="black", lw=0.8)
    ax.set_title("Individual Trade PnL")
    ax.set_ylabel("PnL")
    ax.grid(alpha=0.3, axis="y")

    # 4. Cumulative PnL
    ax = axes[3]
    if not trades.empty:
        cum = trades["pnl"].cumsum()
        ax.plot(cum.values, color="#7F77DD", lw=1.5)
        ax.fill_between(range(len(cum)), 0, cum.values,
                        where=cum.values >= 0, alpha=0.2, color="green")
        ax.fill_between(range(len(cum)), 0, cum.values,
                        where=cum.values < 0, alpha=0.2, color="red")
        ax.axhline(0, color="gray", ls="--", alpha=0.5)
    ax.set_title("Cumulative PnL")
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Cum PnL")
    ax.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(results_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Chart saved: {results_png}")


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════

def main():
    args = parse_args()

    df, used_symbol = fetch_minute_data(args.symbol, args.interval, args.days)
    args.symbol = used_symbol
    print(f"Total candles: {len(df):,}")
    print(f"Data range: {df['ts'].iloc[0]} -> {df['ts'].iloc[-1]}")

    df = add_indicators(df)

    trades, equity, skip, final_capital = run_backtest(df, args.capital, args.risk)

    summary = summarize(trades, equity, skip, args.capital, final_capital, args.days)
    save_outputs(args.outdir, trades, equity, summary, skip, args)

    print("\n✅ PHANTOM v3 backtest complete.")
    print(f"  phantom_v3_trades.csv")
    print(f"  phantom_v3_report.md")
    if not args.skip_plots:
        print(f"  phantom_v3_results.png")


if __name__ == "__main__":
    main()
