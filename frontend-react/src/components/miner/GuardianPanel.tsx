import { useEffect, useState } from 'react';
import { Activity, Gauge, ShieldAlert } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { ApiError } from '@/lib/api';
import { useGuardianStatus, useSetGuardianConfig } from '@/api/hooks';
import { GovernorChart } from '@/components/miner/GovernorChart';
import { GovernorDecisionLog } from '@/components/miner/GovernorDecisionLog';
import type { MinerDetailResponse } from '@/lib/types';

interface Props {
  data: MinerDetailResponse;
}

/**
 * Advanced tab — the Guardian (runtime frequency governor).
 *
 * The Guardian is a slow, always-on loop that nudges ASIC frequency to keep
 * both VR and ASIC chip temperatures and the HW error rate inside safe bounds.
 */
export function GuardianPanel({ data }: Props) {
  const { miner, capabilities } = data;
  const status = useGuardianStatus(miner.id);
  const setConfig = useSetGuardianConfig(miner.id);

  const s = status.data;
  const currentFreq = s?.current_freq_mhz ?? null;

  // The "max frequency" field. Seeded from the stored ceiling, falling back
  // to the live current frequency (what it would default to on first enable).
  const [maxFreq, setMaxFreq] = useState<number | ''>('');
  // Temperature target fields for VR and ASIC chip.
  const [maxVrTemp, setMaxVrTemp] = useState<number | ''>('');
  const [maxChipTemp, setMaxChipTemp] = useState<number | ''>('');
  const [maxPower, setMaxPower] = useState<number | ''>('');
  const [fanMaxPct, setFanMaxPct] = useState<number | ''>('');
  // At-your-own-risk confirmation, gating the enable toggle.
  const [confirmOpen, setConfirmOpen] = useState(false);
  // Separate (stronger) confirmation for the Phase 2 voltage co-tuner opt-in.
  const [voltConfirmOpen, setVoltConfirmOpen] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Sync the editable fields when the backend state arrives / changes.
  useEffect(() => {
    if (!s) return;
    setMaxFreq(s.max_freq_mhz ?? s.current_freq_mhz ?? '');
    setMaxVrTemp(s.max_vr_temp_c ?? s.defaults.vr_high_c ?? '');
    setMaxChipTemp(s.max_chip_temp_c ?? s.defaults.chip_high_c ?? '');
    setMaxPower(s.max_power_w ?? '');
    setFanMaxPct(s.fan_max_pct ?? 100);
  }, [
    s?.max_freq_mhz,
    s?.current_freq_mhz,
    s?.max_vr_temp_c,
    s?.max_chip_temp_c,
    s?.max_power_w,
    s?.fan_max_pct,
  ]);

  if (!capabilities.set_frequency) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          The Guardian controls ASIC frequency, which this miner family does
          not expose over the API. It is available on Bitaxe and Nerd* miners.
        </CardContent>
      </Card>
    );
  }

  if (status.isLoading || !s) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          Loading Guardian status…
        </CardContent>
      </Card>
    );
  }

  if (!s.supported) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          The Guardian is only supported on Bitaxe / Nerd* miners.
        </CardContent>
      </Card>
    );
  }

  if (!s.enabled) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          The Guardian feature is disabled globally (guardian.enabled = false).
        </CardContent>
      </Card>
    );
  }

  const enabled = s.miner_enabled;
  const d = s.defaults;
  const pending = setConfig.isPending;

  const vrDeadband = d.vr_high_c - d.vr_low_c;
  const vrHighC = typeof maxVrTemp === 'number' ? maxVrTemp : d.vr_high_c;
  const vrLowC = Math.round((vrHighC - vrDeadband) * 10) / 10;

  const chipDeadband = d.chip_high_c - d.chip_low_c;
  const chipHighC = typeof maxChipTemp === 'number' ? maxChipTemp : d.chip_high_c;
  const chipLowC = Math.round((chipHighC - chipDeadband) * 10) / 10;

  const softCeil = s.live?.soft_ceiling_mhz ?? null;
  const softCapped =
    softCeil != null && s.max_freq_mhz != null && softCeil < s.max_freq_mhz;

  async function run(
    payload: {
      enabled?: boolean;
      max_freq_mhz?: number;
      freq_floor_mhz?: number;
      max_vr_temp_c?: number;
      max_chip_temp_c?: number;
      voltage_enabled?: boolean;
      max_power_w?: number;
      fan_max_pct?: number;
    },
    ok: string,
  ) {
    setFeedback(null);
    setError(null);
    try {
      await setConfig.mutateAsync(payload);
      setFeedback(ok);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    }
  }

  async function toggleEnabled(next: boolean) {
    const payload: { enabled: boolean; max_freq_mhz?: number } = { enabled: next };
    if (next && typeof maxFreq === 'number' && Number.isFinite(maxFreq)) {
      payload.max_freq_mhz = maxFreq;
    }
    await run(payload, next ? 'Guardian enabled' : 'Guardian disabled');
  }

  function onToggle(next: boolean) {
    if (next) setConfirmOpen(true);
    else void toggleEnabled(false);
  }

  async function confirmEnable() {
    setConfirmOpen(false);
    await toggleEnabled(true);
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <Gauge className="h-4 w-4" /> Guardian
        </CardTitle>
        <Badge
          variant={enabled ? 'success' : 'secondary'}
          className="flex items-center gap-1.5"
        >
          <Activity className="h-3 w-3" /> {enabled ? 'Active' : 'Off'}
        </Badge>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* What it does */}
        <p className="text-sm text-muted-foreground">
          A slow, always-on governor that adapts ASIC <strong>frequency</strong>{' '}
          to both VR and ASIC chip heat. It backs off when either temperature or
          hardware errors climb, and recovers frequency when both sensors cool —
          never going above your max frequency.
        </p>

        {/* Enable toggle */}
        <div className="flex items-center justify-between border-t border-border pt-4">
          <div className="space-y-0.5">
            <Label className="text-sm">Enable Guardian on this miner</Label>
            <p className="text-xs text-muted-foreground">
              Re-evaluates every {d.interval_seconds}s. Changes apply live (no
              reboot).
            </p>
          </div>
          <Switch
            checked={enabled}
            disabled={pending}
            onCheckedChange={onToggle}
          />
        </div>

        {/* Max frequency (editable ceiling) */}
        <div className="space-y-2 border-t border-border pt-4">
          <Label htmlFor="guardian-max" className="text-sm">
            Max frequency (MHz)
          </Label>
          <div className="flex gap-2">
            <Input
              id="guardian-max"
              type="number"
              min={100}
              max={2000}
              step={5}
              value={maxFreq}
              onChange={(e) =>
                setMaxFreq(e.target.value === '' ? '' : Number(e.target.value))
              }
              disabled={pending}
              className="max-w-[140px]"
            />
            <Button
              variant="subtle"
              disabled={pending || maxFreq === ''}
              onClick={() =>
                typeof maxFreq === 'number' &&
                run({ max_freq_mhz: maxFreq }, `Max frequency set to ${maxFreq} MHz`)
              }
            >
              Save max
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            The ceiling the Guardian never exceeds. Defaults to the current
            frequency
            {currentFreq != null ? ` (${currentFreq} MHz)` : ''}; raise it only
            if you know your hardware sustains it.
          </p>
        </div>

        {/* VR Max temperature */}
        <div className="space-y-2 border-t border-border pt-4">
          <Label htmlFor="guardian-maxvrtemp" className="text-sm">
            VR Max temperature (°C)
          </Label>
          <div className="flex items-center gap-2">
            <Input
              id="guardian-maxvrtemp"
              type="number"
              min={40}
              max={110}
              step={1}
              value={maxVrTemp}
              onChange={(e) =>
                setMaxVrTemp(e.target.value === '' ? '' : Number(e.target.value))
              }
              disabled={pending}
              className="max-w-[100px]"
            />
            <Button
              variant="subtle"
              disabled={pending || maxVrTemp === '' || typeof maxVrTemp !== 'number' || maxVrTemp < 40 || maxVrTemp > 110}
              onClick={() =>
                typeof maxVrTemp === 'number' && maxVrTemp >= 40 && maxVrTemp <= 110 &&
                run({ max_vr_temp_c: maxVrTemp }, `VR max temperature set to ${maxVrTemp}°C`)
              }
            >
              Save VR temp
            </Button>
            <span className="text-xs text-muted-foreground">
              Hold setting down to ~{vrLowC}°C
            </span>
          </div>
          {typeof maxVrTemp === 'number' && (maxVrTemp < 40 || maxVrTemp > 110) && (
            <p className="text-xs text-destructive">
              VR max temperature must be between 40°C and 110°C.
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            The VR threshold above which it cuts frequency; holds down to {vrLowC}°C.
            Default: {d.vr_high_c}°C.
          </p>
        </div>

        {/* ASIC Chip Max temperature */}
        <div className="space-y-2 border-t border-border pt-4">
          <Label htmlFor="guardian-maxchiptemp" className="text-sm">
            ASIC Chip Max temperature (°C)
          </Label>
          <div className="flex items-center gap-2">
            <Input
              id="guardian-maxchiptemp"
              type="number"
              min={40}
              max={74}
              step={1}
              value={maxChipTemp}
              onChange={(e) =>
                setMaxChipTemp(e.target.value === '' ? '' : Number(e.target.value))
              }
              disabled={pending}
              className="max-w-[100px]"
            />
            <Button
              variant="subtle"
              disabled={pending || maxChipTemp === '' || typeof maxChipTemp !== 'number' || maxChipTemp < 40 || maxChipTemp >= 75}
              onClick={() =>
                typeof maxChipTemp === 'number' && maxChipTemp >= 40 && maxChipTemp < 75 &&
                run({ max_chip_temp_c: maxChipTemp }, `ASIC chip max temperature set to ${maxChipTemp}°C`)
              }
            >
              Save Chip temp
            </Button>
            <span className="text-xs text-muted-foreground">
              Hold setting down to ~{chipLowC}°C
            </span>
          </div>
          {typeof maxChipTemp === 'number' && (maxChipTemp < 40 || maxChipTemp >= 75) && (
            <p className="text-xs text-destructive">
              ASIC chip max temperature must be between 40°C and 74°C (below the 75°C overheat watchdog).
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            The ASIC chip threshold above which it cuts frequency; holds down to {chipLowC}°C.
            Default: {d.chip_high_c}°C. Keep it below the 75°C overheat watchdog.
          </p>
        </div>

        {/* Max power (per-miner override) */}
        <div className="space-y-2 border-t border-border pt-4">
          <Label htmlFor="guardian-maxpower" className="text-sm">
            Max power limit (W)
          </Label>
          <div className="flex items-center gap-2">
            <Input
              id="guardian-maxpower"
              type="number"
              min={10}
              max={500}
              step={1}
              value={maxPower}
              onChange={(e) =>
                setMaxPower(e.target.value === '' ? '' : Number(e.target.value))
              }
              disabled={pending}
              className="max-w-[100px]"
            />
            <Button
              variant="subtle"
              disabled={pending || maxPower === ''}
              onClick={() =>
                typeof maxPower === 'number' &&
                run({ max_power_w: maxPower }, `Max power limit set to ${maxPower} W`)
              }
            >
              Save power
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Per-miner override for the safety cutoff power limit. Gathers from the miner's
            hardware defaults, and falls back to the global limit ({d.power_cutoff_w ?? 40} W) if unset.
          </p>
        </div>

        {/* Tuning Max Fan Speed */}
        <div className="space-y-2 border-t border-border pt-4">
          <Label htmlFor="guardian-maxfan" className="text-sm">
            Tuning Max Fan Speed (%)
          </Label>
          <div className="flex items-center gap-2">
            <Input
              id="guardian-maxfan"
              type="number"
              min={20}
              max={100}
              step={5}
              value={fanMaxPct}
              onChange={(e) =>
                setFanMaxPct(e.target.value === '' ? '' : Number(e.target.value))
              }
              disabled={pending}
              className="max-w-[100px]"
            />
            <Button
              variant="subtle"
              disabled={pending || fanMaxPct === ''}
              onClick={() =>
                typeof fanMaxPct === 'number' &&
                run({ fan_max_pct: fanMaxPct }, `Tuning max fan speed set to ${fanMaxPct}%`)
              }
            >
              Save fan speed
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            The target fan speed Guardian pins the hardware to while actively tuning frequency.
            Defaults to 100%; lower it (e.g., 80% or 90%) for quieter tuning.
          </p>
        </div>

        {/* Voltage tuning (Phase 2) — only when the family + global master allow it */}
        {s.supports_voltage && s.voltage_master && (
          <div className="space-y-2 border-t border-border pt-4">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label className="text-sm">Voltage tuning (advanced)</Label>
                <p className="text-xs text-muted-foreground">
                  Also lets the Guardian raise/lower core voltage — to hold higher
                  frequencies and shed heat efficiently. More performance, more
                  risk. Hard cutoffs (temp/power/Vin) stay armed underneath.
                </p>
              </div>
              <Switch
                checked={s.voltage_enabled}
                disabled={pending}
                onCheckedChange={(next) => {
                  if (next) setVoltConfirmOpen(true);
                  else void run({ voltage_enabled: false }, 'Voltage tuning disabled');
                }}
              />
            </div>
            {s.voltage_enabled && (
              <p className="text-xs text-muted-foreground">
                Voltage envelope {d.v_floor_mv}–{d.v_ceiling_mv} mV, ±{d.v_step_mv} mV
                steps.
              </p>
            )}
          </div>
        )}

        {/* Policy summary */}
        <div className="space-y-1 border-t border-border pt-4 text-xs text-muted-foreground">
          <p className="font-semibold text-foreground">Policy</p>
          <p>
            VR &gt; {vrHighC}°C or Chip &gt; {chipHighC}°C → −{d.step_down_vr_mhz} MHz · Rejected
            shares &gt; {d.reject_pct_max}% → −{d.step_down_err_mhz} MHz · VR &lt; {vrLowC}°C &amp; Chip &lt; {chipLowC}°C → +{d.step_up_mhz} MHz (up to your max).
            Otherwise it holds. It also backs off — and won't push frequency up —
            when effective hashrate drops below {Math.round(d.valid_pct * 100)}% of
            the theoretical for the current frequency (ASIC instability).
          </p>
        </div>

        {/* Live readout */}
        <div className="space-y-2 border-t border-border pt-4">
          <p className="text-sm font-semibold">Live</p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
            <Stat label="Frequency" value={fmt(s.live?.frequency_mhz ?? currentFreq, 'MHz')} />
            <Stat label="Hashrate" value={fmt(s.live?.hashrate_ths ?? null, 'TH/s')} />
            <Stat label="Expected" value={fmt(s.live?.expected_ths ?? null, 'TH/s')} />
            <Stat label="Voltage" value={fmt(s.live?.voltage_mv ?? null, 'mV')} />
            <Stat label="VR temp" value={fmt(s.live?.vr_temp_c ?? null, '°C')} />
            <Stat label="Chip temp" value={fmt(s.live?.chip_temp_c ?? null, '°C')} />
            <Stat label="Reject" value={fmt(s.live?.reject_pct ?? null, '%')} />
            <Stat label="Error %" value={fmt(s.live?.error_pct ?? null, '%')} />
            <Stat label="Ceiling" value={fmt(s.live?.ceiling_mhz ?? s.max_freq_mhz, 'MHz')} />
            <Stat label="Floor" value={fmt(s.live?.floor_mhz ?? s.freq_floor_mhz, 'MHz')} />
          </div>
          {softCapped && (
            <p className="text-xs text-amber-400">
              Capped to {softCeil} MHz after an effective-hashrate drop (below
              your max). Disable and re-enable the Guardian to re-probe.
            </p>
          )}
          {s.live?.reason && (
            <p className="text-xs text-muted-foreground">
              Last decision: {s.live.reason}
            </p>
          )}
          {!s.live && enabled && (
            <p className="text-xs text-muted-foreground">
              Waiting for the first evaluation…
            </p>
          )}
        </div>

        {/* Risk note */}
        <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200/90">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            The Guardian changes your miner's frequency automatically. It monitors both VR and ASIC chip temperatures to stay within your targets, while the 75°C overheat watchdog remains active underneath. Run it at your own risk and keep an eye on the miner, especially right after enabling.
          </span>
        </div>

        {(feedback || error) && (
          <p
            className={`text-sm ${error ? 'text-destructive' : 'text-emerald-400'}`}
            role="status"
          >
            {error ?? feedback}
          </p>
        )}

        {/* Governor Chart & Collapsible Decision Logs */}
        <div className="space-y-4 border-t border-border pt-4">
          <GovernorChart minerId={miner.id} governorType="guardian" title="Guardian Frequency & Temperature History" />
          <GovernorDecisionLog minerId={miner.id} governorType="guardian" title="Guardian Decision Log" />
        </div>
      </CardContent>

      {/* At-your-own-risk confirmation, shown when enabling the Guardian. */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 text-amber-400" /> Enable Guardian?
            </DialogTitle>
            <DialogDescription asChild>
              <div className="space-y-3 pt-1 text-sm text-muted-foreground">
                <p>
                  The Guardian automatically changes your miner's ASIC frequency
                  while it runs. This is an advanced feature that you enable{' '}
                  <strong className="text-foreground">at your own risk</strong>.
                </p>
                <p>
                  We strongly recommend staying near the miner and watching it
                  closely,{' '}
                  <strong className="text-foreground">
                    especially the first time
                  </strong>{' '}
                  you turn it on. The 75°C overheat watchdog stays armed
                  underneath, but you remain responsible for your hardware.
                </p>
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="subtle" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={pending}
              onClick={confirmEnable}
              className="gap-1.5"
            >
              <ShieldAlert className="h-4 w-4" /> I understand — enable
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Stronger confirmation for the Phase 2 voltage co-tuner. */}
      <Dialog open={voltConfirmOpen} onOpenChange={setVoltConfirmOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 text-amber-400" /> Enable voltage tuning?
            </DialogTitle>
            <DialogDescription asChild>
              <div className="space-y-3 pt-1 text-sm text-muted-foreground">
                <p>
                  This lets the Guardian change your miner's{' '}
                  <strong className="text-foreground">core voltage</strong>{' '}
                  automatically, not just its frequency. Raising voltage increases
                  power draw, heat and stress on the VRM and ASIC — it's the most
                  aggressive thing the Guardian can do, and you enable it{' '}
                  <strong className="text-foreground">at your own risk</strong>.
                </p>
                <p>
                  Hard cutoffs (chip/VR temperature, power and input-voltage
                  limits) stay armed and the 75°C watchdog sits underneath, but you
                  remain responsible for your hardware. Watch it closely,
                  especially the first time.
                </p>
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="subtle" onClick={() => setVoltConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={pending}
              onClick={async () => {
                setVoltConfirmOpen(false);
                await run({ voltage_enabled: true }, 'Voltage tuning enabled');
              }}
              className="gap-1.5"
            >
              <ShieldAlert className="h-4 w-4" /> I understand — enable
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function fmt(v: number | null | undefined, unit: string): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return `${v} ${unit}`;
}
