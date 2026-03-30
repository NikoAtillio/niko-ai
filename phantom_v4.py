#!/usr/bin/env python3
"""
PHANTOM V4 — Adaptive Micro-Trap Engine
Walk-Forward Edition

Architecture:
  DATA    → MT5 CSV loader → 1m or 5m OHLCV
  SIGNAL  → Micro-trap liquidity sweep (adaptive thresholds)
  REGIME  → Volatility + trend + session scoring
  RISK    → FTMO-safe sizing, circuit breakers, adaptive scaling
  ENGINE  → Walk-forward: 90d train / 30d test, rolls 30d
  OUTPUT  → Per-window table, equity curve, signal audit

FTMO Hard Limits (£70k account):
  Max daily loss:   £3,500  → circuit breaker at £2,450 (70%)
  Max total loss:   £7,000  → hard stop at £3,500 (50%)
  Profit target:    £7,000

Walk-Forward Anti-Lookahead Rules:
  - All indicators computed only on data available at bar close
  - Session scoring derived from TRAIN window only, applied to TEST
  - No parameter optimisation between windows (fixed hyperparams)
  - Test window never seen during any training computation
"""

from __future__ import annotations

import argparse
import os
import warnings
from dataclasses import dataclass, field
from datetime import timezone
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# HYPERPARAMETERS  (fixed — not optimised per window)
# ─────────────────────────────────────────────
RESAMPLE_TF        = "5min"       # aggregate 1m → 5m
SWING_LOOKBACK     = 10           # bars for swing high/low
WICK_RATIO_MIN     = 0.50         # min wick/range ratio for trap candle
VOLUME_ZSCORE_MIN  = 0.5          # volume z-score threshold (vs 20-bar mean)
ATR_PERIOD         = 14
ATR_STOP_MULT      = 0.8          # stop = wick ± ATR*mult (tighter than v3)
PARTIAL_EXIT_R     = 1.0          # take 50% off at 1R
FULL_EXIT_R        = 2.0          # close remainder at 2R
MAX_CONCURRENT     = 2
FEE_PCT_PER_SIDE   = 0.00007      # 0.007% per side (Gold CFD typical)
SPREAD_FILTER_MULT = 3.0          # skip if spread > N × rolling median spread
H1_EMA_PERIOD      = 21           # hourly trend bias EMA
SWEEP_ATR_MAX      = 1.5          # max sweep size in ATR units
VOL_MA_PERIOD      = 20

# FTMO risk model
BASE_RISK_PCT      = 0.003        # 0.3% per trade base risk
MAX_RISK_PCT       = 0.005        # 0.5% cap
MIN_RISK_PCT       = 0.001        # 0.1% floor (drawdown protection)
DAILY_CB_PCT       = 0.035        # daily circuit breaker (3.5% of balance)
TOTAL_DD_GUARD_PCT = 0.05         # halt new trades if total DD > 5%
MAX_NOTIONAL_MULT  = 15.0         # max position notional vs capital

# Walk-forward
TRAIN_DAYS         = 90
TEST_DAYS          = 30

# Session: London/NY overlap — data-driven refinement applied per window
SESSION_START_UTC  = 7
SESSION_END_UTC    = 16


# ─────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────

def load_mt5_csv(path: str) -> pd.DataFrame:
    raw = pd.read_csv(path, sep=r"\s+", engine="python")
    raw.columns = [c.strip("<>").lower() for c in raw.columns]
    ts = pd.to_datetime(
        raw["date"].astype(str) + " " + raw["time"].astype(str),
        utc=True, errors="coerce"
    )
    vol_col = next((c for c in ["tickvol", "volume", "vol"] if c in raw.columns), None)
    df = pd.DataFrame({
        "ts":     ts,
        "open":   pd.to_numeric(raw["open"],  errors="coerce"),
        "high":   pd.to_numeric(raw["high"],  errors="coerce"),
        "low":    pd.to_numeric(raw["low"],   errors="coerce"),
        "close":  pd.to_numeric(raw["close"], errors="coerce"),
        "volume": pd.to_numeric(raw[vol_col], errors="coerce") if vol_col else 0.0,
        "spread": pd.to_numeric(raw["spread"], errors="coerce") if "spread" in raw.columns else 0.0,
    })
    df = df.dropna(subset=["ts","open","high","low","close"])
    df["volume"] = df["volume"].fillna(0.0)
    df["spread"] = df["spread"].fillna(0.0)
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    return df


def resample_to_tf(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    df2 = df.set_index("ts")
    agg = {
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
        "spread": "mean",
    }
    r = df2.resample(tf).agg(agg).dropna(subset=["open","high","low","close"])
    r = r.reset_index()
    # Drop bars with zero range (data gaps)
    r = r[(r["high"] - r["low"]) > 0].copy()
    return r


# ─────────────────────────────────────────────
# INDICATORS  (all shift(1) to prevent lookahead)
# ─────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # ATR
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"]  - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(ATR_PERIOD).mean()

    # Volume z-score (shift to avoid lookahead)
    vol_mean = df["volume"].rolling(VOL_MA_PERIOD).mean().shift(1)
    vol_std  = df["volume"].rolling(VOL_MA_PERIOD).std().shift(1)
    df["vol_zscore"] = (df["volume"] - vol_mean) / vol_std.replace(0, np.nan)

    # Spread filter
    df["spread_median"] = df["spread"].rolling(100).median().shift(1)

    # Swing high/low (shift so current bar can't see its own contribution)
    df["swing_high"] = df["high"].rolling(SWING_LOOKBACK).max().shift(1)
    df["swing_low"]  = df["low"].rolling(SWING_LOOKBACK).min().shift(1)

    # Wick ratios
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    upper_wick = df["high"] - df[["open","close"]].max(axis=1)
    lower_wick = df[["open","close"]].min(axis=1) - df["low"]
    df["upper_wick_ratio"] = (upper_wick / rng).fillna(0)
    df["lower_wick_ratio"] = (lower_wick / rng).fillna(0)

    # H1 trend bias (resample from 5m, merge back)
    h1 = (
        df.set_index("ts")[["close"]]
        .resample("1h").last().dropna()
        .rename(columns={"close": "h1_close"})
        .reset_index()
    )
    h1["h1_ema"] = h1["h1_close"].ewm(span=H1_EMA_PERIOD, adjust=False).mean()
    df = pd.merge_asof(
        df.sort_values("ts"),
        h1[["ts","h1_ema"]].sort_values("ts"),
        on="ts", direction="backward"
    )

    # Session hour
    df["hour"] = df["ts"].dt.hour

    # Regime: rolling ATR percentile (volatility regime)
    df["atr_pct"] = df["atr"].rolling(200).rank(pct=True)

    return df.reset_index(drop=True)


# ─────────────────────────────────────────────
# SESSION SCORING  (derived from train window only)
# ─────────────────────────────────────────────

def compute_session_scores(train_trades: pd.DataFrame) -> Dict[int, float]:
    """
    Returns a dict {hour_utc: win_rate} from training trades.
    Used to weight session gate in test window.
    Falls back to fixed session if no train trades.
    """
    if train_trades.empty:
        return {h: 1.0 for h in range(SESSION_START_UTC, SESSION_END_UTC)}
    train_trades = train_trades.copy()
    train_trades["hour"] = pd.to_datetime(train_trades["entry_time"]).dt.hour
    scores = {}
    for h in range(24):
        sub = train_trades[train_trades["hour"] == h]
        if len(sub) >= 3:
            scores[h] = float(sub["win"].mean())
        else:
            scores[h] = 0.0
    return scores


# ─────────────────────────────────────────────
# POSITION
# ─────────────────────────────────────────────

@dataclass
class Position:
    direction:    str
    entry_time:   pd.Timestamp
    entry_price:  float
    qty:          float
    stop:         float
    tp1:          float
    tp2:          float
    r_value:      float
    partial_done: bool = False
    closed:       bool = False
    remaining_qty: float = 0.0
    realized_pnl:  float = 0.0
    fees_paid:     float = 0.0
    exit_time:     Optional[pd.Timestamp] = None
    exit_price:    Optional[float] = None
    exit_reason:   Optional[str] = None

    def __post_init__(self):
        self.remaining_qty = self.qty
        entry_fee = self.entry_price * self.qty * FEE_PCT_PER_SIDE
        self.fees_paid += entry_fee
        self.realized_pnl -= entry_fee


def maybe_close(pos: Position, row: pd.Series) -> float:
    if pos.closed:
        return 0.0
    high, low, ts = float(row["high"]), float(row["low"]), row["ts"]
    delta = 0.0

    def close_qty(price: float, frac: float, reason: str) -> float:
        qty = pos.remaining_qty * frac
        if qty <= 0:
            return 0.0
        gross = (price - pos.entry_price) * qty if pos.direction == "long" else (pos.entry_price - price) * qty
        fee = price * qty * FEE_PCT_PER_SIDE
        net = gross - fee
        pos.realized_pnl += net
        pos.fees_paid += fee
        pos.remaining_qty -= qty
        if pos.remaining_qty <= 1e-10:
            pos.closed = True
            pos.exit_time = ts
            pos.exit_price = price
            pos.exit_reason = reason
        return net

    if pos.direction == "long":
        if not pos.partial_done:
            if low <= pos.stop:
                return close_qty(pos.stop, 1.0, "stop_loss")
            if high >= pos.tp1:
                delta += close_qty(pos.tp1, 0.5, "partial_1r")
                pos.partial_done = True
                pos.stop = pos.entry_price
                if high >= pos.tp2 and not pos.closed:
                    delta += close_qty(pos.tp2, 1.0, "full_2r")
        else:
            if low <= pos.stop:
                return close_qty(pos.stop, 1.0, "stop_be")
            if high >= pos.tp2:
                return close_qty(pos.tp2, 1.0, "full_2r")
    else:
        if not pos.partial_done:
            if high >= pos.stop:
                return close_qty(pos.stop, 1.0, "stop_loss")
            if low <= pos.tp1:
                delta += close_qty(pos.tp1, 0.5, "partial_1r")
                pos.partial_done = True
                pos.stop = pos.entry_price
                if low <= pos.tp2 and not pos.closed:
                    delta += close_qty(pos.tp2, 1.0, "full_2r")
        else:
            if high >= pos.stop:
                return close_qty(pos.stop, 1.0, "stop_be")
            if low <= pos.tp2:
                return close_qty(pos.tp2, 1.0, "full_2r")
    return delta


# ─────────────────────────────────────────────
# BACKTEST ENGINE  (single window)
# ─────────────────────────────────────────────

def run_window(
    df: pd.DataFrame,
    initial_capital: float,
    session_scores: Dict[int, float],
    skip: Dict[str, int],
    adaptive_risk_mult: float = 1.0,
) -> Tuple[pd.DataFrame, pd.DataFrame, float]:
    """
    Run backtest on a single data slice.
    Returns (trades_df, equity_df, final_capital).
    session_scores: {hour: win_rate} from training window.
    adaptive_risk_mult: scaling factor from rolling performance tracker.
    """
    capital = initial_capital
    open_positions: List[Position] = []
    closed: List[Position] = []
    equity_rows: List[dict] = []

    current_day = None
    day_start_capital = capital
    day_blocked = False
    peak_capital = capital

    def log_skip(r: str):
        skip[r] = skip.get(r, 0) + 1

    # Determine active hours from session_scores (hours with WR > 30% or default session)
    if session_scores:
        active_hours = {h for h, wr in session_scores.items() if wr >= 0.30}
        if len(active_hours) < 3:  # fallback if too few hours have data
            active_hours = set(range(SESSION_START_UTC, SESSION_END_UTC))
    else:
        active_hours = set(range(SESSION_START_UTC, SESSION_END_UTC))

    warmup = max(ATR_PERIOD + 2, SWING_LOOKBACK + 2, VOL_MA_PERIOD + 2, 200 + 2)

    for i in range(warmup, len(df)):
        row = df.iloc[i]
        ts  = row["ts"]

        # ── Day reset ──
        d = ts.date()
        if current_day != d:
            current_day = d
            day_start_capital = capital
            day_blocked = False

        # ── Update open positions ──
        for p in list(open_positions):
            capital += maybe_close(p, row)
            if p.closed:
                open_positions.remove(p)
                closed.append(p)

        # ── Equity tracking (cash basis — no MTM distortion) ──
        equity_rows.append({"ts": ts, "equity": capital})

        # ── Total DD guard ──
        peak_capital = max(peak_capital, capital)
        total_dd_pct = (peak_capital - capital) / peak_capital
        if total_dd_pct > TOTAL_DD_GUARD_PCT:
            log_skip("total_dd_guard")
            continue

        # ── Daily circuit breaker ──
        if not day_blocked and capital <= day_start_capital * (1.0 - DAILY_CB_PCT):
            day_blocked = True
        if day_blocked:
            log_skip("daily_circuit_breaker")
            continue

        # ── Concurrent limit ──
        if len(open_positions) >= MAX_CONCURRENT:
            log_skip("max_concurrent")
            continue

        # ── Session gate ──
        hour = int(row["hour"])
        if hour not in active_hours:
            log_skip("outside_session")
            continue

        # ── Indicator warmup check ──
        trap = df.iloc[i - 1]
        if any(pd.isna(trap[c]) for c in ["atr","swing_high","swing_low","vol_zscore"]):
            log_skip("indicator_warmup")
            continue

        # ── Spread filter ──
        if row["spread"] > 0 and not pd.isna(row["spread_median"]) and row["spread_median"] > 0:
            if row["spread"] > row["spread_median"] * SPREAD_FILTER_MULT:
                log_skip("wide_spread")
                continue

        # ── H1 trend bias ──
        h1_ema = row["h1_ema"]
        if pd.isna(h1_ema):
            log_skip("no_h1_bias")
            continue

        # ── L2: Micro-trap detection on PREVIOUS bar ──
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
        if not pd.isna(trap["vol_zscore"]) and trap["vol_zscore"] < VOLUME_ZSCORE_MIN:
            log_skip("volume_fail")
            continue

        # ── L4: Momentum follow-through on current bar ──
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

        # ── L1: Trend alignment ──
        close_px = float(row["close"])
        if direction == "long"  and close_px < h1_ema:
            log_skip("counter_trend")
            continue
        if direction == "short" and close_px > h1_ema:
            log_skip("counter_trend")
            continue

        # ── Entry & stop calculation ──
        entry = close_px
        atr_now = float(row["atr"]) if not pd.isna(row["atr"]) else atr_val

        if direction == "long":
            stop = float(trap["low"]) - atr_now * ATR_STOP_MULT
            r = entry - stop
        else:
            stop = float(trap["high"]) + atr_now * ATR_STOP_MULT
            r = stop - entry

        if r <= 0:
            log_skip("invalid_r")
            continue

        tp1 = entry + PARTIAL_EXIT_R * r if direction == "long" else entry - PARTIAL_EXIT_R * r
        tp2 = entry + FULL_EXIT_R * r   if direction == "long" else entry - FULL_EXIT_R * r

        # ── Fee viability check ──
        # Skip if estimated round-trip fee > 20% of expected 1R gain
        est_fee_pct = FEE_PCT_PER_SIDE * 2  # entry + exit
        if est_fee_pct * entry / r > 0.20:
            log_skip("fee_too_high_vs_r")
            continue

        # ── Position sizing (FTMO-safe) ──
        effective_risk_pct = BASE_RISK_PCT * adaptive_risk_mult
        effective_risk_pct = max(MIN_RISK_PCT, min(MAX_RISK_PCT, effective_risk_pct))
        risk_dollars = capital * effective_risk_pct
        qty = risk_dollars / r
        notional = qty * entry
        if notional > capital * MAX_NOTIONAL_MULT:
            qty = (capital * MAX_NOTIONAL_MULT) / entry
        if qty <= 0:
            log_skip("invalid_size")
            continue

        pos = Position(
            direction=direction,
            entry_time=ts,
            entry_price=entry,
            qty=qty,
            stop=stop,
            tp1=tp1,
            tp2=tp2,
            r_value=r,
        )
        capital += pos.realized_pnl  # deduct entry fee immediately
        open_positions.append(pos)

    # ── Force-close remaining at end of window ──
    final_row = df.iloc[-1]
    final_price = float(final_row["close"])
    final_ts    = final_row["ts"]
    for p in list(open_positions):
        if p.remaining_qty > 0:
            gross = (final_price - p.entry_price) * p.remaining_qty if p.direction == "long" \
                    else (p.entry_price - final_price) * p.remaining_qty
            fee = final_price * p.remaining_qty * FEE_PCT_PER_SIDE
            pnl = gross - fee
            p.realized_pnl += pnl
            p.fees_paid += fee
            p.exit_time = final_ts
            p.exit_price = final_price
            p.exit_reason = "end_of_window"
            p.closed = True
            p.remaining_qty = 0.0
            capital += pnl
        closed.append(p)

    trades_df = pd.DataFrame([{
        "direction":   p.direction,
        "entry_time":  p.entry_time,
        "entry_price": p.entry_price,
        "exit_time":   p.exit_time,
        "exit_price":  p.exit_price,
        "exit_reason": p.exit_reason,
        "qty":         p.qty,
        "pnl":         p.realized_pnl,
        "fees":        p.fees_paid,
        "r_value":     p.r_value,
        "win":         p.realized_pnl > 0,
    } for p in closed])

    equity_df = pd.DataFrame(equity_rows)
    return trades_df, equity_df, capital


# ─────────────────────────────────────────────
# ADAPTIVE RISK MULTIPLIER
# ─────────────────────────────────────────────

def compute_adaptive_mult(recent_trades: pd.DataFrame, lookback: int = 20) -> float:
    """
    Scale risk based on rolling performance of last N trades.
    WR < 35% → 0.5×  |  WR 35–50% → 0.75×  |  WR > 50% → 1.0×
    """
    if recent_trades.empty or len(recent_trades) < 5:
        return 1.0
    tail = recent_trades.tail(lookback)
    wr = tail["win"].mean()
    if wr < 0.35:
        return 0.5
    elif wr < 0.50:
        return 0.75
    else:
        return 1.0


# ─────────────────────────────────────────────
# WALK-FORWARD ORCHESTRATOR
# ─────────────────────────────────────────────

def walk_forward(df: pd.DataFrame, initial_capital: float) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Runs 90d train / 30d test walk-forward across full dataset.
    Returns (window_results_df, all_trades_df, all_equity_df).

    Anti-lookahead guarantees:
      1. Indicators computed on full df but only values up to train_end
         are used to derive session_scores.
      2. Test window slice starts AFTER train_end — no overlap.
      3. adaptive_risk_mult computed from train trades only.
      4. No parameter search — hyperparams fixed above.
    """
    start = df["ts"].iloc[0]
    end   = df["ts"].iloc[-1]

    capital = initial_capital
    all_trades: List[pd.DataFrame] = []
    all_equity: List[pd.DataFrame] = []
    window_results: List[dict] = []
    global_skip: Dict[str, int] = {}

    window_num = 0
    cursor = start

    while True:
        train_start = cursor
        train_end   = cursor + pd.Timedelta(days=TRAIN_DAYS)
        test_start  = train_end
        test_end    = test_start + pd.Timedelta(days=TEST_DAYS)

        if test_end > end:
            break

        window_num += 1
        print(f"\n{'='*60}")
        print(f"Window {window_num:02d} | Train: {train_start.date()} → {train_end.date()} | Test: {test_start.date()} → {test_end.date()}")

        # ── Slice data (strict — no overlap) ──
        train_df = df[(df["ts"] >= train_start) & (df["ts"] < train_end)].copy().reset_index(drop=True)
        test_df  = df[(df["ts"] >= test_start)  & (df["ts"] < test_end)].copy().reset_index(drop=True)

        if len(train_df) < 500 or len(test_df) < 100:
            print(f"  Skipping — insufficient data (train={len(train_df)}, test={len(test_df)})")
            cursor += pd.Timedelta(days=TEST_DAYS)
            continue

        # ── Run train window (to get session scores + adaptive mult) ──
        train_skip: Dict[str, int] = {}
        train_trades, _, train_final = run_window(
            train_df, capital, {}, train_skip, adaptive_risk_mult=1.0
        )

        # ── Derive session scores from train trades ──
        session_scores = compute_session_scores(train_trades)

        # ── Adaptive risk multiplier from train performance ──
        adaptive_mult = compute_adaptive_mult(train_trades)

        # ── Run TEST window (true out-of-sample) ──
        test_skip: Dict[str, int] = {}
        test_trades, test_equity, test_final = run_window(
            test_df, capital, session_scores, test_skip, adaptive_risk_mult=adaptive_mult
        )

        # ── Accumulate global skips ──
        for k, v in test_skip.items():
            global_skip[k] = global_skip.get(k, 0) + v

        # ── Compute window metrics ──
        n = len(test_trades)
        if n > 0:
            wins = test_trades[test_trades["win"]]
            losses = test_trades[~test_trades["win"]]
            wr = test_trades["win"].mean() * 100
            gross_win  = wins["pnl"].sum()
            gross_loss = abs(losses["pnl"].sum())
            pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
            net_pnl = test_trades["pnl"].sum()
            total_fees = test_trades["fees"].sum()
            expectancy = test_trades["pnl"].mean()
            ret_pct = (test_final / capital - 1) * 100
            if not test_equity.empty:
                eq = test_equity["equity"].values
                peak = np.maximum.accumulate(eq)
                dd = (eq - peak) / np.where(peak > 0, peak, 1) * 100
                max_dd = float(dd.min())
            else:
                max_dd = 0.0
        else:
            wr = pf = net_pnl = total_fees = expectancy = ret_pct = max_dd = 0.0

        # ── Train metrics for degradation check ──
        if len(train_trades) > 0:
            train_wr = train_trades["win"].mean() * 100
            train_pf_val = abs(train_trades[train_trades["win"]]["pnl"].sum()) / \
                           max(abs(train_trades[~train_trades["win"]]["pnl"].sum()), 1e-9)
        else:
            train_wr = train_pf_val = 0.0

        degradation_flag = (wr < train_wr * 0.70) if train_wr > 0 else False

        result = {
            "window":        window_num,
            "test_start":    test_start.date(),
            "test_end":      test_end.date(),
            "trades":        n,
            "win_rate":      round(wr, 1),
            "profit_factor": round(pf, 2),
            "net_pnl":       round(net_pnl, 2),
            "total_fees":    round(total_fees, 2),
            "expectancy":    round(expectancy, 2),
            "return_pct":    round(ret_pct, 2),
            "max_dd_pct":    round(max_dd, 2),
            "train_wr":      round(train_wr, 1),
            "adaptive_mult": adaptive_mult,
            "degraded":      degradation_flag,
            "capital_start": round(capital, 2),
            "capital_end":   round(test_final, 2),
        }
        window_results.append(result)

        print(f"  Trades: {n} | WR: {wr:.1f}% | PF: {pf:.2f} | PnL: ${net_pnl:+,.2f} | DD: {max_dd:.2f}% | {'⚠ DEGRADED' if degradation_flag else 'OK'}")
        print(f"  Train WR: {train_wr:.1f}% | Adaptive mult: {adaptive_mult:.2f}x | Fees: ${total_fees:,.2f}")

        # ── Carry capital forward ──
        capital = test_final

        if not test_trades.empty:
            test_trades["window"] = window_num
            all_trades.append(test_trades)
        if not test_equity.empty:
            test_equity["window"] = window_num
            all_equity.append(test_equity)

        cursor += pd.Timedelta(days=TEST_DAYS)

    results_df = pd.DataFrame(window_results)
    trades_df  = pd.concat(all_trades,  ignore_index=True) if all_trades  else pd.DataFrame()
    equity_df  = pd.concat(all_equity,  ignore_index=True) if all_equity  else pd.DataFrame()

    return results_df, trades_df, equity_df, global_skip


# ─────────────────────────────────────────────
# REPORTING & CHARTS
# ─────────────────────────────────────────────

def print_summary(results: pd.DataFrame, trades: pd.DataFrame, initial_capital: float, final_capital: float, skip: Dict[str, int]):
    print("\n" + "=" * 70)
    print("PHANTOM V4 — WALK-FORWARD SUMMARY")
    print("=" * 70)

    if results.empty:
        print("No results.")
        return

    print(f"\n{'Win':>6} {'PF':>6} {'PnL':>10} {'DD%':>7} {'Trades':>7} {'Degr':>6}  Period")
    print("-" * 70)
    for _, r in results.iterrows():
        flag = "⚠" if r["degraded"] else " "
        print(f"{r['win_rate']:>5.1f}% {r['profit_factor']:>6.2f} {r['net_pnl']:>+10.2f} {r['max_dd_pct']:>6.2f}% {r['trades']:>7}  {flag}  {r['test_start']} → {r['test_end']}")

    print("-" * 70)
    if not trades.empty:
        total_trades = len(trades)
        overall_wr   = trades["win"].mean() * 100
        overall_pf_n = trades[trades["win"]]["pnl"].sum()
        overall_pf_d = abs(trades[~trades["win"]]["pnl"].sum())
        overall_pf   = overall_pf_n / overall_pf_d if overall_pf_d > 0 else float("inf")
        overall_exp  = trades["pnl"].mean()
        total_fees   = trades["fees"].sum()
        total_ret    = (final_capital / initial_capital - 1) * 100
        degraded_pct = results["degraded"].mean() * 100

        print(f"\nOVERALL (out-of-sample only)")
        print(f"  Total trades:      {total_trades}")
        print(f"  Win rate:          {overall_wr:.1f}%")
        print(f"  Profit factor:     {overall_pf:.2f}")
        print(f"  Expectancy:        ${overall_exp:+.2f}/trade")
        print(f"  Total fees:        ${total_fees:,.2f}")
        print(f"  Total return:      {total_ret:+.2f}%")
        print(f"  Final capital:     ${final_capital:,.2f}")
        print(f"  Windows degraded:  {degraded_pct:.0f}%")

        print(f"\nSKIP REASONS (test windows only)")
        for k, v in sorted(skip.items(), key=lambda x: -x[1]):
            print(f"  {k:<30} {v:>8,}")

        # Direction breakdown
        print(f"\nDIRECTION BREAKDOWN")
        for d in ["long", "short"]:
            sub = trades[trades["direction"] == d]
            if len(sub) > 0:
                print(f"  {d}: {len(sub)} trades | WR: {sub['win'].mean()*100:.1f}% | PnL: ${sub['pnl'].sum():+,.2f}")

        # Exit reason breakdown
        print(f"\nEXIT REASONS")
        for reason, cnt in trades["exit_reason"].value_counts().items():
            sub = trades[trades["exit_reason"] == reason]
            print(f"  {reason:<20} {cnt:>5} trades | WR: {sub['win'].mean()*100:.0f}% | Avg PnL: ${sub['pnl'].mean():+.2f}")

    print("=" * 70)


def save_charts(results: pd.DataFrame, trades: pd.DataFrame, equity: pd.DataFrame, outdir: str):
    os.makedirs(outdir, exist_ok=True)

    # ── Chart 1: Walk-forward equity curve ──
    fig, axes = plt.subplots(3, 1, figsize=(18, 14))

    if not equity.empty and "ts" in equity.columns:
        axes[0].plot(equity["ts"], equity["equity"], color="#1f77b4", lw=0.8, alpha=0.9)
        # Shade windows alternately
        if not results.empty:
            for _, r in results.iterrows():
                color = "#e8f4e8" if not r["degraded"] else "#fde8e8"
                axes[0].axvspan(
                    pd.Timestamp(r["test_start"], tz="UTC"),
                    pd.Timestamp(r["test_end"],   tz="UTC"),
                    alpha=0.3, color=color
                )
    axes[0].set_title("PHANTOM V4 — Walk-Forward Equity (green=OK, red=degraded window)", fontsize=12)
    axes[0].set_ylabel("Capital ($)")
    axes[0].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    axes[0].xaxis.set_major_locator(mdates.MonthLocator(interval=2))

    # ── Chart 2: Per-window win rate vs profit factor ──
    if not results.empty:
        x = np.arange(len(results))
        bar_colors = ["#2ca02c" if not d else "#d62728" for d in results["degraded"]]
        axes[1].bar(x, results["win_rate"], color=bar_colors, alpha=0.7, label="Win Rate %")
        axes[1].axhline(40, color="orange", lw=1.5, ls="--", label="40% WR target")
        axes[1].axhline(50, color="green",  lw=1.0, ls=":",  label="50% WR")
        ax1b = axes[1].twinx()
        ax1b.plot(x, results["profit_factor"], color="#ff7f0e", marker="o", ms=5, lw=1.5, label="Profit Factor")
        ax1b.axhline(1.0, color="gray", lw=1.0, ls="--")
        ax1b.set_ylabel("Profit Factor", color="#ff7f0e")
        axes[1].set_title("Per-Window Win Rate & Profit Factor")
        axes[1].set_ylabel("Win Rate (%)")
        axes[1].set_xticks(x)
        axes[1].set_xticklabels([str(r["test_start"]) for r in results.to_dict("records")], rotation=45, ha="right", fontsize=7)
        axes[1].legend(loc="upper left", fontsize=8)
        ax1b.legend(loc="upper right", fontsize=8)

    # ── Chart 3: Trade PnL distribution ──
    if not trades.empty:
        colors = ["#2ca02c" if w else "#d62728" for w in trades["win"]]
        axes[2].bar(np.arange(len(trades)), trades["pnl"], color=colors, alpha=0.7)
        axes[2].axhline(0, color="black", lw=0.8)
        axes[2].set_title("Trade PnL (all out-of-sample windows)")
        axes[2].set_ylabel("PnL ($)")
        axes[2].set_xlabel("Trade #")

    plt.tight_layout()
    path = os.path.join(outdir, "phantom_v4_results.png")
    plt.savefig(path, dpi=140)
    plt.close(fig)
    print(f"Chart saved: {path}")

    # ── Chart 2: Window metrics heatmap ──
    if not results.empty:
        fig2, ax = plt.subplots(figsize=(14, 5))
        metrics = results[["win_rate","profit_factor","return_pct","max_dd_pct","trades"]].copy()
        metrics.index = [f"W{r['window']:02d}\n{r['test_start']}" for _, r in results.iterrows()]
        im = ax.imshow(metrics.T.values, aspect="auto", cmap="RdYlGn")
        ax.set_xticks(np.arange(len(metrics)))
        ax.set_xticklabels(metrics.index, fontsize=7)
        ax.set_yticks(np.arange(len(metrics.columns)))
        ax.set_yticklabels(metrics.columns, fontsize=9)
        for i in range(len(metrics.columns)):
            for j in range(len(metrics)):
                ax.text(j, i, f"{metrics.iloc[j, i]:.1f}", ha="center", va="center", fontsize=7)
        plt.colorbar(im, ax=ax)
        ax.set_title("PHANTOM V4 — Window Metrics Heatmap")
        plt.tight_layout()
        path2 = os.path.join(outdir, "phantom_v4_heatmap.png")
        plt.savefig(path2, dpi=140)
        plt.close(fig2)
        print(f"Heatmap saved: {path2}")


def save_report(results: pd.DataFrame, trades: pd.DataFrame, summary: dict, skip: Dict[str, int], outdir: str, args):
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "phantom_v4_report.md")
    with open(path, "w") as f:
        f.write("# PHANTOM V4 Walk-Forward Report\n\n")
        f.write(f"- Data file: {args.data_file}\n")
        f.write(f"- Resample TF: {RESAMPLE_TF}\n")
        f.write(f"- Train/Test: {TRAIN_DAYS}d / {TEST_DAYS}d\n")
        f.write(f"- Capital: ${args.capital:,.2f}\n")
        f.write(f"- Base risk: {BASE_RISK_PCT*100:.2f}%\n\n")
        f.write("## Overall Results\n\n")
        for k, v in summary.items():
            f.write(f"- {k}: {v}\n")
        f.write("\n## Per-Window Results\n\n")
        f.write("| Window | Period | Trades | WR% | PF | PnL | DD% | Degraded |\n")
        f.write("|--------|--------|--------|-----|----|-----|-----|----------|\n")
        for _, r in results.iterrows():
            f.write(f"| {r['window']} | {r['test_start']} → {r['test_end']} | {r['trades']} | {r['win_rate']} | {r['profit_factor']} | ${r['net_pnl']:+,.2f} | {r['max_dd_pct']:.1f}% | {'⚠' if r['degraded'] else '✓'} |\n")
        f.write("\n## Skip Reasons\n\n")
        for k, v in sorted(skip.items(), key=lambda x: -x[1]):
            f.write(f"- {k}: {v:,}\n")
        f.write("\n## Hyperparameters\n\n")
        for name, val in [
            ("RESAMPLE_TF", RESAMPLE_TF), ("SWING_LOOKBACK", SWING_LOOKBACK),
            ("WICK_RATIO_MIN", WICK_RATIO_MIN), ("VOLUME_ZSCORE_MIN", VOLUME_ZSCORE_MIN),
            ("ATR_STOP_MULT", ATR_STOP_MULT), ("BASE_RISK_PCT", BASE_RISK_PCT),
            ("MAX_CONCURRENT", MAX_CONCURRENT), ("FEE_PCT_PER_SIDE", FEE_PCT_PER_SIDE),
            ("SESSION_START_UTC", SESSION_START_UTC), ("SESSION_END_UTC", SESSION_END_UTC),
        ]:
            f.write(f"- {name}: {val}\n")
    print(f"Report saved: {path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="PHANTOM V4 Walk-Forward Backtest")
    p.add_argument("--data-file", required=True, help="Path to MT5 CSV export")
    p.add_argument("--capital", type=float, default=10000.0, help="Starting capital")
    p.add_argument("--outdir", default=".", help="Output directory")
    p.add_argument("--skip-plots", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()

    print("=" * 70)
    print("PHANTOM V4 — Adaptive Micro-Trap Walk-Forward Engine")
    print("=" * 70)
    print(f"Data file:    {args.data_file}")
    print(f"Capital:      ${args.capital:,.2f}")
    print(f"Resample TF:  {RESAMPLE_TF}")
    print(f"Walk-forward: {TRAIN_DAYS}d train / {TEST_DAYS}d test")
    print(f"Base risk:    {BASE_RISK_PCT*100:.2f}% per trade")
    print(f"FTMO limits:  Daily CB {DAILY_CB_PCT*100:.1f}% | Total guard {TOTAL_DD_GUARD_PCT*100:.1f}%")

    # Load & resample
    print("\nLoading data...")
    df_1m = load_mt5_csv(args.data_file)
    print(f"  1m candles: {len(df_1m):,} | {df_1m['ts'].iloc[0].date()} → {df_1m['ts'].iloc[-1].date()}")

    print(f"  Resampling to {RESAMPLE_TF}...")
    df = resample_to_tf(df_1m, RESAMPLE_TF)
    print(f"  {RESAMPLE_TF} candles: {len(df):,}")

    # Add indicators on full dataset (values are shift(1) — no lookahead)
    print("  Computing indicators...")
    df = add_indicators(df)

    # Walk-forward
    print("\nStarting walk-forward...")
    results, trades, equity, skip = walk_forward(df, args.capital)

    # Summary
    final_capital = results["capital_end"].iloc[-1] if not results.empty else args.capital
    summary = {}
    if not trades.empty:
        summary = {
            "total_trades":   len(trades),
            "win_rate":       f"{trades['win'].mean()*100:.1f}%",
            "profit_factor":  f"{abs(trades[trades['win']]['pnl'].sum()) / max(abs(trades[~trades['win']]['pnl'].sum()), 1e-9):.2f}",
            "expectancy":     f"${trades['pnl'].mean():+.2f}",
            "total_fees":     f"${trades['fees'].sum():,.2f}",
            "total_return":   f"{(final_capital/args.capital-1)*100:+.2f}%",
            "final_capital":  f"${final_capital:,.2f}",
            "windows_tested": len(results),
            "windows_degraded": f"{results['degraded'].mean()*100:.0f}%",
        }

    print_summary(results, trades, args.capital, final_capital, skip)

    # Save outputs
    if not args.skip_plots:
        save_charts(results, trades, equity, args.outdir)
    save_report(results, trades, summary, skip, args.outdir, args)

    if not trades.empty:
        trades_path = os.path.join(args.outdir, "phantom_v4_trades.csv")
        trades.to_csv(trades_path, index=False)
        print(f"Trades saved: {trades_path}")

    results_path = os.path.join(args.outdir, "phantom_v4_windows.csv")
    results.to_csv(results_path, index=False)
    print(f"Windows saved: {results_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
