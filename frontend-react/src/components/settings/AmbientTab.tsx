import { useState } from 'react';
import { RefreshCw, Plus, Trash2, Search, CheckCircle2, AlertCircle, Wifi, Cpu } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { useAmbiTempStatus, useSaveAmbiTempHosts, useUpdateAmbiTempHost, useMiners, useSetAmbientSensor } from '@/api/hooks';
import { api } from '@/lib/api';

function MinerAmbientRow({ miner, availableSensors, onMsg }: { miner: any; availableSensors: any[]; onMsg: (msg: string) => void }) {
  const setSensor = useSetAmbientSensor(miner.id);

  async function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const val = e.target.value;
    if (!val) {
      await setSensor.mutateAsync({ sensorId: null, name: null });
      onMsg(`Unassigned ambient sensor from ${miner.name || miner.host}`);
    } else {
      const match = availableSensors.find((s) => s.sensor_id === val);
      const name = match ? match.name || match.sensor_id : val;
      await setSensor.mutateAsync({ sensorId: val, name });
      onMsg(`Assigned ambient sensor ${name} to ${miner.name || miner.host}`);
    }
  }

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between p-3">
      <div>
        <div className="font-semibold text-sm">{miner.name || miner.host}</div>
        <div className="text-xs text-muted-foreground font-mono">{miner.host} · {miner.family.toUpperCase()}</div>
      </div>
      <div className="flex items-center gap-3">
        <select
          className="rounded-md border border-input bg-background px-3 py-1.5 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring"
          value={miner.ambient_sensor_id || ''}
          onChange={handleChange}
          disabled={setSensor.isPending}
        >
          <option value="">No Room Sensor Assigned</option>
          {availableSensors.map((s) => (
            <option key={s.sensor_id} value={s.sensor_id}>
              {s.name || 'Unnamed Sensor'} ({s.sensor_id}) — {s.current_c !== null && s.current_c !== undefined ? `${s.current_c}°C` : 'Offline'}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

export function AmbientTab() {
  const { data: status } = useAmbiTempStatus();
  const { data: minersData } = useMiners();
  const saveHosts = useSaveAmbiTempHosts();
  const updateHost = useUpdateAmbiTempHost();

  const [newHost, setNewHost] = useState('');
  const [isScanning, setIsScanning] = useState(false);
  const [scanResult, setScanResult] = useState<{ cidr?: string; discovered?: any[]; error?: string } | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const pushSensors = status?.push_sensors ?? [];
  const pullSensors = status?.pull_sensors ?? [];
  const configuredHosts: string[] = status?.configured_hosts ?? [];
  const miners = minersData?.miners ?? [];

  // Combine active push and pull sensors for dropdown assignment
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

  async function handleAddHost() {
    if (!newHost.trim()) return;
    const clean = newHost.trim();
    if (configuredHosts.includes(clean)) {
      setActionMsg(`Host ${clean} is already configured.`);
      return;
    }
    const updated = [...configuredHosts, clean];
    await saveHosts.mutateAsync(updated);
    setNewHost('');
    setActionMsg(`Added pull host ${clean}`);
  }

  async function handleRemoveHost(hostToRemove: string) {
    const updated = configuredHosts.filter((h) => h !== hostToRemove);
    await saveHosts.mutateAsync(updated);
    setActionMsg(`Removed pull host ${hostToRemove}`);
  }

  async function handleTriggerPoll() {
    try {
      await api('/api/ambitemp/poll', { method: 'POST' });
      setActionMsg('Triggered poll cycle for temperature sensors.');
    } catch (err) {
      setActionMsg('Failed to trigger poll cycle.');
    }
  }

  async function handleScanSubnet() {
    setIsScanning(true);
    setActionMsg(null);
    try {
      const res = await api<any>('/api/ambitemp/discover');
      setScanResult(res);
    } catch (err: any) {
      setScanResult({ error: err.message || 'Failed to scan subnet.' });
    } finally {
      setIsScanning(false);
    }
  }

  async function handleUpdateHostIP(oldHost: string, newHostIP: string) {
    await updateHost.mutateAsync({ oldHost, newHost: newHostIP });
    setActionMsg(`Updated sensor host IP from ${oldHost} to ${newHostIP}`);
  }

  return (
    <div className="space-y-6">
      {actionMsg && (
        <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
          {actionMsg}
        </div>
      )}

      {/* Miner Room Associations Card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cpu className="h-5 w-5 text-purple-400" />
            Miner Room Associations
          </CardTitle>
          <CardDescription>
            Associate each miner in your fleet with an ambient temperature sensor for room thermal tracking and history overlays.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {miners.length === 0 ? (
            <p className="text-sm text-muted-foreground italic">No miners registered in fleet.</p>
          ) : (
            <div className="divide-y divide-border rounded-md border">
              {miners.map((m: any) => (
                <MinerAmbientRow key={m.id} miner={m} availableSensors={allSensors} onMsg={setActionMsg} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Push Sensors Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Wifi className="h-5 w-5 text-emerald-400" />
                Push Temperature Sensors
              </CardTitle>
              <CardDescription>
                Sensors pushing readings over HTTP (POST /api/ambient). LAN Auth-Exempt.
              </CardDescription>
            </div>
            <span className="rounded bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-400 border border-emerald-500/20">
              LAN Open
            </span>
          </div>
        </CardHeader>
        <CardContent>
          {pushSensors.length === 0 ? (
            <p className="text-sm text-muted-foreground italic">
              No push sensors currently active. Devices can POST to <code className="text-xs text-primary font-mono">/api/ambient</code> with <code className="text-xs text-primary font-mono">{`{"temp_c": 23.5, "name": "Garage", "sensor_id": "a1b2c3d4e5f6"}`}</code>.
            </p>
          ) : (
            <div className="divide-y divide-border rounded-md border">
              {pushSensors.map((s: any) => (
                <div key={s.sensor_id} className="flex items-center justify-between p-3">
                  <div>
                    <div className="font-semibold text-sm">{s.name || 'Unnamed Sensor'}</div>
                    <div className="text-xs text-muted-foreground font-mono">ID: {s.sensor_id}</div>
                  </div>
                  <div className="flex items-center gap-4 text-right">
                    <div>
                      <div className="text-base font-bold">
                        {s.available && s.current_c !== null ? `${s.current_c}°C` : '—'}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Min {s.min_c ?? '—'}°C / Max {s.max_c ?? '—'}°C
                      </div>
                    </div>
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                        s.available
                          ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                          : 'bg-muted text-muted-foreground'
                      }`}
                    >
                      {s.available ? 'Active' : 'Stale'}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pull Sensors Configuration Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <RefreshCw className="h-5 w-5 text-blue-400" />
                Pull Temperature Sensors (HTTP GET)
              </CardTitle>
              <CardDescription>
                Configure external sensors (ESP32/CYD/AmbiTemp) polled over HTTP at <code className="text-xs font-mono">GET /api/readings</code>.
              </CardDescription>
            </div>
            <Button size="sm" variant="outline" onClick={handleTriggerPoll}>
              <RefreshCw className="h-4 w-4 mr-1" />
              Poll Now
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <Input
              placeholder="Sensor IP or hostname (e.g. 192.168.4.200)"
              value={newHost}
              onChange={(e) => setNewHost(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAddHost()}
            />
            <Button onClick={handleAddHost} disabled={saveHosts.isPending}>
              <Plus className="h-4 w-4 mr-1" />
              Add Host
            </Button>
          </div>

          {configuredHosts.length === 0 ? (
            <p className="text-sm text-muted-foreground italic">
              No pull sensor hosts configured. Add a host IP above or scan the subnet below.
            </p>
          ) : (
            <div className="divide-y divide-border rounded-md border">
              {pullSensors.map((p: any) => (
                <div key={p.host} className="flex items-center justify-between p-3">
                  <div>
                    <div className="font-semibold text-sm flex items-center gap-2">
                      {p.name || p.host}
                      {p.online ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                      ) : (
                        <AlertCircle className="h-4 w-4 text-destructive" />
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground font-mono">
                      {p.host} {p.sensor_id ? `(${p.sensor_id})` : ''}
                    </div>
                  </div>

                  <div className="flex items-center gap-4">
                    <div className="text-right">
                      {p.online && p.temp_c !== undefined ? (
                        <span className="text-base font-bold">{p.temp_c}°C</span>
                      ) : (
                        <span className="text-xs text-destructive">{p.error || 'Offline'}</span>
                      )}
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive hover:bg-destructive/10"
                      onClick={() => handleRemoveHost(p.host)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Network Discovery Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Search className="h-5 w-5 text-amber-400" />
                LAN Subnet Temperature Sensor Scanner
              </CardTitle>
              <CardDescription>
                Auto-discover temperature sensors on your local network and automatically update moved IP addresses.
              </CardDescription>
            </div>
            <Button onClick={handleScanSubnet} disabled={isScanning}>
              <Search className="h-4 w-4 mr-1" />
              {isScanning ? 'Scanning Subnet…' : 'Scan Subnet'}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {scanResult?.error && (
            <div className="rounded border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {scanResult.error}
            </div>
          )}

          {scanResult && !scanResult.error && (
            <div className="space-y-3">
              <div className="text-xs text-muted-foreground">
                Scanned subnet <code className="font-mono">{scanResult.cidr}</code> ({(scanResult as any).total_scanned} hosts). Found {scanResult.discovered?.length || 0} active temperature sensors.
              </div>

              {scanResult.discovered?.length === 0 ? (
                <p className="text-sm text-muted-foreground italic">No temperature sensors responded on this subnet.</p>
              ) : (
                <div className="divide-y divide-border rounded-md border">
                  {scanResult.discovered?.map((d: any) => {
                    const isConfigured = configuredHosts.includes(d.ip);
                    const matchingOldHost = pullSensors.find(
                      (p: any) => p.sensor_id && p.sensor_id === d.sensor_id && p.host !== d.ip
                    )?.host;

                    return (
                      <div key={d.ip} className="flex items-center justify-between p-3">
                        <div>
                          <div className="font-semibold text-sm flex items-center gap-2">
                            {d.name}
                            <span className="text-xs text-muted-foreground font-mono">({d.ip})</span>
                          </div>
                          <div className="text-xs text-muted-foreground font-mono">ID: {d.sensor_id}</div>
                        </div>

                        <div className="flex items-center gap-3">
                          <span className="text-sm font-bold">{d.temp_c}°C</span>

                          {matchingOldHost ? (
                            <Button
                              size="sm"
                              className="bg-amber-600 hover:bg-amber-500 text-white"
                              onClick={() => handleUpdateHostIP(matchingOldHost, d.ip)}
                            >
                              Update IP (Moved from {matchingOldHost})
                            </Button>
                          ) : isConfigured ? (
                            <span className="text-xs font-semibold text-emerald-400">Configured</span>
                          ) : (
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() => {
                                handleAddHost();
                                setNewHost(d.ip);
                              }}
                            >
                              Add to Poller
                            </Button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
