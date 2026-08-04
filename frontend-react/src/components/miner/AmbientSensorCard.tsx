import { useState } from 'react';
import { Thermometer } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useAmbiTempStatus, useSetAmbientSensor } from '@/api/hooks';
import type { MinerDetailResponse } from '@/lib/types';

interface Props {
  data: MinerDetailResponse;
}

export function AmbientSensorCard({ data }: Props) {
  const miner = data.miner;
  const { data: status } = useAmbiTempStatus();
  const setSensor = useSetAmbientSensor(miner.id);
  const [msg, setMsg] = useState<string | null>(null);

  const pushSensors = status?.push_sensors ?? [];
  const pullSensors = status?.pull_sensors ?? [];
  const allSensors: any[] = [
    ...pushSensors,
    ...pullSensors
      .filter((p: any) => p.online && p.sensor_id)
      .map((p: any) => ({
        sensor_id: p.sensor_id,
        name: p.name || p.host,
        current_c: p.temp_c,
      })),
  ];

  async function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const val = e.target.value;
    setMsg(null);
    if (!val) {
      await setSensor.mutateAsync({ sensorId: null, name: null });
      setMsg('Unassigned ambient sensor.');
    } else {
      const match = allSensors.find((s) => s.sensor_id === val);
      const name = match ? match.name || match.sensor_id : val;
      await setSensor.mutateAsync({ sensorId: val, name });
      setMsg(`Assigned ambient sensor ${name}.`);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Thermometer className="h-5 w-5 text-emerald-400" />
          Ambient Sensor (Room Assignment)
        </CardTitle>
        <CardDescription>
          Associate this miner with a room temperature sensor to overlay ambient temperatures on your history graphs and track thermal delta.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {msg && (
          <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-300">
            {msg}
          </div>
        )}
        <div className="flex items-center gap-3">
          <select
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring"
            value={miner.ambient_sensor_id || ''}
            onChange={handleChange}
            disabled={setSensor.isPending}
          >
            <option value="">No Room Sensor Assigned</option>
            {allSensors.map((s) => (
              <option key={s.sensor_id} value={s.sensor_id}>
                {s.name || 'Unnamed Sensor'} ({s.sensor_id}) — {s.current_c !== null && s.current_c !== undefined ? `${s.current_c}°C` : 'Offline'}
              </option>
            ))}
          </select>
        </div>
      </CardContent>
    </Card>
  );
}
