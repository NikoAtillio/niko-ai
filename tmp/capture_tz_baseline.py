import csv
import json
from pathlib import Path

repo = Path('/Users/niko/Documents/projects/niko-ai')
log = Path.home() / 'Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/phantom_bridge_log.csv'
rows = list(csv.reader(log.open(), delimiter=';'))

init_idxs = [i for i, r in enumerate(rows) if len(r) >= 2 and r[1] == 'INIT']
if not init_idxs:
    raise SystemExit('No INIT entries found in bridge log')
start = init_idxs[-1]
end = len(rows)
for i in range(start, len(rows)):
    if len(rows[i]) >= 2 and rows[i][1] in ('SYNTH_SUMMARY', 'DEINIT'):
        end = i + 1
        if rows[i][1] == 'SYNTH_SUMMARY':
            break
blk = rows[start:end]

opens, closes, synth = [], [], []
summary = {}
for r in blk:
    if len(r) < 3:
        continue
    tag = r[1]
    if tag == 'OPEN':
        vals = {}
        for x in r[3:]:
            if '=' in x:
                k, v = x.split('=', 1)
                vals[k] = v
        opens.append({'ts': r[0], 'id': r[2], 'dir': vals.get('dir'), 'lots': vals.get('lots'), 'want_entry': vals.get('want_entry'), 'fill': vals.get('fill')})
    elif tag == 'CLOSE':
        vals = {}
        for x in r[3:]:
            if '=' in x:
                k, v = x.split('=', 1)
                vals[k] = v
        closes.append({'ts': r[0], 'id': r[2], 'fill': vals.get('fill')})
    elif tag == 'CLOSE_SYNTH':
        vals = {}
        for x in r[3:]:
            if '=' in x:
                k, v = x.split('=', 1)
                vals[k] = v
        synth.append({'ts': r[0], 'id': r[2], **vals})
    elif tag == 'SYNTH_SUMMARY':
        for x in r[2:]:
            if '=' in x:
                k, v = x.split('=', 1)
                summary[k] = v

stream = []
with open(repo / 'signals/phantom_signals.jsonl') as f:
    for line in f:
        o = json.loads(line)
        if o.get('action') == 'close':
            stream.append({'id': o.get('id'), 'signal_ts': o.get('signal_ts'), 'exit': o.get('exit'), 'reason': o.get('reason')})

baseline = repo / 'tmp' / 'tz_alignment_baseline_6trade.md'
with baseline.open('w') as w:
    w.write('# TZ Alignment Baseline (Pre-Fix)\n\n')
    w.write('## Branch\n')
    w.write('tz-alignment-fix (created from main)\n\n')
    w.write('## Window\n')
    w.write('2025-12-29 to 2026-01-04\n\n')
    w.write('## Stream Close Events (signals/phantom_signals.jsonl)\n')
    for r in stream:
        w.write(f"- {r['id']} | ts={r['signal_ts']} | exit={r['exit']} | reason={r['reason']}\\n")
    w.write('\n## Latest Bridge Synthetic Summary\n')
    w.write(f"- trades={summary.get('trades')} wins={summary.get('wins')} net={summary.get('net')}\\n\n")
    w.write('## Latest Bridge OPEN Events (timestamps)\n')
    for r in opens:
        w.write(f"- {r['ts']} | {r['id']} | dir={r['dir']} lots={r['lots']} want_entry={r['want_entry']} fill={r['fill']}\\n")
    w.write('\n## Latest Bridge CLOSE Events (timestamps)\n')
    for r in closes:
        w.write(f"- {r['ts']} | {r['id']} | fill={r['fill']}\\n")
    w.write('\n## Latest Bridge CLOSE_SYNTH Events\n')
    for r in synth:
        w.write(f"- {r['ts']} | {r['id']} | entry={r.get('entry')} exit={r.get('exit')} qty={r.get('qty')} pnl={r.get('pnl')}\\n")

print(str(baseline))
