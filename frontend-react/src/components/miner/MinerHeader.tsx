import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Pause, Play, Power, Trash2, Zap } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ApiError } from '@/lib/api';
import {
  useDeleteMiner,
  usePauseMiner,
  useRestartMiner,
  useResumeMiner,
  useShutdownMiner,
} from '@/api/hooks';
import { FAMILY_LABEL } from '@/lib/format';
import type { MinerDetailResponse } from '@/lib/types';

interface Props {
  data: MinerDetailResponse;
}

export function MinerHeader({ data }: Props) {
  const navigate = useNavigate();
  const restart = useRestartMiner();
  const pause = usePauseMiner();
  const resume = useResumeMiner();
  const shutdown = useShutdownMiner();
  const remove = useDeleteMiner();
  const qc = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [restartOpen, setRestartOpen] = useState(false);
  const [standbyOpen, setStandbyOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // In-flight Standby/Resume transition. The BitForge ASIC ramps for ~10s
  // each way and the firmware re-seeds its hashrate estimator on resume, so
  // we can't trust the POST response or the raw hashrate to mark the
  // transition done. We overlay a local phase (pausing/resuming) on top of
  // the firmware-reported mining_paused, poll faster while it runs, and
  // resolve it from the live sample (or a deadline).
  const [phase, setPhase] = useState<'idle' | 'pausing' | 'resuming'>('idle');
  const phaseDeadlineRef = useRef(0);
  const resumeAcceptedBaselineRef = useRef<number | null>(null);

  const { miner } = data;
  // Two firmware paths to the same "Standby" idea:
  //  - AxeOS Bitaxe: pause/resume (soft, no reboot)          → capabilities.pause
  //  - NerdQAxe (shufps): shutdown, resume only via restart  → capabilities.shutdown
  const canPause = data.capabilities?.pause ?? false;
  const canShutdown = data.capabilities?.shutdown ?? false;
  // Firmware-level gate: only show Standby when the miner actually reports
  // its stopped-state field (AxeOS/forge-os `miningPaused` / NerdQAxe
  // `shutdown`), surfaced by the backend as mining_paused. On firmware
  // without it the value is null → hide the button instead of offering a
  // control the firmware would 404.
  const supportsStandby =
    (canPause || canShutdown) && data.live_sample?.mining_paused != null;
  const firmwarePaused = data.live_sample?.mining_paused === true;
  const liveHashrate = data.live_sample?.hashrate_ths ?? null;
  const liveAccepted = data.live_sample?.accepted ?? null;
  // Four-state view: an in-flight transition wins over the firmware flag.
  const standbyState: 'mining' | 'pausing' | 'paused' | 'resuming' =
    phase === 'pausing'
      ? 'pausing'
      : phase === 'resuming'
        ? 'resuming'
        : firmwarePaused
          ? 'paused'
          : 'mining';
  const standbyPending = canPause ? pause.isPending : shutdown.isPending;
  const resumePending = canPause ? resume.isPending : restart.isPending;
  const familyLabel = FAMILY_LABEL[miner.family] ?? miner.family;
  const subtitleParts = [
    familyLabel,
    `${miner.host}${miner.port ? `:${miner.port}` : ''}`,
    miner.mac,
  ].filter(Boolean);

  // Auto-dismiss the "command sent" banner after the firmware has had time
  // to apply the change and a poll or two to reflect it.
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 30000);
    return () => clearTimeout(t);
  }, [notice]);

  // Poll the detail faster while a transition is in flight so the badge
  // resolves close to real time (the standard cadence is 5s).
  useEffect(() => {
    if (phase === 'idle') return;
    const iv = setInterval(() => {
      qc.invalidateQueries({ queryKey: ['miner', miner.id] });
    }, 1500);
    return () => clearInterval(iv);
  }, [phase, miner.id, qc]);

  // Resolve the transition from the live sample.
  //  - Pausing is done once the firmware confirms paused AND hashing has
  //    stopped (hashrate ~0; the backend nulls the post-resume spike, so a
  //    null reading also counts as "not hashing").
  //  - Resuming is done once the firmware clears the paused flag AND a new
  //    share has been accepted — the only trustworthy "really mining again"
  //    signal, since the raw hashrate is garbage for a while after re-init.
  useEffect(() => {
    if (phase === 'pausing') {
      if (firmwarePaused && (liveHashrate == null || liveHashrate <= 0.05)) {
        setPhase('idle');
      }
    } else if (phase === 'resuming') {
      const base = resumeAcceptedBaselineRef.current;
      const newShare = liveAccepted != null && base != null && liveAccepted > base;
      if (!firmwarePaused && newShare) {
        setPhase('idle');
      }
    }
  }, [phase, firmwarePaused, liveHashrate, liveAccepted]);

  // Safety net: never get stuck in a transition. Resolve at the deadline
  // even if the confirming signal never arrives (slow pool, dropped poll).
  useEffect(() => {
    if (phase === 'idle') return;
    const pendingPhase = phase;
    const ms = Math.max(0, phaseDeadlineRef.current - Date.now());
    const t = setTimeout(() => {
      setPhase('idle');
      setNotice(
        pendingPhase === 'pausing'
          ? `${miner.name}: pause requested but not confirmed in time — it may still be ramping down. Re-check in a moment.`
          : `${miner.name}: resume sent and accepted — the hashrate can take up to a minute to settle to a real value.`,
      );
    }, ms);
    return () => clearTimeout(t);
  }, [phase, miner.name]);

  async function doRestart() {
    setError(null);
    try {
      await restart.mutateAsync(miner.id);
      setRestartOpen(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    }
  }

  async function doStandby() {
    setError(null);
    try {
      await (canPause ? pause : shutdown).mutateAsync(miner.id);
      setStandbyOpen(false);
      setNotice(null);
      // AxeOS/forge-os has a soft pause whose ramp we can track to "Paused".
      // NerdQAxe shutdown has no live ramp to watch — its `shutdown` flag
      // just flips — so we don't drive a "pausing" phase for it.
      if (canPause) {
        phaseDeadlineRef.current = Date.now() + 20_000;
        setPhase('pausing');
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    }
  }

  async function doResume() {
    setError(null);
    try {
      // AxeOS/forge-os has a soft resume; NerdQAxe resumes only via a restart.
      // Capture the accepted-shares baseline first so the resuming phase can
      // detect the first new share (the trustworthy "really mining" signal).
      resumeAcceptedBaselineRef.current = data.live_sample?.accepted ?? null;
      await (canPause ? resume : restart).mutateAsync(miner.id);
      setNotice(null);
      if (canPause) {
        phaseDeadlineRef.current = Date.now() + 35_000;
        setPhase('resuming');
      } else {
        setNotice(
          `Resume command sent — ${miner.name} is restarting and will be back within ~30s.`,
        );
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    }
  }

  async function doDelete() {
    setError(null);
    try {
      await remove.mutateAsync(miner.id);
      navigate('/');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    }
  }

  return (
    <>
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <Button asChild variant="ghost" size="icon" className="-ml-1 mt-0.5">
            <Link to="/" aria-label="Back to dashboard">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              {miner.name}
              {miner.guardian_active_profile && (
                <span className="ml-2.5 inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 px-3 py-0.5 align-middle text-xs font-mono font-medium text-emerald-400">
                  <Zap className="h-3.5 w-3.5 fill-current" />
                  {miner.guardian_active_profile}
                </span>
              )}
              {standbyState !== 'mining' && (
                <span className="ml-2 inline-flex items-center rounded-full bg-amber-500/15 px-2 py-0.5 align-middle text-xs font-medium text-amber-600">
                  {standbyState === 'pausing'
                    ? 'Pausing…'
                    : standbyState === 'resuming'
                      ? 'Resuming…'
                      : 'Standby'}
                </span>
              )}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {subtitleParts.join(' · ')}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {supportsStandby &&
            (standbyState === 'pausing' || standbyState === 'resuming' ? (
              <Button variant="subtle" disabled>
                {standbyState === 'pausing' ? (
                  <>
                    <Pause className="h-4 w-4" /> Pausing…
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4" /> Resuming…
                  </>
                )}
              </Button>
            ) : standbyState === 'paused' ? (
              <Button variant="subtle" onClick={doResume} disabled={resumePending}>
                <Play className="h-4 w-4" /> {resumePending ? 'Resuming…' : 'Resume'}
              </Button>
            ) : (
              <Button
                variant="subtle"
                onClick={() => setStandbyOpen(true)}
                disabled={standbyPending}
              >
                <Pause className="h-4 w-4" /> Standby
              </Button>
            ))}
          <Button variant="subtle" onClick={() => setRestartOpen(true)}>
            <Power className="h-4 w-4" /> Restart
          </Button>
          <Button variant="destructive" onClick={() => setConfirmOpen(true)}>
            <Trash2 className="h-4 w-4" /> Remove
          </Button>
        </div>
      </header>

      {notice && (
        <div
          className="mt-3 flex items-start justify-between gap-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-600"
          role="status"
        >
          <span>{notice}</span>
          <button
            type="button"
            onClick={() => setNotice(null)}
            className="shrink-0 text-amber-600/70 hover:text-amber-600"
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      )}

      <Dialog open={restartOpen} onOpenChange={setRestartOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Restart {miner.name}?</DialogTitle>
            <DialogDescription>
              The miner reboots and is unreachable for ~30 seconds. Historical metrics are
              preserved.
            </DialogDescription>
          </DialogHeader>
          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRestartOpen(false)} disabled={restart.isPending}>
              Cancel
            </Button>
            <Button onClick={doRestart} disabled={restart.isPending}>
              {restart.isPending ? 'Sending…' : 'Restart'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={standbyOpen} onOpenChange={setStandbyOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Put {miner.name} into standby?</DialogTitle>
            <DialogDescription>
              Mining stops and the ASIC powers down — power draw and heat fall to near idle.
              The miner stays reachable and reports 0 H/s.{' '}
              {canPause
                ? 'Press Resume to bring it back (no reboot). A power cycle also resumes mining; this state is not saved across a reboot.'
                : 'This firmware has no soft resume: bring it back with Resume (which restarts the miner) or a power cycle. The state is not saved across a reboot.'}
            </DialogDescription>
          </DialogHeader>
          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setStandbyOpen(false)} disabled={standbyPending}>
              Cancel
            </Button>
            <Button onClick={doStandby} disabled={standbyPending}>
              {standbyPending ? 'Sending…' : 'Put into standby'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove {miner.name}?</DialogTitle>
            <DialogDescription>
              This deletes the device registration and all historical metrics for this miner.
              The miner itself keeps running on the LAN — you can re-add it later via Scan
              network or Add miner. <strong>This action cannot be undone.</strong>
            </DialogDescription>
          </DialogHeader>
          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)} disabled={remove.isPending}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={doDelete} disabled={remove.isPending}>
              {remove.isPending ? 'Removing…' : 'Remove permanently'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
