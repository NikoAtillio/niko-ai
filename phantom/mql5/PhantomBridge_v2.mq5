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

//==================== INPUTS =======================================
input string  InpSignalFile          = "phantom_signals.jsonl"; // file in Common\Files
input long    InpMagicNumber         = 920025;                  // unique per account/instrument
input string  InpSymbolOverride      = "US100";                // live/demo target symbol
input bool    InpReplayMode          = true;                    // true=backtest replay, false=live polling

// --- broker mode ---
enum ENUM_BROKER_MODE { BROKER_AUTO=0, BROKER_FTMO=1, BROKER_CASH=2 };
input ENUM_BROKER_MODE InpBrokerMode = BROKER_AUTO;

// --- cash-account guardrails (GBP, only enforced in CASH mode) ---
input double  InpMaxDailyLoss        = 500.0;                   // flatten+halt for the day
input double  InpMaxOverallLoss      = 1000.0;                  // flatten+halt (see hard-stop toggle)
input double  InpProfitTarget        = 500.0;                   // log only, keep trading
input bool    InpHardStopOnMaxLoss   = false;                   // true = disable permanently on max loss

// --- lot scaling ---
input double  InpMetaAccountFallback = 10000.0;                 // used only if a signal lacks signal_account_size
input double  InpMaxLots             = 50.0;                    // hard safety cap
input double  InpMinLots             = 0.01;

// --- notifications ---
input bool    InpNotifyPush          = true;                    // SendNotification (mobile)
input bool    InpNotifyEmail         = false;                   // SendMail (needs SMTP)
input bool    InpNotifyAlert         = true;                    // Alert popup + Print

// --- logging ---
input bool    InpLogToCSV            = true;
input string  InpLogFile             = "phantom_bridge_log.csv";

//==================== STATE ========================================
string   g_symbol;
int      g_digits;
double   g_point;
double   g_volstep, g_volmin, g_volmax;
int      g_stopslevel;

ulong    g_filepos     = 0;     // byte offset already consumed (live polling)
int      g_lineidx     = 0;     // lines consumed (replay)
bool     g_meta_seen   = false;
double   g_meta_acct   = 10000.0;
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

datetime g_last_bar = 0;

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
      g_ids[n]=id;
      g_tickets[n]=ticket;
      g_last_sl[n]=0.0;
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
   ArrayResize(g_ids,last);
   ArrayResize(g_tickets,last);
   ArrayResize(g_last_sl,last);
}

double NormalizePrice(const double p){ return NormalizeDouble(p,g_digits); }

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
   if(g_stopslevel<=0) return NormalizePrice(sl);
   double minDist = g_stopslevel*g_point;
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
   string dir = JGetStr(js,"dir");
   double entry = JGetNum(js,"entry");
   double stop  = JGetNum(js,"stop");
   double tp    = JGetNum(js,"tp");
   double qty   = JGetNum(js,"qty");
   double sacct = JGetNum(js,"signal_account_size", g_meta_acct);
   if(sacct<=0) sacct=InpMetaAccountFallback;

   double live_eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double lots = qty * (live_eq / sacct); // per-signal scaling
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

   trade.SetExpertMagicNumber(InpMagicNumber);
   bool ok;
   if(is_long) ok=trade.Buy(lots,g_symbol,0.0,sl,tpx,id);
   else        ok=trade.Sell(lots,g_symbol,0.0,sl,tpx,id);

   if(ok){
      ulong tk=trade.ResultOrder();
      // resolve to position ticket
      if(PositionSelect(g_symbol)) tk=(ulong)PositionGetInteger(POSITION_TICKET);
      MapId(id,tk);
      int idx=FindId(id);
      if(idx>=0) g_last_sl[idx]=sl;
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
   double sl = ClampStopDistance(cur_price, new_stop, is_long);
   double tp = PositionGetDouble(POSITION_TP);

   // dedupe: skip no-op modify
   if(MathAbs(sl - g_last_sl[idx]) < g_point*0.5) return;

   if(trade.PositionModify(tk, sl, tp)){
      g_last_sl[idx]=sl;
      LogCSV("MODIFY;"+id+";new_sl="+DoubleToString(sl,g_digits));
   }
   else {
      int rc=(int)trade.ResultRetcode();
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
   int idx=FindId(id);
   if(idx<0){
      LogCSV("CLOSE_NO_MAP;"+id);
      return;
   }

   ulong tk=g_tickets[idx];
   // If broker already stopped it out, position won't select -> no-op confirmation
   if(!PositionSelectByTicket(tk)){
      LogCSV("CLOSE_ALREADY;"+id);
      UnmapId(id);
      return;
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
// Reads any new lines appended since last call.
void PumpFile()
{
   int h=FileOpen(InpSignalFile, FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h==INVALID_HANDLE) return;

   // seek to where we left off (live). In replay we re-read from 0 and skip consumed lines.
   if(!InpReplayMode){
      FileSeek(h,(long)g_filepos,SEEK_SET);
      while(!FileIsEnding(h)){
         string line=FileReadString(h);
         if(StringLen(line)>0) ProcessLine(line);
      }
      g_filepos=(ulong)FileTell(h);
   }
   else {
      int i=0;
      while(!FileIsEnding(h)){
         string line=FileReadString(h);
         if(i>=g_lineidx && StringLen(line)>0){
            ProcessLine(line);
            g_lineidx++;
         }
         else if(StringLen(line)>0){
            i++;
         }
         if(i<g_lineidx) i=g_lineidx; // keep in sync
      }
   }
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

   PrintFormat("PhantomBridge init | symbol=%s digits=%d step=%.2f stops=%d mode=%s replay=%s",
               g_symbol,g_digits,g_volstep,g_stopslevel,
               (g_mode==BROKER_FTMO?"FTMO":(g_mode==BROKER_CASH?"CASH":"AUTO")),
               (InpReplayMode?"true":"false"));

   LogCSV("INIT;symbol="+g_symbol+";mode="+(g_mode==BROKER_FTMO?"FTMO":"CASH"));
   return INIT_SUCCEEDED;
}

void OnTick()
{
   // bar-close M5 gate: act once per new bar
   datetime bt=iTime(g_symbol,PERIOD_M5,0);
   if(bt==g_last_bar) return;
   g_last_bar=bt;

   if(g_mode==BROKER_CASH) ResetDayIfNeeded();
   PumpFile();
}

void OnDeinit(const int reason)
{
   LogCSV("DEINIT;reason="+IntegerToString(reason));
}
