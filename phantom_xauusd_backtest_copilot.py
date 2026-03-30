#!/usr/bin/env python3
"""
PHANTOM: Price Hunting After Micro Trap On Momentum

Layers:
- L1: H1 trend bias using EMA21
- L2: Micro-trap liquidity sweep of 8-candle swing points + wick ratio
- L3: Volume confirmation (trap candle volume >= 1.4x 20-bar average)
- L4: Momentum confirmation (next candle follows reversal)
- L5: Session gate (London/NY overlap 07:00-16:00 UTC)

Risk model:
- ATR-based stop beyond trap wick
- 50% partial at 1R -> stop to break-even
- Remaining 50% target at 2R
- Max 3 concurrent positions
- Daily -2% circuit breaker
- Fee 0.007% per side
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf


# Strategy defaults
SWING_LOOKBACK = 8
WICK_RATIO_MIN = 0.55
VOLUME_MULT = 1.4
VOL_MA_PERIOD = 20
ATR_PERIOD = 14
ATR_STOP_MULT = 1.0
PARTIAL_EXIT_R = 1.0
FULL_EXIT_R = 2.0
MAX_CONCURRENT = 3
DAILY_CIRCUIT_BREAKER_PCT = 0.02
FEE_PCT_PER_SIDE = 0.00007
SESSION_START_UTC = 7
SESSION_END_UTC = 16
H1_EMA_PERIOD = 21
SWEEP_ATR_MAX = 1.0
MAX_NOTIONAL_MULTIPLIER = 20.0


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
    partial_done: bool = False
    closed: bool = False
    remaining_qty: float = 0.0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None

    def __post_init__(self) -> None:
        self.remaining_qty = self.qty
        entry_fee = self.entry_price * self.qty * FEE_PCT_PER_SIDE
        self.fees_paid += entry_fee
        self.realized_pnl -= entry_fee


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PHANTOM XAUUSD backtest")
    p.add_argument("--symbol", default="XAUUSD=X", help="Yahoo Finance symbol")
    p.add_argument("--interval", default="1m", help="Data interval (default 1m)")
    p.add_argument("--days", type=int, default=30, help="Lookback days")
    p.add_argument("--data-file", default="", help="Optional MT5 CSV export file path")
    p.add_argument("--capital", type=float, default=3720.0, help="Starting capital")
    p.add_argument("--risk", type=float, default=0.01, help="Risk per trade fraction")
    p.add_argument("--skip-plots", action="store_true", help="Skip chart generation")
    p.add_argument("--outdir", default=".", help="Output directory")
    return p.parse_args()


def load_mt5_data(path: str) -> pd.DataFrame:
    raw = pd.read_csv(path, sep=r"\s+", engine="python")
    raw.columns = [str(c).strip().strip("<>").lower() for c in raw.columns]

    date_col = "date" if "date" in raw.columns else None
    time_col = "time" if "time" in raw.columns else None
    if not date_col or not time_col:
        raise ValueError("MT5 file must include DATE and TIME columns")

    open_col = "open" if "open" in raw.columns else None
    high_col = "high" if "high" in raw.columns else None
    low_col = "low" if "low" in raw.columns else None
    close_col = "close" if "close" in raw.columns else None

    if not all([open_col, high_col, low_col, close_col]):
        raise ValueError("MT5 file must include OPEN, HIGH, LOW, CLOSE columns")

    if "tickvol" in raw.columns:
        volume_col = "tickvol"
    elif "volume" in raw.columns:
        volume_col = "volume"
    elif "vol" in raw.columns:
        volume_col = "vol"
    else:
        volume_col = None

    ts = pd.to_datetime(raw[date_col].astype(str) + " " + raw[time_col].astype(str), utc=True, errors="coerce")

    df = pd.DataFrame(
        {
            "ts": ts,
            "open": pd.to_numeric(raw[open_col], errors="coerce"),
            "high": pd.to_numeric(raw[high_col], errors="coerce"),
            "low": pd.to_numeric(raw[low_col], errors="coerce"),
            "close": pd.to_numeric(raw[close_col], errors="coerce"),
            "volume": pd.to_numeric(raw[volume_col], errors="coerce") if volume_col else 0.0,
        }
    )

    df = df.dropna(subset=["ts", "open", "high", "low", "close"]).copy()
    df["volume"] = df["volume"].fillna(0.0)
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)

    if df.empty:
        raise ValueError("No valid rows loaded from MT5 file")

    return df


def fetch_minute_data(symbol: str, interval: str, days: int) -> tuple[pd.DataFrame, str]:
    """
    Pull data in <=7 day chunks due Yahoo intraday limits.
    """
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=days)

    candidates = [symbol]
    if symbol != "GC=F":
        candidates.append("GC=F")

    for candidate in candidates:
        chunks: List[pd.DataFrame] = []
        cursor = start
        chunk_days = 6

        print(f"Fetching {days} days of {interval} {candidate} data from Yahoo Finance...")

        while cursor < end:
            chunk_end = min(cursor + timedelta(days=chunk_days), end)
            df_chunk = yf.download(
                candidate,
                start=cursor,
                end=chunk_end,
                interval=interval,
                auto_adjust=False,
                progress=False,
                threads=False,
            )

            if not df_chunk.empty:
                if isinstance(df_chunk.columns, pd.MultiIndex):
                    df_chunk.columns = [c[0] for c in df_chunk.columns]
                df_chunk = df_chunk.rename(columns=str.lower)
                df_chunk = df_chunk.reset_index().rename(columns={"Datetime": "ts", "Date": "ts"})
                df_chunk["ts"] = pd.to_datetime(df_chunk["ts"], utc=True)
                keep = ["ts", "open", "high", "low", "close", "volume"]
                for c in keep:
                    if c not in df_chunk.columns:
                        if c == "volume":
                            df_chunk[c] = 0.0
                        else:
                            raise ValueError(f"Missing required column: {c}")
                chunks.append(df_chunk[keep])
                print(
                    f"  Chunk {cursor.strftime('%Y-%m-%d')} -> {chunk_end.strftime('%Y-%m-%d')} | "
                    f"{len(df_chunk):,} rows"
                )
            else:
                print(f"  Chunk {cursor.strftime('%Y-%m-%d')} -> {chunk_end.strftime('%Y-%m-%d')} | no data")

            cursor = chunk_end + timedelta(minutes=1)

        if chunks:
            df = pd.concat(chunks, ignore_index=True)
            df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
            if candidate != symbol:
                print(f"Using fallback symbol {candidate} because {symbol} had no 1m feed.")
            return df, candidate

    raise ValueError("No market data returned. Try fewer days or a different symbol.")


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"] - df["close"].shift(1)).abs()
    df["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(ATR_PERIOD).mean()

    # Handle instruments where Yahoo volume is frequently missing/zero.
    if (df["volume"].fillna(0) <= 0).mean() > 0.8:
        print("Volume mostly unavailable from feed; using true range as volume proxy.")
        df["volume"] = df["tr"]

    df["vol_ma20"] = df["volume"].rolling(VOL_MA_PERIOD).mean().shift(1)
    df["hour"] = df["ts"].dt.hour

    # H1 trend bias from minute bars.
    h1 = (
        df.set_index("ts")[["close"]]
        .resample("1H")
        .last()
        .dropna()
        .rename(columns={"close": "h1_close"})
        .reset_index()
    )
    h1["h1_ema21"] = h1["h1_close"].ewm(span=H1_EMA_PERIOD, adjust=False).mean()

    df = pd.merge_asof(
        df.sort_values("ts"),
        h1[["ts", "h1_ema21"]].sort_values("ts"),
        on="ts",
        direction="backward",
    )

    df["swing_high"] = df["high"].rolling(SWING_LOOKBACK).max().shift(1)
    df["swing_low"] = df["low"].rolling(SWING_LOOKBACK).min().shift(1)

    rng = (df["high"] - df["low"]).replace(0, np.nan)
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]
    df["upper_wick_ratio"] = (upper_wick / rng).fillna(0)
    df["lower_wick_ratio"] = (lower_wick / rng).fillna(0)

    return df


def in_session(hour_utc: int) -> bool:
    return SESSION_START_UTC <= hour_utc < SESSION_END_UTC


def maybe_close_position(pos: Position, row: pd.Series) -> float:
    if pos.closed:
        return 0.0

    high = float(row["high"])
    low = float(row["low"])
    ts = row["ts"]
    pnl_delta = 0.0

    def close_qty(price: float, qty_fraction: float, reason: str) -> float:
        nonlocal pos
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

    if pos.direction == "long":
        if not pos.partial_done:
            if low <= pos.stop:
                return close_qty(pos.stop, 1.0, "stop_loss")
            if high >= pos.tp1:
                pnl_delta += close_qty(pos.tp1, 0.5, "partial_1r")
                pos.partial_done = True
                pos.stop = pos.entry_price
                if high >= pos.tp2 and not pos.closed:
                    pnl_delta += close_qty(pos.tp2, 1.0, "full_2r")
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
                pnl_delta += close_qty(pos.tp1, 0.5, "partial_1r")
                pos.partial_done = True
                pos.stop = pos.entry_price
                if low <= pos.tp2 and not pos.closed:
                    pnl_delta += close_qty(pos.tp2, 1.0, "full_2r")
        else:
            if high >= pos.stop:
                return close_qty(pos.stop, 1.0, "stop_be")
            if low <= pos.tp2:
                return close_qty(pos.tp2, 1.0, "full_2r")

    return pnl_delta


def run_backtest(df: pd.DataFrame, initial_capital: float, risk_pct: float) -> tuple[pd.DataFrame, pd.DataFrame, Dict[str, int], float]:
    capital = initial_capital
    open_positions: List[Position] = []
    closed: List[Position] = []
    equity_rows: List[Dict[str, float]] = []
    skip: Dict[str, int] = {}

    current_day = None
    day_start_capital = initial_capital
    day_blocked = False

    def log_skip(reason: str) -> None:
        skip[reason] = skip.get(reason, 0) + 1

    start_idx = max(ATR_PERIOD + 2, SWING_LOOKBACK + 2, VOL_MA_PERIOD + 2)

    for i in range(start_idx, len(df)):
        row = df.iloc[i]
        ts = row["ts"]

        # Day circuit breaker reset.
        d = ts.date()
        if current_day != d:
            current_day = d
            day_start_capital = capital
            day_blocked = False

        # Update open positions first.
        for p in list(open_positions):
            capital += maybe_close_position(p, row)
            if p.closed:
                open_positions.remove(p)
                closed.append(p)

        # Track equity with unrealized PnL at close.
        close_px = float(row["close"])
        unreal = 0.0
        for p in open_positions:
            if p.direction == "long":
                unreal += (close_px - p.entry_price) * p.remaining_qty
            else:
                unreal += (p.entry_price - close_px) * p.remaining_qty
        equity_rows.append({"ts": ts, "equity": capital + unreal, "cash": capital})

        # Daily breaker for NEW entries only.
        if not day_blocked and capital <= day_start_capital * (1.0 - DAILY_CIRCUIT_BREAKER_PCT):
            day_blocked = True

        if day_blocked:
            log_skip("daily_circuit_breaker")
            continue

        if len(open_positions) >= MAX_CONCURRENT:
            log_skip("max_concurrent")
            continue

        if not in_session(int(row["hour"])):
            log_skip("outside_session")
            continue

        trap = df.iloc[i - 1]
        if pd.isna(trap["swing_high"]) or pd.isna(trap["swing_low"]) or pd.isna(trap["atr"]) or pd.isna(trap["vol_ma20"]):
            log_skip("indicator_warmup")
            continue

        # Layer 1: trend bias.
        h1_ema = row["h1_ema21"]
        if pd.isna(h1_ema):
            log_skip("no_h1_bias")
            continue

        # Layer 2: trap detection (previous candle).
        bull_trap = (
            trap["low"] < trap["swing_low"]
            and trap["close"] > trap["swing_low"]
            and trap["lower_wick_ratio"] >= WICK_RATIO_MIN
            and (trap["swing_low"] - trap["low"]) <= trap["atr"] * SWEEP_ATR_MAX
        )
        bear_trap = (
            trap["high"] > trap["swing_high"]
            and trap["close"] < trap["swing_high"]
            and trap["upper_wick_ratio"] >= WICK_RATIO_MIN
            and (trap["high"] - trap["swing_high"]) <= trap["atr"] * SWEEP_ATR_MAX
        )

        if not bull_trap and not bear_trap:
            log_skip("no_micro_trap")
            continue

        # Layer 3: volume confirmation on trap candle.
        if trap["volume"] < trap["vol_ma20"] * VOLUME_MULT:
            log_skip("volume_fail")
            continue

        # Layer 4: follow-through momentum on current candle.
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

        # L1 trend alignment check at entry candle.
        if direction == "long" and row["close"] < h1_ema:
            log_skip("counter_trend")
            continue
        if direction == "short" and row["close"] > h1_ema:
            log_skip("counter_trend")
            continue

        entry = float(row["close"])
        atr = float(row["atr"])

        if direction == "long":
            stop = float(trap["low"] - atr * ATR_STOP_MULT)
            r = entry - stop
            if r <= 0:
                log_skip("invalid_r")
                continue
            tp1 = entry + PARTIAL_EXIT_R * r
            tp2 = entry + FULL_EXIT_R * r
        else:
            stop = float(trap["high"] + atr * ATR_STOP_MULT)
            r = stop - entry
            if r <= 0:
                log_skip("invalid_r")
                continue
            tp1 = entry - PARTIAL_EXIT_R * r
            tp2 = entry - FULL_EXIT_R * r

        risk_dollars = capital * risk_pct
        qty = risk_dollars / r
        notional = qty * entry
        max_notional = capital * MAX_NOTIONAL_MULTIPLIER
        if notional > max_notional:
            qty = max_notional / entry

        if qty <= 0:
            log_skip("invalid_size")
            continue

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
        )
        capital += pos.realized_pnl  # entry fee only
        open_positions.append(pos)

    # Force-close all remaining at final close.
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
        closed.append(p)

    trades_df = pd.DataFrame(
        [
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
                "win": p.realized_pnl > 0,
            }
            for p in closed
        ]
    )

    equity_df = pd.DataFrame(equity_rows)
    return trades_df, equity_df, skip, capital


def summarize(trades: pd.DataFrame, equity: pd.DataFrame, skip: Dict[str, int], initial_capital: float, final_capital: float, days: int) -> Dict[str, float]:
    if trades.empty:
        print("No trades found.")
        return {}

    wins = trades[trades["win"]]
    losses = trades[~trades["win"]]

    total_trades = int(len(trades))
    win_count = int(len(wins))
    loss_count = int(len(losses))
    win_rate = (win_count / total_trades) * 100.0 if total_trades else 0.0

    total_pnl = float(trades["pnl"].sum())
    total_fees = float(trades["fees"].sum())
    total_return = ((final_capital / initial_capital) - 1.0) * 100.0

    avg_win = float(wins["pnl"].mean()) if win_count else 0.0
    avg_loss = float(losses["pnl"].mean()) if loss_count else 0.0
    pf = abs(float(wins["pnl"].sum()) / float(losses["pnl"].sum())) if loss_count and float(losses["pnl"].sum()) != 0 else float("inf")
    expectancy = (win_rate / 100.0) * avg_win + (1.0 - win_rate / 100.0) * avg_loss

    max_consec_loss = 0
    cur = 0
    for w in trades["win"].tolist():
        if not w:
            cur += 1
            max_consec_loss = max(max_consec_loss, cur)
        else:
            cur = 0

    equity = equity.copy()
    equity["peak"] = equity["equity"].cummax()
    equity["drawdown"] = (equity["equity"] - equity["peak"]) / equity["peak"] * 100.0
    max_dd = float(equity["drawdown"].min()) if not equity.empty else 0.0

    trades_per_day = total_trades / max(days, 1)

    print("\n" + "=" * 64)
    print("PHANTOM Results")
    print("=" * 64)
    print(f"Starting Capital: ${initial_capital:,.2f}")
    print(f"Final Capital:    ${final_capital:,.2f}")
    print(f"Total Return:     {total_return:+.2f}%")
    print(f"Net PnL:          ${total_pnl:+,.2f}")
    print(f"Total Fees:       ${total_fees:,.2f}")
    print("-" * 64)
    print(f"Total Trades:     {total_trades}")
    print(f"Win Rate:         {win_rate:.1f}% ({win_count}W/{loss_count}L)")
    print(f"Profit Factor:    {pf:.2f}")
    print(f"Expectancy:       ${expectancy:+.2f} per trade")
    print(f"Trades/Day:       {trades_per_day:.2f}")
    print(f"Max Drawdown:     {max_dd:.2f}%")
    print(f"Max Consec Loss:  {max_consec_loss}")
    print("-" * 64)
    print("Skip Reasons:")
    for k, v in sorted(skip.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {k:<28} {v:>7,}")
    print("=" * 64)

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


def save_outputs(outdir: str, trades: pd.DataFrame, equity: pd.DataFrame, summary: Dict[str, float], skip: Dict[str, int], args: argparse.Namespace) -> None:
    os.makedirs(outdir, exist_ok=True)

    trades_path = os.path.join(outdir, "phantom_backtest_trades.csv")
    report_path = os.path.join(outdir, "phantom_backtest_report.md")
    results_png = os.path.join(outdir, "phantom_backtest_results.png")
    zones_png = os.path.join(outdir, "phantom_backtest_zones.png")

    trades.to_csv(trades_path, index=False)
    print(f"Trades saved: {trades_path}")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# PHANTOM Backtest Report\n\n")
        f.write(f"- Symbol: {args.symbol}\n")
        f.write(f"- Interval: {args.interval}\n")
        f.write(f"- Days: {args.days}\n")
        if args.data_file:
            f.write(f"- Data File: {args.data_file}\n")
        f.write(f"- Capital: ${args.capital:,.2f}\n")
        f.write(f"- Risk/Trade: {args.risk:.4f}\n\n")
        if summary:
            f.write("## Summary\n\n")
            for k, v in summary.items():
                if "pct" in k:
                    f.write(f"- {k}: {v:.2f}%\n")
                elif "capital" in k or "pnl" in k or "fees" in k or "expectancy" in k:
                    f.write(f"- {k}: ${v:,.2f}\n")
                else:
                    f.write(f"- {k}: {v}\n")
        f.write("\n## Skip Reasons\n\n")
        for k, v in sorted(skip.items(), key=lambda x: (-x[1], x[0])):
            f.write(f"- {k}: {v}\n")

    print(f"Report saved: {report_path}")

    if args.skip_plots:
        print("Plots skipped (--skip-plots)")
        return

    eq = equity.copy()
    eq["peak"] = eq["equity"].cummax()
    eq["drawdown"] = (eq["equity"] - eq["peak"]) / eq["peak"] * 100.0

    fig, axes = plt.subplots(3, 1, figsize=(16, 12), sharex=True)

    axes[0].plot(eq["ts"], eq["equity"], color="#1f77b4", lw=1.2)
    axes[0].set_title("PHANTOM Equity Curve")
    axes[0].set_ylabel("Equity")

    axes[1].fill_between(eq["ts"], 0, eq["drawdown"], color="#d62728", alpha=0.3)
    axes[1].plot(eq["ts"], eq["drawdown"], color="#d62728", lw=1.0)
    axes[1].set_title("Drawdown (%)")
    axes[1].set_ylabel("Drawdown %")

    if not trades.empty:
        axes[2].bar(np.arange(len(trades)), trades["pnl"], color=np.where(trades["pnl"] > 0, "#2ca02c", "#d62728"))
    axes[2].axhline(0, color="black", lw=0.8)
    axes[2].set_title("Trade PnL")
    axes[2].set_ylabel("PnL")
    axes[2].set_xlabel("Trade Index")

    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    plt.tight_layout()
    plt.savefig(results_png, dpi=140)
    plt.close(fig)
    print(f"Chart saved: {results_png}")

    # Lightweight zone proxy chart: draw rolling swing bounds.
    # We only need a fast contextual chart for recent behavior.
    look = min(2000, len(equity))
    fig2, ax2 = plt.subplots(figsize=(16, 6))
    if look > 0:
        ax2.plot(equity["ts"].iloc[-look:], equity["equity"].iloc[-look:], color="#1f77b4", lw=1.0)
    ax2.set_title("PHANTOM Recent Equity Context")
    ax2.set_ylabel("Equity")
    plt.tight_layout()
    plt.savefig(zones_png, dpi=140)
    plt.close(fig2)
    print(f"Zone chart saved: {zones_png}")


def main() -> None:
    args = parse_args()

    if args.data_file:
        print(f"Loading MT5 data file: {args.data_file}")
        df = load_mt5_data(args.data_file)
        data_span_days = max(1, int(np.ceil((df["ts"].iloc[-1] - df["ts"].iloc[0]).total_seconds() / 86400)))
        args.days = data_span_days
        args.interval = "1m"
    else:
        df, used_symbol = fetch_minute_data(args.symbol, args.interval, args.days)
        args.symbol = used_symbol
    print(f"Total candles: {len(df):,}")
    print(f"Data: {df['ts'].iloc[0]} -> {df['ts'].iloc[-1]}")

    df = add_indicators(df)

    trades, equity, skip, final_capital = run_backtest(df, args.capital, args.risk)

    summary = summarize(trades, equity, skip, args.capital, final_capital, args.days)
    save_outputs(args.outdir, trades, equity, summary, skip, args)

    print("\nBacktest complete. Files saved:")
    print(f"  {os.path.join(args.outdir, 'phantom_backtest_trades.csv')}")
    print(f"  {os.path.join(args.outdir, 'phantom_backtest_report.md')}")
    if not args.skip_plots:
        print(f"  {os.path.join(args.outdir, 'phantom_backtest_results.png')}")
        print(f"  {os.path.join(args.outdir, 'phantom_backtest_zones.png')}")


if __name__ == "__main__":
    main()
