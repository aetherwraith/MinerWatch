# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the per-miner offline-alert mute.

Covers backend/db.py (the offline_muted flag + ack_offline_alerts) and
backend/alerts.py evaluate(): a muted miner fires no offline alert and no
DB row, the first alert still fires before the user mutes (only the repeats
are silenced), and the mute clears itself when the miner is polled online
again (the reconnect = the next restart).

Runs against a throwaway SQLite file via a patched db_path; alerts.get_config
and alerts.send_notification are stubbed so nothing leaves the process. Runs
under pytest, or standalone: python tests/test_offline_mute.py.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile
import time
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend import alerts, db
from backend.miners.base import MinerSample

_TMP = tempfile.TemporaryDirectory(prefix="mw-test-mute-")


def _use_fresh_db(name: str) -> None:
    db.db_path = lambda: pathlib.Path(_TMP.name) / f"{name}.db"
    db._init_db_sync()  # create the schema on the throwaway file


def _stub_config() -> None:
    """Minimal config the evaluate() offline/temp branches read."""
    alerts.get_config = lambda: SimpleNamespace(
        alerts=SimpleNamespace(
            repeat_seconds=600,
            offline_threshold_seconds=60,
            temp_chip_threshold=75.0,
            temp_vr_threshold=90.0,
        )
    )


def _capture_notifications() -> list[dict]:
    """Replace alerts.send_notification with a recorder. Returns the store."""
    sent: list[dict] = []

    async def _fake(payload: dict) -> None:
        sent.append(payload)

    alerts.send_notification = _fake
    return sent


def _offline_sample() -> MinerSample:
    return MinerSample(family="bitaxe", host="10.0.0.10", online=False)


def test_muted_miner_fires_no_offline_alert():
    _use_fresh_db("muted")
    _stub_config()

    async def run():
        mid = await db.upsert_miner(
            {"name": "Rig", "family": "bitaxe", "host": "10.0.0.10"}
        )
        await db.set_offline_muted(mid, True)

        alerts._state.clear()
        alerts._state[mid] = {"online": False, "last_online_ts": int(time.time()) - 9999}
        sent = _capture_notifications()

        await alerts.evaluate({mid: _offline_sample()})

        assert sent == [], f"muted miner should not notify, got {sent}"
        rows = await db.list_alerts()
        assert all(r["code"] != "offline" for r in rows), "no offline row should be stored"

    asyncio.run(run())


def test_first_alert_fires_then_mute_silences_repeats():
    _use_fresh_db("first-then-mute")
    _stub_config()

    async def run():
        mid = await db.upsert_miner(
            {"name": "Rig", "family": "bitaxe", "host": "10.0.0.10"}
        )
        alerts._state.clear()
        alerts._state[mid] = {"online": False, "last_online_ts": int(time.time()) - 9999}
        sent = _capture_notifications()

        # First cycle, not muted yet -> the offline alert fires (the one the
        # user is fine receiving).
        await alerts.evaluate({mid: _offline_sample()})
        assert len(sent) == 1 and sent[0]["title"] == "Miner offline", sent

        # User taps Mute; a repeat would now be due -> mute must block it.
        await db.set_offline_muted(mid, True)
        alerts._state[mid]["last_offline_alert_ts"] = int(time.time()) - 9999
        sent.clear()

        await alerts.evaluate({mid: _offline_sample()})
        assert sent == [], f"mute should silence the repeat, got {sent}"

    asyncio.run(run())


def test_mute_clears_when_miner_back_online():
    _use_fresh_db("reconnect")
    _stub_config()

    async def run():
        mid = await db.upsert_miner(
            {"name": "Rig", "family": "bitaxe", "host": "10.0.0.10"}
        )
        await db.set_offline_muted(mid, True)

        alerts._state.clear()
        alerts._state[mid] = {
            "online": False,
            "offline_alerted": True,
            "last_online_ts": int(time.time()) - 9999,
        }
        sent = _capture_notifications()

        # Power comes back -> the miner answers a poll -> online.
        await alerts.evaluate(
            {mid: MinerSample(family="bitaxe", host="10.0.0.10", online=True)}
        )

        miner = await db.get_miner(mid)
        assert miner["offline_muted"] == 0, "reconnect must auto-clear the mute"
        # The existing "back online" recovery message still fires.
        assert any(s["title"] == "Miner online" for s in sent), sent

    asyncio.run(run())


def test_ack_offline_alerts_only_targets_offline_rows():
    _use_fresh_db("ack")
    _stub_config()

    async def run():
        mid = await db.upsert_miner(
            {"name": "Rig", "family": "bitaxe", "host": "10.0.0.10"}
        )
        await db.insert_alert(mid, "warning", "offline", "down")
        await db.insert_alert(mid, "warning", "offline", "still down")
        await db.insert_alert(mid, "critical", "temp_chip", "hot")

        acked = await db.ack_offline_alerts(mid)
        assert acked == 2, f"should ack both offline rows, got {acked}"

        unread = await db.list_alerts(only_unack=True)
        codes = sorted(r["code"] for r in unread)
        assert codes == ["temp_chip"], f"only the temp alert stays unread, got {codes}"

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
