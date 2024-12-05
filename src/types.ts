// src/types.ts
export interface ChartAnalysis {
    overallTrend: string;
    confidenceLevels: number[];
    insights: string[];
    marketStructure: MarketStructure;
    tradeSetup: TradeSetup;
}

export interface MarketStructure {
    trend: {
        direction: 'bullish' | 'bearish' | 'neutral';
        strength: number;
    };
    keyLevels: {
        support: number[];
        resistance: number[];
    };
    orderBlocks: OrderBlock[];
    liquidityZones: LiquidityZone[];
    fairValueGaps: FairValueGap[];
}

export interface OrderBlock {
    price: number;
    type: 'buy' | 'sell';
    strength: number;
}

export interface LiquidityZone {
    price: number;
    volume: number;
    type: 'buy' | 'sell';
}

export interface FairValueGap {
    startPrice: number;
    endPrice: number;
    significance: number;
}

export interface TradeSetup {
    type: string;
    entry: number;
    stopLoss: number;
    targets: number[];
    timeframe: string;
    confidence: number;
    setup: string;
}

export interface ImageAnalysisResult {
    success: boolean;
    analysis: ChartAnalysis;
    error?: string;
}