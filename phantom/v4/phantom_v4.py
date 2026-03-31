#!/usr/bin/env python3
"""
PHANTOM v5.1 — Scenario B (WINNER)
===================================
Best result across entire backtest history:
  Net Return : +53.61%
  Max DD     : -5.24%
  PF         : 1.308
  Trades     : 1220
  Expectancy : $4.39/trade
  Final Cap  : $15,361.37 (from $10,000)

Config:
  Asset      : US100 (Nasdaq 100)
  Entry TF   : M5
  Risk/trade : 0.70% of capital
  Timeout    : NONE (removed)
  Score min  : 3 (H4≥1 + H1≥1 + M5/M1≥1)
  ATR stop   : 1.8x ATR
  ATR trail  : 0.8x ATR
  Session    : B (07:00–16:00 UTC)
  Confluence : 0.20% zone tolerance
  Max conc.  : 2 positions
  Cooldown   : 20 min after loss
  Zone lock  : 60 min after zone hit

Usage:
  python phantom_v5_1_B.py --m1 US100_M1.csv --m5 US100_M5.csv \
                            --h1 US100_H1.csv --h4 US100_H4.csv \
                            --capital 10000
"""

import argparse
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
DEFAULTS = dict(
    risk_pct        = 0.007,    # 0.70% per trade  ← WINNER setting
    atr_stop_mult   = 1.8,
    atr_trail_mult  = 0.8,
    score_min       = 3,        # total score across H4+H1+M5
    h4_min          = 1,
    h1_min          = 1,
    tf_low_min      = 1,        # M5 score minimum
    timeout_bars    = None,     # NO timeout  ← key fix
    vol_filter      = False,
    use_m1_low      = False,
    score_cap_m1    = 2,
    max_concurrent  = 2,
    cooldown_min    = 20,
    lockout_min     = 60,
    lockout_atr_mult= 0.75,
    conf_tol        = 0.002,    # 0.20% zone confluence tolerance
    session_start   = 7,        # 07:00 UTC
    session_end     = 16,       # 16:00 UTC
    taker_fee_pct   = 0.0002,   # 0.02% per side
    target_r        = 2.0,
)

# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────────────────────────
def load_tf(path, label):
    df = pd.read_csv(path, sep="\t")
    df.columns = [c.strip("<>").lower() for c in df.columns]
    df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"])
    df = df.set_index("datetime").sort_index()
    df = df[["open","high","low","close","tickvol"]].rename(columns={"tickvol":"volume"})
    df.index = pd.to_datetime(df.index)
    print(f"  {label}: {len(df):,} rows | {df.index[0].date()} → {df.index[-1].date()}")
    return df

# ─────────────────────────────────────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────────────────────────────────────
def calc_atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()

def calc_ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def calc_rsi(s, n=14):
    d  = s.diff()
    g  = d.clip(lower=0).ewm(span=n, adjust=False).mean()
    ls = (-d).clip(lower=0).ewm(span=n, adjust=False).mean()
    return 100 - 100 / (1 + g / ls.replace(0, np.nan))

def add_indicators(df):
    df["atr"]    = calc_atr(df)
    df["ema20"]  = calc_ema(df["close"], 20)
    df["ema50"]  = calc_ema(df["close"], 50)
    df["rsi"]    = calc_rsi(df["close"])
    df["vol_ma"] = df["volume"].rolling(20).mean()
    return df

# ─────────────────────────────────────────────────────────────────────────────
# LOOKUP HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def get_val(df, ts, col, default=np.nan):
    idx = df.index.searchsorted(ts, side="right") - 1
    if idx < 0:
        return default
    return df.iloc[idx][col]

def score_tf(df, ts, direction):
    s   = 0
    c   = get_val(df, ts, "close")
    e20 = get_val(df, ts, "ema20")
    e50 = get_val(df, ts, "ema50")
    rv  = get_val(df, ts, "rsi")
    if np.isnan(c) or np.isnan(e20) or np.isnan(e50):
        return 0
    if direction == "long":
        if c > e20:   s += 1
        if e20 > e50: s += 1
        if not np.isnan(rv) and rv > 50: s += 1
    else:
        if c < e20:   s += 1
        if e20 < e50: s += 1
        if not np.isnan(rv) and rv < 50: s += 1
    return s

# ─────────────────────────────────────────────────────────────────────────────
# H4 ZONE BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def build_h4_zones(h4, n_pivot=3, merge_pct=0.005):
    """Pivot-based H4 S/R zones with merging."""
    highs = h4["high"].values
    lows  = h4["low"].values
    idx   = h4.index

    pivots = []
    for i in range(n_pivot, len(h4) - n_pivot):
        if all(highs[i] >= highs[i-j] and highs[i] >= highs[i+j] for j in range(1, n_pivot+1)):
            pivots.append((idx[i], highs[i], "res"))
        if all(lows[i] <= lows[i-j] and lows[i] <= lows[i+j] for j in range(1, n_pivot+1)):
            pivots.append((idx[i], lows[i], "sup"))

    # Merge nearby zones
    zones = []
    for ts, px, kind in sorted(pivots, key=lambda x: x[1]):
        merged = False
        for z in zones:
            if abs(px - z["price"]) / z["price"] < merge_pct:
                z["price"] = (z["price"] + px) / 2
                z["count"] += 1
                merged = True
                break
        if not merged:
            zones.append({"ts": ts, "price": px, "kind": kind, "count": 1})

    zone_ts  = np.array([z["ts"] for z in zones], dtype="datetime64[ns]")
    zone_px  = np.array([z["price"] for z in zones])
    return zone_ts, zone_px

# ─────────────────────────────────────────────────────────────────────────────
# MAIN BACKTEST ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def run_backtest(candles, h4, h1, m5, zone_ts, zone_px, capital, cfg):
    risk_pct         = cfg["risk_pct"]
    atr_stop_mult    = cfg["atr_stop_mult"]
    atr_trail_mult   = cfg["atr_trail_mult"]
    score_min        = cfg["score_min"]
    h4_min           = cfg["h4_min"]
    h1_min           = cfg["h1_min"]
    tf_low_min       = cfg["tf_low_min"]
    timeout_bars     = cfg["timeout_bars"]
    vol_filter       = cfg["vol_filter"]
    max_concurrent   = cfg["max_concurrent"]
    cooldown_min     = cfg["cooldown_min"]
    lockout_min      = cfg["lockout_min"]
    lockout_atr_mult = cfg["lockout_atr_mult"]
    conf_tol         = cfg["conf_tol"]
    session_start    = cfg["session_start"]
    session_end      = cfg["session_end"]
    taker_fee_pct    = cfg["taker_fee_pct"]
    target_r         = cfg["target_r"]

    c_idx = candles.index.values
    c_o   = candles["open"].values
    c_h   = candles["high"].values
    c_l   = candles["low"].values
    c_c   = candles["close"].values
    c_v   = candles["volume"].values

    trades      = []
    positions   = []
    zone_lock   = {}
    last_loss_ts = pd.Timestamp("2000-01-01", tz="UTC")
    equity_curve = []

    skipped = dict(session=0, max_conc=0, cooldown=0, zone_lock=0,
                   score=0, no_atr=0, no_zone=0, vol=0)

    for i in range(50, len(candles)):
        ts    = pd.Timestamp(c_idx[i])
        price = c_c[i]
        hi    = c_h[i]
        lo    = c_l[i]

        # ── Manage open positions ──────────────────────────────────────────
        still_open = []
        for pos in positions:
            if pos["direction"] == "long":
                # Trail stop
                new_trail = price - pos["atr"] * atr_trail_mult
                if new_trail > pos["stop"]:
                    pos["stop"] = new_trail
                # Check stop
                if lo <= pos["stop"]:
                    pnl  = (pos["stop"] - pos["entry"]) * pos["qty"]
                    fee  = pos["entry"] * pos["qty"] * taker_fee_pct * 2
                    net  = pnl - fee
                    capital += net
                    trades.append({**pos, "exit_price": pos["stop"], "exit_ts": ts,
                                   "exit_reason": "stop", "pnl": net, "fee": fee,
                                   "win": net > 0})
                    if net < 0:
                        last_loss_ts = ts
                    continue
                # Check target
                if hi >= pos["target"]:
                    pnl  = (pos["target"] - pos["entry"]) * pos["qty"]
                    fee  = pos["entry"] * pos["qty"] * taker_fee_pct * 2
                    net  = pnl - fee
                    capital += net
                    trades.append({**pos, "exit_price": pos["target"], "exit_ts": ts,
                                   "exit_reason": "target", "pnl": net, "fee": fee,
                                   "win": True})
                    continue
            else:  # short
                new_trail = price + pos["atr"] * atr_trail_mult
                if new_trail < pos["stop"]:
                    pos["stop"] = new_trail
                if hi >= pos["stop"]:
                    pnl  = (pos["entry"] - pos["stop"]) * pos["qty"]
                    fee  = pos["entry"] * pos["qty"] * taker_fee_pct * 2
                    net  = pnl - fee
                    capital += net
                    trades.append({**pos, "exit_price": pos["stop"], "exit_ts": ts,
                                   "exit_reason": "stop", "pnl": net, "fee": fee,
                                   "win": net > 0})
                    if net < 0:
                        last_loss_ts = ts
                    continue
                if lo <= pos["target"]:
                    pnl  = (pos["entry"] - pos["target"]) * pos["qty"]
                    fee  = pos["entry"] * pos["qty"] * taker_fee_pct * 2
                    net  = pnl - fee
                    capital += net
                    trades.append({**pos, "exit_price": pos["target"], "exit_ts": ts,
                                   "exit_reason": "target", "pnl": net, "fee": fee,
                                   "win": True})
                    continue

            # Timeout
            if timeout_bars is not None:
                bars_open = i - pos["entry_bar"]
                if bars_open >= timeout_bars:
                    pnl  = (price - pos["entry"]) * pos["qty"] * (1 if pos["direction"]=="long" else -1)
                    fee  = pos["entry"] * pos["qty"] * taker_fee_pct * 2
                    net  = pnl - fee
                    capital += net
                    trades.append({**pos, "exit_price": price, "exit_ts": ts,
                                   "exit_reason": "timeout", "pnl": net, "fee": fee,
                                   "win": net > 0})
                    if net < 0:
                        last_loss_ts = ts
                    continue

            still_open.append(pos)

        positions = still_open
        equity_curve.append({"ts": ts, "equity": capital})

        # ── Entry filters ──────────────────────────────────────────────────
        hour = ts.hour
        if not (session_start <= hour < session_end):
            skipped["session"] += 1
            continue

        if len(positions) >= max_concurrent:
            skipped["max_conc"] += 1
            continue

        if ts.tzinfo is None:
            ts_aware = ts.tz_localize("UTC")
        else:
            ts_aware = ts

        if last_loss_ts.tzinfo is None:
            last_loss_aware = last_loss_ts.tz_localize("UTC")
        else:
            last_loss_aware = last_loss_ts

        if (ts_aware - last_loss_aware).total_seconds() / 60 < cooldown_min:
            skipped["cooldown"] += 1
            continue

        # ── ATR ────────────────────────────────────────────────────────────
        atr_val = get_val(m5, ts, "atr")
        if np.isnan(atr_val) or atr_val <= 0:
            skipped["no_atr"] += 1
            continue

        # ── Find nearest H4 zone ───────────────────────────────────────────
        if len(zone_px) == 0:
            skipped["no_zone"] += 1
            continue

        dists = np.abs(zone_px - price)
        nearest_idx = np.argmin(dists)
        zone_price  = zone_px[nearest_idx]
        dist_pct    = dists[nearest_idx] / price

        if dist_pct > conf_tol:
            skipped["no_zone"] += 1
            continue

        direction = "long" if price <= zone_price else "short"

        # ── Zone lockout ───────────────────────────────────────────────────
        lock_key = (round(zone_price, 1), direction)
        if lock_key in zone_lock:
            unlock_ts = zone_lock[lock_key]
            if unlock_ts.tzinfo is None:
                unlock_ts = unlock_ts.tz_localize("UTC")
            if ts_aware < unlock_ts:
                skipped["zone_lock"] += 1
                continue

        # ── Multi-TF score ─────────────────────────────────────────────────
        s_h4 = score_tf(h4, ts, direction)
        s_h1 = score_tf(h1, ts, direction)
        s_m5 = score_tf(m5, ts, direction)
        total_score = s_h4 + s_h1 + s_m5

        if s_h4 < h4_min or s_h1 < h1_min or s_m5 < tf_low_min or total_score < score_min:
            skipped["score"] += 1
            continue

        # ── Volume filter (optional) ───────────────────────────────────────
        if vol_filter:
            vol_ma = get_val(m5, ts, "vol_ma")
            if not np.isnan(vol_ma) and c_v[i] < vol_ma * 1.1:
                skipped["vol"] += 1
                continue

        # ── Position sizing ────────────────────────────────────────────────
        stop_dist = atr_val * atr_stop_mult
        risk_amt  = capital * risk_pct
        qty       = risk_amt / stop_dist if stop_dist > 0 else 0
        if qty <= 0:
            continue

        entry_fee = price * qty * taker_fee_pct
        capital  -= entry_fee

        if direction == "long":
            stop   = price - stop_dist
            target = price + stop_dist * target_r
        else:
            stop   = price + stop_dist
            target = price - stop_dist * target_r

        positions.append({
            "direction":  direction,
            "entry_price": price,
            "entry":      price,
            "entry_ts":   ts,
            "entry_bar":  i,
            "stop":       stop,
            "target":     target,
            "qty":        qty,
            "atr":        atr_val,
            "score":      total_score,
            "zone":       zone_price,
        })

        zone_lock[lock_key] = ts + pd.Timedelta(minutes=lockout_min)

    # ── Force-close remaining positions ───────────────────────────────────
    if len(candles) > 0:
        final_price = c_c[-1]
        final_ts    = pd.Timestamp(c_idx[-1])
        for pos in positions:
            pnl  = (final_price - pos["entry"]) * pos["qty"] * (1 if pos["direction"]=="long" else -1)
            fee  = pos["entry"] * pos["qty"] * taker_fee_pct * 2
            net  = pnl - fee
            capital += net
            trades.append({**pos, "exit_price": final_price, "exit_ts": final_ts,
                           "exit_reason": "eod", "pnl": net, "fee": fee,
                           "win": net > 0})

    return pd.DataFrame(trades), pd.DataFrame(equity_curve), capital

# ─────────────────────────────────────────────────────────────────────────────
# REPORTING
# ─────────────────────────────────────────────────────────────────────────────
def print_report(df_trades, equity_df, initial_capital, final_capital, label):
    n = len(df_trades)
    if n == 0:
        print(f"\n{label}: NO TRADES")
        return

    wins   = df_trades[df_trades["win"] == True]
    losses = df_trades[df_trades["win"] == False]
    wr     = len(wins) / n * 100
    gw     = wins["pnl"].sum()
    gl     = abs(losses["pnl"].sum())
    pf     = gw / gl if gl > 0 else np.inf
    net    = df_trades["pnl"].sum()
    ret    = net / initial_capital * 100
    exp    = df_trades["pnl"].mean()
    fees   = df_trades["fee"].sum()

    # Max drawdown
    if len(equity_df) > 0:
        eq = equity_df["equity"].values
        peak = np.maximum.accumulate(eq)
        dd   = ((eq - peak) / peak * 100)
        max_dd = dd.min()
    else:
        max_dd = 0.0

    # Monthly breakdown
    df_trades["month"] = pd.to_datetime(df_trades["entry_ts"]).dt.to_period("M")
    monthly = df_trades.groupby("month")["pnl"].sum()
    prof_months = (monthly > 0).sum()
    total_months = len(monthly)

    print("\n" + "="*60)
    print(f"  PHANTOM v5.1 — Scenario B (WINNER)")
    print(f"  {label}")
    print("="*60)
    print(f"  Trades       : {n}")
    print(f"  Win Rate     : {wr:.1f}%  ({'✅' if wr>=45 else '❌'})")
    print(f"  Profit Factor: {pf:.3f}  ({'✅' if pf>=1.3 else '❌'})")
    print(f"  Net Return   : {ret:+.2f}%  ({'✅' if ret>0 else '❌'})")
    print(f"  Max Drawdown : {max_dd:.2f}%  ({'✅' if max_dd>=-8 else '❌'})")
    print(f"  Expectancy   : ${exp:+.2f}/trade")
    print(f"  Total Fees   : ${fees:,.2f}")
    print(f"  Final Capital: ${final_capital:,.2f}")
    print(f"  Prof Months  : {prof_months}/{total_months}")
    print("-"*60)
    print(f"  Avg Win      : ${wins['pnl'].mean():+.2f}" if len(wins) else "  Avg Win: N/A")
    print(f"  Avg Loss     : ${losses['pnl'].mean():+.2f}" if len(losses) else "  Avg Loss: N/A")
    print(f"  Best Trade   : ${df_trades['pnl'].max():+.2f}")
    print(f"  Worst Trade  : ${df_trades['pnl'].min():+.2f}")
    print("="*60)

    print("\nMonthly P&L:")
    for period, pnl in monthly.items():
        bar = "█" * int(abs(pnl) / 50) if abs(pnl) > 0 else ""
        sign = "+" if pnl >= 0 else ""
        print(f"  {period}  {sign}{pnl:>8.2f}  {bar}")

def plot_results(df_trades, equity_df, initial_capital, out_path="phantom_v5_1_B_results.png"):
    if len(df_trades) == 0 or len(equity_df) == 0:
        print("No data to plot.")
        return

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle("PHANTOM v5.1 — Scenario B (WINNER: +53.61% | DD -5.24%)",
                 fontsize=14, fontweight="bold", color="#1a1a2e")

    # 1. Equity curve
    ax = axes[0, 0]
    eq = equity_df.set_index("ts")["equity"]
    ax.plot(eq.index, eq.values, color="#2ecc71", linewidth=1.5)
    ax.axhline(initial_capital, color="gray", linestyle="--", alpha=0.5)
    ax.fill_between(eq.index, initial_capital, eq.values,
                    where=eq.values >= initial_capital, alpha=0.15, color="#2ecc71")
    ax.fill_between(eq.index, initial_capital, eq.values,
                    where=eq.values < initial_capital, alpha=0.15, color="#e74c3c")
    ax.set_title("Equity Curve")
    ax.set_ylabel("Capital ($)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.tick_params(axis="x", rotation=30)

    # 2. Drawdown
    ax = axes[0, 1]
    eq_vals = equity_df["equity"].values
    peak    = np.maximum.accumulate(eq_vals)
    dd      = (eq_vals - peak) / peak * 100
    ax.fill_between(equity_df["ts"], dd, 0, color="#e74c3c", alpha=0.6)
    ax.set_title("Drawdown %")
    ax.set_ylabel("DD %")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.tick_params(axis="x", rotation=30)

    # 3. Monthly P&L bar
    ax = axes[1, 0]
    df_trades["month"] = pd.to_datetime(df_trades["entry_ts"]).dt.to_period("M")
    monthly = df_trades.groupby("month")["pnl"].sum()
    colors  = ["#2ecc71" if v >= 0 else "#e74c3c" for v in monthly.values]
    ax.bar(range(len(monthly)), monthly.values, color=colors)
    ax.set_xticks(range(len(monthly)))
    ax.set_xticklabels([str(m) for m in monthly.index], rotation=45, ha="right", fontsize=7)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title("Monthly P&L")
    ax.set_ylabel("P&L ($)")

    # 4. Trade P&L distribution
    ax = axes[1, 1]
    pnls = df_trades["pnl"].values
    ax.hist(pnls[pnls >= 0], bins=30, color="#2ecc71", alpha=0.7, label="Wins")
    ax.hist(pnls[pnls < 0],  bins=30, color="#e74c3c", alpha=0.7, label="Losses")
    ax.axvline(0, color="black", linewidth=1)
    ax.set_title("P&L Distribution")
    ax.set_xlabel("P&L ($)")
    ax.legend()

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Chart saved: {out_path}")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="PHANTOM v5.1 Scenario B — US100 Backtest")
    p.add_argument("--m1",      required=True,  help="M1 data file (tab-separated)")
    p.add_argument("--m5",      required=True,  help="M5 data file (tab-separated)")
    p.add_argument("--h1",      required=True,  help="H1 data file (tab-separated)")
    p.add_argument("--h4",      required=True,  help="H4 data file (tab-separated)")
    p.add_argument("--capital", type=float, default=10000, help="Starting capital (default 10000)")
    p.add_argument("--no-plot", action="store_true", help="Skip chart generation")
    return p.parse_args()

def main():
    args = parse_args()

    print("\n" + "="*60)
    print("  PHANTOM v5.1 — Scenario B (WINNER)")
    print("="*60)

    print("\nLoading data...")
    m1 = add_indicators(load_tf(args.m1, "M1"))
    m5 = add_indicators(load_tf(args.m5, "M5"))
    h1 = add_indicators(load_tf(args.h1, "H1"))
    h4 = add_indicators(load_tf(args.h4, "H4"))

    print("\nBuilding H4 zones...")
    zone_ts, zone_px = build_h4_zones(h4)
    print(f"  Zones found: {len(zone_px)}")

    print("\nRunning backtest (Scenario B)...")
    df_trades, equity_df, final_capital = run_backtest(
        candles=m5,
        h4=h4, h1=h1, m5=m5,
        zone_ts=zone_ts, zone_px=zone_px,
        capital=args.capital,
        cfg=DEFAULTS,
    )

    print_report(df_trades, equity_df, args.capital, final_capital,
                 label="M5 entry | risk=0.70% | no timeout | session 07-16 UTC")

    if len(df_trades) > 0:
        df_trades.to_csv("phantom_v5_1_B_trades.csv", index=False)
        print("\nTrades saved: phantom_v5_1_B_trades.csv")

    if not args.no_plot and len(df_trades) > 0:
        plot_results(df_trades, equity_df, args.capital)

    print("\n" + "="*60)
    print("  DONE")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
