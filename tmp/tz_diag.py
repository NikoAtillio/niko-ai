import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd

log = Path.home() / "Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/phantom_bridge_log.csv"
rows = list(csv.reader(log.open(), delimiter=";"))

init_idxs = [i for i, r in enumerate(rows) if len(r) >= 2 and r[1] == "INIT"]
start = init_idxs[-1]
end = len(rows)
for i in range(start, len(rows)):
    if len(rows[i]) >= 2 and rows[i][1] in ("SYNTH_SUMMARY", "DEINIT"):
        end = i + 1
        if rows[i][1] == "SYNTH_SUMMARY":
            break
blk = rows[start:end]

opens = []
for r in blk:
    if len(r) >= 4 and r[1] == "OPEN":
        ts = pd.to_datetime(r[0], format="%Y.%m.%d %H:%M:%S")
        vals = {}
        for x in r[3:]:
            if "=" in x:
                k, v = x.split("=", 1)
                vals[k] = v
        opens.append(
            {
                "id": r[2],
                "mt5_ts": str(ts),
                "mt5_fill": float(vals.get("fill", "nan")),
                "want_entry": float(vals.get("want_entry", "nan")),
            }
        )

m5 = "data/US100/US100.cash_M5_2021.01.21-2026.03.31"
df = pd.read_csv(m5, sep="\t")
df.columns = [c.strip("<>").lower() for c in df.columns]
df["ts"] = pd.to_datetime(
    df["date"].astype(str).str.strip() + " " + df["time"].astype(str).str.strip(),
    errors="coerce",
)
idx = df[["ts", "open", "high", "low", "close"]].dropna().set_index("ts")

mt5_open_err = []
for o in opens:
    ts = pd.Timestamp(o["mt5_ts"])
    if ts in idx.index:
        mt5_open_err.append(abs(float(idx.loc[ts, "open"]) - o["mt5_fill"]))

scores = []
for h in range(-12, 13):
    errs = []
    for o in opens:
        ts = pd.Timestamp(o["mt5_ts"]) + pd.Timedelta(hours=h)
        if ts in idx.index:
            errs.append(abs(float(idx.loc[ts, "close"]) - o["want_entry"]))
    if errs:
        scores.append(
            {
                "offset_h": h,
                "mean_abs_err": float(np.mean(errs)),
                "max_abs_err": float(np.max(errs)),
                "n": len(errs),
            }
        )
scores = sorted(scores, key=lambda x: x["mean_abs_err"])
best = scores[0]["offset_h"]

per = []
for o in opens:
    mt5_ts = pd.Timestamp(o["mt5_ts"])
    shifted = mt5_ts + pd.Timedelta(hours=best)
    if shifted in idx.index and mt5_ts in idx.index:
        per.append(
            {
                "id": o["id"],
                "mt5_ts": str(mt5_ts),
                "shifted_ts": str(shifted),
                "py_want_entry": o["want_entry"],
                "raw_close_at_shifted": float(idx.loc[shifted, "close"]),
                "diff_close_minus_py": float(idx.loc[shifted, "close"] - o["want_entry"]),
                "mt5_fill": o["mt5_fill"],
                "raw_open_at_mt5_ts": float(idx.loc[mt5_ts, "open"]),
                "diff_open_minus_fill": float(idx.loc[mt5_ts, "open"] - o["mt5_fill"]),
            }
        )

res = {
    "open_events": len(opens),
    "mt5_fill_vs_raw_open_0h_mean_abs_err": float(np.mean(mt5_open_err)) if mt5_open_err else None,
    "mt5_fill_vs_raw_open_0h_max_abs_err": float(np.max(mt5_open_err)) if mt5_open_err else None,
    "best_offsets_for_py_entry_vs_raw_close": scores[:5],
    "selected_best_offset_h": best,
    "per_trade_at_best_offset": per,
}

print(json.dumps(res, indent=2))
