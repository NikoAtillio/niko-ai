import pandas as pd
import yfinance as yf

trades = pd.read_csv('competition/copilot_30d/phantom_backtest_trades.csv')
trades['entry_time'] = pd.to_datetime(trades['entry_time'], utc=True)
trades['exit_time'] = pd.to_datetime(trades['exit_time'], utc=True)

start = trades['entry_time'].min().floor('h')
end = trades['exit_time'].max().ceil('h')

chunks = []
cursor = start - pd.Timedelta(days=3)
while cursor < end + pd.Timedelta(days=1):
    chunk_end = min(cursor + pd.Timedelta(days=6), end + pd.Timedelta(days=1))
    df = yf.download('GC=F', start=cursor.to_pydatetime(), end=chunk_end.to_pydatetime(), interval='1m', auto_adjust=True, progress=False, threads=False)
    if not df.empty:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns={'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})
        df.index = pd.to_datetime(df.index, utc=True)
        chunks.append(df[['close']])
    cursor = chunk_end + pd.Timedelta(minutes=1)

m1 = pd.concat(chunks).sort_index()
m1 = m1[~m1.index.duplicated(keep='first')]
m1 = m1[(m1.index >= start) & (m1.index <= end)]

h4 = m1.resample('4h').last().dropna()
h4['ema21'] = h4['close'].ewm(span=21, adjust=False).mean()
h4['ema_slope'] = h4['ema21'].pct_change()

close_ret = (h4['close'].iloc[-1] / h4['close'].iloc[0] - 1) * 100
ema_ret = (h4['ema21'].iloc[-1] / h4['ema21'].iloc[0] - 1) * 100
below_ema_pct = (h4['close'] < h4['ema21']).mean() * 100
neg_slope_pct = (h4['ema_slope'] < 0).mean() * 100

print('START', start)
print('END', end)
print('H4_BARS', len(h4))
print('H4_CLOSE_RET_PCT', round(close_ret, 3))
print('H4_EMA21_RET_PCT', round(ema_ret, 3))
print('H4_CLOSE_BELOW_EMA21_PCT', round(below_ema_pct, 1))
print('H4_EMA21_NEG_SLOPE_PCT', round(neg_slope_pct, 1))
print('DIR_PNL')
print(trades.groupby('direction')['pnl'].agg(['count','sum','mean']).to_string())
