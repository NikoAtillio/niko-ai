import json
from pathlib import Path


REPO = Path("/Users/niko/Documents/projects/niko-ai")
FILES = [
    REPO / "signals" / "phantom_signals.jsonl",
    REPO / "signals" / "phantom_signals_2022_full.jsonl",
    REPO / "saved_runs" / "2026-06-16_6y" / "cash" / "phantom_signals_cash.jsonl",
    REPO / "saved_runs" / "2026-06-16_6y" / "ftmo" / "phantom_signals_ftmo.jsonl",
    REPO / "recovered_sources" / "restore_backups" / "phantom_signals.pre_rollback_20260605_203639.jsonl",
]


def median(values):
    return values[len(values) // 2] if values else None


def main():
    for path in FILES:
        if not path.exists():
            continue

        qty_values = []
        conf_values = []
        sess_values = []
        regime_values = []
        opens = 0

        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                obj = json.loads(raw_line)
                if obj.get("action") != "open":
                    continue
                opens += 1

                if obj.get("qty") is not None:
                    try:
                        qty_values.append(float(obj["qty"]))
                    except Exception:
                        pass

                for values, key in (
                    (conf_values, "confidence_mult"),
                    (sess_values, "session_mult"),
                    (regime_values, "regime_mult"),
                ):
                    if obj.get(key) is not None:
                        try:
                            values.append(float(obj[key]))
                        except Exception:
                            pass

        qty_values.sort()
        conf_values.sort()
        sess_values.sort()
        regime_values.sort()

        print(path.relative_to(REPO))
        print(f"opens={opens}")
        print(f"qty=({min(qty_values) if qty_values else None},{median(qty_values)},{max(qty_values) if qty_values else None})")
        print(f"confidence_mult=({min(conf_values) if conf_values else None},{median(conf_values)},{max(conf_values) if conf_values else None})")
        print(f"session_mult=({min(sess_values) if sess_values else None},{median(sess_values)},{max(sess_values) if sess_values else None})")
        print(f"regime_mult=({min(regime_values) if regime_values else None},{median(regime_values)},{max(regime_values) if regime_values else None})")
        print()


if __name__ == "__main__":
    main()