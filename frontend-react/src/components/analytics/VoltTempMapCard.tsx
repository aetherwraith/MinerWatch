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
  Legend,
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
                unit=" mV"
                domain={['auto', 'auto']}
                stroke="rgba(255,255,255,0.4)"
                tick={{ fontSize: 11 }}
                label={{ value: 'Core Voltage (mV)', position: 'bottom', offset: 5, fill: 'rgba(255,255,255,0.6)', fontSize: 11 }}
              />
              <YAxis
                type="number"
                dataKey="temp"
                name="ASIC Temp"
                unit="°C"
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
              <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
              <Scatter name="ASIC Chip Temperature" data={chipData} fill="#f97316">
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
