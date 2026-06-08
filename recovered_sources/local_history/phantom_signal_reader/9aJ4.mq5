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
//| Find position by ticket in our metadata array                     |
//+------------------------------------------------------------------+
int FindPositionMeta(ulong ticket) {
    for(int i = 0; i < m_posCount; i++)
        if(m_positions[i].ticket == ticket) return i;
    return -1;
}

//+------------------------------------------------------------------+
//| Extract numeric value from JSON field                              |
//+------------------------------------------------------------------+
double ExtractDouble(string json, string fieldName) {
    string pattern = "\"" + fieldName + "\":";
    int pos = StringFind(json, pattern);
    if(pos < 0) return 0.0;
    
    pos += StringLen(pattern);
    string substr = StringSubstr(json, pos, 50);
    
    // Skip whitespace
    int i = 0;
    while(i < StringLen(substr) && (substr[i] == ' ' || substr[i] == '\t')) i++;
    
    // Extract numeric part
    string numStr = "";
    while(i < StringLen(substr)) {
        char c = substr[i];
        if((c >= '0' && c <= '9') || c == '.' || c == '-' || c == '+' || c == 'e' || c == 'E') {
            numStr += CharToString(c);
        } else {
            break;
        }
        i++;
    }
    
    return (StringLen(numStr) > 0) ? StringToDouble(numStr) : 0.0;
}

//+------------------------------------------------------------------+
//| Extract string value from JSON field                               |
//+------------------------------------------------------------------+
string ExtractString(string json, string fieldName) {
    string pattern = "\"" + fieldName + "\":\"";
    int pos = StringFind(json, pattern);
    if(pos < 0) return "";
    
    pos += StringLen(pattern);
    int endPos = StringFind(json, "\"", pos);
    if(endPos < 0) return "";
    
    return StringSubstr(json, pos, endPos - pos);
}

//+------------------------------------------------------------------+
//| OnInit                                                             |
//+------------------------------------------------------------------+
int OnInit() {
    m_trade.SetExpertMagicNumber(InpMagicNumber);
    m_trade.SetDeviationInPoints(30);
    
    if(InpVerboseLog) {
        PrintFormat("Phantom Signal Reader v1.5 initialized on %s", Symbol());
        PrintFormat("Trail ATR Mult: %.2f, Breakeven R: %.2f, Min Hold: %d hrs",
                   InpTrailATRMult, InpBreakevenR, InpMinHoldHours);
    }
    
    EventSetTimer(1);  // Timer for per-tick management
    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnTimer – manage trailing stops, breakeven, and minimum hold      |
//+------------------------------------------------------------------+
void OnTimer() {
    ManageOpenPositions();
}

//+------------------------------------------------------------------+
//| OnTick – manage positions                                          |
//+------------------------------------------------------------------+
void OnTick() {
    ManageOpenPositions();
}

//+------------------------------------------------------------------+
//| Manage open positions – trailing stops, breakeven, minimum hold    |
//+------------------------------------------------------------------+
void ManageOpenPositions() {
    double bid = SymbolInfoDouble(Symbol(), SYMBOL_BID);
    double ask = SymbolInfoDouble(Symbol(), SYMBOL_ASK);
    datetime now = TimeCurrent();
    
    for(int i = m_posCount - 1; i >= 0; i--) {
        // Check if position still exists
        if(!PositionSelectByTicket(m_positions[i].ticket)) {
            // Position closed externally – remove from tracking
            ArrayRemove(m_positions, i, 1);
            m_posCount--;
            continue;
        }
        
        double currentPrice = (m_positions[i].direction == 1) ? bid : ask;
        double entryPrice   = m_positions[i].entry_price;
        double initialRisk  = m_positions[i].initial_risk;
        bool   isLong       = (m_positions[i].direction == 1);
        
        if(initialRisk <= 0) continue;
        
        // Calculate current R (risk units from entry)
        double currentR = (isLong) 
            ? (currentPrice - entryPrice) / initialRisk
            : (entryPrice - currentPrice) / initialRisk;
        
        // Move to breakeven once +0.8R is reached (only once)
        if(!m_positions[i].be_triggered && currentR >= InpBreakevenR) {
            m_positions[i].current_stop = entryPrice;
            m_positions[i].be_triggered = true;
            
            if(InpVerboseLog) {
                PrintFormat("[BREAKEVEN] Ticket %d: moved stop to entry (%.5f)", 
                           m_positions[i].ticket, entryPrice);
            }
            
            m_trade.PositionModify(m_positions[i].ticket, entryPrice, m_positions[i].tp);
        }
        
        // Trailing stop calculation using stored ATR
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
        
        // Minimum-hold filter: only allow tight stops if:
        // a) Trade is at least MinHoldHours old, OR
        // b) Trade is already in profit (R >= 0)
        double ageHours = (double)(now - m_positions[i].entry_time) / 3600.0;
        bool canTighten = (ageHours >= (double)InpMinHoldHours) || (currentR >= 0.0);
        
        // Apply stop update
        double currentStop = PositionGetDouble(POSITION_SL);
        if(canTighten) {
            // Apply the new tight stop
            double pointValue = SymbolInfoDouble(Symbol(), SYMBOL_POINT);
            if(MathAbs(m_positions[i].current_stop - currentStop) > pointValue) {
                if(InpVerboseLog) {
                    PrintFormat("[TRAIL] Ticket %d: SL %.5f → %.5f (Age: %.1f hrs, R: %.2f)",
                               m_positions[i].ticket, currentStop, m_positions[i].current_stop, 
                               ageHours, currentR);
                }
                m_trade.PositionModify(m_positions[i].ticket, m_positions[i].current_stop, m_positions[i].tp);
            }
        } else {
            // Keep stop at initial level or entry (if BE already triggered)
            if(m_positions[i].be_triggered) {
                double pointValue = SymbolInfoDouble(Symbol(), SYMBOL_POINT);
                if(MathAbs(currentStop - entryPrice) > pointValue) {
                    m_positions[i].current_stop = entryPrice;
                    m_trade.PositionModify(m_positions[i].ticket, entryPrice, m_positions[i].tp);
                }
            }
        }
    }
}

//+------------------------------------------------------------------+
//| Register position for management (called from external code)      |
//+------------------------------------------------------------------+
void RegisterPosition(ulong ticket, string signalId, double entryPrice, 
                     double initialStop, double tp, double atrEntry, int direction) {
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
//| OnDeinit – cleanup                                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
    EventKillTimer();
}
