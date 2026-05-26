import re, sys
from pathlib import Path

path_str = '/Users/niko/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/Tester/Agent-127.0.0.1-3000/logs/20260519.log'
p = Path(path_str)
if not p.exists():
    print(f"File not found: {path_str}")
    sys.exit(1)

b = p.read_bytes()
if len(b) > 120_000_000:
    b = b[-120_000_000:]
    if len(b) >= 2 and len(b) % 2 != 0: b = b[1:]

text = b.decode('utf-16le', errors='ignore')
pattern = r'testing of Experts\\mql5_v1_ftmo\.ex5'
starts = [m.start() for m in re.finditer(pattern, text)]

if not starts:
    print("No segments found in the last 120MB.")
    sys.exit(0)

segs = []
for i in range(len(starts)):
    end = starts[i+1] if i+1 < len(starts) else len(text)
    segs.append(text[starts[i]:end])

for i, seg in enumerate(segs[-3:]):
    idx = len(segs) - 3 + i + 1
    print(f"\n=== Segment {idx} ===")
    for key in ["InpSessionStart", "InpSessionEnd", "InpBrokerUTCOffset", "InpAutoUTCOffset"]:
                         key}            ';                    )
        print(f"{key}: {m.group(1) if m else 'N/A'}")
    
    lines = seg.splitlines()
    ez = [l.strip() for l in lines if "ENTRY_ZONE" in l]
    ee = [l.strip() for l in lines if "ExecuteEntry" in l]
    e    e    e    e    e    e    e    e     f    e    e           e    e  "ENTRY_    e    e    e    e   
    print("First 5 ENTRY_Z    print("First 5 ENTRY_Z    print("First 5 ENTch(    print("First 5 ENTRY_Z    print("First EN    print("First 5 ENTRY_Z    print("First 5 Ece=([\d.]+).*dir=(-?\d+).*total=(\d+)', l)
        if m: print(        ioup(1)        if m: print(        ioup(1)        if m:ro        ifir:{m.g      )} | Tot:{m.group(6)}")
        e        e        e        e        e        e        e  ExecuteEntry:")
    for l in ee[:3]: print(f"  {l[:130]}")
    print("First     print("First     printl in e    print("First     130]}")
