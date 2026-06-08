i have errors in my compile:
phantom_signal_reader_v3.mq5			
Trade.mqh			
Object.mqh			
StdLibErr.mqh			
OrderInfo.mqh			
HistoryOrderInfo.mqh			
PositionInfo.mqh			
DealInfo.mqh			
variable already defined	phantom_signal_reader_v3.mq5	808	14
   see declaration of variable 'InpMagicNumber'	phantom_signal_reader_v3.mq5	16	14
idenfitier 'InpMagicNumber' already used	phantom_signal_reader_v3.mq5	16	14
   see declaration of variable 'InpMagicNumber'	phantom_signal_reader_v3.mq5	16	14
variable already defined	phantom_signal_reader_v3.mq5	809	14
   see declaration of variable 'InpSignalFile'	phantom_signal_reader_v3.mq5	17	14
idenfitier 'InpSignalFile' already used	phantom_signal_reader_v3.mq5	17	14
   see declaration of variable 'InpSignalFile'	phantom_signal_reader_v3.mq5	17	14
variable already defined	phantom_signal_reader_v3.mq5	810	14
   see declaration of variable 'InpVerboseLog'	phantom_signal_reader_v3.mq5	18	14
idenfitier 'InpVerboseLog' already used	phantom_signal_reader_v3.mq5	18	14
   see declaration of variable 'InpVerboseLog'	phantom_signal_reader_v3.mq5	18	14
variable already defined	phantom_signal_reader_v3.mq5	811	14
   see declaration of variable 'InpQtyUnitsPerLotOverride'	phantom_signal_reader_v3.mq5	19	14
idenfitier 'InpQtyUnitsPerLotOverride' already used	phantom_signal_reader_v3.mq5	19	14
   see declaration of variable 'InpQtyUnitsPerLotOverride'	phantom_signal_reader_v3.mq5	19	14
variable already defined	phantom_signal_reader_v3.mq5	812	14
   see declaration of variable 'InpForceMinLotInReplay'	phantom_signal_reader_v3.mq5	20	14
idenfitier 'InpForceMinLotInReplay' already used	phantom_signal_reader_v3.mq5	20	14
   see declaration of variable 'InpForceMinLotInReplay'	phantom_signal_reader_v3.mq5	20	14
variable already defined	phantom_signal_reader_v3.mq5	813	14
   see declaration of variable 'InpReplayExistingSignals'	phantom_signal_reader_v3.mq5	21	14
idenfitier 'InpReplayExistingSignals' already used	phantom_signal_reader_v3.mq5	21	14
   see declaration of variable 'InpReplayExistingSignals'	phantom_signal_reader_v3.mq5	21	14
variable already defined	phantom_signal_reader_v3.mq5	814	14
   see declaration of variable 'InpTrailATRMult'	phantom_signal_reader_v3.mq5	22	14
idenfitier 'InpTrailATRMult' already used	phantom_signal_reader_v3.mq5	22	14
   see declaration of variable 'InpTrailATRMult'	phantom_signal_reader_v3.mq5	22	14
variable already defined	phantom_signal_reader_v3.mq5	815	14
   see declaration of variable 'InpBreakevenR'	phantom_signal_reader_v3.mq5	23	14
idenfitier 'InpBreakevenR' already used	phantom_signal_reader_v3.mq5	23	14
   see declaration of variable 'InpBreakevenR'	phantom_signal_reader_v3.mq5	23	14
variable already defined	phantom_signal_reader_v3.mq5	816	14
            continue;
        }

        if(lineIndex < g_lastLineCount)
        {
            lineIndex++;
            continue;
        }

        string cleanedLine = _trim_copy(line);
        ProcessLine(cleanedLine);
        g_lastLineCount = lineIndex + 1;

        lineIndex++;
    }

    FileClose(handle);
    g_lastLineCount = currentLines;
}

void ProcessSignalsReplay()
{
    datetime nowTime = CurrentReplayTime();
    if(nowTime <= 0)
        return;

    if(nowTime == g_lastReplayBarTime)
        return;
    g_lastReplayBarTime = nowTime;

    while(g_nextSignalIndex < ArraySize(g_signals))
    {
        if(g_signals[g_nextSignalIndex].signalTime > nowTime)
            break;

        string jsonLine = StringFormat(
            "{\"action\":\"%s\",\"signal_id\":\"%s\",\"entry_ts\":\"%s\",\"dir\":\"%s\",\"account_size\":%.10f,\"entry\":%.10f,\"qty\":%.10f,\"stop\":%.10f,\"tp\":%.10f,\"atr_entry\":%.10f}",
            g_signals[g_nextSignalIndex].action,
            StringLen(g_signals[g_nextSignalIndex].signalId) > 0 ? g_signals[g_nextSignalIndex].signalId : g_signals[g_nextSignalIndex].entryTs,
            g_signals[g_nextSignalIndex].entryTs,
            g_signals[g_nextSignalIndex].dir,
            g_signals[g_nextSignalIndex].accountSize,
            g_signals[g_nextSignalIndex].entry,
            g_signals[g_nextSignalIndex].qty,
            g_signals[g_nextSignalIndex].stop,
            g_signals[g_nextSignalIndex].tp,
            EffectiveAtrEntry(g_signals[g_nextSignalIndex].entry, g_signals[g_nextSignalIndex].stop, g_signals[g_nextSignalIndex].atr_entry)
        );
        ProcessLine(jsonLine);
        g_nextSignalIndex++;
    }
}

int OnInit()
{
    trade.SetExpertMagicNumber(InpMagicNumber);
    trade.SetDeviationInPoints(30);
    g_referenceAccountSize = AccountInfoDouble(ACCOUNT_BALANCE);
    if(g_referenceAccountSize <= 0.0)
        g_referenceAccountSize = AccountInfoDouble(ACCOUNT_EQUITY);
    g_lastLineCount = (InpSignalMode == SIGNAL_MODE_REPLAY && InpReplayExistingSignals) ? 0 : CountLines(InpSignalFile);
    if(InpSignalMode == SIGNAL_MODE_REPLAY)
        LoadSignals();

    PrintFormat("phantom_signal_reader initialized v1.5 | magic=%d | mode=%s | replay=%s | start_line=%d | loaded=%d",
                     InpMagicNumber,
                     InpSignalMode == SIGNAL_MODE_REPLAY ? "replay" : "live",
                     InpReplayExistingSignals ? "true" : "false",
                     g_lastLineCount,
                     ArraySize(g_signals));
    double vol_min, vol_step, vol_max;
    int vol_digits;
    GetVolumeSpec(vol_min, vol_step, vol_max, vol_digits);
    PrintFormat("volume constraints | symbol=%s | min=%.8f | step=%.8f | max=%.8f | digits=%d | units_per_lot=%.8f",
                _Symbol,
                vol_min,
                vol_step,
                vol_max,
                vol_digits,
                GetUnitsPerLot());
    EventSetTimer(1);
    return INIT_SUCCEEDED;
}

void OnTick()
{
    if(InpSignalMode == SIGNAL_MODE_REPLAY)
        ProcessSignalsReplay();
    else
        ProcessSignalsLive();

    ManageTrailingStops();
}

void OnTimer()
{
    ManageTrailingStops();
}

void OnDeinit(const int reason)
{
    EventKillTimer();
}