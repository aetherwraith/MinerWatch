import { useEffect, useState } from 'react';
import { Activity, Gauge, ShieldAlert, Clock, Plus, Trash2, Play } from 'lucide-react';

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
import {
  useGuardianStatus,
  useSetGuardianConfig,
  useGuardianProfiles,
  useSaveGuardianProfile,
  useDeleteGuardianProfile,
  useApplyProfileById,
  useGuardianSchedules,
  useSaveGuardianSchedule,
  useDeleteGuardianSchedule,
} from '@/api/hooks';
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
    setMaxVrTemp(s.max_vr_temp_c ?? '');
    setMaxChipTemp(s.max_chip_temp_c ?? '');
    setMaxPower(s.max_power_w ?? s.effective_power_w ?? s.defaults.power_cutoff_w ?? 40);
    setFanMaxPct(s.fan_max_pct ?? 100);
  }, [
    s?.max_freq_mhz,
    s?.current_freq_mhz,
    s?.max_vr_temp_c,
    s?.max_chip_temp_c,
    s?.max_power_w,
    s?.effective_power_w,
    s?.defaults?.power_cutoff_w,
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
      clear_vr_temp?: boolean;
      clear_chip_temp?: boolean;
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
        <div className="space-y-3 border-t border-border pt-4">
          <div className="flex items-center justify-between">
            <Label className="text-sm font-medium">VR Temperature Target (°C)</Label>
            <Badge variant={s.vr_temp_source === 'custom' ? 'default' : 'secondary'} className="text-xs">
              {s.vr_temp_source === 'custom'
                ? `Custom Guardian Override (${s.effective_vr_temp_c}°C)`
                : s.vr_temp_source === 'governor'
                ? `Inherited from Auto-Fan (${s.effective_vr_temp_c}°C)`
                : `Global Default (${s.effective_vr_temp_c}°C)`}
            </Badge>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <Button
              variant={s.vr_temp_source !== 'custom' ? 'default' : 'outline'}
              size="sm"
              disabled={pending}
              onClick={() => {
                setMaxVrTemp('');
                void run({ clear_vr_temp: true }, 'VR target set to inherit from Auto-Fan');
              }}
            >
              Use Auto-Fan target ({s.autofan_vr_temp_c ?? d.vr_high_c}°C)
            </Button>
            <Button
              variant={s.vr_temp_source === 'custom' ? 'default' : 'outline'}
              size="sm"
              disabled={pending}
              onClick={() => {
                if (typeof maxVrTemp !== 'number') setMaxVrTemp(s.effective_vr_temp_c);
              }}
            >
              Set Custom Override
            </Button>
          </div>

          {(s.vr_temp_source === 'custom' || typeof maxVrTemp === 'number') && (
            <div className="flex items-center gap-2 flex-wrap pt-1">
              <Input
                id="guardian-maxvrtemp"
                type="number"
                min={40}
                max={110}
                step={1}
                value={maxVrTemp}
                placeholder={`${s.effective_vr_temp_c}`}
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
                  run({ max_vr_temp_c: maxVrTemp }, `VR custom override set to ${maxVrTemp}°C`)
                }
              >
                Save VR override
              </Button>
              <span className="text-xs text-muted-foreground">
                Hold setting down to ~{vrLowC}°C
              </span>
            </div>
          )}
          {typeof maxVrTemp === 'number' && (maxVrTemp < 40 || maxVrTemp > 110) && (
            <p className="text-xs text-destructive">
              VR max temperature must be between 40°C and 110°C.
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            The VR threshold above which frequency steps down; holds down to ~{vrLowC}°C.
            Active target: {s.effective_vr_temp_c}°C ({s.vr_temp_source}).
          </p>
        </div>

        {/* ASIC Chip Max temperature */}
        <div className="space-y-3 border-t border-border pt-4">
          <div className="flex items-center justify-between">
            <Label className="text-sm font-medium">ASIC Chip Temperature Target (°C)</Label>
            <Badge variant={s.chip_temp_source === 'custom' ? 'default' : 'secondary'} className="text-xs">
              {s.chip_temp_source === 'custom'
                ? `Custom Guardian Override (${s.effective_chip_temp_c}°C)`
                : s.chip_temp_source === 'governor'
                ? `Inherited from Auto-Fan (${s.effective_chip_temp_c}°C)`
                : `Global Default (${s.effective_chip_temp_c}°C)`}
            </Badge>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <Button
              variant={s.chip_temp_source !== 'custom' ? 'default' : 'outline'}
              size="sm"
              disabled={pending}
              onClick={() => {
                setMaxChipTemp('');
                void run({ clear_chip_temp: true }, 'ASIC chip target set to inherit from Auto-Fan');
              }}
            >
              Use Auto-Fan target ({s.autofan_chip_temp_c ?? d.chip_high_c}°C)
            </Button>
            <Button
              variant={s.chip_temp_source === 'custom' ? 'default' : 'outline'}
              size="sm"
              disabled={pending}
              onClick={() => {
                if (typeof maxChipTemp !== 'number') setMaxChipTemp(s.effective_chip_temp_c);
              }}
            >
              Set Custom Override
            </Button>
          </div>

          {(s.chip_temp_source === 'custom' || typeof maxChipTemp === 'number') && (
            <div className="flex items-center gap-2 flex-wrap pt-1">
              <Input
                id="guardian-maxchiptemp"
                type="number"
                min={40}
                max={74}
                step={1}
                value={maxChipTemp}
                placeholder={`${s.effective_chip_temp_c}`}
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
                  run({ max_chip_temp_c: maxChipTemp }, `ASIC chip custom override set to ${maxChipTemp}°C`)
                }
              >
                Save Chip override
              </Button>
              <span className="text-xs text-muted-foreground">
                Hold setting down to ~{chipLowC}°C
              </span>
            </div>
          )}
          {typeof maxChipTemp === 'number' && (maxChipTemp < 40 || maxChipTemp >= 75) && (
            <p className="text-xs text-destructive">
              ASIC chip max temperature must be between 40°C and 74°C (below the 75°C overheat watchdog).
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            The ASIC chip threshold above which frequency steps down; holds down to ~{chipLowC}°C.
            Active target: {s.effective_chip_temp_c}°C ({s.chip_temp_source}). Keep below 75°C overheat watchdog.
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

        {/* Guardian Profiles & Scheduled Profile Switcher (Placed above history graphs and logs) */}
        <GuardianProfilesAndSchedules
          minerId={miner.id}
          currentFreq={currentFreq}
          activeProfile={s?.active_profile}
          minerFanMode={miner.fan_mode}
          minerFanSpeed={miner.fan_min_override}
        />

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

function GuardianProfilesAndSchedules({
  minerId,
  currentFreq,
  activeProfile,
  minerFanMode,
  minerFanSpeed,
}: {
  minerId: number;
  currentFreq: number | null;
  activeProfile?: string | null;
  minerFanMode?: string | null;
  minerFanSpeed?: number | null;
}) {
  const { data: profData } = useGuardianProfiles(minerId);
  const { data: schedData } = useGuardianSchedules(minerId);
  const saveProfile = useSaveGuardianProfile(minerId);
  const deleteProfile = useDeleteGuardianProfile(minerId);
  const applyProfile = useApplyProfileById(minerId);
  const saveSchedule = useSaveGuardianSchedule(minerId);
  const deleteSchedule = useDeleteGuardianSchedule(minerId);

  const profiles = profData?.profiles ?? [];
  const schedules = schedData?.schedules ?? [];

  const [newProfileName, setNewProfileName] = useState('');
  const [profFreq, setProfFreq] = useState<number | ''>(currentFreq ?? 500);
  const [profVolt, setProfVolt] = useState<number | ''>('');
  const [profFanMode, setProfFanMode] = useState<string>('manual');
  const [customFanPct, setCustomFanPct] = useState<number>(minerFanSpeed ?? 60);
  const [selectedProfileId, setSelectedProfileId] = useState<number | null>(null);
  const [schedTime, setSchedTime] = useState('08:00');
  const [schedDays] = useState<string[]>(['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']);

  useEffect(() => {
    if (currentFreq && profFreq === 500) {
      setProfFreq(currentFreq);
    }
  }, [currentFreq]);

  const handleSaveProfile = () => {
    if (!newProfileName.trim()) return;

    let targetFanMode: string | undefined;
    let targetFanSpeed: number | undefined;

    if (profFanMode === 'manual') {
      targetFanMode = 'manual';
      targetFanSpeed = Number(customFanPct) || 60;
    } else if (profFanMode === 'minerwatch') {
      targetFanMode = 'minerwatch';
      targetFanSpeed = Number(customFanPct) || 80;
    } else if (profFanMode === 'firmware') {
      targetFanMode = 'firmware';
    } else {
      targetFanMode = (minerFanMode || 'firmware').toLowerCase();
      targetFanSpeed = minerFanSpeed ?? 60;
    }

    const freqVal = profFreq !== '' ? Number(profFreq) : (currentFreq ?? 500);
    const voltVal = profVolt !== '' ? Number(profVolt) : undefined;

    saveProfile.mutate(
      {
        name: newProfileName.trim(),
        max_freq_mhz: freqVal,
        voltage_mv: voltVal,
        fan_mode: targetFanMode as any,
        fan_speed_pct: targetFanMode === 'manual' ? targetFanSpeed : undefined,
        fan_max_pct: targetFanSpeed,
      },
      {
        onSuccess: () => {
          setNewProfileName('');
        },
      }
    );
  };

  const handleAddSchedule = () => {
    if (!selectedProfileId) return;
    saveSchedule.mutate({
      profile_id: selectedProfileId,
      time_hhmm: schedTime,
      days: schedDays,
      enabled: true,
    });
  };

  return (
    <div className="space-y-4 pt-4 border-t border-border">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold text-sm">
          <Clock className="h-4 w-4 text-emerald-400" />
          Guardian Profiles & Time-of-Day Switcher
        </div>
        <span className="text-xs text-muted-foreground font-mono">
          {profiles.length} Profiles · {schedules.length} Rules
        </span>
      </div>

      {/* Profiles Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
        {profiles.map((p) => {
          const isActive = activeProfile === p.name;
          const displaySpeed = p.fan_speed_pct ?? p.fan_max_pct;
          return (
            <div
              key={p.id}
              className={`p-3.5 rounded-lg border flex flex-col justify-between gap-3 transition-colors ${
                isActive ? 'border-emerald-500 bg-emerald-500/10' : 'border-border/60 bg-muted/20'
              }`}
            >
              <div className="space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-xs text-foreground truncate">{p.name}</span>
                  {isActive ? (
                    <Badge className="bg-emerald-500 text-slate-950 font-bold text-[10px] shrink-0">
                      Active Now
                    </Badge>
                  ) : p.is_benchmark ? (
                    <Badge variant="outline" className="text-[10px] bg-emerald-500/10 text-emerald-400 border-emerald-500/30 shrink-0">
                      Benchmark
                    </Badge>
                  ) : (
                    <Badge variant="secondary" className="text-[10px] shrink-0">
                      Custom
                    </Badge>
                  )}
                </div>
                <div className="text-[11px] text-muted-foreground space-y-0.5 font-mono">
                  {p.max_freq_mhz && <div>Frequency: <span className="text-foreground">{p.max_freq_mhz} MHz</span></div>}
                  {p.voltage_mv && <div>Voltage: <span className="text-foreground">{p.voltage_mv} mV</span></div>}
                  {p.fan_mode === 'manual' ? (
                    <div>Fan: <span className="text-emerald-400 font-semibold">Manual ({displaySpeed ?? 50}%)</span></div>
                  ) : p.fan_mode === 'minerwatch' ? (
                    <div>Fan: <span className="text-foreground">Auto-Fan (Max {displaySpeed ?? 100}%)</span></div>
                  ) : displaySpeed ? (
                    <div>Max Fan: <span className="text-foreground">{displaySpeed}%</span></div>
                  ) : null}
                </div>
              </div>

              <div className="flex items-center justify-between gap-2 pt-2 border-t border-border/40">
                <Button
                  variant={isActive ? 'default' : 'subtle'}
                  size="sm"
                  onClick={() => applyProfile.mutate(p.id)}
                  disabled={applyProfile.isPending || isActive}
                  className={`h-8 text-xs flex-1 gap-1.5 ${
                    isActive ? 'bg-emerald-600 text-white opacity-80' : 'text-emerald-400 hover:text-emerald-300'
                  }`}
                >
                  <Play className="h-3 w-3 fill-current" />
                  {isActive ? 'Active' : 'Apply Now'}
                </Button>
                {!p.is_benchmark && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => deleteProfile.mutate(p.id)}
                    disabled={deleteProfile.isPending}
                    className="h-8 w-8 p-0 shrink-0 text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Form: Save / Create Profile */}
      <div className="p-3.5 rounded-lg border border-border/60 bg-muted/20 space-y-3 text-xs">
        <div className="font-semibold text-foreground">Save or Create Guardian Profile</div>
        <div className="grid grid-cols-1 sm:grid-cols-12 gap-3 items-end">
          <div className="sm:col-span-3 space-y-1">
            <Label className="text-xs text-muted-foreground">Profile Name</Label>
            <Input
              placeholder="e.g. Quiet Profile (Day)"
              value={newProfileName}
              onChange={(e) => setNewProfileName(e.target.value)}
              className="h-9 text-xs font-mono w-full"
            />
          </div>

          <div className="sm:col-span-2 space-y-1">
            <Label className="text-xs text-muted-foreground">Freq (MHz)</Label>
            <Input
              type="number"
              value={profFreq}
              onChange={(e) => setProfFreq(e.target.value === '' ? '' : Number(e.target.value))}
              placeholder="500"
              className="h-9 text-xs font-mono w-full"
            />
          </div>

          <div className="sm:col-span-2 space-y-1">
            <Label className="text-xs text-muted-foreground">Volt (mV, opt)</Label>
            <Input
              type="number"
              value={profVolt}
              onChange={(e) => setProfVolt(e.target.value === '' ? '' : Number(e.target.value))}
              placeholder="Auto"
              className="h-9 text-xs font-mono w-full"
            />
          </div>

          <div className="sm:col-span-3 space-y-1">
            <Label className="text-xs text-muted-foreground">Fan Control Mode</Label>
            <select
              value={profFanMode}
              onChange={(e) => setProfFanMode(e.target.value)}
              className="h-9 w-full rounded-md border border-border bg-background px-2 text-xs font-mono text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="manual">Manual Fan Speed (%)</option>
              <option value="minerwatch">Auto-Fan (MinerWatch)</option>
              <option value="firmware">Firmware Auto</option>
              <option value="current">Keep Current Fan Mode</option>
            </select>
          </div>

          {profFanMode === 'manual' || profFanMode === 'minerwatch' ? (
            <div className="sm:col-span-2 space-y-1">
              <Label className="text-xs text-muted-foreground">
                {profFanMode === 'manual' ? 'Manual Fan %' : 'Max Fan %'}
              </Label>
              <Input
                type="number"
                min={10}
                max={100}
                value={customFanPct}
                onChange={(e) => setCustomFanPct(Number(e.target.value))}
                className="h-9 text-xs font-mono w-full"
              />
            </div>
          ) : null}

          <div className={`${profFanMode === 'firmware' || profFanMode === 'current' ? 'sm:col-span-2' : 'sm:col-span-12 sm:col-start-1'} pt-1`}>
            <Button
              variant="secondary"
              size="sm"
              onClick={handleSaveProfile}
              disabled={saveProfile.isPending || !newProfileName.trim()}
              className="h-9 w-full text-xs font-medium gap-1.5 shrink-0"
            >
              <Plus className="h-3.5 w-3.5" />
              Save Profile
            </Button>
          </div>
        </div>
      </div>

      {/* Time-of-Day Profile Switcher Table & Add Form */}
      <div className="space-y-3 pt-2">
        <div className="text-xs font-semibold text-muted-foreground">Active Time-of-Day Switch Rules</div>

        {schedules.length > 0 && (
          <div className="rounded-md border border-border/60 overflow-hidden text-xs">
            <table className="w-full text-left">
              <thead className="bg-muted/50 text-muted-foreground border-b border-border/60">
                <tr>
                  <th className="p-2.5 pl-3 w-24">Time</th>
                  <th className="p-2.5">Target Profile</th>
                  <th className="p-2.5 w-36">Days</th>
                  <th className="p-2.5 text-right pr-3 w-16">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {schedules.map((sc) => (
                  <tr key={sc.id} className="hover:bg-muted/20">
                    <td className="p-2.5 pl-3 font-mono font-semibold text-emerald-400">{sc.time_hhmm}</td>
                    <td className="p-2.5 font-medium">{sc.profile_name || 'Profile'}</td>
                    <td className="p-2.5 text-muted-foreground uppercase text-[10px]">
                      {sc.days_json ? JSON.parse(sc.days_json).join(', ') : 'ALL'}
                    </td>
                    <td className="p-2.5 text-right pr-3">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => deleteSchedule.mutate(sc.id)}
                        disabled={deleteSchedule.isPending}
                        className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Add Schedule Form */}
        <div className="p-3.5 rounded-lg border border-border/60 bg-muted/20 space-y-3 text-xs">
          <div className="font-semibold text-foreground">Add Automatic Time-of-Day Profile Switch</div>
          <div className="grid grid-cols-1 sm:grid-cols-12 gap-3 items-end">
            <div className="sm:col-span-3 space-y-1">
              <Label className="text-xs text-muted-foreground">Time (HH:MM)</Label>
              <Input
                type="time"
                value={schedTime}
                onChange={(e) => setSchedTime(e.target.value)}
                className="h-9 text-xs font-mono w-full"
              />
            </div>

            <div className="sm:col-span-6 space-y-1">
              <Label className="text-xs text-muted-foreground">Target Profile</Label>
              <select
                value={selectedProfileId ?? ''}
                onChange={(e) => setSelectedProfileId(Number(e.target.value))}
                className="h-9 w-full rounded-md border border-border bg-background px-3 text-xs font-mono text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="">Select Target Profile...</option>
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="sm:col-span-3">
              <Button
                variant="default"
                size="sm"
                onClick={handleAddSchedule}
                disabled={saveSchedule.isPending || !selectedProfileId}
                className="h-9 w-full text-xs font-medium gap-1.5 bg-emerald-600 hover:bg-emerald-500 text-white"
              >
                <Plus className="h-3.5 w-3.5" />
                Add Rule
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
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
