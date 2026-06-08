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
#property version   "1.1"
#property strict

input int    InpMagicNumber = 123456;
input string InpSignalFile = "phantom_signals.jsonl";
input bool   InpVerboseLog = true;
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
    double   qty;
    double   stop;
    double   tp;
    string   entryTs;
};

SignalRecord g_signals[];
int g_nextSignalIndex = 0;

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

    int handle = FileOpen(InpSignalFile, FILE_READ | FILE_COMMON | FILE_ANSI);
    if(handle == INVALID_HANDLE)
        return;

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
        signal.qty = _get_json_number(line, "qty");
        signal.stop = _get_json_number(line, "stop");
        signal.tp = _get_json_number(line, "tp");
        _append_signal(signal);
    }

    FileClose(handle);
}

int CountLines(const string &fileName)
{
    int handle = FileOpen(fileName, FILE_READ | FILE_COMMON | FILE_ANSI);
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
    double qty = _get_json_number(cleaned, "qty");
    double stop = _get_json_number(cleaned, "stop");
    double tp = _get_json_number(cleaned, "tp");
    string ts = _get_json_string(cleaned, "entry_ts");

    if(InpVerboseLog)
        PrintFormat("Signal -> dir=%s qty=%.4f stop=%.5f tp=%.5f ts=%s", dir, qty, stop, tp, ts);

    bool ok = false;
    string comment = "Phantom|" + ts;

    if(dir == "long" || dir == "buy")
        ok = trade.Buy(qty, NULL, 0, stop > 0 ? stop : 0, tp > 0 ? tp : 0, comment);
    else if(dir == "short" || dir == "sell")
        ok = trade.Sell(qty, NULL, 0, stop > 0 ? stop : 0, tp > 0 ? tp : 0, comment);
    else
    {
        PrintFormat("Unknown direction: %s", dir);
        return;
    }

    if(ok)
        PrintFormat("Executed %s qty=%.4f", dir, qty);
    else
        PrintFormat("Failed %s qty=%.4f | err=%d | retcode=%d", dir, qty, GetLastError(), trade.ResultRetcode());
}

void ProcessSignalsLive()
{
    int currentLines = CountLines(InpSignalFile);
    if(currentLines < g_lastLineCount)
        g_lastLineCount = 0;

    if(currentLines <= g_lastLineCount)
        return;

    int handle = FileOpen(InpSignalFile, FILE_READ | FILE_COMMON | FILE_ANSI);
    if(handle == INVALID_HANDLE)
        return;

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
    datetime nowTime = TimeCurrent();
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

    PrintFormat("phantom_signal_reader initialized | magic=%d | mode=%s | replay=%s | start_line=%d | loaded=%d",
                     InpMagicNumber,
                     InpSignalMode == SIGNAL_MODE_REPLAY ? "replay" : "live",
                     InpReplayExistingSignals ? "true" : "false",
                     g_lastLineCount,
                     ArraySize(g_signals));
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