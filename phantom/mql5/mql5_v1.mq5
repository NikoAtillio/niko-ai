//+------------------------------------------------------------------+
//|                                          Phantom_P2_US100_B.mq5  |
//|                                    Multi-Timeframe Zone Strategy  |
//|                                             US100 Scenario B      |
//+------------------------------------------------------------------+
#property copyright "Phantom P2 MT5"
#property version   "1.00"
#property description "Multi-Timeframe Zone-Based Strategy for US100"
#property description "Scenario B - High Risk Profile"

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
input bool     InpPeakSessionBoost = true;            // Enable 1.2x size during peak hours (14-17 UTC)

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
input double   InpRiskPercent = 1.4;                 // Risk per trade (% of capital)
input double   InpATRStopMult = 1.5;                 // Stop loss (H4 ATR multiplier)
input double   InpTPMult = 1.3;                      // Take profit (R multiple)
input double   InpTrailATRMult = 0.8;                // Trailing stop (H4 ATR multiplier)
input double   InpBreakevenR = 0.8;                  // Move stop to BE at this R
input int      InpMaxConcurrent = 3;                 // Max positions per 4H window
input int      InpCooldownMin = 20;                  // Cooldown between entries (minutes)
input int      InpLockoutMin = 60;                   // Lockout after loss (minutes)
input int      InpCircuitBreakerLosses = 5;          // Consecutive losses to trigger pause
input int      InpCircuitBreakerHours = 24;          // Pause duration (hours)

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
input int      InpBrokerUTCOffset = 2;               // Broker time = UTC + offset
input bool     InpAutoUTCOffset = true;              // Auto-switch between winter/summer offsets
input int      InpWinterUTCOffset = 2;               // Winter offset (Nov-Mar)
input int      InpSummerUTCOffset = 3;               // Summer offset (Mar-Nov)

// --- Development ---
input bool     InpEnableDebugPrint = false;           // Enable debug output
input bool     InpEnableVisuals = true;               // Draw zones on chart

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
   double     entry_price;
   double     stop_price;
   double     tp_price;
   double     initial_risk;
   double     atr_entry;      // H4 ATR at entry
   bool       be_triggered;
   int        direction;      // 1 = long, -1 = short
};
SPositionMeta m_pos_meta[];

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

// Zone colors
color         m_demandColor = clrDodgerBlue;
color         m_supplyColor = clrTomato;

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
   ArrayResize(m_pos_meta, 0);
   ArrayResize(m_entry_times_utc, 0);
   
   // Build initial zones
   BuildH4Zones();
   
   // Set timer for periodic zone refresh
   EventSetTimer(300); // Refresh zones every 5 minutes
   
   Print("Phantom P2 US100 Scenario B initialized successfully");
   Print("Symbol: ", Symbol(), " | Risk: ", InpRiskPercent, "% | ATR Stop: ", InpATRStopMult, "x");
   
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
   
   // Refresh zones periodically
   static datetime lastZoneRefresh = 0;
   if(TimeCurrent() - lastZoneRefresh > 300) { // Every 5 minutes
      BuildH4Zones();
      lastZoneRefresh = TimeCurrent();
   }
   
   // Check for exits first
   ManageOpenPositions();
   
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
   
   // Get H4 data
   int bars = InpZoneLookback + (InpPivotBars * 2) + 50;
   double highs[], lows[];
   datetime times[];
   
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
   
   // Calculate confirmation time
   int confirmMinutes = InpMinConfirmBars * PeriodSeconds(InpConfirmTF) / 60;
   m_zones[size].confirmed_at = confirmedUtc + confirmMinutes * 60;
   m_zones[size].confirmed = (ToUTC(TimeCurrent()) >= m_zones[size].confirmed_at);
   
   m_zoneCount++;
}

//+------------------------------------------------------------------+
//| Manage open positions (trailing, breakeven, exits)               |
//+------------------------------------------------------------------+
void ManageOpenPositions() {
   double bid = SymbolInfoDouble(Symbol(), SYMBOL_BID);
   double ask = SymbolInfoDouble(Symbol(), SYMBOL_ASK);
   datetime barTime = iTime(Symbol(), PERIOD_M5, 1);
   double barClose = iClose(Symbol(), PERIOD_M5, 1);
   double barHigh = iHigh(Symbol(), PERIOD_M5, 1);
   double barLow = iLow(Symbol(), PERIOD_M5, 1);
   datetime barTimeUtc = ToUTC(barTime);
   
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
               if(newTrail > stopPrice) {
                  stopPrice = newTrail;
               }
            } else {
               double newTrail = barClose + trailDistance;
               if(newTrail < stopPrice) {
                  stopPrice = newTrail;
               }
            }
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
         
         if(exitNow) {
            m_trade.PositionClose(ticket);
         }
      }
   }
   CleanPositionMeta();
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
   if(!CanTrade()) return;
   
   datetime barTime = iTime(Symbol(), PERIOD_M5, 1);
   datetime barTimeUtc = ToUTC(barTime);
   double signalPrice = iClose(Symbol(), PERIOD_M5, 1);
   
   // Get H4 ATR
   double h4ATR = GetATRAtTime(PERIOD_H4, m_handleH4ATR, barTime);
   if(h4ATR <= 0) return;
   
   // Rolling window filter (UTC)
   datetime windowStartUtc = barTimeUtc - (InpZoneLookback * PeriodSeconds(PERIOD_H4));
   
   // Scan zones for potential entries
   for(int i = 0; i < m_zoneCount; i++) {
      if(m_zones[i].time < windowStartUtc) continue;
      if(m_zones[i].time >= barTimeUtc) continue;
      if(!m_zones[i].confirmed && barTimeUtc < m_zones[i].confirmed_at) {
         continue;
      }
      
      // Zone proximity check
      double zoneDist = MathAbs(signalPrice - m_zones[i].price) / m_zones[i].price;
      if(zoneDist > InpZoneTolerance) continue;
      
      // Chasing filter (M15 ATR)
      double m15ATR = GetATRAtTime(PERIOD_M15, m_handleM15ATR, barTime);
      if(m15ATR > 0) {
         if(MathAbs(signalPrice - m_zones[i].price) > InpChaseFilterATR * m15ATR) {
            continue; // Too far, skip
         }
      }
      
      // Bounce filter
      if(m_zones[i].direction == 1) { // Long/demand zone
         if(signalPrice < m_zones[i].price * (1 - InpZoneTolerance)) continue; // Broke below
      } else { // Short/supply zone
         if(signalPrice > m_zones[i].price * (1 + InpZoneTolerance)) continue; // Broke above
      }
      
      // Session filter
      double sessionMult = GetSessionMultiplier();
      if(sessionMult <= 0) continue;
      
      // Cluster cap
      if(!CheckClusterCap(barTimeUtc)) continue;
      
      // Daily regime
      string regime = GetDailyRegime(barTime);
      double regimeMult = GetRegimeMultiplier(regime, m_zones[i].direction);
      
      // Multi-timeframe scoring
      int h4Score = GetTFScoreAtTime(PERIOD_H4, m_zones[i].direction, barTime);
      int h1Score = GetTFScoreAtTime(PERIOD_H1, m_zones[i].direction, barTime);
      int ltfScore = GetTFScoreAtTime(PERIOD_M5, m_zones[i].direction, barTime);
      
      if(h4Score < InpH4ScoreMin || h1Score < InpH1ScoreMin || ltfScore < InpLTFScoreMin) {
         continue;
      }
      
      int totalScore = h4Score + h1Score + ltfScore;
      
      // Direction score offset
      int effectiveScoreMin = InpScoreMin;
      if(m_zones[i].direction == 1) { // Long
         effectiveScoreMin += InpLongScoreOffset;
      }
      
      if(totalScore < effectiveScoreMin) continue;
      if(ltfScore > InpLTFScoreCap) continue;
      
      // Confidence multiplier
      double confMult = CalculateConfidenceMultiplier(barTimeUtc);
      
      // Calculate position size and execute
      ExecuteEntry(m_zones[i], h4ATR, sessionMult, regimeMult, confMult, totalScore, barTime, barTimeUtc, signalPrice);
      
      break; // One entry per bar
   }
}

//+------------------------------------------------------------------+
//| Check if trading is allowed                                      |
//+------------------------------------------------------------------+
bool CanTrade() {
   // Circuit breaker check
   if(TimeCurrent() < m_circuitBreakerUntil) {
      return false;
   }
   
   // Max concurrent positions check
   int currentPositions = CountPositions();
   if(currentPositions >= InpMaxConcurrent) {
      return false;
   }
   
   // Cooldown check
   if(m_lastEntryTime > 0) {
      if(TimeCurrent() - m_lastEntryTime < InpCooldownMin * 60) {
         return false;
      }
   }
   
   // Lockout after loss check
   if(m_lastLossExitTime > 0) {
      if(TimeCurrent() - m_lastLossExitTime < InpLockoutMin * 60) {
         return false;
      }
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
double GetSessionMultiplier() {
   MqlDateTime utc;
   GetUTCTime(utc);
   
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
   if(shift < 0) return 0;
   if(CopyClose(Symbol(), tf, shift, 1, close) < 1) return 0;
   if(CopyBuffer(handleEMA20, 0, shift, 1, ema20) < 1) return 0;
   if(CopyBuffer(handleEMA50, 0, shift, 1, ema50) < 1) return 0;
   if(CopyBuffer(handleRSI, 0, shift, 1, rsi) < 1) return 0;
   
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
   
   return score;
}

//+------------------------------------------------------------------+
//| Calculate confidence multiplier                                  |
//+------------------------------------------------------------------+
double CalculateConfidenceMultiplier(datetime entryUtc) {
   int entriesInWindow = CountEntriesInWindow(entryUtc);
   return (entriesInWindow == 0) ? InpConfidenceMult : 1.0;
}

//+------------------------------------------------------------------+
//| Execute entry                                                    |
//+------------------------------------------------------------------+
void ExecuteEntry(SZone &zone, double h4ATR, double sessionMult,
                  double regimeMult, double confMult, int totalScore,
                  datetime barTime, datetime barTimeUtc, double signalPrice) {
   double entryPrice = ApplyExecutionAdjustment(signalPrice, zone.direction, true);
   ENUM_ORDER_TYPE orderType = (zone.direction == 1) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   
   // Calculate stop and take profit
   double stopDistance = InpATRStopMult * h4ATR;
   double stopPrice = (zone.direction == 1)
      ? entryPrice - stopDistance
      : entryPrice + stopDistance;
   double takeProfit = (zone.direction == 1)
      ? entryPrice + (InpTPMult * stopDistance)
      : entryPrice - (InpTPMult * stopDistance);
   
   // Calculate position size
   double accountEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskAmount = accountEquity * (InpRiskPercent / 100.0);
   double initialRisk = MathAbs(entryPrice - stopPrice);
   if(initialRisk <= 0) initialRisk = stopDistance;
   
   double sizeMultiplier = sessionMult * regimeMult * confMult;
   double volume = (riskAmount / initialRisk) * sizeMultiplier;
   
   // Normalize volume
   double lotStep = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_STEP);
   volume = MathFloor(volume / lotStep) * lotStep;
   
   double minLot = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MAX);
   
   if(volume < minLot) volume = minLot;
   if(volume > maxLot) volume = maxLot;
   
   // Prepare comment with metadata
   string comment = StringFormat("P2_B|%s|S=%d|ATR=%.5f|REG=%s|CONF=%.1f",
                                (zone.direction == 1) ? "LONG" : "SHORT",
                                totalScore,
                                h4ATR,
                                GetDailyRegime(barTime),
                                confMult);
   
   // Execute trade (manual stop/TP management)
   m_trade.PositionOpen(Symbol(), orderType, volume, entryPrice, 0.0, 0.0, comment);
   
   if(m_trade.ResultRetcode() == TRADE_RETCODE_DONE) {
      ulong ticket = 0;
      if(PositionSelect(Symbol())) {
         ticket = (ulong)PositionGetInteger(POSITION_TICKET);
      }
      if(ticket == 0) {
         return;
      }
      int metaIndex = ArraySize(m_pos_meta);
      ArrayResize(m_pos_meta, metaIndex + 1);
      m_pos_meta[metaIndex].ticket = ticket;
      m_pos_meta[metaIndex].entry_time = barTime;
      m_pos_meta[metaIndex].entry_time_utc = barTimeUtc;
      m_pos_meta[metaIndex].entry_price = entryPrice;
      m_pos_meta[metaIndex].stop_price = stopPrice;
      m_pos_meta[metaIndex].tp_price = takeProfit;
      m_pos_meta[metaIndex].initial_risk = initialRisk;
      m_pos_meta[metaIndex].atr_entry = h4ATR;
      m_pos_meta[metaIndex].be_triggered = false;
      m_pos_meta[metaIndex].direction = zone.direction;
      
      RegisterEntryTime(barTimeUtc);
      m_lastEntryTime = barTime;
      
      if(InpEnableDebugPrint) {
         Print("Entry executed: ", (zone.direction == 1) ? "LONG" : "SHORT",
               " | Price: ", entryPrice,
               " | SL: ", stopPrice,
               " | TP: ", takeProfit,
               " | Volume: ", volume,
               " | Score: ", totalScore);
      }
   } else {
      Print("Entry failed: ", m_trade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
//| Handle trade events (for circuit breaker tracking)               |
//+------------------------------------------------------------------+
void OnTrade() {
   // This would need history deal checking
   // For simplicity, circuit breaker logic can be implemented in a 
   // more sophisticated version using OnTradeTransaction
}

//+------------------------------------------------------------------+
//| Draw zones on chart                                              |
//+------------------------------------------------------------------+
void DrawZones() {
   if(!InpEnableVisuals) return;
   
   // Clear old zone objects
   ObjectsDeleteAll(0, "Zone_");
   
   for(int i = 0; i < m_zoneCount; i++) {
      string objName = StringFormat("Zone_%d", i);
      color zoneColor = (m_zones[i].direction == 1) ? m_demandColor : m_supplyColor;
      
      // Draw horizontal line
      if(!ObjectCreate(0, objName, OBJ_HLINE, 0, 0, m_zones[i].price)) {
         continue;
      }
      
      ObjectSetInteger(0, objName, OBJPROP_COLOR, zoneColor);
      ObjectSetInteger(0, objName, OBJPROP_STYLE, 
                      m_zones[i].confirmed ? STYLE_SOLID : STYLE_DASH);
      ObjectSetInteger(0, objName, OBJPROP_WIDTH, 2);
      
      // Add zone label
      string labelName = objName + "_label";
      string labelText = StringFormat("%s Zone %.2f [%s]",
                                     (m_zones[i].direction == 1) ? "Demand" : "Supply",
                                     m_zones[i].price,
                                     m_zones[i].confirmed ? "Active" : "Pending");
      
      ObjectCreate(0, labelName, OBJ_TEXT, 0, TimeCurrent(), m_zones[i].price);
      ObjectSetString(0, labelName, OBJPROP_TEXT, labelText);
      ObjectSetInteger(0, labelName, OBJPROP_COLOR, zoneColor);
      ObjectSetInteger(0, labelName, OBJPROP_FONTSIZE, 8);
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
      if(!PositionSelectByTicket(m_pos_meta[i].ticket)) {
         ArrayRemove(m_pos_meta, i, 1);
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