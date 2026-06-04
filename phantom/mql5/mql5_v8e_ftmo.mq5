//+------------------------------------------------------------------+
//|                                          Phantom_P2_US100_V8E.mq5 |
//|                                    Multi-Timeframe Zone Strategy  |
//|                                             US100 Scenario B      |
//+------------------------------------------------------------------+
//  V8E changelog (V8C + zone flip):
//    - V8C unchanged as base (V8A hard-seed ATR + V8B touch gate)
//
//  V8E — Zone Direction Flip (Break-and-Retest):
//    PROBLEM : When price breaks convincingly through a demand zone and
//              retests from below, the zone still had direction=1 (long).
//              The EA would only consider longs there, missing the short.
//              Example: Jan 14 retest of the Jan 13 demand zone (~25468).
//    FIX     : Track when price closes beyond a zone by > InpZoneBreakATRFrac
//              * M15ATR on the wrong side for >= InpZoneBreakBars bars.
//              On confirmation, zone.effective_dir flips (-1→1 or 1→-1).
//              All entry logic uses effective_dir, not the original direction.
//    IMPACT  : Break-and-retest shorts (longs) at previously bullish (bearish)
//              levels are now tradeable. No other logic changed.
//    SCOPE   : SZone struct (3 new fields), AddZone, PreserveTouchState,
//              new UpdateZoneBreaks(), CheckEntryConditions (use effective_dir).
//    GUARD   : InpZoneFlipEnabled=false restores V8C behaviour.
//+------------------------------------------------------------------+
#property copyright "Phantom P2 MT5"
#property version   "8.40"
#property description "Multi-Timeframe Zone-Based Strategy for US100"
#property description "Scenario B - V8E (V8C + Zone Direction Flip)"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//+------------------------------------------------------------------+
//| Input Parameters                                                  |
//+------------------------------------------------------------------+
// --- Zone Detection ---
input int      InpPivotBars           = 2;
input int      InpZoneLookback        = 50;
input double   InpZoneTolerance       = 0.002;
input double   InpChaseFilterATR      = 1.5;

// --- V8b: Zone Touch Confirmation ---
input bool     InpZoneTouchRequired   = false;
input int      InpZoneBounceBars      = 0;
input double   InpZoneBounceATRFrac   = 0.1;

// --- V8E: Zone Direction Flip ---
input bool     InpZoneFlipEnabled     = true;   // Allow zone to flip direction after break
input double   InpZoneBreakATRFrac    = 0.3;    // Close must be this * M15ATR beyond zone to count as break
input int      InpZoneBreakBars       = 1;      // Min consecutive M5 bars beyond zone to confirm break

// --- Session Filter ---
input int      InpSessionStart        = 13;
input int      InpSessionEnd          = 21;
input bool     InpPeakSessionBoost    = true;

// --- Confirmation ---
input int      InpMinConfirmBars      = 1;
input ENUM_TIMEFRAMES InpConfirmTF    = PERIOD_H1;

// --- Scoring ---
input int      InpScoreMin            = 3;
input int      InpH4ScoreMin          = 1;
input int      InpH1ScoreMin          = 1;
input int      InpLTFScoreMin         = 1;
input int      InpLTFScoreCap         = 3;
input int      InpLongScoreOffset     = 1;
input int      InpCTTotalScoreMin     = 4;
input int      InpCTH4ScoreMin        = 0;
input int      InpCTH1ScoreMin        = 1;
input int      InpCTLTFScoreMin       = 1;

// --- Risk Management ---
input double   InpRiskPercent         = 0.7;
input double   InpRiskMultiplier      = 2.0;
input double   InpATRStopMult         = 1.5;
input double   InpTPMult              = 1.3;
input double   InpTrailATRMult        = 0.8;
input double   InpBreakevenR          = 0.8;
input int      InpMaxConcurrent       = 3;
input int      InpCooldownMin         = 20;
input bool     InpEnableDebugLogs     = true;
input int      InpLockoutMin          = 60;
input int      InpCircuitBreakerLosses= 5;
input int      InpCircuitBreakerHours = 24;

// --- FTMO Guardrails ---
input bool     InpEnableFTMOGuardrails    = false;
input double   InpFTMOAccountSize         = 70000.0;
input double   InpFTMOProfitTargetPct     = 5.0;
input double   InpFTMOMaxLossPct          = 10.0;
input double   InpFTMOMaxDailyLossPct     = 5.0;
input int      InpFTMOTradingPeriodDays   = 0;
input int      InpFTMOMinTradingDays      = 2;
input double   InpFTMOMaxLeverage         = 30.0;

// --- Position Sizing ---
input double   InpConfidenceMult      = 1.5;
input double   InpSessionSoftMult     = 0.5;
input double   InpCounterTrendMult    = 0.5;

// --- Execution ---
input double   InpSpreadBPS           = 0.0;
input double   InpSlippageBPS         = 0.0;
input ulong    InpMagicNumber         = 202406;
input string   InpComment             = "Phantom P2 US100 B V8e";

// --- Time handling ---
input bool     InpAutoDetectUTC       = false;
input int      InpManualUTCOffset     = -5;

// --- V5/V8a: EWM ATR ---
input int      InpEWMATRPeriod        = 14;
input double   InpPythonExpectedATR   = 103.76;

// --- Development ---
input bool     InpEnableDebugPrint    = true;
input bool     InpEnableVisuals       = true;
input bool     InpShowOnlyActiveZones = true;
input bool     InpShowZoneOrigins     = true;
input bool     InpShowInactiveZoneMarkers = true;
input bool     InpShowZoneTimeframe   = true;

//+------------------------------------------------------------------+
//| Global Variables                                                  |
//+------------------------------------------------------------------+
CTrade         m_trade;
CPositionInfo  m_position;
CAccountInfo   m_account;
CSymbolInfo    m_symbol;

int            m_handleH4ATR_Debug;
int            m_handleH4EMA20, m_handleH4EMA50, m_handleH4RSI;
int            m_handleH1EMA20, m_handleH1EMA50, m_handleH1RSI;
int            m_handleM5EMA20, m_handleM5EMA50, m_handleM5RSI, m_handleM5Volume;
int            m_handleDailyEMA50, m_handleDailyEMA200;

int            m_detectedUTCOffsetHours = 0;
int            m_ewmDebugCount = 0;
bool           m_ewmDebugDone  = false;

//+------------------------------------------------------------------+
//| SZone struct — V8E adds 3 zone-flip fields                       |
//+------------------------------------------------------------------+
struct SZone {
   datetime    time;
   double      price;
   int         direction;       // original direction (never changes)
   ENUM_TIMEFRAMES source_tf;
   datetime    origin_time_utc;
   bool        confirmed;
   datetime    confirmed_at;

   // V8b: touch/bounce
   bool        touch_logged;
   datetime    last_touch_time;
   int         touch_count;
   bool        bounce_confirmed;
   datetime    bounce_confirmed_at;
   int         bars_away;
   int         last_entry_day_key;

   // V8E: zone flip
   int         effective_dir;       // active trade direction (may differ from direction after flip)
   bool        broken;              // price has closed convincingly through zone on wrong side
   datetime    broken_at;           // when break was confirmed
   int         break_bars_count;    // consecutive M5 bars price has held beyond zone
};

SZone         m_zones[];
int           m_zoneCount;

struct SPositionMeta {
   ulong      ticket;
   datetime   entry_time;
   datetime   entry_time_utc;
   string     entry_comment;
   double     entry_price;
   double     stop_price;
   double     tp_price;
   double     initial_risk;
   double     atr_entry;
   bool       be_triggered;
   int        direction;
   int        total_score;
   double     confidence_mult;
   double     session_mult;
   double     regime_mult;
   string     regime;
   datetime   zone_time_utc;
   double     zone_price;
   bool       logged;
};
SPositionMeta m_pos_meta[];
ulong        m_closed_positions[];

datetime      m_entry_times_utc[];

int           m_consecutiveLosses;
datetime      m_lastEntryTime;
datetime      m_lastLossExitTime;
datetime      m_circuitBreakerUntil;
int           m_tradeCsvHandle = INVALID_HANDLE;
string        m_tradeCsvFileName = "phantom_mql5_trade_log_v8e.csv";

double        m_ftmoInitialEquity;
double        m_ftmoDayStartEquity;
datetime      m_ftmoTradingStartUtc;
int           m_ftmoCurrentDayKey;
int           m_ftmoTradeDayKeys[];
bool          m_ftmoHardStop;
datetime      m_ftmoLastStatusPrint;

color         m_demandColor = clrDodgerBlue;
color         m_supplyColor = clrTomato;

//+------------------------------------------------------------------+
//| SafeBarShift                                                      |
//+------------------------------------------------------------------+
int SafeBarShift(string symbol, ENUM_TIMEFRAMES tf, datetime time)
{
   int shift = iBarShift(symbol, tf, time, false);
   if(shift < 0) return shift;
   datetime barOpen = iTime(symbol, tf, shift);
   if(time == barOpen && shift + 1 < iBars(symbol, tf))
      return shift + 1;
   return shift;
}

//+------------------------------------------------------------------+
//| UTC helpers                                                       |
//+------------------------------------------------------------------+
int      GetEffectiveUTCOffset()       { return m_detectedUTCOffsetHours; }
datetime ToUTC(datetime serverTime)    { return serverTime - (m_detectedUTCOffsetHours * 3600); }
datetime FromUTC(datetime utcTime)     { return utcTime    + (m_detectedUTCOffsetHours * 3600); }
void     GetUTCTime(MqlDateTime &utc)  { TimeToStruct(ToUTC(TimeCurrent()), utc); }

datetime Get4HWindowStart(datetime timeUtc)
{
   return (timeUtc / 14400) * 14400;
}

//+------------------------------------------------------------------+
//| V8a: CalcEWM_ATR_Py — Hard-Seed ATR (unchanged)                 |
//+------------------------------------------------------------------+
double CalcEWM_ATR_Py(string symbol, ENUM_TIMEFRAMES tf, int period,
                       datetime barTime, bool logComparison = false)
{
   int totalBars  = iBars(symbol, tf);
   int targetShift = iBarShift(symbol, tf, barTime, false);

   if(tf == PERIOD_H4)
      targetShift = targetShift + 1;

   int minWarmup = period * 5;
   if(targetShift < 0 || (totalBars - 1 - targetShift) < minWarmup)
      return 0.0;

   int lookback    = targetShift + minWarmup;
   int seedStart   = lookback + (period - 1);
   int barsToFetch = seedStart + 2;

   if(barsToFetch > totalBars) return 0.0;

   double highs[], lows[], closes[];
   ArraySetAsSeries(highs,  true);
   ArraySetAsSeries(lows,   true);
   ArraySetAsSeries(closes, true);

   if(CopyHigh (symbol, tf, 0, barsToFetch, highs)  < barsToFetch) return 0.0;
   if(CopyLow  (symbol, tf, 0, barsToFetch, lows)   < barsToFetch) return 0.0;
   if(CopyClose(symbol, tf, 0, barsToFetch, closes)  < barsToFetch) return 0.0;

   double alpha   = 2.0 / ((double)period + 1.0);
   double oneMinA = 1.0 - alpha;

   double seedSum = 0.0;
   for(int k = seedStart; k >= lookback; k--)
   {
      double trHL = highs[k] - lows[k];
      double trHC = (k + 1 < barsToFetch) ? MathAbs(highs[k] - closes[k + 1]) : trHL;
      double trLC = (k + 1 < barsToFetch) ? MathAbs(lows[k]  - closes[k + 1]) : trHL;
      seedSum += MathMax(trHL, MathMax(trHC, trLC));
   }
   double ewmATR = seedSum / (double)period;

   for(int i = lookback - 1; i >= targetShift; i--)
   {
      double trHL = highs[i]  - lows[i];
      double trHC = MathAbs(highs[i]  - closes[i + 1]);
      double trLC = MathAbs(lows[i]   - closes[i + 1]);
      double tr   = MathMax(trHL, MathMax(trHC, trLC));
      ewmATR      = alpha * tr + oneMinA * ewmATR;
   }

   static int debugCount = 0;
   if(logComparison && tf == PERIOD_H4 && debugCount < 10 && InpEnableDebugPrint)
   {
      double wilderVal = 0.0;
      int wilderHandle = iATR(symbol, tf, period);
      if(wilderHandle != INVALID_HANDLE)
      {
         double buf[1];
         if(CopyBuffer(wilderHandle, 0, targetShift, 1, buf) > 0)
            wilderVal = buf[0];
         IndicatorRelease(wilderHandle);
      }
      PrintFormat(
         "V8a_EWM_ATR[%02d]: shift=%d | SMA-Seeded=%.4f | Wilder=%.4f | Py_Expected=%.4f",
         debugCount, targetShift, ewmATR, wilderVal, InpPythonExpectedATR);
      debugCount++;
      if(debugCount >= 10)
         Print("V8a: EWM ATR validation logging complete (10 prints)");
   }

   return ewmATR;
}

//+------------------------------------------------------------------+
//| CSV logging (unchanged)                                           |
//+------------------------------------------------------------------+
bool OpenTradeCsv() {
   if(m_tradeCsvHandle != INVALID_HANDLE) { FileClose(m_tradeCsvHandle); m_tradeCsvHandle = INVALID_HANDLE; }
   m_tradeCsvHandle = FileOpen(m_tradeCsvFileName, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ';');
   if(m_tradeCsvHandle == INVALID_HANDLE) return false;
   FileWrite(m_tradeCsvHandle,
             "entry_time_utc","exit_time_utc","ticket","symbol","direction","volume",
             "entry_price","exit_price","stop_price","tp_price","initial_risk","exit_reason",
             "gross_profit","commission","swap","net_profit","r_value","score",
             "confidence_mult","regime","broker_exit_reason","entry_comment",
             "session_mult","regime_mult","zone_price","zone_time_utc","exit_comment");
   FileFlush(m_tradeCsvHandle);
   return true;
}

void CloseTradeCsv() {
   if(m_tradeCsvHandle != INVALID_HANDLE) { FileFlush(m_tradeCsvHandle); FileClose(m_tradeCsvHandle); m_tradeCsvHandle = INVALID_HANDLE; }
}

string TradeDirectionToString(int direction) { return (direction == 1) ? "long" : "short"; }

string InferExitReason(double dealPrice, double stopPrice, double tpPrice) {
   double point = SymbolInfoDouble(Symbol(), SYMBOL_POINT);
   double tolerance = MathMax(point * 2.0, point);
   if(MathAbs(dealPrice - stopPrice) <= tolerance) return "stop";
   if(MathAbs(dealPrice - tpPrice)   <= tolerance) return "tp";
   return "close";
}

string DealReasonToString(long reason) {
   switch(reason) {
      case DEAL_REASON_CLIENT:           return "client";
      case DEAL_REASON_MOBILE:           return "mobile";
      case DEAL_REASON_WEB:              return "web";
      case DEAL_REASON_EXPERT:           return "expert";
      case DEAL_REASON_SL:               return "sl";
      case DEAL_REASON_TP:               return "tp";
      case DEAL_REASON_SO:               return "stop_out";
      case DEAL_REASON_ROLLOVER:         return "rollover";
      case DEAL_REASON_VMARGIN:          return "margin";
      case DEAL_REASON_SPLIT:            return "split";
      case DEAL_REASON_CORPORATE_ACTION: return "corp_action";
      default: return StringFormat("reason_%I64d", reason);
   }
}

void LogTradeCsvRow(datetime entryUtc, datetime exitUtc, ulong ticket, int direction, double volume,
                    double entryPrice, double exitPrice, double stopPrice, double tpPrice,
                    double initialRisk, string exitReason, double grossProfit, double commission,
                    double swap, double netProfit, double rValue, int score,
                    double confidenceMult, string regime, string brokerExitReason,
                    string entryComment, double sessionMult,
                    double regimeMult, double zonePrice, datetime zoneTimeUtc,
                    string exitComment) {
   if(m_tradeCsvHandle == INVALID_HANDLE) return;
   FileWrite(m_tradeCsvHandle,
             TimeToString(entryUtc, TIME_DATE|TIME_SECONDS),
             TimeToString(exitUtc,  TIME_DATE|TIME_SECONDS),
             (long)ticket, Symbol(), TradeDirectionToString(direction),
             DoubleToString(volume, 2),
             DoubleToString(entryPrice, _Digits), DoubleToString(exitPrice, _Digits),
             DoubleToString(stopPrice,  _Digits), DoubleToString(tpPrice,   _Digits),
             DoubleToString(initialRisk,_Digits), exitReason,
             DoubleToString(grossProfit,2), DoubleToString(commission,2),
             DoubleToString(swap,2),        DoubleToString(netProfit,2),
             DoubleToString(rValue,3), score, DoubleToString(confidenceMult,2),
             regime, brokerExitReason, entryComment,
             DoubleToString(sessionMult,2), DoubleToString(regimeMult,2),
             DoubleToString(zonePrice,_Digits),
             TimeToString(zoneTimeUtc, TIME_DATE|TIME_SECONDS), exitComment);
   FileFlush(m_tradeCsvHandle);
}

//+------------------------------------------------------------------+
//| Export functions (unchanged)                                      |
//+------------------------------------------------------------------+
void ExportTesterTrades() {
   string fileName = "phantom_mt5_tester_export_v8e.csv";
   int handle = FileOpen(fileName, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ';');
   if(handle == INVALID_HANDLE) return;

   FileWrite(handle,
             "entry_time_utc","exit_time_utc","ticket","symbol","direction","volume",
             "entry_price","exit_price","stop_price","tp_price","initial_risk","exit_reason",
             "gross_profit","commission","swap","net_profit","r_value","score",
             "confidence_mult","regime","broker_exit_reason","entry_comment",
             "session_mult","regime_mult","zone_price","zone_time_utc","exit_comment","holding_minutes");

   if(!HistorySelect(0, TimeCurrent() + 86400)) { FileClose(handle); return; }
   long dealsTotal = HistoryDealsTotal();
   int rowsWritten = 0;

   for(int i = 0; i < dealsTotal; i++) {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;
      if(HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagicNumber) continue;
      long dealEntry = HistoryDealGetInteger(deal, DEAL_ENTRY);
      if(dealEntry != DEAL_ENTRY_OUT && dealEntry != DEAL_ENTRY_OUT_BY && dealEntry != DEAL_ENTRY_INOUT) continue;

      ulong positionId = (ulong)HistoryDealGetInteger(deal, DEAL_POSITION_ID);
      datetime exitTime    = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
      double   exitPrice   = HistoryDealGetDouble(deal, DEAL_PRICE);
      double   exitProfit  = HistoryDealGetDouble(deal, DEAL_PROFIT);
      double   exitCommission = HistoryDealGetDouble(deal, DEAL_COMMISSION);
      double   exitSwap    = HistoryDealGetDouble(deal, DEAL_SWAP);
      double   exitVolume  = HistoryDealGetDouble(deal, DEAL_VOLUME);
      string   exitComment = HistoryDealGetString(deal, DEAL_COMMENT);
      long     dealReason  = HistoryDealGetInteger(deal, DEAL_REASON);

      datetime entryTime = 0; double entryPrice = 0.0; int direction = 0;
      for(int j = 0; j < dealsTotal; j++) {
         ulong entryDeal = HistoryDealGetTicket(j);
         if(entryDeal == 0) continue;
         if((ulong)HistoryDealGetInteger(entryDeal, DEAL_POSITION_ID) != positionId) continue;
         if(HistoryDealGetInteger(entryDeal, DEAL_MAGIC) != InpMagicNumber) continue;
         if(HistoryDealGetInteger(entryDeal, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
         entryTime  = (datetime)HistoryDealGetInteger(entryDeal, DEAL_TIME);
         entryPrice = HistoryDealGetDouble(entryDeal, DEAL_PRICE);
         direction  = (HistoryDealGetInteger(entryDeal, DEAL_TYPE) == DEAL_TYPE_BUY) ? 1 : -1;
         break;
      }
      if(entryTime == 0) continue;

      double stopPrice = 0.0, tpPrice = 0.0, confidenceMult = 1.0;
      double zonePrice = 0.0, sessionMult = 1.0, regimeMult = 1.0;
      int score = 0; string regime = "unknown", entryComment2 = ""; datetime zoneTimeUtc = 0;

      int metaIndex = FindPositionMeta(positionId);
      if(metaIndex >= 0) {
         stopPrice      = m_pos_meta[metaIndex].stop_price;
         tpPrice        = m_pos_meta[metaIndex].tp_price;
         score          = m_pos_meta[metaIndex].total_score;
         confidenceMult = m_pos_meta[metaIndex].confidence_mult;
         regime         = m_pos_meta[metaIndex].regime;
         entryComment2  = m_pos_meta[metaIndex].entry_comment;
         sessionMult    = m_pos_meta[metaIndex].session_mult;
         regimeMult     = m_pos_meta[metaIndex].regime_mult;
         zonePrice      = m_pos_meta[metaIndex].zone_price;
         zoneTimeUtc    = m_pos_meta[metaIndex].zone_time_utc;
      }

      double initialRisk  = MathAbs(entryPrice - stopPrice);
      double netProfit    = exitProfit + exitCommission + exitSwap;
      double rValue       = (initialRisk > 0.0) ? ((direction == 1) ? (exitPrice - entryPrice) / initialRisk
                                                                     : (entryPrice - exitPrice) / initialRisk) : 0.0;
      string exitReason   = InferExitReason(exitPrice, stopPrice, tpPrice);
      double holdingMinutes = (double)(exitTime - entryTime) / 60.0;

      FileWrite(handle,
                TimeToString(entryTime, TIME_DATE|TIME_SECONDS),
                TimeToString(exitTime,  TIME_DATE|TIME_SECONDS),
                (long)positionId, Symbol(), TradeDirectionToString(direction), DoubleToString(exitVolume,2),
                DoubleToString(entryPrice,_Digits), DoubleToString(exitPrice,_Digits),
                DoubleToString(stopPrice, _Digits), DoubleToString(tpPrice,  _Digits),
                DoubleToString(initialRisk,_Digits), exitReason,
                DoubleToString(exitProfit,2),      DoubleToString(exitCommission,2),
                DoubleToString(exitSwap,2),         DoubleToString(netProfit,2),
                DoubleToString(rValue,3), score,    DoubleToString(confidenceMult,2),
                regime, DealReasonToString(dealReason), entryComment2,
                DoubleToString(sessionMult,2),      DoubleToString(regimeMult,2),
                DoubleToString(zonePrice,_Digits),
                TimeToString(zoneTimeUtc, TIME_DATE|TIME_SECONDS),
                exitComment, DoubleToString(holdingMinutes,1));
      rowsWritten++;
   }
   FileClose(handle);
}

void ExportAllDealsToCSV() {
   int fileHandle = FileOpen("phantom_mt5_export_v8e.csv", FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ';');
   if(fileHandle == INVALID_HANDLE) return;
   if(!HistorySelect(0, TimeCurrent() + 86400)) { FileClose(fileHandle); return; }

   FileWrite(fileHandle, "entry_time","exit_time","ticket","symbol","direction","volume",
             "entry_price","exit_price","stop_loss","take_profit","gross_profit",
             "commission","swap","net_profit","profit_percent","exit_type");

   long dealsTotal = HistoryDealsTotal();
   for(int i = 0; i < dealsTotal; i++) {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;
      if(HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagicNumber) continue;
      if(HistoryDealGetInteger(deal, DEAL_ENTRY) == DEAL_ENTRY_IN) continue;

      datetime exitTime    = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
      double   exitPrice   = HistoryDealGetDouble(deal, DEAL_PRICE);
      double   exitProfit  = HistoryDealGetDouble(deal, DEAL_PROFIT);
      double   exitCommission = HistoryDealGetDouble(deal, DEAL_COMMISSION);
      double   exitSwap    = HistoryDealGetDouble(deal, DEAL_SWAP);
      ulong    positionId  = HistoryDealGetInteger(deal, DEAL_POSITION_ID);

      datetime entryTime = 0; double entryPrice = 0; int direction = 0;
      for(int j = 0; j < dealsTotal; j++) {
         ulong entryDeal = HistoryDealGetTicket(j);
         if(HistoryDealGetInteger(entryDeal, DEAL_POSITION_ID) == positionId &&
            HistoryDealGetInteger(entryDeal, DEAL_ENTRY) == DEAL_ENTRY_IN) {
            entryTime  = (datetime)HistoryDealGetInteger(entryDeal, DEAL_TIME);
            entryPrice = HistoryDealGetDouble(entryDeal, DEAL_PRICE);
            direction  = (HistoryDealGetInteger(entryDeal, DEAL_TYPE) == DEAL_TYPE_BUY) ? 1 : -1;
            break;
         }
      }
      if(entryTime == 0) continue;

      double stopPrice = 0, tpPrice = 0;
      int metaIndex = FindPositionMeta(positionId);
      if(metaIndex >= 0) { stopPrice = m_pos_meta[metaIndex].stop_price; tpPrice = m_pos_meta[metaIndex].tp_price; }

      string exitType = (exitPrice <= stopPrice + SymbolInfoDouble(Symbol(), SYMBOL_POINT)) ? "sl" : "tp";
      FileWrite(fileHandle,
                TimeToString(entryTime, TIME_DATE|TIME_SECONDS),
                TimeToString(exitTime,  TIME_DATE|TIME_SECONDS),
                (long)positionId, Symbol(), (direction == 1) ? "long" : "short",
                DoubleToString(HistoryDealGetDouble(deal, DEAL_VOLUME),2),
                DoubleToString(entryPrice,_Digits), DoubleToString(exitPrice,_Digits),
                DoubleToString(stopPrice,_Digits),  DoubleToString(tpPrice,  _Digits),
                DoubleToString(exitProfit,2),        DoubleToString(exitCommission,2),
                DoubleToString(exitSwap,2),
                DoubleToString((exitProfit+exitCommission+exitSwap),2),
                DoubleToString(((exitPrice-entryPrice)/entryPrice*100),2), exitType);
   }
   FileClose(fileHandle);
}

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit() {
   m_trade.SetExpertMagicNumber(InpMagicNumber);
   m_trade.SetDeviationInPoints(30);
   m_symbol.Name(Symbol());
   m_symbol.Refresh();

   m_handleH4ATR_Debug = iATR(Symbol(), PERIOD_H4, InpEWMATRPeriod);
   if(m_handleH4ATR_Debug == INVALID_HANDLE)
      Print("V8E WARNING: Could not create Wilder debug handle");

   m_handleH4EMA20    = iMA(Symbol(), PERIOD_H4, 20,  0, MODE_EMA, PRICE_CLOSE);
   m_handleH4EMA50    = iMA(Symbol(), PERIOD_H4, 50,  0, MODE_EMA, PRICE_CLOSE);
   m_handleH4RSI      = iRSI(Symbol(), PERIOD_H4, 14, PRICE_CLOSE);
   m_handleH1EMA20    = iMA(Symbol(), PERIOD_H1, 20,  0, MODE_EMA, PRICE_CLOSE);
   m_handleH1EMA50    = iMA(Symbol(), PERIOD_H1, 50,  0, MODE_EMA, PRICE_CLOSE);
   m_handleH1RSI      = iRSI(Symbol(), PERIOD_H1, 14, PRICE_CLOSE);
   m_handleM5EMA20    = iMA(Symbol(), PERIOD_M5, 20,  0, MODE_EMA, PRICE_CLOSE);
   m_handleM5EMA50    = iMA(Symbol(), PERIOD_M5, 50,  0, MODE_EMA, PRICE_CLOSE);
   m_handleM5RSI      = iRSI(Symbol(), PERIOD_M5, 14, PRICE_CLOSE);
   m_handleM5Volume   = iVolumes(Symbol(), PERIOD_M5, VOLUME_TICK);
   m_handleDailyEMA50 = iMA(Symbol(), PERIOD_D1, 50,  0, MODE_EMA, PRICE_CLOSE);
   m_handleDailyEMA200= iMA(Symbol(), PERIOD_D1, 200, 0, MODE_EMA, PRICE_CLOSE);

   if(InpAutoDetectUTC) {
      m_detectedUTCOffsetHours = (int)MathRound((double)(TimeCurrent() - TimeGMT()) / 3600.0);
      PrintFormat("V8E UTC: Auto-detected offset = %+d hours", m_detectedUTCOffsetHours);
   } else {
      m_detectedUTCOffsetHours = InpManualUTCOffset;
      PrintFormat("V8E UTC: Manual offset = %+d hours", m_detectedUTCOffsetHours);
   }

   MqlDateTime utcNow;
   TimeToStruct(ToUTC(TimeCurrent()), utcNow);
   PrintFormat("V8E Session: UTC hour=%d | Session=%d:00-%d:00",
               utcNow.hour, InpSessionStart, InpSessionEnd);

   if(InpEnableDebugPrint) {
      PrintFormat("V8E ZoneFlip: enabled=%s | breakATRFrac=%.2f | breakBars=%d",
                  InpZoneFlipEnabled ? "YES" : "NO",
                  InpZoneBreakATRFrac, InpZoneBreakBars);
      PrintFormat("V8b ZoneTouch: required=%s | bounceBars=%d | bounceATRFrac=%.2f",
                  InpZoneTouchRequired ? "YES" : "NO",
                  InpZoneBounceBars, InpZoneBounceATRFrac);
   }

   m_zoneCount            = 0;
   m_consecutiveLosses    = 0;
   m_lastEntryTime        = 0;
   m_lastLossExitTime     = 0;
   m_circuitBreakerUntil  = 0;
   m_ftmoInitialEquity    = AccountInfoDouble(ACCOUNT_EQUITY);
   m_ftmoDayStartEquity   = m_ftmoInitialEquity;
   m_ftmoTradingStartUtc  = ToUTC(TimeCurrent());
   m_ftmoCurrentDayKey    = 0;
   m_ftmoHardStop         = false;
   m_ftmoLastStatusPrint  = 0;
   m_ewmDebugCount        = 0;
   m_ewmDebugDone         = false;
   ArrayResize(m_pos_meta,        0);
   ArrayResize(m_entry_times_utc, 0);
   ArrayResize(m_ftmoTradeDayKeys,0);
   ArrayResize(m_closed_positions,0);

   OpenTradeCsv();
   BuildH4Zones();
   EventSetTimer(300);

   Print("Phantom P2 US100 V8E initialized — V8C + Zone Direction Flip");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
   if(m_handleH4ATR_Debug != INVALID_HANDLE) { IndicatorRelease(m_handleH4ATR_Debug); m_handleH4ATR_Debug = INVALID_HANDLE; }
   IndicatorRelease(m_handleH4EMA20);  IndicatorRelease(m_handleH4EMA50);  IndicatorRelease(m_handleH4RSI);
   IndicatorRelease(m_handleH1EMA20);  IndicatorRelease(m_handleH1EMA50);  IndicatorRelease(m_handleH1RSI);
   IndicatorRelease(m_handleM5EMA20);  IndicatorRelease(m_handleM5EMA50);  IndicatorRelease(m_handleM5RSI);
   IndicatorRelease(m_handleM5Volume);
   IndicatorRelease(m_handleDailyEMA50); IndicatorRelease(m_handleDailyEMA200);
   if(InpEnableVisuals) ObjectsDeleteAll(0, "Zone_");
   ExportAllDealsToCSV();
   CloseTradeCsv();
   EventKillTimer();
   Comment("");
}

//+------------------------------------------------------------------+
//| OnTick                                                            |
//+------------------------------------------------------------------+
void OnTick() {
   static datetime lastBarM5 = 0;
   datetime currentBarM5 = iTime(Symbol(), PERIOD_M5, 0);
   if(currentBarM5 == lastBarM5) return;
   lastBarM5 = currentBarM5;

   static datetime lastZoneRefresh = 0;
   if(TimeCurrent() - lastZoneRefresh > 300) {
      BuildH4Zones();
      lastZoneRefresh = TimeCurrent();
   }

   ManageOpenPositions();
   LogClosedTradesFromHistory();
   CheckEntryConditions();
}

void OnTimer() {
   BuildH4Zones();
   if(InpEnableVisuals) DrawZones();
}

//+------------------------------------------------------------------+
//| PreserveTouchState — V8E: also preserve flip fields              |
//+------------------------------------------------------------------+
void PreserveTouchState(SZone &oldZones[], int oldCount)
{
   double tol = InpZoneTolerance;
   for(int i = 0; i < m_zoneCount; i++)
   {
      for(int j = 0; j < oldCount; j++)
      {
         if(m_zones[i].direction == oldZones[j].direction &&
            MathAbs(m_zones[i].price - oldZones[j].price) / MathMax(m_zones[i].price, 1.0) <= tol)
         {
            // V8b fields
            m_zones[i].touch_logged        = oldZones[j].touch_logged;
            m_zones[i].last_touch_time     = oldZones[j].last_touch_time;
            m_zones[i].touch_count         = oldZones[j].touch_count;
            m_zones[i].bounce_confirmed    = oldZones[j].bounce_confirmed;
            m_zones[i].bounce_confirmed_at = oldZones[j].bounce_confirmed_at;
            m_zones[i].bars_away           = oldZones[j].bars_away;
            m_zones[i].last_entry_day_key  = oldZones[j].last_entry_day_key;
            // V8E fields
            m_zones[i].effective_dir       = oldZones[j].effective_dir;
            m_zones[i].broken              = oldZones[j].broken;
            m_zones[i].broken_at           = oldZones[j].broken_at;
            m_zones[i].break_bars_count    = oldZones[j].break_bars_count;
            break;
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Zone building                                                     |
//+------------------------------------------------------------------+
void BuildH4Zones() {
   SZone oldZones[];
   int   oldCount = m_zoneCount;
   ArrayResize(oldZones, oldCount);
   for(int k = 0; k < oldCount; k++) oldZones[k] = m_zones[k];

   ArrayResize(m_zones, 0);
   m_zoneCount = 0;
   int bars = iBars(Symbol(), PERIOD_H4);
   double highs[], lows[]; datetime times[];
   if(bars <= (InpPivotBars * 2)) return;
   ArraySetAsSeries(highs, false); ArraySetAsSeries(lows, false); ArraySetAsSeries(times, false);
   CopyHigh(Symbol(), PERIOD_H4, 0, bars, highs);
   CopyLow (Symbol(), PERIOD_H4, 0, bars, lows);
   CopyTime(Symbol(), PERIOD_H4, 0, bars, times);

   for(int i = InpPivotBars; i < bars - InpPivotBars; i++) {
      datetime confirmedAt = times[i + InpPivotBars];
      if(IsPivotHigh(highs, i, InpPivotBars)) AddZone(confirmedAt, highs[i], -1);
      if(IsPivotLow (lows,  i, InpPivotBars)) AddZone(confirmedAt, lows[i],   1);
   }

   if(oldCount > 0) PreserveTouchState(oldZones, oldCount);
}

bool IsPivotHigh(double &highs[], int index, int bars) {
   double pivotHigh = highs[index];
   for(int j = 1; j <= bars; j++) { if(highs[index-j] > pivotHigh || highs[index+j] > pivotHigh) return false; }
   return true;
}

bool IsPivotLow(double &lows[], int index, int bars) {
   double pivotLow = lows[index];
   for(int j = 1; j <= bars; j++) { if(lows[index-j] < pivotLow || lows[index+j] < pivotLow) return false; }
   return true;
}

void AddZone(datetime confirmedAt, double price, int direction) {
   int size = ArraySize(m_zones);
   ArrayResize(m_zones, size + 1);
   datetime confirmedUtc = ToUTC(confirmedAt);

   m_zones[size].time              = confirmedUtc;
   m_zones[size].price             = price;
   m_zones[size].direction         = direction;
   m_zones[size].source_tf         = PERIOD_H4;
   m_zones[size].origin_time_utc   = confirmedUtc;
   int confirmMinutes = InpMinConfirmBars * PeriodSeconds(InpConfirmTF) / 60;
   m_zones[size].confirmed_at      = confirmedUtc + confirmMinutes * 60;
   m_zones[size].confirmed         = (ToUTC(TimeCurrent()) >= m_zones[size].confirmed_at);

   // V8b
   m_zones[size].touch_logged      = false;
   m_zones[size].last_touch_time   = 0;
   m_zones[size].touch_count       = 0;
   m_zones[size].bounce_confirmed  = false;
   m_zones[size].bounce_confirmed_at = 0;
   m_zones[size].bars_away         = 0;
   m_zones[size].last_entry_day_key = 0;

   // V8E
   m_zones[size].effective_dir     = direction;  // starts equal to original direction
   m_zones[size].broken            = false;
   m_zones[size].broken_at         = 0;
   m_zones[size].break_bars_count  = 0;

   m_zoneCount++;
}

//+------------------------------------------------------------------+
//| V8b: UpdateZoneTouches (unchanged from V8C)                      |
//+------------------------------------------------------------------+
void UpdateZoneTouches(datetime barTimeUtc, double barClose, double m15ATR)
{
   double bounceThresh = InpZoneBounceATRFrac * m15ATR;

   for(int i = 0; i < m_zoneCount; i++)
   {
      if(!m_zones[i].confirmed && barTimeUtc < m_zones[i].confirmed_at) continue;

      double dist = MathAbs(barClose - m_zones[i].price);
      bool inBand = (dist / MathMax(m_zones[i].price, 1.0)) <= InpZoneTolerance;

      if(m_zones[i].bounce_confirmed)
      {
         bool invalidated = (m_zones[i].direction == 1 && barClose < m_zones[i].price * (1 - InpZoneTolerance)) ||
                            (m_zones[i].direction == -1 && barClose > m_zones[i].price * (1 + InpZoneTolerance));
         if(invalidated)
         {
            m_zones[i].bounce_confirmed    = false;
            m_zones[i].bounce_confirmed_at = 0;
            m_zones[i].bars_away           = 0;
            m_zones[i].touch_logged        = false;
         }
      }

      if(inBand)
      {
         bool isNewTouch = (m_zones[i].touch_count == 0) ||
                           ((barTimeUtc - m_zones[i].last_touch_time) > 4 * PeriodSeconds(PERIOD_M5));
         if(isNewTouch)
         {
            m_zones[i].touch_logged    = true;
            m_zones[i].last_touch_time = barTimeUtc;
            m_zones[i].touch_count++;
            if(!m_zones[i].bounce_confirmed)
               m_zones[i].bars_away = 0;
         }
         else
         {
            if(!m_zones[i].bounce_confirmed)
               m_zones[i].bars_away = 0;
         }
      }
      else if(m_zones[i].touch_logged && !m_zones[i].bounce_confirmed)
      {
         if(dist >= bounceThresh)
         {
            m_zones[i].bars_away++;
            if(m_zones[i].bars_away >= InpZoneBounceBars)
            {
               m_zones[i].bounce_confirmed    = true;
               m_zones[i].bounce_confirmed_at = barTimeUtc;
            }
         }
         else
            m_zones[i].bars_away = 0;
      }
   }
}

//+------------------------------------------------------------------+
//| V8E: UpdateZoneBreaks                                            |
//|                                                                  |
//| Called once per M5 bar, AFTER UpdateZoneTouches.                |
//|                                                                  |
//| Break rule: a confirmed zone is considered broken when price     |
//| closes beyond the zone + InpZoneBreakATRFrac * M15ATR on the    |
//| OPPOSITE side from its original direction, for at least         |
//| InpZoneBreakBars consecutive M5 bars.                           |
//|                                                                  |
//| On break confirmation: effective_dir is flipped.                |
//|   demand (dir=1):  price closes below zone → effective_dir = -1 |
//|   supply (dir=-1): price closes above zone → effective_dir =  1 |
//|                                                                  |
//| Flip reset: if price returns inside the tolerance band after a  |
//| flip, effective_dir resets to original direction.               |
//+------------------------------------------------------------------+
void UpdateZoneBreaks(datetime barTimeUtc, double barClose, double m15ATR)
{
   if(!InpZoneFlipEnabled) return;

   double breakDist = InpZoneBreakATRFrac * m15ATR;

   for(int i = 0; i < m_zoneCount; i++)
   {
      // Only apply to confirmed zones
      if(!m_zones[i].confirmed && barTimeUtc < m_zones[i].confirmed_at) continue;

      int origDir = m_zones[i].direction;

      // Check if price is on the "wrong" side of the zone (break candidate)
      bool onWrongSide = false;
      if(origDir == 1)  // demand: wrong side = below zone
         onWrongSide = (barClose < m_zones[i].price - breakDist);
      else              // supply: wrong side = above zone
         onWrongSide = (barClose > m_zones[i].price + breakDist);

      if(onWrongSide)
      {
         m_zones[i].break_bars_count++;
         if(m_zones[i].break_bars_count >= InpZoneBreakBars && !m_zones[i].broken)
         {
            m_zones[i].broken        = true;
            m_zones[i].broken_at     = barTimeUtc;
            m_zones[i].effective_dir = -origDir;  // flip direction

            if(InpEnableDebugPrint)
               PrintFormat("V8E ZoneFlip[%d]: price=%.4f zone=%.4f origDir=%s → effectiveDir=%s time=%s",
                           i, barClose, m_zones[i].price,
                           (origDir == 1) ? "demand" : "supply",
                           (m_zones[i].effective_dir == 1) ? "demand" : "supply",
                           TimeToString(barTimeUtc, TIME_DATE|TIME_MINUTES));
         }
      }
      else
      {
         // Price not on wrong side — reset break count
         m_zones[i].break_bars_count = 0;

         // If previously broken but price returned to band, reset flip
         if(m_zones[i].broken)
         {
            double dist = MathAbs(barClose - m_zones[i].price);
            bool inBand = (dist / MathMax(m_zones[i].price, 1.0)) <= InpZoneTolerance;
            // Only reset flip if price is meaningfully back on the original side
            bool backOnOrigSide = false;
            if(origDir == 1)  backOnOrigSide = (barClose > m_zones[i].price + breakDist * 0.5);
            else               backOnOrigSide = (barClose < m_zones[i].price - breakDist * 0.5);

            if(backOnOrigSide)
            {
               m_zones[i].broken       = false;
               m_zones[i].broken_at    = 0;
               m_zones[i].effective_dir = origDir;
               if(InpEnableDebugPrint)
                  PrintFormat("V8E ZoneUnflip[%d]: zone=%.4f restored to original dir=%s",
                              i, m_zones[i].price, (origDir==1)?"demand":"supply");
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Position management (unchanged from V8C)                         |
//+------------------------------------------------------------------+
void ManageOpenPositions() {
   datetime barTime    = iTime  (Symbol(), PERIOD_M5, 1);
   double   barClose   = iClose (Symbol(), PERIOD_M5, 1);
   double   barHigh    = iHigh  (Symbol(), PERIOD_M5, 1);
   double   barLow     = iLow   (Symbol(), PERIOD_M5, 1);
   datetime barTimeUtc = ToUTC(barTime);

   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      if(m_position.SelectByIndex(i)) {
         if(m_position.Symbol() != Symbol() || m_position.Magic() != InpMagicNumber) continue;
         ulong ticket    = m_position.Ticket();
         int   metaIndex = FindPositionMeta(ticket);
         if(metaIndex < 0) continue;

         double entryPrice  = m_pos_meta[metaIndex].entry_price;
         double stopPrice   = m_pos_meta[metaIndex].stop_price;
         double tpPrice     = m_pos_meta[metaIndex].tp_price;
         double initialRisk = m_pos_meta[metaIndex].initial_risk;
         double atrEntry    = m_pos_meta[metaIndex].atr_entry;
         bool   isLong      = (m_pos_meta[metaIndex].direction == 1);

         if(atrEntry > 0) {
            double trailDistance = InpTrailATRMult * atrEntry;
            if(isLong) { double newTrail = barClose - trailDistance; if(newTrail > stopPrice) stopPrice = newTrail; }
            else       { double newTrail = barClose + trailDistance; if(newTrail < stopPrice) stopPrice = newTrail; }
         }

         double currentR = (isLong) ? (barClose - entryPrice) / initialRisk
                                    : (entryPrice - barClose) / initialRisk;
         if(!m_pos_meta[metaIndex].be_triggered && currentR >= InpBreakevenR) {
            stopPrice = entryPrice;
            m_pos_meta[metaIndex].be_triggered = true;
         }

         int barsPerHour  = MathMax(1, 60 / 5);
         int minHoldBars  = 2 * barsPerHour;
         int holdBars     = (int)((barTime - m_pos_meta[metaIndex].entry_time) / PeriodSeconds(PERIOD_M5));
         bool allowStopExit = (holdBars >= minHoldBars) || (currentR >= 0.0);

         bool   exitNow      = false;
         double exitSignalPx = 0.0;
         if(isLong) {
            if(allowStopExit && barLow  <= stopPrice) { exitSignalPx = stopPrice; exitNow = true; }
            else if(barHigh >= tpPrice)               { exitSignalPx = tpPrice;   exitNow = true; }
         } else {
            if(allowStopExit && barHigh >= stopPrice) { exitSignalPx = stopPrice; exitNow = true; }
            else if(barLow   <= tpPrice)              { exitSignalPx = tpPrice;   exitNow = true; }
         }

         m_pos_meta[metaIndex].stop_price = stopPrice;

         double currentBrokerStop = m_position.StopLoss();
         if(MathAbs(stopPrice - currentBrokerStop) > SymbolInfoDouble(Symbol(), SYMBOL_POINT))
            m_trade.PositionModify(ticket, stopPrice, tpPrice);

         if(exitNow) {
            double volume      = m_position.Volume();
            double tickSize    = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_SIZE);
            double tickValue   = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_VALUE);
            double grossProfit = (isLong) ? (exitSignalPx - entryPrice) * volume * tickValue / tickSize
                                          : (entryPrice - exitSignalPx) * volume * tickValue / tickSize;
            double rValue      = (initialRisk > 0.0) ? (grossProfit / (initialRisk * tickValue / tickSize)) : 0.0;
            string exitReason  = InferExitReason(exitSignalPx, stopPrice, tpPrice);
            LogTradeCsvRow(m_pos_meta[metaIndex].entry_time_utc, barTimeUtc, ticket,
                           m_pos_meta[metaIndex].direction, volume,
                           entryPrice, exitSignalPx, stopPrice, tpPrice, initialRisk,
                           exitReason, grossProfit, 0, 0, grossProfit, rValue,
                           m_pos_meta[metaIndex].total_score,
                           m_pos_meta[metaIndex].confidence_mult,
                           m_pos_meta[metaIndex].regime,
                           (exitSignalPx <= stopPrice + SymbolInfoDouble(Symbol(), SYMBOL_POINT)) ? "sl" : "tp",
                           m_pos_meta[metaIndex].entry_comment,
                           m_pos_meta[metaIndex].session_mult,
                           m_pos_meta[metaIndex].regime_mult,
                           m_pos_meta[metaIndex].zone_price,
                           m_pos_meta[metaIndex].zone_time_utc, "auto_close");
            m_trade.PositionClose(ticket);
         }
      }
   }
}

void LogClosedTradesFromHistory() {
   long dealsTotal = HistoryDealsTotal();
   for(int i = 0; i < dealsTotal; i++) {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;
      if(HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagicNumber) continue;
      long dealEntry = HistoryDealGetInteger(deal, DEAL_ENTRY);
      if(dealEntry != DEAL_ENTRY_OUT && dealEntry != DEAL_ENTRY_OUT_BY && dealEntry != DEAL_ENTRY_INOUT) continue;
      ulong positionId   = HistoryDealGetInteger(deal, DEAL_POSITION_ID);
      bool  alreadyLogged = false;
      for(int j = 0; j < ArraySize(m_pos_meta); j++) {
         if(m_pos_meta[j].ticket == positionId && m_pos_meta[j].logged) { alreadyLogged = true; break; }
      }
      if(alreadyLogged) continue;
      int metaIndex = FindPositionMeta(positionId);
      if(metaIndex < 0) continue;

      datetime dealTime       = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
      double   dealPrice      = HistoryDealGetDouble(deal, DEAL_PRICE);
      double   dealProfit     = HistoryDealGetDouble(deal, DEAL_PROFIT);
      double   dealCommission = HistoryDealGetDouble(deal, DEAL_COMMISSION);
      double   dealSwap       = HistoryDealGetDouble(deal, DEAL_SWAP);
      double   dealVolume     = HistoryDealGetDouble(deal, DEAL_VOLUME);
      string   dealComment    = HistoryDealGetString(deal, DEAL_COMMENT);
      long     dealReason     = HistoryDealGetInteger(deal, DEAL_REASON);

      SPositionMeta meta = m_pos_meta[metaIndex];
      string exitReason  = InferExitReason(dealPrice, meta.stop_price, meta.tp_price);
      double netProfit   = dealProfit + dealCommission + dealSwap;
      double rValue      = (meta.initial_risk > 0.0)
                           ? ((meta.direction == 1) ? (dealPrice - meta.entry_price) / meta.initial_risk
                                                    : (meta.entry_price - dealPrice) / meta.initial_risk)
                           : 0.0;
      LogTradeCsvRow(meta.entry_time_utc, dealTime, positionId, meta.direction, dealVolume,
                     meta.entry_price, dealPrice, meta.stop_price, meta.tp_price, meta.initial_risk,
                     exitReason, dealProfit, dealCommission, dealSwap, netProfit, rValue,
                     meta.total_score, meta.confidence_mult, meta.regime,
                     DealReasonToString(dealReason),
                     meta.entry_comment, meta.session_mult, meta.regime_mult,
                     meta.zone_price, meta.zone_time_utc, dealComment);
      m_pos_meta[metaIndex].logged = true;
   }
}

//+------------------------------------------------------------------+
//| CheckEntryConditions                                             |
//| V8E: UpdateZoneBreaks() added after UpdateZoneTouches().        |
//|      All entry direction logic uses effective_dir, not direction.|
//+------------------------------------------------------------------+
void CheckEntryConditions() {
   datetime barTime = iTime(Symbol(), PERIOD_M5, 1);
   if(!CanTrade(barTime)) return;
   datetime barTimeUtc  = ToUTC(barTime);
   double   signalPrice = iClose(Symbol(), PERIOD_M5, 1);

   double h4ATR  = CalcEWM_ATR_Py(Symbol(), PERIOD_H4,  InpEWMATRPeriod, barTime, true);
   double m15ATR = CalcEWM_ATR_Py(Symbol(), PERIOD_M15, InpEWMATRPeriod, barTime, false);
   if(h4ATR <= 0) return;

   // V8b touch tracking
   UpdateZoneTouches(barTimeUtc, signalPrice, m15ATR);
   // V8E break/flip tracking
   UpdateZoneBreaks(barTimeUtc, signalPrice, m15ATR);

   double   sessionMultForBar = GetSessionMultiplier(barTimeUtc);
   datetime windowStartUtc    = barTimeUtc - (InpZoneLookback * PeriodSeconds(PERIOD_H4));
   int      entryDayKey       = GetUTCDateKey(barTimeUtc);

   for(int i = 0; i < m_zoneCount; i++) {
      if(m_zones[i].time < windowStartUtc || m_zones[i].time >= barTimeUtc) continue;
      if(!m_zones[i].confirmed && barTimeUtc < m_zones[i].confirmed_at) continue;

      // V8E: use effective_dir for all direction-dependent checks
      int eDir = m_zones[i].effective_dir;

      if(MathAbs(signalPrice - m_zones[i].price) / m_zones[i].price > InpZoneTolerance) continue;
      if(m15ATR > 0 && MathAbs(signalPrice - m_zones[i].price) > InpChaseFilterATR * m15ATR) continue;
      if(eDir ==  1 && signalPrice < m_zones[i].price * (1 - InpZoneTolerance)) continue;
      if(eDir == -1 && signalPrice > m_zones[i].price * (1 + InpZoneTolerance)) continue;
      if(sessionMultForBar <= 0 || !CheckClusterCap(barTimeUtc)) continue;
      if(m_zones[i].last_entry_day_key == entryDayKey)
      {
         if(InpEnableDebugPrint)
            PrintFormat("V8E ZoneLocked[%d]: zone=%.4f effectiveDir=%s already traded today",
                        i, m_zones[i].price, (eDir == 1) ? "demand" : "supply");
         continue;
      }

      // V8b bounce gate
      if(InpZoneTouchRequired && !m_zones[i].bounce_confirmed) continue;

      string regime     = GetDailyRegime(barTime);
      double regimeMult = GetRegimeMultiplier(regime, eDir);
      int    h4Score    = GetTFScoreAtTime(PERIOD_H4, eDir, barTime);
      int    h1Score    = GetTFScoreAtTime(PERIOD_H1, eDir, barTime);
      int    m5Score    = GetTFScoreAtTime(PERIOD_M5, eDir, barTime);
      int    totalScore = h4Score + h1Score + m5Score;
      int    ltfAgg     = h1Score + m5Score;
      int    effectiveScoreMin = InpScoreMin + ((eDir == 1) ? InpLongScoreOffset : 0);

      bool counterTrend = ((regime == "bull" && eDir == -1) ||
                           (regime == "bear" && eDir ==  1));
      if(eDir == -1)
      {
         if(h4Score < InpH4ScoreMin || h1Score < InpH1ScoreMin || m5Score < InpLTFScoreMin) continue;
         if(totalScore < effectiveScoreMin) continue;
      }
      else if(counterTrend)
      {
         if(totalScore < InpCTTotalScoreMin) continue;
         if(h4Score    < InpCTH4ScoreMin)   continue;
         if(h1Score    < InpCTH1ScoreMin)   continue;
         if(ltfAgg     < InpCTLTFScoreMin)  continue;
      }
      else
      {
         if(h4Score < InpH4ScoreMin || h1Score < InpH1ScoreMin || m5Score < InpLTFScoreMin) continue;
         if(totalScore < effectiveScoreMin) continue;
      }
      if(m5Score > InpLTFScoreCap) continue;
      double confMult = CalculateConfidenceMultiplier(barTimeUtc);

      ExecuteEntry(m_zones[i], eDir, h4ATR, sessionMultForBar, regimeMult, confMult,
                   totalScore, barTime, barTimeUtc, signalPrice);
      break;
   }
}

bool CanTrade(datetime referenceTime) {
   if(referenceTime < m_circuitBreakerUntil) return false;
   if(CountPositions() >= InpMaxConcurrent) return false;
   if(m_lastEntryTime > 0 && referenceTime - m_lastEntryTime < InpCooldownMin * 60) return false;
   if(m_lastLossExitTime > 0 && referenceTime - m_lastLossExitTime < InpLockoutMin * 60) return false;
   return true;
}

int CountPositions() {
   int count = 0;
   for(int i = 0; i < PositionsTotal(); i++)
      if(m_position.SelectByIndex(i) && m_position.Symbol() == Symbol() && m_position.Magic() == InpMagicNumber)
         count++;
   return count;
}

double GetSessionMultiplier(datetime barTimeUtc = 0) {
   MqlDateTime utc;
   if(barTimeUtc == 0) GetUTCTime(utc);
   else TimeToStruct(barTimeUtc, utc);
   if(utc.day_of_week == 0 || utc.day_of_week == 6) return 0.0;
   if(utc.hour >= InpSessionStart && utc.hour < InpSessionEnd) {
      double mult = 1.0;
      if(InpPeakSessionBoost && utc.hour >= 14 && utc.hour <= 17) mult *= 1.2;
      return mult;
   }
   return 0.0;
}

bool CheckClusterCap(datetime entryUtc) { return CountEntriesInWindow(entryUtc) < InpMaxConcurrent; }

string GetDailyRegime(datetime barTime) {
   double ema50[1], ema200[1];
   int shift = SafeBarShift(Symbol(), PERIOD_D1, barTime);
   if(shift < 0) return "bull";
   if(CopyBuffer(m_handleDailyEMA50,  0, shift, 1, ema50)  < 1) return "bull";
   if(CopyBuffer(m_handleDailyEMA200, 0, shift, 1, ema200) < 1) return "bull";
   return (ema50[0] > ema200[0]) ? "bull" : "bear";
}

double GetRegimeMultiplier(string regime, int direction) {
   if((regime == "bull" && direction ==  1) ||
      (regime == "bear" && direction == -1)) return 1.0;
   return InpCounterTrendMult;
}

int GetTFScoreAtTime(ENUM_TIMEFRAMES tf, int direction, datetime barTime) {
   int handleEMA20, handleEMA50, handleRSI;
   int shift;

   switch(tf) {
      case PERIOD_H4:
         handleEMA20 = m_handleH4EMA20;
         handleEMA50 = m_handleH4EMA50;
         handleRSI   = m_handleH4RSI;
         shift = SafeBarShift(Symbol(), PERIOD_H4, barTime) + 1;
         break;
      case PERIOD_H1:
         handleEMA20 = m_handleH1EMA20;
         handleEMA50 = m_handleH1EMA50;
         handleRSI   = m_handleH1RSI;
         shift = SafeBarShift(Symbol(), PERIOD_H1, barTime);
         break;
      default:
         handleEMA20 = m_handleM5EMA20;
         handleEMA50 = m_handleM5EMA50;
         handleRSI   = m_handleM5RSI;
         shift = SafeBarShift(Symbol(), PERIOD_M5, barTime);
         break;
   }

   if(shift < 0) return 0;

   double close[1], ema20[1], ema50[1], rsi[1];
   if(CopyClose (Symbol(), tf, shift, 1, close) < 1) return 0;
   if(CopyBuffer(handleEMA20, 0, shift, 1, ema20) < 1) return 0;
   if(CopyBuffer(handleEMA50, 0, shift, 1, ema50) < 1) return 0;
   if(CopyBuffer(handleRSI,   0, shift, 1, rsi)   < 1) return 0;
   int score = 0;
   if(direction == 1) {
      if(close[0] > ema20[0]) score++; if(ema20[0] > ema50[0]) score++; if(rsi[0] > 50) score++;
   } else {
      if(close[0] < ema20[0]) score++; if(ema20[0] < ema50[0]) score++; if(rsi[0] < 50) score++;
   }
   return score;
}

double CalculateConfidenceMultiplier(datetime entryUtc) {
   return (CountEntriesInWindow(entryUtc) == 0) ? InpConfidenceMult : 1.0;
}

//+------------------------------------------------------------------+
//| ExecuteEntry — V8E: takes eDir as explicit parameter            |
//+------------------------------------------------------------------+
void ExecuteEntry(SZone &zone, int eDir, double h4ATR, double sessionMult,
                  double regimeMult, double confMult, int totalScore,
                  datetime barTime, datetime barTimeUtc, double signalPrice) {
   double entryPrice = ApplyExecutionAdjustment(signalPrice, eDir, true);
   ENUM_ORDER_TYPE orderType  = (eDir == 1) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double stopDistance = InpATRStopMult * h4ATR;
   double stopPrice    = (eDir ==  1) ? signalPrice - stopDistance : signalPrice + stopDistance;
   double takeProfit   = (eDir ==  1) ? entryPrice  + (InpTPMult * stopDistance)
                                      : entryPrice  - (InpTPMult * stopDistance);

   double accountEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskAmount    = accountEquity * (InpRiskPercent / 100.0) * InpRiskMultiplier;
   double initialRisk   = MathAbs(entryPrice - stopPrice);
   if(initialRisk <= 0) initialRisk = stopDistance;

   double tickSize      = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_SIZE);
   double tickValue     = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_VALUE);
   double contractSize  = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_CONTRACT_SIZE);
   if(contractSize <= 0.0) contractSize = 1.0;

   double riskPerLot    = (tickSize > 0.0 && tickValue > 0.0)
                          ? (initialRisk / tickSize) * tickValue
                          : initialRisk * contractSize;
   double sizeMultiplier = sessionMult * regimeMult * confMult;
   double volume         = (riskAmount / riskPerLot) * sizeMultiplier;

   double lotStep = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_STEP);
   if(lotStep <= 0.0) lotStep = 0.01;
   volume = MathFloor(volume / lotStep) * lotStep;
   volume = MathMax(volume, SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MIN));
   volume = MathMin(volume, SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MAX));

   // V8E: tag flipped zones in comment
   string flipTag = (zone.broken) ? "|FLIP" : "";
   string comment = StringFormat("P2_B_V8E|%s|S=%d|ATR=%.5f|REG=%s|CONF=%.1f|TC=%d%s",
                                 (eDir == 1) ? "LONG" : "SHORT",
                                 totalScore, h4ATR, GetDailyRegime(barTime), confMult,
                                 zone.touch_count, flipTag);

   if(InpEnableDebugPrint)
      PrintFormat("V8E Entry: dir=%s price=%.4f stop=%.4f tp=%.4f vol=%.2f ATR=%.4f flipped=%s",
                  (eDir==1)?"LONG":"SHORT", entryPrice, stopPrice, takeProfit, volume, h4ATR,
                  zone.broken ? "YES" : "NO");

   m_trade.PositionOpen(Symbol(), orderType, volume, entryPrice, stopPrice, takeProfit, comment);

   if(m_trade.ResultRetcode() == TRADE_RETCODE_DONE) {
      ulong ticket = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
         if(m_position.SelectByIndex(i) && m_position.Symbol() == Symbol() && m_position.Magic() == InpMagicNumber)
            { ticket = m_position.Ticket(); break; }
      if(ticket == 0) return;

      int metaIndex = ArraySize(m_pos_meta);
      ArrayResize(m_pos_meta, metaIndex + 1);
      m_pos_meta[metaIndex].ticket          = ticket;
      m_pos_meta[metaIndex].entry_time      = barTime;
      m_pos_meta[metaIndex].entry_time_utc  = barTimeUtc;
      m_pos_meta[metaIndex].entry_comment   = comment;
      m_pos_meta[metaIndex].entry_price     = entryPrice;
      m_pos_meta[metaIndex].stop_price      = stopPrice;
      m_pos_meta[metaIndex].tp_price        = takeProfit;
      m_pos_meta[metaIndex].initial_risk    = initialRisk;
      m_pos_meta[metaIndex].atr_entry       = h4ATR;
      m_pos_meta[metaIndex].be_triggered    = false;
      m_pos_meta[metaIndex].direction       = eDir;
      m_pos_meta[metaIndex].total_score     = totalScore;
      m_pos_meta[metaIndex].confidence_mult = confMult;
      m_pos_meta[metaIndex].session_mult    = sessionMult;
      m_pos_meta[metaIndex].regime_mult     = regimeMult;
      m_pos_meta[metaIndex].regime          = GetDailyRegime(barTime);
      m_pos_meta[metaIndex].zone_time_utc   = zone.time;
      m_pos_meta[metaIndex].zone_price      = zone.price;
      m_pos_meta[metaIndex].logged          = false;
      zone.last_entry_day_key               = GetUTCDateKey(barTimeUtc);
      RegisterEntryTime(barTimeUtc);
      m_lastEntryTime = barTime;
   }
}

//+------------------------------------------------------------------+
//| Helpers (unchanged)                                               |
//+------------------------------------------------------------------+
string TfToShortString(ENUM_TIMEFRAMES tf) {
   switch(tf) {
      case PERIOD_M1:  return "M1";  case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15"; case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";  case PERIOD_D1:  return "D1";
      default: return "TF";
   }
}

double ApplyExecutionAdjustment(double price, int direction, bool isEntry) {
   double adj = price * (InpSpreadBPS / 10000.0) / 2.0 + price * (InpSlippageBPS / 10000.0);
   return (isEntry) ? ((direction == 1) ? price + adj : price - adj)
                    : ((direction == 1) ? price - adj : price + adj);
}

void RegisterEntryTime(datetime entryUtc) {
   int size = ArraySize(m_entry_times_utc);
   ArrayResize(m_entry_times_utc, size + 1);
   m_entry_times_utc[size] = entryUtc;
   PruneEntryTimes(entryUtc);
}

int CountEntriesInWindow(datetime entryUtc) {
   datetime ws = Get4HWindowStart(entryUtc);
   int count = 0;
   for(int i = 0; i < ArraySize(m_entry_times_utc); i++)
      if(m_entry_times_utc[i] >= ws && m_entry_times_utc[i] < ws + PeriodSeconds(PERIOD_H4))
         count++;
   return count;
}

void PruneEntryTimes(datetime nowUtc) {
   datetime cutoff = nowUtc - (48 * 3600);
   for(int i = ArraySize(m_entry_times_utc) - 1; i >= 0; i--)
      if(m_entry_times_utc[i] < cutoff) ArrayRemove(m_entry_times_utc, i, 1);
}

int FindPositionMeta(ulong ticket) {
   for(int i = 0; i < ArraySize(m_pos_meta); i++)
      if(m_pos_meta[i].ticket == ticket) return i;
   return -1;
}

double GetEffectiveZoneTolerance() { return InpZoneTolerance; }

//+------------------------------------------------------------------+
//| Draw zones — V8E: flipped zones drawn in contrasting colour     |
//+------------------------------------------------------------------+
void DrawZones() {
   if(!InpEnableVisuals) return;
   ObjectsDeleteAll(0, "Zone_");
   datetime nowUtc = ToUTC(TimeCurrent());
   for(int i = 0; i < m_zoneCount; i++) {
      if(m_zones[i].time < nowUtc - (InpZoneLookback * PeriodSeconds(PERIOD_H4))) continue;
      string n = StringFormat("Zone_%d", i);
      color clr;
      if(m_zones[i].broken)
         // Flipped zone: show in opposite colour (bright gold for flipped demand→supply, violet for flipped supply→demand)
         clr = (m_zones[i].effective_dir == -1) ? clrGold : clrMediumOrchid;
      else if(!m_zones[i].touch_logged)
         clr = (m_zones[i].direction == 1) ? clrSteelBlue : clrLightCoral;
      else if(m_zones[i].bounce_confirmed)
         clr = (m_zones[i].direction == 1) ? m_demandColor : m_supplyColor;
      else
         clr = (m_zones[i].direction == 1) ? clrCornflowerBlue : clrSalmon;
      ObjectCreate(0, n + "_line", OBJ_TREND, 0,
                   FromUTC(m_zones[i].origin_time_utc), m_zones[i].price,
                   TimeCurrent(), m_zones[i].price);
      ObjectSetInteger(0, n + "_line", OBJPROP_COLOR,     clr);
      ObjectSetInteger(0, n + "_line", OBJPROP_STYLE,     STYLE_SOLID);
      ObjectSetInteger(0, n + "_line", OBJPROP_RAY_RIGHT, false);
   }
   ChartRedraw();
}

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest     &request,
                        const MqlTradeResult      &result) {
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD && HistoryDealSelect(trans.deal)) {
      if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) == InpMagicNumber) {
         long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
         if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY || entry == DEAL_ENTRY_INOUT) {
            double pnl = HistoryDealGetDouble(trans.deal, DEAL_PROFIT)
                       + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION)
                       + HistoryDealGetDouble(trans.deal, DEAL_SWAP);
            if(pnl > 0) m_consecutiveLosses = 0;
            else {
               m_consecutiveLosses++;
               m_lastLossExitTime = (datetime)HistoryDealGetInteger(trans.deal, DEAL_TIME);
               if(m_consecutiveLosses >= InpCircuitBreakerLosses) {
                  m_circuitBreakerUntil = m_lastLossExitTime + InpCircuitBreakerHours * 3600;
                  m_consecutiveLosses   = 0;
               }
            }
         }
      }
   }
}

void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam) {
   if(id == CHARTEVENT_CHART_CHANGE && InpEnableVisuals) DrawZones();
}

int GetUTCDateKey(datetime utcTime) {
   MqlDateTime dt; TimeToStruct(utcTime, dt); return dt.year * 1000 + dt.day_of_year;
}

void RegisterFTMOTradingDay(datetime entryUtc) {
   int dayKey = GetUTCDateKey(entryUtc);
   for(int i = 0; i < ArraySize(m_ftmoTradeDayKeys); i++) if(m_ftmoTradeDayKeys[i] == dayKey) return;
   int s = ArraySize(m_ftmoTradeDayKeys); ArrayResize(m_ftmoTradeDayKeys, s + 1); m_ftmoTradeDayKeys[s] = dayKey;
}

double OnTester() {
   ExportTesterTrades();
   double ddPct = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   return TesterStatistics(STAT_PROFIT) / (ddPct > 0 ? ddPct : 0.01);
}
//+------------------------------------------------------------------+