# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the stored per-sensor ambient (room) temperature time-series.

Covers backend/db.py: the per-sensor insert, the 1-minute and 1-hour
rollups (grouped by ``sensor_id``), the tier routing shared with the
per-miner metrics, the tiered-retention sweep reaching the ambient tables,
sensor isolation in range queries, and the migration that resets the old
single-series schema to the per-sensor one.

Runs against throwaway SQLite files via a patched ``db_path``, so the real
data directory is never touched. Runs under pytest, or standalone:
``python tests/test_ambient_history.py``.
"""
from __future__ import annotations

import asyncio
import pathlib
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend import db

_TMP = tempfile.TemporaryDirectory(prefix="mw-test-ambient-")

SID = "0000000000aa"
SID2 = "0000000000bb"


def _use_fresh_db(name: str) -> None:
    """Point the db module at a brand-new SQLite file (one per test)."""
    db.db_path = lambda: pathlib.Path(_TMP.name) / f"{name}.db"


def _aligned_base() -> int:
    """An hour-aligned timestamp two hours in the past, so every sample we
    insert falls inside *closed* minute/hour buckets the rollups will pick
    up (they deliberately skip the current, still-filling bucket)."""
    return ((db.now_ts() // 3600) * 3600) - 7200


async def _seed_raw(
    base: int, sensor_id: str = SID, count: int = 21, step: int = 30
) -> list[float]:
    """Insert ``count`` samples ``step`` seconds apart, triangular 20→24→20."""
    vals: list[float] = []
    for i in range(count):
        v = round(20.0 + abs((i % 8) - 4) * 0.5, 1)
        vals.append(v)
        await db.insert_ambient_metric(sensor_id, base + i * step, v)
    return vals


def test_insert_and_raw_range():
    _use_fresh_db("raw")

    async def run():
        await db.init_db()
        base = _aligned_base()
        vals = await _seed_raw(base)

        rows, tier = await db.ambient_metrics_range(base, base + 600, SID)  # span 600s
        assert tier == "metrics"               # raw tier for short ranges
        assert len(rows) == len(vals)
        assert set(rows[0].keys()) == {"ts", "temp_c"}
        assert rows[0]["ts"] < rows[-1]["ts"]  # ascending
        assert {r["temp_c"] for r in rows} <= set(vals)

    asyncio.run(run())


def test_rollup_1m_and_1h():
    _use_fresh_db("rollup")

    async def run():
        await db.init_db()
        base = _aligned_base()
        vals = await _seed_raw(base)

        rolled_1m = await db.rollup_ambient_to_1m(now=base + 3600, lookback_seconds=3600)
        rolled_1h = await db.rollup_ambient_to_1h(now=base + 7200, lookback_seconds=7200)
        assert rolled_1m >= 1 and rolled_1h >= 1

        m1, t_1m = await db.ambient_metrics_range(base, base + 7200, SID)        # 2h → 1m
        h1, t_1h = await db.ambient_metrics_range(base - 100_000, base + 7200, SID)  # → 1h
        assert t_1m == "metrics_1m" and len(m1) >= 1
        assert t_1h == "metrics_1h" and len(h1) >= 1

        lo, hi = min(vals), max(vals)
        assert lo <= m1[0]["temp_c"] <= hi   # bucket average within envelope
        assert lo <= h1[0]["temp_c"] <= hi

    asyncio.run(run())


def test_range_tier_routing():
    _use_fresh_db("routing")

    async def run():
        await db.init_db()
        base = _aligned_base()
        # Tier is chosen purely by span (mirrors _pick_metrics_tier), so it
        # holds even with no rows present.
        _, t_raw = await db.ambient_metrics_range(base, base + 3600, SID)
        _, t_1m = await db.ambient_metrics_range(base, base + 86_400, SID)
        _, t_1h = await db.ambient_metrics_range(base, base + 86_401, SID)
        assert (t_raw, t_1m, t_1h) == ("metrics", "metrics_1m", "metrics_1h")

    asyncio.run(run())


def test_sensors_are_isolated_in_range():
    _use_fresh_db("isolation")

    async def run():
        await db.init_db()
        base = _aligned_base()
        await db.insert_ambient_metric(SID, base, 20.0)
        await db.insert_ambient_metric(SID2, base, 30.0)
        a, _ = await db.ambient_metrics_range(base - 10, base + 10, SID)
        b, _ = await db.ambient_metrics_range(base - 10, base + 10, SID2)
        assert [r["temp_c"] for r in a] == [20.0]
        assert [r["temp_c"] for r in b] == [30.0]

    asyncio.run(run())


def test_rollup_keeps_sensors_separate():
    _use_fresh_db("rollup_iso")

    async def run():
        await db.init_db()
        base = _aligned_base()
        for i in range(21):
            await db.insert_ambient_metric(SID, base + i * 30, 20.0)
            await db.insert_ambient_metric(SID2, base + i * 30, 30.0)
        await db.rollup_ambient_to_1m(now=base + 3600, lookback_seconds=3600)

        m_a, t_a = await db.ambient_metrics_range(base, base + 7200, SID)
        m_b, t_b = await db.ambient_metrics_range(base, base + 7200, SID2)
        assert t_a == "metrics_1m" and t_b == "metrics_1m"
        assert len(m_a) >= 1 and len(m_b) >= 1
        assert all(abs(r["temp_c"] - 20.0) < 1e-6 for r in m_a)  # never blended
        assert all(abs(r["temp_c"] - 30.0) < 1e-6 for r in m_b)

    asyncio.run(run())


def test_cleanup_covers_ambient():
    _use_fresh_db("cleanup")

    async def run():
        await db.init_db()
        # One ancient raw sample (well past the 48h raw window) must be swept.
        old_ts = db.now_ts() - 10 * 24 * 3600
        await db.insert_ambient_metric(SID, old_ts, 21.0)

        deleted = await db.cleanup_tiered(
            retention_raw_hours=48, retention_1m_days=30, retention_1h_days=730,
        )
        for key in ("ambient_metrics", "ambient_metrics_1m", "ambient_metrics_1h"):
            assert key in deleted
        assert deleted["ambient_metrics"] >= 1

        rows, _ = await db.ambient_metrics_range(old_ts - 60, old_ts + 60, SID)
        assert rows == []  # pruned

    asyncio.run(run())


def test_migration_resets_old_single_series_schema():
    _use_fresh_db("migrate")

    # Build a DB that still carries the OLD single-series ambient schema
    # (keyed on ts only, no sensor_id) with one stored row.
    path = db.db_path()
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE ambient_metrics (ts INTEGER PRIMARY KEY, temp_c REAL);"
        "CREATE TABLE ambient_metrics_1m (ts INTEGER PRIMARY KEY, temp_c REAL,"
        " temp_min_c REAL, temp_max_c REAL, sample_count INTEGER NOT NULL);"
        "CREATE TABLE ambient_metrics_1h (ts INTEGER PRIMARY KEY, temp_c REAL,"
        " temp_min_c REAL, temp_max_c REAL, sample_count INTEGER NOT NULL);"
        "INSERT INTO ambient_metrics (ts, temp_c) VALUES (1000, 21.0);"
    )
    conn.commit()
    conn.close()

    async def run():
        await db.init_db()

        check = sqlite3.connect(str(db.db_path()))
        cols = [r[1] for r in check.execute("PRAGMA table_info(ambient_metrics)").fetchall()]
        check.close()
        assert "sensor_id" in cols                       # migrated to per-sensor

        # Old single-series data is intentionally discarded by the reset.
        rows, _ = await db.ambient_metrics_range(0, 10_000, "legacy000000")
        assert rows == []

        # And the new per-sensor path works on the migrated tables.
        await db.insert_ambient_metric(SID, 1000, 22.5)
        rows2, _ = await db.ambient_metrics_range(900, 1100, SID)
        assert [r["temp_c"] for r in rows2] == [22.5]

    asyncio.run(run())


def test_miner_ambient_sensor_assignment():
    _use_fresh_db("assign")

    async def run():
        await db.init_db()
        mid = await db.upsert_miner({"name": "Rig", "family": "bitaxe", "host": "10.0.0.1"})

        m = await db.get_miner(mid)
        assert m is not None and "ambient_sensor_id" in m and "ambient_sensor_name" in m
        assert m["ambient_sensor_id"] is None and m["ambient_sensor_name"] is None

        await db.set_ambient_sensor(mid, SID, "Garage")
        m = await db.get_miner(mid)
        assert m["ambient_sensor_id"] == SID and m["ambient_sensor_name"] == "Garage"

        # The poller's refresh heals a rename without the user reassigning.
        await db.refresh_assigned_sensor_name(SID, "Garage Bench")
        assert (await db.get_miner(mid))["ambient_sensor_name"] == "Garage Bench"

        await db.set_ambient_sensor(mid, None)              # clear both id and name
        m = await db.get_miner(mid)
        assert m["ambient_sensor_id"] is None and m["ambient_sensor_name"] is None

    asyncio.run(run())


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
