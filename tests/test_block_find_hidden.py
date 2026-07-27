# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the per-trophy hidden flag on block_finds.

Covers backend/db.py: the dashboard filter (``include_hidden=False``
excludes dismissed trophies), the everything-else view
(``include_hidden=True`` — Umbrel widget, Settings restore list), the
single-row hide/unhide flip, and the anti-duplication guard staying
aware of hidden rows (hiding must never let the same share re-fire).

Runs against a throwaway SQLite file via a patched ``db_path``, so the
real data directory is never touched. Runs under pytest, or
standalone: ``python tests/test_block_find_hidden.py``.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend import db

_TMP = tempfile.TemporaryDirectory(prefix="mw-test-hidden-")


def _use_fresh_db(name: str) -> None:
    """Point the db module at a brand-new SQLite file. Each test gets
    its own database, so tests stay order-independent (the standalone
    runner below executes them alphabetically, pytest by declaration)."""
    db.db_path = lambda: pathlib.Path(_TMP.name) / f"{name}.db"


async def _seed() -> tuple[int, int]:
    await db.init_db()
    first = await db.insert_block_find(
        miner_id=None, miner_name="Gamma",
        share_difficulty=130e12, network_difficulty=126e12,
        ts=1_900_000_000, block_height=905123,
    )
    second = await db.insert_block_find(
        miner_id=None, miner_name="Lucky",
        share_difficulty=140e12, network_difficulty=126e12,
        ts=1_900_000_600, block_height=905200,
    )
    return first, second


def test_hide_filters_dashboard_but_not_full_view():
    _use_fresh_db("filters")

    async def run():
        first, second = await _seed()

        assert await db.set_block_find_hidden(first, hidden=True) is True

        visible = await db.list_block_finds()
        assert [r["id"] for r in visible] == [second]
        assert visible[0]["hidden"] == 0

        everything = await db.list_block_finds(include_hidden=True)
        assert {r["id"]: r["hidden"] for r in everything} == {first: 1, second: 0}

    asyncio.run(run())


def test_unhide_restores_and_missing_id_is_false():
    _use_fresh_db("unhide")

    async def run():
        first, _second = await _seed()
        await db.set_block_find_hidden(first, hidden=True)

        assert await db.set_block_find_hidden(first, hidden=False) is True
        assert len(await db.list_block_finds()) == 2
        assert await db.set_block_find_hidden(999_999, hidden=True) is False

    asyncio.run(run())


def test_hidden_rows_still_feed_the_antidup_guard():
    """Hiding a trophy must NOT let the poller re-fire the same share:
    last_block_find_share_value ignores the hidden flag by design."""
    _use_fresh_db("guard")

    async def run():
        await db.init_db()
        miner_id = await db.upsert_miner(
            {"name": "Gamma", "family": "bitaxe", "host": "10.0.0.10"}
        )
        find_id = await db.insert_block_find(
            miner_id=miner_id, miner_name="Gamma",
            share_difficulty=160e12, network_difficulty=126e12,
            ts=1_900_001_200, block_height=905300,
        )
        await db.set_block_find_hidden(find_id, hidden=True)

        guard = await db.last_block_find_share_value(miner_id)
        assert guard == 160e12

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
