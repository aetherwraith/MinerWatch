import { useMemo } from 'react';
import { ShieldAlert } from 'lucide-react';
import {
  ComposedChart,
  Line,
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

interface ColdDropWatchCardProps {
  miners: MinerListEntry[];
}

export function ColdDropWatchCard({ miners }: ColdDropWatchCardProps) {
  // Map miner thermal status for cold-drop & thermal stability monitoring
  const thermalStatus = useMemo(() => {
    return miners.map((m) => {
      const chipTemp = m.last_metric?.temp_chip_c ?? 0;
      const vrTemp = m.last_metric?.temp_vr_c ?? null;
      const hr = m.last_metric?.hashrate_ths ?? 0;
      const fan = m.last_metric?.fan_pct ?? null;

      // Identify potential cold drop / thermal disturbance state:
      // VR or ASIC temp is cool (< 52°C) while fan is at high speed (> 85%), or big VR-to-chip delta (> 18°C)
      const coldDropActive = (chipTemp > 0 && chipTemp < 52 && fan !== null && fan > 85) || (vrTemp !== null && (chipTemp - vrTemp > 18 || vrTemp - chipTemp > 18));

      return {
        id: m.id,
        name: m.name || `Miner #${m.id}`,
        chipTemp,
        vrTemp,
        hashrate: Number(hr.toFixed(2)),
        fan,
        coldDropActive,
      };
    });
  }, [miners]);

  const coldDropCount = thermalStatus.filter((t) => t.coldDropActive).length;

  if (!thermalStatus.length) return null;

  return (
    <Card className="border-border/60">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-cyan-500/15 text-cyan-400">
              <ShieldAlert className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-base font-semibold">Cold-Drop & Thermal Shock Watch</CardTitle>
              <CardDescription>
                Monitors rapid thermal drops, ambient cold intake, and fan surges affecting hashrate stability
              </CardDescription>
            </div>
          </div>
          <Badge variant={coldDropCount > 0 ? 'destructive' : 'secondary'} className="font-mono text-xs">
            {coldDropCount > 0 ? `${coldDropCount} Thermal Alert` : 'Thermal Stable'}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={thermalStatus} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
              <XAxis
                dataKey="name"
                stroke="rgba(255,255,255,0.4)"
                tick={{ fontSize: 11 }}
              />
              <YAxis
                yAxisId="temp"
                unit="°C"
                stroke="#f97316"
                tick={{ fontSize: 11 }}
                label={{ value: 'Temp (°C)', angle: -90, position: 'insideLeft', fill: '#f97316', fontSize: 11 }}
              />
              <YAxis
                yAxisId="hash"
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
              <Line yAxisId="temp" type="monotone" dataKey="chipTemp" name="ASIC Temp (°C)" stroke="#f97316" strokeWidth={2} dot={{ r: 4 }} />
              <Line yAxisId="temp" type="monotone" dataKey="vrTemp" name="VR Temp (°C)" stroke="#a855f7" strokeWidth={2} strokeDasharray="4 4" dot={{ r: 3 }} />
              <Line yAxisId="hash" type="monotone" dataKey="hashrate" name="Hashrate (TH/s)" stroke="#38bdf8" strokeWidth={2.5} dot={{ r: 4 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        {coldDropCount > 0 && (
          <div className="p-3 rounded-lg border border-amber-500/30 bg-amber-500/10 text-amber-200 text-xs">
            <span className="font-semibold">Thermal Disturbance Notice:</span> One or more miners are experiencing high fan speeds with low temperatures or large VR-to-chip delta. Verify ambient airflow and fan PID settings.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
