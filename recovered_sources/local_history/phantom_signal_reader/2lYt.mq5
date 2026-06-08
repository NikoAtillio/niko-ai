//+------------------------------------------------------------------+
//| phantom_signal_reader.mq5                                        |
//| Minimal EA: reads newline-delimited JSON signals from             |
//| MT5 Common/Files/phantom_signals.jsonl and executes market orders|
//|                                                                     |
//| File roles:                                                         |
//| - signals/phantom_signals.jsonl    local Python backtest archive    |
//| - MT5 Common/Files/phantom_signals.jsonl  file this EA reads        |
//| - phantom/mql5/phantom_signal_reader.mq5  this MT5 bridge EA       |
//+------------------------------------------------------------------+
#property copyright ""
#property link      ""
#property version   "1.3"
#property strict

input int    InpMagicNumber = 123456;
input string InpSignalFile = "phantom_signals.jsonl";
input bool   InpVerboseLog = false;
input double InpQtyUnitsPerLotOverride = 0.0;
input bool   InpForceMinLotInReplay = false;
input bool   InpReplayExistingSignals = true;

enum SignalMode
{
    SIGNAL_MODE_REPLAY = 0,
    SIGNAL_MODE_LIVE   = 1
};

input SignalMode InpSignalMode = SIGNAL_MODE_REPLAY;

#include <Trade\Trade.mqh>
CTrade trade;

int g_lastLineCount = 0;

struct SignalRecord
{
    datetime signalTime;
    string   dir;
    double   entry;
    double   qty;
    double   stop;
    double   tp;
    string   entryTs;
};

SignalRecord g_signals[];
int g_nextSignalIndex = 0;
datetime g_lastReplayBarTime = 0;

void GetVolumeSpec(double &volMin, double &volStep, double &volMax, int &volDigits)
{
    volMin = 0.0;
    volStep = 0.0;
    volMax = 0.0;
    volDigits = 2;

    double value = 0.0;
    if(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN, value))
        volMin = value;
    if(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP, value))
        volStep = value;
    if(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX, value))
        volMax = value;

    // Defensive defaults for brokers/symbols that report incomplete metadata.
    if(volMin <= 0.0) volMin = 1.0;
    if(volStep <= 0.0) volStep = 1.0;
    if(volMax <= 0.0) volMax = 1000.0;

    // Derive decimal precision from the step size because SYMBOL_VOLUME_DIGITS
    // is not available in all MQL5 builds.
    double stepProbe = volStep;
    volDigits = 0;
    while(volDigits < 8 && MathAbs(stepProbe - MathRound(stepProbe)) > 1e-9)
    {
        stepProbe *= 10.0;
        volDigits++;
    }
}

int OpenSignalFile(const string &fileName, const int mode)
{
    int handle = FileOpen(fileName, mode | FILE_COMMON);
    if(handle != INVALID_HANDLE)
        return handle;

    return FileOpen(fileName, mode);
}

double AdjustVolume(double requested)
{
    if(requested <= 0.0)
        return(0.0);

    double vol_min, vol_step, vol_max;
    int vol_digits;
    GetVolumeSpec(vol_min, vol_step, vol_max, vol_digits);

    if(requested > vol_max) requested = vol_max;

    if(requested < vol_min)
        return(0.0);

    // floor to step to avoid sending an out-of-grid lot size
    double steps = MathFloor((requested - vol_min + 1e-12) / vol_step);
    double adjusted = vol_min + steps * vol_step;
    adjusted = NormalizeDouble(adjusted, vol_digits);

    if(adjusted > vol_max) adjusted = vol_max;

    return(adjusted);
}

double GetUnitsPerLot()
{
    if(InpQtyUnitsPerLotOverride > 0.0)
        return InpQtyUnitsPerLotOverride;

    double contractSize = 0.0;
    if(SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE, contractSize) && contractSize > 0.0)
        return contractSize;

    return 1.0;
}

double MapPythonQtyToLots(double pythonQty)
{
    double unitsPerLot = GetUnitsPerLot();
    if(unitsPerLot <= 0.0)
        unitsPerLot = 1.0;

    double rawLots = pythonQty / unitsPerLot;
    double adjusted = AdjustVolume(rawLots);

    if(adjusted <= 0.0)
    {
        if(InpForceMinLotInReplay)
            return MinValidVolume();
        return 0.0;
    }

    return adjusted;
}

double MinValidVolume()
{
    double vol_min, vol_step, vol_max;
    int vol_digits;
    GetVolumeSpec(vol_min, vol_step, vol_max, vol_digits);
    if(vol_min <= 0.0)
        return(0.0);
    if(vol_max > 0.0 && vol_min > vol_max)
        return(0.0);
    return(vol_min);
}

datetime CurrentReplayTime()
{
    datetime barTime = iTime(_Symbol, PERIOD_CURRENT, 0);
    if(barTime > 0)
        return barTime;
    return TimeCurrent();
}

void SortSignalsByTime()
{
    int n = ArraySize(g_signals);
    for(int i = 1; i < n; i++)
    {
        SignalRecord key = g_signals[i];
        int j = i - 1;
        while(j >= 0 && g_signals[j].signalTime > key.signalTime)
        {
            g_signals[j + 1] = g_signals[j];
            j--;
        }
        g_signals[j + 1] = key;
    }
}

// Simple helpers to extract JSON-like values from single-line JSON objects.
string _trim_copy(string text)
{
    int left = 0;
    int right = StringLen(text) - 1;

    while(left <= right)
    {
        int ch = StringGetCharacter(text, left);
        if(ch > 32) break;
        left++;
    }

    while(right >= left)
    {
        int ch = StringGetCharacter(text, right);
        if(ch > 32) break;
        right--;
    }

    if(right < left)
        return "";

    return StringSubstr(text, left, right - left + 1);
}

string _get_json_string(const string &line, const string &key)
{
    string pat = StringFormat("\"%s\"", key);
    int p = StringFind(line, pat);
    if(p == -1) return "";
    p = StringFind(line, ":", p);
    if(p == -1) return "";

    int i = p + 1;
    while(i < StringLen(line) && (StringGetCharacter(line, i) == ' ' || StringGetCharacter(line, i) == '\t')) i++;

    if(i < StringLen(line) && StringGetCharacter(line, i) == '"')
    {
        i++;
        int j = i;
        while(j < StringLen(line) && StringGetCharacter(line, j) != '"') j++;
        return StringSubstr(line, i, j - i);
    }

    int j = i;
    while(j < StringLen(line) && StringGetCharacter(line, j) != ',' && StringGetCharacter(line, j) != '}') j++;
    return _trim_copy(StringSubstr(line, i, j - i));
}

double _get_json_number(const string &line, const string &key)
{
    string v = _get_json_string(line, key);
    if(StringLen(v) == 0) return 0.0;
    return StringToDouble(v);
}

datetime _parse_signal_time(string ts)
{
    StringReplace(ts, "T", " ");
    StringReplace(ts, "-", ".");
    int z = StringFind(ts, "Z");
    if(z >= 0)
        ts = StringSubstr(ts, 0, z);
    return (datetime)StringToTime(ts);
}

void _append_signal(const SignalRecord &signal)
{
    int size = ArraySize(g_signals);
    ArrayResize(g_signals, size + 1);
    g_signals[size] = signal;
}

void LoadSignals()
{
    ArrayResize(g_signals, 0);

    int handle = OpenSignalFile(InpSignalFile, FILE_READ | FILE_TXT | FILE_ANSI);
    if(handle == INVALID_HANDLE)
    {
        PrintFormat("Failed to open signal file for replay: %s | err=%d", InpSignalFile, GetLastError());
        return;
    }

    while(!FileIsEnding(handle))
    {
        string line = _trim_copy(FileReadString(handle));
        if(StringLen(line) == 0)
            continue;

        SignalRecord signal;
        signal.entryTs = _get_json_string(line, "entry_ts");
        signal.signalTime = _parse_signal_time(signal.entryTs);
        signal.dir = _get_json_string(line, "dir");
        StringToLower(signal.dir);
        signal.entry = _get_json_number(line, "entry");
        signal.qty = _get_json_number(line, "qty");
        signal.stop = _get_json_number(line, "stop");
        signal.tp = _get_json_number(line, "tp");
        _append_signal(signal);
    }

    FileClose(handle);
    SortSignalsByTime();
}

int CountLines(const string &fileName)
{
    int handle = OpenSignalFile(fileName, FILE_READ | FILE_TXT | FILE_ANSI);
    if(handle == INVALID_HANDLE)
        return 0;

    int count = 0;
    while(!FileIsEnding(handle))
    {
        string line = FileReadString(handle);
        if(StringLen(_trim_copy(line)) > 0)
            count++;
    }
    FileClose(handle);
    return count;
}

void ProcessLine(const string &line)
{
    string cleaned = _trim_copy(line);
    if(StringLen(cleaned) == 0)
        return;

    string dir = _get_json_string(cleaned, "dir");
    StringToLower(dir);
    double entry = _get_json_number(cleaned, "entry");
    double qty = _get_json_number(cleaned, "qty");
    double stop = _get_json_number(cleaned, "stop");
    double tp = _get_json_number(cleaned, "tp");
    string ts = _get_json_string(cleaned, "entry_ts");

    if(InpVerboseLog)
        PrintFormat("Signal -> dir=%s entry=%.5f qty=%.4f stop=%.5f tp=%.5f ts=%s", dir, entry, qty, stop, tp, ts);

    bool ok = false;
    string comment = "Phantom|" + ts;

    double useQty = MapPythonQtyToLots(qty);
    if(useQty <= 0.0)
    {
        PrintFormat("Rejected %s qty=%.8f — not within symbol volume bounds", dir, qty);
        return;
    }

    if(InpVerboseLog)
    {
        double unitsPerLot = GetUnitsPerLot();
        PrintFormat("Qty map | python=%.8f unitsPerLot=%.8f -> lots=%.8f", qty, unitsPerLot, useQty);
    }

    if(dir == "long" || dir == "buy")
        ok = trade.Buy(useQty, NULL, 0, stop > 0 ? stop : 0, tp > 0 ? tp : 0, comment);
    else if(dir == "short" || dir == "sell")
        ok = trade.Sell(useQty, NULL, 0, stop > 0 ? stop : 0, tp > 0 ? tp : 0, comment);
    else
    {
        PrintFormat("Unknown direction: %s", dir);
        return;
    }

    if(ok)
    {
        double actualEntry = trade.ResultPrice();
        if(actualEntry <= 0.0 && PositionSelect(_Symbol))
            actualEntry = PositionGetDouble(POSITION_PRICE_OPEN);

        if(entry > 0.0 && actualEntry > 0.0 && stop > 0.0 && tp > 0.0)
        {
            double stopDist = MathAbs(entry - stop);
            double tpDist = MathAbs(entry - tp);
            double adjustedStop = 0.0;
            double adjustedTp = 0.0;

            if(dir == "long" || dir == "buy")
            {
                adjustedStop = actualEntry - stopDist;
                adjustedTp = actualEntry + tpDist;
            }
            else
            {
                adjustedStop = actualEntry + stopDist;
                adjustedTp = actualEntry - tpDist;
            }

            bool modified = trade.PositionModify(_Symbol, adjustedStop, adjustedTp);
            if(InpVerboseLog)
            {
                PrintFormat("Entry align | signal=%.5f actual=%.5f stopDist=%.5f tpDist=%.5f modify=%s",
                            entry,
                            actualEntry,
                            stopDist,
                            tpDist,
                            modified ? "true" : "false");
            }
        }

        PrintFormat("Executed %s qty=%.4f", dir, useQty);
        return;
    }

    int err = GetLastError();
    uint rc = trade.ResultRetcode();
    if(rc == TRADE_RETCODE_INVALID_VOLUME)
    {
        double minQty = MinValidVolume();
        if(minQty > 0.0 && minQty != useQty)
        {
            ResetLastError();
            bool retryOk = false;
            if(dir == "long" || dir == "buy")
                retryOk = trade.Buy(minQty, NULL, 0, stop > 0 ? stop : 0, tp > 0 ? tp : 0, comment + "|minvol");
            else if(dir == "short" || dir == "sell")
                retryOk = trade.Sell(minQty, NULL, 0, stop > 0 ? stop : 0, tp > 0 ? tp : 0, comment + "|minvol");

            if(retryOk)
            {
                PrintFormat("Executed %s qty=%.4f after invalid-volume retry (orig=%.4f)", dir, minQty, useQty);
                return;
            }

            PrintFormat("Retry failed %s qty=%.4f | err=%d | retcode=%d", dir, minQty, GetLastError(), trade.ResultRetcode());
        }

        // Some index CFDs accept whole lots only despite reported step metadata.
        double wholeQty = MathFloor(useQty + 1e-12);
        if(wholeQty >= 1.0 && wholeQty != useQty)
        {
            ResetLastError();
            bool wholeOk = false;
            if(dir == "long" || dir == "buy")
                wholeOk = trade.Buy(wholeQty, NULL, 0, stop > 0 ? stop : 0, tp > 0 ? tp : 0, comment + "|wholelot");
            else if(dir == "short" || dir == "sell")
                wholeOk = trade.Sell(wholeQty, NULL, 0, stop > 0 ? stop : 0, tp > 0 ? tp : 0, comment + "|wholelot");

            if(wholeOk)
            {
                PrintFormat("Executed %s qty=%.4f after whole-lot retry (orig=%.4f)", dir, wholeQty, useQty);
                return;
            }

            PrintFormat("Whole-lot retry failed %s qty=%.4f | err=%d | retcode=%d", dir, wholeQty, GetLastError(), trade.ResultRetcode());
        }
    }

    PrintFormat("Failed %s qty=%.4f | err=%d | retcode=%d", dir, useQty, err, rc);
}

void ProcessSignalsLive()
{
    int currentLines = CountLines(InpSignalFile);
    if(currentLines < g_lastLineCount)
        g_lastLineCount = 0;

    if(currentLines <= g_lastLineCount)
        return;

    int handle = OpenSignalFile(InpSignalFile, FILE_READ | FILE_TXT | FILE_ANSI);
    if(handle == INVALID_HANDLE)
    {
        PrintFormat("Failed to open signal file for live processing: %s | err=%d", InpSignalFile, GetLastError());
        return;
    }

    int lineIndex = 0;
    while(!FileIsEnding(handle))
    {
        string line = FileReadString(handle);
        if(StringLen(_trim_copy(line)) == 0)
        {
            lineIndex++;
            continue;
        }

        if(lineIndex < g_lastLineCount)
        {
            lineIndex++;
            continue;
        }

        string cleanedLine = _trim_copy(line);
        ProcessLine(cleanedLine);
        g_lastLineCount = lineIndex + 1;

        lineIndex++;
    }

    FileClose(handle);
    g_lastLineCount = currentLines;
}

void ProcessSignalsReplay()
{
    datetime nowTime = CurrentReplayTime();
    if(nowTime <= 0)
        return;

    // Replay only once per new chart bar to avoid per-tick spam and heavy loops.
    if(nowTime == g_lastReplayBarTime)
        return;
    g_lastReplayBarTime = nowTime;

    while(g_nextSignalIndex < ArraySize(g_signals))
    {
        if(g_signals[g_nextSignalIndex].signalTime > nowTime)
            break;

        string jsonLine = StringFormat(
            "{\"entry_ts\":\"%s\",\"dir\":\"%s\",\"qty\":%.10f,\"stop\":%.10f,\"tp\":%.10f}",
            g_signals[g_nextSignalIndex].entryTs,
            g_signals[g_nextSignalIndex].dir,
            g_signals[g_nextSignalIndex].qty,
            g_signals[g_nextSignalIndex].stop,
            g_signals[g_nextSignalIndex].tp
        );
        ProcessLine(jsonLine);
        g_nextSignalIndex++;
    }
}

int OnInit()
{
    trade.SetExpertMagicNumber(InpMagicNumber);
    g_lastLineCount = (InpSignalMode == SIGNAL_MODE_REPLAY && InpReplayExistingSignals) ? 0 : CountLines(InpSignalFile);
    if(InpSignalMode == SIGNAL_MODE_REPLAY)
        LoadSignals();

    PrintFormat("phantom_signal_reader initialized v1.3-force-minlot | magic=%d | mode=%s | replay=%s | start_line=%d | loaded=%d",
                     InpMagicNumber,
                     InpSignalMode == SIGNAL_MODE_REPLAY ? "replay" : "live",
                     InpReplayExistingSignals ? "true" : "false",
                     g_lastLineCount,
                     ArraySize(g_signals));
    double vol_min, vol_step, vol_max;
    int vol_digits;
    GetVolumeSpec(vol_min, vol_step, vol_max, vol_digits);
    PrintFormat("volume constraints | symbol=%s | min=%.8f | step=%.8f | max=%.8f | digits=%d | units_per_lot=%.8f",
                _Symbol,
                vol_min,
                vol_step,
                vol_max,
                vol_digits,
                GetUnitsPerLot());
    return INIT_SUCCEEDED;
}

void OnTick()
{
    if(InpSignalMode == SIGNAL_MODE_REPLAY)
        ProcessSignalsReplay();
    else
        ProcessSignalsLive();
}

void OnDeinit(const int reason)
{
}

//+------------------------------------------------------------------+