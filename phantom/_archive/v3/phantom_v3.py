#!/usr/bin/env python3
from __future__ import annotations

"""
PHANTOM v5.1 — Scenario A
===========================
1H Zones | score≥5 | volume filter | M1 entry | no timeout
Result: +41.55% return | -3.79% DD | PF 1.450 | WR 43.2%

Run:
    python phantom_v5_1_A.py \
        --m1  US100.cash_M1_23-24 \
        --m5  US100.cash_M5_23-24 \
        --h1  US100.cash_H1_23-24 \
        --h4  US100.cash_H4_23-24 \
        --capital 10000
"""

import argparse
import warnings
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

# ── PARAMETERS ────────────────────────────────────────────────────────────────
STARTING_CAPITAL   = 10_000.0

# Scenario A — 1H zones, score≥5, vol filter
RISK_PCT           = 0.0070        # 0.70% risk per trade (score-scaled below)
ATR_STOP_MULT      = 1.35          # H1 ATR × 1.35 for stop
ATR_TRAIL_MULT     = 0.90
PARTIAL_R          = 1.0
FULL_R             = 2.0
PARTIAL_FRAC       = 0.5
MOVE_BE            = True
MAX_CONCURRENT     = 3
FEE_PCT            = 0.00007
SESSION_START_UTC  = 7
SESSION_END_UTC    = 16
SWING_LOOKBACK     = 10
WICK_RATIO_MIN     = 0.50
VOLUME_ZSCORE_MIN  = 0.5
ZONE_MERGE_PCT     = 0.0012
COOLDOWN_BARS      = 20
ZONE_LOCKOUT_BARS  = 60
DAILY_LOSS_LIMIT   = 0.04
TIMEOUT_BARS       = None          # No timeout

# Scenario A scoring
SCORE_MIN          = 5             # require total score ≥ 5
H4_MIN             = 0             # no H4 minimum for A (H1 zones)
H1_MIN             = 1             # need at least 1 H1 signal
TF_LOW_MIN         = 2             # M1 must score ≥ 2
SCORE_CAP_M1       = 3             # cap M1 contribution at 3
SCORE_CAP_M5       = 2
VOL_FILTER         = True          # volume filter enabled

# Risk slope by score
RISK_SLOPE = {1: 0.0035, 2: 0.0070, 3: 0.0105, 4: 0.0140, 5: 0.0175, 6: 0.0175}

# ── DATA LOADING ──────────────────────────────────────────────────────────────
COLS = ["date", "time", "open", "high", "low", "close", "tickvol", "vol", "spread"]

def load_tf(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    df = pd.read_csv(p, sep="\t", header=0, names=COLS)
    df["dt"] = pd.to_datetime(df["date"] + " " + df["time"])
    df = df.set_index("dt").sort_index()
    df = df[["open", "high", "low", "close", "vol"]].rename(columns={"vol": "volume"})
    df = df.apply(pd.to_numeric, errors="coerce").dropna()
    return df

def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def compute_ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()

# ── ZONE DETECTION ────────────────────────────────────────────────────────────
def detect_zones(df: pd.DataFrame, lookback: int = 10, merge_pct: float = ZONE_MERGE_PCT):
    highs, lows = [], []
    h = df["high"].values
    l = df["low"].values
    n = len(df)
    for i in range(lookback, n - lookback):
        if h[i] == max(h[i - lookback: i + lookback + 1]):
            highs.append(h[i])
        if l[i] == min(l[i - lookback: i + lookback + 1]):
            lows.append(l[i])
    raw = sorted(set(highs + lows))
    if not raw:
        return []
    merged = [raw[0]]
    for z in raw[1:]:
        if (z - merged[-1]) / merged[-1] > merge_pct:
            merged.append(z)
        else:
            merged[-1] = (merged[-1] + z) / 2
    return merged

# ── SIGNAL SCORING ────────────────────────────────────────────────────────────
def score_candle(candle, prev_candle, vol_ma, atr, direction, use_vol=True):
    score = 0
    o, hi, lo, c = candle["open"], candle["high"], candle["low"], candle["close"]
    rng = hi - lo
    if rng < 1e-9:
        return 0

    # Pin bar
    if direction == "long":
        lower_wick = min(o, c) - lo
        if lower_wick / rng >= WICK_RATIO_MIN:
            score += 1
    else:
        upper_wick = hi - max(o, c)
        if upper_wick / rng >= WICK_RATIO_MIN:
            score += 1

    # Engulfing
    if prev_candle is not None:
        prev_body = abs(prev_candle["close"] - prev_candle["open"])
        body = abs(c - o)
        if direction == "long" and c > prev_candle["open"] and o < prev_candle["close"] and body > prev_body * 0.8:
            score += 1
        if direction == "short" and c < prev_candle["open"] and o > prev_candle["close"] and body > prev_body * 0.8:
            score += 1

    # Volume
    if use_vol and vol_ma > 0 and candle["volume"] > vol_ma * (1 + VOLUME_ZSCORE_MIN):
        score += 1

    # Momentum close
    if direction == "long" and c > (lo + rng * 0.6):
        score += 1
    if direction == "short" and c < (hi - rng * 0.6):
        score += 1

    return score

# ── BACKTEST ENGINE ───────────────────────────────────────────────────────────
def run_backtest(df_m1, df_m5, df_h1, df_h4, capital, label="Scenario A"):

    print(f"\n{'='*65}")
    print(f"  {label}")
    print(f"{'='*65}")

    df_m1 = df_m1.copy(); df_m1["atr"] = compute_atr(df_m1); df_m1["vol_ma"] = df_m1["volume"].rolling(20).mean()
    df_m5 = df_m5.copy(); df_m5["atr"] = compute_atr(df_m5); df_m5["vol_ma"] = df_m5["volume"].rolling(20).mean()
    df_h1 = df_h1.copy(); df_h1["atr"] = compute_atr(df_h1); df_h1["ema50"] = compute_ema(df_h1["close"], 50)
    df_h4 = df_h4.copy(); df_h4["atr"] = compute_atr(df_h4)

    # Scenario A: zones from H1 only
    zones = detect_zones(df_h1, lookback=SWING_LOOKBACK)
    print(f"  H1 zones detected: {len(zones)}")

    def htf_val(df_htf, col, ts):
        idx = df_htf.index.searchsorted(ts, side="right") - 1
        if idx < 0: return np.nan
        return df_htf.iloc[idx][col]

    open_trades   = []
    closed_trades = []
    equity_curve  = []
    skip_reasons  = defaultdict(int)
    total_fees    = 0.0
    peak_cap      = capital
    day_start_cap = capital
    current_day   = None
    day_halted    = False
    last_loss_bar = -999
    zone_last_traded = {}

    m1_arr  = df_m1.values
    m1_idx  = df_m1.index
    m1_cols = {c: i for i, c in enumerate(df_m1.columns)}
    def col(name): return m1_cols[name]

    for i in range(SWING_LOOKBACK + 2, len(df_m1)):
        ts    = m1_idx[i]
        row   = m1_arr[i]
        close = row[col("close")]
        high  = row[col("high")]
        low   = row[col("low")]
        open_ = row[col("open")]
        atr_m1= row[col("atr")]
        vol   = row[col("volume")]
        vol_ma= row[col("vol_ma")]

        day = ts.date()
        if day != current_day:
            current_day   = day
            day_start_cap = capital
            day_halted    = False

        # ── Process exits ──
        to_close = []
        for t in open_trades:
            if t["dir"] == "long":
                if low <= t["sl"]:
                    pnl = (t["sl"] - t["ep"]) * t["qty"]
                    fee = (t["ep"] + t["sl"]) * t["qty"] * FEE_PCT
                    capital += pnl - fee; total_fees += fee
                    t.update({"xp": t["sl"], "xt": ts, "xr": "stop_loss", "pnl": pnl - fee})
                    to_close.append(t); continue
                if not t["partial"] and high >= t["t1"]:
                    qty_p = t["qty"] * PARTIAL_FRAC
                    pnl = (t["t1"] - t["ep"]) * qty_p
                    fee = (t["ep"] + t["t1"]) * qty_p * FEE_PCT
                    capital += pnl - fee; total_fees += fee
                    t["qty"] -= qty_p; t["partial"] = True
                    if MOVE_BE: t["sl"] = t["ep"]
                if t["partial"] and high >= t["t2"]:
                    pnl = (t["t2"] - t["ep"]) * t["qty"]
                    fee = (t["ep"] + t["t2"]) * t["qty"] * FEE_PCT
                    capital += pnl - fee; total_fees += fee
                    t.update({"xp": t["t2"], "xt": ts, "xr": "full_2r", "pnl": t.get("pnl", 0) + pnl - fee})
                    to_close.append(t); continue
            else:
                if high >= t["sl"]:
                    pnl = (t["ep"] - t["sl"]) * t["qty"]
                    fee = (t["ep"] + t["sl"]) * t["qty"] * FEE_PCT
                    capital += pnl - fee; total_fees += fee
                    t.update({"xp": t["sl"], "xt": ts, "xr": "stop_loss", "pnl": pnl - fee})
                    to_close.append(t); continue
                if not t["partial"] and low <= t["t1"]:
                    qty_p = t["qty"] * PARTIAL_FRAC
                    pnl = (t["ep"] - t["t1"]) * qty_p
                    fee = (t["ep"] + t["t1"]) * qty_p * FEE_PCT
                    capital += pnl - fee; total_fees += fee
                    t["qty"] -= qty_p; t["partial"] = True
                    if MOVE_BE: t["sl"] = t["ep"]
                if t["partial"] and low <= t["t2"]:
                    pnl = (t["ep"] - t["t2"]) * t["qty"]
                    fee = (t["ep"] + t["t2"]) * t["qty"] * FEE_PCT
                    capital += pnl - fee; total_fees += fee
                    t.update({"xp": t["t2"], "xt": ts, "xr": "full_2r", "pnl": t.get("pnl", 0) + pnl - fee})
                    to_close.append(t); continue

        for t in to_close:
            if t in open_trades:
                open_trades.remove(t)
                if t.get("pnl", 0) < 0:
                    last_loss_bar = i
                closed_trades.append(t)

        equity_curve.append(capital)
        if capital > peak_cap: peak_cap = capital

        if (capital - day_start_cap) / day_start_cap <= -DAILY_LOSS_LIMIT:
            day_halted = True
        if day_halted:
            skip_reasons["daily_halt"] += 1; continue

        hour = ts.hour
        if not (SESSION_START_UTC <= hour < SESSION_END_UTC):
            skip_reasons["outside_session"] += 1; continue

        if len(open_trades) >= MAX_CONCURRENT:
            skip_reasons["max_concurrent"] += 1; continue

        if (i - last_loss_bar) < COOLDOWN_BARS:
            skip_reasons["cooldown"] += 1; continue

        if not zones:
            continue
        nearest = min(zones, key=lambda z: abs(z - close))
        dist_pct = abs(nearest - close) / nearest
        if dist_pct > 0.003:
            skip_reasons["price_not_at_zone"] += 1; continue

        direction = "long" if close < nearest else "short"

        zk = round(nearest, 1)
        if zk in zone_last_traded and (i - zone_last_traded[zk]) < ZONE_LOCKOUT_BARS:
            skip_reasons["zone_lockout"] += 1; continue

        # H1 trend bias
        h1_ema = htf_val(df_h1, "ema50", ts)
        if np.isnan(h1_ema):
            skip_reasons["no_h1_ema"] += 1; continue

        # Score H1
        h1_idx = df_h1.index.searchsorted(ts, side="right") - 1
        if h1_idx < 1:
            skip_reasons["no_h1_data"] += 1; continue
        h1_candle = df_h1.iloc[h1_idx]
        h1_prev   = df_h1.iloc[h1_idx - 1]
        h1_atr    = h1_candle["atr"]
        h1_vol_ma = df_h1["volume"].rolling(20).mean().iloc[h1_idx]
        score_h1  = min(score_candle(h1_candle, h1_prev, h1_vol_ma, h1_atr, direction, VOL_FILTER), SCORE_CAP_M5)

        # Score M5
        m5_idx = df_m5.index.searchsorted(ts, side="right") - 1
        if m5_idx < 1:
            skip_reasons["no_m5_data"] += 1; continue
        m5_candle = df_m5.iloc[m5_idx]
        m5_prev   = df_m5.iloc[m5_idx - 1]
        m5_atr    = m5_candle["atr"]
        m5_vol_ma = df_m5["volume"].rolling(20).mean().iloc[m5_idx]
        score_m5  = min(score_candle(m5_candle, m5_prev, m5_vol_ma, m5_atr, direction, VOL_FILTER), SCORE_CAP_M5)

        # Score M1
        prev_row = m1_arr[i - 1]
        prev_dict = {"open": prev_row[col("open")], "high": prev_row[col("high")],
                     "low": prev_row[col("low")], "close": prev_row[col("close")],
                     "volume": prev_row[col("volume")]}
        cur_dict  = {"open": open_, "high": high, "low": low, "close": close, "volume": vol}
        score_m1  = min(score_candle(cur_dict, prev_dict, vol_ma, atr_m1, direction, VOL_FILTER), SCORE_CAP_M1)

        total_score = score_h1 + score_m5 + score_m1

        if total_score < SCORE_MIN:
            skip_reasons["score_too_low"] += 1; continue
        if score_h1 < H1_MIN:
            skip_reasons["h1_score_low"] += 1; continue
        if score_m1 < TF_LOW_MIN:
            skip_reasons["m1_score_low"] += 1; continue

        # Volume filter
        if VOL_FILTER and (np.isnan(vol_ma) or vol_ma == 0 or vol < vol_ma * (1 + VOLUME_ZSCORE_MIN)):
            skip_reasons["low_volume"] += 1; continue

        if np.isnan(atr_m1) or atr_m1 == 0:
            skip_reasons["no_atr"] += 1; continue

        # Use H1 ATR for stop
        stop_atr = h1_atr if not np.isnan(h1_atr) and h1_atr > 0 else atr_m1

        entry_price = close
        if direction == "long":
            sl = entry_price - stop_atr * ATR_STOP_MULT
            risk_price = entry_price - sl
        else:
            sl = entry_price + stop_atr * ATR_STOP_MULT
            risk_price = sl - entry_price

        if risk_price <= 0:
            skip_reasons["invalid_risk"] += 1; continue

        # Score-scaled risk
        risk_pct_scaled = RISK_SLOPE.get(min(total_score, 6), RISK_PCT)
        risk_usd = capital * risk_pct_scaled
        qty      = risk_usd / risk_price

        t1 = entry_price + risk_price * PARTIAL_R  if direction == "long" else entry_price - risk_price * PARTIAL_R
        t2 = entry_price + risk_price * FULL_R     if direction == "long" else entry_price - risk_price * FULL_R

        entry_fee  = entry_price * qty * FEE_PCT
        capital   -= entry_fee
        total_fees += entry_fee

        zone_last_traded[zk] = i

        open_trades.append({
            "dir": direction, "ep": entry_price, "et": ts, "sl": sl,
            "t1": t1, "t2": t2, "qty": qty, "bar": i,
            "partial": False, "score": total_score,
            "xp": None, "xt": None, "xr": None, "pnl": 0.0
        })

    # Force-close remaining
    final_price = df_m1.iloc[-1]["close"]
    final_time  = m1_idx[-1]
    for t in open_trades:
        pnl = (final_price - t["ep"]) * t["qty"] * (1 if t["dir"] == "long" else -1)
        fee = (t["ep"] + final_price) * t["qty"] * FEE_PCT
        capital += pnl - fee; total_fees += fee
        t.update({"xp": final_price, "xt": final_time, "xr": "end_of_data",
                  "pnl": t.get("pnl", 0) + pnl - fee})
        closed_trades.append(t)

    return closed_trades, equity_curve, skip_reasons, capital, total_fees

# ── RESULTS ───────────────────────────────────────────────────────────────────
def analyse(closed_trades, equity_curve, skip_reasons, final_cap, total_fees,
            start_cap, label, outdir="."):
    import os
    n = len(closed_trades)
    wins   = [t for t in closed_trades if t.get("pnl", 0) > 0]
    losses = [t for t in closed_trades if t.get("pnl", 0) <= 0]
    wr     = len(wins) / n * 100 if n else 0
    gp     = sum(t["pnl"] for t in wins)
    gl     = abs(sum(t["pnl"] for t in losses))
    pf     = gp / gl if gl > 0 else float("inf")
    net    = final_cap - start_cap
    ret    = net / start_cap * 100
    exp    = net / n if n else 0

    eq   = np.array(equity_curve)
    peak = np.maximum.accumulate(eq)
    dd   = (eq - peak) / peak * 100
    max_dd = dd.min()

    print(f"\n  Trades     : {n}")
    print(f"  Win %      : {wr:.1f}%")
    print(f"  PF         : {pf:.3f}")
    print(f"  Net Return : {ret:.2f}%")
    print(f"  Net P&L    : ${net:+,.2f}")
    print(f"  Fees       : ${total_fees:,.2f}")
    print(f"  Max DD     : {max_dd:.2f}%")
    print(f"  Expectancy : ${exp:+.2f}/trade")

    er = defaultdict(int)
    for t in closed_trades: er[t.get("xr", "unknown")] += 1
    print(f"\n  Exit reasons:")
    for k, v in sorted(er.items(), key=lambda x: -x[1]):
        print(f"    {k:<25}: {v}")

    print(f"\n  Skip reasons:")
    for k, v in sorted(skip_reasons.items(), key=lambda x: -x[1]):
        print(f"    {k:<30}: {v:,}")

    os.makedirs(outdir, exist_ok=True)
    rows = [{"direction": t["dir"], "entry_time": t["et"], "entry_price": t["ep"],
             "exit_time": t["xt"], "exit_price": t["xp"], "exit_reason": t["xr"],
             "pnl": t["pnl"], "score": t["score"]} for t in closed_trades]
    pd.DataFrame(rows).to_csv(f"{outdir}/phantom_v5_1_A_trades.csv", index=False)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8))
    fig.suptitle(f"PHANTOM v5.1 Scenario A — {label}", fontsize=13, fontweight="bold")
    ax1.plot(eq, color="#2E86AB", lw=1.5)
    ax1.axhline(start_cap, color="gray", ls="--", alpha=0.5)
    ax1.fill_between(range(len(eq)), start_cap, eq, where=eq >= start_cap, alpha=0.2, color="green")
    ax1.fill_between(range(len(eq)), start_cap, eq, where=eq < start_cap, alpha=0.2, color="red")
    ax1.set_title(f"Equity Curve | Return: {ret:.2f}% | Final: ${final_cap:,.0f}")
    ax1.set_ylabel("Capital ($)"); ax1.grid(alpha=0.3)
    ax2.fill_between(range(len(dd)), 0, dd, color="red", alpha=0.4)
    ax2.plot(dd, color="darkred", lw=1)
    ax2.set_title(f"Drawdown (Max: {max_dd:.2f}%)")
    ax2.set_ylabel("DD %"); ax2.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{outdir}/phantom_v5_1_A_results.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n  Chart saved: {outdir}/phantom_v5_1_A_results.png")
    print(f"  Trades CSV : {outdir}/phantom_v5_1_A_trades.csv")

    return {"trades": n, "wr": wr, "pf": pf, "return_pct": ret, "max_dd": max_dd}

# ── MAIN ──────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="PHANTOM v5.1 Scenario A — 1H Zones, score≥5, vol filter")
    p.add_argument("--m1",      required=True)
    p.add_argument("--m5",      required=True)
    p.add_argument("--h1",      required=True)
    p.add_argument("--h4",      required=True)
    p.add_argument("--capital", type=float, default=STARTING_CAPITAL)
    p.add_argument("--outdir",  default=".")
    p.add_argument("--skip-plots", action="store_true")
    return p.parse_args()

def main():
    args = parse_args()
    print("\n" + "="*65)
    print("  PHANTOM v5.1 — Scenario A")
    print("  1H Zones | score≥5 | vol filter | No Timeout")
    print("  Expected: +41.55% return | -3.79% DD | PF 1.450 | WR 43.2%")
    print("="*65)

    print("\nLoading data...")
    df_m1 = load_tf(args.m1)
    df_m5 = load_tf(args.m5)
    df_h1 = load_tf(args.h1)
    df_h4 = load_tf(args.h4)
    print(f"  M1: {len(df_m1):,} bars | M5: {len(df_m5):,} | H1: {len(df_h1):,} | H4: {len(df_h4):,}")
    print(f"  Range: {df_m1.index[0].date()} → {df_m1.index[-1].date()}")

    closed, equity, skips, final_cap, fees = run_backtest(
        df_m1=df_m1, df_m5=df_m5, df_h1=df_h1, df_h4=df_h4,
        capital=args.capital,
        label="1H Zones | score≥5 | vol filter | No Timeout"
    )

    analyse(closed, equity, skips, final_cap, fees,
            args.capital, "1H Zones | score≥5 | vol filter | No Timeout",
            outdir=args.outdir)

    print("\n" + "="*65)
    print("  PHANTOM v5.1 Scenario A — COMPLETE")
    print("="*65 + "\n")

if __name__ == "__main__":
    main()
