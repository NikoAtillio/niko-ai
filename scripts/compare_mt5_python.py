"""Compare MT5 tester exports against Python phantom trade logs."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Tuple

import pandas as pd


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def load_mt5_trades(path: Path) -> pd.DataFrame:
    df = _read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "entry_time_utc" in df.columns and "entry_time" not in df.columns:
        df = df.rename(columns={"entry_time_utc": "entry_time"})
    if "exit_time_utc" in df.columns and "exit_time" not in df.columns:
        df = df.rename(columns={"exit_time_utc": "exit_time"})

    for column in ["entry_time", "exit_time", "zone_time_utc"]:
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], errors="coerce")

    if "direction" in df.columns:
        df["direction"] = df["direction"].astype(str).str.lower().replace({"buy": "long", "sell": "short"})

    numeric_columns = [
        "volume",
        "entry_price",
        "exit_price",
        "stop_price",
        "tp_price",
        "initial_risk",
        "gross_profit",
        "commission",
        "swap",
        "net_profit",
        "r_value",
        "score",
        "confidence_mult",
        "session_mult",
        "regime_mult",
        "zone_price",
        "holding_minutes",
    ]
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    return df


def load_python_trades(path: Path) -> pd.DataFrame:
    df = _read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]

    rename_map = {
        "entry_ts": "entry_time",
        "exit_ts": "exit_time",
        "pnl": "net_profit",
        "profit": "net_profit",
        "dir": "direction",
    }
    for old_name, new_name in rename_map.items():
        if old_name in df.columns and new_name not in df.columns:
            df = df.rename(columns={old_name: new_name})

    for column in ["entry_time", "exit_time"]:
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], errors="coerce")

    if "direction" in df.columns:
        df["direction"] = df["direction"].astype(str).str.lower()

    for column in ["net_profit", "volume", "entry_price", "exit_price", "r_value"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    return df


def match_trades_by_time(
    mt5_df: pd.DataFrame,
    python_df: pd.DataFrame,
    tolerance_minutes: float,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if "entry_time" not in mt5_df.columns or "entry_time" not in python_df.columns:
        raise ValueError("Both datasets must contain entry_time columns")

    mt5 = mt5_df.reset_index(drop=True).copy()
    py = python_df.reset_index(drop=True).copy()
    mt5["_matched_py_idx"] = pd.NA
    py["_matched_mt5_idx"] = pd.NA
    py["_match_diff_min"] = pd.NA

    mt5_candidates = mt5.sort_values(["entry_time", "direction"] if "direction" in mt5.columns else ["entry_time"])
    py_candidates = py.sort_values(["entry_time", "direction"] if "direction" in py.columns else ["entry_time"])

    matches = []

    for mt5_idx, mt5_row in mt5_candidates.iterrows():
        mt5_time = mt5_row["entry_time"]
        if pd.isna(mt5_time):
            continue

        direction = str(mt5_row.get("direction", "")).lower()
        candidate_pool = py_candidates
        if "direction" in py_candidates.columns and direction:
            same_direction = py_candidates[py_candidates["direction"].astype(str).str.lower() == direction]
            if not same_direction.empty:
                candidate_pool = same_direction

        best_py_idx = None
        best_diff = None
        for py_idx, py_row in candidate_pool.iterrows():
            py_time = py_row["entry_time"]
            if pd.isna(py_time):
                continue
            diff = abs((mt5_time - py_time).total_seconds()) / 60.0
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_py_idx = py_idx

        if best_py_idx is not None and best_diff is not None and best_diff <= tolerance_minutes:
            matches.append(
                {
                    "mt5_idx": mt5_idx,
                    "py_idx": best_py_idx,
                    "time_diff_min": best_diff,
                }
            )
            mt5.loc[mt5_idx, "_matched_py_idx"] = best_py_idx
            py.loc[best_py_idx, "_matched_mt5_idx"] = mt5_idx
            py.loc[best_py_idx, "_match_diff_min"] = best_diff

    matches_df = pd.DataFrame(matches)
    unmatched_mt5 = mt5[mt5["_matched_py_idx"].isna()].copy()
    unmatched_python = py[py["_matched_mt5_idx"].isna()].copy()
    return matches_df, unmatched_mt5, unmatched_python


def summarize_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "net_profit": 0.0,
            "avg_holding_minutes": 0.0,
            "profit_factor": 0.0,
        }

    pnl_col = "net_profit" if "net_profit" in df.columns else None
    pnl = df[pnl_col].fillna(0.0) if pnl_col else pd.Series([0.0] * len(df))
    winners = pnl[pnl > 0]
    losers = pnl[pnl < 0]

    gross_profit = float(winners.sum()) if not winners.empty else 0.0
    gross_loss = float(abs(losers.sum())) if not losers.empty else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    holding_minutes = df["holding_minutes"] if "holding_minutes" in df.columns else pd.Series(dtype=float)
    holding_mean = float(holding_minutes.dropna().mean()) if not holding_minutes.dropna().empty else 0.0

    return {
        "trades": int(len(df)),
        "win_rate": float((pnl > 0).mean() * 100.0),
        "net_profit": float(pnl.sum()),
        "avg_holding_minutes": holding_mean,
        "profit_factor": float(profit_factor),
    }


def build_report(mt5_df: pd.DataFrame, python_df: pd.DataFrame, matches_df: pd.DataFrame, unmatched_mt5: pd.DataFrame, unmatched_python: pd.DataFrame) -> str:
    mt5_metrics = summarize_metrics(mt5_df)
    py_metrics = summarize_metrics(python_df)

    lines = []
    lines.append("=" * 72)
    lines.append("MT5 VS PYTHON PHANTOM COMPARISON")
    lines.append("=" * 72)
    lines.append(f"MT5 trades:    {mt5_metrics['trades']}")
    lines.append(f"Python trades:  {py_metrics['trades']}")
    lines.append(f"Matched trades: {len(matches_df)}")
    lines.append(f"MT5 unmatched:  {len(unmatched_mt5)}")
    lines.append(f"Python unmatched: {len(unmatched_python)}")
    lines.append("")
    lines.append("SUMMARY METRICS")
    lines.append("-" * 72)
    lines.append(f"Win rate:       MT5={mt5_metrics['win_rate']:.2f}% | Python={py_metrics['win_rate']:.2f}%")
    lines.append(f"Net profit:     MT5={mt5_metrics['net_profit']:.2f} | Python={py_metrics['net_profit']:.2f}")
    lines.append(f"Avg hold (min): MT5={mt5_metrics['avg_holding_minutes']:.1f} | Python={py_metrics['avg_holding_minutes']:.1f}")
    lines.append(f"Profit factor:  MT5={mt5_metrics['profit_factor']:.3f} | Python={py_metrics['profit_factor']:.3f}")
    lines.append("")

    if not matches_df.empty:
        merged = matches_df.merge(mt5_df.reset_index().rename(columns={"index": "mt5_idx"}), on="mt5_idx", how="left")
        merged = merged.merge(python_df.reset_index().rename(columns={"index": "py_idx"}), on="py_idx", how="left", suffixes=("_mt5", "_py"))
        pnl_mt5 = merged["net_profit_mt5"] if "net_profit_mt5" in merged.columns else merged.get("net_profit")
        pnl_py = merged["net_profit_py"] if "net_profit_py" in merged.columns else merged.get("net_profit")
        if pnl_mt5 is not None and pnl_py is not None:
            corr = pnl_mt5.corr(pnl_py)
            lines.append("MATCHED TRADE ANALYSIS")
            lines.append("-" * 72)
            lines.append(f"PnL correlation: {corr:.3f}" if pd.notna(corr) else "PnL correlation: n/a")
            lines.append("")

        lines.append("FIRST 20 MATCHES")
        lines.append("-" * 72)
        preview = merged.head(20)
        for _, row in preview.iterrows():
            mt5_pnl = row.get("net_profit_mt5", row.get("net_profit", 0.0))
            py_pnl = row.get("net_profit_py", row.get("net_profit", 0.0))
            mt5_dir = row.get("direction_mt5", row.get("direction", "n/a"))
            py_dir = row.get("direction_py", row.get("direction", "n/a"))
            lines.append(
                f"diff={row['time_diff_min']:.1f}m | MT5 {row.get('entry_time_mt5')} {mt5_dir} pnl={mt5_pnl:.2f} | "
                f"PY {row.get('entry_time_py')} {py_dir} pnl={py_pnl:.2f}"
            )
        lines.append("")

    if not unmatched_mt5.empty:
        lines.append("UNMATCHED MT5 TRADES (first 10)")
        lines.append("-" * 72)
        preview = unmatched_mt5.head(10)
        for _, row in preview.iterrows():
            lines.append(
                f"{row.get('entry_time')} | {row.get('direction', 'n/a')} | net={row.get('net_profit', row.get('profit', 0.0))} | "
                f"score={row.get('score', 'n/a')} regime={row.get('regime', 'n/a')}"
            )
        lines.append("")

    if not unmatched_python.empty:
        lines.append("UNMATCHED PYTHON TRADES (first 10)")
        lines.append("-" * 72)
        preview = unmatched_python.head(10)
        pnl_col = "net_profit" if "net_profit" in unmatched_python.columns else None
        for _, row in preview.iterrows():
            pnl_value = row.get(pnl_col, row.get("pnl", 0.0)) if pnl_col else row.get("pnl", 0.0)
            lines.append(
                f"{row.get('entry_time')} | {row.get('direction', row.get('dir', 'n/a'))} | net={pnl_value}"
            )
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare MT5 tester export against Python phantom backtest")
    parser.add_argument("--mt5", required=True, type=Path, help="Path to phantom_mt5_tester_export.csv")
    parser.add_argument("--python", required=True, type=Path, help="Path to Python phantom trade CSV")
    parser.add_argument("--tolerance-minutes", type=float, default=5.0, help="Entry time matching tolerance")
    parser.add_argument("--output", type=Path, default=Path("comparison_report.txt"), help="Report output path")
    args = parser.parse_args()

    mt5_df = load_mt5_trades(args.mt5)
    python_df = load_python_trades(args.python)
    matches_df, unmatched_mt5, unmatched_python = match_trades_by_time(mt5_df, python_df, args.tolerance_minutes)
    report = build_report(mt5_df, python_df, matches_df, unmatched_mt5, unmatched_python)
    args.output.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nWrote report to {args.output}")


if __name__ == "__main__":
    main()
