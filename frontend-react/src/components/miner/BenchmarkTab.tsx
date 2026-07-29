import { useState, useEffect, useMemo } from 'react';
import { Gauge, Play, Square, Sparkles, Rocket, RefreshCw, CheckCircle2 } from 'lucide-react';
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
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';

import {
  useMinerBenchmarkStatus,
  useStartBenchmark,
  useCancelBenchmark,
  useApplyBenchmarkProfile,
} from '@/api/hooks';
import type { BenchmarkRun } from '@/lib/types';

interface BenchmarkTabProps {
  minerId: number;
}

export function BenchmarkTab({ minerId }: BenchmarkTabProps) {
  const { data, isLoading } = useMinerBenchmarkStatus(minerId);
  const startMutation = useStartBenchmark(minerId);
  const cancelMutation = useCancelBenchmark(minerId);
  const applyMutation = useApplyBenchmarkProfile(minerId);

  const defaults = data?.defaults;
  const running = !!data?.running;
  const latestRun: BenchmarkRun | null = data?.latest_run ?? null;

  // Local config form state
  const [minFreq, setMinFreq] = useState<number>(400);
  const [maxFreq, setMaxFreq] = useState<number>(600);
  const [freqStep, setFreqStep] = useState<number>(25);
  const [minVolt, setMinVolt] = useState<number>(1150);
  const [maxVolt, setMaxVolt] = useState<number>(1300);
  const [voltStep, setVoltStep] = useState<number>(25);
  const [dwellTime, setDwellTime] = useState<number>(30);
  const [maxErrorRate, setMaxErrorRate] = useState<number>(1.1);
  const [benchFanMode, setBenchFanMode] = useState<'pin' | 'firmware' | 'minerwatch'>('pin');
  const [pinFanPct, setPinFanPct] = useState<number>(100);
  const [quietFanMaxPct, setQuietFanMaxPct] = useState<number>(65);
  const [enableMicrotuning, setEnableMicrotuning] = useState<boolean>(false);
  const [microFreqStep, setMicroFreqStep] = useState<number>(5);
  const [microVoltStep, setMicroVoltStep] = useState<number>(10);

  // Sync defaults when data arrives
  useEffect(() => {
    if (defaults) {
      setMinFreq(defaults.min_freq_mhz);
      setMaxFreq(defaults.max_freq_mhz);
      setFreqStep(defaults.freq_step_mhz);
      setMinVolt(defaults.min_voltage_mv);
      setMaxVolt(defaults.max_voltage_mv);
      setVoltStep(defaults.voltage_step_mv);
      setDwellTime(defaults.dwell_time_s);
      setMaxErrorRate(defaults.max_error_rate_pct);
    }
  }, [defaults]);

  const handleStart = () => {
    startMutation.mutate({
      min_freq_mhz: minFreq,
      max_freq_mhz: maxFreq,
      freq_step_mhz: freqStep,
      min_voltage_mv: minVolt,
      max_voltage_mv: maxVolt,
      voltage_step_mv: voltStep,
      dwell_time_s: dwellTime,
      max_error_rate_pct: maxErrorRate,
      fan_mode: benchFanMode,
      pin_fan_pct: benchFanMode === 'pin' ? pinFanPct : null,
      quiet_fan_max_pct: quietFanMaxPct || null,
      enable_microtuning: enableMicrotuning,
      micro_freq_step_mhz: microFreqStep,
      micro_volt_step_mv: microVoltStep,
    });
  };

  const samples = latestRun?.samples ?? [];
  const totalSteps = latestRun?.total_steps || 1;
  const currentStep = latestRun?.current_step || 0;
  const progressPct = Math.min(100, Math.round((currentStep / totalSteps) * 100));

  // Prepared chart data
  const chartData = useMemo(() => {
    return samples.map((s, idx) => ({
      step: idx + 1,
      name: `${s.freq_mhz}MHz / ${s.voltage_mv}mV`,
      freq: s.freq_mhz,
      volt: s.voltage_mv,
      efficiency: s.efficiency_j_th ? Number(s.efficiency_j_th.toFixed(1)) : null,
      hashrate: s.hashrate_ths ? Number(s.hashrate_ths.toFixed(2)) : null,
      chipTemp: s.chip_temp_c ? Number(s.chip_temp_c.toFixed(1)) : null,
      stable: !!s.stable,
    }));
  }, [samples]);

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 p-5 rounded-xl bg-card border border-border/60">
        <div className="flex items-center gap-3.5">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400">
            <Gauge className="h-6 w-6" />
          </div>
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Efficiency Sweet-Spot Benchmarker</h2>
            <p className="text-xs text-muted-foreground">
              Automated frequency & voltage sweep to discover optimal J/TH efficiency and max hashrate profiles
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          {running ? (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
              className="h-9 gap-2"
            >
              <Square className="h-4 w-4 fill-current" />
              Cancel Benchmark
            </Button>
          ) : (
            <Button
              variant="default"
              size="sm"
              onClick={handleStart}
              disabled={startMutation.isPending || isLoading}
              className="h-9 gap-2 bg-emerald-600 hover:bg-emerald-500 text-white"
            >
              <Play className="h-4 w-4 fill-current" />
              Start Sweet-Spot Sweep
            </Button>
          )}
        </div>
      </div>

      {/* Background Server Execution Banner */}
      <div className="flex items-start gap-3 rounded-lg border border-cyan-500/30 bg-cyan-500/10 p-3 text-xs text-cyan-200">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-cyan-400" />
        <span>
          <strong>Asynchronous Server Execution:</strong> Benchmarks execute in a dedicated background process on the MinerWatch server. You can safely close or navigate away from this tab at any time—the sweep continues automatically and progress is synchronized across all browser windows.
        </span>
      </div>

      {/* Sweep Progress Bar & Live Status (When Running) */}
      {running && (
        <Card className="border-emerald-500/50 bg-emerald-500/10">
          <CardContent className="pt-5 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-emerald-300 font-semibold text-sm">
                <RefreshCw className="h-4 w-4 animate-spin text-emerald-400" />
                Benchmark Sweep in Progress...
                <Badge variant="outline" className="font-mono text-xs bg-emerald-500/20 text-emerald-300 border-emerald-500/40">
                  Step {currentStep} of {totalSteps} ({progressPct}%)
                </Badge>
              </div>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => cancelMutation.mutate()}
                disabled={cancelMutation.isPending}
                className="h-8 text-xs font-semibold gap-1.5"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
                Cancel Benchmark
              </Button>
            </div>

            <div className="h-3 w-full overflow-hidden rounded-full bg-muted/50">
              <div
                className="h-full bg-gradient-to-r from-emerald-500 via-cyan-400 to-indigo-500 transition-all duration-500"
                style={{ width: `${progressPct}%` }}
              />
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] font-mono text-muted-foreground pt-1">
              <div>Range: <span className="text-foreground">{minFreq}-{maxFreq} MHz</span></div>
              <div>Volt: <span className="text-foreground">{minVolt}-{maxVolt} mV</span></div>
              <div>Dwell: <span className="text-foreground">{dwellTime}s</span></div>
              <div>Fan Mode: <span className="text-foreground capitalize">{benchFanMode}</span></div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Optimal Candidate Profile Cards (When Completed or Samples Available) */}
      {latestRun && (latestRun.status === 'completed' || latestRun.best_eff_freq) && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Max Efficiency Profile Card */}
          <Card className="border-emerald-500/50 bg-gradient-to-br from-emerald-500/10 to-transparent">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-emerald-400">
                  <Sparkles className="h-5 w-5" />
                  <CardTitle className="text-base font-semibold">Max Efficiency Profile</CardTitle>
                </div>
                <Badge className="bg-emerald-500/20 text-emerald-300 border-emerald-500/30 text-[10px]">
                  Sweet-Spot
                </Badge>
              </div>
              <CardDescription>Lowest energy usage per Terahash (J/TH)</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2.5 rounded-lg border border-border/50 bg-muted/20 font-mono">
                  <span className="text-muted-foreground text-[10px]">Freq / Voltage</span>
                  <div className="text-sm font-bold text-foreground mt-0.5">
                    {latestRun.best_eff_freq ?? '—'} MHz / {latestRun.best_eff_volt ?? '—'} mV
                  </div>
                </div>
                <div className="p-2.5 rounded-lg border border-border/50 bg-muted/20 font-mono">
                  <span className="text-muted-foreground text-[10px]">Efficiency</span>
                  <div className="text-sm font-bold text-emerald-400 mt-0.5">
                    {latestRun.best_eff_j_th ? `${latestRun.best_eff_j_th.toFixed(1)} J/TH` : '—'}
                  </div>
                </div>
              </div>
              <Button
                variant="default"
                size="sm"
                onClick={() => applyMutation.mutate('max_efficiency')}
                disabled={applyMutation.isPending || !latestRun.best_eff_freq}
                className="w-full h-9 bg-emerald-600 hover:bg-emerald-500 text-white font-medium gap-2 text-xs"
              >
                <CheckCircle2 className="h-4 w-4" />
                Apply Max Efficiency
              </Button>
            </CardContent>
          </Card>

          {/* Max Hashrate Profile Card */}
          <Card className="border-cyan-500/50 bg-gradient-to-br from-cyan-500/10 to-transparent">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-cyan-400">
                  <Rocket className="h-5 w-5" />
                  <CardTitle className="text-base font-semibold">Max Hashrate Profile</CardTitle>
                </div>
                <Badge className="bg-cyan-500/20 text-cyan-300 border-cyan-500/30 text-[10px]">
                  Peak Performance
                </Badge>
              </div>
              <CardDescription>Highest mining throughput (TH/s)</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2.5 rounded-lg border border-border/50 bg-muted/20 font-mono">
                  <span className="text-muted-foreground text-[10px]">Freq / Voltage</span>
                  <div className="text-sm font-bold text-foreground mt-0.5">
                    {latestRun.best_hash_freq ?? '—'} MHz / {latestRun.best_hash_volt ?? '—'} mV
                  </div>
                </div>
                <div className="p-2.5 rounded-lg border border-border/50 bg-muted/20 font-mono">
                  <span className="text-muted-foreground text-[10px]">Peak Hashrate</span>
                  <div className="text-sm font-bold text-cyan-400 mt-0.5">
                    {latestRun.best_hash_ths ? `${latestRun.best_hash_ths.toFixed(2)} TH/s` : '—'}
                  </div>
                </div>
              </div>
              <Button
                variant="default"
                size="sm"
                onClick={() => applyMutation.mutate('max_hashrate')}
                disabled={applyMutation.isPending || !latestRun.best_hash_freq}
                className="w-full h-9 bg-cyan-600 hover:bg-cyan-500 text-white font-medium gap-2 text-xs"
              >
                <CheckCircle2 className="h-4 w-4" />
                Apply Max Hashrate
              </Button>
            </CardContent>
          </Card>

          {/* Best Quiet Profile Card */}
          <Card className="border-indigo-500/50 bg-gradient-to-br from-indigo-500/10 to-transparent">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-indigo-400">
                  <Gauge className="h-5 w-5" />
                  <CardTitle className="text-base font-semibold">Best Quiet Profile</CardTitle>
                </div>
                <Badge className="bg-indigo-500/20 text-indigo-300 border-indigo-500/30 text-[10px]">
                  Acoustic Quiet
                </Badge>
              </div>
              <CardDescription>Max performance (TH/s) where Fan ≤ {latestRun.quiet_fan_max_pct ?? 65}%</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2.5 rounded-lg border border-border/50 bg-muted/20 font-mono">
                  <span className="text-muted-foreground text-[10px]">Freq / Voltage</span>
                  <div className="text-sm font-bold text-foreground mt-0.5">
                    {latestRun.best_quiet_freq ? `${latestRun.best_quiet_freq} MHz / ${latestRun.best_quiet_volt} mV` : '—'}
                  </div>
                </div>
                <div className="p-2.5 rounded-lg border border-border/50 bg-muted/20 font-mono">
                  <span className="text-muted-foreground text-[10px]">Quiet Efficiency</span>
                  <div className="text-sm font-bold text-indigo-400 mt-0.5">
                    {latestRun.best_quiet_j_th ? `${latestRun.best_quiet_j_th.toFixed(1)} J/TH` : '—'}
                  </div>
                </div>
              </div>
              <Button
                variant="default"
                size="sm"
                onClick={() => applyMutation.mutate('quiet')}
                disabled={applyMutation.isPending || !latestRun.best_quiet_freq}
                className="w-full h-9 bg-indigo-600 hover:bg-indigo-500 text-white font-medium gap-2 text-xs"
              >
                <CheckCircle2 className="h-4 w-4" />
                Apply Quiet Profile
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Sweep Configuration Controls */}
      <Card className="border-border/60">
        <CardHeader>
          <CardTitle className="text-base font-semibold">Sweep Parameters</CardTitle>
          <CardDescription>
            Configure min/max operating frequency (MHz), core voltage (mV), step sizes, and stability thresholds
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-5">
          {/* Frequency & Voltage Matrix Inputs */}
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 text-xs">
            <div className="space-y-1.5">
              <Label className="text-xs">Min Frequency (MHz)</Label>
              <Input
                type="number"
                value={minFreq}
                onChange={(e) => setMinFreq(Number(e.target.value))}
                disabled={running}
                className="h-8 text-xs font-mono"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Max Frequency (MHz)</Label>
              <Input
                type="number"
                value={maxFreq}
                onChange={(e) => setMaxFreq(Number(e.target.value))}
                disabled={running}
                className="h-8 text-xs font-mono"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Frequency Step (MHz)</Label>
              <Input
                type="number"
                value={freqStep}
                onChange={(e) => setFreqStep(Number(e.target.value))}
                disabled={running}
                className="h-8 text-xs font-mono"
              />
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs">Min Voltage (mV)</Label>
              <Input
                type="number"
                value={minVolt}
                onChange={(e) => setMinVolt(Number(e.target.value))}
                disabled={running}
                className="h-8 text-xs font-mono"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Max Voltage (mV)</Label>
              <Input
                type="number"
                value={maxVolt}
                onChange={(e) => setMaxVolt(Number(e.target.value))}
                disabled={running}
                className="h-8 text-xs font-mono"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Voltage Step (mV)</Label>
              <Input
                type="number"
                value={voltStep}
                onChange={(e) => setVoltStep(Number(e.target.value))}
                disabled={running}
                className="h-8 text-xs font-mono"
              />
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs">Dwell Time per Step (sec)</Label>
              <Input
                type="number"
                value={dwellTime}
                onChange={(e) => setDwellTime(Number(e.target.value))}
                disabled={running}
                className="h-8 text-xs font-mono"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Max Error Rate (%)</Label>
              <Input
                type="number"
                step="0.5"
                value={maxErrorRate}
                onChange={(e) => setMaxErrorRate(Number(e.target.value))}
                disabled={running}
                className="h-8 text-xs font-mono"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Fan Control Mode during Sweep</Label>
              <select
                value={benchFanMode}
                onChange={(e) => setBenchFanMode(e.target.value as any)}
                disabled={running}
                className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs font-mono text-foreground focus:outline-none"
              >
                <option value="pin">Fixed Fan Speed (%)</option>
                <option value="firmware">Firmware Auto (Quiet Search)</option>
                <option value="minerwatch">MinerWatch Auto-Fan</option>
              </select>
            </div>

            {benchFanMode === 'pin' ? (
              <div className="space-y-1.5">
                <Label className="text-xs font-mono">Pinned Fan Speed (%)</Label>
                <Input
                  type="number"
                  min={10}
                  max={100}
                  value={pinFanPct}
                  onChange={(e) => setPinFanPct(Number(e.target.value))}
                  disabled={running}
                  className="h-8 text-xs font-mono"
                />
              </div>
            ) : (
              <div className="space-y-1.5">
                <Label className="text-xs font-mono text-indigo-300">Max Quiet Fan Limit (%)</Label>
                <Input
                  type="number"
                  min={10}
                  max={100}
                  value={quietFanMaxPct}
                  onChange={(e) => setQuietFanMaxPct(Number(e.target.value))}
                  disabled={running}
                  placeholder="e.g. 65"
                  className="h-8 text-xs font-mono border-indigo-500/40 focus:border-indigo-400"
                />
              </div>
            )}
          </div>

          {/* Optional Microtuning Settings */}
          <div className="pt-3 border-t border-border/50 space-y-3 text-xs">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="microtune-chk"
                checked={enableMicrotuning}
                onChange={(e) => setEnableMicrotuning(e.target.checked)}
                disabled={running}
                className="rounded border-border text-emerald-500 focus:ring-emerald-500"
              />
              <label htmlFor="microtune-chk" className="font-semibold text-foreground cursor-pointer select-none">
                Enable Fine Microtuning Sweep (home in on precise optimal point)
              </label>
            </div>

            {enableMicrotuning && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pl-6 pt-1">
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Fine Micro Frequency Step (MHz)</Label>
                  <Input
                    type="number"
                    min={1}
                    max={20}
                    value={microFreqStep}
                    onChange={(e) => setMicroFreqStep(Number(e.target.value))}
                    disabled={running}
                    className="h-8 text-xs font-mono"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Fine Micro Voltage Step (mV)</Label>
                  <Input
                    type="number"
                    min={1}
                    max={20}
                    value={microVoltStep}
                    onChange={(e) => setMicroVoltStep(Number(e.target.value))}
                    disabled={running}
                    className="h-8 text-xs font-mono"
                  />
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Benchmark Sweep Chart */}
      {chartData.length > 0 && (
        <Card className="border-border/60">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base font-semibold">Sweep Combination Matrix</CardTitle>
                <CardDescription>
                  Efficiency (J/TH) vs Hashrate (TH/s) across sampled frequency and voltage states
                </CardDescription>
              </div>
              <Badge variant="outline" className="font-mono text-xs">
                {chartData.length} Sample Points
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
                    tick={{ fontSize: 10 }}
                  />
                  <YAxis
                    yAxisId="left"
                    stroke="#10b981"
                    tick={{ fontSize: 11 }}
                    label={{ value: 'Efficiency (J/TH)', angle: -90, position: 'insideLeft', fill: '#10b981', fontSize: 11 }}
                  />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
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
                    formatter={(val: number, name: string) => [
                      name.includes('Efficiency') ? `${val} J/TH` : `${val} TH/s`,
                      name,
                    ]}
                  />
                  <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
                  <Bar yAxisId="left" dataKey="efficiency" name="Efficiency (J/TH)" fill="#10b981" radius={[4, 4, 0, 0]} opacity={0.85} />
                  <Line yAxisId="right" type="monotone" dataKey="hashrate" name="Hashrate (TH/s)" stroke="#38bdf8" strokeWidth={2.5} dot={{ r: 4 }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            {/* Matrix Data Table */}
            <div className="rounded-md border border-border/60 overflow-hidden">
              <div className="max-h-60 overflow-y-auto">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-muted/60 text-muted-foreground border-b border-border/60">
                    <tr>
                      <th className="p-2 pl-3">Step</th>
                      <th className="p-2">Frequency</th>
                      <th className="p-2">Voltage</th>
                      <th className="p-2">Hashrate</th>
                      <th className="p-2">Power</th>
                      <th className="p-2">Efficiency</th>
                      <th className="p-2">Fan Speed</th>
                      <th className="p-2">Chip Temp</th>
                      <th className="p-2">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/40">
                    {samples.map((s, i) => (
                      <tr key={s.id || i} className="hover:bg-muted/20">
                        <td className="p-2 pl-3 font-mono text-muted-foreground">{i + 1}</td>
                        <td className="p-2 font-mono font-medium">{s.freq_mhz} MHz</td>
                        <td className="p-2 font-mono text-muted-foreground">{s.voltage_mv} mV</td>
                        <td className="p-2 font-mono">{s.hashrate_ths ? `${s.hashrate_ths.toFixed(2)} TH/s` : '—'}</td>
                        <td className="p-2 font-mono">{s.power_w ? `${s.power_w.toFixed(1)} W` : '—'}</td>
                        <td className="p-2 font-mono font-semibold text-emerald-400">
                          {s.efficiency_j_th ? `${s.efficiency_j_th.toFixed(1)} J/TH` : '—'}
                        </td>
                        <td className="p-2 font-mono text-muted-foreground">
                          {s.fan_pct != null ? `${s.fan_pct.toFixed(0)}%` : '—'}
                        </td>
                        <td className="p-2 font-mono">{s.chip_temp_c ? `${s.chip_temp_c.toFixed(1)}°C` : '—'}</td>
                        <td className="p-2">
                          {s.stable ? (
                            <Badge variant="outline" className="text-[10px] bg-emerald-500/10 text-emerald-400 border-emerald-500/30">
                              Stable
                            </Badge>
                          ) : (
                            <Badge variant="destructive" className="text-[10px]" title={s.abort_reason || 'Unstable'}>
                              Unstable
                            </Badge>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
