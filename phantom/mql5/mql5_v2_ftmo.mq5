//+------------------------------------------------------------------+
//|                                          Phantom_P2_US100_B.mq5  |
//|                                    Multi-Timeframe Zone Strategy  |
//|                                             US100 Scenario B      |
//+------------------------------------------------------------------+
#property copyright "Phantom P2 MT5"
#property version   "2.00"
#property description "Multi-Timeframe Zone-Based Strategy for US100"
#property description "Scenario B - FTMO Guardrailed Profile"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//+------------------------------------------------------------------+
//| Input Parameters                                                  |
//+------------------------------------------------------------------+
// --- Zone Detection ---
input int      InpPivotBars = 2;                    // Pivot bars for zone detection
input int      InpZoneLookback = 50;                 // H4 bars lookback for zones
input double   InpZoneTolerance = 0.002;             // Zone proximity (0.20%)
input double   InpChaseFilterATR = 1.5;              // Max distance from zone (M15 ATR multiplier)

// --- Session Filter ---
input int      InpSessionStart = 13;                 // Session start (UTC hour)
input int      InpSessionEnd = 21;                   // Session end (UTC hour)
input bool     InpPeakSessionBoost = true;           // CRITICAL: Peak-hour boost for profitability!

// --- Confirmation ---
input int      InpMinConfirmBars = 1;                // Min H1 bars before zone active
input ENUM_TIMEFRAMES InpConfirmTF = PERIOD_H1;      // Confirmation timeframe

// --- Scoring ---
input int      InpScoreMin = 3;                      // Minimum total score
input int      InpH4ScoreMin = 1;                    // Minimum H4 score
input int      InpH1ScoreMin = 1;                    // Minimum H1 score
input int      InpLTFScoreMin = 1;                   // Minimum LTF (M5) score
input int      InpLTFScoreCap = 3;                   // Maximum LTF score
input int      InpLongScoreOffset = 1;               // Additional score required for longs

// --- Risk Management ---
input double   InpRiskPercent = 0.7;                 // Risk per trade (% of capital) - matches Python "high"
input double   InpRiskMultiplier = 2.0;              // Aggressive sizing multiplier (CRITICAL: makes strategy profitable!)
input double   InpATRStopMult = 1.5;                 // Stop loss (H4 ATR multiplier)
input double   InpTPMult = 1.3;                      // Take profit (R multiple)
input double   InpTrailATRMult = 0.8;                // Trailing stop (H4 ATR multiplier)
input double   InpBreakevenR = 0.8;                  // Move stop to BE at this R
input int      InpMaxConcurrent = 3;                 // Max positions per 4H window (matches Python "high")
input int      InpCooldownMin = 20;                  // Cooldown between entries (minutes)
input bool     InpEnableDebugLogs = true;            // Enable verbose debug Print() logs
input int      InpLockoutMin = 60;                   // Lockout after loss (minutes)
input int      InpCircuitBreakerLosses = 5;          // Consecutive losses to trigger pause
input int      InpCircuitBreakerHours = 24;          // Pause duration (hours)

// --- FTMO Guardrails ---
input bool     InpEnableFTMOGuardrails = false;      // Enforce FTMO-style account limits
input double   InpFTMOAccountSize = 70000.0;         // Challenge account size
input double   InpFTMOProfitTargetPct = 5.0;         // Profit target (% of account size)
input double   InpFTMOMaxLossPct = 10.0;             // Max overall loss (% of account size)
input double   InpFTMOMaxDailyLossPct = 5.0;         // Max daily loss (% of account size)
input int      InpFTMOTradingPeriodDays = 0;         // Challenge window (days, 0 disables)
input int      InpFTMOMinTradingDays = 2;            // Minimum active trading days
input double   InpFTMOMaxLeverage = 30.0;            // Max notional leverage

// --- Position Sizing ---
input double   InpConfidenceMult = 1.5;              // Size multiplier for high confidence
input double   InpSessionSoftMult = 0.5;             // Size multiplier for soft session
input double   InpCounterTrendMult = 0.5;            // Size multiplier for counter-trend trades

// --- Execution ---
input double   InpSpreadBPS = 1.0;                   // Spread adjustment (basis points)
input double   InpSlippageBPS = 1.0;                 // Slippage adjustment (basis points)
input ulong     InpMagicNumber = 202406;              // EA Magic Number
input string   InpComment = "Phantom P2 US100 B";    // Order comment

// --- Time handling ---
input int      InpBrokerUTCOffset = -5;              // Broker time = UTC + offset (US100 = EST = UTC-5)
input bool     InpAutoUTCOffset = true;              // Auto-switch between winter/summer offsets
input int      InpWinterUTCOffset = -5;              // Winter offset (EST, Nov-Mar)
input int      InpSummerUTCOffset = -4;              // Summer offset (EDT, Mar-Nov)

// --- Development ---
input bool     InpEnableDebugPrint = true;           // Enable debug output
input bool     InpEnableVisuals = true;               // Draw zones on chart
input bool     InpShowOnlyActiveZones = true;         // Hide old/inactive zones from the chart
input bool     InpShowZoneOrigins = true;             // Show each zone's origin point and label
input bool     InpShowInactiveZoneMarkers = true;     // Mark zones after they fall out of the active state
input bool     InpShowZoneTimeframe = true;           // Include detected timeframe in labels

//+------------------------------------------------------------------+
//| Global Variables                                                  |
//+------------------------------------------------------------------+
CTrade         m_trade;
CPositionInfo  m_position;
CAccountInfo   m_account;
CSymbolInfo    m_symbol;

// Timeframe handles
int            m_handleM5, m_handleM15, m_handleH1, m_handleH4, m_handleDaily;
// Indicator handles
int            m_handleH4ATR, m_handleH4EMA20, m_handleH4EMA50, m_handleH4RSI;
int            m_handleH1EMA20, m_handleH1EMA50, m_handleH1RSI;
int            m_handleM15ATR;
int            m_handleM5EMA20, m_handleM5EMA50, m_handleM5RSI, m_handleM5Volume;
int            m_handleDailyEMA50, m_handleDailyEMA200;

// Zone arrays
struct SZone {
   datetime    time;          // Zone timestamp (UTC)
   double      price;         // Zone price level
   int         direction;     // 1 = demand (long), -1 = supply (short)
   ENUM_TIMEFRAMES source_tf; // Timeframe used to detect this zone
   datetime    origin_time_utc; // Origin timestamp used for chart labels
   bool        confirmed;     // Confirmation delay passed
   datetime    confirmed_at;  // When zone becomes active (UTC)
};
SZone         m_zones[];
int           m_zoneCount;
int           m_zoneStartIndex;  // For rolling window

struct SPositionMeta {
   ulong      ticket;
   datetime   entry_time;     // Entry bar time (server time)
   datetime   entry_time_utc; // Entry bar time (UTC)
   string     entry_comment;
   double     entry_price;
   double     stop_price;
   double     tp_price;
   double     initial_risk;
   double     atr_entry;      // H4 ATR at entry
   bool       be_triggered;
   int        direction;      // 1 = long, -1 = short
   int        total_score;
   double     confidence_mult;
   double     session_mult;
   double     regime_mult;
   string     regime;
   datetime   zone_time_utc;
   double     zone_price;
   bool       logged;         // Track if this position's exit has been logged
};
SPositionMeta m_pos_meta[];
ulong        m_closed_positions[]; // Track closed position IDs to avoid duplicate logging

struct STesterEntry {
   ulong      position_id;
   datetime   entry_time;
   double     entry_price;
   double     volume;
   int        direction;
   double     stop_price;
   double     tp_price;
};

datetime      m_entry_times_utc[]; // Track entry timestamps for cluster counting

// Trade tracking
struct STradeWindow {
   datetime    windowStart;
   int         tradeCount;
};
STradeWindow  m_tradeWindows[];
int           m_consecutiveLosses;
datetime      m_lastEntryTime;
datetime      m_lastLossExitTime;
datetime      m_circuitBreakerUntil;
int           m_tradeCsvHandle = INVALID_HANDLE;
string        m_tradeCsvFileName = "phantom_mql5_trade_log_v2.csv";

// FTMO state tracking
double        m_ftmoInitialEquity;
double        m_ftmoDayStartEquity;
datetime      m_ftmoTradingStartUtc;
int           m_ftmoCurrentDayKey;
int           m_ftmoTradeDayKeys[];
bool          m_ftmoHardStop;
datetime      m_ftmoLastStatusPrint;

// Zone colors
color         m_demandColor = clrDodgerBlue;
color         m_supplyColor = clrTomato;

//+------------------------------------------------------------------+
//| Compact trade CSV logging                                        |
//+------------------------------------------------------------------+
bool OpenTradeCsv() {
   if(m_tradeCsvHandle != INVALID_HANDLE) {
      FileClose(m_tradeCsvHandle);
      m_tradeCsvHandle = INVALID_HANDLE;
   }

   m_tradeCsvHandle = FileOpen(m_tradeCsvFileName, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ';');
   if(m_tradeCsvHandle == INVALID_HANDLE) {
      if(InpEnableDebugPrint) {
         PrintFormat("TradeCsv: failed to open %s (err=%d)", m_tradeCsvFileName, GetLastError());
      }
      return false;
   }

   FileWrite(m_tradeCsvHandle,
             "entry_time_utc",
             "exit_time_utc",
             "ticket",
             "symbol",
             "direction",
             "volume",
             "entry_price",
             "exit_price",
             "stop_price",
             "tp_price",
             "initial_risk",
             "exit_reason",
             "gross_profit",
             "commission",
             "swap",
             "net_profit",
             "r_value",
             "score",
             "confidence_mult",
             "regime",
             "broker_exit_reason",
             "entry_comment",
             "session_mult",
             "regime_mult",
             "zone_price",
             "zone_time_utc",
             "exit_comment");
   FileFlush(m_tradeCsvHandle);
   return true;
}

void CloseTradeCsv() {
   if(m_tradeCsvHandle != INVALID_HANDLE) {
      FileFlush(m_tradeCsvHandle);
      FileClose(m_tradeCsvHandle);
      m_tradeCsvHandle = INVALID_HANDLE;
   }
}

string TradeDirectionToString(int direction) {
   return (direction == 1) ? "long" : "short";
}

string InferExitReason(double dealPrice, double stopPrice, double tpPrice) {
   double point = SymbolInfoDouble(Symbol(), SYMBOL_POINT);
   double tolerance = MathMax(point * 2.0, point);
   if(MathAbs(dealPrice - stopPrice) <= tolerance) return "stop";
   if(MathAbs(dealPrice - tpPrice) <= tolerance) return "tp";
   return "close";
}

string DealReasonToString(long reason) {
   switch(reason) {
      case DEAL_REASON_CLIENT: return "client";
      case DEAL_REASON_MOBILE: return "mobile";
      case DEAL_REASON_WEB: return "web";
      case DEAL_REASON_EXPERT: return "expert";
      case DEAL_REASON_SL: return "sl";
      case DEAL_REASON_TP: return "tp";
      case DEAL_REASON_SO: return "stop_out";
      case DEAL_REASON_ROLLOVER: return "rollover";
      case DEAL_REASON_VMARGIN: return "margin";
      case DEAL_REASON_SPLIT: return "split";
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
             TimeToString(entryUtc, TIME_DATE | TIME_SECONDS),
             TimeToString(exitUtc, TIME_DATE | TIME_SECONDS),
             (long)ticket,
             Symbol(),
             TradeDirectionToString(direction),
             DoubleToString(volume, 2),
             DoubleToString(entryPrice, _Digits),
             DoubleToString(exitPrice, _Digits),
             DoubleToString(stopPrice, _Digits),
             DoubleToString(tpPrice, _Digits),
             DoubleToString(initialRisk, _Digits),
             exitReason,
             DoubleToString(grossProfit, 2),
             DoubleToString(commission, 2),
             DoubleToString(swap, 2),
             DoubleToString(netProfit, 2),
             DoubleToString(rValue, 3),
             score,
             DoubleToString(confidenceMult, 2),
             regime,
             brokerExitReason,
             entryComment,
             DoubleToString(sessionMult, 2),
             DoubleToString(regimeMult, 2),
             DoubleToString(zonePrice, _Digits),
             TimeToString(zoneTimeUtc, TIME_DATE | TIME_SECONDS),
             exitComment);
   FileFlush(m_tradeCsvHandle);
}

//+------------------------------------------------------------------+
//| Export tester trades to CSV                                      |
//+------------------------------------------------------------------+
void ExportTesterTrades() {
   string fileName = "phantom_mt5_tester_export_v2.csv";
   int handle = FileOpen(fileName, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ';');
   if(handle == INVALID_HANDLE) {
      if(InpEnableDebugPrint) {
         PrintFormat("TesterExport: failed to open %s (err=%d)", fileName, GetLastError());
      }
      return;
   }

   FileWrite(handle,
             "entry_time_utc",
             "exit_time_utc",
             "ticket",
             "symbol",
             "direction",
             "volume",
             "entry_price",
             "exit_price",
             "stop_price",
             "tp_price",
             "initial_risk",
             "exit_reason",
             "gross_profit",
             "commission",
             "swap",
             "net_profit",
             "r_value",
             "score",
             "confidence_mult",
             "regime",
             "broker_exit_reason",
             "entry_comment",
             "session_mult",
             "regime_mult",
             "zone_price",
             "zone_time_utc",
             "exit_comment",
             "holding_minutes");

   if(!HistorySelect(0, TimeCurrent() + 86400)) {
      if(InpEnableDebugPrint) {
         PrintFormat("TesterExport: HistorySelect failed (err=%d)", GetLastError());
      }
      FileClose(handle);
      return;
   }

   int dealsTotal = HistoryDealsTotal();
   int rowsWritten = 0;

   for(int i = 0; i < dealsTotal; i++) {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;

      long dealMagic = HistoryDealGetInteger(deal, DEAL_MAGIC);
      if(dealMagic != InpMagicNumber) continue;

      long dealEntry = HistoryDealGetInteger(deal, DEAL_ENTRY);
      if(dealEntry != DEAL_ENTRY_OUT && dealEntry != DEAL_ENTRY_OUT_BY && dealEntry != DEAL_ENTRY_INOUT) {
         continue;
      }

      ulong positionId = (ulong)HistoryDealGetInteger(deal, DEAL_POSITION_ID);
      datetime exitTime = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
      double exitPrice = HistoryDealGetDouble(deal, DEAL_PRICE);
      double exitProfit = HistoryDealGetDouble(deal, DEAL_PROFIT);
      double exitCommission = HistoryDealGetDouble(deal, DEAL_COMMISSION);
      double exitSwap = HistoryDealGetDouble(deal, DEAL_SWAP);
      double exitVolume = HistoryDealGetDouble(deal, DEAL_VOLUME);
      string exitComment = HistoryDealGetString(deal, DEAL_COMMENT);
      long dealReason = HistoryDealGetInteger(deal, DEAL_REASON);

      datetime entryTime = 0;
      double entryPrice = 0.0;
      int direction = 0;

      for(int j = 0; j < dealsTotal; j++) {
         ulong entryDeal = HistoryDealGetTicket(j);
         if(entryDeal == 0) continue;

         if((ulong)HistoryDealGetInteger(entryDeal, DEAL_POSITION_ID) != positionId) continue;
         if(HistoryDealGetInteger(entryDeal, DEAL_MAGIC) != InpMagicNumber) continue;
         if(HistoryDealGetInteger(entryDeal, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;

         entryTime = (datetime)HistoryDealGetInteger(entryDeal, DEAL_TIME);
         entryPrice = HistoryDealGetDouble(entryDeal, DEAL_PRICE);
         long entryType = HistoryDealGetInteger(entryDeal, DEAL_TYPE);
         direction = (entryType == DEAL_TYPE_BUY) ? 1 : -1;
         break;
      }

      if(entryTime == 0) continue;

      double stopPrice = 0.0;
      double tpPrice = 0.0;
      int score = 0;
      double confidenceMult = 1.0;
      string regime = "unknown";
      string entryComment = "";
      double sessionMult = 1.0;
      double regimeMult = 1.0;
      double zonePrice = 0.0;
      datetime zoneTimeUtc = 0;

      int metaIndex = FindPositionMeta(positionId);
      if(metaIndex >= 0) {
         stopPrice = m_pos_meta[metaIndex].stop_price;
         tpPrice = m_pos_meta[metaIndex].tp_price;
         score = m_pos_meta[metaIndex].total_score;
         confidenceMult = m_pos_meta[metaIndex].confidence_mult;
         regime = m_pos_meta[metaIndex].regime;
         entryComment = m_pos_meta[metaIndex].entry_comment;
         sessionMult = m_pos_meta[metaIndex].session_mult;
         regimeMult = m_pos_meta[metaIndex].regime_mult;
         zonePrice = m_pos_meta[metaIndex].zone_price;
         zoneTimeUtc = m_pos_meta[metaIndex].zone_time_utc;
      }

      double initialRisk = MathAbs(entryPrice - stopPrice);
      double netProfit = exitProfit + exitCommission + exitSwap;
      double rValue = 0.0;
      if(initialRisk > 0.0) {
         rValue = (direction == 1) ? (exitPrice - entryPrice) / initialRisk
                                   : (entryPrice - exitPrice) / initialRisk;
      }

      double point = SymbolInfoDouble(Symbol(), SYMBOL_POINT);
      double tolerance = MathMax(point * 5.0, point);
      string exitReason = "close";
      if(stopPrice > 0.0 && MathAbs(exitPrice - stopPrice) <= tolerance) {
         exitReason = "stop";
      } else if(tpPrice > 0.0 && MathAbs(exitPrice - tpPrice) <= tolerance) {
         exitReason = "tp";
      }

      double holdingMinutes = (double)(exitTime - entryTime) / 60.0;

      FileWrite(handle,
                TimeToString(entryTime, TIME_DATE | TIME_SECONDS),
                TimeToString(exitTime, TIME_DATE | TIME_SECONDS),
                (long)positionId,
                Symbol(),
                TradeDirectionToString(direction),
                DoubleToString(exitVolume, 2),
                DoubleToString(entryPrice, _Digits),
                DoubleToString(exitPrice, _Digits),
                DoubleToString(stopPrice, _Digits),
                DoubleToString(tpPrice, _Digits),
                DoubleToString(initialRisk, _Digits),
                exitReason,
                DoubleToString(exitProfit, 2),
                DoubleToString(exitCommission, 2),
                DoubleToString(exitSwap, 2),
                DoubleToString(netProfit, 2),
                DoubleToString(rValue, 3),
                score,
                DoubleToString(confidenceMult, 2),
                regime,
                DealReasonToString(dealReason),
                entryComment,
                DoubleToString(sessionMult, 2),
                DoubleToString(regimeMult, 2),
                DoubleToString(zonePrice, _Digits),
                TimeToString(zoneTimeUtc, TIME_DATE | TIME_SECONDS),
                exitComment,
                DoubleToString(holdingMinutes, 1));
      rowsWritten++;
   }

   FileClose(handle);
   if(InpEnableDebugPrint) {
      PrintFormat("TesterExport: wrote %d trades to %s", rowsWritten, fileName);
   }
}

//+------------------------------------------------------------------+
//| Export all deals from history to CSV (for backtest data analysis)|
//+------------------------------------------------------------------+
void ExportAllDealsToCSV() {
   // Open CSV file for export
   int fileHandle = FileOpen("phantom_mt5_export_v2.csv", FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ';');
   if(fileHandle == INVALID_HANDLE) {
      if(InpEnableDebugPrint) {
         PrintFormat("ExportAllDeals: failed to open export file (err=%d)", GetLastError());
      }
      return;
   }

   // Select history for the entire backtest period
   if(!HistorySelect(0, TimeCurrent() + 86400)) {
      if(InpEnableDebugPrint) {
         PrintFormat("ExportAllDeals: HistorySelect failed (err=%d)", GetLastError());
      }
      FileClose(fileHandle);
      return;
   }

   // Write header
   FileWrite(fileHandle,
             "entry_time", "exit_time", "ticket", "symbol", "direction", "volume",
             "entry_price", "exit_price", "stop_loss", "take_profit", "gross_profit",
             "commission", "swap", "net_profit", "profit_percent", "exit_type");
   
   // Iterate through all deals in history
   int dealsTotal = HistoryDealsTotal();
   int rowsWritten = 0;
   
   if(InpEnableDebugPrint) {
      PrintFormat("ExportAllDeals: Starting export. Total deals in history: %d", dealsTotal);
   }
   
   for(int i = 0; i < dealsTotal; i++) {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;
      
      // Filter by magic number
      long dealMagic = HistoryDealGetInteger(deal, DEAL_MAGIC);
      if(dealMagic != InpMagicNumber) {
         if(i < 5 && InpEnableDebugPrint) {
            PrintFormat("ExportAllDeals: Deal %d - Magic mismatch: got %d, want %d", i, dealMagic, InpMagicNumber);
         }
         continue;
      }
      
      // Only log exit deals
      long dealEntry = HistoryDealGetInteger(deal, DEAL_ENTRY);
      if(dealEntry != DEAL_ENTRY_OUT && dealEntry != DEAL_ENTRY_OUT_BY && dealEntry != DEAL_ENTRY_INOUT) {
         if(InpEnableDebugPrint) {
            PrintFormat("ExportAllDeals: Deal %d - Not an exit deal (dealEntry=%d)", i, dealEntry);
         }
         continue;
      }
      
      // Get exit deal info
      datetime exitTime = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
      double exitPrice = HistoryDealGetDouble(deal, DEAL_PRICE);
      double exitVolume = HistoryDealGetDouble(deal, DEAL_VOLUME);
      double exitProfit = HistoryDealGetDouble(deal, DEAL_PROFIT);
      double exitCommission = HistoryDealGetDouble(deal, DEAL_COMMISSION);
      double exitSwap = HistoryDealGetDouble(deal, DEAL_SWAP);
      long dealType = HistoryDealGetInteger(deal, DEAL_TYPE);
      ulong positionId = HistoryDealGetInteger(deal, DEAL_POSITION_ID);
      
      // Find corresponding entry deal
      datetime entryTime = 0;
      double entryPrice = 0;
      int direction = 0;
      double stopPrice = 0;
      double tpPrice = 0;
      
      for(int j = 0; j < dealsTotal; j++) {
         ulong entryDeal = HistoryDealGetTicket(j);
         if(entryDeal == 0) continue;
         
         long entryMagic = HistoryDealGetInteger(entryDeal, DEAL_MAGIC);
         if(entryMagic != InpMagicNumber) continue;
         
         long entryType = HistoryDealGetInteger(entryDeal, DEAL_ENTRY);
         ulong entryPosId = HistoryDealGetInteger(entryDeal, DEAL_POSITION_ID);
         
         if(entryType == DEAL_ENTRY_IN && entryPosId == positionId) {
            entryTime = (datetime)HistoryDealGetInteger(entryDeal, DEAL_TIME);
            entryPrice = HistoryDealGetDouble(entryDeal, DEAL_PRICE);
            long entryDealType = HistoryDealGetInteger(entryDeal, DEAL_TYPE);
            direction = (entryDealType == DEAL_TYPE_BUY) ? 1 : -1;
            break;
         }
      }
      
      if(entryTime == 0) continue; // Entry not found, skip
      
      // Look up position info from metadata if available
      int metaIndex = FindPositionMeta(positionId);
      if(metaIndex >= 0) {
         stopPrice = m_pos_meta[metaIndex].stop_price;
         tpPrice = m_pos_meta[metaIndex].tp_price;
      }
      
      // Write trade row
      string exitType = (exitPrice <= stopPrice + SymbolInfoDouble(Symbol(), SYMBOL_POINT)) ? "sl" : "tp";
      double netProfit = exitProfit + exitCommission + exitSwap;
      double profitPercent = (entryPrice > 0) ? ((exitPrice - entryPrice) / entryPrice * 100) : 0;
      
      FileWrite(fileHandle,
                TimeToString(entryTime, TIME_DATE | TIME_SECONDS),
                TimeToString(exitTime, TIME_DATE | TIME_SECONDS),
                (long)positionId,
                Symbol(),
                (direction == 1) ? "long" : "short",
                DoubleToString(exitVolume, 2),
                DoubleToString(entryPrice, _Digits),
                DoubleToString(exitPrice, _Digits),
                DoubleToString(stopPrice, _Digits),
                DoubleToString(tpPrice, _Digits),
                DoubleToString(exitProfit, 2),
                DoubleToString(exitCommission, 2),
                DoubleToString(exitSwap, 2),
                DoubleToString(netProfit, 2),
                DoubleToString(profitPercent, 2),
                exitType);
      rowsWritten++;
   }
   
   FileClose(fileHandle);
   if(InpEnableDebugPrint) {
      PrintFormat("ExportAllDeals: exported %d trades to phantom_mt5_export_v2.csv", rowsWritten);
   }
}

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit() {
   // Initialize trade object
   m_trade.SetExpertMagicNumber(InpMagicNumber);
   m_trade.SetDeviationInPoints(30);
   
   // Set symbol
   m_symbol.Name(Symbol());
   m_symbol.Refresh();
   
   // Create indicator handles
   m_handleH4ATR = iATR(Symbol(), PERIOD_H4, 14);
   m_handleH4EMA20 = iMA(Symbol(), PERIOD_H4, 20, 0, MODE_EMA, PRICE_CLOSE);
   m_handleH4EMA50 = iMA(Symbol(), PERIOD_H4, 50, 0, MODE_EMA, PRICE_CLOSE);
   m_handleH4RSI = iRSI(Symbol(), PERIOD_H4, 14, PRICE_CLOSE);
   
   m_handleH1EMA20 = iMA(Symbol(), PERIOD_H1, 20, 0, MODE_EMA, PRICE_CLOSE);
   m_handleH1EMA50 = iMA(Symbol(), PERIOD_H1, 50, 0, MODE_EMA, PRICE_CLOSE);
   m_handleH1RSI = iRSI(Symbol(), PERIOD_H1, 14, PRICE_CLOSE);
   
   m_handleM15ATR = iATR(Symbol(), PERIOD_M15, 14);
   
   m_handleM5EMA20 = iMA(Symbol(), PERIOD_M5, 20, 0, MODE_EMA, PRICE_CLOSE);
   m_handleM5EMA50 = iMA(Symbol(), PERIOD_M5, 50, 0, MODE_EMA, PRICE_CLOSE);
   m_handleM5RSI = iRSI(Symbol(), PERIOD_M5, 14, PRICE_CLOSE);
   m_handleM5Volume = iVolumes(Symbol(), PERIOD_M5, VOLUME_TICK);
   
   m_handleDailyEMA50 = iMA(Symbol(), PERIOD_D1, 50, 0, MODE_EMA, PRICE_CLOSE);
   m_handleDailyEMA200 = iMA(Symbol(), PERIOD_D1, 200, 0, MODE_EMA, PRICE_CLOSE);
   
   // Verify handles
   if(m_handleH4ATR == INVALID_HANDLE || m_handleH4EMA20 == INVALID_HANDLE ||
      m_handleH4EMA50 == INVALID_HANDLE || m_handleH4RSI == INVALID_HANDLE ||
      m_handleH1EMA20 == INVALID_HANDLE || m_handleH1EMA50 == INVALID_HANDLE ||
      m_handleH1RSI == INVALID_HANDLE || m_handleM15ATR == INVALID_HANDLE ||
      m_handleM5EMA20 == INVALID_HANDLE || m_handleM5EMA50 == INVALID_HANDLE ||
      m_handleM5RSI == INVALID_HANDLE || m_handleM5Volume == INVALID_HANDLE ||
      m_handleDailyEMA50 == INVALID_HANDLE || m_handleDailyEMA200 == INVALID_HANDLE) {
      Print("Failed to create one or more indicator handles");
      return INIT_FAILED;
   }
   
   // Initialize tracking variables
   m_zoneCount = 0;
   m_consecutiveLosses = 0;
   m_lastEntryTime = 0;
   m_lastLossExitTime = 0;
   m_circuitBreakerUntil = 0;
   m_ftmoInitialEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   m_ftmoDayStartEquity = m_ftmoInitialEquity;
   m_ftmoTradingStartUtc = ToUTC(TimeCurrent());
   m_ftmoCurrentDayKey = 0;
   m_ftmoHardStop = false;
   m_ftmoLastStatusPrint = 0;
   ArrayResize(m_pos_meta, 0);
   ArrayResize(m_entry_times_utc, 0);
   ArrayResize(m_ftmoTradeDayKeys, 0);
   ArrayResize(m_closed_positions, 0);

   if(!OpenTradeCsv()) {
      Print("Warning: trade CSV logging disabled for this run");
   } else if(InpEnableDebugPrint) {
      PrintFormat("TradeCsv: writing compact trade log to %s", m_tradeCsvFileName);
   }

   if(InpEnableDebugPrint) {
      double tickSize = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_SIZE);
      double tickValue = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_VALUE);
      double contractSize = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_CONTRACT_SIZE);
      PrintFormat("SymbolDebug: symbol=%s tickSize=%.8f tickValue=%.8f contractSize=%.2f point=%.8f digits=%d lotStep=%.2f minLot=%.2f maxLot=%.2f",
                  Symbol(),
                  tickSize,
                  tickValue,
                  contractSize,
                  SymbolInfoDouble(Symbol(), SYMBOL_POINT),
                  _Digits,
                  SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_STEP),
                  SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MIN),
                  SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MAX));
      PrintFormat("TimezoneDebug: autoUTC=%s brokerOffset=%d winterOffset=%d summerOffset=%d session=%d-%d",
                  InpAutoUTCOffset ? "true" : "false",
                  InpBrokerUTCOffset,
                  InpWinterUTCOffset,
                  InpSummerUTCOffset,
                  InpSessionStart,
                  InpSessionEnd);
   }
   
   // Build initial zones
   BuildH4Zones();
   
   // Set timer for periodic zone refresh
   EventSetTimer(300); // Refresh zones every 5 minutes
   
   Print("Phantom P2 US100 Scenario B FTMO initialized successfully");
   Print("Symbol: ", Symbol(), " | Risk: ", InpRiskPercent, "% | ATR Stop: ", InpATRStopMult, "x");
   if(InpEnableFTMOGuardrails) {
      Print("FTMO Guardrails ON | Account=", InpFTMOAccountSize,
            " | DailyLoss=", InpFTMOMaxDailyLossPct, "% | MaxLoss=", InpFTMOMaxLossPct,
            "% | ProfitTarget=", InpFTMOProfitTargetPct, "%");
   }
   
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
   // Release indicator handles
   IndicatorRelease(m_handleH4ATR);
   IndicatorRelease(m_handleH4EMA20);
   IndicatorRelease(m_handleH4EMA50);
   IndicatorRelease(m_handleH4RSI);
   IndicatorRelease(m_handleH1EMA20);
   IndicatorRelease(m_handleH1EMA50);
   IndicatorRelease(m_handleH1RSI);
   IndicatorRelease(m_handleM15ATR);
   IndicatorRelease(m_handleM5EMA20);
   IndicatorRelease(m_handleM5EMA50);
   IndicatorRelease(m_handleM5RSI);
   IndicatorRelease(m_handleM5Volume);
   IndicatorRelease(m_handleDailyEMA50);
   IndicatorRelease(m_handleDailyEMA200);
   
   // Remove chart objects
   if(InpEnableVisuals) {
      ObjectsDeleteAll(0, "Zone_");
   }

   // Export all trades from MT5 history to CSV (backtest data export)
   ExportAllDealsToCSV();
   
   CloseTradeCsv();
   
   EventKillTimer();
   Comment("");
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick() {
   // Check if new bar on M5
   static datetime lastBarM5 = 0;
   datetime currentBarM5 = iTime(Symbol(), PERIOD_M5, 0);
   
   if(currentBarM5 == lastBarM5) return; // Only process on new M5 bar
   lastBarM5 = currentBarM5;
   
   // Debug: Log every bar processed
   if(InpEnableDebugPrint) {
      Print("OnTick: M5 bar processed " + TimeToString(currentBarM5, TIME_DATE|TIME_SECONDS));
   }
   
   // Refresh zones periodically
   static datetime lastZoneRefresh = 0;
   if(TimeCurrent() - lastZoneRefresh > 300) { // Every 5 minutes
      BuildH4Zones();
      lastZoneRefresh = TimeCurrent();
   }
   
   // Check for exits first
   ManageOpenPositions();
   
   // Log any closed trades from history (fallback for backtesting reliability)
   LogClosedTradesFromHistory();
   
   // Check for entry conditions
   CheckEntryConditions();
}

//+------------------------------------------------------------------+
//| Timer function for periodic tasks                                 |
//+------------------------------------------------------------------+
void OnTimer() {
   BuildH4Zones();
   if(InpEnableVisuals) DrawZones();
}

//+------------------------------------------------------------------+
//| Build H4 pivot zones                                             |
//+------------------------------------------------------------------+
void BuildH4Zones() {
   // Clear existing zones
   ArrayResize(m_zones, 0);
   m_zoneCount = 0;
   
   // Get all available H4 data so zone availability matches the Python model.
   int bars = iBars(Symbol(), PERIOD_H4);
   double highs[], lows[];
   datetime times[];

   if(bars <= (InpPivotBars * 2)) {
      if(InpEnableDebugPrint) {
         PrintFormat("Zones refreshed: insufficient H4 bars (%d) for pivot detection", bars);
      }
      return;
   }
   
   ArraySetAsSeries(highs, false);
   ArraySetAsSeries(lows, false);
   ArraySetAsSeries(times, false);
   
   CopyHigh(Symbol(), PERIOD_H4, 0, bars, highs);
   CopyLow(Symbol(), PERIOD_H4, 0, bars, lows);
   CopyTime(Symbol(), PERIOD_H4, 0, bars, times);
   
   // Detect pivots (chronological array). Python confirms at i + pivot_bars.
   for(int i = InpPivotBars; i < bars - InpPivotBars; i++) {
      datetime confirmedAt = times[i + InpPivotBars];
      
      // Pivot high (supply zone for shorts)
      if(IsPivotHigh(highs, i, InpPivotBars)) {
         AddZone(confirmedAt, highs[i], -1); // -1 = short/supply
      }
      
      // Pivot low (demand zone for longs)
      if(IsPivotLow(lows, i, InpPivotBars)) {
         AddZone(confirmedAt, lows[i], 1); // 1 = long/demand
      }
   }
   
   if(InpEnableDebugPrint) {
      Print("Zones refreshed: ", m_zoneCount, " zones found");
   }
}

//+------------------------------------------------------------------+
//| Check if pivot high                                              |
//+------------------------------------------------------------------+
bool IsPivotHigh(double &highs[], int index, int bars) {
   double pivotHigh = highs[index];
   for(int j = 1; j <= bars; j++) {
      if(highs[index - j] > pivotHigh) return false;
      if(highs[index + j] > pivotHigh) return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Check if pivot low                                               |
//+------------------------------------------------------------------+
bool IsPivotLow(double &lows[], int index, int bars) {
   double pivotLow = lows[index];
   for(int j = 1; j <= bars; j++) {
      if(lows[index - j] < pivotLow) return false;
      if(lows[index + j] < pivotLow) return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Add zone to array                                                |
//+------------------------------------------------------------------+
void AddZone(datetime confirmedAt, double price, int direction) {
   int size = ArraySize(m_zones);
   ArrayResize(m_zones, size + 1);
   
   datetime confirmedUtc = ToUTC(confirmedAt);
   m_zones[size].time = confirmedUtc;
   m_zones[size].price = price;
   m_zones[size].direction = direction;
   m_zones[size].source_tf = PERIOD_H4;
   m_zones[size].origin_time_utc = confirmedUtc;
   
   // Calculate confirmation time
   int confirmMinutes = InpMinConfirmBars * PeriodSeconds(InpConfirmTF) / 60;
   m_zones[size].confirmed_at = confirmedUtc + confirmMinutes * 60;
   m_zones[size].confirmed = (ToUTC(TimeCurrent()) >= m_zones[size].confirmed_at);

   if(InpEnableDebugPrint) {
      PrintFormat("AddZone: time=%s price=%.5f dir=%s confirmed=%s confirmed_at=%s",
                  TimeToString(m_zones[size].time, TIME_DATE|TIME_SECONDS),
                  m_zones[size].price,
                  (m_zones[size].direction == 1) ? "LONG" : "SHORT",
                  m_zones[size].confirmed ? "true" : "false",
                  TimeToString(m_zones[size].confirmed_at, TIME_DATE|TIME_SECONDS));
   }

   m_zoneCount++;
}

//+------------------------------------------------------------------+
//| Log closed trades from history (fallback for backtesting)        |
//+------------------------------------------------------------------+
void LogClosedTradesFromHistory() {
   // Scan trading history for any closed deals that haven't been logged yet
   int dealsTotal = HistoryDealsTotal();
   for(int i = 0; i < dealsTotal; i++) {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;
      
      long dealMagic = HistoryDealGetInteger(deal, DEAL_MAGIC);
      if(dealMagic != InpMagicNumber) continue;
      
      long dealEntry = HistoryDealGetInteger(deal, DEAL_ENTRY);
      if(dealEntry != DEAL_ENTRY_OUT && dealEntry != DEAL_ENTRY_OUT_BY && dealEntry != DEAL_ENTRY_INOUT) {
         continue; // Only log exits
      }
      
      ulong positionId = HistoryDealGetInteger(deal, DEAL_POSITION_ID);
      
      // Check if this position has already been logged
      bool alreadyLogged = false;
      for(int j = 0; j < ArraySize(m_pos_meta); j++) {
         if(m_pos_meta[j].ticket == positionId && m_pos_meta[j].logged) {
            alreadyLogged = true;
            break;
         }
      }
      if(alreadyLogged) continue;
      
      // Find the entry deal and position metadata
      int metaIndex = FindPositionMeta(positionId);
      if(metaIndex < 0) continue; // No metadata found
      
      // Log this exit
      datetime dealTime = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
      double dealPrice = HistoryDealGetDouble(deal, DEAL_PRICE);
      double dealProfit = HistoryDealGetDouble(deal, DEAL_PROFIT);
      double dealCommission = HistoryDealGetDouble(deal, DEAL_COMMISSION);
      double dealSwap = HistoryDealGetDouble(deal, DEAL_SWAP);
      double dealVolume = HistoryDealGetDouble(deal, DEAL_VOLUME);
      string dealComment = HistoryDealGetString(deal, DEAL_COMMENT);
      long dealReason = HistoryDealGetInteger(deal, DEAL_REASON);
      
      SPositionMeta meta = m_pos_meta[metaIndex];
      string exitReason = InferExitReason(dealPrice, meta.stop_price, meta.tp_price);
      string brokerExitReason = DealReasonToString(dealReason);
      double netProfit = dealProfit + dealCommission + dealSwap;
      double rValue = (meta.initial_risk > 0.0)
         ? ((meta.direction == 1) ? (dealPrice - meta.entry_price) / meta.initial_risk
                                  : (meta.entry_price - dealPrice) / meta.initial_risk)
         : 0.0;
      
      LogTradeCsvRow(meta.entry_time_utc, dealTime, positionId, meta.direction, dealVolume,
                     meta.entry_price, dealPrice, meta.stop_price, meta.tp_price,
                     meta.initial_risk, exitReason, dealProfit, dealCommission, dealSwap,
                     netProfit, rValue, meta.total_score, meta.confidence_mult, meta.regime,
                     brokerExitReason, meta.entry_comment, meta.session_mult, meta.regime_mult,
                     meta.zone_price, meta.zone_time_utc, dealComment);
      
      // Mark as logged to avoid duplicate entries
      m_pos_meta[metaIndex].logged = true;
   }
}

//+------------------------------------------------------------------+
//| Manage open positions (trailing, breakeven, exits)               |
//+------------------------------------------------------------------+
void ManageOpenPositions() {
   double bid = SymbolInfoDouble(Symbol(), SYMBOL_BID);
   double ask = SymbolInfoDouble(Symbol(), SYMBOL_ASK);
   datetime barTime = iTime(Symbol(), PERIOD_M5, 1);
   double barOpen = iOpen(Symbol(), PERIOD_M5, 1);
   double barClose = iClose(Symbol(), PERIOD_M5, 1);
   double barHigh = iHigh(Symbol(), PERIOD_M5, 1);
   double barLow = iLow(Symbol(), PERIOD_M5, 1);
   datetime barTimeUtc = ToUTC(barTime);

   if(InpEnableDebugPrint) {
      PrintFormat("ManageOpenPositionsDebug: barTime=%s barTimeUtc=%s open=%.5f high=%.5f low=%.5f close=%.5f bid=%.5f ask=%.5f",
                  TimeToString(barTime, TIME_DATE|TIME_SECONDS),
                  TimeToString(barTimeUtc, TIME_DATE|TIME_SECONDS),
                  barOpen, barHigh, barLow, barClose, bid, ask);
   }
   
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      if(m_position.SelectByIndex(i)) {
         if(m_position.Symbol() != Symbol()) continue;
         if(m_position.Magic() != InpMagicNumber) continue;
         
         // Get current position state
         ulong ticket = m_position.Ticket();
         int metaIndex = FindPositionMeta(ticket);
         if(metaIndex < 0) continue;
         
         double entryPrice = m_pos_meta[metaIndex].entry_price;
         double stopPrice = m_pos_meta[metaIndex].stop_price;
         double tpPrice = m_pos_meta[metaIndex].tp_price;
         double initialRisk = m_pos_meta[metaIndex].initial_risk;
         double atrEntry = m_pos_meta[metaIndex].atr_entry;
         bool isLong = (m_pos_meta[metaIndex].direction == 1);
         
         // Trailing stop update (must be before breakeven)
         if(atrEntry > 0) {
            double trailDistance = InpTrailATRMult * atrEntry;
            if(isLong) {
               double newTrail = barClose - trailDistance;
               if(InpEnableDebugPrint) {
                  PrintFormat("TrailCalc: ticket=%I64u dir=LONG atrEntry=%.5f trailDistance=%.5f barClose=%.5f stopBefore=%.5f stopAfter=%.5f",
                              ticket,
                              atrEntry,
                              trailDistance,
                              barClose,
                              stopPrice,
                              newTrail);
               }
               if(newTrail > stopPrice) {
                  stopPrice = newTrail;
               }
            } else {
               double newTrail = barClose + trailDistance;
               if(InpEnableDebugPrint) {
                  PrintFormat("TrailCalc: ticket=%I64u dir=SHORT atrEntry=%.5f trailDistance=%.5f barClose=%.5f stopBefore=%.5f stopAfter=%.5f",
                              ticket,
                              atrEntry,
                              trailDistance,
                              barClose,
                              stopPrice,
                              newTrail);
               }
               if(newTrail < stopPrice) {
                  stopPrice = newTrail;
               }
            }
         } else if(InpEnableDebugPrint) {
            PrintFormat("TrailCalc: ticket=%I64u skipped because atrEntry=%.5f", ticket, atrEntry);
         }
         
         // Breakeven check (after trailing)
         double currentR = (isLong)
            ? (barClose - entryPrice) / initialRisk
            : (entryPrice - barClose) / initialRisk;
         if(!m_pos_meta[metaIndex].be_triggered && currentR >= InpBreakevenR) {
            stopPrice = entryPrice;
            m_pos_meta[metaIndex].be_triggered = true;
         }
         
         // Minimum-hold stop filter
         int barsPerHour = MathMax(1, 60 / 5);
         int minHoldBars = 2 * barsPerHour;
         int holdBars = (int)((barTime - m_pos_meta[metaIndex].entry_time) / PeriodSeconds(PERIOD_M5));
         bool allowStopExit = (holdBars >= minHoldBars) || (currentR >= 0.0);
         
         // Exit checks using bar high/low
         bool exitNow = false;
         double exitSignalPx = 0.0;
         
         if(isLong) {
            if(allowStopExit && barLow <= stopPrice) {
               exitSignalPx = stopPrice;
               exitNow = true;
            } else if(barHigh >= tpPrice) {
               exitSignalPx = tpPrice;
               exitNow = true;
            }
         } else {
            if(allowStopExit && barHigh >= stopPrice) {
               exitSignalPx = stopPrice;
               exitNow = true;
            } else if(barLow <= tpPrice) {
               exitSignalPx = tpPrice;
               exitNow = true;
            }
         }
         
         // Persist updated stop
         m_pos_meta[metaIndex].stop_price = stopPrice;
         
         // Apply trailing stop or breakeven modification to broker (CRITICAL: was missing before)
         double currentBrokerStop = m_position.StopLoss();
         if(MathAbs(stopPrice - currentBrokerStop) > SymbolInfoDouble(Symbol(), SYMBOL_POINT)) {
            if(!m_trade.PositionModify(ticket, stopPrice, tpPrice)) {
               if(InpEnableDebugPrint) {
                  PrintFormat("TrailDebug: PositionModify FAILED ticket=%I64u newStop=%.5f error=%s", 
                     ticket, stopPrice, m_trade.ResultComment());
               }
            } else if(InpEnableDebugPrint) {
               PrintFormat("TrailDebug: PositionModify SUCCESS ticket=%I64u oldStop=%.5f newStop=%.5f r=%.2f", 
                  ticket, currentBrokerStop, stopPrice, currentR);
            }
         }
         
         if(exitNow) {
            // Log the trade immediately before closing (use exit signal price as exit price)
            double volume = m_position.Volume();
            double grossProfit = 0.0;
            double commission = 0.0;
            double swap = 0.0;
            
            // Calculate PNL based on exit signal price
            if(isLong) {
               grossProfit = (exitSignalPx - entryPrice) * volume * SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_VALUE) / SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_SIZE);
            } else {
               grossProfit = (entryPrice - exitSignalPx) * volume * SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_VALUE) / SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_SIZE);
            }
            
            double netProfit = grossProfit + commission + swap;
            double rValue = (initialRisk > 0.0) ? (grossProfit / (initialRisk * SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_VALUE) / SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_SIZE))) : 0.0;
            string exitReason = InferExitReason(exitSignalPx, stopPrice, tpPrice);
            
            // Log the trade
            LogTradeCsvRow(m_pos_meta[metaIndex].entry_time_utc, barTimeUtc, ticket, 
                          m_pos_meta[metaIndex].direction, volume,
                          entryPrice, exitSignalPx, stopPrice, tpPrice,
                          initialRisk, exitReason, grossProfit, commission, swap,
                          netProfit, rValue, m_pos_meta[metaIndex].total_score, 
                          m_pos_meta[metaIndex].confidence_mult, m_pos_meta[metaIndex].regime,
                          (exitSignalPx <= stopPrice + SymbolInfoDouble(Symbol(), SYMBOL_POINT)) ? "sl" : "tp",
                          m_pos_meta[metaIndex].entry_comment, m_pos_meta[metaIndex].session_mult,
                          m_pos_meta[metaIndex].regime_mult, m_pos_meta[metaIndex].zone_price,
                          m_pos_meta[metaIndex].zone_time_utc, "auto_close");
            
            m_trade.PositionClose(ticket);
         }
      }
   }
   // Preserve closed position metadata so OnTester() can export the full backtest history.
}

//+------------------------------------------------------------------+
//| Get ATR value stored for position                                |
//+------------------------------------------------------------------+
double GetPositionATR(ulong ticket) {
   // Store ATR in position comment as "ATR=0.00123"
   string comment;
   if(PositionSelectByTicket(ticket)) {
      comment = PositionGetString(POSITION_COMMENT);
      int startPos = StringFind(comment, "ATR=");
      if(startPos >= 0) {
         string atrStr = StringSubstr(comment, startPos + 4);
         int endPos = StringFind(atrStr, " ");
         if(endPos > 0) atrStr = StringSubstr(atrStr, 0, endPos);
         return StringToDouble(atrStr);
      }
   }
   return 0.0;
}

//+------------------------------------------------------------------+
//| Check entry conditions                                           |
//+------------------------------------------------------------------+
void CheckEntryConditions() {
   // Check if we can trade
   datetime barTime = iTime(Symbol(), PERIOD_M5, 1);
   if(!CanTrade(barTime)) return;
   
   datetime barTimeUtc = ToUTC(barTime);
   double signalPrice = iClose(Symbol(), PERIOD_M5, 1);
   double signalOpen = iOpen(Symbol(), PERIOD_M5, 1);
   double signalHigh = iHigh(Symbol(), PERIOD_M5, 1);
   double signalLow = iLow(Symbol(), PERIOD_M5, 1);

   if(InpEnableDebugPrint) {
      PrintFormat("EntryTimeDebug: barTime=%s barTimeUtc=%s signalTF=%s m5Bars=%d",
                  TimeToString(barTime, TIME_DATE|TIME_SECONDS),
                  TimeToString(barTimeUtc, TIME_DATE|TIME_SECONDS),
                  TfToShortString(PERIOD_M5),
                  Bars(Symbol(), PERIOD_M5));
   }

   if(InpEnableDebugPrint) {
      PrintFormat("BAR_DATA: bar=%s O=%.5f H=%.5f L=%.5f C=%.5f",
                  TimeToString(barTime, TIME_DATE|TIME_MINUTES),
                  signalOpen, signalHigh, signalLow, signalPrice);
   }
   
   // Get H4 ATR
   double h4ATR = GetATRAtTime(PERIOD_H4, m_handleH4ATR, barTime);
   double m15ATR = GetATRAtTime(PERIOD_M15, m_handleM15ATR, barTime);
   if(h4ATR <= 0) {
      if(InpEnableDebugPrint) {
         PrintFormat("ATRDebug: invalid H4 ATR symbol=%s bar=%s h4ATR=%.8f m15ATR=%.8f", Symbol(), TimeToString(barTime, TIME_DATE|TIME_SECONDS), h4ATR, m15ATR);
      }
      return;
   }
   if(InpEnableDebugPrint) {
      PrintFormat("ATRDebug: symbol=%s bar=%s h4ATR=%.8f m15ATR=%.8f zoneTol=%.6f signal=%.5f",
                  Symbol(), TimeToString(barTime, TIME_DATE|TIME_SECONDS), h4ATR, m15ATR, GetEffectiveZoneTolerance(), signalPrice);
   }
  
     // Compute session multiplier once and log it for the bar (ensures SessionDebug visibility)
     double sessionMultForBar = GetSessionMultiplier(barTimeUtc);
     if(InpEnableDebugPrint) {
        PrintFormat("SessionMultDebug: bar=%s sessionMult=%.2f",
                    TimeToString(barTimeUtc, TIME_DATE|TIME_SECONDS), sessionMultForBar);
     }

     // Dump current zone list (indices, times, price, dir, confirmed) to ensure full data capture
     if(InpEnableDebugPrint) {
        for(int zi = 0; zi < m_zoneCount; zi++) {
           PrintFormat("ZoneDump idx=%d time=%s price=%.5f dir=%s confirmed=%d confirmed_at=%s source_tf=%s",
                       zi,
                       TimeToString(m_zones[zi].time, TIME_DATE|TIME_SECONDS),
                       m_zones[zi].price,
                       (m_zones[zi].direction==1)?"LONG":"SHORT",
                       m_zones[zi].confirmed ? 1 : 0,
                       TimeToString(m_zones[zi].confirmed_at, TIME_DATE|TIME_SECONDS),
                       TfToShortString(m_zones[zi].source_tf));
        }
     }
   
   // Rolling window filter (UTC)
   datetime windowStartUtc = barTimeUtc - (InpZoneLookback * PeriodSeconds(PERIOD_H4));

   int skipOutOfWindow = 0;
   int skipPending = 0;
   int skipZoneTolerance = 0;
   int skipChase = 0;
   int skipBounce = 0;
   int skipSession = 0;
   int skipCluster = 0;
   int skipScoreFloor = 0;
   int skipLtfCap = 0;
   bool entryExecuted = false;
   
   // Scan zones for potential entries
   for(int i = 0; i < m_zoneCount; i++) {
      if(m_zones[i].time < windowStartUtc) {
         skipOutOfWindow++;
         if(InpEnableDebugPrint) PrintFormat("SkipZone idx=%d reason=out_of_window zone_time=%s", i, TimeToString(m_zones[i].time, TIME_DATE|TIME_SECONDS));
         continue;
      }
      if(m_zones[i].time >= barTimeUtc) {
         skipOutOfWindow++;
         if(InpEnableDebugPrint) PrintFormat("SkipZone idx=%d reason=future_zone zone_time=%s", i, TimeToString(m_zones[i].time, TIME_DATE|TIME_SECONDS));
         continue;
      }
      if(!m_zones[i].confirmed && barTimeUtc < m_zones[i].confirmed_at) {
         skipPending++;
         if(InpEnableDebugPrint) PrintFormat("SkipZone idx=%d reason=pending_confirmation confirmed_at=%s", i, TimeToString(m_zones[i].confirmed_at, TIME_DATE|TIME_SECONDS));
         continue;
      }
      
      // Zone proximity check
      double zoneDist = MathAbs(signalPrice - m_zones[i].price) / m_zones[i].price;
      if(InpEnableDebugPrint) {
         PrintFormat("ScanZone idx=%d time=%s zone_price=%.5f dir=%s zoneDist=%.5f tol=%.6f signal=%.5f",
                     i,
                     TimeToString(m_zones[i].time, TIME_DATE|TIME_SECONDS),
                     m_zones[i].price,
                     (m_zones[i].direction == 1) ? "LONG" : "SHORT",
                     zoneDist,
                     GetEffectiveZoneTolerance(),
                     signalPrice);
      }
      if(zoneDist > GetEffectiveZoneTolerance()) {
         skipZoneTolerance++;
         if(InpEnableDebugPrint) PrintFormat("SkipZone idx=%d reason=tolerance zoneDist=%.6f tol=%.6f", i, zoneDist, GetEffectiveZoneTolerance());
         continue;
      }
      
      // Chasing filter (M15 ATR)
      if(m15ATR > 0) {
         if(MathAbs(signalPrice - m_zones[i].price) > InpChaseFilterATR * m15ATR) {
            skipChase++;
            if(InpEnableDebugPrint) PrintFormat("SkipZone idx=%d reason=chase_filter distance=%.5f limit=%.5f m15ATR=%.8f", i, MathAbs(signalPrice - m_zones[i].price), InpChaseFilterATR * m15ATR, m15ATR);
            continue; // Too far, skip
         }
      }
      
      // Bounce filter
      if(m_zones[i].direction == 1) { // Long/demand zone
         if(signalPrice < m_zones[i].price * (1 - InpZoneTolerance)) {
            skipBounce++;
            if(InpEnableDebugPrint) PrintFormat("SkipZone idx=%d reason=bounce_reject LONG price=%.5f zone=%.5f", i, signalPrice, m_zones[i].price);
            continue; // Broke below
         }
      } else { // Short/supply zone
         if(signalPrice > m_zones[i].price * (1 + InpZoneTolerance)) {
            skipBounce++;
            if(InpEnableDebugPrint) PrintFormat("SkipZone idx=%d reason=bounce_reject SHORT price=%.5f zone=%.5f", i, signalPrice, m_zones[i].price);
            continue; // Broke above
         }
      }
      
      // Session filter (use pre-computed value)
      if(sessionMultForBar <= 0) {
         skipSession++;
         if(InpEnableDebugPrint) PrintFormat("SkipZone idx=%d reason=session_filter", i);
         continue;
      }
      
      // Cluster cap
      if(!CheckClusterCap(barTimeUtc)) {
         skipCluster++;
         if(InpEnableDebugPrint) PrintFormat("SkipZone idx=%d reason=cluster_cap", i);
         continue;
      }
      
      // Daily regime
      string regime = GetDailyRegime(barTime);
      double regimeMult = GetRegimeMultiplier(regime, m_zones[i].direction);
      
      // Multi-timeframe scoring
      int h4Score = GetTFScoreAtTime(PERIOD_H4, m_zones[i].direction, barTime);
      int h1Score = GetTFScoreAtTime(PERIOD_H1, m_zones[i].direction, barTime);
      int ltfScore = GetTFScoreAtTime(PERIOD_M5, m_zones[i].direction, barTime);
      
      if(h4Score < InpH4ScoreMin || h1Score < InpH1ScoreMin || ltfScore < InpLTFScoreMin) {
         skipScoreFloor++;
         if(InpEnableDebugPrint) PrintFormat("SkipZone idx=%d reason=score_floor h4=%d h1=%d ltf=%d mins=%d/%d/%d", i, h4Score, h1Score, ltfScore, InpH4ScoreMin, InpH1ScoreMin, InpLTFScoreMin);
         continue;
      }
      
      int totalScore = h4Score + h1Score + ltfScore;
      
      // Direction score offset
      int effectiveScoreMin = InpScoreMin;
      if(m_zones[i].direction == 1) { // Long
         effectiveScoreMin += InpLongScoreOffset;
      }
      
      if(totalScore < effectiveScoreMin) {
         skipScoreFloor++;
         if(InpEnableDebugPrint) PrintFormat("SkipZone idx=%d reason=score_total total=%d min=%d", i, totalScore, effectiveScoreMin);
         continue;
      }
      if(ltfScore > InpLTFScoreCap) {
         skipLtfCap++;
         if(InpEnableDebugPrint) PrintFormat("SkipZone idx=%d reason=ltf_cap ltf=%d cap=%d", i, ltfScore, InpLTFScoreCap);
         continue;
      }
      
      // Confidence multiplier
      double confMult = CalculateConfidenceMultiplier(barTimeUtc);
      
      if(InpEnableDebugPrint) {
         PrintFormat("ENTRY_ZONE: bar=%s signal=%.5f zone_idx=%d zone_time=%s zone_price=%.5f dir=%s zoneDist=%.6f tol=%.6f h4=%d h1=%d ltf=%d total=%d effMin=%d session=%.2f regime=%s regimeMult=%.2f confMult=%.2f h4ATR=%.5f m15ATR=%.5f",
               TimeToString(barTime, TIME_DATE|TIME_MINUTES),
               signalPrice,
               i,
               TimeToString(m_zones[i].time, TIME_DATE|TIME_SECONDS),
               m_zones[i].price,
               (m_zones[i].direction == 1) ? "LONG" : "SHORT",
               zoneDist,
               GetEffectiveZoneTolerance(),
               h4Score,
               h1Score,
               ltfScore,
               totalScore,
               effectiveScoreMin,
               sessionMultForBar,
               regime,
               regimeMult,
               confMult,
               h4ATR,
               m15ATR);
      }

      // Calculate position size and execute
      ExecuteEntry(m_zones[i], h4ATR, sessionMultForBar, regimeMult, confMult, totalScore, barTime, barTimeUtc, signalPrice);
      entryExecuted = true;
      
      break; // One entry per bar
   }

   if(InpEnableDebugPrint && !entryExecuted) {
      PrintFormat("EntryScanSummary: symbol=%s bar=%s zones=%d outOfWindow=%d pending=%d zoneTol=%d chase=%d bounce=%d session=%d cluster=%d scoreFloor=%d ltfCap=%d sessionMult=%.2f",
                  Symbol(),
                  TimeToString(barTime, TIME_DATE|TIME_SECONDS),
                  m_zoneCount,
                  skipOutOfWindow,
                  skipPending,
                  skipZoneTolerance,
                  skipChase,
                  skipBounce,
                  skipSession,
                  skipCluster,
                  skipScoreFloor,
                  skipLtfCap,
                  sessionMultForBar);
   }
}

//+------------------------------------------------------------------+
//| Check if trading is allowed                                      |
//+------------------------------------------------------------------+
bool CanTrade(datetime referenceTime) {
   // Top-level diagnostic: print key gating state for this reference time
   if(InpEnableDebugPrint) {
      int currentPositions = CountPositions();
      int cooldownRemaining = 0;
      if(m_lastEntryTime > 0) cooldownRemaining = MathMax(0, (int)(InpCooldownMin * 60 - (referenceTime - m_lastEntryTime)));
      int lockoutRemaining = 0;
      if(m_lastLossExitTime > 0) lockoutRemaining = MathMax(0, (int)(InpLockoutMin * 60 - (referenceTime - m_lastLossExitTime)));
      PrintFormat("CanTradeDebug: reference=%s lastEntry=%s cooldownRem=%d lastLossExit=%s lockoutRem=%d circuitUntil=%s positions=%d",
                  TimeToString(referenceTime, TIME_DATE|TIME_SECONDS),
                  (m_lastEntryTime==0)?"0":TimeToString(m_lastEntryTime, TIME_DATE|TIME_SECONDS),
                  cooldownRemaining,
                  (m_lastLossExitTime==0)?"0":TimeToString(m_lastLossExitTime, TIME_DATE|TIME_SECONDS),
                  lockoutRemaining,
                  (m_circuitBreakerUntil==0)?"0":TimeToString(m_circuitBreakerUntil, TIME_DATE|TIME_SECONDS),
                  currentPositions);
   }
   if(InpEnableFTMOGuardrails) {
      string ftmoReason = "";
      if(!CheckFTMOGuardrails(ftmoReason)) {
         if(InpEnableDebugPrint && (TimeCurrent() - m_ftmoLastStatusPrint >= 60)) {
            Print("FTMO block: ", ftmoReason);
            m_ftmoLastStatusPrint = TimeCurrent();
         }
         return false;
      }
   }

   // Circuit breaker check
   if(referenceTime < m_circuitBreakerUntil) {
      if(InpEnableDebugPrint) PrintFormat("CanTrade: Circuit breaker active until %s", TimeToString(m_circuitBreakerUntil, TIME_DATE|TIME_SECONDS));
      return false;
   }
   
   // Max concurrent positions check
   int currentPositions = CountPositions();
   if(currentPositions >= InpMaxConcurrent) {
      if(InpEnableDebugPrint) PrintFormat("CanTrade: Max concurrent reached (%d >= %d)", currentPositions, InpMaxConcurrent);
      return false;
   }
   
   // Cooldown check
   if(m_lastEntryTime > 0) {
      if(referenceTime - m_lastEntryTime < InpCooldownMin * 60) {
         if(InpEnableDebugPrint) PrintFormat("CanTrade: Cooldown active (%d sec remaining)", InpCooldownMin * 60 - (int)(referenceTime - m_lastEntryTime));
         return false;
      }
   }
   
   // Lockout after loss check
   if(m_lastLossExitTime > 0) {
      if(referenceTime - m_lastLossExitTime < InpLockoutMin * 60) {
         if(InpEnableDebugPrint) PrintFormat("CanTrade: Lockout active (%d sec remaining)", InpLockoutMin * 60 - (int)(referenceTime - m_lastLossExitTime));
         return false;
      }
   }
   
   return true;
}

int GetUTCDateKey(datetime utcTime) {
   MqlDateTime dt;
   TimeToStruct(utcTime, dt);
   return dt.year * 1000 + dt.day_of_year;
}

void SyncFTMODailyBaseline() {
   if(!InpEnableFTMOGuardrails) return;

   datetime nowUtc = ToUTC(TimeCurrent());
   int dayKey = GetUTCDateKey(nowUtc);
   if(m_ftmoCurrentDayKey == 0) {
      m_ftmoCurrentDayKey = dayKey;
      m_ftmoDayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      return;
   }
   if(dayKey != m_ftmoCurrentDayKey) {
      m_ftmoCurrentDayKey = dayKey;
      m_ftmoDayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      if(InpEnableDebugPrint) {
         Print("FTMO daily baseline reset: ", m_ftmoDayStartEquity);
      }
   }
}

void RegisterFTMOTradingDay(datetime entryUtc) {
   if(!InpEnableFTMOGuardrails) return;

   int dayKey = GetUTCDateKey(entryUtc);
   int size = ArraySize(m_ftmoTradeDayKeys);
   for(int i = 0; i < size; i++) {
      if(m_ftmoTradeDayKeys[i] == dayKey) return;
   }

   ArrayResize(m_ftmoTradeDayKeys, size + 1);
   m_ftmoTradeDayKeys[size] = dayKey;
}

bool CheckFTMOGuardrails(string &reason) {
   reason = "ok";
   if(!InpEnableFTMOGuardrails) return true;
   if(m_ftmoHardStop) {
      reason = StringFormat("hard stop active | equity=%.2f dayStart=%.2f initial=%.2f",
                            AccountInfoDouble(ACCOUNT_EQUITY), m_ftmoDayStartEquity, m_ftmoInitialEquity);
      return false;
   }

   SyncFTMODailyBaseline();

   double accountSize = (InpFTMOAccountSize > 0.0) ? InpFTMOAccountSize : m_ftmoInitialEquity;
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double dailyLimitCash = accountSize * (InpFTMOMaxDailyLossPct / 100.0);
   double maxLossCash = accountSize * (InpFTMOMaxLossPct / 100.0);
   double profitTargetCash = accountSize * (InpFTMOProfitTargetPct / 100.0);

   double dailyFloor = m_ftmoDayStartEquity - dailyLimitCash;
   if(equity <= dailyFloor) {
      reason = StringFormat("max daily loss reached | equity=%.2f floor=%.2f dayStart=%.2f limitCash=%.2f",
                            equity, dailyFloor, m_ftmoDayStartEquity, dailyLimitCash);
      m_ftmoHardStop = true;
      return false;
   }

   double totalFloor = m_ftmoInitialEquity - maxLossCash;
   if(equity <= totalFloor) {
      reason = StringFormat("max overall loss reached | equity=%.2f floor=%.2f initial=%.2f limitCash=%.2f",
                            equity, totalFloor, m_ftmoInitialEquity, maxLossCash);
      m_ftmoHardStop = true;
      return false;
   }

   datetime nowUtc = ToUTC(TimeCurrent());
   if(InpFTMOTradingPeriodDays > 0 && nowUtc >= (m_ftmoTradingStartUtc + InpFTMOTradingPeriodDays * 86400)) {
      reason = StringFormat("trading period expired | now=%s start=%s days=%d",
                            TimeToString(nowUtc, TIME_DATE|TIME_SECONDS),
                            TimeToString(m_ftmoTradingStartUtc, TIME_DATE|TIME_SECONDS),
                            InpFTMOTradingPeriodDays);
      m_ftmoHardStop = true;
      return false;
   }

   int tradedDays = ArraySize(m_ftmoTradeDayKeys);
   if(equity >= (m_ftmoInitialEquity + profitTargetCash) && tradedDays >= InpFTMOMinTradingDays) {
      reason = StringFormat("profit target reached | equity=%.2f target=%.2f tradedDays=%d minDays=%d",
                            equity, m_ftmoInitialEquity + profitTargetCash, tradedDays, InpFTMOMinTradingDays);
      m_ftmoHardStop = true;
      return false;
   }

   return true;
}

//+------------------------------------------------------------------+
//| Count current positions                                          |
//+------------------------------------------------------------------+
int CountPositions() {
   int count = 0;
   for(int i = 0; i < PositionsTotal(); i++) {
      if(m_position.SelectByIndex(i)) {
         if(m_position.Symbol() == Symbol() && m_position.Magic() == InpMagicNumber) {
            count++;
         }
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//| Get session size multiplier                                      |
//+------------------------------------------------------------------+
double GetSessionMultiplier(datetime barTimeUtc = 0) {
   MqlDateTime utc;
   if(barTimeUtc == 0) {
      GetUTCTime(utc);
   } else {
      TimeToStruct(barTimeUtc, utc);
   }

   // Debug: always log what the EA sees for session checks when debug enabled
   if(InpEnableDebugPrint) {
      PrintFormat("SessionDebug: serverTime=%s utcHour=%d utcDay=%d start=%d end=%d",
                  TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES),
                  utc.hour, utc.day_of_week, InpSessionStart, InpSessionEnd);
   }

   // Check weekend (UTC)
   if(utc.day_of_week == 0 || utc.day_of_week == 6) {
      return 0.0; // US100 only weekdays
   }

   // Core session check (13:00-21:00 UTC)
   if(utc.hour >= InpSessionStart && utc.hour < InpSessionEnd) {
      double mult = 1.0;
      // Peak session boost (14-17 UTC)
      if(InpPeakSessionBoost && utc.hour >= 14 && utc.hour <= 17) {
         mult *= 1.2;
      }
      return mult;
   }

   return 0.0; // Outside session
}

//+------------------------------------------------------------------+
//| Check cluster cap (max trades per 4H window)                     |
//+------------------------------------------------------------------+
bool CheckClusterCap(datetime entryUtc) {
   int entriesInWindow = CountEntriesInWindow(entryUtc);
   return entriesInWindow < InpMaxConcurrent;
}

//+------------------------------------------------------------------+
//| Get daily regime (bull/bear)                                     |
//+------------------------------------------------------------------+
string GetDailyRegime(datetime barTime) {
   double ema50[1], ema200[1];
   int shift = iBarShift(Symbol(), PERIOD_D1, barTime, false);
   if(shift < 0) return "bull";
   if(CopyBuffer(m_handleDailyEMA50, 0, shift, 1, ema50) < 1) return "bull";
   if(CopyBuffer(m_handleDailyEMA200, 0, shift, 1, ema200) < 1) return "bull";
   
   return (ema50[0] > ema200[0]) ? "bull" : "bear";
}

//+------------------------------------------------------------------+
//| Get regime size multiplier                                       |
//+------------------------------------------------------------------+
double GetRegimeMultiplier(string regime, int direction) {
   if((regime == "bull" && direction == 1) || 
      (regime == "bear" && direction == -1)) {
      return 1.0; // With trend
   }
   return InpCounterTrendMult; // Counter-trend
}

//+------------------------------------------------------------------+
//| Get timeframe score (simplified version)                        |
//+------------------------------------------------------------------+
int GetTFScoreAtTime(ENUM_TIMEFRAMES tf, int direction, datetime barTime) {
   int handleEMA20, handleEMA50, handleRSI;
   
   switch(tf) {
      case PERIOD_H4:
         handleEMA20 = m_handleH4EMA20;
         handleEMA50 = m_handleH4EMA50;
         handleRSI = m_handleH4RSI;
         break;
      case PERIOD_H1:
         handleEMA20 = m_handleH1EMA20;
         handleEMA50 = m_handleH1EMA50;
         handleRSI = m_handleH1RSI;
         break;
      case PERIOD_M5:
         handleEMA20 = m_handleM5EMA20;
         handleEMA50 = m_handleM5EMA50;
         handleRSI = m_handleM5RSI;
         break;
      default:
         return 0;
   }
   
   double close[1], ema20[1], ema50[1], rsi[1];
   int shift = iBarShift(Symbol(), tf, barTime, false);
   if(shift < 0) {
      if(InpEnableDebugPrint) PrintFormat("ScoreDebug: tf=%s dir=%d barTime=%s shift=%d -> iBarShift<0", TfToShortString(tf), direction, TimeToString(barTime, TIME_DATE|TIME_SECONDS), shift);
      return 0;
   }
   if(CopyClose(Symbol(), tf, shift, 1, close) < 1) {
      if(InpEnableDebugPrint) PrintFormat("ScoreDebug: tf=%s dir=%d barTime=%s shift=%d -> CopyClose failed", TfToShortString(tf), direction, TimeToString(barTime, TIME_DATE|TIME_SECONDS), shift);
      return 0;
   }
   if(CopyBuffer(handleEMA20, 0, shift, 1, ema20) < 1) {
      if(InpEnableDebugPrint) PrintFormat("ScoreDebug: tf=%s dir=%d barTime=%s shift=%d -> CopyBuffer EMA20 failed", TfToShortString(tf), direction, TimeToString(barTime, TIME_DATE|TIME_SECONDS), shift);
      return 0;
   }
   if(CopyBuffer(handleEMA50, 0, shift, 1, ema50) < 1) {
      if(InpEnableDebugPrint) PrintFormat("ScoreDebug: tf=%s dir=%d barTime=%s shift=%d -> CopyBuffer EMA50 failed", TfToShortString(tf), direction, TimeToString(barTime, TIME_DATE|TIME_SECONDS), shift);
      return 0;
   }
   if(CopyBuffer(handleRSI, 0, shift, 1, rsi) < 1) {
      if(InpEnableDebugPrint) PrintFormat("ScoreDebug: tf=%s dir=%d barTime=%s shift=%d -> CopyBuffer RSI failed", TfToShortString(tf), direction, TimeToString(barTime, TIME_DATE|TIME_SECONDS), shift);
      return 0;
   }
   
   int score = 0;
   
   if(direction == 1) { // Long conditions
      if(close[0] > ema20[0]) score++;
      if(ema20[0] > ema50[0]) score++;
      if(rsi[0] > 50) score++;
   } else { // Short conditions
      if(close[0] < ema20[0]) score++;
      if(ema20[0] < ema50[0]) score++;
      if(rsi[0] < 50) score++;
   }
   
   if(InpEnableDebugPrint && score == 0) {
      PrintFormat("ScoreDebug: tf=%s dir=%d barTime=%s shift=%d close=%.5f ema20=%.5f ema50=%.5f rsi=%.5f score=%d",
                  TfToShortString(tf), direction, TimeToString(barTime, TIME_DATE|TIME_SECONDS), shift,
                  (double)close[0], (double)ema20[0], (double)ema50[0], (double)rsi[0], score);
   }

   return score;
}

//+------------------------------------------------------------------+
//| Calculate confidence multiplier                                  |
//+------------------------------------------------------------------+
double CalculateConfidenceMultiplier(datetime entryUtc) {
   int entriesInWindow = CountEntriesInWindow(entryUtc);
   if(InpEnableDebugPrint) {
      datetime windowStart = Get4HWindowStart(entryUtc);
      PrintFormat("ConfDebug: entryUtc=%s windowStart=%s entriesInWindow=%d totalRegistered=%d",
                  TimeToString(entryUtc, TIME_DATE|TIME_SECONDS), TimeToString(windowStart, TIME_DATE|TIME_SECONDS),
                  entriesInWindow, ArraySize(m_entry_times_utc));
   }
   return (entriesInWindow == 0) ? InpConfidenceMult : 1.0;
}

//+------------------------------------------------------------------+
//| Execute entry                                                    |
//+------------------------------------------------------------------+
void ExecuteEntry(SZone &zone, double h4ATR, double sessionMult,
                  double regimeMult, double confMult, int totalScore,
                  datetime barTime, datetime barTimeUtc, double signalPrice) {
   if(InpEnableDebugPrint) {
      PrintFormat("EXECUTING: bar=%s dir=%s signalPrice=%.5f zonePrice=%.5f h4ATR=%.5f score=%d confMult=%.2f sessionMult=%.2f regimeMult=%.2f",
                  TimeToString(barTime, TIME_DATE|TIME_MINUTES),
                  (zone.direction == 1) ? "LONG" : "SHORT",
                  signalPrice, zone.price, h4ATR, totalScore, confMult, sessionMult, regimeMult);
   }
   
   double entryPrice = ApplyExecutionAdjustment(signalPrice, zone.direction, true);
   ENUM_ORDER_TYPE orderType = (zone.direction == 1) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   
   // Calculate stop and take profit
   double stopDistance = InpATRStopMult * h4ATR;
   // Use the raw signal price to compute stop distance (match Python logic)
   double stopPrice = (zone.direction == 1)
      ? signalPrice - stopDistance
      : signalPrice + stopDistance;
   double takeProfit = (zone.direction == 1)
      ? entryPrice + (InpTPMult * stopDistance)
      : entryPrice - (InpTPMult * stopDistance);
   
   // Calculate position size
   double accountEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskAmount = accountEquity * (InpRiskPercent / 100.0);
   
   // Apply aggressive sizing multiplier (critical for profitability!)
   riskAmount *= InpRiskMultiplier;

   if(InpEnableFTMOGuardrails) {
      SyncFTMODailyBaseline();
      double accountSize = (InpFTMOAccountSize > 0.0) ? InpFTMOAccountSize : m_ftmoInitialEquity;
      double dailyLimitCash = accountSize * (InpFTMOMaxDailyLossPct / 100.0);
      double totalLimitCash = accountSize * (InpFTMOMaxLossPct / 100.0);
      double usedDailyLoss = MathMax(0.0, m_ftmoDayStartEquity - accountEquity);
      double usedTotalLoss = MathMax(0.0, m_ftmoInitialEquity - accountEquity);
      double remainingDaily = dailyLimitCash - usedDailyLoss;
      double remainingTotal = totalLimitCash - usedTotalLoss;
      riskAmount = MathMin(riskAmount, MathMin(remainingDaily, remainingTotal));
      if(riskAmount <= 0.0) {
         if(InpEnableDebugPrint) {
            Print("Entry blocked: FTMO loss budget exhausted");
         }
         return;
      }
   }

   double initialRisk = MathAbs(entryPrice - stopPrice);
   if(initialRisk <= 0) initialRisk = stopDistance;

   // Compute monetary risk per single lot using tick size/value when available.
   double tickSize = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_VALUE);
   double contractSize = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_CONTRACT_SIZE);
   if(contractSize <= 0.0) contractSize = 1.0;

   double riskPerLot = 0.0;
   if(tickSize > 0.0 && tickValue > 0.0) {
      double ticks = initialRisk / tickSize;
      riskPerLot = ticks * tickValue; // monetary risk for 1.0 lot at this stop distance
   }
   // Fallback: estimate using contract size if tick metadata missing
   if(riskPerLot <= 0.0) {
      riskPerLot = initialRisk * contractSize;
   }

   double sizeMultiplier = sessionMult * regimeMult * confMult;
   double rawVolume = riskAmount / riskPerLot;
   double volume = rawVolume * sizeMultiplier;

   // Normalize volume to broker steps and clamp to min/max
   double lotStep = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_STEP);
   if(lotStep <= 0.0) lotStep = 0.01;
   volume = MathFloor(volume / lotStep) * lotStep;

   double minLot = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MAX);
   if(minLot <= 0.0) minLot = lotStep;
   if(maxLot <= 0.0) maxLot = lotStep * 1000;

   if(volume < minLot) volume = minLot;
   if(volume > maxLot) volume = maxLot;

   // Enforce FTMO leverage cap as a further hard cap on volume
   if(InpEnableFTMOGuardrails && InpFTMOMaxLeverage > 0.0) {
      double notionalPerLot = MathAbs(entryPrice * contractSize);
      if(notionalPerLot > 0.0) {
         double maxNotional = accountEquity * InpFTMOMaxLeverage;
         double maxVolumeByLev = maxNotional / notionalPerLot;
         if(volume > maxVolumeByLev) {
            volume = MathFloor(maxVolumeByLev / lotStep) * lotStep;
         }
      }
      if(volume < minLot) {
         if(InpEnableDebugPrint) {
            Print("Entry blocked: below minimum lot after FTMO leverage cap");
         }
         return;
      }
   }

   // Pre-check required margin and free margin to avoid No money errors
   double requiredMargin = 0.0;
   bool marginCalcOk = OrderCalcMargin(orderType, Symbol(), volume, entryPrice, requiredMargin);
   double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(marginCalcOk && requiredMargin > freeMargin) {
      if(InpEnableDebugPrint) {
         PrintFormat("Entry blocked: insufficient free margin. required=%.2f free=%.2f vol=%.2f", requiredMargin, freeMargin, volume);
      }
      return;
   }

   if(InpEnableDebugPrint) {
      PrintFormat("SizingDebug: entry=%.5f stop=%.5f initialRisk=%.5f tickSize=%.8f tickValue=%.5f contractSize=%.2f riskPerLot=%.5f rawVolume=%.4f sizeMult=%.3f finalVol=%.2f",
                  entryPrice, stopPrice, initialRisk, tickSize, tickValue, contractSize, riskPerLot, rawVolume, sizeMultiplier, volume);
   }
   
   // Prepare comment with metadata
   string comment = StringFormat("P2_B|%s|S=%d|ATR=%.5f|REG=%s|CONF=%.1f",
                                (zone.direction == 1) ? "LONG" : "SHORT",
                                totalScore,
                                h4ATR,
                                GetDailyRegime(barTime),
                                confMult);
   
   // Execute trade (set SL/TP at open)
   if(InpEnableDebugPrint) {
      PrintFormat("ExecuteEntry: dir=%s order=%s price=%.5f SL=%.5f TP=%.5f vol=%.2f",
                  (zone.direction == 1) ? "LONG" : "SHORT",
                  (orderType == ORDER_TYPE_BUY) ? "BUY" : "SELL",
                  entryPrice,
                  stopPrice,
                  takeProfit,
                  volume);
   }
   m_trade.PositionOpen(Symbol(), orderType, volume, entryPrice, stopPrice, takeProfit, comment);
   
   if(m_trade.ResultRetcode() == TRADE_RETCODE_DONE) {
      ulong ticket = 0;
      // Find the newly opened position by searching the latest entry
      int posCount = PositionsTotal();
      for(int i = posCount - 1; i >= 0; i--) {
         if(m_position.SelectByIndex(i)) {
            if(m_position.Symbol() == Symbol() && m_position.Magic() == InpMagicNumber) {
               ticket = m_position.Ticket();
               break;
            }
         }
      }
      if(ticket == 0) {
         Print("Warning: Could not find newly opened position after successful trade");
         return;
      }
      int metaIndex = ArraySize(m_pos_meta);
      ArrayResize(m_pos_meta, metaIndex + 1);
      m_pos_meta[metaIndex].ticket = ticket;
      m_pos_meta[metaIndex].entry_time = barTime;
      m_pos_meta[metaIndex].entry_time_utc = barTimeUtc;
      m_pos_meta[metaIndex].entry_comment = comment;
      m_pos_meta[metaIndex].entry_price = entryPrice;
      m_pos_meta[metaIndex].stop_price = stopPrice;
      m_pos_meta[metaIndex].tp_price = takeProfit;
      m_pos_meta[metaIndex].initial_risk = initialRisk;
      m_pos_meta[metaIndex].atr_entry = h4ATR;
      m_pos_meta[metaIndex].be_triggered = false;
      m_pos_meta[metaIndex].direction = zone.direction;
      m_pos_meta[metaIndex].total_score = totalScore;
      m_pos_meta[metaIndex].confidence_mult = confMult;
      m_pos_meta[metaIndex].session_mult = sessionMult;
      m_pos_meta[metaIndex].regime_mult = regimeMult;
      m_pos_meta[metaIndex].regime = GetDailyRegime(barTime);
      m_pos_meta[metaIndex].zone_time_utc = zone.time;
      m_pos_meta[metaIndex].zone_price = zone.price;
      m_pos_meta[metaIndex].logged = false;  // Mark as not yet logged

      if(InpEnableDebugPrint) {
         PrintFormat("StoreATR: ticket=%I64u atr_entry=%.5f h4ATR=%.5f initialRisk=%.5f",
               ticket,
               m_pos_meta[metaIndex].atr_entry,
               h4ATR,
               initialRisk);
      }
      
      RegisterEntryTime(barTimeUtc);
      RegisterFTMOTradingDay(barTimeUtc);
      m_lastEntryTime = barTime;
      
      if(InpEnableDebugPrint) {
         Print("Entry executed: ", (zone.direction == 1) ? "LONG" : "SHORT",
            " | Price: ", entryPrice,
            " | SL: ", stopPrice,
            " | TP: ", takeProfit,
            " | Volume: ", volume,
            " | Score: ", totalScore,
            " | Conf: ", DoubleToString(confMult, 2));
      }
   } else {
      Print("Entry failed: ", m_trade.ResultRetcodeDescription());
   }
}

// Note: Trade event handling is implemented in OnTradeTransaction().
// OnTrade() is not needed for this EA.

//+------------------------------------------------------------------+
//| Draw zones on chart                                              |
//+------------------------------------------------------------------+
void DrawZones() {
   if(!InpEnableVisuals) return;
   
   // Clear old zone objects
   ObjectsDeleteAll(0, "Zone_");

   datetime nowServer = TimeCurrent();
   datetime nowUtc = ToUTC(nowServer);
   datetime activeCutoffUtc = nowUtc - (InpZoneLookback * PeriodSeconds(PERIOD_H4));
   
   for(int i = 0; i < m_zoneCount; i++) {
      bool isWithinActiveWindow = (m_zones[i].time >= activeCutoffUtc);
      bool isTouchedOrBroken = false;
      double currentPrice = SymbolInfoDouble(Symbol(), SYMBOL_BID);
      if(m_zones[i].direction == 1) {
         isTouchedOrBroken = (currentPrice < m_zones[i].price * (1 - InpZoneTolerance));
      } else {
         isTouchedOrBroken = (currentPrice > m_zones[i].price * (1 + InpZoneTolerance));
      }

      bool isActive = m_zones[i].confirmed && isWithinActiveWindow && !isTouchedOrBroken;
      string tfLabel = InpShowZoneTimeframe ? StringFormat("%s ", TfToShortString(m_zones[i].source_tf)) : "";
      string sideLabel = (m_zones[i].direction == 1) ? "Demand" : "Supply";
      string stateLabel = "Inactive";
      if(!m_zones[i].confirmed) {
         stateLabel = "Pending";
      } else if(!isWithinActiveWindow) {
         stateLabel = "Old";
      } else if(isTouchedOrBroken) {
         stateLabel = "Mitigated";
      } else {
         stateLabel = "Active";
      }
      string originLabel = TimeToString(FromUTC(m_zones[i].origin_time_utc), TIME_DATE|TIME_MINUTES);

      string baseName = StringFormat("Zone_%d", i);
      color zoneColor = (m_zones[i].direction == 1) ? m_demandColor : m_supplyColor;
      
      if(isActive || !InpShowOnlyActiveZones) {
         string lineName = baseName + "_line";
         datetime originServer = FromUTC(m_zones[i].origin_time_utc);
         if(!ObjectCreate(0, lineName, OBJ_TREND, 0, originServer, m_zones[i].price, nowServer, m_zones[i].price)) {
            continue;
         }
         ObjectSetInteger(0, lineName, OBJPROP_COLOR, zoneColor);
         ObjectSetInteger(0, lineName, OBJPROP_STYLE, isActive ? STYLE_SOLID : STYLE_DASH);
         ObjectSetInteger(0, lineName, OBJPROP_WIDTH, 2);
         ObjectSetInteger(0, lineName, OBJPROP_RAY_RIGHT, false);
         ObjectSetInteger(0, lineName, OBJPROP_RAY_LEFT, false);
         ObjectSetInteger(0, lineName, OBJPROP_BACK, true);

         if(InpShowZoneOrigins) {
            string labelName = baseName + "_label";
            string labelText = StringFormat("%s%s | %s | origin %s",
                                            tfLabel,
                                            sideLabel,
                                            stateLabel,
                                            originLabel);
            ObjectCreate(0, labelName, OBJ_TEXT, 0, nowServer, m_zones[i].price);
            ObjectSetString(0, labelName, OBJPROP_TEXT, labelText);
            ObjectSetInteger(0, labelName, OBJPROP_COLOR, zoneColor);
            ObjectSetInteger(0, labelName, OBJPROP_FONTSIZE, 8);
         }
      } else if(InpShowInactiveZoneMarkers) {
         string markerName = baseName + "_marker";
         datetime originServer = FromUTC(m_zones[i].origin_time_utc);
         if(!ObjectCreate(0, markerName, OBJ_TEXT, 0, originServer, m_zones[i].price)) {
            continue;
         }
         string markerText = StringFormat("%s%s | %s | origin %s",
                                          tfLabel,
                                          sideLabel,
                                          stateLabel,
                                          originLabel);
         ObjectSetString(0, markerName, OBJPROP_TEXT, markerText);
         ObjectSetInteger(0, markerName, OBJPROP_COLOR, zoneColor);
         ObjectSetInteger(0, markerName, OBJPROP_FONTSIZE, 7);
      }
   }
   
   ChartRedraw();
}

//+------------------------------------------------------------------+
//| OnTradeTransaction handler (for loss tracking)                  |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                       const MqlTradeRequest &request,
                       const MqlTradeResult &result) {
   // Track losses for circuit breaker when a position closes
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD) {
      if(HistoryDealSelect(trans.deal)) {
         long dealMagic = HistoryDealGetInteger(trans.deal, DEAL_MAGIC);
         if(dealMagic == InpMagicNumber) {
            double dealProfit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT);
            double dealCommission = HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
            double dealSwap = HistoryDealGetDouble(trans.deal, DEAL_SWAP);
            double netProfit = dealProfit + dealCommission + dealSwap;
            long dealEntry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
            if(dealEntry == DEAL_ENTRY_OUT || dealEntry == DEAL_ENTRY_OUT_BY || dealEntry == DEAL_ENTRY_INOUT) {
               datetime dealTime = (datetime)HistoryDealGetInteger(trans.deal, DEAL_TIME);
               ulong positionId = (ulong)HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);
               double dealVolume = HistoryDealGetDouble(trans.deal, DEAL_VOLUME);
               double dealPrice = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
               string dealComment = HistoryDealGetString(trans.deal, DEAL_COMMENT);
               long dealReason = HistoryDealGetInteger(trans.deal, DEAL_REASON);

               int metaIndex = FindPositionMeta(positionId);
               if(metaIndex >= 0) {
                  SPositionMeta meta = m_pos_meta[metaIndex];
                  string exitReason = InferExitReason(dealPrice, meta.stop_price, meta.tp_price);
                  string brokerExitReason = DealReasonToString(dealReason);
                  double rValue = (meta.initial_risk > 0.0)
                     ? ((meta.direction == 1) ? (dealPrice - meta.entry_price) / meta.initial_risk
                                              : (meta.entry_price - dealPrice) / meta.initial_risk)
                     : 0.0;
                  LogTradeCsvRow(meta.entry_time_utc, dealTime, positionId, meta.direction, dealVolume,
                                 meta.entry_price, dealPrice, meta.stop_price, meta.tp_price,
                                 meta.initial_risk, exitReason, dealProfit, dealCommission, dealSwap,
                                 netProfit, rValue, meta.total_score, meta.confidence_mult, meta.regime,
                                 brokerExitReason, meta.entry_comment, meta.session_mult, meta.regime_mult,
                                 meta.zone_price, meta.zone_time_utc, dealComment);
               }

               if(netProfit > 0) {
                  m_consecutiveLosses = 0;
               } else {
                  m_consecutiveLosses++;
                  m_lastLossExitTime = dealTime;
                  if(m_consecutiveLosses >= InpCircuitBreakerLosses) {
                     m_circuitBreakerUntil = dealTime + InpCircuitBreakerHours * 3600;
                     Print("Circuit breaker activated! Pausing until ", m_circuitBreakerUntil);
                     m_consecutiveLosses = 0;
                  }
               }
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Time helpers                                                    |
//+------------------------------------------------------------------+
int GetLastSundayDay(int year, int month) {
   MqlDateTime dt;
   dt.year = year;
   dt.mon = month;
   dt.day = 31;
   dt.hour = 0;
   dt.min = 0;
   dt.sec = 0;
   datetime t = StructToTime(dt);
   TimeToStruct(t, dt);
   int dow = dt.day_of_week; // 0=Sun
   int offset = (dow >= 0) ? dow : 0;
   return dt.day - offset;
}

bool IsSummerOffset(datetime utcTime) {
   MqlDateTime dt;
   TimeToStruct(utcTime, dt);
   int year = dt.year;

   int marchSunday = GetLastSundayDay(year, 3);
   int octSunday = GetLastSundayDay(year, 10);

   MqlDateTime start;
   start.year = year; start.mon = 3; start.day = marchSunday;
   start.hour = 1; start.min = 0; start.sec = 0;
   datetime dstStart = StructToTime(start);

   MqlDateTime end;
   end.year = year; end.mon = 10; end.day = octSunday;
   end.hour = 1; end.min = 0; end.sec = 0;
   datetime dstEnd = StructToTime(end);

   return (utcTime >= dstStart && utcTime < dstEnd);
}

int GetEffectiveUTCOffset() {
   if(!InpAutoUTCOffset) {
      return InpBrokerUTCOffset;
   }
   datetime utcNow = TimeGMT();
   return IsSummerOffset(utcNow) ? InpSummerUTCOffset : InpWinterUTCOffset;
}

datetime ToUTC(datetime serverTime) {
   int offset = GetEffectiveUTCOffset();
   return serverTime - (offset * 3600);
}

datetime FromUTC(datetime utcTime) {
   int offset = GetEffectiveUTCOffset();
   return utcTime + (offset * 3600);
}

string TfToShortString(ENUM_TIMEFRAMES tf) {
   switch(tf) {
      case PERIOD_M1:  return "M1";
      case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
      case PERIOD_D1:  return "D1";
      case PERIOD_W1:  return "W1";
      case PERIOD_MN1: return "MN1";
      default:         return "TF";
   }
}

void GetUTCTime(MqlDateTime &utc) {
   datetime utcTime = ToUTC(TimeCurrent());
   TimeToStruct(utcTime, utc);
}

//+------------------------------------------------------------------+
//| Execution adjustment                                            |
//+------------------------------------------------------------------+
double ApplyExecutionAdjustment(double price, int direction, bool isEntry) {
   double halfSpread = price * (InpSpreadBPS / 10000.0) / 2.0;
   double slippage = price * (InpSlippageBPS / 10000.0);
   double adjustment = halfSpread + slippage;
   if(isEntry) {
      return (direction == 1) ? price + adjustment : price - adjustment;
   }
   return (direction == 1) ? price - adjustment : price + adjustment;
}

//+------------------------------------------------------------------+
//| Cluster tracking                                                |
//+------------------------------------------------------------------+
void RegisterEntryTime(datetime entryUtc) {
   int size = ArraySize(m_entry_times_utc);
   ArrayResize(m_entry_times_utc, size + 1);
   m_entry_times_utc[size] = entryUtc;
   PruneEntryTimes(entryUtc);
}

int CountEntriesInWindow(datetime entryUtc) {
   datetime windowStart = Get4HWindowStart(entryUtc);
   datetime windowEnd = windowStart + PeriodSeconds(PERIOD_H4);
   int count = 0;
   for(int i = 0; i < ArraySize(m_entry_times_utc); i++) {
      if(m_entry_times_utc[i] >= windowStart && m_entry_times_utc[i] < windowEnd) {
         count++;
      }
   }
   return count;
}

void PruneEntryTimes(datetime nowUtc) {
   datetime cutoff = nowUtc - (48 * 3600);
   for(int i = ArraySize(m_entry_times_utc) - 1; i >= 0; i--) {
      if(m_entry_times_utc[i] < cutoff) {
         ArrayRemove(m_entry_times_utc, i, 1);
      }
   }
}

datetime Get4HWindowStart(datetime timeUtc) {
   MqlDateTime dt;
   TimeToStruct(timeUtc, dt);
   dt.min = 0;
   dt.sec = 0;
   dt.hour = dt.hour - (dt.hour % 4);
   return StructToTime(dt);
}

//+------------------------------------------------------------------+
//| Indicator lookup                                                |
//+------------------------------------------------------------------+
double GetATRAtTime(ENUM_TIMEFRAMES tf, int handle, datetime barTime) {
   double atr[1];
   int shift = iBarShift(Symbol(), tf, barTime, false);
   if(shift < 0) return 0.0;
   if(CopyBuffer(handle, 0, shift, 1, atr) < 1) return 0.0;
   return atr[0];
}

//+------------------------------------------------------------------+
//| Position metadata helpers                                       |
//+------------------------------------------------------------------+
int FindPositionMeta(ulong ticket) {
   for(int i = 0; i < ArraySize(m_pos_meta); i++) {
      if(m_pos_meta[i].ticket == ticket) return i;
   }
   return -1;
}

void CleanPositionMeta() {
   for(int i = ArraySize(m_pos_meta) - 1; i >= 0; i--) {
      if(i >= ArraySize(m_pos_meta)) continue; // Safety check
      if(!PositionSelectByTicket(m_pos_meta[i].ticket)) {
         if(i >= 0 && i < ArraySize(m_pos_meta)) {
            ArrayRemove(m_pos_meta, i, 1);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Chart event handler                                              |
//+------------------------------------------------------------------+
void OnChartEvent(const int id,
                 const long &lparam,
                 const double &dparam,
                 const string &sparam) {
   if(id == CHARTEVENT_CHART_CHANGE) {
      if(InpEnableVisuals) DrawZones();
   }
}

//+------------------------------------------------------------------+
//| Custom optimization metric for MT5 Strategy Tester               |
//+------------------------------------------------------------------+
double OnTester() {
   // Diagnostic: write deal history count to a debug file
   {
      int debugHandle = FileOpen("phantom_mt5_tester_diagnostic.txt", FILE_WRITE | FILE_TXT | FILE_ANSI, ' ');
      if(debugHandle != INVALID_HANDLE) {
         if(HistorySelect(0, TimeCurrent() + 86400)) {
            int dealsTotal = HistoryDealsTotal();
            FileWrite(debugHandle, StringFormat("HistorySelect succeeded. HistoryDealsTotal=%d", dealsTotal));
         } else {
            FileWrite(debugHandle, StringFormat("HistorySelect FAILED. GetLastError=%d", GetLastError()));
         }
         FileClose(debugHandle);
      }
   }
   
   ExportTesterTrades();

   // Custom max metric: favor profitable runs with controlled drawdown.
   double profit = TesterStatistics(STAT_PROFIT);
   double ddRelPct = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   double pf = TesterStatistics(STAT_PROFIT_FACTOR);
   double trades = TesterStatistics(STAT_TRADES);

   // Penalize very low-trade configurations during optimization.
   if(trades < 5.0) {
      return -1000000.0 + trades;
   }

   if(ddRelPct <= 0.0) ddRelPct = 0.01;
   if(pf <= 0.0) pf = 0.01;

   // Score = (profit / drawdown%) * capped profit factor multiplier.
   double pfMult = MathMin(pf, 5.0);
   double score = (profit / ddRelPct) * pfMult;
   return score;
}
//+------------------------------------------------------------------+
//| GetEffectiveZoneTolerance()                                       |
//+------------------------------------------------------------------+
double GetEffectiveZoneTolerance() {
   return InpZoneTolerance;
}