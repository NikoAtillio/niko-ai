import csv
import glob
import os
from pathlib import Path


REPO = Path("/Users/niko/Documents/projects/niko-ai")
TARGET_FINAL = 696138.48
PATTERNS = [
    "phantom_mt5_tester_export*.csv",
    "phantom_mt5_export*.csv",
    "phantom_mql5_trade_log*.csv",
    "saved_runs/**/*.csv",
    "_docs_archive/backtest_artifacts/**/*.csv",
    "backtest_artifacts/**/*.csv",
]


def parse_file(path: Path):
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        first = handle.readline().strip("\n\r")
        if not first:
            return None
        delimiter = ";" if (";" in first and "," not in first) else ","
        header = [part.strip() for part in first.split(delimiter)]
        net_col = next((col for col in ("net_profit", "pnl") if col in header), None)
        qty_col = next((col for col in ("volume", "qty") if col in header), None)
        conf_col = "confidence_mult" if "confidence_mult" in header else None
        if not net_col:
            return None

        reader = csv.DictReader(handle, fieldnames=header, delimiter=delimiter)
        total = 0.0
        rows = 0
        qty_values = []
        conf_values = []

        for row in reader:
            rows += 1
            try:
                value = row.get(net_col)
                if value not in (None, ""):
                    total += float(value)
            except Exception:
                pass
            if qty_col:
                try:
                    value = row.get(qty_col)
                    if value not in (None, ""):
                        qty_values.append(float(value))
                except Exception:
                    pass
            if conf_col:
                try:
                    value = row.get(conf_col)
                    if value not in (None, ""):
                        conf_values.append(float(value))
                except Exception:
                    pass

        qty_values.sort()
        conf_values.sort()

        def median(values):
            return values[len(values) // 2] if values else None

        return {
            "path": str(path.relative_to(REPO)),
            "rows": rows,
            "sum_net": total,
            "final_10k": 10000.0 + total,
            "qty_min": min(qty_values) if qty_values else None,
            "qty_med": median(qty_values),
            "qty_max": max(qty_values) if qty_values else None,
            "conf_min": min(conf_values) if conf_values else None,
            "conf_med": median(conf_values),
            "conf_max": max(conf_values) if conf_values else None,
        }


def main():
    paths = []
    seen = set()
    for pattern in PATTERNS:
        for raw_path in glob.glob(str(REPO / pattern), recursive=True):
            if os.path.isfile(raw_path) and raw_path not in seen:
                seen.add(raw_path)
                paths.append(Path(raw_path))

    rows = []
    for path in paths:
        try:
            parsed = parse_file(path)
        except Exception:
            parsed = None
        if parsed:
            rows.append(parsed)

    rows.sort(key=lambda row: abs(row["final_10k"] - TARGET_FINAL))

    print("TOP_CLOSEST_TO_696138_48")
    for row in rows[:120]:
        print(
            f"{row['path']}|rows={row['rows']}|sum_net={row['sum_net']:.2f}|"
            f"final_10k={row['final_10k']:.2f}|"
            f"qty=({row['qty_min']},{row['qty_med']},{row['qty_max']})|"
            f"conf=({row['conf_min']},{row['conf_med']},{row['conf_max']})"
        )

    print()
    print("CURRENT_AND_KEY_EXPORTS")
    keys = [
        "phantom_mt5_tester_export_20260518_120212.csv",
        "phantom_mt5_tester_export_latest.csv",
        "phantom_mql5_trade_log.csv",
        "phantom_mql5_trade_log_latest.csv",
        "saved_runs/2026-06-16_6y/cash/phantom_p2_ftmo_v2_trades_US100_P2_FTMO_V2B.csv",
        "saved_runs/v7_nov01_jan31/phantom_p2_ftmo_trades_US100_P2_FTMOB.csv",
    ]
    for key in keys:
        row = next((item for item in rows if item["path"] == key), None)
        if row:
            print(
                f"{row['path']}|rows={row['rows']}|sum_net={row['sum_net']:.2f}|"
                f"final_10k={row['final_10k']:.2f}|"
                f"qty=({row['qty_min']},{row['qty_med']},{row['qty_max']})|"
                f"conf=({row['conf_min']},{row['conf_med']},{row['conf_max']})"
            )


if __name__ == "__main__":
    main()