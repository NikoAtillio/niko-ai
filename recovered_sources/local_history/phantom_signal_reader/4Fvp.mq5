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
input bool   InpFailIfReplaySignalsTooLow = true;
input int    InpMinReplaySignals = 5;

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
    string   action;
    string   signalId;
    string   dir;
    double   accountSize;
    double   entry;
    double   qty;
    double   stop;
    double   tp;
    string   entryTs;
};

SignalRecord g_signals[];
int g_nextSignalIndex = 0;
datetime g_lastReplayBarTime = 0;
double g_referenceAccountSize = 0.0;
string g_lastSignalFileSource = "none";

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
    {
        g_lastSignalFileSource = "common";
        return handle;
    }

    handle = FileOpen(fileName, mode);
    if(handle != INVALID_HANDLE)
    {
        g_lastSignalFileSource = "local";
        return handle;
    }

    g_lastSignalFileSource = "none";
    return INVALID_HANDLE;
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

double MapPythonQtyToLots(double pythonQty, double signalAccountSize)
{
    double unitsPerLot = GetUnitsPerLot();
    if(unitsPerLot <= 0.0)
        unitsPerLot = 1.0;

    // Use current balance/equity at execution time so sizing tracks account drift.
    double liveAccountSize = AccountInfoDouble(ACCOUNT_BALANCE);
    if(liveAccountSize <= 0.0)
        liveAccountSize = AccountInfoDouble(ACCOUNT_EQUITY);
    if(liveAccountSize <= 0.0)
        liveAccountSize = g_referenceAccountSize;
    if(liveAccountSize <= 0.0)
        liveAccountSize = signalAccountSize > 0.0 ? signalAccountSize : 1.0;

    double baseSignalAccountSize = signalAccountSize;
    if(baseSignalAccountSize <= 0.0)
        baseSignalAccountSize = 70000.0;

    double scale = liveAccountSize / baseSignalAccountSize;
    if(scale <= 0.0)
        scale = 1.0;

    double rawLots = (pythonQty * scale) / unitsPerLot;
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

ulong FindPositionTicketByComment(const string &comment)
{
    int total = PositionsTotal();
    for(int index = 0; index < total; index++)
    {
        ulong ticket = PositionGetTicket(index);
        if(ticket == 0)
            continue;
        if(!PositionSelectByTicket(ticket))
            continue;
        string positionComment = PositionGetString(POSITION_COMMENT);
        if(positionComment == comment)
            return ticket;
    }
    return 0;
}

bool ModifyPositionByTicket(const ulong ticket, const double stop, const double tp)
{
    if(ticket == 0)
        return false;
    if(!PositionSelectByTicket(ticket))
        return false;

    string symbol = PositionGetString(POSITION_SYMBOL);
    MqlTradeRequest request;
    MqlTradeResult result;
    ZeroMemory(request);
    ZeroMemory(result);

    request.action = TRADE_ACTION_SLTP;
    request.position = ticket;
    request.symbol = symbol;
    request.sl = stop;
    request.tp = tp;
    request.magic = InpMagicNumber;

    if(!OrderSend(request, result))
        return false;

    return (result.retcode == TRADE_RETCODE_DONE || result.retcode == TRADE_RETCODE_DONE_PARTIAL);
}

bool ClosePositionByTicket(const ulong ticket, const string &comment)
{
    if(ticket == 0)
        return false;
    if(!PositionSelectByTicket(ticket))
        return false;

    string symbol = PositionGetString(POSITION_SYMBOL);
    double volume = PositionGetDouble(POSITION_VOLUME);
    long posType = PositionGetInteger(POSITION_TYPE);
    double price = 0.0;
    if(posType == POSITION_TYPE_BUY)
        SymbolInfoDouble(symbol, SYMBOL_BID, price);
    else
        SymbolInfoDouble(symbol, SYMBOL_ASK, price);

    MqlTradeRequest request;
    MqlTradeResult result;
    ZeroMemory(request);
    ZeroMemory(result);

    request.action = TRADE_ACTION_DEAL;
    request.position = ticket;
    request.symbol = symbol;
    request.volume = volume;
    request.price = price;
    request.magic = InpMagicNumber;
    request.comment = comment;
    request.deviation = 20;
    request.type = (posType == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;

    if(!OrderSend(request, result))
        return false;

    return (result.retcode == TRADE_RETCODE_DONE || result.retcode == TRADE_RETCODE_DONE_PARTIAL);
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
        signal.action = _get_json_string(line, "action");
        StringToLower(signal.action);
        if(StringLen(signal.action) == 0)
            signal.action = "open";
        signal.entryTs = _get_json_string(line, "entry_ts");
        signal.signalId = _get_json_string(line, "signal_id");
        if(StringLen(signal.signalId) == 0)
            signal.signalId = signal.entryTs;
        signal.signalTime = _parse_signal_time(signal.entryTs);
        signal.dir = _get_json_string(line, "dir");
        StringToLower(signal.dir);
        signal.accountSize = _get_json_number(line, "account_size");
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

    string action = _get_json_string(cleaned, "action");
    StringToLower(action);
    string signalId = _get_json_string(cleaned, "signal_id");
    string dir = _get_json_string(cleaned, "dir");
    StringToLower(dir);
    double entry = _get_json_number(cleaned, "entry");
    double accountSize = _get_json_number(cleaned, "account_size");
    double qty = _get_json_number(cleaned, "qty");
    double stop = _get_json_number(cleaned, "stop");
    double tp = _get_json_number(cleaned, "tp");
    string ts = _get_json_string(cleaned, "entry_ts");
    if(StringLen(action) == 0)
        action = "open";
    if(StringLen(signalId) == 0)
        signalId = ts;

    if(InpVerboseLog)
        PrintFormat("Signal -> action=%s id=%s dir=%s entry=%.5f qty=%.4f stop=%.5f tp=%.5f acct=%.2f ts=%s", action, signalId, dir, entry, qty, stop, tp, accountSize, ts);

    if(action == "modify")
    {
        ulong ticket = FindPositionTicketByComment(signalId);
        if(ticket == 0)
        {
            if(InpVerboseLog)
                PrintFormat("Modify skipped, no open position found for signal_id=%s", signalId);
            return;
        }

        if(ModifyPositionByTicket(ticket, stop, tp))
        {
            PrintFormat("Modified position signal_id=%s stop=%.5f tp=%.5f", signalId, stop, tp);
            return;
        }

        PrintFormat("Modify failed signal_id=%s | err=%d", signalId, GetLastError());
        return;
    }

    if(action == "close")
    {
        ulong ticket = FindPositionTicketByComment(signalId);
        if(ticket == 0)
        {
            if(InpVerboseLog)
                PrintFormat("Close skipped, no open position found for signal_id=%s", signalId);
            return;
        }

        string closeComment = "Phantom|" + signalId + "|close";
        if(ClosePositionByTicket(ticket, closeComment))
        {
            PrintFormat("Closed position signal_id=%s", signalId);
            return;
        }

        PrintFormat("Close failed signal_id=%s | err=%d", signalId, GetLastError());
        return;
    }

    bool ok = false;
    string comment = "Phantom|" + signalId;

    double useQty = MapPythonQtyToLots(qty, accountSize);
    if(useQty <= 0.0)
    {
        PrintFormat("Rejected %s qty=%.8f — not within symbol volume bounds", dir, qty);
        return;
    }

    if(InpVerboseLog)
    {
        double unitsPerLot = GetUnitsPerLot();
        double liveAccountSize = AccountInfoDouble(ACCOUNT_BALANCE);
        if(liveAccountSize <= 0.0)
            liveAccountSize = AccountInfoDouble(ACCOUNT_EQUITY);
        if(liveAccountSize <= 0.0)
            liveAccountSize = g_referenceAccountSize;
        double baseSignalAccountSize = accountSize > 0.0 ? accountSize : 70000.0;
        double scale = (baseSignalAccountSize > 0.0) ? (liveAccountSize / baseSignalAccountSize) : 1.0;
        PrintFormat("Qty map | python=%.8f signalAcct=%.2f liveAcct=%.2f scale=%.6f unitsPerLot=%.8f -> lots=%.8f", qty, baseSignalAccountSize, liveAccountSize, scale, unitsPerLot, useQty);
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
        PrintFormat("Executed %s qty=%.4f", dir, useQty);
        return;
    }

    int err = GetLastError();
    uint rc = trade.ResultRetcode();
    if(rc == TRADE_RETCODE_INVALID_VOLUME)
    {
        PrintFormat("Rejected %s qty=%.8f due to invalid volume | err=%d | retcode=%d", dir, useQty, GetLastError(), rc);
        return;
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
            "{\"action\":\"%s\",\"signal_id\":\"%s\",\"entry_ts\":\"%s\",\"dir\":\"%s\",\"account_size\":%.10f,\"qty\":%.10f,\"stop\":%.10f,\"tp\":%.10f}",
            g_signals[g_nextSignalIndex].action,
            StringLen(g_signals[g_nextSignalIndex].signalId) > 0 ? g_signals[g_nextSignalIndex].signalId : g_signals[g_nextSignalIndex].entryTs,
            g_signals[g_nextSignalIndex].entryTs,
            g_signals[g_nextSignalIndex].dir,
            g_signals[g_nextSignalIndex].accountSize,
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
    g_referenceAccountSize = AccountInfoDouble(ACCOUNT_BALANCE);
    if(g_referenceAccountSize <= 0.0)
        g_referenceAccountSize = AccountInfoDouble(ACCOUNT_EQUITY);
    g_lastLineCount = (InpSignalMode == SIGNAL_MODE_REPLAY && InpReplayExistingSignals) ? 0 : CountLines(InpSignalFile);
    if(InpSignalMode == SIGNAL_MODE_REPLAY)
    {
        LoadSignals();
        int loadedSignals = ArraySize(g_signals);
        if(InpFailIfReplaySignalsTooLow && loadedSignals < InpMinReplaySignals)
        {
            PrintFormat("FATAL: replay loaded %d signals (< %d) from %s file. Aborting to prevent accidental one-trade run. file=%s",
                        loadedSignals,
                        InpMinReplaySignals,
                        g_lastSignalFileSource,
                        InpSignalFile);
            return INIT_FAILED;
        }
    }

    PrintFormat("phantom_signal_reader initialized v1.4-command-stream | magic=%d | mode=%s | replay=%s | start_line=%d | loaded=%d | source=%s",
                     InpMagicNumber,
                     InpSignalMode == SIGNAL_MODE_REPLAY ? "replay" : "live",
                     InpReplayExistingSignals ? "true" : "false",
                     g_lastLineCount,
                     ArraySize(g_signals),
                     g_lastSignalFileSource);
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