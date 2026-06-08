//+------------------------------------------------------------------+
//| phantom_signal_reader.mq5                                        |
//| Reads newline-delimited JSON signals from phantom_signals.jsonl  |
//| and executes market orders with trailing stops & breakeven       |
//|                                                                     |
//| Features (v1.5):                                                  |
//| - Trailing stop scaled by H4 ATR at entry                         |
//| - Breakeven move at +0.8R                                         |
//| - Minimum 2-hour hold before tight stops                          |
//| - Signal replay from JSON file                                    |
//+------------------------------------------------------------------+
#property copyright ""
#property link      ""
#property version   "1.5"
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

//--- Risk management (NEW in v1.5)
input double   InpTrailATRMult        = 0.8;     // Trailing stop = price - (ATR * mult)
input double   InpBreakevenR          = 0.8;     // R-level to move stop to entry
input int      InpMinHoldHours        = 2;       // Minimum hours before tight stops apply

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
    double   atr_entry;        // NEW in v1.5 – H4 ATR at entry
};

SignalRecord g_signals[];
int g_nextSignalIndex = 0;
datetime g_lastReplayBarTime = 0;
double g_referenceAccountSize = 0.0;

//--- Tracking for trailing stops (NEW in v1.5)
struct PositionMeta {
    ulong    ticket;
    string   signal_id;
    datetime entry_time;
    double   entry_price;
    double   initial_stop;
    double   current_stop;
    double   tp;
    double   atr_entry;        // H4 ATR at entry
    bool     be_triggered;
    double   initial_risk;     // Entry - initial stop (absolute)
    int      direction;        // 1 = long, -1 = short
};

PositionMeta  m_positions[];
int           m_posCount = 0;

//+------------------------------------------------------------------+
//| HELPER FUNCTIONS – Volume & Account Mapping                      |
//+------------------------------------------------------------------+
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

    if(volMin <= 0.0) volMin = 1.0;
    if(volStep <= 0.0) volStep = 1.0;
    if(volMax <= 0.0) volMax = 1000.0;

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

    double liveAccountSize = g_referenceAccountSize;
    if(liveAccountSize <= 0.0)
        liveAccountSize = AccountInfoDouble(ACCOUNT_BALANCE);
    if(liveAccountSize <= 0.0)
        liveAccountSize = AccountInfoDouble(ACCOUNT_EQUITY);
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

double EffectiveAtrEntry(const double entryPrice, const double stopPrice, const double atrEntry)
{
    if(atrEntry > 0.0)
        return atrEntry;

    if(entryPrice > 0.0 && stopPrice > 0.0)
        return MathAbs(entryPrice - stopPrice);

    return 0.0;
}

datetime CurrentReplayTime()
{
    datetime barTime = iTime(_Symbol, PERIOD_CURRENT, 0);
    if(barTime > 0)
        return barTime;
    return TimeCurrent();
}

//+------------------------------------------------------------------+
//| SIGNAL PARSING HELPERS                                            |
//+------------------------------------------------------------------+
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

//+------------------------------------------------------------------+
//| POSITION MANAGEMENT HELPERS                                       |
//+------------------------------------------------------------------+
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

//+------------------------------------------------------------------+
//| TRAILING STOP MANAGEMENT (v1.5 NEW)                              |
//+------------------------------------------------------------------+
void ManageTrailingStops()
{
    double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
    double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
    datetime now = TimeCurrent();
    
    for(int i = m_posCount - 1; i >= 0; i--) {
        if(!PositionSelectByTicket(m_positions[i].ticket)) {
            ArrayRemove(m_positions, i, 1);
            m_posCount--;
            continue;
        }
        
        double currentPrice = (m_positions[i].direction == 1) ? bid : ask;
        double entryPrice   = m_positions[i].entry_price;
        double initialRisk  = m_positions[i].initial_risk;
        bool   isLong       = (m_positions[i].direction == 1);
        
        if(initialRisk <= 0) continue;
        
        double currentR = (isLong) 
            ? (currentPrice - entryPrice) / initialRisk
            : (entryPrice - currentPrice) / initialRisk;
        
        // Breakeven trigger
        if(!m_positions[i].be_triggered && currentR >= InpBreakevenR) {
            m_positions[i].current_stop = entryPrice;
            m_positions[i].be_triggered = true;
            
            if(InpVerboseLog) {
                PrintFormat("[BREAKEVEN] Ticket %d: moved stop to entry (%.5f)", 
                           m_positions[i].ticket, entryPrice);
            }
            
            ModifyPositionByTicket(m_positions[i].ticket, entryPrice, m_positions[i].tp);
        }
        
        // Trailing stop
        double atr = m_positions[i].atr_entry;
        if(atr <= 0) continue;
        
        double trailDist = InpTrailATRMult * atr;
        double newStop;
        
        if(isLong) {
            newStop = currentPrice - trailDist;
            if(newStop > m_positions[i].current_stop)
                m_positions[i].current_stop = newStop;
        } else {
            newStop = currentPrice + trailDist;
            if(newStop < m_positions[i].current_stop)
                m_positions[i].current_stop = newStop;
        }
        
        // Minimum-hold filter
        double ageHours = (double)(now - m_positions[i].entry_time) / 3600.0;
        bool canTighten = (ageHours >= (double)InpMinHoldHours) || (currentR >= 0.0);
        
        double currentStop = PositionGetDouble(POSITION_SL);
        if(canTighten) {
            double pointValue = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
            if(MathAbs(m_positions[i].current_stop - currentStop) > pointValue) {
                if(InpVerboseLog) {
                    PrintFormat("[TRAIL] Ticket %d: SL %.5f → %.5f (Age: %.1f hrs, R: %.2f)",
                               m_positions[i].ticket, currentStop, m_positions[i].current_stop, 
                               ageHours, currentR);
                }
                ModifyPositionByTicket(m_positions[i].ticket, m_positions[i].current_stop, m_positions[i].tp);
            }
        }
    }
}

void RegisterOpenPosition(ulong ticket, string signalId, double entryPrice, 
                         double initialStop, double tp, double atrEntry, int direction)
{
    int idx = m_posCount;
    ArrayResize(m_positions, idx + 1);
    
    m_positions[idx].ticket       = ticket;
    m_positions[idx].signal_id    = signalId;
    m_positions[idx].entry_time   = TimeCurrent();
    m_positions[idx].entry_price  = entryPrice;
    m_positions[idx].initial_stop = initialStop;
    m_positions[idx].current_stop = initialStop;
    m_positions[idx].tp           = tp;
    m_positions[idx].atr_entry    = atrEntry;
    m_positions[idx].be_triggered = false;
    m_positions[idx].initial_risk = MathAbs(entryPrice - initialStop);
    m_positions[idx].direction    = direction;
    
    m_posCount++;
}

//+------------------------------------------------------------------+
//| SIGNAL FILE LOADING & PROCESSING                                 |
//+------------------------------------------------------------------+
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
        signal.atr_entry = _get_json_number(line, "atr_entry");  // NEW in v1.5
        signal.atr_entry = EffectiveAtrEntry(signal.entry, signal.stop, signal.atr_entry);
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
    double atrEntry = _get_json_number(cleaned, "atr_entry");  // NEW in v1.5
    atrEntry = EffectiveAtrEntry(entry, stop, atrEntry);
    string ts = _get_json_string(cleaned, "entry_ts");
    if(StringLen(action) == 0)
        action = "open";
    if(StringLen(signalId) == 0)
        signalId = ts;

    if(InpVerboseLog)
        PrintFormat("Signal -> action=%s id=%s dir=%s entry=%.5f qty=%.4f stop=%.5f tp=%.5f atr=%.5f acct=%.2f ts=%s", action, signalId, dir, entry, qty, stop, tp, atrEntry, accountSize, ts);

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
        double liveAccountSize = g_referenceAccountSize;
        if(liveAccountSize <= 0.0)
            liveAccountSize = AccountInfoDouble(ACCOUNT_BALANCE);
        if(liveAccountSize <= 0.0)
            liveAccountSize = AccountInfoDouble(ACCOUNT_EQUITY);
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
        ulong ticket = trade.ResultOrder();
        if(ticket > 0)
        {
            int direction = (dir == "long" || dir == "buy") ? 1 : -1;
            RegisterOpenPosition(ticket, signalId, entry, stop, tp, atrEntry, direction);
        }
        PrintFormat("Executed %s qty=%.4f (atr_entry=%.5f)", dir, useQty, atrEntry);
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

    // Do not hard-gate replay processing by bar timestamp.
    // Some tester modes can keep bar time unchanged while ticks still advance.
    if(nowTime > g_lastReplayBarTime)
        g_lastReplayBarTime = nowTime;

    while(g_nextSignalIndex < ArraySize(g_signals))
    {
        if(g_signals[g_nextSignalIndex].signalTime > nowTime)
            break;

        string jsonLine = StringFormat(
            "{\"action\":\"%s\",\"signal_id\":\"%s\",\"entry_ts\":\"%s\",\"dir\":\"%s\",\"account_size\":%.10f,\"entry\":%.10f,\"qty\":%.10f,\"stop\":%.10f,\"tp\":%.10f,\"atr_entry\":%.10f}",
            g_signals[g_nextSignalIndex].action,
            StringLen(g_signals[g_nextSignalIndex].signalId) > 0 ? g_signals[g_nextSignalIndex].signalId : g_signals[g_nextSignalIndex].entryTs,
            g_signals[g_nextSignalIndex].entryTs,
            g_signals[g_nextSignalIndex].dir,
            (g_signals[g_nextSignalIndex].accountSize > 0.0 ? g_signals[g_nextSignalIndex].accountSize : g_referenceAccountSize),
            g_signals[g_nextSignalIndex].entry,
            g_signals[g_nextSignalIndex].qty,
            g_signals[g_nextSignalIndex].stop,
            g_signals[g_nextSignalIndex].tp,
            EffectiveAtrEntry(g_signals[g_nextSignalIndex].entry, g_signals[g_nextSignalIndex].stop, g_signals[g_nextSignalIndex].atr_entry)
        );
        ProcessLine(jsonLine);
        g_nextSignalIndex++;
    }
}

//+------------------------------------------------------------------+
//| EA LIFECYCLE                                                      |
//+------------------------------------------------------------------+
int OnInit() {
    trade.SetExpertMagicNumber(InpMagicNumber);
    trade.SetDeviationInPoints(30);
    g_referenceAccountSize = AccountInfoDouble(ACCOUNT_BALANCE);
    if(g_referenceAccountSize <= 0.0)
        g_referenceAccountSize = AccountInfoDouble(ACCOUNT_EQUITY);
    if(g_referenceAccountSize <= 0.0)
        g_referenceAccountSize = 70000.0;
    
    if(InpVerboseLog) {
        PrintFormat("Phantom Signal Reader v1.5 initialized on %s", _Symbol);
        PrintFormat("Trail ATR Mult: %.2f, Breakeven R: %.2f, Min Hold: %d hrs",
                   InpTrailATRMult, InpBreakevenR, InpMinHoldHours);
    }
    
    if(InpReplayExistingSignals && InpSignalMode == SIGNAL_MODE_REPLAY) {
        LoadSignals();
        PrintFormat("Loaded %d signals for replay", ArraySize(g_signals));
    }
    
    EventSetTimer(1);
    return INIT_SUCCEEDED;
}

void OnTick() {
    if(InpSignalMode == SIGNAL_MODE_REPLAY && InpReplayExistingSignals) {
        ProcessSignalsReplay();
    } else if(InpSignalMode == SIGNAL_MODE_LIVE) {
        ProcessSignalsLive();
    }
    
    ManageTrailingStops();
}

void OnTimer() {
    if(InpSignalMode == SIGNAL_MODE_REPLAY && InpReplayExistingSignals) {
        ProcessSignalsReplay();
    }
    ManageTrailingStops();
}

void OnDeinit(const int reason) {
    EventKillTimer();
}
