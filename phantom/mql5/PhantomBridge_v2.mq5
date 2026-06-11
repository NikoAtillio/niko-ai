//+------------------------------------------------------------------+
//|                                          PhantomBridge_v2.mq5     |
//|        Faithful MT5 translator for the PHANTOM p2 signal stream  |
//|  Reads phantom_signals.jsonl (FILE_COMMON) and replays actions:  |
//|  meta / open / modify / close / heartbeat                        |
//+------------------------------------------------------------------+
#property strict
#property description "PHANTOM p2 bridge - reads phantom_signals.jsonl and mirrors Python signals"

#include <Trade/Trade.mqh>
CTrade trade;

//==================== FORWARD DECLARATIONS =========================
void   LogCSV(const string line);
void   ProcessLine(const string raw);
void   Notify(const string title, const string body);
double NormalizePrice(const double p);
double NormalizeLots(double lots);
int    FindId(const string id);
void   UnmapId(const string id);
bool   StampModelMode();
void   DetectStraddles(const datetime bar_time);

//==================== INPUTS =======================================
input string  InpSignalFile          = "phantom_signals.jsonl"; // file in Common\Files
input long    InpMagicNumber         = 920025;                  // unique per account/instrument
input string  InpSymbolOverride      = "US100";                // live/demo target symbol
input bool    InpReplayMode          = true;                    // true=backtest replay, false=live polling
input bool    InpReplayUseSignalPricing = true;                 // in replay, use signal qty/entry/exit for parity ledger

// --- broker mode ---
enum ENUM_BROKER_MODE { BROKER_AUTO=0, BROKER_FTMO=1, BROKER_CASH=2 };
input ENUM_BROKER_MODE InpBrokerMode = BROKER_AUTO;

// --- cash-account guardrails (GBP, only enforced in CASH mode) ---
input double  InpMaxDailyLoss        = 500.0;                   // flatten+halt for the day
input double  InpMaxOverallLoss      = 1000.0;                  // flatten+halt (see hard-stop toggle)
input double  InpProfitTarget        = 500.0;                   // log only, keep trading
input bool    InpHardStopOnMaxLoss   = false;                   // true = disable permanently on max loss

// --- lot scaling ---
input double  InpMetaAccountFallback = 5000.0;                  // used only if a signal lacks signal_account_size
input double  InpMaxLots             = 50.0;                    // hard safety cap
input double  InpMinLots             = 0.01;

// --- notifications ---
input bool    InpNotifyPush          = true;                    // SendNotification (mobile)
input bool    InpNotifyEmail         = false;                   // SendMail (needs SMTP)
input bool    InpNotifyAlert         = true;                    // Alert popup + Print

// --- logging ---
input bool    InpLogToCSV            = true;
input string  InpLogFile             = "phantom_bridge_log.csv";
input bool    InpEnableStraddleAudit = true;                    // log-only straddle detector

//==================== STATE ========================================
string   g_symbol;
int      g_digits;
double   g_point;
double   g_volstep, g_volmin, g_volmax;
int      g_stopslevel;

ulong    g_filepos     = 0;     // byte offset already consumed (live polling)
int      g_lineidx     = 0;     // lines consumed (replay)
bool     g_meta_seen   = false;
double   g_meta_acct   = 5000.0;
ENUM_BROKER_MODE g_mode = BROKER_CASH;

// guardrail state
bool     g_halted_today   = false;
bool     g_disabled_perm  = false;
datetime g_halt_serverday = 0;
double   g_day_start_equity = 0.0;
datetime g_current_day    = 0;

// signal_id -> position ticket map
string   g_ids[];
ulong    g_tickets[];
double   g_last_sl[];      // last applied SL per mapped id (dedupe)
double   g_sig_entry[];    // signal entry price per id (replay parity)
double   g_sig_qty[];      // signal qty per id (replay parity)
int      g_sig_dir[];      // +1 long, -1 short (replay parity)

double   g_synth_net = 0.0;
int      g_synth_trades = 0;
int      g_synth_wins = 0;

datetime g_last_bar = 0;

// replay event store (loaded once)
string   g_replay_raw[];
datetime g_replay_ts[];
int      g_replay_next = 0;
bool     g_replay_loaded = false;

// pending replay TP closes: arm on close(reason=tp), then watch ticks in-bar
string   g_pending_ids[];
ulong    g_pending_tickets[];
double   g_pending_tp[];
double   g_pending_sl[];
int      g_pending_dir[];      // +1 long, -1 short
datetime g_pending_expiry[];   // next bar open fallback

// seen open IDs to enforce one-shot execution even if the stream has duplicates
string   g_open_once_ids[];

bool HasOpenFired(const string id)
{
   for(int i=0; i<ArraySize(g_open_once_ids); i++)
      if(g_open_once_ids[i] == id) return true;
   return false;
}

void MarkOpenFired(const string id)
{
   if(id == "" || HasOpenFired(id)) return;
   int n = ArraySize(g_open_once_ids);
   ArrayResize(g_open_once_ids, n + 1);
   g_open_once_ids[n] = id;
}

int FindPending(const string id)
{
   for(int i=0; i<ArraySize(g_pending_ids); i++)
      if(g_pending_ids[i] == id) return i;
   return -1;
}

void RemovePendingAt(const int idx)
{
   int last = ArraySize(g_pending_ids) - 1;
   if(idx < 0 || idx > last) return;

   g_pending_ids[idx]     = g_pending_ids[last];
   g_pending_tickets[idx] = g_pending_tickets[last];
   g_pending_tp[idx]      = g_pending_tp[last];
   g_pending_sl[idx]      = g_pending_sl[last];
   g_pending_dir[idx]     = g_pending_dir[last];
   g_pending_expiry[idx]  = g_pending_expiry[last];

   ArrayResize(g_pending_ids, last);
   ArrayResize(g_pending_tickets, last);
   ArrayResize(g_pending_tp, last);
   ArrayResize(g_pending_sl, last);
   ArrayResize(g_pending_dir, last);
   ArrayResize(g_pending_expiry, last);
}

void ArmReplayTpClose(const string id, const ulong tk, const int dir_sig, const double tp_price, const double sl_price)
{
   int idx = FindPending(id);
   if(idx < 0){
      int n = ArraySize(g_pending_ids);
      ArrayResize(g_pending_ids, n + 1);
      ArrayResize(g_pending_tickets, n + 1);
      ArrayResize(g_pending_tp, n + 1);
      ArrayResize(g_pending_sl, n + 1);
      ArrayResize(g_pending_dir, n + 1);
      ArrayResize(g_pending_expiry, n + 1);
      idx = n;
   }

   g_pending_ids[idx] = id;
   g_pending_tickets[idx] = tk;
   g_pending_tp[idx] = tp_price;
   g_pending_sl[idx] = sl_price;
   g_pending_dir[idx] = dir_sig;
   g_pending_expiry[idx] = g_last_bar + PeriodSeconds(PERIOD_M5);

   LogCSV("CLOSE_TP_ARM;"+id+
          ";tp="+DoubleToString(tp_price,g_digits)+
          ";sl="+DoubleToString(sl_price,g_digits)+
          ";expiry="+TimeToString(g_pending_expiry[idx], TIME_DATE|TIME_SECONDS));
}

void ProcessPendingReplayTpCloses()
{
   if(!InpReplayMode) return;
   if(!InpReplayUseSignalPricing) return;

   for(int i=ArraySize(g_pending_ids)-1; i>=0; i--){
      string id = g_pending_ids[i];
      ulong tk = g_pending_tickets[i];

      if(!PositionSelectByTicket(tk)){
         LogCSV("CLOSE_TP_FILLED;"+id);
         UnmapId(id);
         RemovePendingAt(i);
         continue;
      }

      if(TimeCurrent() < g_pending_expiry[i]) continue;

      if(trade.PositionClose(tk)){
         LogCSV("CLOSE_TP_FALLBACK_MKT;"+id+
                ";fill="+DoubleToString(trade.ResultPrice(),g_digits));
         UnmapId(id);
      }
      else {
         LogCSV("CLOSE_TP_FALLBACK_MKT_FAIL;"+id+
                ";ret="+IntegerToString(trade.ResultRetcode())+
                ";"+trade.ResultRetcodeDescription());
      }

      RemovePendingAt(i);
   }
}

//==================== TESTER MODE STAMP ===========================
// MT5 does not expose a direct modelling enum in EA runtime.
// We stamp best-effort context so runs can be audited for trust level.
bool StampModelMode()
{
   bool in_tester = (bool)MQLInfoInteger(MQL_TESTER);
   if(!in_tester){
      LogCSV("MODEL_MODE;tester=false;mode=LIVE_OR_DEMO");
      return true;
   }

   MqlTick ticks[];
   int copied = CopyTicks(g_symbol, ticks, COPY_TICKS_ALL, 0, 32);
   bool has_ticks = (copied > 0);

   string mode = has_ticks ? "TICK_DRIVEN_LIKELY" : "UNKNOWN_OR_OHLC";
   LogCSV("MODEL_MODE;tester=true;copied_ticks="+IntegerToString(copied)+";mode="+mode);

   if(!has_ticks){
      LogCSV("MODEL_MODE_WARN;low_confidence_modelling;use_every_tick_real_for_straddle_trust");
      Print("WARNING: Low-confidence tester tick context. Use 'Every tick based on real ticks' for reliable TP/SL ordering.");
   }
   return has_ticks;
}

//==================== STRADDLE AUDIT (LOG-ONLY) ===================
// Detect bars where both armed TP and armed SL are within the same completed
// bar range. No fill override is applied; this is visibility only.
void DetectStraddles(const datetime bar_time)
{
   if(!InpEnableStraddleAudit) return;
   if(!InpReplayMode) return;
   if(!InpReplayUseSignalPricing) return;
   if(ArraySize(g_pending_ids) <= 0) return;

   double bhigh = iHigh(g_symbol, PERIOD_M5, 1);
   double blow  = iLow(g_symbol, PERIOD_M5, 1);
   if(bhigh <= 0.0 || blow <= 0.0 || bhigh < blow) return;

   for(int p=0; p<ArraySize(g_pending_ids); p++){
      string id = g_pending_ids[p];
      double tp = g_pending_tp[p];
      double sl = g_pending_sl[p];
      int dir = g_pending_dir[p];

      if(tp <= 0.0 || sl <= 0.0) continue;

      bool tp_in = (tp >= blow && tp <= bhigh);
      bool sl_in = (sl >= blow && sl <= bhigh);
      if(!(tp_in && sl_in)) continue;

      string d = (dir > 0) ? "long" : ((dir < 0) ? "short" : "unknown");
      LogCSV("STRADDLE_DETECTED;"+id+
             ";bar_ts="+TimeToString(bar_time, TIME_DATE|TIME_SECONDS)+
             ";bar_high="+DoubleToString(bhigh,g_digits)+
             ";bar_low="+DoubleToString(blow,g_digits)+
             ";tp="+DoubleToString(tp,g_digits)+
             ";sl="+DoubleToString(sl,g_digits)+
             ";dir="+d+
             ";policy_hint=sl_first");
   }
}

//==================== HELPERS ======================================
int FindId(const string id)
{
   for(int i=0;i<ArraySize(g_ids);i++) if(g_ids[i]==id) return i;
   return -1;
}

void MapId(const string id, const ulong ticket)
{
   int idx=FindId(id);
   if(idx<0){
      int n=ArraySize(g_ids);
      ArrayResize(g_ids,n+1);
      ArrayResize(g_tickets,n+1);
      ArrayResize(g_last_sl,n+1);
      ArrayResize(g_sig_entry,n+1);
      ArrayResize(g_sig_qty,n+1);
      ArrayResize(g_sig_dir,n+1);
      g_ids[n]=id;
      g_tickets[n]=ticket;
      g_last_sl[n]=0.0;
      g_sig_entry[n]=0.0;
      g_sig_qty[n]=0.0;
      g_sig_dir[n]=0;
   }
   else {
      g_tickets[idx]=ticket;
   }
}

void UnmapId(const string id)
{
   int idx=FindId(id);
   if(idx<0) return;
   int last=ArraySize(g_ids)-1;
   g_ids[idx]=g_ids[last];
   g_tickets[idx]=g_tickets[last];
   g_last_sl[idx]=g_last_sl[last];
   g_sig_entry[idx]=g_sig_entry[last];
   g_sig_qty[idx]=g_sig_qty[last];
   g_sig_dir[idx]=g_sig_dir[last];
   ArrayResize(g_ids,last);
   ArrayResize(g_tickets,last);
   ArrayResize(g_last_sl,last);
    ArrayResize(g_sig_entry,last);
    ArrayResize(g_sig_qty,last);
    ArrayResize(g_sig_dir,last);
}

double NormalizePrice(const double p){ return NormalizeDouble(p,g_digits); }

double MinStopDistance()
{
   double stop_dist = (g_stopslevel > 0) ? (g_stopslevel * g_point) : 0.0;
   int freeze_level = (int)SymbolInfoInteger(g_symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double freeze_dist = (freeze_level > 0) ? (freeze_level * g_point) : 0.0;
   return MathMax(stop_dist, freeze_dist);
}

double NormalizeLots(double lots)
{
   if(lots<=0) return 0.0;
   lots = MathMax(lots, g_volmin);
   lots = MathMin(lots, MathMin(g_volmax, InpMaxLots));
   double steps = MathRound(lots/g_volstep);
   lots = steps*g_volstep;
   if(lots < g_volmin) lots = g_volmin;
   return NormalizeDouble(lots, 2);
}

double ClampStopDistance(const double price, double sl, const bool is_long)
{
   double minDist = MinStopDistance();
   if(minDist<=0.0) return NormalizePrice(sl);
   if(is_long){ if(price-sl < minDist) sl = price-minDist; }
   else       { if(sl-price < minDist) sl = price+minDist; }
   return NormalizePrice(sl);
}

//==================== JSON (minimal flat parser) ===================
// Flat one-line JSON objects only (our schema). Returns "" if key absent.
string JGetStr(const string js, const string key)
{
   string pat="\""+key+"\"";
   int k=StringFind(js,pat);
   if(k<0) return "";
   int c=StringFind(js,":",k);
   if(c<0) return "";
   int i=c+1;
   while(i<StringLen(js) && (StringGetCharacter(js,i)==' ')) i++;
   if(i>=StringLen(js)) return "";
   ushort ch=StringGetCharacter(js,i);
   if(ch=='\"'){
      int e=StringFind(js,"\"",i+1);
      if(e<0) return "";
      return StringSubstr(js,i+1,e-(i+1));
   }
   else {
      int e=i;
      while(e<StringLen(js)){
         ushort cc=StringGetCharacter(js,e);
         if(cc==','||cc=='}'||cc==' ') break;
         e++;
      }
      return StringSubstr(js,i,e-i);
   }
}

double JGetNum(const string js,const string key,const double def=0.0)
{
   string s=JGetStr(js,key);
   if(s=="") return def;
   return StringToDouble(s);
}

datetime ParseSignalTime(const string js)
{
   string ts = JGetStr(js, "signal_ts");
   if(ts == "") ts = JGetStr(js, "entry_ts");
   if(ts == "") return (datetime)0;
   StringReplace(ts, "T", " ");
   int z = StringFind(ts, "Z");
   if(z >= 0) ts = StringSubstr(ts, 0, z);
   return StringToTime(ts);
}

bool LoadAllEvents()
{
   if(g_replay_loaded) return true;

   int h=FileOpen(InpSignalFile, FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h==INVALID_HANDLE) return false;

   ArrayResize(g_replay_raw, 0);
   ArrayResize(g_replay_ts, 0);
   g_replay_next = 0;

   while(!FileIsEnding(h)){
      string line = FileReadString(h);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringLen(line) < 2) continue;

      int n = ArraySize(g_replay_raw);
      ArrayResize(g_replay_raw, n + 1);
      ArrayResize(g_replay_ts, n + 1);
      g_replay_raw[n] = line;
      g_replay_ts[n] = ParseSignalTime(line);
   }

   FileClose(h);
   g_replay_loaded = true;
   LogCSV("LOAD_EVENTS;count=" + IntegerToString(ArraySize(g_replay_raw)));
   PrintFormat("PhantomBridge replay loaded %d events", ArraySize(g_replay_raw));
   return true;
}

void ReplayDueEvents(const datetime bar_time)
{
   if(!g_replay_loaded && !LoadAllEvents()) return;

   static datetime s_last_valid_ts = 0;

   while(g_replay_next < ArraySize(g_replay_raw)){
      datetime ts = g_replay_ts[g_replay_next];

      if(ts <= 0){
         // Undated events inherit prior valid event time so they cannot jump ahead.
         ts = s_last_valid_ts;
      }
      else {
         s_last_valid_ts = ts;
      }

      if(ts > bar_time) break;
      ProcessLine(g_replay_raw[g_replay_next]);
      g_replay_next++;
   }
}

//==================== NOTIFY =======================================
void Notify(const string title, const string body)
{
   string msg=title+" | "+body;
   if(InpNotifyAlert){
      Alert(msg);
      Print(msg);
   }
   else {
      Print(msg);
   }
   if(InpNotifyPush)  SendNotification(StringSubstr(msg,0,255));
   if(InpNotifyEmail) SendMail(title, body);
}

//==================== CSV LOG ======================================
void LogCSV(const string line)
{
   if(!InpLogToCSV) return;
   int h=FileOpen(InpLogFile, FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ';');
   if(h==INVALID_HANDLE) return;
   FileSeek(h,0,SEEK_END);
   FileWrite(h, TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS), line);
   FileClose(h);
}

//==================== BROKER MODE DETECT ===========================
ENUM_BROKER_MODE DetectMode()
{
   if(InpBrokerMode!=BROKER_AUTO) return InpBrokerMode;
   string co=AccountInfoString(ACCOUNT_COMPANY);
   string sv=AccountInfoString(ACCOUNT_SERVER);
   string s=co+" "+sv;
   StringToLower(s);
   if(StringFind(s,"ftmo")>=0) return BROKER_FTMO;
   return BROKER_CASH;
}

//==================== GUARDRAILS (cash mode) =======================
datetime ServerDay()
{
   datetime t=TimeCurrent();
   MqlDateTime st;
   TimeToStruct(t,st);
   st.hour=0;
   st.min=0;
   st.sec=0;
   return StructToTime(st);
}

void ResetDayIfNeeded()
{
   datetime d=ServerDay();
   if(d!=g_current_day){
      g_current_day=d;
      g_day_start_equity=AccountInfoDouble(ACCOUNT_EQUITY);
      if(g_halted_today && g_halt_serverday!=d){
         g_halted_today=false;
         Notify("PHANTOM resumed","New server day "+TimeToString(d,TIME_DATE)+". Daily halt cleared; trading resumed.");
      }
   }
}

void FlattenAll(const string why)
{
   for(int i=PositionsTotal()-1;i>=0;i--){
      ulong tk=PositionGetTicket(i);
      if(tk==0) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpMagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL)!=g_symbol) continue;
      trade.PositionClose(tk);
   }
   LogCSV("FLATTEN;"+why);
}

// returns true if trading is currently blocked
bool GuardrailBlock()
{
   if(g_mode!=BROKER_CASH) return g_disabled_perm; // FTMO handles its own
   if(g_disabled_perm) return true;

   ResetDayIfNeeded();
   if(g_halted_today) return true;

   double eq   = AccountInfoDouble(ACCOUNT_EQUITY);
   double bal  = AccountInfoDouble(ACCOUNT_BALANCE);
   double dayPnL = eq - g_day_start_equity;

   // overall loss vs initial deposit baseline (use balance start of run)
   static double s_baseline=0.0;
   if(s_baseline==0.0) s_baseline=bal;
   double overall = eq - s_baseline;

   if(InpProfitTarget>0 && dayPnL>=InpProfitTarget){
      LogCSV("PROFIT_TARGET;dayPnL="+DoubleToString(dayPnL,2));
   }

   if(InpMaxOverallLoss>0 && overall<=-InpMaxOverallLoss){
      FlattenAll("MAX_OVERALL_LOSS");
      if(InpHardStopOnMaxLoss){
         g_disabled_perm=true;
         Notify("PHANTOM DISABLED","Max overall loss -"+DoubleToString(InpMaxOverallLoss,2)+" GBP hit. EA permanently disabled.");
      }
      else {
         g_halted_today=true;
         g_halt_serverday=ServerDay();
         Notify("PHANTOM halted","Max overall loss -"+DoubleToString(InpMaxOverallLoss,2)+" GBP hit. Flattened & halted; auto-resume next server day.");
      }
      return true;
   }

   if(InpMaxDailyLoss>0 && dayPnL<=-InpMaxDailyLoss){
      FlattenAll("MAX_DAILY_LOSS");
      g_halted_today=true;
      g_halt_serverday=ServerDay();
      Notify("PHANTOM halted","Max daily loss -"+DoubleToString(InpMaxDailyLoss,2)+" GBP hit (dayPnL="+DoubleToString(dayPnL,2)+"). Flattened & halted; auto-resume next server day.");
      return true;
   }

   return false;
}

//==================== ACTION HANDLERS ==============================
void HandleMeta(const string js)
{
   g_meta_seen=true;
   g_meta_acct=JGetNum(js,"signal_account_size",InpMetaAccountFallback);
   LogCSV("META;acct="+DoubleToString(g_meta_acct,2));
}

void HandleOpen(const string js)
{
   if(GuardrailBlock()){
      LogCSV("OPEN_BLOCKED_GUARDRAIL");
      return;
   }

   string id  = JGetStr(js,"id");
   if(id=="") id = JGetStr(js,"entry_ts");
   if(HasOpenFired(id)){
      LogCSV("OPEN_DUP_SKIP;"+id);
      return;
   }
   string dir = JGetStr(js,"dir");
   double entry = JGetNum(js,"entry");
   double stop  = JGetNum(js,"stop");
   double tp    = JGetNum(js,"tp");
   double qty   = JGetNum(js,"qty");
   double sacct = JGetNum(js,"signal_account_size", g_meta_acct);
   if(sacct<=0) sacct=InpMetaAccountFallback;

   double live_eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double lots;
   if(InpReplayMode && InpReplayUseSignalPricing) lots = qty;
   else                                            lots = qty * (live_eq / sacct); // per-signal scaling
   lots = NormalizeLots(lots);
   if(lots<=0){
      LogCSV("OPEN_SKIP_ZEROLOT;"+id);
      return;
   }

   bool is_long = (dir=="long");
   double price = is_long ? SymbolInfoDouble(g_symbol,SYMBOL_ASK)
                          : SymbolInfoDouble(g_symbol,SYMBOL_BID);
   double sl = ClampStopDistance(price, stop, is_long);
   double tpx = NormalizePrice(tp);

   // Fidelity mode in replay: do not attach broker SL/TP.
   double open_sl = InpReplayMode ? 0.0 : sl;
   double open_tp = InpReplayMode ? 0.0 : tpx;

   trade.SetExpertMagicNumber(InpMagicNumber);
   bool ok;
   if(is_long) ok=trade.Buy(lots,g_symbol,0.0,open_sl,open_tp,id);
   else        ok=trade.Sell(lots,g_symbol,0.0,open_sl,open_tp,id);

   if(ok){
      ulong tk=trade.ResultOrder();
      // Resolve to position ticket by matching comment/magic/symbol.
      ulong resolved=0;
      for(int pi=PositionsTotal()-1; pi>=0; pi--){
         ulong cand=PositionGetTicket(pi);
         if(cand==0) continue;
         if(!PositionSelectByTicket(cand)) continue;
         if(PositionGetInteger(POSITION_MAGIC)!=InpMagicNumber) continue;
         if(PositionGetString(POSITION_SYMBOL)!=g_symbol) continue;
         if(PositionGetString(POSITION_COMMENT)==id){ resolved=cand; break; }
      }
      if(resolved!=0) tk=resolved;
      MapId(id,tk);
      MarkOpenFired(id);
      int idx=FindId(id);
      if(idx>=0){
         g_last_sl[idx]=sl;
         g_sig_entry[idx]=entry;
         g_sig_qty[idx]=qty;
         g_sig_dir[idx]=is_long ? 1 : -1;
      }
      LogCSV("OPEN;"+id+";dir="+dir+";lots="+DoubleToString(lots,2)+
             ";want_entry="+DoubleToString(entry,g_digits)+
             ";fill="+DoubleToString(trade.ResultPrice(),g_digits)+
             ";sl="+DoubleToString(sl,g_digits)+";tp="+DoubleToString(tpx,g_digits)+
             ";sacct="+DoubleToString(sacct,2)+";live_eq="+DoubleToString(live_eq,2));
   }
   else {
      LogCSV("OPEN_FAIL;"+id+";ret="+IntegerToString(trade.ResultRetcode())+";"+trade.ResultRetcodeDescription());
   }
}

void HandleModify(const string js)
{
   string id = JGetStr(js,"id");
   double new_stop = JGetNum(js,"new_stop");
   int idx=FindId(id);
   if(idx<0){
      LogCSV("MODIFY_NO_MAP;"+id);
      return;
   }

   ulong tk=g_tickets[idx];
   if(!PositionSelectByTicket(tk)){
      LogCSV("MODIFY_NO_POS;"+id);
      UnmapId(id);
      return;
   }

   bool is_long = (PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY);
   double cur_price = is_long ? SymbolInfoDouble(g_symbol,SYMBOL_BID)
                              : SymbolInfoDouble(g_symbol,SYMBOL_ASK);
   double minDist = MinStopDistance();

   bool sl_valid_side = is_long ? (new_stop < (cur_price - minDist))
                                : (new_stop > (cur_price + minDist));
   if(!sl_valid_side){
      LogCSV("MODIFY_SKIP_LATE;"+id+
             ";reason=invalid_sl_side"+
             ";ref="+DoubleToString(cur_price,g_digits)+
             ";sl="+DoubleToString(new_stop,g_digits)+
             ";minDist="+DoubleToString(minDist,g_digits));
      return;
   }

   double sl = ClampStopDistance(cur_price, new_stop, is_long);
   double tp = PositionGetDouble(POSITION_TP);

   // dedupe: skip no-op modify
   if(MathAbs(sl - g_last_sl[idx]) < g_point*0.5) return;

   if(InpReplayMode){
      g_last_sl[idx]=sl;
      LogCSV("MODIFY_AUDIT;"+id+";new_sl="+DoubleToString(sl,g_digits));
      return;
   }

   if(trade.PositionModify(tk, sl, tp)){
      g_last_sl[idx]=sl;
      LogCSV("MODIFY;"+id+";new_sl="+DoubleToString(sl,g_digits));
   }
   else {
      int rc=(int)trade.ResultRetcode();
      if(rc==10016){
         // Price can move between compute and submit; refresh and retry once.
         double retry_price = is_long ? SymbolInfoDouble(g_symbol,SYMBOL_BID)
                                      : SymbolInfoDouble(g_symbol,SYMBOL_ASK);
         bool retry_valid_side = is_long ? (new_stop < (retry_price - minDist))
                                         : (new_stop > (retry_price + minDist));
         if(!retry_valid_side){
            LogCSV("MODIFY_SKIP_LATE;"+id+
                   ";reason=invalid_sl_side_refresh"+
                   ";ref="+DoubleToString(retry_price,g_digits)+
                   ";sl="+DoubleToString(new_stop,g_digits)+
                   ";minDist="+DoubleToString(minDist,g_digits));
            return;
         }

         double retry_sl = ClampStopDistance(retry_price, new_stop, is_long);
         if(MathAbs(retry_sl - sl) >= g_point*0.5 && trade.PositionModify(tk, retry_sl, tp)){
            g_last_sl[idx]=retry_sl;
            LogCSV("MODIFY_RETRY;"+id+";new_sl="+DoubleToString(retry_sl,g_digits));
            return;
         }
         rc=(int)trade.ResultRetcode();
      }

      if(rc==10025 || rc==10027){
         g_last_sl[idx]=sl; // no change / disabled - swallow
      }
      else {
         LogCSV("MODIFY_FAIL;"+id+";ret="+IntegerToString(rc)+";"+trade.ResultRetcodeDescription());
      }
   }
}

void HandleClose(const string js)
{
   string id = JGetStr(js,"id");
   double exit_sig = JGetNum(js,"exit");
   string reason = JGetStr(js,"reason");
   int idx=FindId(id);
   if(idx<0){
      LogCSV("CLOSE_NO_MAP;"+id);
      return;
   }

   if(InpReplayMode && InpReplayUseSignalPricing && exit_sig>0.0){
      double entry_sig = g_sig_entry[idx];
      double qty_sig = g_sig_qty[idx];
      int dir_sig = g_sig_dir[idx];
      if(qty_sig>0.0 && dir_sig!=0){
         double pnl_sig = (dir_sig>0) ? (exit_sig-entry_sig)*qty_sig : (entry_sig-exit_sig)*qty_sig;
         g_synth_net += pnl_sig;
         g_synth_trades++;
         if(pnl_sig>0.0) g_synth_wins++;
         LogCSV("CLOSE_SYNTH;"+id+
                ";entry="+DoubleToString(entry_sig,g_digits)+
                ";exit="+DoubleToString(exit_sig,g_digits)+
                ";qty="+DoubleToString(qty_sig,6)+
                ";pnl="+DoubleToString(pnl_sig,2));
      }
   }

   ulong tk=g_tickets[idx];
   // If broker already stopped it out, position won't select -> no-op confirmation
   if(!PositionSelectByTicket(tk)){
      LogCSV("CLOSE_ALREADY;"+id);
      UnmapId(id);
      return;
   }

   if(InpReplayMode && InpReplayUseSignalPricing && reason=="tp" && exit_sig>0.0){
      double sl_sig = g_last_sl[idx];
      int dir_sig = g_sig_dir[idx];
      bool is_long = (PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY);
      double ref_px = is_long ? SymbolInfoDouble(g_symbol,SYMBOL_BID)
                              : SymbolInfoDouble(g_symbol,SYMBOL_ASK);
      double minDist = MinStopDistance();

      double tp_arm = NormalizePrice(exit_sig);
      if(minDist>0.0){
         if(is_long){
            if(tp_arm-ref_px < minDist) tp_arm = NormalizePrice(ref_px+minDist);
         }
         else {
            if(ref_px-tp_arm < minDist) tp_arm = NormalizePrice(ref_px-minDist);
         }
      }

      double sl_arm = 0.0;
      if(sl_sig>0.0){
         sl_arm = ClampStopDistance(ref_px, sl_sig, is_long);
      }

      bool tp_valid_side = is_long ? (tp_arm>ref_px) : (tp_arm<ref_px);
      if(!tp_valid_side){
         LogCSV("CLOSE_TP_ARM_SKIP_LATE;"+id+
                ";reason=invalid_tp_side"+
                ";ref="+DoubleToString(ref_px,g_digits)+
                ";tp="+DoubleToString(tp_arm,g_digits));
      }
      else {

         // Arm broker-side TP/SL to emulate resting-order semantics in replay.
         // This avoids optimistic market-on-touch fills at wick extremes.
         if(trade.PositionModify(tk, sl_arm, tp_arm)){
            ArmReplayTpClose(id, tk, dir_sig, tp_arm, sl_arm);
            return;
         }
         LogCSV("CLOSE_TP_ARM_FAIL;"+id+
                ";ret="+IntegerToString(trade.ResultRetcode())+
                ";"+trade.ResultRetcodeDescription());
      }
   }

   if(trade.PositionClose(tk)){
      LogCSV("CLOSE;"+id+";fill="+DoubleToString(trade.ResultPrice(),g_digits));
   }
   else {
      LogCSV("CLOSE_FAIL;"+id+";ret="+IntegerToString(trade.ResultRetcode()));
   }
   UnmapId(id);
}

//==================== LINE DISPATCH ================================
void ProcessLine(const string raw)
{
   string js=raw;
   StringTrimLeft(js);
   StringTrimRight(js);
   if(StringLen(js)<2) return;

   string action=JGetStr(js,"action");
   if(action=="meta")           HandleMeta(js);
   else if(action=="open")      HandleOpen(js);
   else if(action=="modify")    HandleModify(js);
   else if(action=="close")     HandleClose(js);
   else if(action=="heartbeat") { /* liveness only */ }
}

//==================== FILE READ ====================================
// Reads any new lines appended since last call (live polling only).
void PumpFileLive()
{
   int h=FileOpen(InpSignalFile, FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h==INVALID_HANDLE) return;

   FileSeek(h,(long)g_filepos,SEEK_SET);
   while(!FileIsEnding(h)){
      string line=FileReadString(h);
      if(StringLen(line)>0) ProcessLine(line);
   }
   g_filepos=(ulong)FileTell(h);
   FileClose(h);
}

//==================== EVENTS =======================================
int OnInit()
{
   g_symbol = (InpSymbolOverride!="") ? InpSymbolOverride : _Symbol;
   if(!SymbolSelect(g_symbol,true)){
      // fallback resolve
      string alts[]={"NAS100","USTEC","USTECH","US100.cash","NAS100.cash","US100"};
      for(int i=0;i<ArraySize(alts);i++){
         if(SymbolSelect(alts[i],true)){
            g_symbol=alts[i];
            break;
         }
      }
   }

   g_digits=(int)SymbolInfoInteger(g_symbol,SYMBOL_DIGITS);
   g_point =SymbolInfoDouble(g_symbol,SYMBOL_POINT);
   g_volstep=SymbolInfoDouble(g_symbol,SYMBOL_VOLUME_STEP);
   g_volmin =SymbolInfoDouble(g_symbol,SYMBOL_VOLUME_MIN);
   g_volmax =SymbolInfoDouble(g_symbol,SYMBOL_VOLUME_MAX);
   g_stopslevel=(int)SymbolInfoInteger(g_symbol,SYMBOL_TRADE_STOPS_LEVEL);

   g_mode=DetectMode();
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetTypeFillingBySymbol(g_symbol);

   g_current_day=ServerDay();
   g_day_start_equity=AccountInfoDouble(ACCOUNT_EQUITY);

   g_replay_loaded = false;
   g_replay_next = 0;
   ArrayResize(g_replay_raw, 0);
   ArrayResize(g_replay_ts, 0);
   ArrayResize(g_open_once_ids, 0);
   ArrayResize(g_sig_entry, 0);
   ArrayResize(g_sig_qty, 0);
   ArrayResize(g_sig_dir, 0);
   ArrayResize(g_pending_ids, 0);
   ArrayResize(g_pending_tickets, 0);
   ArrayResize(g_pending_tp, 0);
   ArrayResize(g_pending_sl, 0);
   ArrayResize(g_pending_dir, 0);
   ArrayResize(g_pending_expiry, 0);
   g_synth_net = 0.0;
   g_synth_trades = 0;
   g_synth_wins = 0;

   PrintFormat("PhantomBridge init | symbol=%s digits=%d step=%.2f stops=%d mode=%s replay=%s",
               g_symbol,g_digits,g_volstep,g_stopslevel,
               (g_mode==BROKER_FTMO?"FTMO":(g_mode==BROKER_CASH?"CASH":"AUTO")),
               (InpReplayMode?"true":"false"));

   LogCSV("INIT;symbol="+g_symbol+";mode="+(g_mode==BROKER_FTMO?"FTMO":"CASH"));
   StampModelMode();
   return INIT_SUCCEEDED;
}

void OnTick()
{
   ProcessPendingReplayTpCloses();

   // bar-close M5 gate: act once per new bar
   datetime bt=iTime(g_symbol,PERIOD_M5,0);
   if(bt==g_last_bar) return;
   g_last_bar=bt;

   DetectStraddles(bt);

   if(g_mode==BROKER_CASH) ResetDayIfNeeded();
   if(InpReplayMode){
      ReplayDueEvents(bt);
   }
   else {
      PumpFileLive();
   }
}

void OnDeinit(const int reason)
{
   if(InpReplayMode && InpReplayUseSignalPricing){
      LogCSV("SYNTH_SUMMARY;trades="+IntegerToString(g_synth_trades)+
             ";wins="+IntegerToString(g_synth_wins)+
             ";net="+DoubleToString(g_synth_net,2));
   }
   LogCSV("DEINIT;reason="+IntegerToString(reason));
}
