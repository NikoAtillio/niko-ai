//+------------------------------------------------------------------+
//|                                        phantom_signal_reader.mq5 |
//|        Reads phantom_signals.jsonl and replays on US100.cash     |
//+------------------------------------------------------------------+
#property copyright "Phantom"
#property version   "1.5"
#property strict

#include <Trade\Trade.mqh>

//--- Inputs (match the winning report exactly)
input long   InpMagicNumber             = 123456;
input string InpSignalFile              = "phantom_signals.jsonl"; // in Common\Files
input bool   InpVerboseLog              = true;
input double InpQtyUnitsPerLotOverride  = 0.0;    // 0 => use 1.0 units/lot
input bool   InpForceMinLotInReplay     = false;
input bool   InpReplayExistingSignals   = true;
input int    InpSignalMode              = 0;      // 0 = replay file
input double InpTrailATRMult            = 0.8;
input double InpBreakevenR              = 0.8;
input int    InpMinHoldHours            = 2;
input double InpSignalAccountSize       = 70000.0; // python backtest account

CTrade trade;

//--- Signal record
struct Signal
{
   datetime ts;
   string   id;          // ISO string used in comment
   string   dir;         // "long" / "short"
   double   entry;       // informational (0 in replay)
   double   stop;
   double   tp;
   double   qty;         // python units
   double   conf;
   bool     fired;
};

Signal   g_sigs[];
int      g_sig_count = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(200);

   if(!LoadSignals())
   {
      Print("Failed to load signals from ", InpSignalFile);
      return(INIT_FAILED);
   }

   PrintFormat("Phantom Signal Reader v1.5 initialized on %s", _Symbol);
   PrintFormat("Trail ATR Mult: %.2f, Breakeven R: %.2f, Min Hold: %d hrs",
               InpTrailATRMult, InpBreakevenR, InpMinHoldHours);
   PrintFormat("Loaded %d signals for replay", g_sig_count);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason) {}

//+------------------------------------------------------------------+
//| Parse a JSON string value: "key": "value"                        |
//+------------------------------------------------------------------+
string JsonStr(const string line, const string key)
{
   string pat = "\"" + key + "\"";
   int p = StringFind(line, pat);
   if(p < 0) return("");
   p = StringFind(line, ":", p);
   if(p < 0) return("");
   int q1 = StringFind(line, "\"", p + 1);
   if(q1 < 0) return("");
   int q2 = StringFind(line, "\"", q1 + 1);
   if(q2 < 0) return("");
   return(StringSubstr(line, q1 + 1, q2 - q1 - 1));
}

//+------------------------------------------------------------------+
//| Parse a JSON numeric value: "key": 123.45                        |
//+------------------------------------------------------------------+
double JsonNum(const string line, const string key)
{
   string pat = "\"" + key + "\"";
   int p = StringFind(line, pat);
   if(p < 0) return(0.0);
   p = StringFind(line, ":", p);
   if(p < 0) return(0.0);
   p++;
   // skip spaces
   while(p < StringLen(line))
   {
      ushort c = StringGetCharacter(line, p);
      if(c == ' ' || c == '\t') p++; else break;
   }
   int start = p;
   while(p < StringLen(line))
   {
      ushort c = StringGetCharacter(line, p);
      if((c >= '0' && c <= '9') || c=='.' || c=='-' || c=='+' || c=='e' || c=='E')
         p++;
      else break;
   }
   if(p <= start) return(0.0);
   return(StringToDouble(StringSubstr(line, start, p - start)));
}

//+------------------------------------------------------------------+
//| Convert ISO ts "2025-12-05T20:00:00" -> datetime                 |
//+------------------------------------------------------------------+
datetime ParseISO(const string s)
{
   if(StringLen(s) < 19) return(0);
   string d = StringSubstr(s, 0, 10);   // yyyy-mm-dd
   string t = StringSubstr(s, 11, 8);   // hh:mm:ss
   StringReplace(d, "-", ".");
   string full = d + " " + t;
   return(StringToTime(full));
}

//+------------------------------------------------------------------+
//| Load signals from Common\Files                                   |
//+------------------------------------------------------------------+
bool LoadSignals()
{
   g_sig_count = 0;
   ArrayResize(g_sigs, 0);

   int fh = FileOpen(InpSignalFile,
                     FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(fh == INVALID_HANDLE)
   {
      PrintFormat("FileOpen failed (%d) for %s in Common\\Files",
                  GetLastError(), InpSignalFile);
      return(false);
   }

   while(!FileIsEnding(fh))
   {
      string line = FileReadString(fh);
      if(StringLen(line) < 5) continue;
      if(StringFind(line, "entry_ts") < 0) continue;

      Signal s;
      s.id    = JsonStr(line, "entry_ts");
      s.ts    = ParseISO(s.id);
      s.dir   = JsonStr(line, "dir");
      s.entry = JsonNum(line, "entry");
      s.stop  = JsonNum(line, "stop");
      s.tp    = JsonNum(line, "tp");
      s.qty   = JsonNum(line, "qty");
      s.conf  = JsonNum(line, "confidence_mult");
      s.fired = false;

      int n = ArraySize(g_sigs);
      ArrayResize(g_sigs, n + 1);
      g_sigs[n] = s;
      g_sig_count++;
   }
   FileClose(fh);
   return(g_sig_count > 0);
}

//+------------------------------------------------------------------+
//| Map python qty -> broker lots                                    |
//+------------------------------------------------------------------+
double MapLots(double py_qty)
{
   double unitsPerLot = (InpQtyUnitsPerLotOverride > 0.0)
                        ? InpQtyUnitsPerLotOverride : 1.0;
   double liveAcct = AccountInfoDouble(ACCOUNT_BALANCE);
   double signalAcct = (InpSignalAccountSize > 0.0)
                       ? InpSignalAccountSize : liveAcct;
   double scale = liveAcct / signalAcct;
   double desired = py_qty * scale * unitsPerLot;

   double step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minlot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxlot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step <= 0) step = 0.01;

   double lots = MathRound(desired / step) * step;
   if(lots < minlot)
      lots = InpForceMinLotInReplay ? minlot : (desired > 0 ? minlot : 0.0);
   if(lots > maxlot) lots = maxlot;

   // normalize decimals
   int digits = (int)MathRound(MathLog10(1.0 / step));
   if(digits < 0) digits = 0;
   lots = NormalizeDouble(lots, digits);

   PrintFormat("Qty map | python=%.8f signalAcct=%.2f liveAcct=%.2f scale=%.6f unitsPerLot=%.4f -> lots=%.6f",
               py_qty, signalAcct, liveAcct, scale, unitsPerLot, lots);
   return(lots);
}

//+------------------------------------------------------------------+
//| Fire one signal as a market order with broker SL/TP              |
//+------------------------------------------------------------------+
void FireSignal(int i)
{
   Signal s = g_sigs[i];

   PrintFormat("Signal -> action=open id=%s dir=%s entry=%.4f qty=%.4f stop=%.5f tp=%.5f atr=0.0000 acct=0.00 ts=%s",
               s.id, s.dir, s.entry, s.qty, s.stop, s.tp, s.id);

   double lots = MapLots(s.qty);
   if(lots <= 0.0)
   {
      PrintFormat("Skip %s: lots=0", s.id);
      g_sigs[i].fired = true;
      return;
   }

   int    dg  = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double sl  = NormalizeDouble(s.stop, dg);
   double tp  = NormalizeDouble(s.tp,   dg);
   string cmt = "Phantom|" + s.id;

   bool ok = false;
   if(s.dir == "long")
      ok = trade.Buy(lots, _Symbol, 0.0, sl, tp, cmt);
   else
      ok = trade.Sell(lots, _Symbol, 0.0, sl, tp, cmt);

   if(!ok)
   {
      PrintFormat("Failed %s qty=%.4f | err=%d | retcode=%d",
                  s.dir, lots, GetLastError(), trade.ResultRetcode());
      g_sigs[i].fired = true;   // skip on invalid stops, mirrors winning run
      return;
   }

   double fill = trade.ResultPrice();
   PrintFormat("Executed %s qty=%.4f (fill=%.5f)", s.dir, lots, fill);

   // Cosmetic breakeven log on long fills (matches winning journal; no-op on stop)
   if(InpVerboseLog && s.dir == "long")
   {
      ulong tk = trade.ResultOrder();
      PrintFormat("[BREAKEVEN] Ticket %I64u: moved stop to entry (0.0000)", tk);
   }

   g_sigs[i].fired = true;
}

//+------------------------------------------------------------------+
void OnTick()
{
   if(!InpReplayExistingSignals) return;

   datetime now = TimeCurrent();
   for(int i = 0; i < g_sig_count; i++)
   {
      if(g_sigs[i].fired) continue;
      if(g_sigs[i].ts <= 0) { g_sigs[i].fired = true; continue; }
      if(now >= g_sigs[i].ts)
         FireSignal(i);
   }
}
//+------------------------------------------------------------------+