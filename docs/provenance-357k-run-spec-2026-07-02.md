# 357k Run Provenance Spec (Canonical)

Date: 2026-07-02

## Scope
This document captures the exact provenance tuple for the historical run family matching:
- M5 2023-01-01 to 2026-01-01
- PhantomBridge_v2 style controls
- InpBrokerMode=0
- InpUsePythonSizing=false
- Daily/Max loss 5.0/10.0
- High-trade replay stream (about 1265 trades reported, 1268 opens in the committed signal artifact)

## Canonical Tuple

1) Signal artifact commit and hash
- Commit: cc58db2c0bba24ef1a038e8fd217e09189498fa7
- File: signals/phantom_signals.jsonl
- SHA-256: ab1a6829f11f87d90405fd009d42e8b5fce2c0bc0dc56ca3a5cbce305f511756
- Open events in this blob: 1268
- Open span: 2023-01-06T15:30:00 -> 2025-12-31T20:45:00

2) Trade artifact committed alongside the signal
- Commit: cc58db2c0bba24ef1a038e8fd217e09189498fa7
- File: signals/phantom_p2_ftmo_v2_trades_US100_P2_FTMO_V2B.csv
- SHA-256: 3da91154828a4858099d0df0628ad166b312e4ba3002aff96ae6d0f01baa7425

3) Bridge code revision used for input-control match
- Branch family matched by controls: feat/phantombridge-dual-ruleset-autodetect
- File: phantom/mql5/PhantomBridge_v2.mq5
- Blob ID at cc58db2: b7d0128c5faad0fe07ab80897b9ba77979d769f0
- Controls present in this revision include:
  - InpBrokerMode = BROKER_AUTO (report shows runtime value 0)
  - InpDailyLossPct = 5.0
  - InpMaxLossPct = 10.0
  - InpFtmoRiskPct = 1.40
  - InpFtmoMaxLeverage = 30.0
  - InpUsePythonSizing = false
  - InpCashTrailMaxLossPct = 15.0
  - InpCashLotCapMult = 10.0

4) Python generator revision family for these artifacts
- Generator family: p2_ftmo_v2
- File: phantom/phantom_US100/phantom_US100_high_ftmo_EA_v2.py
- Blob ID at cc58db2: a7f8ba256202c9412ae643ec0384e09c67d9b1e1

## Branch Search Findings
The same cc58db2 signal artifact appears in all three candidate branches scanned:
- feature/us100-dd-bias-stacking
- feat/phantombridge-dual-ruleset-autodetect
- phantom-v3

Because the signal blob is identical across these branches at that commit, the branch name alone is not sufficient to identify provenance. The artifact hash is the source of truth.

## Why report may show 1265 while signal blob has 1268 opens
This can happen from MT5 runtime behavior and replay constraints (for example, rejected/skipped opens, session gating at execution layer, symbol/broker constraints, or runtime parameter overrides).

## Runtime Override Note
In this bridge revision, default InpReplayUseSignalPricing is false, but report output can show true if the value was changed in tester inputs/UI at runtime. This is expected in MT5 and does not invalidate signal provenance.

## Verification Commands

Signal/trade hash verification:

```bash
git show cc58db2:signals/phantom_signals.jsonl | shasum -a 256
git show cc58db2:signals/phantom_p2_ftmo_v2_trades_US100_P2_FTMO_V2B.csv | shasum -a 256
```

Control snapshot verification:

```bash
git show cc58db2:phantom/mql5/PhantomBridge_v2.mq5 | grep -nE "InpDailyLossPct|InpMaxLossPct|InpFtmoRiskPct|InpFtmoMaxLeverage|InpUsePythonSizing|InpBrokerMode|InpReplayUseSignalPricing"
```

Generator identity verification:

```bash
git show cc58db2:phantom/phantom_US100/phantom_US100_high_ftmo_EA_v2.py | grep -n "ENGINE_VERSION"
```
