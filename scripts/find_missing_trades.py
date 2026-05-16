#!/usr/bin/env python3
import csv
from datetime import datetime

mt5_file='/Users/niko/Documents/projects/niko-ai/phantom_mql5_trade_log.csv'
py_file='/Users/niko/Documents/projects/niko-ai/backtest_artifacts/high-vs-high2-20260429_154936/high/phantom_p2_trades_US100_P2B.csv'

mt5_entries = []
with open(mt5_file,'r') as f:
    r=csv.DictReader(f, delimiter=';')
    for row in r:
        try:
            t=datetime.strptime(row['entry_time_utc'],'%Y.%m.%d %H:%M:%S')
        except Exception:
            continue
        mt5_entries.append({'time':t,'dir':row.get('direction','').lower(),'row':row})

py_entries = []
with open(py_file,'r') as f:
    r=csv.DictReader(f)
    for row in r:
        ts=row.get('entry_ts','')
        try:
            t=datetime.strptime(ts,'%Y-%m-%d %H:%M:%S')
        except Exception:
            try:
                t=datetime.strptime(ts,'%Y-%m-%d')
            except Exception:
                continue
        py_entries.append({'time':t,'dir':row.get('dir','').lower(),'row':row})

start=datetime(2025,12,1)
end=datetime(2026,3,31,23,59,59)
py_window=[p for p in py_entries if start<=p['time']<=end]
mt5_window=[m for m in mt5_entries if start<=m['time']<=end]

missing=[]
for p in py_window:
    found=False
    for m in mt5_window:
        if abs((m['time']-p['time']).total_seconds())<=15*60 and m['dir']==p['dir']:
            found=True
            break
    if not found:
        missing.append(p)

out='/Users/niko/Documents/projects/niko-ai/mt5_missing_python_trades._export.csv'
with open(out,'w',newline='') as f:
    w=csv.writer(f)
    w.writerow(['entry_ts','dir','entry_row'])
    for p in missing:
        w.writerow([p['time'].strftime('%Y-%m-%d %H:%M:%S'),p['dir'],p['row']])

print('Python in window:',len(py_window))
print('MT5 in window:',len(mt5_window))
print('Missing trades count:',len(missing))
print('Wrote missing list to',out)
