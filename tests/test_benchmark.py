"""Tests for Guardian Automated Benchmarker & Profiler."""

import pytest
from backend import benchmark, db


@pytest.mark.anyio
async def test_benchmark_db_lifecycle():
    await db.init_db()
    # Insert dummy miner
    miner_id = await db.upsert_miner({
        "family": "bitaxe",
        "host": "192.168.1.99",
        "port": 80,
        "name": "Test Benchaxe",
        "enabled": 1,
    })

    try:
        # Create benchmark run
        cfg = {
            "min_freq_mhz": 400,
            "max_freq_mhz": 500,
            "freq_step_mhz": 50,
            "min_voltage_mv": 1150,
            "max_voltage_mv": 1250,
            "voltage_step_mv": 50,
            "dwell_time_s": 10,
            "max_error_rate_pct": 2.0,
            "pin_fan_pct": 80,
            "total_steps": 6,
        }

        bench_id = await db.create_miner_benchmark(miner_id, cfg)
        assert bench_id > 0

        # Fetch status
        latest = await db.get_latest_miner_benchmark(miner_id)
        assert latest is not None
        assert latest["status"] == "running"
        assert latest["min_freq_mhz"] == 400
        assert latest["total_steps"] == 6

        # Add samples
        sample1 = {
            "freq_mhz": 400,
            "voltage_mv": 1150,
            "hashrate_ths": 2.5,
            "power_w": 40.0,
            "efficiency_j_th": 16.0,
            "chip_temp_c": 55.0,
            "vr_temp_c": 60.0,
            "error_rate_pct": 0.0,
            "stable": True,
        }
        await db.add_benchmark_sample(bench_id, miner_id, sample1)

        sample2 = {
            "freq_mhz": 450,
            "voltage_mv": 1200,
            "hashrate_ths": 3.0,
            "power_w": 45.0,
            "efficiency_j_th": 15.0,  # Best efficiency
            "chip_temp_c": 58.0,
            "vr_temp_c": 63.0,
            "error_rate_pct": 0.5,
            "stable": True,
        }
        await db.add_benchmark_sample(bench_id, miner_id, sample2)

        # Update status & best profiles
        await db.update_miner_benchmark(
            bench_id,
            status="completed",
            current_step=6,
            best_eff={"freq_mhz": 450, "voltage_mv": 1200, "efficiency_j_th": 15.0},
            best_hash={"freq_mhz": 450, "voltage_mv": 1200, "hashrate_ths": 3.0},
        )

        res = await db.get_latest_miner_benchmark(miner_id)
        assert res["status"] == "completed"
        assert res["best_eff_j_th"] == 15.0
        assert res["best_hash_freq"] == 450
        assert len(res["samples"]) == 2

        # Test clear
        await db.clear_miner_benchmarks(miner_id)
        cleared = await db.get_latest_miner_benchmark(miner_id)
        assert cleared is None

    finally:
        async with db.connect() as conn:
            await conn.execute("DELETE FROM miners WHERE id = ?", (miner_id,))


@pytest.mark.anyio
async def test_microtuning_execution_flow():
    await db.init_db()
    miner_id = await db.upsert_miner({
        "family": "bitaxe",
        "host": "192.168.1.98",
        "port": 80,
        "name": "Test MicroBench",
        "enabled": 1,
    })

    try:
        cfg = {
            "min_freq_mhz": 500,
            "max_freq_mhz": 550,
            "freq_step_mhz": 25,
            "min_voltage_mv": 1200,
            "max_voltage_mv": 1250,
            "voltage_step_mv": 25,
            "dwell_time_s": 1,
            "max_error_rate_pct": 2.0,
            "enable_microtuning": True,
            "micro_freq_step_mhz": 5,
            "micro_volt_step_mv": 10,
        }

        bench_id = await db.create_miner_benchmark(miner_id, cfg)
        comb = [(500, 1200), (525, 1250)]

        # Mock poller metric sample
        class DummySample:
            hashrate_ths = 2.0
            power_w = 30.0
            temp_chip_c = 50.0
            temp_vr_c = 45.0
            error_pct = 0.0
            rejected = 0
            accepted = 100

        benchmark.poller.last_results[miner_id] = DummySample()

        # Run sweep
        await benchmark._run_benchmark_sweep(bench_id, miner_id, cfg, comb)

        res = await db.get_latest_miner_benchmark(miner_id)
        assert res is not None
        assert res["status"] == "completed"
        assert res["best_eff_freq"] is not None
        assert res["best_hash_freq"] is not None
    finally:
        benchmark.poller.last_results.pop(miner_id, None)
        async with db.connect() as conn:
            await conn.execute("DELETE FROM miners WHERE id = ?", (miner_id,))

