#!/usr/bin/env python3
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import pandas as pd
import yfinance as yf


def load_trades(path: str) -> pd.DataFrame:
    trades = pd.read_csv(path)
    trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True)
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], utc=True)
    return trades.sort_values("entry_time").reset_index(drop=True)


def fetch_candles(start: pd.Timestamp, end: pd.Timestamp, symbol: str = "GC=F") -> pd.DataFrame:
    chunks = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + pd.Timedelta(days=6), end)
        candles = yf.download(
            symbol,
            start=cursor.to_pydatetime(),
            end=chunk_end.to_pydatetime(),
            interval="1m",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        if not candles.empty:
            if isinstance(candles.columns, pd.MultiIndex):
                candles.columns = candles.columns.get_level_values(0)
            candles = candles.rename(columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
            })
            candles.index = pd.to_datetime(candles.index, utc=True)
            chunks.append(candles[["open", "high", "low", "close"]].dropna())
        cursor = chunk_end + pd.Timedelta(minutes=1)

    if not chunks:
        raise ValueError("No candle data fetched for requested period.")

    out = pd.concat(chunks).sort_index()
    out = out[~out.index.duplicated(keep="first")]
    return out


def plot_chart(candles: pd.DataFrame, trades: pd.DataFrame, outpath: str) -> None:
    fig, ax = plt.subplots(figsize=(24, 10))

    x = mdates.date2num(candles.index.to_pydatetime())
    minute_w = 1.0 / (24 * 60)
    body_w = minute_w * 0.7

    for i, (_, row) in enumerate(candles.iterrows()):
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])

        color = "#1f9d55" if c >= o else "#c53030"
        ax.vlines(x[i], l, h, color=color, linewidth=0.4, alpha=0.8, zorder=1)

        low_body = min(o, c)
        body_h = abs(c - o)
        if body_h < 0.03:
            body_h = 0.03
        ax.add_patch(
            Rectangle(
                (x[i] - body_w / 2, low_body),
                body_w,
                body_h,
                facecolor=color,
                edgecolor=color,
                linewidth=0.4,
                alpha=0.85,
                zorder=2,
            )
        )

    for i, t in trades.iterrows():
        direction = t["direction"]
        win = bool(t["win"])

        entry_marker = "^" if direction == "long" else "v"
        entry_color = "#1d4ed8" if direction == "long" else "#9333ea"
        exit_color = "#15803d" if win else "#b91c1c"

        et = t["entry_time"]
        xt = t["exit_time"]
        ep = float(t["entry_price"])
        xp = float(t["exit_price"])

        ax.scatter(et, ep, marker=entry_marker, color=entry_color, s=44, zorder=5)
        ax.scatter(xt, xp, marker="x", color=exit_color, s=46, zorder=5)
        ax.plot([et, xt], [ep, xp], linestyle="--", linewidth=0.8, color=exit_color, alpha=0.7, zorder=4)

        ax.text(et, ep, f"E{i+1}", fontsize=7, color=entry_color, ha="left", va="bottom")
        ax.text(xt, xp, f"X{i+1}:{t['exit_reason']}", fontsize=7, color=exit_color, ha="left", va="bottom")

    ax.set_title("Copilot PHANTOM 30-Day Trades: 1m Candles with Entry/Exit Labels")
    ax.set_ylabel("Price")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M", tz=trades["entry_time"].dt.tz))
    plt.xticks(rotation=35)
    ax.grid(alpha=0.2)

    legend_handles = [
        Line2D([0], [0], color="#1f9d55", lw=2, label="Bull candle"),
        Line2D([0], [0], color="#c53030", lw=2, label="Bear candle"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#1d4ed8", label="Long entry", markersize=8),
        Line2D([0], [0], marker="v", color="w", markerfacecolor="#9333ea", label="Short entry", markersize=8),
        Line2D([0], [0], marker="x", color="#15803d", label="Winning exit", markersize=8),
        Line2D([0], [0], marker="x", color="#b91c1c", label="Losing exit", markersize=8),
    ]
    ax.legend(handles=legend_handles, loc="upper left")

    plt.tight_layout()
    fig.savefig(outpath, dpi=180)
    plt.close(fig)


def main() -> None:
    trades_path = "competition/copilot_30d/phantom_backtest_trades.csv"
    outpath = "competition/copilot_30d/phantom_trades_candles_30d.png"

    trades = load_trades(trades_path)
    if trades.empty:
        raise ValueError("Trade file has no rows.")

    start = trades["entry_time"].min() - pd.Timedelta(hours=4)
    end = trades["exit_time"].max() + pd.Timedelta(hours=4)

    candles = fetch_candles(start, end, symbol="GC=F")
    plot_chart(candles, trades, outpath)
    print(f"Saved: {outpath}")


if __name__ == "__main__":
    main()
