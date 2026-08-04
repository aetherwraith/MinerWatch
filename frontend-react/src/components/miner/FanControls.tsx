import { useEffect, useState } from 'react';
import { AlertTriangle, Fan, Hand, Sparkles } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Slider } from '@/components/ui/slider';
import { Badge } from '@/components/ui/badge';
import { ApiError } from '@/lib/api';
import { useSetFan, useSetFanConfig } from '@/api/hooks';
import { GovernorChart } from '@/components/miner/GovernorChart';
import { GovernorDecisionLog } from '@/components/miner/GovernorDecisionLog';
import type { MinerDetailResponse } from '@/lib/types';

interface Props {
  data: MinerDetailResponse;
}

/**
 * Controls tab — fan-only.
 *
 * Frequency and voltage controls are intentionally not surfaced in the
 * vanilla page (commented out in miner.js) because direct overclock /
 * undervolt from the UI is dangerous if used without instrumentation.
 * We keep the same posture here: the capability is reported and the
 * backend endpoints exist, but the UI exposes only fan management.
 */
export function FanControls({ data }: Props) {
  const { miner, capabilities, live_sample } = data;
  const rawPayload = (live_sample as any)?.raw ?? {};
  const firmwareTargetTemp = (live_sample as any)?.temp_target ?? rawPayload.tempTarget ?? rawPayload.pidTargetTemp ?? rawPayload.targetTemp;

  const initialTarget = miner.auto_target_c ?? (firmwareTargetTemp != null ? Number(firmwareTargetTemp) : 65);
  const [target, setTarget] = useState<number>(initialTarget);
  const [minFanPct, setMinFanPct] = useState<number>(miner.fan_min_override ?? 25);
  const defaultVr = miner.fan_vr_target_c ?? initialTarget ?? 60;
  const [vrTarget, setVrTarget] = useState<number>(defaultVr);

  const [autoFanLinked, setAutoFanLinked] = useState<boolean>(miner.fan_linked === 0 ? false : true);
  const [fan1Source, setFan1Source] = useState<string>(miner.fan1_source ?? 'asic');
  const [fan2Source, setFan2Source] = useState<string>(miner.fan2_source ?? 'vr');

  const hasMultipleFans =
    (data.last_metric?.fan_pct_2 != null) ||
    (miner.family?.toLowerCase() === 'nerdoctaxe');

  const [linkFans, setLinkFans] = useState<boolean>(true);
  const lastFanPct = data.last_metric?.fan_pct ?? null;
  const lastFanPct2 = data.last_metric?.fan_pct_2 ?? null;
  const initialPct = miner.fan_mode === 'manual' && lastFanPct
    ? Math.round(Number(lastFanPct))
    : 50;
  const initialPct2 = miner.fan_mode === 'manual' && lastFanPct2
    ? Math.round(Number(lastFanPct2))
    : initialPct;

  const [pct, setPct] = useState<number>(initialPct);
  const [pct2, setPct2] = useState<number>(initialPct2);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const setFan = useSetFan(miner.id);
  const setFanConfig = useSetFanConfig(miner.id);

  // Keep fields in sync with backend state on first load / external changes
  useEffect(() => {
    const effTarget = miner.auto_target_c ?? (firmwareTargetTemp != null ? Number(firmwareTargetTemp) : 65);
    setTarget(effTarget);
    setMinFanPct(miner.fan_min_override ?? 25);
    setVrTarget(miner.fan_vr_target_c ?? effTarget ?? 60);
    setAutoFanLinked(miner.fan_linked === 0 ? false : true);
    setFan1Source(miner.fan1_source ?? 'asic');
    setFan2Source(miner.fan2_source ?? 'vr');
  }, [
    miner.auto_target_c,
    firmwareTargetTemp,
    miner.fan_min_override,
    miner.fan_vr_target_c,
    miner.fan_linked,
    miner.fan1_source,
    miner.fan2_source,
  ]);

  if (!capabilities.set_fan) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          Write controls are not supported for this miner family. Only the toolbar
          actions (Restart, Remove) are available.
        </CardContent>
      </Card>
    );
  }

  const fanMode = miner.fan_mode ?? 'firmware';

  async function applyManual() {
    setFeedback(null);
    setError(null);
    try {
      await setFanConfig.mutateAsync({ fan_mode: 'manual' });
      if (hasMultipleFans && !linkFans) {
        await setFan.mutateAsync({ percent: pct, percent2: pct2 });
        setFeedback(`Fans set: Fan 1 = ${pct}%, Fan 2 = ${pct2}%`);
      } else {
        await setFan.mutateAsync({ percent: pct });
        setFeedback(`Fan set to ${pct}%`);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    }
  }

  async function enableFirmwareAuto() {
    setFeedback(null);
    setError(null);
    try {
      await setFanConfig.mutateAsync({
        fan_mode: 'firmware',
        auto_target_c: Number.isFinite(target) ? target : undefined,
      });
      setFeedback(`AUTO (firmware) control enabled — target ${target}°C`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    }
  }

  async function enableAuto() {
    setFeedback(null);
    setError(null);
    if (Number.isNaN(target)) {
      setError('Set the target temperature first.');
      return;
    }
    try {
      await setFanConfig.mutateAsync({
        fan_mode: 'minerwatch',
        auto_target_c: target,
      });
      setFeedback(`AUTO (MinerWatch) enabled — target ${target}°C`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    }
  }

  async function saveTarget() {
    setFeedback(null);
    setError(null);
    if (Number.isNaN(target) || target < 30 || target > 95) {
      setError('Invalid ASIC target temperature (30–95°C).');
      return;
    }
    try {
      await setFanConfig.mutateAsync({ auto_target_c: target });
      setFeedback(`Target saved: ${target}°C`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    }
  }

  async function saveMinFanPct() {
    setFeedback(null);
    setError(null);
    if (Number.isNaN(minFanPct) || minFanPct < 0 || minFanPct > 100) {
      setError('Invalid minimum fan speed (0–100%).');
      return;
    }
    try {
      await setFanConfig.mutateAsync({ fan_min_override: minFanPct });
      setFeedback(`Minimum fan speed floor set to ${minFanPct}%`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    }
  }

  async function saveVrTarget() {
    setFeedback(null);
    setError(null);
    if (Number.isNaN(vrTarget) || vrTarget < 40 || vrTarget > 110) {
      setError('Invalid VR target temperature (40–110°C).');
      return;
    }
    try {
      await setFanConfig.mutateAsync({ fan_vr_target_c: vrTarget });
      setFeedback(`VR target temperature saved: ${vrTarget}°C`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    }
  }

  async function saveAutoFanMapping() {
    setFeedback(null);
    setError(null);
    try {
      await setFanConfig.mutateAsync({
        fan_linked: autoFanLinked ? 1 : 0,
        fan1_source: fan1Source,
        fan2_source: fan2Source,
      });
      setFeedback(
        autoFanLinked
          ? 'Auto-fan governor set to Linked (both fans respond to highest temperature).'
          : `Auto-fan governor set to Independent: Fan 1 → ${fan1Source.toUpperCase()}, Fan 2 → ${fan2Source.toUpperCase()}`
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    }
  }

  const modeBadge =
    fanMode === 'manual'
      ? { icon: Hand, label: 'Manual', tone: 'outline' as const }
      : fanMode === 'minerwatch'
        ? { icon: Sparkles, label: 'AUTO (MinerWatch)', tone: 'success' as const }
        : { icon: Fan, label: 'AUTO (firmware)', tone: 'secondary' as const };

  const pending = setFan.isPending || setFanConfig.isPending;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Fan</CardTitle>
        <Badge variant={modeBadge.tone} className="flex items-center gap-1.5">
          <modeBadge.icon className="h-3 w-3" /> {modeBadge.label}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-3">
          {hasMultipleFans && (
            <div className="flex items-center justify-between border-b border-border pb-2">
              <span className="text-xs text-muted-foreground">Dual-fan setup</span>
              <label className="flex items-center gap-2 text-xs font-medium cursor-pointer">
                <input
                  type="checkbox"
                  checked={linkFans}
                  onChange={(e) => {
                    const checked = e.target.checked;
                    setLinkFans(checked);
                    if (checked) setPct2(pct);
                  }}
                  className="rounded border-border bg-background"
                />
                Link Fan 1 &amp; Fan 2
              </label>
            </div>
          )}

          <div className="flex items-center justify-between">
            <Label className="text-sm">{hasMultipleFans && !linkFans ? 'Fan 1 Speed' : 'Manual speed'}</Label>
            <span className="text-sm font-semibold tabular-nums">{pct}%</span>
          </div>
          <Slider
            value={[pct]}
            min={0}
            max={100}
            step={1}
            disabled={pending}
            onValueChange={(v) => {
              const val = v[0] ?? pct;
              setPct(val);
              if (linkFans) setPct2(val);
            }}
          />

          {hasMultipleFans && !linkFans && (
            <div className="space-y-2 pt-2">
              <div className="flex items-center justify-between">
                <Label className="text-sm">Fan 2 Speed</Label>
                <span className="text-sm font-semibold tabular-nums">{pct2}%</span>
              </div>
              <Slider
                value={[pct2]}
                min={0}
                max={100}
                step={1}
                disabled={pending}
                onValueChange={(v) => setPct2(v[0] ?? pct2)}
              />
            </div>
          )}

          {(pct < 25 || (hasMultipleFans && !linkFans && pct2 < 25)) && (
            <div className="flex items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-200/90">
              <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
              <span>
                <strong>Warning:</strong> Manual fan speeds below 25% risk severe overheating on VRM and ASIC components under load.
              </span>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={applyManual}
              disabled={pending}
              variant={fanMode === 'manual' ? 'default' : 'subtle'}
              className="flex-1 sm:flex-initial"
            >
              <Hand className="h-4 w-4" /> Apply Manual
            </Button>
            <Button
              variant={fanMode === 'firmware' ? 'default' : 'subtle'}
              onClick={enableFirmwareAuto}
              disabled={pending}
              className="flex-1 sm:flex-initial"
            >
              <Fan className="h-4 w-4" /> Firmware AUTO
            </Button>
            <Button
              variant={fanMode === 'minerwatch' ? 'default' : 'subtle'}
              onClick={enableAuto}
              disabled={pending}
              className="flex-1 sm:flex-initial"
            >
              <Sparkles className="h-4 w-4" /> MinerWatch AUTO
            </Button>
          </div>
        </div>

        {/* ASIC Target Temperature */}
        <div className="space-y-2 border-t border-border pt-4">
          <Label htmlFor="auto-target" className="text-sm">
            Target ASIC temperature for MinerWatch AUTO (°C)
          </Label>
          <div className="flex gap-2">
            <Input
              id="auto-target"
              type="number"
              min={40}
              max={90}
              step={0.5}
              value={Number.isFinite(target) ? target : ''}
              onChange={(e) => setTarget(Number(e.target.value))}
              disabled={pending}
              className="max-w-[140px]"
            />
            <Button variant="subtle" onClick={saveTarget} disabled={pending}>
              Save target
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Chip hint: BM1370 (Gamma) ~60–65°C · BM1397 ~65–70°C · Avalon Nano 3s ~70–75°C.
          </p>
        </div>

        {/* Minimum Fan Speed Floor */}
        <div className="space-y-2 border-t border-border pt-4">
          <Label htmlFor="fan-min-speed" className="text-sm">
            Minimum fan speed floor (%)
          </Label>
          <div className="flex gap-2">
            <Input
              id="fan-min-speed"
              type="number"
              min={0}
              max={100}
              step={1}
              value={Number.isFinite(minFanPct) ? minFanPct : ''}
              onChange={(e) => setMinFanPct(Number(e.target.value))}
              disabled={pending}
              className="max-w-[140px]"
            />
            <Button variant="subtle" onClick={saveMinFanPct} disabled={pending}>
              Save min speed
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            The minimum fan speed floor enforced by the MinerWatch auto-fan governor. Default: 25%.
          </p>
        </div>

        {/* VR Target Temperature */}
        <div className="space-y-2 border-t border-border pt-4">
          <Label htmlFor="vr-target" className="text-sm">
            VR Target temperature (°C)
          </Label>
          <div className="flex gap-2">
            <Input
              id="vr-target"
              type="number"
              min={40}
              max={110}
              step={1}
              value={Number.isFinite(vrTarget) ? vrTarget : ''}
              onChange={(e) => setVrTarget(Number(e.target.value))}
              disabled={pending}
              className="max-w-[140px]"
            />
            <Button variant="subtle" onClick={saveVrTarget} disabled={pending}>
              Save VR target
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Target VR temperature regulated by the auto-fan governor. Defaults to your ASIC target temperature.
          </p>
        </div>

        {/* Auto-Fan Governor Linking */}
        {hasMultipleFans && (
          <div className="space-y-3 border-t border-border pt-4">
            <div className="flex items-center justify-between">
              <Label className="text-sm font-medium">Auto-Fan Governor Linking</Label>
              <label className="flex items-center gap-2 text-xs font-medium cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoFanLinked}
                  onChange={(e) => setAutoFanLinked(e.target.checked)}
                  disabled={pending}
                  className="rounded border-border bg-background"
                />
                Link Fans in Auto Mode
              </label>
            </div>

            {!autoFanLinked && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
                <div className="space-y-1.5">
                  <Label className="text-xs">Fan 1 Target Sensor</Label>
                  <select
                    value={fan1Source}
                    onChange={(e) => setFan1Source(e.target.value)}
                    disabled={pending}
                    className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <option value="asic">ASIC Chip Temp (°C)</option>
                    <option value="vr">VRM Temp (°C)</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Fan 2 Target Sensor</Label>
                  <select
                    value={fan2Source}
                    onChange={(e) => setFan2Source(e.target.value)}
                    disabled={pending}
                    className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <option value="asic">ASIC Chip Temp (°C)</option>
                    <option value="vr">VRM Temp (°C)</option>
                  </select>
                </div>
              </div>
            )}

            <div className="flex justify-end">
              <Button variant="subtle" size="sm" onClick={saveAutoFanMapping} disabled={pending}>
                Save governor linking
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              {autoFanLinked
                ? 'Linked: Both fans run together at the speed required to satisfy whichever temperature sensor is hotter.'
                : 'Independent: Fan 1 and Fan 2 are driven by separate PID decision loops based on their assigned temperature sensor.'}
            </p>
          </div>
        )}

        <p className="text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">Apply Manual</span> = fixed fan percentage.{' '}
          <span className="font-semibold text-foreground">Firmware AUTO</span> = returns fan control back to the miner's onboard firmware controller.{' '}
          <span className="font-semibold text-foreground">MinerWatch AUTO</span> = server-side PID controller adjusts linked fan speeds every 5 s to hold chip and VR temps within target.
        </p>

        {(feedback || error) && (
          <p className={`text-sm ${error ? 'text-destructive' : 'text-emerald-400'}`} role="status">
            {error ?? feedback}
          </p>
        )}

        {/* Governor Chart & Collapsible Decision Logs */}
        <div className="space-y-4 border-t border-border pt-4">
          <GovernorChart minerId={miner.id} governorType="autofan" title="Auto-Fan Control & Temperature History" hasMultipleFans={hasMultipleFans} />
          <GovernorDecisionLog minerId={miner.id} governorType="autofan" title="Auto-Fan Decision Log" />
        </div>
      </CardContent>
    </Card>
  );
}
