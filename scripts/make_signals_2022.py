import csv, json
infile='backtest_artifacts/py_12m_2022_disable_ftmo/phantom_p2_ftmo_v2_trades_US100_P2_FTMO_V2B.csv'
out='signals/phantom_signals_2022_full.jsonl'
with open(infile) as f, open(out,'w') as o:
    reader=csv.DictReader(f)
    meta={"v":1,"action":"meta","engine":"p2_ftmo_v2","instrument":"US100","signal_account_size":25000.0,"ftmo":False}
    o.write(json.dumps(meta)+"\n")
    for i,row in enumerate(reader, start=1):
        id=row['entry_ts']+"#%d"%i
        open_rec={"v":1,"action":"open","id":id,"entry_ts":row['entry_ts'],"dir":row['dir'],"entry":float(row['entry']),"stop":(float(row['stop_price_initial']) if row['stop_price_initial'] else None),"tp":(float(row['exit_signal_price']) if row['exit_signal_price'] else None),"qty":float(row['qty']),"regime":row.get('regime')}
        close_rec={"v":1,"action":"close","id":id,"exit_ts":row['exit_ts'],"exit":float(row['exit']),"reason":row['exit_reason']}
        o.write(json.dumps(open_rec)+"\n")
        o.write(json.dumps(close_rec)+"\n")
print('wrote',out)
