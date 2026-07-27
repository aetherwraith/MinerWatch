# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the consolidated panel feed (backend/panel.panel_feed).

Pure-function tests — no I/O. The panel feed is the single ``/api/panel``
blob the ESPHome touch panel polls over HTTP. Runs under pytest, or
standalone: ``python tests/test_panel_feed.py``.
"""
from __future__ import annotations

import json
import pathlib
import sys

# Make the repo root importable whether invoked via pytest or directly.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend.miners.base import MinerSample
from backend.panel import PANEL_MAX_TEMPS, _num, panel_feed


def _sample(**kw) -> MinerSample:
    return MinerSample(
        family=kw.pop("family", "bitaxe"),
        host=kw.pop("host", "10.0.0.5"),
        **kw,
    )


def test_num_coercion() -> None:
    assert _num(None) is None
    assert _num("nope") is None
    assert _num(4.987) == 4.99
    assert _num(95) == 95.0


def test_panel_feed_shape_names_and_values() -> None:
    miners = [
        {"id": 1, "mac": "DE:AD:BE:EF:12:34", "name": "Avalon Q"},
        {"id": 2, "mac": "AA:BB:CC:DD:EE:FF"},  # no rec name -> hostname fallback
    ]
    samples = {
        1: _sample(host="10.0.0.11", online=True, model="Avalon Nano 3",
                   hashrate_ths=4.9, power_w=95.0, temp_chip_c=62.0, temp_vr_c=70.0),
        2: _sample(host="10.0.0.12", online=False, hostname="bitaxe-2"),
    }
    feed = panel_feed(miners, samples)
    assert set(feed) == {"miners"}
    rows = feed["miners"]
    assert len(rows) == 2

    a = rows[0]
    assert a["id"] == "deadbeef1234"          # sanitized MAC
    assert a["name"] == "Avalon Q"            # from the DB record
    assert a["ip"] == "10.0.0.11"             # sample.host
    assert a["model"] == "Avalon Nano 3"
    assert (a["hr"], a["pw"], a["tp"], a["vr"]) == (4.9, 95.0, 62.0, 70.0)
    assert a["on"] is True

    b = rows[1]
    assert b["id"] == "aabbccddeeff"
    assert b["name"] == "bitaxe-2"            # hostname fallback
    assert b["ip"] == "10.0.0.12"
    assert b["on"] is False
    assert b["hr"] is None                    # offline / no data -> null
    assert b["vr"] is None                    # VR not reported -> null

    # Must be JSON-serialisable (exactly what the endpoint returns).
    assert json.loads(json.dumps(feed)) == feed


def test_panel_feed_missing_sample() -> None:
    miners = [{"id": 9, "mac": "", "name": "Ghost", "host": "10.0.0.99"}]
    feed = panel_feed(miners, {})             # no sample for id 9
    row = feed["miners"][0]
    assert row["name"] == "Ghost"
    assert row["ip"] == "10.0.0.99"           # falls back to the rec address
    assert row["on"] is False
    assert row["hr"] is None


def test_panel_feed_btc_price_optional() -> None:
    miners = [{"id": 1, "mac": "AA:BB:CC:DD:EE:FF", "name": "M"}]

    # Omitted by default — the panel shows "--" until a price arrives.
    feed = panel_feed(miners, {})
    assert "btc_usd" not in feed and "btc_chg" not in feed and "btc_at" not in feed

    # When provided: USD rounds to int, change to 2dp, stamp passes through.
    feed = panel_feed(miners, {}, btc_usd=70996.4, btc_chg=-3.927,
                      btc_at="Tue 2 Jun, 05:52")
    assert feed["btc_usd"] == 70996
    assert isinstance(feed["btc_usd"], int)
    assert feed["btc_chg"] == -3.93
    assert feed["btc_at"] == "Tue 2 Jun, 05:52"
    assert json.loads(json.dumps(feed)) == feed   # still JSON-serialisable

    # change/stamp are tied to the price: without a price they're dropped.
    feed = panel_feed(miners, {}, btc_usd=None, btc_chg=1.5, btc_at="Tue 2 Jun, 05:52")
    assert "btc_usd" not in feed and "btc_chg" not in feed and "btc_at" not in feed

    # A positive change keeps its sign; an empty stamp is treated as absent.
    feed = panel_feed(miners, {}, btc_usd=71000, btc_chg=2.5, btc_at="")
    assert feed["btc_chg"] == 2.5
    assert "btc_at" not in feed


def _order_fixture() -> tuple[list[dict], dict[int, MinerSample]]:
    """Four miners as list_miners() would hand them over (name order),
    including one without a MAC (falls back to the mw<id> identity)."""
    miners = [
        {"id": 1, "mac": "AA:00:00:00:00:01", "name": "Alpha"},
        {"id": 2, "mac": "AA:00:00:00:00:02", "name": "Bravo"},
        {"id": 3, "mac": "AA:00:00:00:00:03", "name": "Charlie"},
        {"id": 4, "mac": None, "name": "Delta", "host": "10.0.0.4"},
    ]
    samples = {
        1: _sample(host="10.0.0.1", online=True, hashrate_ths=1.1),
        3: _sample(host="10.0.0.3", online=True, hashrate_ths=3.3),
    }
    return miners, samples


def test_panel_feed_applies_custom_order() -> None:
    miners, samples = _order_fixture()
    baseline = panel_feed(miners, samples)
    feed = panel_feed(
        miners, samples,
        order=["aa0000000003", "mw4", "aa0000000001", "aa0000000002"],
    )
    assert [r["id"] for r in feed["miners"]] == [
        "aa0000000003", "mw4", "aa0000000001", "aa0000000002",
    ]
    # Same rows as the unordered feed — a pure permutation. Every field
    # of every miner is byte-identical; only the array order changed.
    by_id = lambda r: r["id"]
    assert sorted(feed["miners"], key=by_id) == sorted(baseline["miners"], key=by_id)
    assert json.loads(json.dumps(feed)) == feed


def test_panel_feed_partial_order_appends_rest_in_api_order() -> None:
    # Miners absent from the stored order (new ones) follow the ordered
    # block, keeping the incoming (name-sorted) sequence.
    miners, samples = _order_fixture()
    feed = panel_feed(miners, samples, order=["aa0000000002"])
    assert [r["id"] for r in feed["miners"]] == [
        "aa0000000002", "aa0000000001", "aa0000000003", "mw4",
    ]


def test_panel_feed_order_skips_stale_ids() -> None:
    # Ids of removed miners linger in the stored order on purpose (so a
    # returning miner reclaims its slot); the feed must skip them
    # without dropping or duplicating anyone.
    miners, samples = _order_fixture()
    feed = panel_feed(
        miners, samples,
        order=["dead0000beef", "aa0000000002", "aa0000000002", "mw99"],
    )
    ids = [r["id"] for r in feed["miners"]]
    assert ids[0] == "aa0000000002"
    assert sorted(ids) == sorted(
        ["aa0000000001", "aa0000000002", "aa0000000003", "mw4"]
    )


def test_panel_feed_no_order_is_byte_identical() -> None:
    # Backward compatibility: no stored order (None or empty) must
    # reproduce the default output exactly, BTC/temp blocks included.
    miners, samples = _order_fixture()
    kwargs = dict(
        btc_usd=70996.4, btc_chg=-3.927, btc_at="Tue 2 Jun, 05:52",
        temps=[{"name": "Garage", "current_c": 23.4, "min_c": 17.9, "max_c": 29.0}],
    )
    baseline = panel_feed(miners, samples, **kwargs)
    assert panel_feed(miners, samples, order=None, **kwargs) == baseline
    assert panel_feed(miners, samples, order=[], **kwargs) == baseline
    assert json.dumps(panel_feed(miners, samples, order=None, **kwargs)) == json.dumps(baseline)


def test_panel_feed_temps_optional() -> None:
    miners = [{"id": 1, "mac": "AA:BB:CC:DD:EE:FF", "name": "M"}]

    # Off by default — no rotating temperature block.
    feed = panel_feed(miners, {})
    assert "temps" not in feed

    # An empty list means no live sensors, same as absent (row hidden).
    assert "temps" not in panel_feed(miners, {}, temps=[])

    # Two sensors: terse keys, readings rounded to 1 dp, order preserved. A
    # stale sensor keeps min/max but reports a null current ("-" on the panel).
    feed = panel_feed(
        miners, {},
        temps=[
            {"name": "Garage", "current_c": 23.456, "min_c": 17.9, "max_c": 29.04},
            {"name": "Cucina", "current_c": None, "min_c": 16.0, "max_c": 26.0},
        ],
    )
    assert feed["temps"] == [
        {"n": "Garage", "c": 23.5, "mn": 17.9, "mx": 29.0},
        {"n": "Cucina", "c": None, "mn": 16.0, "mx": 26.0},
    ]
    assert json.loads(json.dumps(feed)) == feed

    # Capped so a wall panel never rotates through dozens of rows.
    many = [
        {"name": f"S{i}", "current_c": 20.0, "min_c": 10.0, "max_c": 25.0}
        for i in range(12)
    ]
    assert len(panel_feed(miners, {}, temps=many)["temps"]) == PANEL_MAX_TEMPS


if __name__ == "__main__":
    test_num_coercion()
    test_panel_feed_shape_names_and_values()
    test_panel_feed_missing_sample()
    test_panel_feed_btc_price_optional()
    test_panel_feed_applies_custom_order()
    test_panel_feed_partial_order_appends_rest_in_api_order()
    test_panel_feed_order_skips_stale_ids()
    test_panel_feed_no_order_is_byte_identical()
    test_panel_feed_temps_optional()
    print("ok — panel_feed tests passed")
