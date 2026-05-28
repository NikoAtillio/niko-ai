//+------------------------------------------------------------------+
//|                                          Phantom_P2_US100_V5.mq5 |
//|                                    Multi-Timeframe Zone Strategy  |
//|                                             US100 Scenario B      |
//+------------------------------------------------------------------+
//  V5 changelog (vs V4-1):
//    - EWM ATR replaces Wilder iATR (Sprint 1a)
//      * Seed: first bar's TR (matching Python's ewm initialisation)
//      * Alpha: 2/(period+1) matching pandas.ewm(span=N, adjust=False)
//      * Warm-up guard: 5× period bars minimum
//      * Validation logging: first 10 H4 bars print EWM vs Wilder vs Python expected
//    - m_handleH4ATR and m_handleM15ATR iATR handles removed
//    - GetATRAtTime() removed, replaced by CalcEWM_ATR_Py()
//    - NO parameter changes from V4-1 (InpATRStopMult, InpTPMult, etc. unchanged)
//    - All other logic verbatim from V4-1
//+------------------------------------------------------------------+
#property copyright "Phantom P2 MT5"
#property version   "5.00"
#property description "Multi-Timeframe Zone-Based Strategy for US100"
#property description "Scenario B - V5 EWM ATR Sprint 1a"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//+------------------------------------------------------------------+
//| Input Parameters                                                  |
//+------------------------------------------------------------------+
// --- Zone Detection ---
input int      InpPivotBars = 2;
input int      InpZoneLookback = 50;
input double   InpZoneTolerance = 0.002;
input double   InpChaseFilterATR = 1.5;

// --- Session Filter ---
input int      InpSessionStart = 13;
input int      InpSessionEnd = 21;
input bool     InpPeakSessionBoost = true;

// --- Confirmation ---
input int      InpMinConfirmBars = 1;
input ENUM_TIMEFRAMES InpConfirmTF = PERIOD_H1;

// --- Scoring ---
input int      InpScoreMin = 3;
input int      InpH4ScoreMin = 1;
input int      InpH1ScoreMin = 1;
input int      InpLTFScoreMin = 1;
input int      InpLTFScoreCap = 3;
input int      InpLongScoreOffset = 1;

// --- Risk Management ---
input double   InpRiskPercent = 0.7;
input double   InpRiskMultiplier = 2.0;
input double   InpATRStopMult = 1.5;
input double   InpTPMult = 1.3;
input double   InpTrailATRMult = 0.8;
input double   InpBreakevenR = 0.8;
input int      InpMaxConcurrent = 3;
input int      InpCooldownMin = 20;
input bool     InpEnableDebugLogs = true;
input int      InpLockoutMin = 60;
input int      InpCircuitBreakerLosses = 5;
input int      InpCircuitBreakerHours = 24;

// --- FTMO Guardrails ---
input bool     InpEnableFTMOGuardrails = false;
input double   InpFTMOAccountSize = 70000.0;
input double   InpFTMOProfitTargetPct = 5.0;
input double   InpFTMOMaxLossPct = 10.0;
input double   InpFTMOMaxDailyLossPct = 5.0;
input int      InpFTMOTradingPeriodDays = 0;
input int      InpFTMOMinTradingDays = 2;
input double   InpFTMOMaxLeverage = 30.0;

// --- Position Sizing ---
input double   InpConfidenceMult = 1.5;
input double   InpSessionSoftMult = 0.5;
input double   InpCounterTrendMult = 0.5;

// --- Execution (V4: zero defaults) ---
input double   InpSpreadBPS = 0.0;
input double   InpSlippageBPS = 0.0;
input ulong    InpMagicNumber = 202406;
input string   InpComment = "Phantom P2 US100 B";

// --- Time handling (V4: auto-detect with manual override) ---
input bool     InpAutoDetectUTC = false;
input int      InpManualUTCOffset = -5;

// --- V5: EWM ATR ---
input int      InpEWMATRPeriod = 14;          // EWM ATR period (must match Python span=14)
input double   InpPythonExpectedATR = 103.76; // Expected Python H4 ATR on Dec 1 for validation

// --- Development ---
input bool     InpEnableDebugPrint = true;
input bool     InpEnableVisuals = true;
input bool     InpShowOnlyActiveZones = true;
input bool     InpShowZoneOrigins = true;
input bool     InpShowInactiveZoneMarkers = true;
input bool     InpShowZoneTimeframe = true;

//+------------------------------------------------------------------+
//| Global Variables                                                  |
//+------------------------------------------------------------------+
CTrade         m_trade;
CPositionInfo  m_position;
CAccountInfo   m_account;
CSymbolInfo    m_symbol;

// Indicator handles
// V5: m_handleH4ATR and m_handleM15ATR removed — replaced by CalcEWM_ATR_Py()
// V5: m_handleH4ATR_Debug retained ONLY for validation logging in Sprint 1a
int            m_handleH4ATR_Debug;   // Wilder ATR — used only in EWM validation log, released after 10 prints
int            m_handleH4EMA20, m_handleH4EMA50, m_handleH4RSI;
int            m_handleH1EMA20, m_handleH1EMA50, m_handleH1RSI;
int            m_handleM5EMA20, m_handleM5EMA50, m_handleM5RSI, m_handleM5Volume;
int            m_handleDailyEMA50, m_handleDailyEMA200;

// V4: Detected UTC offset
int            m_detectedUTCOffsetHours = 0;

// V5: EWM ATR validation counter
int            m_ewmDebugCount = 0;
bool           m_ewmDebugDone  = false;

// Zone arrays
struct SZone {
   datetime    time;
   double      price;
   int         direction;
   ENUM_TIMEFRAMES source_tf;
   datetime    origin_time_utc;
   bool        confirmed;
   datetime    confirmed_at;
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
string        m_tradeCsvFileName = "phantom_mql5_trade_log_v5.csv";

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
//| V4: SafeBarShift                                                  |
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
//| V4: UTC helpers                                                   |
//+------------------------------------------------------------------+
int GetEffectiveUTCOffset() { return m_detectedUTCOffsetHours; }

datetime ToUTC(datetime serverTime)   { return serverTime - (m_detectedUTCOffsetHours * 3600); }
datetime FromUTC(datetime utcTime)    { return utcTime    + (m_detectedUTCOffsetHours * 3600); }

void GetUTCTime(MqlDateTime &utc)     { TimeToStruct(ToUTC(TimeCurrent()), utc); }

//+------------------------------------------------------------------+
//| V4: DST-safe 4H window                                           |
//+------------------------------------------------------------------+
datetime Get4HWindowStart(datetime timeUtc)
{
   return (timeUtc / 14400) * 14400;
}

//+------------------------------------------------------------------+
//| V5: CalcEWM_ATR_Py                                               |
//|   Exact match for pandas ewm(span=N, adjust=False)               |
//|   Seed  : first bar's TR (not SMA seed)                          |
//|   Alpha : 2/(period+1)                                           |
//|   Guard : returns 0.0 if < 5*period bars available               |
//|   Debug : first 10 H4 calls print EWM vs Wilder vs Python target |
//+------------------------------------------------------------------+
double CalcEWM_ATR_Py(string symbol, ENUM_TIMEFRAMES tf, int period,
                       datetime barTime, bool logComparison = false)
{
   int totalBars   = iBars(symbol, tf);
   int targetShift = iBarShift(symbol, tf, barTime, false);

   // Warm-up guard: need 5× period bars behind target bar
   int minWarmup = period * 5;
   if(targetShift < 0 || (totalBars - 1 - targetShift) < minWarmup)
      return 0.0;

   // Fetch from oldest bar in lookback window down to target bar
   int lookback    = targetShift + minWarmup;   // oldest shift (furthest back)
   int barsToFetch = lookback + 2;              // +2 for prev-close TR computation

   if(barsToFetch > totalBars) return 0.0;

   double highs[], lows[], closes[];
   ArraySetAsSeries(highs,  true);
   ArraySetAsSeries(lows,   true);
   ArraySetAsSeries(closes, true);

   if(CopyHigh (symbol, tf, 0, barsToFetch, highs)  < barsToFetch) return 0.0;
   if(CopyLow  (symbol, tf, 0, barsToFetch, lows)   < barsToFetch) return 0.0;
   if(CopyClose(symbol, tf, 0, barsToFetch, closes)  < barsToFetch) return 0.0;

   double alpha    = 2.0 / ((double)period + 1.0);
   double oneMinA  = 1.0 - alpha;

   // Seed: first bar's TR at oldest bar in window (matches Python ewm seed)
   // ArraySetAsSeries=true means index 0=newest, index lookback=oldest
   double ewmATR = highs[lookback] - lows[lookback];

   // Walk forward from (oldest-1) to targetShift inclusive
   for(int i = lookback - 1; i >= targetShift; i--)
   {
      double trHL = highs[i]  - lows[i];
      double trHC = MathAbs(highs[i]  - closes[i + 1]);
      double trLC = MathAbs(lows[i]   - closes[i + 1]);
      double tr   = MathMax(trHL, MathMax(trHC, trLC));
      ewmATR      = alpha * tr + oneMinA * ewmATR;
   }

   // V5: Validation logging — first 10 H4 ATR calls only
   if(logComparison && tf == PERIOD_H4 && !m_ewmDebugDone && InpEnableDebugPrint)
   {
      double wilderVal = 0.0;
      if(m_handleH4ATR_Debug != INVALID_HANDLE)
      {
         double buf[1];
         if(CopyBuffer(m_handleH4ATR_Debug, 0, targetShift, 1, buf) > 0)
            wilderVal = buf[0];
      }

      PrintFormat(
         "V5_EWM_ATR[%02d]: bar_shift=%d | EWM=%.4f | Wilder=%.4f | Py_Expected=%.4f | EWM_vs_Py=%+.4f | Wilder_vs_Py=%+.4f",
         m_ewmDebugCount, targetShift,
         ewmATR, wilderVal, InpPythonExpectedATR,
         ewmATR   - InpPythonExpectedATR,
         wilderVal - InpPythonExpectedATR);

      m_ewmDebugCount++;
      if(m_ewmDebugCount >= 10)
      {
         m_ewmDebugDone = true;
         // Release Wilder debug handle — no longer needed
         if(m_handleH4ATR_Debug != INVALID_HANDLE)
         {
            IndicatorRelease(m_handleH4ATR_Debug);
            m_handleH4ATR_Debug = INVALID_HANDLE;
            Print("V5: Wilder debug handle released after 10 validation prints");
         }
      }
   }

   return ewmATR;
}

//+------------------------------------------------------------------+
//| CSV logging (unchanged from V4)                                  |
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
//| Export functions (unchanged from V4)                             |
//+------------------------------------------------------------------+
void ExportTesterTrades() {
   string fileName = "phantom_mt5_tester_export_v5.csv";
   int handle = FileOpen(fileName, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ';');
   if(handle == INVALID_HANDLE) return;

   FileWrite(handle,
             "entry_time_utc","exit_time_utc","ticket","symbol","direction","volume",
             "entry_price","exit_price","stop_price","tp_price","initial_risk","exit_reason",
             "gross_profit","commission","swap","net_profit","r_value","score",
             "confidence_mult","regime","broker_exit_reason","entry_comment",
             "session_mult","regime_mult","zone_price","zone_time_utc","exit_comment","holding_minutes");

   if(!HistorySelect(0, TimeCurrent() + 86400)) { FileClose(handle); return; }
   int dealsTotal = HistoryDealsTotal();
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
   int fileHandle = FileOpen("phantom_mt5_export_v5.csv", FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ';');
   if(fileHandle == INVALID_HANDLE) return;
   if(!HistorySelect(0, TimeCurrent() + 86400)) { FileClose(fileHandle); return; }

   FileWrite(fileHandle, "entry_time","exit_time","ticket","symbol","direction","volume",
             "entry_price","exit_price","stop_loss","take_profit","gross_profit",
             "commission","swap","net_profit","profit_percent","exit_type");

   int dealsTotal = HistoryDealsTotal();
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

   // V5: No H4ATR or M15ATR handles — replaced by CalcEWM_ATR_Py()
   // Wilder debug handle: used only for Sprint 1a validation logging
   m_handleH4ATR_Debug = iATR(Symbol(), PERIOD_H4, InpEWMATRPeriod);
   if(m_handleH4ATR_Debug == INVALID_HANDLE)
      Print("V5 WARNING: Could not create Wilder debug handle — comparison logging disabled");

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

   // V4: Auto-detect UTC offset
   if(InpAutoDetectUTC) {
      m_detectedUTCOffsetHours = (int)MathRound((double)(TimeCurrent() - TimeGMT()) / 3600.0);
      PrintFormat("V5 UTC: Auto-detected offset = %+d hours (Server: %s, GMT: %s)",
                  m_detectedUTCOffsetHours,
                  TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES),
                  TimeToString(TimeGMT(),     TIME_DATE|TIME_MINUTES));
   } else {
      m_detectedUTCOffsetHours = InpManualUTCOffset;
      PrintFormat("V5 UTC: Manual offset = %+d hours", m_detectedUTCOffsetHours);
   }

   // V4: Session diagnostic
   MqlDateTime utcNow;
   TimeToStruct(ToUTC(TimeCurrent()), utcNow);
   PrintFormat("V5 Session: Current UTC hour=%d | Session window=%d:00-%d:00 | InSession=%s",
               utcNow.hour, InpSessionStart, InpSessionEnd,
               (utcNow.hour >= InpSessionStart && utcNow.hour < InpSessionEnd) ? "YES" : "NO");

   // Symbol debug
   if(InpEnableDebugPrint) {
      PrintFormat("SymbolDebug: symbol=%s tickSize=%.8f tickValue=%.8f contractSize=%.2f lotStep=%.2f minLot=%.2f maxLot=%.2f",
                  Symbol(),
                  SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_SIZE),
                  SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_VALUE),
                  SymbolInfoDouble(Symbol(), SYMBOL_TRADE_CONTRACT_SIZE),
                  SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_STEP),
                  SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MIN),
                  SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MAX));
      PrintFormat("V5 EWM ATR: period=%d alpha=%.6f warmup=%d bars | Py expected ATR=%.4f",
                  InpEWMATRPeriod,
                  2.0 / ((double)InpEWMATRPeriod + 1.0),
                  InpEWMATRPeriod * 5,
                  InpPythonExpectedATR);
   }

   // State init
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

   Print("Phantom P2 US100 Scenario B V5 initialized — EWM ATR Sprint 1a");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
   // V5: Release debug handle if still open
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
//| Zone building (unchanged from V4)                                |
//+------------------------------------------------------------------+
void BuildH4Zones() {
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
   m_zones[size].time           = confirmedUtc;
   m_zones[size].price          = price;
   m_zones[size].direction      = direction;
   m_zones[size].source_tf      = PERIOD_H4;
   m_zones[size].origin_time_utc= confirmedUtc;
   int confirmMinutes = InpMinConfirmBars * PeriodSeconds(InpConfirmTF) / 60;
   m_zones[size].confirmed_at   = confirmedUtc + confirmMinutes * 60;
   m_zones[size].confirmed      = (ToUTC(TimeCurrent()) >= m_zones[size].confirmed_at);
   m_zoneCount++;
}

//+------------------------------------------------------------------+
//| Position management (unchanged from V4)                          |
//+------------------------------------------------------------------+
void ManageOpenPositions() {
   double bid = SymbolInfoDouble(Symbol(), SYMBOL_BID);
   double ask = SymbolInfoDouble(Symbol(), SYMBOL_ASK);
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

         bool   exitNow       = false;
         double exitSignalPx  = 0.0;
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
   int dealsTotal = HistoryDealsTotal();
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
//| Entry conditions                                                  |
//| V5 change: GetATRAtTime() replaced by CalcEWM_ATR_Py()          |
//+------------------------------------------------------------------+
void CheckEntryConditions() {
   datetime barTime = iTime(Symbol(), PERIOD_M5, 1);
   if(!CanTrade(barTime)) return;
   datetime barTimeUtc  = ToUTC(barTime);
   double   signalPrice = iClose(Symbol(), PERIOD_M5, 1);

   // V5: EWM ATR — logComparison=true for H4 (validation prints), false for M15
   double h4ATR  = CalcEWM_ATR_Py(Symbol(), PERIOD_H4,  InpEWMATRPeriod, barTime, true);
   double m15ATR = CalcEWM_ATR_Py(Symbol(), PERIOD_M15, InpEWMATRPeriod, barTime, false);
   if(h4ATR <= 0) return;

   // ═══════════════════════════════════════════════════════════════════
   // V5-DIAG: Indicator diagnostic — Dec 1-5, 2025 (UTC session hours)
   // Prints one DIAG| line per M5 bar during session to match Python output
   // ═══════════════════════════════════════════════════════════════════
   static datetime diagStart   = D'2025.12.01 00:00';
   static datetime diagEnd     = D'2025.12.06 00:00';
   static bool     diagDone    = false;
   static datetime diagLastBar = 0;

   if(!diagDone && barTime >= diagStart && barTime < diagEnd && barTime != diagLastBar)
   {
      MqlDateTime dtUtc;
      TimeToStruct(barTimeUtc, dtUtc);

      if(dtUtc.hour >= InpSessionStart && dtUtc.hour < InpSessionEnd)
      {
         // M5 indicators
         double m5ema20[1], m5ema50[1], m5rsi[1];
         int m5shift = iBarShift(Symbol(), PERIOD_M5, barTime, false);
         bool m5ok = (CopyBuffer(m_handleM5EMA20, 0, m5shift, 1, m5ema20) > 0 &&
                      CopyBuffer(m_handleM5EMA50, 0, m5shift, 1, m5ema50) > 0 &&
                      CopyBuffer(m_handleM5RSI,   0, m5shift, 1, m5rsi)   > 0);

         // H4 indicators
         double h4ema20[1], h4ema50[1], h4rsi[1];
         int h4shift = iBarShift(Symbol(), PERIOD_H4, barTime, false);
         bool h4ok = (CopyBuffer(m_handleH4EMA20, 0, h4shift, 1, h4ema20) > 0 &&
                      CopyBuffer(m_handleH4EMA50, 0, h4shift, 1, h4ema50) > 0 &&
                      CopyBuffer(m_handleH4RSI,   0, h4shift, 1, h4rsi)   > 0);

         // Active zone count in lookback window
         int activeZones = 0;
         datetime windowStart = barTimeUtc - (InpZoneLookback * PeriodSeconds(PERIOD_H4));
         for(int z = 0; z < m_zoneCount; z++)
            if(m_zones[z].time >= windowStart && m_zones[z].time < barTimeUtc)
               activeZones++;

         if(m5ok && h4ok)
            PrintFormat("DIAG|%s|M5|C=%.2f|E20=%.2f|E50=%.2f|RSI=%.2f|H4|E20=%.2f|E50=%.2f|RSI=%.2f|ATR=%.4f|M15ATR=%.4f|Zones=%d",
                        TimeToString(barTime, TIME_DATE|TIME_MINUTES),
                        signalPrice,
                        m5ema20[0], m5ema50[0], m5rsi[0],
                        h4ema20[0], h4ema50[0], h4rsi[0],
                        h4ATR, m15ATR, activeZones);
      }

      diagLastBar = barTime;
      if(barTime >= diagEnd)
      {
         diagDone = true;
         Print("DIAG: Indicator diagnostic complete for Dec 1-5 2025");
      }
   }
   // ═══════════════════════════════════════════════════════════════════

   double   sessionMultForBar = GetSessionMultiplier(barTimeUtc);
   datetime windowStartUtc    = barTimeUtc - (InpZoneLookback * PeriodSeconds(PERIOD_H4));

   for(int i = 0; i < m_zoneCount; i++) {
      if(m_zones[i].time < windowStartUtc || m_zones[i].time >= barTimeUtc) continue;
      if(!m_zones[i].confirmed && barTimeUtc < m_zones[i].confirmed_at) continue;
      if(MathAbs(signalPrice - m_zones[i].price) / m_zones[i].price > InpZoneTolerance) continue;
      if(m15ATR > 0 && MathAbs(signalPrice - m_zones[i].price) > InpChaseFilterATR * m15ATR) continue;
      if(m_zones[i].direction ==  1 && signalPrice < m_zones[i].price * (1 - InpZoneTolerance)) continue;
      if(m_zones[i].direction == -1 && signalPrice > m_zones[i].price * (1 + InpZoneTolerance)) continue;
      if(sessionMultForBar <= 0 || !CheckClusterCap(barTimeUtc)) continue;

      string regime     = GetDailyRegime(barTime);
      double regimeMult = GetRegimeMultiplier(regime, m_zones[i].direction);
      int    h4Score    = GetTFScoreAtTime(PERIOD_H4, m_zones[i].direction, barTime);
      int    h1Score    = GetTFScoreAtTime(PERIOD_H1, m_zones[i].direction, barTime);
      int    ltfScore   = GetTFScoreAtTime(PERIOD_M5, m_zones[i].direction, barTime);
      if(h4Score < InpH4ScoreMin || h1Score < InpH1ScoreMin || ltfScore < InpLTFScoreMin) continue;
      int totalScore        = h4Score + h1Score + ltfScore;
      int effectiveScoreMin = InpScoreMin + ((m_zones[i].direction == 1) ? InpLongScoreOffset : 0);
      if(totalScore < effectiveScoreMin || ltfScore > InpLTFScoreCap) continue;
      double confMult = CalculateConfidenceMultiplier(barTimeUtc);

      ExecuteEntry(m_zones[i], h4ATR, sessionMultForBar, regimeMult, confMult, totalScore, barTime, barTimeUtc, signalPrice);
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
   switch(tf) {
      case PERIOD_H4: handleEMA20 = m_handleH4EMA20; handleEMA50 = m_handleH4EMA50; handleRSI = m_handleH4RSI; break;
      case PERIOD_H1: handleEMA20 = m_handleH1EMA20; handleEMA50 = m_handleH1EMA50; handleRSI = m_handleH1RSI; break;
      default:        handleEMA20 = m_handleM5EMA20; handleEMA50 = m_handleM5EMA50; handleRSI = m_handleM5RSI; break;
   }
   double close[1], ema20[1], ema50[1], rsi[1];
   int shift = SafeBarShift(Symbol(), tf, barTime);
   if(shift < 0) return 0;
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
//| Execute entry (unchanged from V4)                                |
//+------------------------------------------------------------------+
void ExecuteEntry(SZone &zone, double h4ATR, double sessionMult,
                  double regimeMult, double confMult, int totalScore,
                  datetime barTime, datetime barTimeUtc, double signalPrice) {
   double entryPrice = ApplyExecutionAdjustment(signalPrice, zone.direction, true);
   ENUM_ORDER_TYPE orderType  = (zone.direction == 1) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double stopDistance = InpATRStopMult * h4ATR;
   double stopPrice    = (zone.direction ==  1) ? signalPrice - stopDistance : signalPrice + stopDistance;
   double takeProfit   = (zone.direction ==  1) ? entryPrice  + (InpTPMult * stopDistance)
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

   string comment = StringFormat("P2_B|%s|S=%d|ATR=%.5f|REG=%s|CONF=%.1f",
                                 (zone.direction == 1) ? "LONG" : "SHORT",
                                 totalScore, h4ATR, GetDailyRegime(barTime), confMult);

   if(InpEnableDebugPrint)
      PrintFormat("V5 Entry: dir=%s price=%.4f stop=%.4f tp=%.4f vol=%.2f ATR=%.4f stopDist=%.4f riskAmt=%.2f riskPerLot=%.4f",
                  (zone.direction==1)?"LONG":"SHORT",
                  entryPrice, stopPrice, takeProfit, volume,
                  h4ATR, stopDistance, riskAmount, riskPerLot);

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
      m_pos_meta[metaIndex].direction       = zone.direction;
      m_pos_meta[metaIndex].total_score     = totalScore;
      m_pos_meta[metaIndex].confidence_mult = confMult;
      m_pos_meta[metaIndex].session_mult    = sessionMult;
      m_pos_meta[metaIndex].regime_mult     = regimeMult;
      m_pos_meta[metaIndex].regime          = GetDailyRegime(barTime);
      m_pos_meta[metaIndex].zone_time_utc   = zone.time;
      m_pos_meta[metaIndex].zone_price      = zone.price;
      m_pos_meta[metaIndex].logged          = false;
      RegisterEntryTime(barTimeUtc);
      m_lastEntryTime = barTime;
   }
}

//+------------------------------------------------------------------+
//| Helpers (unchanged from V4 — GetATRAtTime removed)              |
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
//| Draw zones, event handlers, FTMO helpers, OnTester              |
//+------------------------------------------------------------------+
void DrawZones() {
   if(!InpEnableVisuals) return;
   ObjectsDeleteAll(0, "Zone_");
   datetime nowUtc = ToUTC(TimeCurrent());
   for(int i = 0; i < m_zoneCount; i++) {
      if(m_zones[i].time < nowUtc - (InpZoneLookback * PeriodSeconds(PERIOD_H4))) continue;
      string n   = StringFormat("Zone_%d", i);
      color  clr = (m_zones[i].direction == 1) ? m_demandColor : m_supplyColor;
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