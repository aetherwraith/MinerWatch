"""Automated Guardian Sweet-Spot Efficiency Benchmarker & Profiler.

Performs a grid sweep over frequency (MHz) and voltage (mV) operating
combinations, measuring stable hashrate, power, efficiency (J/TH), and error rates.
Enforces Guardian thermal safety nets at all times during the sweep.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend import db, guardian
from backend.miners import driver_for_record
from backend.poller import poller

logger = logging.getLogger("minerwatch.benchmark")

# In-memory registry of running benchmark tasks and abort flags by miner_id
_running_benchmarks: dict[int, asyncio.Task] = {}
_abort_flags: dict[int, bool] = {}


def is_benchmark_running(miner_id: int) -> bool:
    """Return True if a benchmark is currently executing for the miner."""
    task = _running_benchmarks.get(miner_id)
    return task is not None and not task.done()


def cancel_benchmark(miner_id: int) -> bool:
    """Signal an active benchmark to abort and cancel its background task."""
    if is_benchmark_running(miner_id):
        _abort_flags[miner_id] = True
        task = _running_benchmarks.get(miner_id)
        if task and not task.done():
            task.cancel()
        return True
    return False


async def start_benchmark_task(miner_id: int, config: dict[str, Any]) -> int:
    """Initialize and launch an async benchmark sweep task for the miner."""
    if is_benchmark_running(miner_id):
        msg = f"Benchmark already running for miner #{miner_id}"
        raise RuntimeError(msg)

    # Compute candidate matrix grid
    frequencies = list(
        range(
            config["min_freq_mhz"],
            config["max_freq_mhz"] + 1,
            max(1, config["freq_step_mhz"]),
        )
    )
    voltages = list(
        range(
            config["min_voltage_mv"],
            config["max_voltage_mv"] + 1,
            max(1, config["voltage_step_mv"]),
        )
    )

    combinations = [(f, v) for f in frequencies for v in voltages]
    config["total_steps"] = len(combinations)

    # Create DB record
    benchmark_id = await db.create_miner_benchmark(miner_id, config)

    # Clear abort flag
    _abort_flags[miner_id] = False

    # Launch async task
    task = asyncio.create_task(
        _run_benchmark_sweep(benchmark_id, miner_id, config, combinations)
    )
    _running_benchmarks[miner_id] = task
    return benchmark_id

async def _apply_freq_and_volt(miner_id: int, freq: int, volt: int) -> bool:
    """Apply frequency and voltage to the miner hardware driver."""
    miner = await db.get_miner(miner_id)
    if not miner:
        return False
    drv = driver_for_record(miner)
    ok_f = True
    ok_v = True
    if drv.can_set_frequency:
        ok_f = await drv.set_frequency(freq)
    if drv.can_set_voltage:
        ok_v = await drv.set_voltage(volt)
    return ok_f and ok_v


async def _set_fan_speed(miner_id: int, pct: int) -> bool:
    """Set custom fan speed percentage on miner driver."""
    miner = await db.get_miner(miner_id)
    if not miner:
        return False
    drv = driver_for_record(miner)
    if drv and drv.can_set_fan:
        return await drv.set_fan_speed(pct)
    return False


async def _get_latest_metrics(miner_id: int) -> dict[str, Any]:
    """Get latest polled metrics dictionary for a miner."""
    sample = poller.last_results.get(miner_id)
    if not sample:
        return {}
    rej = float(getattr(sample, "rejected", 0) or 0)
    acc = float(getattr(sample, "accepted", 0) or 0)
    tot = rej + acc
    reject_pct = (rej / tot * 100.0) if tot > 0 else 0.0
    hw_err_pct = float(getattr(sample, "error_pct", 0) or 0.0)

    return {
        "hashrate_ths": getattr(sample, "hashrate_ths", None),
        "power_w": getattr(sample, "power_w", None),
        "temp_chip_c": getattr(sample, "temp_chip_c", None),
        "temp_vr_c": getattr(sample, "temp_vr_c", None),
        "fan_pct": getattr(sample, "fan_pct", None),
        "rejected": rej,
        "accepted": acc,
        "reject_pct": reject_pct,
        "error_pct": hw_err_pct,
    }


async def _thermal_cooling_pause(
    miner_id: int,
    benchmark_id: int,
    max_chip_temp: float,
    max_vr_temp: float,
) -> None:
    """Pause miner on thermal safety trigger, force fans 100%, cool below target caps, then resume & ramp up (10s)."""
    miner = await db.get_miner(miner_id)
    if not miner:
        return

    drv = driver_for_record(miner)
    try:
        await _set_fan_speed(miner_id, 100)
    except Exception as e:
        logger.warning("Failed forcing fans 100%% for thermal pause on miner #%d: %s", miner_id, e)

    if drv.can_pause:
        try:
            await drv.pause()
            logger.info("Soft-paused ASIC hashing for thermal cooling on miner #%d", miner_id)
        except Exception as e:
            logger.warning("Failed soft-pausing ASIC on miner #%d: %s", miner_id, e)

    target_chip = max(50.0, max_chip_temp - 3.0)
    target_vr = max(60.0, max_vr_temp - 3.0)

    logger.warning(
        "Thermal cooling pause active on benchmark #%d miner #%d (waiting for Chip ≤ %.1f°C / VR ≤ %.1f°C)...",
        benchmark_id, miner_id, target_chip, target_vr,
    )

    for cool_sec in range(180):
        if _abort_flags.get(miner_id):
            break
        await asyncio.sleep(1)
        latest = await _get_latest_metrics(miner_id)
        if latest:
            c_temp = latest.get("temp_chip_c")
            v_temp = latest.get("temp_vr_c")

            chip_ok = (c_temp is None) or (c_temp <= target_chip)
            vr_ok = (v_temp is None) or (v_temp <= target_vr)

            if chip_ok and vr_ok:
                logger.info(
                    "Miner #%d cooled down successfully (Chip: %s°C, VR: %s°C) after %ds",
                    miner_id, f"{c_temp:.1f}" if c_temp else "—", f"{v_temp:.1f}" if v_temp else "—", cool_sec + 1,
                )
                break

    if drv.can_pause and not _abort_flags.get(miner_id):
        try:
            await drv.resume()
            logger.info("Resumed ASIC hashing after thermal cooling on miner #%d", miner_id)
        except Exception as e:
            logger.warning("Failed resuming ASIC hashing on miner #%d: %s", miner_id, e)

    if not _abort_flags.get(miner_id):
        logger.info("Ramping up miner #%d for 10s prior to next step...", miner_id)
        await asyncio.sleep(10)


async def _run_benchmark_sweep(
    benchmark_id: int,
    miner_id: int,
    config: dict[str, Any],
    combinations: list[tuple[int, int]],
) -> None:
    """Background task performing the frequency/voltage sweep with safety checks."""
    logger.info("Starting benchmark sweep #%d for miner #%d (%d combinations)", benchmark_id, miner_id, len(combinations))

    miner = await db.get_miner(miner_id)
    if not miner:
        await db.update_miner_benchmark(benchmark_id, status="failed")
        return

    # Record baseline settled settings
    orig_freq = miner.get("guardian_max_freq_mhz") or 500
    orig_guardian_enabled = bool(miner.get("guardian_enabled"))
    orig_fan_mode = miner.get("fan_mode")

    best_eff: dict[str, Any] | None = None
    best_hash: dict[str, Any] | None = None
    best_quiet: dict[str, Any] | None = None

    pin_fan_pct = config.get("pin_fan_pct")
    dwell_time_s = max(5, config.get("dwell_time_s", 30))
    early_skip_sec = max(5, int(config.get("early_skip_sec", 60)))
    # Default error rate threshold set to Guardian's 1.1% threshold
    max_error_rate_pct = float(config.get("max_error_rate_pct", 1.1))

    # Thermal safety cutoffs (from explicit parameter override or Guardian caps)
    guardian_chip_max, guardian_vr_max = guardian.get_target_max_temps(miner)
    max_chip_temp = float(config.get("target_max_chip_temp_c") or guardian_chip_max)
    max_vr_temp = float(config.get("target_max_vr_temp_c") or guardian_vr_max)

    # Disable Guardian governor while benchmarking to prevent interference,
    # and reset any active tuning state/fan pin
    guardian.guardian.reset_miner(miner_id)
    if orig_guardian_enabled:
        try:
            await db.update_miner_guardian_config(miner_id, enabled=False)
            logger.info("Disabled Guardian governor on miner #%d for duration of benchmark", miner_id)
        except Exception as e:
            logger.warning("Failed to temporarily disable Guardian on miner #%d: %s", miner_id, e)

    # Configure fan mode for benchmark run (fixed pin, firmware auto, or minerwatch auto)
    bench_fan_mode = (config.get("fan_mode") or "pin").lower()
    if bench_fan_mode == "firmware":
        try:
            cfg = get_config()
            drv = driver_for_record({**miner, "timeout": cfg.polling.request_timeout})
            await drv.set_auto_fan(True)
            logger.info("Configured miner #%d fan control to firmware auto for benchmark", miner_id)
        except Exception as e:
            logger.warning("Failed setting firmware auto fan for benchmark on miner #%d: %s", miner_id, e)
    elif bench_fan_mode == "pin" and pin_fan_pct is not None:
        try:
            await _set_fan_speed(miner_id, pin_fan_pct)
        except Exception as e:
            logger.warning("Failed to pin fan speed to %d%% for miner #%d: %s", pin_fan_pct, miner_id, e)
    else:
        from backend.auto_control import auto_fan
        auto_fan.reset_miner_state(miner_id)

    stable_samples: list[dict[str, Any]] = []

    try:
        for idx, (freq, volt) in enumerate(combinations):
            if _abort_flags.get(miner_id):
                logger.info("Benchmark #%d requested abort by user", benchmark_id)
                await db.update_miner_benchmark(benchmark_id, status="aborted", current_step=idx)
                break

            await db.update_miner_benchmark(benchmark_id, current_step=idx + 1)

            # Apply candidate operating point to hardware driver
            try:
                await _apply_freq_and_volt(miner_id, freq, volt)
            except Exception as e:
                logger.warning("Error applying freq=%d MHz volt=%d mV on miner #%d: %s", freq, volt, miner_id, e)

            # Dwell time loop with safety net checking every second
            dwell_aborted = False
            thermal_safety_trigger = False
            abort_reason = None
            dwell_samples: list[dict[str, Any]] = []

            for second in range(1, dwell_time_s + 1):
                if _abort_flags.get(miner_id):
                    dwell_aborted = True
                    break

                await asyncio.sleep(1)

                # Fetch live metric sample
                latest = await _get_latest_metrics(miner_id)
                if latest:
                    dwell_samples.append(latest)
                    chip_temp = latest.get("temp_chip_c")
                    vr_temp = latest.get("temp_vr_c")

                    # 1. Guardian Thermal Safety Net Check (Emergency Halt)
                    if (chip_temp and chip_temp >= max_chip_temp + 2.0) or (vr_temp and vr_temp >= max_vr_temp + 2.0):
                        dwell_aborted = True
                        thermal_safety_trigger = True
                        abort_reason = f"Thermal safety trigger (Chip: {chip_temp}°C, VR: {vr_temp}°C)"
                        logger.warning("Safety net triggered on benchmark #%d miner #%d: %s", benchmark_id, miner_id, abort_reason)
                        break

                    # 2. Early Dwell Skip for Long Dwell Periods (dwell_time_s > early_skip_sec)
                    # If we've observed telemetry past early_skip_sec and metrics indicate instability or out-of-bounds temps:
                    if dwell_time_s > early_skip_sec and second >= early_skip_sec and len(dwell_samples) >= 3:
                        recent_window = dwell_samples[-5:]
                        def _r_avg(k: str) -> float | None:
                            v_list = [s[k] for s in recent_window if s.get(k) is not None]
                            return (sum(v_list) / len(v_list)) if v_list else None

                        cur_hr = _r_avg("hashrate_ths") or 0.0
                        cur_hw_err = _r_avg("error_pct") or 0.0
                        cur_rej_pct = _r_avg("reject_pct") or 0.0
                        cur_eff_err = max(cur_hw_err, cur_rej_pct)
                        cur_chip_t = _r_avg("temp_chip_c")
                        cur_vr_t = _r_avg("temp_vr_c")

                        exp_hr = None
                        if miner:
                            sc = miner.get("small_core_count")
                            ac = miner.get("asic_count")
                            if sc and ac:
                                exp_hr = (freq * sc * ac) / 1_000_000.0

                        severe_errors = cur_eff_err >= max(5.0, max_error_rate_pct * 3.5)
                        severe_hr_deficit = exp_hr is not None and exp_hr > 0 and cur_hr < (exp_hr * 0.5)
                        zero_hashrate = cur_hr == 0.0
                        temp_out_of_bounds = (
                            (cur_chip_t is not None and cur_chip_t > max_chip_temp) or
                            (cur_vr_t is not None and cur_vr_t > max_vr_temp)
                        )

                        if severe_errors or severe_hr_deficit or zero_hashrate or temp_out_of_bounds:
                            dwell_aborted = True
                            if temp_out_of_bounds:
                                abort_reason = f"Early dwell skip ({second}s): Temperature out of bounds (Chip: {cur_chip_t:.1f}°C > {max_chip_temp:.1f}°C, VR: {cur_vr_t:.1f}°C > {max_vr_temp:.1f}°C)"
                            elif severe_errors:
                                abort_reason = f"Early dwell skip ({second}s): Severe error rate ({cur_eff_err:.1f}%)"
                            elif severe_hr_deficit:
                                abort_reason = f"Early dwell skip ({second}s): Hashrate {cur_hr:.2f} TH/s < 50% theoretical ({exp_hr:.2f} TH/s)"
                            else:
                                abort_reason = f"Early dwell skip ({second}s): Zero hashrate output"

                            logger.info("Early dwell skip on benchmark #%d miner #%d step (%d MHz @ %d mV): %s", benchmark_id, miner_id, freq, volt, abort_reason)
                            break

            if _abort_flags.get(miner_id):
                await db.update_miner_benchmark(benchmark_id, status="aborted", current_step=idx + 1)
                break

            # Calculate settled averages over the last third of the dwell period (min 5 seconds)
            window_size = max(5, dwell_time_s // 3)
            window_samples = dwell_samples[-window_size:] if dwell_samples else []

            def _avg(key: str) -> float | None:
                vals = [s[key] for s in window_samples if s.get(key) is not None]
                return (sum(vals) / len(vals)) if vals else None

            hr = _avg("hashrate_ths") or 0.0
            power = _avg("power_w") or 0.0
            chip_t = _avg("temp_chip_c")
            vr_t = _avg("temp_vr_c")
            hw_err = _avg("error_pct") or 0.0
            rej_pct = _avg("reject_pct") or 0.0

            fan_t = _avg("fan_pct")

            # Combine chip hardware error rate and pool share rejection rate
            effective_err_rate = max(hw_err, rej_pct)

            # Calculate expected theoretical hashrate matching Guardian rules (85% threshold)
            expected_ths = None
            if miner:
                small_cores = miner.get("small_core_count")
                asic_count = miner.get("asic_count")
                if small_cores and asic_count:
                    total_cores = int(small_cores) * int(asic_count)
                    expected_ths = (freq * total_cores) / 1_000_000.0

            valid_hashrate = True
            if expected_ths and expected_ths > 0:
                valid_hashrate = (hr >= expected_ths * 0.85)

            if not valid_hashrate and not abort_reason:
                abort_reason = f"Hashrate {hr:.2f} TH/s below 85% theoretical ({expected_ths * 0.85:.2f} TH/s)"

            j_th = (power / hr) if (hr > 0 and power > 0) else None
            is_stable = not dwell_aborted and effective_err_rate <= max_error_rate_pct and hr > 0 and valid_hashrate

            sample_record = {
                "freq_mhz": freq,
                "voltage_mv": volt,
                "hashrate_ths": round(hr, 3) if hr > 0 else None,
                "power_w": round(power, 1) if power > 0 else None,
                "efficiency_j_th": round(j_th, 2) if j_th is not None else None,
                "chip_temp_c": round(chip_t, 1) if chip_t is not None else None,
                "vr_temp_c": round(vr_t, 1) if vr_t is not None else None,
                "fan_pct": round(fan_t, 1) if fan_t is not None else None,
                "error_rate_pct": round(effective_err_rate, 2),
                "stable": is_stable,
                "abort_reason": abort_reason if not is_stable else None,
            }

            await db.add_benchmark_sample(benchmark_id, miner_id, sample_record)

            if is_stable and j_th is not None:
                stable_samples.append(sample_record)

            # If thermal safety trigger occurred, pause to cool down, unpause & ramp up 10s, then continue!
            if thermal_safety_trigger or (dwell_aborted and abort_reason and "Thermal" in abort_reason):
                await _thermal_cooling_pause(miner_id, benchmark_id, max_chip_temp, max_vr_temp)

        # Optional Microtuning Sweep Phase
        enable_micro = bool(config.get("enable_microtuning"))
        micro_f_step = int(config.get("micro_freq_step_mhz", 5))
        micro_v_step = int(config.get("micro_volt_step_mv", 10))

        if enable_micro and stable_samples and not _abort_flags.get(miner_id):
            best_eff_cand = min(stable_samples, key=lambda s: s["efficiency_j_th"] or 9999.0)
            best_hash_cand = max(stable_samples, key=lambda s: s["hashrate_ths"] or 0.0)

            sampled_pairs = {(s["freq_mhz"], s["voltage_mv"]) for s in stable_samples}
            micro_candidates: set[tuple[int, int]] = set()

            for cand in (best_eff_cand, best_hash_cand):
                cfreq = cand["freq_mhz"]
                cvolt = cand["voltage_mv"]
                f_start = max(min_freq_mhz, cfreq - freq_step_mhz)
                f_end = min(max_freq_mhz, cfreq + freq_step_mhz)
                v_start = max(min_voltage_mv, cvolt - voltage_step_mv)
                v_end = min(max_voltage_mv, cvolt + voltage_step_mv)

                for f in range(f_start, f_end + 1, micro_f_step):
                    for v in range(v_start, v_end + 1, micro_v_step):
                        if (f, v) not in sampled_pairs:
                            micro_candidates.add((f, v))

            if micro_candidates:
                total_micro = len(micro_candidates)
                await db.update_miner_benchmark(
                    benchmark_id,
                    sweep_phase="microtuning",
                    micro_current_step=0,
                    micro_total_steps=total_micro,
                )
                logger.info("Starting Phase 2 microtuning sweep with %d fine candidate points on miner #%d", total_micro, miner_id)

                for m_idx, (f, v) in enumerate(sorted(list(micro_candidates))):
                    if _abort_flags.get(miner_id):
                        break

                    await db.update_miner_benchmark(
                        benchmark_id,
                        sweep_phase="microtuning",
                        micro_current_step=m_idx + 1,
                        micro_total_steps=total_micro,
                    )

                    try:
                        await _apply_freq_and_volt(miner_id, f, v)
                    except Exception as e:
                        logger.warning("Error microtuning freq=%d volt=%d: %s", f, v, e)

                    m_dwell_samples: list[dict[str, Any]] = []
                    m_aborted = False
                    m_thermal_trigger = False
                    m_abort_reason = None

                    for m_sec in range(1, dwell_time_s + 1):
                        if _abort_flags.get(miner_id):
                            m_aborted = True
                            break
                        await asyncio.sleep(1)
                        latest = await _get_latest_metrics(miner_id)
                        if latest:
                            m_dwell_samples.append(latest)
                            chip_t = latest.get("temp_chip_c")
                            vr_t = latest.get("temp_vr_c")
                            if (chip_t and chip_t >= max_chip_temp + 2.0) or (vr_t and vr_t >= max_vr_temp + 2.0):
                                m_aborted = True
                                m_thermal_trigger = True
                                m_abort_reason = f"Thermal safety trigger (Chip: {chip_t}°C, VR: {vr_t}°C)"
                                break

                            # Early Dwell Skip for Long Dwell Periods (dwell_time_s > early_skip_sec)
                            if dwell_time_s > early_skip_sec and m_sec >= early_skip_sec and len(m_dwell_samples) >= 3:
                                m_recent = m_dwell_samples[-5:]
                                def _mr_avg(k: str) -> float | None:
                                    v_list = [s[k] for s in m_recent if s.get(k) is not None]
                                    return (sum(v_list) / len(v_list)) if v_list else None

                                cur_hr = _mr_avg("hashrate_ths") or 0.0
                                cur_hw_err = _mr_avg("error_pct") or 0.0
                                cur_rej_pct = _mr_avg("reject_pct") or 0.0
                                cur_eff_err = max(cur_hw_err, cur_rej_pct)
                                cur_chip_t = _mr_avg("temp_chip_c")
                                cur_vr_t = _mr_avg("temp_vr_c")

                                exp_hr = None
                                if miner:
                                    sc = miner.get("small_core_count")
                                    ac = miner.get("asic_count")
                                    if sc and ac:
                                        exp_hr = (f * sc * ac) / 1_000_000.0

                                severe_errors = cur_eff_err >= max(5.0, max_error_rate_pct * 3.5)
                                severe_hr_deficit = exp_hr is not None and exp_hr > 0 and cur_hr < (exp_hr * 0.5)
                                zero_hashrate = cur_hr == 0.0
                                temp_out_of_bounds = (
                                    (cur_chip_t is not None and cur_chip_t > max_chip_temp) or
                                    (cur_vr_t is not None and cur_vr_t > max_vr_temp)
                                )

                                if severe_errors or severe_hr_deficit or zero_hashrate or temp_out_of_bounds:
                                    m_aborted = True
                                    if temp_out_of_bounds:
                                        m_abort_reason = f"Early dwell skip ({m_sec}s): Temperature out of bounds (Chip: {cur_chip_t:.1f}°C > {max_chip_temp:.1f}°C, VR: {cur_vr_t:.1f}°C > {max_vr_temp:.1f}°C)"
                                    elif severe_errors:
                                        m_abort_reason = f"Early dwell skip ({m_sec}s): Severe error rate ({cur_eff_err:.1f}%)"
                                    elif severe_hr_deficit:
                                        m_abort_reason = f"Early dwell skip ({m_sec}s): Hashrate {cur_hr:.2f} TH/s < 50% theoretical ({exp_hr:.2f} TH/s)"
                                    else:
                                        m_abort_reason = f"Early dwell skip ({m_sec}s): Zero hashrate output"

                                    logger.info("Microtuning early dwell skip on miner #%d step (%d MHz @ %d mV): %s", miner_id, f, v, m_abort_reason)
                                    break

                    if m_aborted and _abort_flags.get(miner_id):
                        break

                    window_size = max(5, dwell_time_s // 3)
                    m_window = m_dwell_samples[-window_size:] if m_dwell_samples else []
                    def _m_avg(key: str) -> float | None:
                        vals = [s[key] for s in m_window if s.get(key) is not None]
                        return (sum(vals) / len(vals)) if vals else None

                    hr = _m_avg("hashrate_ths") or 0.0
                    power = _m_avg("power_w") or 0.0
                    chip_t = _m_avg("temp_chip_c")
                    vr_t = _m_avg("temp_vr_c")
                    m_fan_t = _m_avg("fan_pct")
                    hw_err = _m_avg("error_pct") or 0.0
                    rej_pct = _m_avg("reject_pct") or 0.0
                    eff_err = max(hw_err, rej_pct)
                    j_th = (power / hr) if (hr > 0 and power > 0) else None

                    # Guardian expected theoretical hashrate check for microtuning
                    m_expected_ths = None
                    if miner:
                        small_cores = miner.get("small_core_count")
                        asic_count = miner.get("asic_count")
                        if small_cores and asic_count:
                            total_cores = int(small_cores) * int(asic_count)
                            m_expected_ths = (f * total_cores) / 1_000_000.0

                    m_valid_hashrate = True
                    if m_expected_ths and m_expected_ths > 0:
                        m_valid_hashrate = (hr >= m_expected_ths * 0.85)

                    if not m_valid_hashrate and not m_abort_reason:
                        m_abort_reason = f"Hashrate {hr:.2f} TH/s below 85% theoretical ({m_expected_ths * 0.85:.2f} TH/s)"

                    is_stable = not m_aborted and eff_err <= max_error_rate_pct and hr > 0 and m_valid_hashrate

                    m_sample = {
                        "freq_mhz": f,
                        "voltage_mv": v,
                        "hashrate_ths": round(hr, 3) if hr > 0 else None,
                        "power_w": round(power, 1) if power > 0 else None,
                        "efficiency_j_th": round(j_th, 2) if j_th is not None else None,
                        "chip_temp_c": round(chip_t, 1) if chip_t is not None else None,
                        "vr_temp_c": round(vr_t, 1) if vr_t is not None else None,
                        "fan_pct": round(m_fan_t, 1) if m_fan_t is not None else None,
                        "error_rate_pct": round(eff_err, 2),
                        "stable": is_stable,
                        "abort_reason": m_abort_reason if not is_stable else None,
                    }
                    await db.add_benchmark_sample(benchmark_id, miner_id, m_sample)
                    if is_stable and j_th is not None:
                        stable_samples.append(m_sample)

                    if m_thermal_trigger or (m_aborted and m_abort_reason and "Thermal" in m_abort_reason):
                        await _thermal_cooling_pause(miner_id, benchmark_id, max_chip_temp, max_vr_temp)

        # Sweep finished — calculate best candidate profiles across all stable samples (coarse + microtuning)
        best_eff = None
        best_hash = None
        best_quiet = None

        if stable_samples:
            # Max Efficiency = lowest J/TH
            valid_eff_samples = [s for s in stable_samples if s.get("efficiency_j_th") is not None and s["efficiency_j_th"] > 0]
            if valid_eff_samples:
                best_eff = min(valid_eff_samples, key=lambda s: s["efficiency_j_th"])

            # Max Hashrate = highest TH/s
            valid_hash_samples = [s for s in stable_samples if s.get("hashrate_ths") is not None and s["hashrate_ths"] > 0]
            if valid_hash_samples:
                best_hash = max(valid_hash_samples, key=lambda s: s["hashrate_ths"])

            # Best Quiet = max performance candidate where settled fan speed <= quiet_fan_max_pct
            quiet_max_fan = config.get("quiet_fan_max_pct")
            if quiet_max_fan is not None and valid_hash_samples:
                quiet_cands = [
                    s for s in valid_hash_samples
                    if s.get("fan_pct") is not None and s["fan_pct"] <= float(quiet_max_fan)
                ]
                if quiet_cands:
                    best_quiet = max(quiet_cands, key=lambda s: s["hashrate_ths"])

        status_str = "completed" if not _abort_flags.get(miner_id) else "aborted"
        await db.update_miner_benchmark(
            benchmark_id,
            status=status_str,
            current_step=len(combinations),
            best_eff=best_eff,
            best_hash=best_hash,
            best_quiet=best_quiet,
        )

    except asyncio.CancelledError:
        logger.info("Benchmark sweep task cancelled for miner #%d", miner_id)
        await db.update_miner_benchmark(benchmark_id, status="aborted")
    except Exception as e:
        logger.error("Benchmark sweep failed for miner #%d: %s", miner_id, e, exc_info=True)
        await db.update_miner_benchmark(benchmark_id, status="failed")
    finally:
        # Cleanup & restore baseline state
        _running_benchmarks.pop(miner_id, None)
        _abort_flags.pop(miner_id, None)

        # Restore Guardian governor state if it was enabled prior to benchmark
        if orig_guardian_enabled:
            try:
                await db.update_miner_guardian_config(miner_id, enabled=True)
                logger.info("Restored Guardian governor state on miner #%d", miner_id)
            except Exception as e:
                logger.warning("Failed restoring Guardian state for miner #%d: %s", miner_id, e)

        # Restore original frequency / settings
        try:
            if best_eff and best_eff.get("freq_mhz"):
                await _apply_freq_and_volt(
                    miner_id,
                    best_eff["freq_mhz"],
                    best_eff["voltage_mv"],
                )
            else:
                await _apply_freq_and_volt(miner_id, orig_freq, 1200)
        except Exception as e:
            logger.warning("Failed restoring baseline for miner #%d: %s", miner_id, e)
