//+------------------------------------------------------------------+
//|                                            BreakoutWatcherEA.mq5 |
//|                                    Copyright 2026, Telegram-Bot-Ansh |
//+------------------------------------------------------------------+
#property copyright "Telegram-Bot-Ansh"
#property link      ""
#property version   "1.00"
#property description "Watches dual-range breakout levels and executes market entry on break"
#property strict

#include <Trade\Trade.mqh>

//--- Input Parameters
input string   InpFileName          = "breakout_tasks.json"; // Signal task filename
input bool     InpUseCommonFolder   = true;                  // Read from Common Files folder
input ulong    InpMagicNumber       = 777999;                // Magic Number
input ulong    InpDeviation         = 20;                    // Max deviation in points
input bool     InpDrawVisualLines   = true;                  // Draw visual breakout lines on chart
input int      InpTimerMs           = 250;                   // Check interval in milliseconds (250ms)
input color    InpColorUpper        = clrLimeGreen;          // Upper Buy Breakout Line Color
input color    InpColorLower        = clrRed;                // Lower Sell Breakdown Line Color

//--- Global Variables
CTrade         g_trade;
string         g_currentId          = "";
string         g_symbol             = "";
double         g_upperTrigger       = 0.0;
double         g_upperSL            = 0.0;
double         g_upperTP            = 0.0;
double         g_lowerTrigger       = 0.0;
double         g_lowerSL            = 0.0;
double         g_lowerTP            = 0.0;
double         g_lot                = 0.02;
string         g_status             = "";
datetime       g_lastReadTime       = 0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("[BreakoutWatcherEA] Initialized. Monitoring file: ", InpFileName);
   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(InpDeviation);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   EventSetMillisecondTimer(InpTimerMs);
   ReadTaskFile();
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   RemoveChartObjects();
   Print("[BreakoutWatcherEA] Deinitialized. Cleanup complete.");
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   CheckAndTriggerBreakout();
}

//+------------------------------------------------------------------+
//| Timer function                                                   |
//+------------------------------------------------------------------+
void OnTimer()
{
   // Periodically re-read file if new task arrived
   ReadTaskFile();
   CheckAndTriggerBreakout();
}

//+------------------------------------------------------------------+
//| Simple JSON string value extractor                               |
//+------------------------------------------------------------------+
string ExtractJsonString(const string text, const string key)
{
   string pattern = "\"" + key + "\":";
   int pos = StringFind(text, pattern);
   if(pos < 0) return("");
   
   pos += StringLen(pattern);
   // Skip whitespace
   while(pos < StringLen(text) && (StringGetCharacter(text, pos) == ' ' || StringGetCharacter(text, pos) == '\"'))
      pos++;
      
   int endPos = pos;
   while(endPos < StringLen(text) && StringGetCharacter(text, endPos) != '\"' && StringGetCharacter(text, endPos) != ',' && StringGetCharacter(text, endPos) != '}')
      endPos++;
      
   return(StringSubstr(text, pos, endPos - pos));
}

//+------------------------------------------------------------------+
//| Simple JSON double value extractor                               |
//+------------------------------------------------------------------+
double ExtractJsonDouble(const string text, const string key)
{
   string strVal = ExtractJsonString(text, key);
   if(strVal == "" || strVal == "null") return(0.0);
   return(StringToDouble(strVal));
}

//+------------------------------------------------------------------+
//| Read Task File from Files or Common Files                        |
//+------------------------------------------------------------------+
void ReadTaskFile()
{
   int flags = FILE_READ | FILE_TXT | FILE_ANSI | FILE_SHARE_READ;
   if(InpUseCommonFolder)
      flags |= FILE_COMMON;

   // Try symbol-specific task file first (e.g. breakout_task_OILCash#.json)
   string symFile1 = StringFormat("breakout_task_%s.json", _Symbol);
   string cleanSym = _Symbol;
   StringReplace(cleanSym, "#", "");
   StringReplace(cleanSym, ".", "_");
   string symFile2 = StringFormat("breakout_task_%s.json", cleanSym);

   int handle = FileOpen(symFile1, flags);
   if(handle == INVALID_HANDLE)
      handle = FileOpen(symFile2, flags);
   if(handle == INVALID_HANDLE)
      handle = FileOpen(InpFileName, flags);

   if(handle == INVALID_HANDLE)
      return;

   string content = "";
   while(!FileIsEnding(handle))
   {
      content += FileReadString(handle) + " ";
   }
   FileClose(handle);

   if(content == "") return;

   string id = ExtractJsonString(content, "id");
   string sym = ExtractJsonString(content, "symbol");
   string status = ExtractJsonString(content, "status");

   if(sym == "") return;

   // Ensure this EA on _Symbol only processes tasks meant for this chart's symbol
   if(sym != _Symbol && StringFind(sym, _Symbol) < 0 && StringFind(_Symbol, sym) < 0)
      return;

   // Only update if setup is new or modified
   if(id != g_currentId || status != g_status)
   {
      g_currentId    = id;
      g_symbol       = sym;
      g_status       = status;
      g_upperTrigger = ExtractJsonDouble(content, "upper_trigger");
      g_upperSL      = ExtractJsonDouble(content, "upper_sl");
      g_upperTP      = ExtractJsonDouble(content, "upper_tp");
      g_lowerTrigger = ExtractJsonDouble(content, "lower_trigger");
      g_lowerSL      = ExtractJsonDouble(content, "lower_sl");
      g_lowerTP      = ExtractJsonDouble(content, "lower_tp");
      g_lot          = ExtractJsonDouble(content, "lot");
      if(g_lot <= 0) g_lot = 0.02;

      PrintFormat("[BreakoutWatcherEA] Task Loaded for %s: %s | Status: %s | Upper: %.4f | Lower: %.4f",
                  _Symbol, g_currentId, g_status, g_upperTrigger, g_lowerTrigger);

      if(g_status == "WATCHING" && InpDrawVisualLines)
      {
         UpdateChartObjects();
      }
      else if(g_status != "WATCHING")
      {
         RemoveChartObjects();
      }
   }
}

//+------------------------------------------------------------------+
//| Write Task Status Back to File                                   |
//+------------------------------------------------------------------+
void UpdateTaskStatus(string newStatus)
{
   g_status = newStatus;
   int flags = FILE_WRITE | FILE_TXT | FILE_ANSI;
   if(InpUseCommonFolder)
      flags |= FILE_COMMON;

   string symFile1 = StringFormat("breakout_task_%s.json", _Symbol);
   string cleanSym = _Symbol;
   StringReplace(cleanSym, "#", "");
   StringReplace(cleanSym, ".", "_");
   string symFile2 = StringFormat("breakout_task_%s.json", cleanSym);

   string json = StringFormat(
      "{\"id\":\"%s\",\"symbol\":\"%s\",\"upper_trigger\":%.4f,\"upper_sl\":%.4f,\"upper_tp\":%.4f,\"lower_trigger\":%.4f,\"lower_sl\":%.4f,\"lower_tp\":%.4f,\"lot\":%.2f,\"status\":\"%s\"}",
      g_currentId, g_symbol, g_upperTrigger, g_upperSL, g_upperTP, g_lowerTrigger, g_lowerSL, g_lowerTP, g_lot, newStatus
   );

   // 1. Write symbol-specific files
   int h1 = FileOpen(symFile1, flags);
   if(h1 != INVALID_HANDLE)
   {
      FileWriteString(h1, json);
      FileClose(h1);
   }

   if(cleanSym != _Symbol)
   {
      int h2 = FileOpen(symFile2, flags);
      if(h2 != INVALID_HANDLE)
      {
         FileWriteString(h2, json);
         FileClose(h2);
      }
   }

   // 2. Write master task file
   int handle = FileOpen(InpFileName, flags);
   if(handle != INVALID_HANDLE)
   {
      FileWriteString(handle, json);
      FileClose(handle);
   }
}

//+------------------------------------------------------------------+
//| Draw or Update Visual Lines on Chart                             |
//+------------------------------------------------------------------+
void UpdateChartObjects()
{
   if(g_symbol != _Symbol && g_symbol != "")
      return; // Only draw on matching symbol chart

   // Upper Breakout Line
   if(g_upperTrigger > 0)
   {
      string nameUpper = "EA_UPPER_BREAKOUT";
      if(ObjectFind(0, nameUpper) < 0)
         ObjectCreate(0, nameUpper, OBJ_HLINE, 0, 0, g_upperTrigger);
      ObjectSetDouble(0, nameUpper, OBJPROP_PRICE, g_upperTrigger);
      ObjectSetInteger(0, nameUpper, OBJPROP_COLOR, InpColorUpper);
      ObjectSetInteger(0, nameUpper, OBJPROP_WIDTH, 2);
      ObjectSetInteger(0, nameUpper, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetString(0, nameUpper, OBJPROP_TOOLTIP, StringFormat("BUY BREAKOUT TRIGGER @ %.2f (SL: %.2f, TP: %.2f)", g_upperTrigger, g_upperSL, g_upperTP));
   }

   // Lower Breakdown Line
   if(g_lowerTrigger > 0)
   {
      string nameLower = "EA_LOWER_BREAKDOWN";
      if(ObjectFind(0, nameLower) < 0)
         ObjectCreate(0, nameLower, OBJ_HLINE, 0, 0, g_lowerTrigger);
      ObjectSetDouble(0, nameLower, OBJPROP_PRICE, g_lowerTrigger);
      ObjectSetInteger(0, nameLower, OBJPROP_COLOR, InpColorLower);
      ObjectSetInteger(0, nameLower, OBJPROP_WIDTH, 2);
      ObjectSetInteger(0, nameLower, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetString(0, nameLower, OBJPROP_TOOLTIP, StringFormat("SELL BREAKDOWN TRIGGER @ %.2f (SL: %.2f, TP: %.2f)", g_lowerTrigger, g_lowerSL, g_lowerTP));
   }

   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Remove Visual Lines from Chart                                   |
//+------------------------------------------------------------------+
void RemoveChartObjects()
{
   ObjectDelete(0, "EA_UPPER_BREAKOUT");
   ObjectDelete(0, "EA_LOWER_BREAKDOWN");
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Check Breakout Conditions and Trigger Order                      |
//+------------------------------------------------------------------+
void CheckAndTriggerBreakout()
{
   if(g_status != "WATCHING") return;
   if(g_symbol == "") return;
   if(g_symbol != _Symbol && StringFind(g_symbol, _Symbol) < 0 && StringFind(_Symbol, g_symbol) < 0)
      return;

   MqlTick tick;
   if(!SymbolInfoTick(g_symbol, tick))
      return;

   int digits = (int)SymbolInfoInteger(g_symbol, SYMBOL_DIGITS);

   // 1. Check UPPER Breakout (BUY)
   if(g_upperTrigger > 0 && tick.ask >= g_upperTrigger)
   {
      PrintFormat("[BreakoutWatcherEA] >>> UPPER BREAKOUT CONFIRMED! Ask: %.4f >= Trigger: %.4f. Executing BUY...", tick.ask, g_upperTrigger);
      
      double sl = (g_upperSL > 0) ? NormalizeDouble(g_upperSL, digits) : 0.0;
      double tp = (g_upperTP > 0) ? NormalizeDouble(g_upperTP, digits) : 0.0;

      if(g_trade.Buy(g_lot, g_symbol, tick.ask, sl, tp, "EA Breakout BUY"))
      {
         PrintFormat("[BreakoutWatcherEA] BUY Order Executed! Ticket: %d", g_trade.ResultOrder());
         UpdateTaskStatus("TRIGGERED_BUY");
         RemoveChartObjects();
         PlaySound("alert.wav");
      }
      else
      {
         PrintFormat("[BreakoutWatcherEA] BUY Execution failed: %s (Code: %d)", g_trade.ResultComment(), g_trade.ResultRetcode());
      }
      return;
   }

   // 2. Check LOWER Breakdown (SELL)
   if(g_lowerTrigger > 0 && tick.bid <= g_lowerTrigger)
   {
      PrintFormat("[BreakoutWatcherEA] >>> LOWER BREAKDOWN CONFIRMED! Bid: %.4f <= Trigger: %.4f. Executing SELL...", tick.bid, g_lowerTrigger);

      double sl = (g_lowerSL > 0) ? NormalizeDouble(g_lowerSL, digits) : 0.0;
      double tp = (g_lowerTP > 0) ? NormalizeDouble(g_lowerTP, digits) : 0.0;

      if(g_trade.Sell(g_lot, g_symbol, tick.bid, sl, tp, "EA Breakdown SELL"))
      {
         PrintFormat("[BreakoutWatcherEA] SELL Order Executed! Ticket: %d", g_trade.ResultOrder());
         UpdateTaskStatus("TRIGGERED_SELL");
         RemoveChartObjects();
         PlaySound("alert.wav");
      }
      else
      {
         PrintFormat("[BreakoutWatcherEA] SELL Execution failed: %s (Code: %d)", g_trade.ResultComment(), g_trade.ResultRetcode());
      }
      return;
   }
}
//+------------------------------------------------------------------+
