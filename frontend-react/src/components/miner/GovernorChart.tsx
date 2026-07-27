import { useState } from 'react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useGovernorHistory } from '@/api/hooks';
import { Button } from '@/components/ui/button';

interface Props {
  minerId: number;
  governorType: 'guardian' | 'autofan';
  title?: string;
  hasMultipleFans?: boolean;
}

export function GovernorChart({ minerId, governorType, title, hasMultipleFans }: Props) {
  const [hours, setHours] = useState(24);
  const { data, isLoading } = useGovernorHistory(minerId, hours);

  const rawHistory = data?.history ?? [];
  const filteredHistory = rawHistory.filter(
    (d) => d.governor_type === governorType
  );

  const chartData = filteredHistory.map((d) => {
    const timeStr = new Date(d.ts * 1000).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
    return {
      time: timeStr,
      chip_temp: d.chip_temp != null ? Number(d.chip_temp.toFixed(1)) : null,
      vr_temp: d.vr_temp != null ? Number(d.vr_temp.toFixed(1)) : null,
      target_chip: d.target_chip_temp != null ? Number(d.target_chip_temp) : null,
      target_vr: d.target_vr_temp != null ? Number(d.target_vr_temp) : null,
      freq: d.details?.freq_to != null ? Number(d.details.freq_to) : null,
      fan1: d.details?.fan1_pct != null ? Number(d.details.fan1_pct) : null,
      fan2: d.details?.fan2_pct != null ? Number(d.details.fan2_pct) : null,
    };
  });

  const showFan2 = Boolean(hasMultipleFans && chartData.some((d) => d.fan2 != null && d.fan2 !== d.fan1));

  return (
    <div className="border border-border rounded-lg bg-card/40 p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold">
          {title || `${governorType === 'guardian' ? 'Guardian Frequency' : 'Auto-Fan Control'} History`}
        </h4>
        <div className="flex items-center gap-1 text-xs">
          <span className="text-muted-foreground mr-1">Range:</span>
          {[6, 12, 24, 48].map((h) => (
            <Button
              key={h}
              size="sm"
              variant={hours === h ? 'default' : 'subtle'}
              onClick={() => setHours(h)}
              className="h-6 text-xs px-2"
            >
              {h}h
            </Button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="h-48 flex items-center justify-center text-xs text-muted-foreground">
          Loading chart data...
        </div>
      ) : chartData.length === 0 ? (
        <div className="h-48 flex items-center justify-center text-xs text-muted-foreground">
          No governor activity recorded in the past {hours} hours.
        </div>
      ) : (
        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
              <XAxis dataKey="time" tick={{ fontSize: 10 }} stroke="currentColor" opacity={0.5} />
              <YAxis
                yAxisId="temp"
                domain={['auto', 'auto']}
                tick={{ fontSize: 10 }}
                stroke="#38bdf8"
                label={{ value: '°C', angle: -90, position: 'insideLeft', style: { fontSize: 10, fill: '#38bdf8' } }}
              />
              <YAxis
                yAxisId="ctrl"
                orientation="right"
                domain={governorType === 'guardian' ? ['auto', 'auto'] : [0, 100]}
                tick={{ fontSize: 10 }}
                stroke={governorType === 'guardian' ? '#a855f7' : '#22c55e'}
                label={{
                  value: governorType === 'guardian' ? 'MHz' : '%',
                  angle: 90,
                  position: 'insideRight',
                  style: { fontSize: 10, fill: governorType === 'guardian' ? '#a855f7' : '#22c55e' },
                }}
              />
              <Tooltip
                contentStyle={{ backgroundColor: 'rgba(15, 23, 42, 0.9)', borderColor: 'rgba(255, 255, 255, 0.1)', fontSize: '11px', borderRadius: '6px' }}
              />
              <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '4px' }} />

              {/* Temperatures */}
              <Line yAxisId="temp" type="monotone" dataKey="chip_temp" name="ASIC Temp (°C)" stroke="#38bdf8" strokeWidth={2} dot={false} />
              <Line yAxisId="temp" type="monotone" dataKey="vr_temp" name="VR Temp (°C)" stroke="#f97316" strokeWidth={2} dot={false} />
              <Line yAxisId="temp" type="monotone" dataKey="target_chip" name="Target ASIC (°C)" stroke="#94a3b8" strokeDasharray="4 4" dot={false} />

              {/* Controller outputs */}
              {governorType === 'guardian' ? (
                <Line yAxisId="ctrl" type="stepAfter" dataKey="freq" name="Freq (MHz)" stroke="#a855f7" strokeWidth={2.5} dot={false} />
              ) : showFan2 ? (
                <>
                  <Line yAxisId="ctrl" type="monotone" dataKey="fan1" name="Fan 1 (%)" stroke="#22c55e" strokeWidth={2} dot={false} />
                  <Line yAxisId="ctrl" type="monotone" dataKey="fan2" name="Fan 2 (%)" stroke="#eab308" strokeDasharray="3 3" strokeWidth={1.5} dot={false} />
                </>
              ) : (
                <Line yAxisId="ctrl" type="monotone" dataKey="fan1" name="Fan Speed (%)" stroke="#22c55e" strokeWidth={2} dot={false} />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
