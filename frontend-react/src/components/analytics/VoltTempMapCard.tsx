import { useMemo } from 'react';
import { ThermometerSnowflake } from 'lucide-react';
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { MinerListEntry } from '@/lib/types';

interface VoltTempMapCardProps {
  miners: MinerListEntry[];
}

export function VoltTempMapCard({ miners }: VoltTempMapCardProps) {
  // Scatter points: Voltage (mV) vs Temp (°C)
  const chipData = useMemo(() => {
    return miners
      .filter((m) => m.last_metric && m.last_metric.voltage_mv && m.last_metric.temp_chip_c)
      .map((m) => ({
        name: m.name || `Miner #${m.id}`,
        voltage: m.last_metric?.voltage_mv ?? 1200,
        temp: m.last_metric?.temp_chip_c ?? 0,
        freq: m.last_metric?.frequency_mhz ?? 500,
        vrTemp: m.last_metric?.temp_vr_c ?? null,
      }));
  }, [miners]);

  if (!chipData.length) return null;

  return (
    <Card className="border-border/60">
      <CardHeader>
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-amber-500/15 text-amber-400">
              <ThermometerSnowflake className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-base font-semibold">Voltage & Temperature Scatter Map</CardTitle>
              <CardDescription>
                Correlation mapping between core voltage (mV) and ASIC/VR temperatures (°C)
              </CardDescription>
            </div>
          </div>

          <div className="flex items-center gap-3 text-xs bg-muted/30 px-3 py-1.5 rounded-md border border-border/40">
            <div className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-500 inline-block" />
              <span className="text-muted-foreground">Cool (&lt;58°C)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-amber-500 inline-block" />
              <span className="text-muted-foreground">Warm (58–64°C)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-red-500 inline-block" />
              <span className="text-muted-foreground">Hot (≥65°C)</span>
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
              <XAxis
                type="number"
                dataKey="voltage"
                name="Voltage"
                domain={['auto', 'auto']}
                stroke="rgba(255,255,255,0.4)"
                tick={{ fontSize: 11 }}
                label={{ value: 'Core Voltage (mV)', position: 'bottom', offset: 5, fill: 'rgba(255,255,255,0.6)', fontSize: 11 }}
              />
              <YAxis
                type="number"
                dataKey="temp"
                name="ASIC Temp"
                domain={['auto', 'auto']}
                stroke="rgba(255,255,255,0.4)"
                tick={{ fontSize: 11 }}
                label={{ value: 'ASIC Temp (°C)', angle: -90, position: 'insideLeft', fill: 'rgba(255,255,255,0.6)', fontSize: 11 }}
              />
              <Tooltip
                cursor={{ strokeDasharray: '3 3' }}
                contentStyle={{
                  backgroundColor: '#0f172a',
                  borderColor: 'rgba(255,255,255,0.15)',
                  borderRadius: '8px',
                  fontSize: '12px',
                }}
                formatter={(val: number, name: string) => [
                  name === 'Voltage' ? `${val} mV` : `${val}°C`,
                  name,
                ]}
              />
              <Scatter name="ASIC Chip Temperature" data={chipData}>
                {chipData.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={entry.temp >= 65 ? '#ef4444' : entry.temp >= 58 ? '#f97316' : '#10b981'}
                  />
                ))}
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
