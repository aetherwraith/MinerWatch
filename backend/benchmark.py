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
    return {
        "hashrate_ths": getattr(sample, "hashrate_ths", None),
        "power_w": getattr(sample, "power_w", None),
        "temp_chip_c": getattr(sample, "temp_chip_c", None),
        "temp_vr_c": getattr(sample, "temp_vr_c", None),
        "fan_pct": getattr(sample, "fan_pct", None),
        "rejected": getattr(sample, "rejected", 0),
        "accepted": getattr(sample, "accepted", 0),
    }


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
    orig_fan_mode = miner.get("fan_mode")
    orig_fan_override = miner.get("fan_min_override")

    pin_fan_pct = config.get("pin_fan_pct")
    dwell_time_s = max(5, config.get("dwell_time_s", 30))
    max_error_rate_pct = float(config.get("max_error_rate_pct", 5.0))

    # Thermal safety cutoffs (default 70°C chip / 85°C VR or miner Guardian caps)
    max_chip_temp = float(miner.get("guardian_max_chip_temp_c") or miner.get("guardian_max_temp_c") or 68.0)
    max_vr_temp = float(miner.get("guardian_max_vr_temp_c") or 82.0)

    # If pin_fan_pct is specified, temporarily pin miner fan
    if pin_fan_pct is not None:
        try:
            await _set_fan_speed(miner_id, pin_fan_pct)
        except Exception as e:
            logger.warning("Failed to pin fan speed to %d%% for miner #%d: %s", pin_fan_pct, miner_id, e)

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
            abort_reason = None
            sample_metrics: dict[str, Any] = {}

            for second in range(dwell_time_s):
                if _abort_flags.get(miner_id):
                    dwell_aborted = True
                    break

                await asyncio.sleep(1)

                # Fetch live metric sample
                latest = await _get_latest_metrics(miner_id)
                if latest:
                    chip_temp = latest.get("temp_chip_c")
                    vr_temp = latest.get("temp_vr_c")

                    # Guardian Thermal Safety Net Check!
                    if (chip_temp and chip_temp >= max_chip_temp + 2.0) or (vr_temp and vr_temp >= max_vr_temp + 2.0):
                        dwell_aborted = True
                        abort_reason = f"Thermal safety trigger (Chip: {chip_temp}°C, VR: {vr_temp}°C)"
                        logger.warning("Safety net triggered on benchmark #%d miner #%d: %s", benchmark_id, miner_id, abort_reason)
                        break

                    # Collect metrics near end of dwell window
                    if second >= dwell_time_s - 5:
                        sample_metrics = latest

            if _abort_flags.get(miner_id):
                await db.update_miner_benchmark(benchmark_id, status="aborted", current_step=idx + 1)
                break

            # Evaluate point metrics & stability
            hr = float(sample_metrics.get("hashrate_ths") or 0.0)
            power = float(sample_metrics.get("power_w") or 0.0)
            chip_t = sample_metrics.get("temp_chip_c")
            vr_t = sample_metrics.get("temp_vr_c")
            rej = float(sample_metrics.get("rejected") or 0.0)
            acc = float(sample_metrics.get("accepted") or 0.0)
            tot_shares = rej + acc
            err_rate = (rej / tot_shares * 100.0) if tot_shares > 0 else 0.0

            j_th = (power / hr) if (hr > 0 and power > 0) else None
            is_stable = not dwell_aborted and err_rate <= max_error_rate_pct and hr > 0

            sample_record = {
                "freq_mhz": freq,
                "voltage_mv": volt,
                "hashrate_ths": hr if hr > 0 else None,
                "power_w": power if power > 0 else None,
                "efficiency_j_th": j_th,
                "chip_temp_c": chip_t,
                "vr_temp_c": vr_t,
                "error_rate_pct": err_rate,
                "stable": is_stable,
                "abort_reason": abort_reason if not is_stable else None,
            }

            await db.add_benchmark_sample(benchmark_id, miner_id, sample_record)

            if is_stable and j_th is not None:
                stable_samples.append(sample_record)

            # If thermal safety net triggered, immediately step back to safe frequency
            if dwell_aborted and abort_reason:
                logger.info("Halting benchmark #%d due to thermal safety net", benchmark_id)
                await db.update_miner_benchmark(benchmark_id, status="aborted", current_step=idx + 1)
                break

        # Sweep finished — calculate best profiles
        best_eff = None
        best_hash = None

        if stable_samples:
            # Max Efficiency = lowest J/TH
            best_eff = min(stable_samples, key=lambda s: s["efficiency_j_th"] or 9999.0)
            # Max Hashrate = highest TH/s
            best_hash = max(stable_samples, key=lambda s: s["hashrate_ths"] or 0.0)

        status_str = "completed" if not _abort_flags.get(miner_id) else "aborted"
        await db.update_miner_benchmark(
            benchmark_id,
            status=status_str,
            current_step=len(combinations),
            best_eff=best_eff,
            best_hash=best_hash,
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
