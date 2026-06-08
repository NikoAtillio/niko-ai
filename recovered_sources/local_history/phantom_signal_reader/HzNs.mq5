//+------------------------------------------------------------------+
//|                                     phantom_signal_reader_v15.mq5 |
//|                    Reads JSON signals & applies trailing SL        |
//|                  with breakeven & minimum-hold filters             |
//+------------------------------------------------------------------+
#property copyright "Phantom P2 Bridge"
#property version   "1.5"
#property description "Signal reader with trailing stop, breakeven, & min hold"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>
#include <Trade\SymbolInfo.mqh>
#include <Files\FileTxt.mqh>

//--- Input parameters
input ulong    InpMagicNumber         = 123456;
input string   InpSignalFile          = "phantom_signals.jsonl";
input bool     InpVerboseLog          = true;
input double   InpQtyUnitsPerLotOverride = 0.0;  // 0 = use symbol contract size
input bool     InpForceMinLotInReplay  = false;
input bool     InpReplayExistingSignals = true;

//--- Risk management parameters
input double   InpTrailATRMult        = 0.8;     // Trailing stop = price - (ATR * mult)
input double   InpBreakevenR          = 0.8;     // R-level to move stop to entry
input int      InpMinHoldHours        = 2;       // Minimum hours before tight stops apply

//--- Global objects
CTrade         m_trade;
CPositionInfo  m_position;
CSymbolInfo    m_symbol;
CAccountInfo   m_account;

//--- Structures for signal and position tracking
struct SignalRecord {
    string   action;
    string   signal_id;
    datetime entry_ts;
    datetime exit_ts;
    string   dir;
    double   entry;
    double   stop;
    double   tp;
    double   qty;
    double   account_size;
    double   confidence_mult;
    string   regime;
    double   atr_entry;        // H4 ATR at entry (NEW)
    string   exit_reason;
    bool     be_triggered;
};

struct PositionMeta {
    ulong    ticket;
    string   signal_id;
    datetime entry_time;
    double   entry_price;
    double   initial_stop;
    double   current_stop;
    double   tp;
    double   atr_entry;        // Stored from signal
    bool     be_triggered;
    double   initial_risk;     // Entry - initial stop (absolute)
    int      direction;        // 1 = long, -1 = short
    double   confidence_mult;
    string   regime;
};

PositionMeta  m_positions[];
int           m_posCount = 0;
double        m_unitsPerLot = 1.0;
int           m_nextSignalLine = 0;

//+------------------------------------------------------------------+
//| Find position by ticket in our metadata array                     |
//+------------------------------------------------------------------+
int FindPositionMeta(ulong ticket) {
    for(int i = 0; i < m_posCount; i++)
        if(m_positions[i].ticket == ticket) return i;
    return -1;
}

//+------------------------------------------------------------------+
//| Parse a JSON signal line (simplified manual parsing)              |
//+------------------------------------------------------------------+
bool ParseSignalLine(string line, SignalRecord &sig) {
    // Very basic JSON parsing – adapt to your JSON library as needed
    // This assumes key-value pairs are reasonably ordered
    
    // Extract action
    int pos = StringFind(line, "\"action\":");
    if(pos < 0) return false;
    pos = StringFind(line, "\"", pos + 10);
    if(pos < 0) return false;
    int end = StringFind(line, "\"", pos + 1);
    if(end < 0) return false;
    sig.action = StringSubstr(line, pos + 1, end - pos - 1);
    
    // Extract other fields with error handling
    // (In production, use a proper JSON library like jared.mqh or JSON.mqh)
    
    // Extract signal_id
    pos = StringFind(line, "\"signal_id\":");
    if(pos >= 0) {
        pos = StringFind(line, "\"", pos + 13);
        if(pos >= 0) {
            end = StringFind(line, "\"", pos + 1);
            if(end >= 0) sig.signal_id = StringSubstr(line, pos + 1, end - pos - 1);
        }
    }
    
    // Extract dir
    pos = StringFind(line, "\"dir\":");
    if(pos >= 0) {
        pos = StringFind(line, "\"", pos + 6);
        if(pos >= 0) {
            end = StringFind(line, "\"", pos + 1);
            if(end >= 0) sig.dir = StringSubstr(line, pos + 1, end - pos - 1);
        }
    }
    
    // Extract entry (numeric)
    pos = StringFind(line, "\"entry\":");
    if(pos >= 0) sig.entry = StringToDouble(StringSubstr(line, pos + 8, 20));
    
    // Extract stop (numeric)
    pos = StringFind(line, "\"stop\":");
    if(pos >= 0) sig.stop = StringToDouble(StringSubstr(line, pos + 7, 20));
    
    // Extract tp (numeric)
    pos = StringFind(line, "\"tp\":");
    if(pos >= 0) sig.tp = StringToDouble(StringSubstr(line, pos + 5, 20));
    
    // Extract qty (numeric)
    pos = StringFind(line, "\"qty\":");
    if(pos >= 0) sig.qty = StringToDouble(StringSubstr(line, pos + 6, 20));
    
    // Extract atr_entry (NEW – critical for trailing stops)
    pos = StringFind(line, "\"atr_entry\":");
    if(pos >= 0) sig.atr_entry = StringToDouble(StringSubstr(line, pos + 12, 20));
    else sig.atr_entry = 0.0;  // Fallback if not present
    
    // Extract confidence_mult
    pos = StringFind(line, "\"confidence_mult\":");
    if(pos >= 0) sig.confidence_mult = StringToDouble(StringSubstr(line, pos + 18, 20));
    else sig.confidence_mult = 1.0;
    
    // Extract regime
    pos = StringFind(line, "\"regime\":");
    if(pos >= 0) {
        pos = StringFind(line, "\"", pos + 9);
        if(pos >= 0) {
            end = StringFind(line, "\"", pos + 1);
            if(end >= 0) sig.regime = StringSubstr(line, pos + 1, end - pos - 1);
        }
    }
    
    return true;
}

//+------------------------------------------------------------------+
//| OnInit                                                             |
//+------------------------------------------------------------------+
int OnInit() {
    m_trade.SetExpertMagicNumber(InpMagicNumber);
    m_trade.SetDeviationInPoints(30);
    
    m_symbol.Name(Symbol());
    m_symbol.Refresh();
    
    // Determine units per lot
    double contractSize = m_symbol.ContractSize();
    if(InpQtyUnitsPerLotOverride > 0.0) {
        m_unitsPerLot = InpQtyUnitsPerLotOverride;
    } else {
        m_unitsPerLot = (contractSize > 0.0) ? contractSize : 1.0;
    }
    
    if(InpVerboseLog) {
        PrintFormat("Phantom Signal Reader v1.5 initialized on %s", Symbol());
        PrintFormat("Units per lot: %.2f, Trail ATR Mult: %.2f, Breakeven R: %.2f, Min Hold: %d hrs",
                   m_unitsPerLot, InpTrailATRMult, InpBreakevenR, InpMinHoldHours);
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
//| OnTick – process new signals and manage positions                 |
//+------------------------------------------------------------------+
void OnTick() {
    if(!InpReplayExistingSignals) return;
    
    static datetime lastBarTime = 0;
    datetime currentBarTime = iTime(Symbol(), PERIOD_M5, 0);
    if(currentBarTime == lastBarTime) return;
    lastBarTime = currentBarTime;
    
    // Process pending signals (would read from file)
    // In a full implementation, read next line from InpSignalFile
    // For now, we assume signals are pre-loaded or provided externally
    
    ManageOpenPositions();
}

//+------------------------------------------------------------------+
//| Execute an open signal                                             |
//+------------------------------------------------------------------+
void ExecuteOpenSignal(SignalRecord &sig) {
    ENUM_ORDER_TYPE type = (sig.dir == "long") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
    double volume = sig.qty;
    
    // Adjust volume to symbol constraints
    double minLot = m_symbol.LotsMin();
    double step   = m_symbol.LotsStep();
    double maxLot = m_symbol.LotsMax();
    
    volume = MathFloor(volume / step) * step;
    volume = MathMax(volume, minLot);
    volume = MathMin(volume, maxLot);
    
    if(InpForceMinLotInReplay && volume < minLot) volume = minLot;
    
    string comment = StringFormat("Phantom|%s", sig.signal_id);
    
    if(InpVerboseLog) {
        PrintFormat("[OPEN] %s %.4f lots | Entry: %.5f, SL: %.5f, TP: %.5f, ATR: %.5f",
                   sig.dir, volume, sig.entry, sig.stop, sig.tp, sig.atr_entry);
    }
    
    // Place order
    if(!m_trade.PositionOpen(Symbol(), type, volume, sig.entry, sig.stop, sig.tp, comment)) {
        if(InpVerboseLog) PrintFormat("[ERROR] Failed to open position: %s", m_trade.ResultComment());
        return;
    }
    
    // Store position metadata
    ulong ticket = m_trade.ResultOrder();
    if(ticket == 0) return;
    
    int idx = m_posCount;
    ArrayResize(m_positions, idx + 1);
    
    m_positions[idx].ticket       = ticket;
    m_positions[idx].signal_id    = sig.signal_id;
    m_positions[idx].entry_time   = TimeCurrent();
    m_positions[idx].entry_price  = sig.entry;
    m_positions[idx].initial_stop = sig.stop;
    m_positions[idx].current_stop = sig.stop;
    m_positions[idx].tp           = sig.tp;
    m_positions[idx].atr_entry    = sig.atr_entry;  // Store ATR for trailing calcs
    m_positions[idx].be_triggered = false;
    m_positions[idx].initial_risk = MathAbs(sig.entry - sig.stop);
    m_positions[idx].direction    = (sig.dir == "long") ? 1 : -1;
    m_positions[idx].confidence_mult = sig.confidence_mult;
    m_positions[idx].regime       = sig.regime;
    
    m_posCount++;
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
        
        // 1. Calculate current R (risk units from entry)
        double currentR = (isLong) 
            ? (currentPrice - entryPrice) / initialRisk
            : (entryPrice - currentPrice) / initialRisk;
        
        // 2. Move to breakeven once +0.8R is reached (only once)
        if(!m_positions[i].be_triggered && currentR >= InpBreakevenR) {
            m_positions[i].current_stop = entryPrice;
            m_positions[i].be_triggered = true;
            
            if(InpVerboseLog) {
                PrintFormat("[BREAKEVEN] Ticket %d: moved stop to entry (%.5f)", 
                           m_positions[i].ticket, entryPrice);
            }
            
            m_trade.PositionModify(m_positions[i].ticket, entryPrice, m_positions[i].tp);
        }
        
        // 3. Trailing stop calculation using stored ATR
        double atr = m_positions[i].atr_entry;
        if(atr <= 0) continue;  // Skip if no valid ATR
        
        double trailDist = InpTrailATRMult * atr;
        double newStop;
        
        if(isLong) {
            newStop = currentPrice - trailDist;
            // Only tighten – never loosen
            if(newStop > m_positions[i].current_stop)
                m_positions[i].current_stop = newStop;
        } else {
            newStop = currentPrice + trailDist;
            // Only tighten – never loosen
            if(newStop < m_positions[i].current_stop)
                m_positions[i].current_stop = newStop;
        }
        
        // 4. Minimum-hold filter: only allow tight stops if:
        //    a) Trade is at least MinHoldHours old, OR
        //    b) Trade is already in profit (R >= 0)
        double ageHours = (double)(now - m_positions[i].entry_time) / 3600.0;
        bool canTighten = (ageHours >= (double)InpMinHoldHours) || (currentR >= 0.0);
        
        // 5. Apply stop update
        double currentStop = PositionGetDouble(POSITION_SL);
        if(canTighten) {
            // Apply the new tight stop
            if(MathAbs(m_positions[i].current_stop - currentStop) > m_symbol.Point()) {
                if(InpVerboseLog) {
                    PrintFormat("[TRAIL] Ticket %d: SL %.5f → %.5f (Age: %.1f hrs, R: %.2f)",
                               m_positions[i].ticket, currentStop, m_positions[i].current_stop, 
                               ageHours, currentR);
                }
                m_trade.PositionModify(m_positions[i].ticket, m_positions[i].current_stop, m_positions[i].tp);
            }
        } else {
            // Keep stop at initial level or entry (if BE already triggered)
            if(m_positions[i].be_triggered && MathAbs(currentStop - entryPrice) > m_symbol.Point()) {
                m_positions[i].current_stop = entryPrice;
                m_trade.PositionModify(m_positions[i].ticket, entryPrice, m_positions[i].tp);
            }
        }
    }
}

//+------------------------------------------------------------------+
//| OnDeinit – cleanup                                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
    EventKillTimer();
}
