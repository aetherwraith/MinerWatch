# SPDX-License-Identifier: AGPL-3.0-only
"""Guardian — a runtime frequency governor for AxeOS miners (Bitaxe / Nerd*).

This is a continuous, *slow* control loop. It is a twin of the server-side
auto-fan PID in ``auto_control.py``, but acts on a different lever and a
different sensor:

  - the auto-fan PID is the FAST inner loop (5 s): it modulates the FAN to
    hold the CHIP temperature near a target;
  - the Guardian is the SLOW outer loop (default 5 min): it nudges the ASIC
    FREQUENCY to keep the VR (voltage-regulator) temperature and the
    rejected-share rate inside safe bounds, recovering frequency when cool.

Nothing else in MinerWatch governs the VR in a closed loop — the fan PID
and the 75 °C overheat watchdog both watch the *chip*. The VR is frequently
the real bottleneck, so a VR-driven frequency governor fills a genuine gap
rather than duplicating the fan logic. The two loops reinforce each other:
when the VR gets hot the Guardian cuts frequency → less power → the VR
*and* the chip cool → the fan PID eases off.

Control law (v1, frequency-only), evaluated once per ``interval_seconds``:

    VR temp   > vr_high_c        → frequency − step_down_vr_mhz   (safety)
    reject %  > reject_pct_max   → frequency − step_down_err_mhz  (safety)
    VR temp   < vr_low_c         → frequency + step_up_mhz        (recover)
    otherwise (deadband)         → hold

Down-actions (safety) take priority over the upward recovery, and every
result is clamped to the per-miner ``[floor, ceiling]``. The ceiling is the
user's "max frequency" — by default the miner's current frequency at the
moment the Guardian is enabled, but editable for expert users.

Why the cadence is the safety knob: AxeOS applies a frequency change LIVE
(no reboot — confirmed for both Bitaxe and Nerd*), so there is no downtime
cost per nudge. The limiting factor is instead the VR's *thermal inertia*:
after a change the VR keeps drifting for a minute or two. Ticking faster
than that would mean acting on a reading that hasn't finished responding,
which causes hunting. So the loop runs on a long interval (≥ the VR settle
time), and an optional ``cooldown_seconds`` can enforce extra settle time.

NVS wear: a frequency PATCH persists to the ESP32's flash. The governor
only writes when the target *differs* from the live frequency, so inside the
65–70 °C deadband it parks on an equilibrium frequency and stops writing.

Reversibility: this is an additive bolt-on. It lives in this module, reads
``poller.last_results``, uses only driver methods that already exist
(``set_frequency`` / ``poll``) and three per-miner columns on the ``miners``
table. It never changes voltage in v1 (see the v2 notes below and in
docs/guardian-design.md).

v2 (not active here): AxeOS also applies *voltage* changes live, which opens
a second lever — respond to a sustained reject rate by RAISING coreVoltage
(the proper fix for undervolt instability) instead of only cutting freq, and
optionally lower voltage alongside frequency cuts to preserve J/TH. Auto-
raising voltage 24/7 unattended is riskier (more heat/watts, closer to the
hardware limits), so it stays out of v1. The decision function and the
config carry the seams for it; see ``GuardianCfg.v2_*`` and the design doc.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from . import db
from .config import get_config
from .miners import driver_for_record
from .miners.base import MinerSample

log = logging.getLogger("minerwatch.guardian")

# Families this governor knows how to drive. All speak the AxeOS REST API
# and expose ``vrTemp`` (or ``vcore`` temp mapping for nmaxe); the VR temperature
# is the primary control signal.
# bitforge (forge-os) lacks ``expectedHashrate``, so its validity test
# relies on the smallCoreCount × asicCount fallback.
GUARDIAN_FAMILIES = ("bitaxe", "nerdoctaxe", "bitforge", "nmaxe")


# ============================================================================
# Pure decision function (no I/O — unit-tested in tests/test_guardian.py)
# ============================================================================

def decide_frequency(
    *,
    current_freq: int,
    ceiling_mhz: int,
    floor_mhz: int,
    temp_c: float | None = None,
    hw_error_pct: float | None = None,
    temp_high_c: float | None = None,
    temp_low_c: float | None = None,
    vr_temp_c: float | None = None,
    vr_high_c: float | None = None,
    vr_low_c: float | None = None,
    chip_temp_c: float | None = None,
    chip_high_c: float | None = None,
    chip_low_c: float | None = None,
    hw_error_pct_max: float = 1.1,
    step_down_temp_mhz: int = 20,
    step_down_err_mhz: int = 10,
    step_up_mhz: int = 10,
    source_label: str = "VR",
    hashrate_invalid: bool = False,
    step_down_hr_mhz: int | None = None,
    allow_recovery: bool = True,
    instability_label: str = "hashrate below theoretical",
    fan_pct: float | None = None,
    max_fan_pct: float = 95.0,
) -> tuple[int, str]:
    """Decide the next frequency for one miner.

    Returns ``(target_freq_mhz, reason)``. ``target_freq_mhz == current_freq``
    means "hold" (the caller then writes nothing, sparing NVS). The function
    is deliberately pure so the policy can be reasoned about and tested in
    isolation from the driver/poller plumbing.

    Supports monitoring both VR and ASIC chip temperatures simultaneously when
    ``vr_temp_c`` and ``chip_temp_c`` are provided alongside their thresholds.
    Also checks fan overhead before stepping up frequency.
    """
    # Defensive: a mis-set floor above the ceiling must not brick the loop.
    floor_mhz = min(floor_mhz, ceiling_mhz)

    # 0. Enforce the per-miner ceiling/floor first, regardless of sensors.
    if current_freq > ceiling_mhz:
        return ceiling_mhz, f"above max {ceiling_mhz} MHz → cap to ceiling"
    if current_freq < floor_mhz:
        return floor_mhz, f"below floor {floor_mhz} MHz → raise to floor"

    # 1..3 — the control law. Priority: back off on heat (VR then Chip),
    # then on instability, and only otherwise try to recover frequency.
    vr_over = vr_temp_c is not None and vr_high_c is not None and round(vr_temp_c, 1) > round(vr_high_c, 1)
    chip_over = chip_temp_c is not None and chip_high_c is not None and round(chip_temp_c, 1) > round(chip_high_c, 1)
    legacy_over = temp_c is not None and temp_high_c is not None and round(temp_c, 1) > round(temp_high_c, 1)

    if vr_over:
        target = current_freq - step_down_temp_mhz
        reason = f"VR {vr_temp_c:.1f}°C > {vr_high_c:.1f}°C → -{step_down_temp_mhz} MHz"
    elif chip_over:
        target = current_freq - step_down_temp_mhz
        reason = f"Chip {chip_temp_c:.1f}°C > {chip_high_c:.1f}°C → -{step_down_temp_mhz} MHz"
    elif legacy_over:
        target = current_freq - step_down_temp_mhz
        reason = (
            f"{source_label} {temp_c:.1f}°C > {temp_high_c:.1f}°C "
            f"→ -{step_down_temp_mhz} MHz"
        )
    elif hashrate_invalid:
        sd_hr = step_down_hr_mhz if step_down_hr_mhz is not None else step_down_temp_mhz
        target = current_freq - sd_hr
        reason = f"{instability_label} (instability) → -{sd_hr} MHz"
    elif hw_error_pct is not None and hw_error_pct > hw_error_pct_max:
        target = current_freq - step_down_err_mhz
        reason = (
            f"Reject {hw_error_pct:.2f}% > {hw_error_pct_max:.2f}% "
            f"→ -{step_down_err_mhz} MHz"
        )
    else:
        # Check recovery condition: all active sensors must be cool and fan overhead must exist.
        vr_cool = vr_temp_c is None or vr_high_c is None or vr_low_c is None or round(vr_temp_c, 1) < round(vr_low_c, 1)
        chip_cool = chip_temp_c is None or chip_high_c is None or chip_low_c is None or round(chip_temp_c, 1) < round(chip_low_c, 1)
        legacy_cool = temp_c is None or temp_high_c is None or temp_low_c is None or round(temp_c, 1) < round(temp_low_c, 1)
        has_temp_reading = vr_temp_c is not None or chip_temp_c is not None or temp_c is not None
        fan_overhead_ok = fan_pct is None or fan_pct < max_fan_pct

        if allow_recovery and has_temp_reading and vr_cool and chip_cool and legacy_cool:
            if not fan_overhead_ok:
                return current_freq, f"cool but fan at max capacity ({fan_pct:.0f}%) → hold frequency"
            target = current_freq + step_up_mhz
            if vr_temp_c is not None and chip_temp_c is not None and vr_low_c is not None and chip_low_c is not None:
                reason = f"VR {vr_temp_c:.1f}°C & Chip {chip_temp_c:.1f}°C cool → +{step_up_mhz} MHz"
            elif vr_temp_c is not None and vr_low_c is not None:
                reason = f"VR {vr_temp_c:.1f}°C < {vr_low_c:.1f}°C → +{step_up_mhz} MHz"
            elif chip_temp_c is not None and chip_low_c is not None:
                reason = f"Chip {chip_temp_c:.1f}°C < {chip_low_c:.1f}°C → +{step_up_mhz} MHz"
            else:
                reason = f"{source_label} {temp_c:.1f}°C < {temp_low_c:.1f}°C → +{step_up_mhz} MHz"
        else:
            return current_freq, "hold (within deadband)"

    target = max(floor_mhz, min(ceiling_mhz, target))
    if target == current_freq:
        return current_freq, "hold (at limit)"
    return target, reason


def vin_band(
    vin_mv: float | None, vin_min_mv: float, vin_max_mv: float
) -> tuple[float, float]:
    """Scale the configured Vin window to the board's input rail."""
    if vin_mv is not None and vin_mv > 8000:
        return vin_min_mv * 12 / 5, vin_max_mv * 12 / 5
    return vin_min_mv, vin_max_mv


def decide_point(
    *,
    current_freq: int,
    current_volt: int,
    ceiling_mhz: int,
    floor_mhz: int,
    volt_ceiling_mv: int,
    volt_floor_mv: int,
    temp_c: float | None = None,
    temp_high_c: float | None = None,
    temp_low_c: float | None = None,
    vr_temp_high_c: float | None = None,
    vr_temp_low_c: float | None = None,
    chip_temp_high_c: float | None = None,
    chip_temp_low_c: float | None = None,
    hashrate_invalid: bool,
    valid: bool,
    instability_label: str = "hashrate below theoretical",
    chip_c: float | None,
    chip_cutoff_c: float,
    vr_c: float | None,
    vr_cutoff_c: float,
    power_w: float | None,
    power_cutoff_w: float | None,
    vin_mv: float | None,
    vin_min_mv: float,
    vin_max_mv: float,
    step_down_mhz: int,
    step_up_mhz: int,
    step_volt_mv: int,
    fan_pct: float | None = None,
    max_fan_pct: float = 95.0,
) -> tuple[int, int, str]:
    """Decide ``(target_freq_mhz, target_volt_mv, reason)`` for the V/F co-tuner."""
    f, v = int(current_freq), int(current_volt)
    floor_mhz = min(floor_mhz, ceiling_mhz)
    volt_floor_mv = min(volt_floor_mv, volt_ceiling_mv)

    # 0. Enforce the envelope first.
    if f > ceiling_mhz:
        return ceiling_mhz, min(v, volt_ceiling_mv), f"above max {ceiling_mhz} MHz → cap"
    if v > volt_ceiling_mv:
        return f, volt_ceiling_mv, f"above max {volt_ceiling_mv} mV → cap"
    if f < floor_mhz:
        return floor_mhz, v, f"below floor {floor_mhz} MHz → raise"

    # 1. Hard safety cutoffs — back BOTH levers off at once.
    hard = None
    if chip_c is not None and round(chip_c, 1) >= round(chip_cutoff_c, 1):
        hard = f"chip {chip_c:.1f}°C ≥ {chip_cutoff_c:.1f}°C"
    elif vr_c is not None and round(vr_c, 1) >= round(vr_cutoff_c, 1):
        hard = f"VR {vr_c:.1f}°C ≥ {vr_cutoff_c:.1f}°C"
    elif power_cutoff_w and power_w is not None and power_w >= power_cutoff_w:
        hard = f"power {power_w:.0f}W ≥ {power_cutoff_w:.0f}W"
    elif vin_mv is not None and (vin_mv < vin_min_mv or vin_mv > vin_max_mv):
        hard = f"Vin {vin_mv:.0f}mV out of range"
    if hard is not None:
        nf = max(floor_mhz, f - step_down_mhz)
        nv = max(volt_floor_mv, v - step_volt_mv)
        if nf == f and nv == v:
            return f, v, f"safety: {hard} (at floor)"
        return nf, nv, f"safety: {hard} → back off"

    # 2. Temperature over user limits → co-move down the V/F curve.
    vr_over = vr_c is not None and vr_temp_high_c is not None and round(vr_c, 1) > round(vr_temp_high_c, 1)
    chip_over = chip_c is not None and chip_temp_high_c is not None and round(chip_c, 1) > round(chip_temp_high_c, 1)
    legacy_over = temp_c is not None and temp_high_c is not None and round(temp_c, 1) > round(temp_high_c, 1)
    if vr_over or chip_over or legacy_over:
        nf = max(floor_mhz, f - step_down_mhz)
        nv = max(volt_floor_mv, v - step_volt_mv)
        if nf == f and nv == v:
            return f, v, "hold (at limit)"
        lbl = "VR" if vr_over else ("Chip" if chip_over else "temp")
        val = vr_c if vr_over else (chip_c if chip_over else temp_c)
        hi = vr_temp_high_c if vr_over else (chip_temp_high_c if chip_over else temp_high_c)
        return nf, nv, f"{lbl} {val:.1f}°C > {hi:.1f}°C → back off"

    # 3. Instability → cure with voltage if there's thermal+power+fan headroom
    if hashrate_invalid:
        power_ok = (
            not power_cutoff_w or power_w is None or power_w < power_cutoff_w * 0.92
        )
        temp_ok = (
            (vr_c is None or vr_temp_high_c is None or round(vr_c, 1) <= round(vr_temp_high_c - 2, 1))
            and (chip_c is None or chip_temp_high_c is None or round(chip_c, 1) <= round(chip_temp_high_c - 2, 1))
            and (temp_c is None or temp_high_c is None or round(temp_c, 1) <= round(temp_high_c - 2, 1))
        )
        fan_ok = fan_pct is None or fan_pct < max_fan_pct
        if v < volt_ceiling_mv and power_ok and temp_ok and fan_ok:
            nv = min(volt_ceiling_mv, v + step_volt_mv)
            return f, nv, f"{instability_label} → +{nv - v} mV (cure)"
        elif v < volt_ceiling_mv and not fan_ok:
            return f, v, f"{instability_label}, fan at max ({fan_pct:.0f}%) → hold voltage"
        nf = max(floor_mhz, f - step_down_mhz)
        if nf == f:
            return f, v, "hold (at floor)"
        return nf, v, f"{instability_label}, V maxed → -{f - nf} MHz"

    # 4. Valid and cool → push frequency up for more hashrate (if fan overhead exists)
    vr_cool = vr_c is None or vr_temp_low_c is None or round(vr_c, 1) < round(vr_temp_low_c, 1)
    chip_cool = chip_c is None or chip_temp_low_c is None or round(chip_c, 1) < round(chip_temp_low_c, 1)
    legacy_cool = temp_c is None or temp_low_c is None or round(temp_c, 1) < round(temp_low_c, 1)
    if valid and vr_cool and chip_cool and legacy_cool and f < ceiling_mhz:
        if fan_pct is not None and fan_pct >= max_fan_pct:
            return f, v, f"cool but fan at max capacity ({fan_pct:.0f}%) → hold frequency"
        nf = min(ceiling_mhz, f + step_up_mhz)
        if nf != f:
            fan_lbl = f" (fan {fan_pct:.0f}%)" if fan_pct is not None else ""
            return nf, v, f"valid & cool{fan_lbl} → +{nf - f} MHz"

    # 5. Hold — park (no NVS write).
    return f, v, "hold (within deadband)"


# ============================================================================
# Per-miner state
# ============================================================================

class _GuardianState:
    """Mutable per-miner state the loop carries between ticks."""

    __slots__ = (
        "consecutive_holds",
        "is_tuning",
        "last_change_ts",
        "last_commanded_freq",
        "last_hashrate",
        "last_reason",
        "last_reject_pct",
        "last_temp_c",
        "last_ts",
        "prev_accepted",
        "prev_hw_errors",
        "prev_rejected",
        "soft_ceiling",
    )

    def __init__(self) -> None:
        self.prev_accepted: int | None = None
        self.prev_rejected: int | None = None
        self.last_commanded_freq: int | None = None
        self.last_change_ts: float = 0.0
        self.last_reason: str | None = None
        self.last_ts: float = 0.0
        self.last_temp_c: float | None = None
        self.last_reject_pct: float | None = None
        self.soft_ceiling: int | None = None
        self.prev_hw_errors: int | None = None
        self.last_hashrate: float | None = None
        self.consecutive_holds: int = 0
        self.is_tuning: bool = True


def _reject_pct(
    state: _GuardianState, sample: MinerSample, min_shares: int
) -> float | None:
    """Rejected-share % over the interval = Δrejected / Δ(acc+rej) × 100, or None.

    Replaces the old errorCount/total HW% which was wrong on AxeOS: the
    hashrateMonitor ``total`` field is the *hashrate*, not a work counter, so
    dividing the cumulative error count by it produced absurd values (>100%).
    Rejected shares (``sharesRejected`` / ``sharesAccepted``) are genuine
    monotonic counters available on every AxeOS family, and their ratio sits
    in the right ballpark (well under 1% on a healthy miner).

    Computed as a *windowed* delta (instability shows up as a burst of fresh
    rejects), guarded by ``min_shares``: if too few shares landed in the
    interval the rate is statistically meaningless, so we return None (the
    caller then governs on VR alone this tick). Returns None on the first
    tick (no baseline) and on a counter reset (miner rebooted).

    Side effect: advances the stored baseline to the current counters.
    """
    acc = sample.accepted
    rej = sample.rejected
    prev_a = state.prev_accepted
    prev_r = state.prev_rejected

    pct: float | None = None
    if (
        acc is not None and rej is not None
        and prev_a is not None and prev_r is not None
        and acc >= prev_a and rej >= prev_r  # guard against counter resets
    ):
        d_acc = acc - prev_a
        d_rej = rej - prev_r
        d_tot = d_acc + d_rej
        if d_tot >= max(1, int(min_shares)):
            pct = (d_rej / d_tot) * 100.0

    # Advance the baseline (also resets cleanly after a detected reset).
    state.prev_accepted = acc
    state.prev_rejected = rej
    return pct


# ============================================================================
# Guardian controller (one slow loop for the whole fleet)
# ============================================================================

class GuardianController:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._states: dict[int, _GuardianState] = {}
        # Live status per miner, surfaced by the API/UI.
        self._status: dict[int, dict[str, Any]] = {}
        self.last_tick_ts: float = 0.0

    # ---- lifecycle (mirrors AutoFanController) ----

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="minerwatch-guardian")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()
        self._task = None

    def status(self, miner_id: int) -> dict[str, Any] | None:
        return self._status.get(int(miner_id))

    def is_tuning(self, miner_id: int) -> bool:
        """Return True if Guardian is actively searching/tuning frequency for miner_id."""
        st = self._states.get(int(miner_id))
        if st is None:
            return True
        return st.is_tuning

    async def eval_miner_now(self, miner_id: int) -> None:
        """Immediately trigger an evaluation tick for one miner upon enable/config change."""
        from .poller import poller as _poller
        m = await db.get_miner(int(miner_id))
        if m and _coerce_bool(m.get("guardian_enabled")):
            sample = _poller.last_results.get(int(miner_id))
            if sample:
                await self._eval_miner(m, sample, time.time())

    def reset_miner(self, miner_id: int) -> None:
        """Drop a miner's in-memory governor state (soft ceiling, reject-rate
        baseline, settle timer) and its live readout.

        Called when the user changes the miner's Guardian config so a setting
        change re-probes *immediately* — otherwise the soft ceiling only clears
        on the next tick, and a quick disable→re-enable (within one interval)
        never clears it at all because the per-tick cleanup never runs while the
        miner is disabled.
        """
        self._states.pop(int(miner_id), None)
        self._status.pop(int(miner_id), None)

    # ---- main loop ----

    async def _run(self) -> None:
        cfg = get_config().guardian
        log.info(
            "Guardian started — interval=%ds VR>%.0f°C −%dMHz / reject%%>%.2f −%dMHz "
            "/ VR<%.0f°C +%dMHz, floor=%dMHz",
            cfg.interval_seconds, cfg.vr_high_c, cfg.step_down_vr_mhz,
            cfg.reject_pct_max, cfg.step_down_err_mhz,
            cfg.vr_low_c, cfg.step_up_mhz, cfg.frequency_floor_mhz,
        )
        from .poller import poller as _poller

        while not self._stop.is_set():
            try:
                if get_config().guardian.enabled:
                    await self._tick(_poller.last_results)
            except Exception:
                log.exception("guardian tick error")
            # Re-read the interval each loop so a settings change takes effect
            # without a restart.
            interval = max(30, int(get_config().guardian.interval_seconds))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue
        log.info("Guardian stopped")

    async def _tick(self, samples: dict[int, MinerSample]) -> None:
        self.last_tick_ts = time.time()
        cfg = get_config()
        gcfg = cfg.guardian
        miners = await db.list_miners(only_enabled=True)
        seen: set[int] = set()

        for miner in miners:
            miner_id = int(miner["id"])
            if not _coerce_bool(miner.get("guardian_enabled")):
                continue
            family = (miner.get("family") or "").lower()
            if family not in GUARDIAN_FAMILIES:
                continue
            sample = samples.get(miner_id)
            if sample is None or not sample.online:
                continue
            # Skip a miner that's deliberately in standby (AxeOS pause): its
            # ASIC is powered down and reads 0 H/s, which the governor would
            # otherwise read as instability and try to "cure" by raising
            # voltage on a chip that isn't even running. Leaving it out of
            # ``seen`` also drops its state, so it restarts from a fresh
            # baseline on resume.
            if sample.mining_paused:
                continue
            seen.add(miner_id)
            try:
                await self._govern_one(miner, sample, gcfg, cfg)
            except Exception:
                log.exception("guardian: miner=%s govern error", miner.get("name"))

        # Drop state for miners no longer governed/online so a returning miner
        # starts with a fresh reject-rate baseline instead of a stale delta.
        for mid in list(self._states):
            if mid not in seen:
                self._states.pop(mid, None)
        for mid in list(self._status):
            if mid not in seen:
                self._status.pop(mid, None)

    async def _govern_one(self, miner: dict, sample: MinerSample, gcfg, cfg) -> None:
        miner_id = int(miner["id"])
        state = self._states.get(miner_id)
        if state is None:
            state = _GuardianState()
            self._states[miner_id] = state

        # Current frequency: trust the live sample; fall back to what we last
        # commanded if the firmware didn't report it this poll.
        current_freq = (
            int(sample.frequency_mhz)
            if sample.frequency_mhz
            else state.last_commanded_freq
        )

        # Reject % over the interval (advances the baseline as a side effect).
        reject_pct = _reject_pct(state, sample, gcfg.reject_min_shares)

        # Both VR and Chip temperatures are monitored simultaneously.
        source = "both"
        source_label = "VR/Chip"

        # Fetch recent averages over the configured window to avoid transient dips/spikes
        window = int(getattr(gcfg, "hashrate_average_window_seconds", 30))
        avg_metrics = {}
        if window > 0:
            try:
                avg_metrics = await db.get_recent_metrics_average(miner_id, window)
            except Exception:
                log.exception("guardian: failed to fetch recent averages for miner=%s", miner.get("name"))

        # Fallback to instantaneous values if not found or window is 0
        hashrate_ths = avg_metrics.get("hashrate_ths")
        if hashrate_ths is None:
            hashrate_ths = sample.hashrate_ths

        temp_chip_c = avg_metrics.get("temp_chip_c")
        if temp_chip_c is None:
            temp_chip_c = sample.temp_chip_c

        temp_vr_c = avg_metrics.get("temp_vr_c")
        if temp_vr_c is None:
            temp_vr_c = sample.temp_vr_c

        power_w = avg_metrics.get("power_w")
        if power_w is None:
            power_w = sample.power_w

        error_pct = avg_metrics.get("error_pct")
        if error_pct is None:
            error_pct = sample.error_pct

        temp_c = temp_vr_c if temp_vr_c is not None else temp_chip_c

        # Effective hashrate (TH/s) and the ASIC hardware-error percentage (error_pct)
        hw_errors = sample.hw_errors
        err_delta = None
        if (
            hw_errors is not None
            and state.prev_hw_errors is not None
            and hw_errors >= state.prev_hw_errors
        ):
            err_delta = hw_errors - state.prev_hw_errors
        if hw_errors is not None:
            state.prev_hw_errors = hw_errors
        tele = dict(
            hashrate_ths=hashrate_ths,
            asic_errors=hw_errors,
            asic_error_delta=err_delta,
        )

        now = time.time()
        state.last_ts = now
        state.last_temp_c = temp_c
        state.last_reject_pct = reject_pct
        state.last_hashrate = hashrate_ths

        if current_freq is None:
            self._publish(miner_id, miner, current_freq, temp_c, reject_pct,
                          "no frequency reading", changed=False, source=source,
                          vr_temp_c=temp_vr_c, chip_temp_c=temp_chip_c,
                          soft_ceiling=state.soft_ceiling, **tele)
            return

        ceiling = miner.get("guardian_max_freq_mhz")
        ceiling = int(ceiling) if ceiling else int(current_freq)
        floor = miner.get("guardian_freq_floor_mhz")
        floor = int(floor) if floor else int(gcfg.frequency_floor_mhz)

        # Resolve VR and Chip temperature thresholds
        family_name = (miner.get("family") or "").lower()
        vr_default_high, vr_default_low = gcfg.temp_band("vr", family_name)
        chip_default_high, chip_default_low = gcfg.temp_band("chip", family_name)

        max_vr_temp = miner.get("guardian_max_vr_temp_c")
        if not max_vr_temp and str(miner.get("guardian_temp_source") or "").lower() == "vr":
            max_vr_temp = miner.get("guardian_max_temp_c")
        if max_vr_temp:
            vr_high = float(max_vr_temp)
            vr_low = vr_high - (vr_default_high - vr_default_low)
        else:
            vr_high, vr_low = vr_default_high, vr_default_low

        max_chip_temp = miner.get("guardian_max_chip_temp_c")
        if not max_chip_temp and str(miner.get("guardian_temp_source") or "").lower() == "chip":
            max_chip_temp = miner.get("guardian_max_temp_c")
        if max_chip_temp:
            chip_high = float(max_chip_temp)
            chip_low = chip_high - (chip_default_high - chip_default_low)
        else:
            chip_high, chip_low = chip_default_high, chip_default_low

        eff_ceiling = ceiling
        if state.soft_ceiling is not None:
            eff_ceiling = min(eff_ceiling, int(state.soft_ceiling))

        expected_ths = sample.expected_hashrate_ths
        if expected_ths is None:
            cores = None
            if sample.small_core_count and sample.asic_count:
                cores = int(sample.small_core_count) * int(sample.asic_count)
            expected_ths = (int(current_freq) * cores) / 1_000_000 if cores else None
        settled = (now - state.last_change_ts) >= max(0, int(gcfg.hashrate_settle_seconds))
        can_validate = (
            expected_ths is not None and hashrate_ths is not None and settled
        )
        valid_hr = bool(can_validate and hashrate_ths >= expected_ths * float(gcfg.valid_pct))
        error_high = (
            error_pct is not None
            and float(error_pct) > float(gcfg.error_pct_max)
        )
        hashrate_invalid = bool((can_validate and not valid_hr) or error_high)
        allow_up = bool(valid_hr and not error_high)
        instab_label = (
            "error % high" if (error_high and valid_hr) else "hashrate below theoretical"
        )
        tele["expected_ths"] = round(expected_ths, 2) if expected_ths is not None else None
        tele["valid"] = valid_hr if can_validate else None
        tele["error_pct"] = round(error_pct, 2) if error_pct is not None else None

        voltage_on = (
            bool(getattr(gcfg, "v2_voltage_enabled", False))
            and _coerce_bool(miner.get("guardian_voltage_enabled"))
            and (sample.voltage_set_mv is not None or sample.voltage_mv is not None)
        )
        if voltage_on:
            cur_v = int(
                sample.voltage_set_mv if sample.voltage_set_mv else sample.voltage_mv
            )
            drv = driver_for_record({**miner, "timeout": cfg.polling.request_timeout})
            if drv.can_set_voltage and drv.can_set_frequency:
                db_power_limit = miner.get("guardian_max_power_w")
                power_cut = float(db_power_limit) if db_power_limit is not None else (
                    float(sample.max_power_w) if sample.max_power_w else (
                        float(getattr(gcfg, "power_cutoff_w", 0) or 0) or None
                    )
                )
                vin_lo, vin_hi = vin_band(
                    sample.input_voltage_mv,
                    float(gcfg.vin_min_mv),
                    float(gcfg.vin_max_mv),
                )
                tf, tv, vreason = decide_point(
                    current_freq=int(current_freq),
                    current_volt=cur_v,
                    ceiling_mhz=eff_ceiling,
                    floor_mhz=floor,
                    volt_ceiling_mv=int(gcfg.v2_voltage_ceiling_mv),
                    volt_floor_mv=int(gcfg.v2_voltage_floor_mv),
                    vr_temp_high_c=vr_high,
                    vr_temp_low_c=vr_low,
                    chip_temp_high_c=chip_high,
                    chip_temp_low_c=chip_low,
                    hashrate_invalid=hashrate_invalid,
                    valid=allow_up,
                    instability_label=instab_label,
                    chip_c=temp_chip_c,
                    chip_cutoff_c=float(gcfg.chip_cutoff_c),
                    vr_c=temp_vr_c,
                    vr_cutoff_c=float(gcfg.vr_cutoff_c),
                    power_w=power_w,
                    power_cutoff_w=power_cut,
                    vin_mv=sample.input_voltage_mv,
                    vin_min_mv=vin_lo,
                    vin_max_mv=vin_hi,
                    step_down_mhz=gcfg.step_down_vr_mhz,
                    step_up_mhz=gcfg.step_up_mhz,
                    step_volt_mv=int(gcfg.v2_voltage_step_mv),
                    fan_pct=float(sample.fan_pct) if sample.fan_pct is not None else None,
                )
                tele["voltage_mv"] = cur_v
                tele["target_voltage_mv"] = tv
                if hashrate_invalid and tf < int(current_freq):
                    state.soft_ceiling = (
                        tf if state.soft_ceiling is None
                        else min(int(state.soft_ceiling), tf)
                    )
                changed = tf != int(current_freq) or tv != cur_v
                if not changed:
                    self._publish(miner_id, miner, current_freq, temp_c, reject_pct,
                                  vreason, changed=False, ceiling=eff_ceiling,
                                  floor=floor, source=source,
                                  vr_temp_c=temp_vr_c, chip_temp_c=temp_chip_c,
                                  soft_ceiling=state.soft_ceiling, **tele)
                    return
                cooldown = int(gcfg.cooldown_seconds or 0)
                if cooldown > 0 and (now - state.last_change_ts) < cooldown:
                    self._publish(miner_id, miner, current_freq, temp_c, reject_pct,
                                  f"cooldown ({vreason})", changed=False,
                                  ceiling=eff_ceiling, floor=floor, source=source,
                                  vr_temp_c=temp_vr_c, chip_temp_c=temp_chip_c,
                                  soft_ceiling=state.soft_ceiling, **tele)
                    return
                ok = True
                try:
                    if tv > cur_v:
                        ok = await drv.set_voltage(int(tv))
                    if ok and tf != int(current_freq):
                        ok = await drv.set_frequency(int(tf))
                    if ok and tv < cur_v:
                        ok = await drv.set_voltage(int(tv))
                except Exception as exc:  # noqa: BLE001
                    log.warning("guardian: miner=%s co-tune failed: %s",
                                miner.get("name"), exc)
                    self._publish(miner_id, miner, current_freq, temp_c, reject_pct,
                                  f"co-tune failed: {exc}", changed=False,
                                  ceiling=eff_ceiling, floor=floor, source=source,
                                  vr_temp_c=temp_vr_c, chip_temp_c=temp_chip_c,
                                  soft_ceiling=state.soft_ceiling, **tele)
                    return
                if ok:
                    state.last_commanded_freq = int(tf)
                    state.last_change_ts = now
                    state.last_reason = vreason
                    tele["voltage_mv"] = int(tv)
                    log.info(
                        "guardian: miner=%s V/F %d→%d MHz %d→%d mV (%s) "
                        "[VR=%s Chip=%s hr=%s exp=%s ceiling=%d]",
                        miner.get("name"), int(current_freq), int(tf), cur_v, int(tv),
                        vreason,
                        f"{temp_vr_c:.1f}" if temp_vr_c is not None else "n/a",
                        f"{temp_chip_c:.1f}" if temp_chip_c is not None else "n/a",
                        f"{hashrate_ths:.2f}" if hashrate_ths is not None else "n/a",
                        tele.get("expected_ths"), eff_ceiling,
                    )
                    self._publish(miner_id, miner, tf, temp_c, reject_pct, vreason,
                                  changed=True, ceiling=eff_ceiling, floor=floor,
                                  source=source, vr_temp_c=temp_vr_c, chip_temp_c=temp_chip_c,
                                  soft_ceiling=state.soft_ceiling, **tele)
                    try:
                        act = "STEP_DOWN" if tf < int(current_freq) else ("STEP_UP" if tf > int(current_freq) else "HOLD")
                        await db.insert_governor_decision(
                            miner_id=miner_id,
                            governor_type="guardian",
                            action_taken=act,
                            reason=vreason,
                            chip_temp=temp_chip_c,
                            vr_temp=temp_vr_c,
                            target_chip_temp=chip_high,
                            target_vr_temp=vr_high,
                            details={"freq_from": int(current_freq), "freq_to": int(tf), "voltage_from": cur_v, "voltage_to": int(tv)},
                        )
                    except Exception:  # noqa: BLE001
                        pass
                return

        target, reason = decide_frequency(
            current_freq=int(current_freq),
            ceiling_mhz=eff_ceiling,
            floor_mhz=floor,
            vr_temp_c=temp_vr_c,
            vr_high_c=vr_high,
            vr_low_c=vr_low,
            chip_temp_c=temp_chip_c,
            chip_high_c=chip_high,
            chip_low_c=chip_low,
            hw_error_pct=reject_pct,
            hw_error_pct_max=gcfg.reject_pct_max,
            step_down_temp_mhz=gcfg.step_down_vr_mhz,
            step_down_err_mhz=gcfg.step_down_err_mhz,
            step_up_mhz=gcfg.step_up_mhz,
            source_label=source_label,
            hashrate_invalid=hashrate_invalid,
            step_down_hr_mhz=gcfg.step_down_hashrate_mhz,
            allow_recovery=allow_up,
            instability_label=instab_label,
            fan_pct=float(sample.fan_pct) if sample.fan_pct is not None else None,
        )

        if hashrate_invalid and target < int(current_freq):
            state.soft_ceiling = (
                int(target) if state.soft_ceiling is None
                else min(int(state.soft_ceiling), int(target))
            )

        if target == int(current_freq):
            state.consecutive_holds += 1
            if state.consecutive_holds >= 2:
                state.is_tuning = False
            self._publish(miner_id, miner, current_freq, temp_c, reject_pct,
                          reason, changed=False, ceiling=eff_ceiling, floor=floor,
                          source=source, vr_temp_c=temp_vr_c, chip_temp_c=temp_chip_c,
                          soft_ceiling=state.soft_ceiling, **tele)
            return

        state.consecutive_holds = 0
        state.is_tuning = True

        cooldown = int(gcfg.cooldown_seconds or 0)
        if cooldown > 0 and (now - state.last_change_ts) < cooldown:
            self._publish(miner_id, miner, current_freq, temp_c, reject_pct,
                          f"cooldown ({reason})", changed=False,
                          ceiling=eff_ceiling, floor=floor, source=source,
                          vr_temp_c=temp_vr_c, chip_temp_c=temp_chip_c,
                          soft_ceiling=state.soft_ceiling, **tele)
            return

        drv = driver_for_record({**miner, "timeout": cfg.polling.request_timeout})
        if not drv.can_set_frequency:
            return
        try:
            ok = await drv.set_frequency(int(target))
        except Exception as exc:  # noqa: BLE001
            log.warning("guardian: miner=%s set_frequency failed: %s",
                        miner.get("name"), exc)
            self._publish(miner_id, miner, current_freq, temp_c, reject_pct,
                          f"set_frequency failed: {exc}", changed=False,
                          ceiling=eff_ceiling, floor=floor, source=source,
                          vr_temp_c=temp_vr_c, chip_temp_c=temp_chip_c,
                          soft_ceiling=state.soft_ceiling, **tele)
            return
        if ok:
            state.last_commanded_freq = int(target)
            state.last_change_ts = now
            state.last_reason = reason
            log.info(
                "guardian: miner=%s %d→%d MHz (%s) [VR=%s Chip=%s reject%%=%s hr=%s "
                "ceiling=%d floor=%d]",
                miner.get("name"), int(current_freq), int(target), reason,
                f"{temp_vr_c:.1f}" if temp_vr_c is not None else "n/a",
                f"{temp_chip_c:.1f}" if temp_chip_c is not None else "n/a",
                f"{reject_pct:.2f}" if reject_pct is not None else "n/a",
                f"{hashrate_ths:.2f}" if hashrate_ths is not None else "n/a",
                eff_ceiling, floor,
            )
            self._publish(miner_id, miner, target, temp_c, reject_pct, reason,
                          changed=True, ceiling=eff_ceiling, floor=floor,
                          source=source, vr_temp_c=temp_vr_c, chip_temp_c=temp_chip_c,
                          soft_ceiling=state.soft_ceiling, **tele)
        else:
            log.warning("guardian: miner=%s rejected set_frequency(%d)",
                        miner.get("name"), int(target))

    def _publish(
        self,
        miner_id: int,
        miner: dict,
        freq: int | None,
        temp_c: float | None,
        reject_pct: float | None,
        reason: str,
        *,
        changed: bool,
        ceiling: int | None = None,
        floor: int | None = None,
        source: str = "both",
        vr_temp_c: float | None = None,
        chip_temp_c: float | None = None,
        hashrate_ths: float | None = None,
        asic_errors: int | None = None,
        asic_error_delta: int | None = None,
        soft_ceiling: int | None = None,
        expected_ths: float | None = None,
        valid: bool | None = None,
        error_pct: float | None = None,
        voltage_mv: int | None = None,
        target_voltage_mv: int | None = None,
    ) -> None:
        """Update the live status surfaced by the API/UI."""
        vr_r = round(vr_temp_c, 1) if vr_temp_c is not None else (round(temp_c, 1) if temp_c is not None and source == "vr" else None)
        chip_r = round(chip_temp_c, 1) if chip_temp_c is not None else (round(temp_c, 1) if temp_c is not None and source == "chip" else None)
        temp_r = vr_r if vr_r is not None else chip_r

        self._status[miner_id] = {
            "miner_id": miner_id,
            "frequency_mhz": freq,
            "ceiling_mhz": ceiling,
            "floor_mhz": floor,
            "temp_c": temp_r,
            "temp_source": source,
            "vr_temp_c": vr_r,
            "chip_temp_c": chip_r,
            "reject_pct": round(reject_pct, 3) if reject_pct is not None else None,
            "hashrate_ths": round(hashrate_ths, 2) if hashrate_ths is not None else None,
            "expected_ths": expected_ths,
            "valid": valid,
            "error_pct": error_pct,
            "voltage_mv": voltage_mv,
            "target_voltage_mv": target_voltage_mv,
            "asic_errors": asic_errors,
            "asic_error_delta": asic_error_delta,
            "reason": reason,
            "changed": bool(changed),
            "ts": int(time.time()),
        }


def _coerce_bool(value: Any) -> bool:
    """SQLite stores the per-miner flag as 0/1; tolerate bool/str too."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False


# Global instance (used by main.py)
guardian = GuardianController()
