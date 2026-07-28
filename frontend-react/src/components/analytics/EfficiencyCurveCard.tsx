import { useMemo } from 'react';
import { Gauge } from 'lucide-react';
import {
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { MinerListEntry } from '@/lib/types';

interface EfficiencyCurveCardProps {
  miners: MinerListEntry[];
}

export function EfficiencyCurveCard({ miners }: EfficiencyCurveCardProps) {
  // Aggregate operating points per miner: Frequency (MHz), Power (W), Hashrate (TH/s), J/TH efficiency
  const chartData = useMemo(() => {
    return miners
      .filter((m) => m.last_metric && m.last_metric.frequency_mhz && m.last_metric.hashrate_ths && m.last_metric.hashrate_ths > 0)
      .map((m) => {
        const freq = m.last_metric?.frequency_mhz ?? 0;
        const hr = m.last_metric?.hashrate_ths ?? 0;
        const power = m.last_metric?.power_w ?? 0;
        const jTh = hr > 0 && power > 0 ? Number((power / hr).toFixed(1)) : null;
        return {
          name: m.name || `Miner #${m.id}`,
          freq,
          hashrate: Number(hr.toFixed(2)),
          power: Number(power.toFixed(1)),
          efficiency: jTh,
        };
      })
      .sort((a, b) => a.freq - b.freq);
  }, [miners]);

  if (!chartData.length) return null;

  return (
    <Card className="border-border/60">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-emerald-500/15 text-emerald-400">
              <Gauge className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-base font-semibold">Efficiency & Frequency Operating Curve</CardTitle>
              <CardDescription>
                Power efficiency (J/TH) vs Operating Frequency (MHz) across active miners
              </CardDescription>
            </div>
          </div>
          <Badge variant="outline" className="font-mono text-xs">
            {chartData.length} Active Miner{chartData.length > 1 ? 's' : ''}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
              <XAxis
                dataKey="name"
                stroke="rgba(255,255,255,0.4)"
                tick={{ fontSize: 11 }}
              />
              <YAxis
                yAxisId="left"
                unit=" J/TH"
                stroke="#10b981"
                tick={{ fontSize: 11 }}
                label={{ value: 'Efficiency (J/TH)', angle: -90, position: 'insideLeft', fill: '#10b981', fontSize: 11 }}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                unit=" TH/s"
                stroke="#38bdf8"
                tick={{ fontSize: 11 }}
                label={{ value: 'Hashrate (TH/s)', angle: 90, position: 'insideRight', fill: '#38bdf8', fontSize: 11 }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0f172a',
                  borderColor: 'rgba(255,255,255,0.15)',
                  borderRadius: '8px',
                  fontSize: '12px',
                }}
              />
              <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
              <Bar yAxisId="left" dataKey="efficiency" name="Efficiency (J/TH)" fill="#10b981" radius={[4, 4, 0, 0]} opacity={0.8} />
              <Line yAxisId="right" type="monotone" dataKey="hashrate" name="Hashrate (TH/s)" stroke="#38bdf8" strokeWidth={2.5} dot={{ r: 4 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
