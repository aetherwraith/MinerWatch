import { useState } from 'react';
import { BarChart3, Sparkles, Gauge, ShieldAlert } from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { PredictionsCard } from '@/components/analytics/PredictionsCard';
import { TopSharesCard } from '@/components/analytics/TopSharesCard';
import { PoissonLuckCard } from '@/components/analytics/PoissonLuckCard';
import { EfficiencyCurveCard } from '@/components/analytics/EfficiencyCurveCard';
import { VoltTempMapCard } from '@/components/analytics/VoltTempMapCard';
import { ColdDropWatchCard } from '@/components/analytics/ColdDropWatchCard';
import { useFleetBestTop, useFleetPrediction, useMiners } from '@/api/hooks';
import type { PredictionCoin } from '@/lib/types';

export function AnalyticsPage() {
  const [activeTab, setActiveTab] = useState<'overview' | 'luck' | 'efficiency' | 'thermal'>('overview');
  // Coin for the "Find a block (solo)" odds — 'auto' = the coin we're mining.
  const [coin, setCoin] = useState<PredictionCoin>('auto');
  const { data: predData } = useFleetPrediction(coin);
  const { data: topData } = useFleetBestTop('alltime', 10);
  const { data: minersData } = useMiners();

  const prediction = predData ?? null;
  const top = topData ?? null;
  const miners = minersData?.miners ?? [];

  const predVisible = !!(prediction && prediction.fleet_hashrate_ths && prediction.best_alltime);
  const topVisible = !!top?.entries?.length;
  const anythingVisible = predVisible || topVisible || miners.length > 0;

  return (
    <div className="space-y-5">
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Analytics & Diagnostics</h1>
          <p className="text-sm text-muted-foreground">
            Statistical predictions, efficiency curves, and thermal drop analytics
          </p>
        </div>
        <div className="flex items-center gap-1.5 bg-muted/40 p-1 rounded-lg border border-border/50 text-xs self-start sm:self-auto">
          <Button
            variant={activeTab === 'overview' ? 'default' : 'ghost'}
            size="sm"
            onClick={() => setActiveTab('overview')}
            className="h-8 px-3 text-xs"
          >
            <BarChart3 className="h-3.5 w-3.5 mr-1.5" />
            Overview
          </Button>
          <Button
            variant={activeTab === 'luck' ? 'default' : 'ghost'}
            size="sm"
            onClick={() => setActiveTab('luck')}
            className="h-8 px-3 text-xs"
          >
            <Sparkles className="h-3.5 w-3.5 mr-1.5" />
            Luck Curve
          </Button>
          <Button
            variant={activeTab === 'efficiency' ? 'default' : 'ghost'}
            size="sm"
            onClick={() => setActiveTab('efficiency')}
            className="h-8 px-3 text-xs"
          >
            <Gauge className="h-3.5 w-3.5 mr-1.5" />
            Efficiency & Volt/Temp
          </Button>
          <Button
            variant={activeTab === 'thermal' ? 'default' : 'ghost'}
            size="sm"
            onClick={() => setActiveTab('thermal')}
            className="h-8 px-3 text-xs"
          >
            <ShieldAlert className="h-3.5 w-3.5 mr-1.5" />
            Cold-Drop Watch
          </Button>
        </div>
      </header>

      {activeTab === 'overview' && (
        <div className="space-y-5">
          <PredictionsCard data={prediction} coin={coin} onCoinChange={setCoin} />
          <TopSharesCard data={top} miners={miners} />
        </div>
      )}

      {activeTab === 'luck' && (
        <div className="space-y-5">
          <PoissonLuckCard prediction={prediction} />
        </div>
      )}

      {activeTab === 'efficiency' && (
        <div className="space-y-5">
          <EfficiencyCurveCard miners={miners} />
          <VoltTempMapCard miners={miners} />
        </div>
      )}

      {activeTab === 'thermal' && (
        <div className="space-y-5">
          <ColdDropWatchCard miners={miners} />
        </div>
      )}

      {!anythingVisible && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-md bg-chart-mining/15 text-chart-mining">
                <BarChart3 className="h-5 w-5" />
              </div>
              <div>
                <CardTitle>No data yet</CardTitle>
                <CardDescription>Add a miner and let it run for a few minutes</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              As soon as a miner accepts its first share, Predictions and the Top best shares
              leaderboard populate automatically. Head over to{' '}
              <a className="text-primary hover:underline" href="/">
                the Dashboard
              </a>{' '}
              to add one if you haven't already.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
