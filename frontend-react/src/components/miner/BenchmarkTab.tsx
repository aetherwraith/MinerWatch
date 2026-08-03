import { useState, useEffect, useMemo, useDeferredValue } from 'react';
import { Gauge, Play, Square, Sparkles, Rocket, RefreshCw, CheckCircle2 } from 'lucide-react';
import {
  ComposedChart,
  Line,
  Bar,
  Cell,
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
  useGuardianProfiles,
  useAcknowledgeBenchmark,
  type BenchmarkProfileToSave,
} from '@/api/hooks';
import type { BenchmarkRun } from '@/lib/types';

interface BenchmarkTabProps {
  minerId: number;
}

function getTempColorClass(temp: number | null | undefined, maxCap: number): string {
  if (temp == null) return 'text-muted-foreground';
  const diff = maxCap - temp;
  if (diff <= 0) {
    return 'text-rose-400 font-extrabold animate-pulse'; // At or exceeding max target cap
  }
  if (diff <= 4) {
    return 'text-orange-400 font-bold'; // Within 4°C of max target cap
  }
  if (diff <= 10) {
    return 'text-amber-300 font-bold'; // Within 10°C of max target cap
  }
  return 'text-emerald-400 font-bold'; // Cool & optimal (>10°C headroom)
}

export function BenchmarkTab({ minerId }: BenchmarkTabProps) {
  const { data } = useMinerBenchmarkStatus(minerId);
  const { data: profilesData } = useGuardianProfiles(minerId);
  const startMutation = useStartBenchmark(minerId);
  const cancelMutation = useCancelBenchmark(minerId);
  const applyMutation = useApplyBenchmarkProfile(minerId);
  const ackMutation = useAcknowledgeBenchmark(minerId);

  const defaults = data?.defaults;
  const maxChipTempCap = defaults?.target_max_chip_temp_c ?? 68;
  const maxVrTempCap = defaults?.target_max_vr_temp_c ?? 82;
  const running = !!data?.running;
  const latestRun: BenchmarkRun | null = data?.latest_run ?? null;
  const existingProfiles = profilesData?.profiles ?? [];

  // Acknowledgment & profile save selection state
  const isUnacknowledged = !!latestRun && !running && (latestRun.acknowledged === 0 || latestRun.acknowledged === undefined) && (latestRun.status === 'completed' || latestRun.status === 'aborted' || latestRun.status === 'failed');

  const effExisting = existingProfiles.find((p) => p.name === 'Max Efficiency (Benchmark)');
  const hashExisting = existingProfiles.find((p) => p.name === 'Max Hashrate (Benchmark)');
  const quietExisting = existingProfiles.find((p) => p.name === 'Best Quiet (Benchmark)');

  const [saveEff, setSaveEff] = useState<boolean>(true);
  const [saveHash, setSaveHash] = useState<boolean>(true);
  const [saveQuiet, setSaveQuiet] = useState<boolean>(true);

  // Sync default selection when run finishes
  useEffect(() => {
    setSaveEff(!!latestRun?.best_eff_freq);
    setSaveHash(!!latestRun?.best_hash_freq);
    setSaveQuiet(!!latestRun?.best_quiet_freq);
  }, [latestRun?.id]);

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
  const [earlySkipSec, setEarlySkipSec] = useState<number>(60);
  const [maxChipTemp, setMaxChipTemp] = useState<number>(68);
  const [maxVrTemp, setMaxVrTemp] = useState<number>(82);

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
      if (defaults.early_skip_sec) setEarlySkipSec(defaults.early_skip_sec);
      if (defaults.target_max_chip_temp_c) setMaxChipTemp(defaults.target_max_chip_temp_c);
      if (defaults.target_max_vr_temp_c) setMaxVrTemp(defaults.target_max_vr_temp_c);
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
      early_skip_sec: earlySkipSec,
      target_max_chip_temp_c: maxChipTemp,
      target_max_vr_temp_c: maxVrTemp,
    });
  };

  const samples = latestRun?.samples ?? [];
  const sweepPhase = latestRun?.sweep_phase || 'coarse';
  const coarseTotal = latestRun?.total_steps || 1;
  const coarseCurrent = latestRun?.current_step || 0;
  const microTotal = latestRun?.micro_total_steps || 0;
  const microCurrent = latestRun?.micro_current_step || 0;

  const isMicroPhase = sweepPhase === 'microtuning' || (running && microTotal > 0 && microCurrent > 0);

  const activeTotal = isMicroPhase ? microTotal : coarseTotal;
  const activeCurrent = isMicroPhase ? microCurrent : coarseCurrent;
  const progressPct = Math.min(100, Math.round((activeCurrent / Math.max(1, activeTotal)) * 100));

  const dwellSec = latestRun?.dwell_time_s ?? dwellTime ?? 30;
  const remainingSteps = Math.max(0, activeTotal - activeCurrent);
  const etaSec = remainingSteps * dwellSec;
  const etaText = useMemo(() => {
    if (!running) return null;
    if (etaSec <= 0) return 'Finishing phase...';
    const m = Math.floor(etaSec / 60);
    const s = etaSec % 60;
    if (m === 0) return `~${s}s remaining`;
    return `~${m}m ${s > 0 ? `${s}s ` : ''}remaining`;
  }, [running, etaSec]);

  // Prepared chart data (includes strictly STABLE Phase 1 coarse and Phase 2 microtuning points)
  const rawChartData = useMemo(() => {
    return samples
      .filter((s) => s.stable && s.efficiency_j_th != null && s.hashrate_ths != null)
      .map((s, idx) => ({
        step: idx + 1,
        name: `${s.freq_mhz}MHz / ${s.voltage_mv}mV`,
        freq: s.freq_mhz,
        volt: s.voltage_mv,
        efficiency: s.efficiency_j_th != null ? Number(s.efficiency_j_th.toFixed(1)) : 0,
        hashrate: s.hashrate_ths != null ? Number(s.hashrate_ths.toFixed(2)) : 0,
        power: s.power_w ? Number(s.power_w.toFixed(1)) : null,
        chipTemp: s.chip_temp_c ? Number(s.chip_temp_c.toFixed(1)) : null,
        vrTemp: s.vr_temp_c ? Number(s.vr_temp_c.toFixed(1)) : null,
        errorRate: s.error_rate_pct != null ? Number(s.error_rate_pct.toFixed(1)) : null,
        stable: true,
        abortReason: null,
        isMicro: idx >= coarseTotal,
      }));
  }, [samples, coarseTotal]);

  const chartData = useDeferredValue(rawChartData);

  // Live leading candidates computed from stable samples during run or completed (with fallback to non-thermal-aborted hashing samples)
  const liveCandidateSamples = useMemo(() => {
    const st = samples.filter((s) => s.stable);
    if (st.length) return st;
    return samples.filter((s) => (s.hashrate_ths ?? 0) > 0 && !s.abort_reason?.startsWith('Thermal'));
  }, [samples]);

  const liveBestEff = useMemo(() => {
    if (!liveCandidateSamples.length) return null;
    return liveCandidateSamples.reduce((best, cur) => {
      if (!cur.efficiency_j_th) return best;
      if (!best || !best.efficiency_j_th || cur.efficiency_j_th < best.efficiency_j_th) return cur;
      return best;
    }, null as (typeof samples)[0] | null);
  }, [liveCandidateSamples]);

  const liveBestHash = useMemo(() => {
    if (!liveCandidateSamples.length) return null;
    return liveCandidateSamples.reduce((best, cur) => {
      if (!cur.hashrate_ths) return best;
      if (!best || !best.hashrate_ths || cur.hashrate_ths > best.hashrate_ths) return cur;
      return best;
    }, null as (typeof samples)[0] | null);
  }, [liveCandidateSamples]);

  const liveBestQuiet = useMemo(() => {
    const isAutoFan = latestRun?.fan_mode ? ['firmware', 'minerwatch'].includes(latestRun.fan_mode) : benchFanMode !== 'pin';
    if (!isAutoFan || !liveCandidateSamples.length) return null;
    const quietLimit = latestRun?.quiet_fan_max_pct ?? quietFanMaxPct ?? 65;
    const quietCands = liveCandidateSamples.filter(
      (s) => s.fan_pct != null && s.fan_pct <= quietLimit && s.hashrate_ths != null
    );
    if (!quietCands.length) return null;
    return quietCands.reduce((best, cur) => {
      if (!best || (cur.hashrate_ths ?? 0) > (best.hashrate_ths ?? 0)) return cur;
      return best;
    }, null as (typeof samples)[0] | null);
  }, [liveCandidateSamples, latestRun?.fan_mode, latestRun?.quiet_fan_max_pct, benchFanMode, quietFanMaxPct]);

  // Generate planned combinations to determine active target parameters for any step (including step 1!)
  const plannedCombinations = useMemo(() => {
    const minF = latestRun?.min_freq_mhz ?? minFreq;
    const maxF = latestRun?.max_freq_mhz ?? maxFreq;
    const stepF = latestRun?.freq_step_mhz ?? freqStep ?? 10;
    const minV = latestRun?.min_voltage_mv ?? minVolt;
    const maxV = latestRun?.max_voltage_mv ?? maxVolt;
    const stepV = latestRun?.voltage_step_mv ?? voltStep ?? 10;

    const list: { freq_mhz: number; voltage_mv: number }[] = [];
    if (stepF <= 0 || stepV <= 0) return list;
    for (let f = minF; f <= maxF; f += stepF) {
      for (let v = minV; v <= maxV; v += stepV) {
        list.push({ freq_mhz: f, voltage_mv: v });
      }
    }
    return list;
  }, [latestRun, minFreq, maxFreq, freqStep, minVolt, maxVolt, voltStep]);

  // Current parameters under active test (works from Step 1 onwards across both phases!)
  const activeTestingPoint = useMemo(() => {
    const live = data?.live_metrics;

    if (isMicroPhase) {
      const latestSample = samples[samples.length - 1];
      return {
        freq_mhz: latestSample?.freq_mhz ?? minFreq,
        voltage_mv: latestSample?.voltage_mv ?? minVolt,
        hashrate_ths: live?.hashrate_ths ?? latestSample?.hashrate_ths ?? null,
        fan_pct: live?.fan_pct ?? latestSample?.fan_pct ?? null,
        temp_chip_c: live?.temp_chip_c ?? latestSample?.chip_temp_c ?? null,
        temp_vr_c: live?.temp_vr_c ?? latestSample?.vr_temp_c ?? null,
      };
    }
    const activeStepIdx = Math.max(0, (latestRun?.current_step || 1) - 1);
    const plan = plannedCombinations[activeStepIdx] ?? plannedCombinations[0] ?? { freq_mhz: minFreq, voltage_mv: minVolt };
    const sampleForStep = samples[activeStepIdx] ?? samples[samples.length - 1] ?? null;

    return {
      freq_mhz: plan.freq_mhz,
      voltage_mv: plan.voltage_mv,
      hashrate_ths: live?.hashrate_ths ?? sampleForStep?.hashrate_ths ?? null,
      fan_pct: live?.fan_pct ?? sampleForStep?.fan_pct ?? null,
      temp_chip_c: live?.temp_chip_c ?? sampleForStep?.chip_temp_c ?? null,
      temp_vr_c: live?.temp_vr_c ?? sampleForStep?.vr_temp_c ?? null,
    };
  }, [isMicroPhase, latestRun, plannedCombinations, minFreq, minVolt, samples, data?.live_metrics]);

  // Display values for candidate cards with fallback to saved existing profiles
  const displayEffFreq = latestRun?.best_eff_freq ?? liveBestEff?.freq_mhz ?? effExisting?.max_freq_mhz ?? null;
  const displayEffVolt = latestRun?.best_eff_volt ?? liveBestEff?.voltage_mv ?? effExisting?.voltage_mv ?? null;
  const displayEffJTh = latestRun?.best_eff_j_th ?? liveBestEff?.efficiency_j_th ?? null;

  const displayHashFreq = latestRun?.best_hash_freq ?? liveBestHash?.freq_mhz ?? hashExisting?.max_freq_mhz ?? null;
  const displayHashVolt = latestRun?.best_hash_volt ?? liveBestHash?.voltage_mv ?? hashExisting?.voltage_mv ?? null;
  const displayHashThs = latestRun?.best_hash_ths ?? liveBestHash?.hashrate_ths ?? null;

  const displayQuietFreq = latestRun?.best_quiet_freq ?? liveBestQuiet?.freq_mhz ?? quietExisting?.max_freq_mhz ?? null;
  const displayQuietVolt = latestRun?.best_quiet_volt ?? liveBestQuiet?.voltage_mv ?? quietExisting?.voltage_mv ?? null;
  const displayQuietFan = latestRun?.best_quiet_fan_pct ?? liveBestQuiet?.fan_pct ?? quietExisting?.fan_speed_pct ?? null;

  const handleAcknowledge = (withProfiles: boolean) => {
    if (!latestRun || !withProfiles) {
      ackMutation.mutate([]);
      return;
    }

    const profilesToSave: BenchmarkProfileToSave[] = [];

    const effFreq = latestRun.best_eff_freq ?? displayEffFreq;
    const effVolt = latestRun.best_eff_volt ?? displayEffVolt;
    if (saveEff && effFreq && effVolt) {
      profilesToSave.push({
        name: 'Max Efficiency (Benchmark)',
        max_freq_mhz: effFreq,
        voltage_mv: effVolt,
        fan_mode: latestRun.fan_mode || 'firmware',
        existing_id: effExisting?.id ?? null,
      });
    }

    const hashFreq = latestRun.best_hash_freq ?? displayHashFreq;
    const hashVolt = latestRun.best_hash_volt ?? displayHashVolt;
    if (saveHash && hashFreq && hashVolt) {
      profilesToSave.push({
        name: 'Max Hashrate (Benchmark)',
        max_freq_mhz: hashFreq,
        voltage_mv: hashVolt,
        fan_mode: latestRun.fan_mode || 'firmware',
        existing_id: hashExisting?.id ?? null,
      });
    }

    const quietFreq = latestRun.best_quiet_freq ?? displayQuietFreq;
    const quietVolt = latestRun.best_quiet_volt ?? displayQuietVolt;
    if (saveQuiet && quietFreq && quietVolt) {
      profilesToSave.push({
        name: 'Best Quiet (Benchmark)',
        max_freq_mhz: quietFreq,
        voltage_mv: quietVolt,
        fan_mode: latestRun.fan_mode || 'firmware',
        existing_id: quietExisting?.id ?? null,
      });
    }

    ackMutation.mutate(profilesToSave);
  };

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
              disabled={running || startMutation.isPending}
              className="h-9 gap-2 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs disabled:opacity-50"
            >
              <Play className="h-4 w-4 fill-current" />
              Start Benchmark Sweep
            </Button>
          )}
        </div>
      </div>

      {/* Unacknowledged Benchmark Profile Save & Overwrite Panel */}
      {isUnacknowledged && latestRun && (
        <Card className="border-amber-500/60 bg-amber-500/10">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-amber-300">
                <Sparkles className="h-5 w-5" />
                <CardTitle className="text-base font-semibold">Benchmark Complete — Save or Update Profiles</CardTitle>
              </div>
              <Badge className="bg-amber-500/20 text-amber-300 border-amber-500/40 text-xs">
                Action Required
              </Badge>
            </div>
            <CardDescription className="text-amber-200/80">
              A benchmark sweep completed. Review candidate profiles below. You can save or overwrite existing profiles before acknowledging and unlocking new benchmark runs.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
              {/* Max Efficiency Candidate */}
              <div className={`p-3.5 rounded-lg border transition-all ${saveEff ? 'border-emerald-500/60 bg-emerald-500/10' : 'border-border/40 bg-muted/20 opacity-60'}`}>
                <div className="flex items-center justify-between font-semibold text-emerald-300 mb-1">
                  <span>Max Efficiency</span>
                  {effExisting && <Badge variant="outline" className="text-[9px] bg-amber-500/15 text-amber-300 border-amber-500/40">Existing Profile Found</Badge>}
                </div>
                <div className="space-y-1 font-mono text-[11px] text-foreground">
                  <div>New: <span className="font-bold">{latestRun.best_eff_freq ?? '—'} MHz / {latestRun.best_eff_volt ?? '—'} mV</span> ({latestRun.best_eff_j_th ? `${latestRun.best_eff_j_th.toFixed(1)} J/TH` : '—'})</div>
                  {effExisting && (
                    <div className="text-muted-foreground">
                      Existing: {effExisting.max_freq_mhz} MHz / {effExisting.voltage_mv} mV
                    </div>
                  )}
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="chk-save-eff"
                    checked={saveEff}
                    onChange={(e) => setSaveEff(e.target.checked)}
                    disabled={!latestRun.best_eff_freq}
                    className="rounded border-border text-emerald-500 focus:ring-emerald-500"
                  />
                  <label htmlFor="chk-save-eff" className="text-[11px] font-medium text-foreground cursor-pointer">
                    {effExisting ? 'Overwrite Existing Profile' : 'Create Guardian Profile'}
                  </label>
                </div>
              </div>

              {/* Max Hashrate Candidate */}
              <div className={`p-3.5 rounded-lg border transition-all ${saveHash ? 'border-cyan-500/60 bg-cyan-500/10' : 'border-border/40 bg-muted/20 opacity-60'}`}>
                <div className="flex items-center justify-between font-semibold text-cyan-300 mb-1">
                  <span>Max Hashrate</span>
                  {hashExisting && <Badge variant="outline" className="text-[9px] bg-amber-500/15 text-amber-300 border-amber-500/40">Existing Profile Found</Badge>}
                </div>
                <div className="space-y-1 font-mono text-[11px] text-foreground">
                  <div>New: <span className="font-bold">{latestRun.best_hash_freq ?? '—'} MHz / {latestRun.best_hash_volt ?? '—'} mV</span> ({latestRun.best_hash_ths ? `${latestRun.best_hash_ths.toFixed(2)} TH/s` : '—'})</div>
                  {hashExisting && (
                    <div className="text-muted-foreground">
                      Existing: {hashExisting.max_freq_mhz} MHz / {hashExisting.voltage_mv} mV
                    </div>
                  )}
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="chk-save-hash"
                    checked={saveHash}
                    onChange={(e) => setSaveHash(e.target.checked)}
                    disabled={!latestRun.best_hash_freq}
                    className="rounded border-border text-cyan-500 focus:ring-cyan-500"
                  />
                  <label htmlFor="chk-save-hash" className="text-[11px] font-medium text-foreground cursor-pointer">
                    {hashExisting ? 'Overwrite Existing Profile' : 'Create Guardian Profile'}
                  </label>
                </div>
              </div>

              {/* Best Quiet Candidate (Only if calculated under auto fan mode) */}
              {latestRun.best_quiet_freq ? (
                <div className={`p-3.5 rounded-lg border transition-all ${saveQuiet ? 'border-indigo-500/60 bg-indigo-500/10' : 'border-border/40 bg-muted/20 opacity-60'}`}>
                  <div className="flex items-center justify-between font-semibold text-indigo-300 mb-1">
                    <span>Best Quiet Profile</span>
                    {quietExisting && <Badge variant="outline" className="text-[9px] bg-amber-500/15 text-amber-300 border-amber-500/40">Existing Profile Found</Badge>}
                  </div>
                  <div className="space-y-1 font-mono text-[11px] text-foreground">
                    <div>New: <span className="font-bold">{latestRun.best_quiet_freq} MHz / {latestRun.best_quiet_volt} mV</span> ({latestRun.best_quiet_fan_pct?.toFixed(0)}% Fan)</div>
                    {quietExisting && (
                      <div className="text-muted-foreground">
                        Existing: {quietExisting.max_freq_mhz} MHz / {quietExisting.voltage_mv} mV
                      </div>
                    )}
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <input
                      type="checkbox"
                      id="chk-save-quiet"
                      checked={saveQuiet}
                      onChange={(e) => setSaveQuiet(e.target.checked)}
                      className="rounded border-border text-indigo-500 focus:ring-indigo-500"
                    />
                    <label htmlFor="chk-save-quiet" className="text-[11px] font-medium text-foreground cursor-pointer">
                      {quietExisting ? 'Overwrite Existing Profile' : 'Create Guardian Profile'}
                    </label>
                  </div>
                </div>
              ) : (
                <div className="p-3.5 rounded-lg border border-border/30 bg-muted/10 text-muted-foreground flex flex-col justify-center text-center">
                  <span className="font-semibold text-xs text-foreground/70">Quiet Profile N/A</span>
                  <span className="text-[10px] mt-1">Quiet profiles are only calculated when using Firmware Auto or MinerWatch Auto Fan modes.</span>
                </div>
              )}
            </div>

            <div className="flex flex-col sm:flex-row items-center gap-3 pt-2">
              <Button
                variant="default"
                size="sm"
                onClick={() => handleAcknowledge(true)}
                disabled={ackMutation.isPending}
                className="w-full sm:w-auto h-9 bg-amber-600 hover:bg-amber-500 text-white font-medium text-xs gap-2"
              >
                <CheckCircle2 className="h-4 w-4" />
                Save Selected Profiles & Complete Benchmark
              </Button>

              <Button
                variant="outline"
                size="sm"
                onClick={() => handleAcknowledge(false)}
                disabled={ackMutation.isPending}
                className="w-full sm:w-auto h-9 text-xs border-amber-500/40 text-amber-200 hover:bg-amber-500/20"
              >
                Acknowledge & Dismiss without Saving
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

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
              <div className="flex flex-wrap items-center gap-2 text-emerald-300 font-semibold text-sm">
                <RefreshCw className="h-4 w-4 animate-spin text-emerald-400" />
                <span>
                  {isMicroPhase ? 'Phase 2: Fine Microtuning Search...' : 'Phase 1: Coarse Matrix Sweep...'}
                </span>
                <Badge variant="outline" className="font-mono text-xs bg-emerald-500/20 text-emerald-300 border-emerald-500/40 gap-1.5">
                  <span>
                    {isMicroPhase ? `Micro Step ${activeCurrent} of ${activeTotal}` : `Step ${activeCurrent} of ${activeTotal}`} ({progressPct}%)
                  </span>
                  {etaText && (
                    <>
                      <span className="text-emerald-400/60">•</span>
                      <span className="text-emerald-200">ETA: {etaText}</span>
                    </>
                  )}
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

            {/* Current Operating Point Under Active Test (Renders from Step 1) */}
            {activeTestingPoint && (
              <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/15 p-3 text-xs space-y-1.5">
                <div className="flex items-center justify-between font-mono font-semibold text-emerald-300">
                  <span className="flex items-center gap-1.5">
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                    </span>
                    Active Test Point ({isMicroPhase ? `Micro Step ${activeCurrent}` : `Step ${activeCurrent}`} of {activeTotal}):
                  </span>
                  <Badge className="bg-emerald-500/25 text-emerald-200 border-emerald-500/40 text-[10px]">
                    Live Sampling
                  </Badge>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 font-mono text-[11px] text-foreground pt-0.5">
                  <div>Frequency: <span className="font-bold text-emerald-400">{activeTestingPoint.freq_mhz} MHz</span></div>
                  <div>Voltage: <span className="font-bold text-cyan-400">{activeTestingPoint.voltage_mv} mV</span></div>
                  <div>Hashrate: <span className="font-bold text-foreground">{activeTestingPoint.hashrate_ths != null ? `${activeTestingPoint.hashrate_ths.toFixed(2)} TH/s` : 'Settling...'}</span></div>
                  <div>Fan Speed: <span className="font-bold text-indigo-300">{activeTestingPoint.fan_pct != null ? `${Math.round(activeTestingPoint.fan_pct)}%` : '—'}</span></div>
                  <div>Chip Temp: <span className={getTempColorClass(activeTestingPoint.temp_chip_c, maxChipTempCap)}>{activeTestingPoint.temp_chip_c != null ? `${activeTestingPoint.temp_chip_c.toFixed(1)}°C` : '—'}</span></div>
                  <div>VR Temp: <span className={getTempColorClass(activeTestingPoint.temp_vr_c, maxVrTempCap)}>{activeTestingPoint.temp_vr_c != null ? `${activeTestingPoint.temp_vr_c.toFixed(1)}°C` : '—'}</span></div>
                </div>
              </div>
            )}

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] font-mono text-muted-foreground pt-1">
              <div>Range: <span className="text-foreground">{latestRun?.min_freq_mhz ?? minFreq}-{latestRun?.max_freq_mhz ?? maxFreq} MHz</span></div>
              <div>Volt: <span className="text-foreground">{latestRun?.min_voltage_mv ?? minVolt}-{latestRun?.max_voltage_mv ?? maxVolt} mV</span></div>
              <div>Dwell: <span className="text-foreground">{latestRun?.dwell_time_s ?? dwellTime}s</span></div>
              <div>Fan Mode: <span className="text-foreground capitalize">{latestRun?.fan_mode ?? benchFanMode}</span></div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Optimal Candidate Profile Leaderboard Cards (Shown when run or leading candidates or existing saved profiles exist) */}
      {(running || samples.length > 0 || latestRun?.best_eff_freq || effExisting || hashExisting || quietExisting) && (
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
                  {running ? 'Leading Candidate' : (latestRun?.best_eff_freq ? 'Sweet-Spot' : 'Saved Profile')}
                </Badge>
              </div>
              <CardDescription>Lowest energy usage per Terahash (J/TH)</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2.5 rounded-lg border border-border/50 bg-muted/20 font-mono">
                  <span className="text-muted-foreground text-[10px]">Freq / Voltage</span>
                  <div className="text-sm font-bold text-foreground mt-0.5">
                    {displayEffFreq ? `${displayEffFreq} MHz / ${displayEffVolt ?? 1200} mV` : (running ? 'Evaluating...' : 'No candidate')}
                  </div>
                </div>
                <div className="p-2.5 rounded-lg border border-border/50 bg-muted/20 font-mono">
                  <span className="text-muted-foreground text-[10px]">Efficiency</span>
                  <div className="text-sm font-bold text-emerald-400 mt-0.5">
                    {displayEffJTh != null ? `${displayEffJTh.toFixed(1)} J/TH` : (effExisting ? 'Saved Profile' : (running ? 'Evaluating...' : '—'))}
                  </div>
                </div>
              </div>
              <Button
                variant="default"
                size="sm"
                onClick={() => applyMutation.mutate('max_efficiency')}
                disabled={running || applyMutation.isPending || !displayEffFreq}
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
                  {running ? 'Leading Candidate' : (latestRun?.best_hash_freq ? 'Peak Performance' : 'Saved Profile')}
                </Badge>
              </div>
              <CardDescription>Highest mining throughput (TH/s)</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2.5 rounded-lg border border-border/50 bg-muted/20 font-mono">
                  <span className="text-muted-foreground text-[10px]">Freq / Voltage</span>
                  <div className="text-sm font-bold text-foreground mt-0.5">
                    {displayHashFreq ? `${displayHashFreq} MHz / ${displayHashVolt ?? 1200} mV` : (running ? 'Evaluating...' : 'No candidate')}
                  </div>
                </div>
                <div className="p-2.5 rounded-lg border border-border/50 bg-muted/20 font-mono">
                  <span className="text-muted-foreground text-[10px]">Peak Hashrate</span>
                  <div className="text-sm font-bold text-cyan-400 mt-0.5">
                    {displayHashThs != null ? `${displayHashThs.toFixed(2)} TH/s` : (hashExisting ? 'Saved Profile' : (running ? 'Evaluating...' : '—'))}
                  </div>
                </div>
              </div>
              <Button
                variant="default"
                size="sm"
                onClick={() => applyMutation.mutate('max_hashrate')}
                disabled={running || applyMutation.isPending || !displayHashFreq}
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
                  {running ? 'Leading Candidate' : (latestRun?.best_quiet_freq ? 'Acoustic Quiet' : 'Saved Profile')}
                </Badge>
              </div>
              <CardDescription>Max performance (TH/s) where Fan ≤ {latestRun?.quiet_fan_max_pct ?? quietFanMaxPct ?? 65}%</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2.5 rounded-lg border border-border/50 bg-muted/20 font-mono">
                  <span className="text-muted-foreground text-[10px]">Freq / Voltage</span>
                  <div className="text-sm font-bold text-foreground mt-0.5">
                    {displayQuietFreq ? `${displayQuietFreq} MHz / ${displayQuietVolt ?? 1200} mV` : (running ? 'Evaluating...' : 'No candidate')}
                  </div>
                </div>
                <div className="p-2.5 rounded-lg border border-border/50 bg-muted/20 font-mono">
                  <span className="text-muted-foreground text-[10px]">Quiet Hashrate / Fan</span>
                  <div className="text-sm font-bold text-indigo-400 mt-0.5">
                    {displayQuietFreq ? `${liveBestQuiet?.hashrate_ths?.toFixed(2) ?? '—'} TH/s @ ${displayQuietFan ? displayQuietFan.toFixed(0) + '%' : '—'}` : (quietExisting ? 'Saved Profile' : (running ? 'Evaluating...' : '—'))}
                  </div>
                </div>
              </div>
              <Button
                variant="default"
                size="sm"
                onClick={() => applyMutation.mutate('quiet')}
                disabled={running || applyMutation.isPending || !displayQuietFreq}
                className="w-full h-9 bg-indigo-600 hover:bg-indigo-500 text-white font-medium gap-2 text-xs"
              >
                <CheckCircle2 className="h-4 w-4" />
                Apply Quiet Profile
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Sweep Configuration Controls (Only shown when no benchmark is running) */}
      {!running && (
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
                <Label className="text-xs">Early Skip Settling Window (sec)</Label>
                <Input
                  type="number"
                  min={10}
                  max={300}
                  value={earlySkipSec}
                  onChange={(e) => setEarlySkipSec(Number(e.target.value))}
                  disabled={running}
                  title="Min observation window before skipping non-stabilizing or out-of-bounds combinations early."
                  className="h-8 text-xs font-mono"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Max Target Chip Temp (°C)</Label>
                <Input
                  type="number"
                  min={40}
                  max={100}
                  value={maxChipTemp}
                  onChange={(e) => setMaxChipTemp(Number(e.target.value))}
                  disabled={running}
                  title="Thermal safety cutoff limit for ASIC chip temperature during benchmark sweep (retrieved from Guardian)."
                  className="h-8 text-xs font-mono"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Max Target VR Temp (°C)</Label>
                <Input
                  type="number"
                  min={40}
                  max={120}
                  value={maxVrTemp}
                  onChange={(e) => setMaxVrTemp(Number(e.target.value))}
                  disabled={running}
                  title="Thermal safety cutoff limit for VR temperature during benchmark sweep (retrieved from Guardian)."
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

            {/* Start Sweep Action Button inside Parameters Card */}
            <div className="pt-4 border-t border-border/50 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <span className="text-xs text-muted-foreground">
                {`Configured sweep: ${minFreq}–${maxFreq} MHz in ${freqStep} MHz steps, ${minVolt}–${maxVolt} mV in ${voltStep} mV steps.`}
              </span>
              <Button
                variant="default"
                size="sm"
                onClick={handleStart}
                disabled={running || startMutation.isPending}
                className="h-9 px-5 gap-2 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs disabled:opacity-50 shrink-0 self-end sm:self-auto"
              >
                <Play className="h-4 w-4 fill-current" />
                Start Benchmark Sweep
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Benchmark Sweep Chart & Matrix Table */}
      {(running || chartData.length > 0) && (
        <Card className="border-border/60">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base font-semibold">Sweep Combination Matrix</CardTitle>
                <CardDescription>
                  Efficiency (J/TH) vs Hashrate (TH/s) across sampled frequency and voltage states
                </CardDescription>
                <div className="flex items-center gap-3 text-xs pt-1.5">
                  <div className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded bg-emerald-500 inline-block" />
                    <span className="text-muted-foreground text-[11px]">Phase 1: Coarse Steps</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded bg-purple-500 inline-block" />
                    <span className="text-purple-300 font-medium text-[11px]">Phase 2: Microtuning Steps</span>
                  </div>
                </div>
              </div>
              <Badge variant="outline" className="font-mono text-xs">
                {chartData.length} Sample Points {running && '(Sampling...)'}
              </Badge>
            </div>
          </CardHeader>

          <CardContent className="space-y-4">
            {chartData.length > 0 ? (
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
                      content={({ active, payload }) => {
                        if (!active || !payload || !payload.length) return null;
                        const data = payload[0].payload;
                        const isUnstable = !data.stable;
                        return (
                          <div className="rounded-lg border border-border/80 bg-slate-950/95 p-3 text-xs shadow-xl backdrop-blur space-y-1.5 min-w-[210px]">
                            <div className="flex items-center justify-between gap-2 border-b border-border/50 pb-1.5">
                              <div className="flex items-center gap-1.5">
                                <span className="font-semibold text-slate-100">{data.name}</span>
                                {data.isMicro && (
                                  <span className="rounded bg-purple-500/25 px-1.5 py-0.5 text-[10px] font-semibold text-purple-300 border border-purple-500/40">
                                    Microtune
                                  </span>
                                )}
                              </div>
                              <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold ${data.stable ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' : 'bg-red-500/15 text-red-400 border border-red-500/30'}`}>
                                {data.stable ? 'Stable' : 'Unstable'}
                              </span>
                            </div>

                            <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                              {data.efficiency !== null && (
                                <div>
                                  <span className="text-muted-foreground">Efficiency: </span>
                                  <span className="font-mono text-emerald-400 font-medium">{data.efficiency} J/TH</span>
                                </div>
                              )}
                              {data.hashrate !== null && (
                                <div>
                                  <span className="text-muted-foreground">Hashrate: </span>
                                  <span className="font-mono text-sky-400 font-medium">{data.hashrate} TH/s</span>
                                </div>
                              )}
                              {data.power !== null && (
                                <div>
                                  <span className="text-muted-foreground">Power: </span>
                                  <span className="font-mono text-slate-200">{data.power} W</span>
                                </div>
                              )}
                              {data.chipTemp !== null && (
                                <div>
                                  <span className="text-muted-foreground">Chip Temp: </span>
                                  <span className="font-mono text-amber-300">{data.chipTemp} °C</span>
                                </div>
                              )}
                              {data.vrTemp !== null && (
                                <div>
                                  <span className="text-muted-foreground">VR Temp: </span>
                                  <span className="font-mono text-amber-300">{data.vrTemp} °C</span>
                                </div>
                              )}
                              {data.errorRate !== null && (
                                <div>
                                  <span className="text-muted-foreground">Error Rate: </span>
                                  <span className={`font-mono ${data.errorRate > 0 ? 'text-red-400 font-semibold' : 'text-slate-300'}`}>{data.errorRate}%</span>
                                </div>
                              )}
                            </div>

                            {isUnstable && (
                              <div className="mt-1.5 border-t border-red-500/30 pt-1.5 text-[11px] text-red-300 bg-red-950/40 p-1.5 rounded border border-red-800/40">
                                <span className="font-semibold text-red-400 block mb-0.5">⚠️ Instability Trigger:</span>
                                <span>{data.abortReason || 'Hardware error rate or stability threshold exceeded'}</span>
                              </div>
                            )}
                          </div>
                        );
                      }}
                    />
                    <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
                    <Bar yAxisId="left" dataKey="efficiency" name="Efficiency (J/TH)" radius={[4, 4, 0, 0]} opacity={0.85}>
                      {chartData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.isMicro ? '#c084fc' : '#10b981'} />
                      ))}
                    </Bar>
                    <Line
                      yAxisId="right"
                      type="monotone"
                      dataKey="hashrate"
                      name="Hashrate (TH/s)"
                      stroke="#38bdf8"
                      strokeWidth={2.5}
                      dot={(props: any) => {
                        const { cx, cy, payload } = props;
                        if (!cx || !cy) return <circle key={props.key} cx={0} cy={0} r={0} />;
                        const isMicro = payload?.isMicro;
                        return (
                          <circle
                            key={props.key}
                            cx={cx}
                            cy={cy}
                            r={isMicro ? 5 : 4}
                            fill={isMicro ? '#e879f9' : '#38bdf8'}
                            stroke={isMicro ? '#a855f7' : '#0284c7'}
                            strokeWidth={1.5}
                          />
                        );
                      }}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="flex h-48 w-full flex-col items-center justify-center rounded-lg border border-dashed border-border/50 bg-muted/10 p-6 text-center text-xs">
                <RefreshCw className="h-6 w-6 animate-spin text-emerald-400 mb-2.5" />
                <span className="font-semibold text-foreground text-sm">Sampling Step 1 in Progress...</span>
                <span className="text-muted-foreground mt-1 max-w-sm">
                  Collecting baseline telemetry and thermal stability measurements for {activeTestingPoint?.freq_mhz ?? minFreq} MHz @ {activeTestingPoint?.voltage_mv ?? minVolt} mV. Telemetry graph will render as soon as Step 1 settles ({dwellTime}s dwell).
                </span>
              </div>
            )}

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
                      <th className="p-2">VR Temp</th>
                      <th className="p-2">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/40">
                    {samples.map((s, i) => (
                      <tr
                        key={s.id || i}
                        className={`hover:bg-muted/20 ${i >= coarseTotal ? 'bg-purple-950/25 border-l-2 border-l-purple-500' : ''}`}
                      >
                        <td className="p-2 pl-3 font-mono text-muted-foreground">
                          <span className="inline-flex items-center gap-1.5">
                            <span>{i + 1}</span>
                            {i >= coarseTotal && (
                              <Badge variant="outline" className="text-[9px] bg-purple-500/20 text-purple-300 border-purple-500/40 px-1 py-0 font-sans">
                                Micro
                              </Badge>
                            )}
                          </span>
                        </td>
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
                        <td className="p-2 font-mono">
                          <span className={getTempColorClass(s.chip_temp_c, maxChipTempCap)}>
                            {s.chip_temp_c != null ? `${s.chip_temp_c.toFixed(1)}°C` : '—'}
                          </span>
                        </td>
                        <td className="p-2 font-mono">
                          <span className={getTempColorClass(s.vr_temp_c, maxVrTempCap)}>
                            {s.vr_temp_c != null ? `${s.vr_temp_c.toFixed(1)}°C` : '—'}
                          </span>
                        </td>
                        <td className="p-2">
                          {s.stable ? (
                            <Badge variant="outline" className="text-[10px] bg-emerald-500/10 text-emerald-400 border-emerald-500/30">
                              Stable
                            </Badge>
                          ) : (
                            <Badge
                              variant="destructive"
                              className="text-[10px] cursor-help transition-opacity hover:opacity-90"
                              title={s.abort_reason ? `Instability Trigger: ${s.abort_reason}` : 'Unstable / Error Rate Exceeded'}
                            >
                              ⚠️ Unstable
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
