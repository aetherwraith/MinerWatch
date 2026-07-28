import { useMemo } from 'react';
import { Sparkles } from 'lucide-react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { PredictionResponse } from '@/lib/types';

interface PoissonLuckCardProps {
  prediction: PredictionResponse | null;
}

export function PoissonLuckCard({ prediction }: PoissonLuckCardProps) {
  // Generate Poisson distribution points from 0% to 300% expected shares
  const points = useMemo(() => {
    const data = [];
    for (let pct = 0; pct <= 300; pct += 10) {
      const lambda = pct / 100;
      // Probability of finding AT LEAST 1 block by lambda expected shares
      const prob = (1 - Math.exp(-lambda)) * 100;
      data.push({
        expectedPct: pct,
        probability: Number(prob.toFixed(2)),
      });
    }
    return data;
  }, []);

  const totalTHs = prediction?.fleet_hashrate_ths ?? 0;

  return (
    <Card className="border-border/60">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-chart-mining/15 text-chart-mining">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-base font-semibold">Poisson Luck & Probability Curve</CardTitle>
              <CardDescription>
                Theoretical cumulative probability of finding a block vs expected shares submitted
              </CardDescription>
            </div>
          </div>
          {totalTHs > 0 && (
            <Badge variant="secondary" className="font-mono text-xs">
              Fleet: {totalTHs.toFixed(2)} TH/s
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
              <defs>
                <linearGradient id="poissonGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
              <XAxis
                dataKey="expectedPct"
                unit="%"
                stroke="rgba(255,255,255,0.4)"
                tick={{ fontSize: 11 }}
                label={{ value: 'Expected Shares Submitted (%)', position: 'bottom', offset: 5, fill: 'rgba(255,255,255,0.6)', fontSize: 11 }}
              />
              <YAxis
                unit="%"
                domain={[0, 100]}
                stroke="rgba(255,255,255,0.4)"
                tick={{ fontSize: 11 }}
                label={{ value: 'Chance of Finding Block', angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.6)', fontSize: 11 }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0f172a',
                  borderColor: 'rgba(255,255,255,0.15)',
                  borderRadius: '8px',
                  fontSize: '12px',
                }}
                formatter={(val: number) => [`${val}%`, 'Probability']}
                labelFormatter={(label) => `Expected Shares: ${label}%`}
              />
              <ReferenceLine x={100} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: '100% (Expected)', fill: '#f59e0b', fontSize: 11 }} />
              <ReferenceLine y={63.2} stroke="#10b981" strokeDasharray="3 3" label={{ value: '63.2% at 100% Shares', fill: '#10b981', fontSize: 11 }} />
              <Area
                type="monotone"
                dataKey="probability"
                stroke="#38bdf8"
                strokeWidth={2}
                fillOpacity={1}
                fill="url(#poissonGrad)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2 text-xs">
          <div className="p-3 rounded-lg border border-border/50 bg-muted/20">
            <span className="text-muted-foreground">50% Expected Shares</span>
            <div className="text-base font-semibold text-foreground">39.3% Block Chance</div>
            <p className="text-[11px] text-muted-foreground mt-0.5">4 in 10 mining rounds find a block before 50% shares</p>
          </div>
          <div className="p-3 rounded-lg border border-border/50 bg-muted/20">
            <span className="text-muted-foreground">100% Expected Shares</span>
            <div className="text-base font-semibold text-emerald-400">63.2% Block Chance</div>
            <p className="text-[11px] text-muted-foreground mt-0.5">Statistical median threshold for solo mining</p>
          </div>
          <div className="p-3 rounded-lg border border-border/50 bg-muted/20">
            <span className="text-muted-foreground">200% Expected Shares</span>
            <div className="text-base font-semibold text-amber-400">86.5% Block Chance</div>
            <p className="text-[11px] text-muted-foreground mt-0.5">Only 13.5% of rounds take more than double expected shares</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
