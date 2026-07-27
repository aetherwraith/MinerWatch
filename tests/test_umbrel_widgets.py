# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the umbrelOS desktop-widget payload builders.

Covers the contract umbrelOS relies on (backend/umbrel_widgets.py):

  * fleet four-stats: aggregates only online miners, renders all values
    as strings, switches to the celebration layout within the 7-day
    window after a block find and back out of it afterwards;
  * miners list: offline rows first with "Offline · age", stable
    ordering by nominal hashrate, 5-row cap with the "+N more miners"
    aggregate row, and the no-miners shape.

Runs under pytest, or standalone: ``python tests/test_umbrel_widgets.py``.
"""
from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

# Make the repo root importable whether invoked via pytest or directly.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend.umbrel_widgets import (
    BLOCK_CELEBRATION_SECONDS,
    WIDGET_REFRESH,
    build_fleet_widget,
    build_miners_widget,
)

NOW = 1_900_000_000.0


def _sample(**overrides):
    """A live MinerSample stand-in with the fields the builders read."""
    defaults = dict(
        online=True,
        hashrate_ths=1.2,
        expected_hashrate_ths=1.25,
        temp_chip_c=58.4,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _miner(mid, name, model="Bitaxe Gamma"):
    return {"id": mid, "name": name, "model": model, "host": f"10.0.0.{mid}"}


# ---------- fleet (four-stats) ----------

def test_fleet_normal_aggregates_online_only():
    miners = [_miner(1, "Lucky"), _miner(2, "Garage"), _miner(3, "Attic")]
    samples = {
        1: _sample(hashrate_ths=1.2, temp_chip_c=58.4),
        2: _sample(hashrate_ths=4.0, temp_chip_c=61.2),
        3: _sample(online=False, hashrate_ths=9.9, temp_chip_c=99.0),
    }
    w = build_fleet_widget(miners, samples, best_alltime=4.29e9, latest_find=None, now=NOW)

    assert w["type"] == "four-stats"
    items = w["items"]
    assert len(items) == 4
    assert items[0] == {"title": "Hashrate", "text": "5.20", "subtext": "TH/s"}
    assert items[1]["text"] == "2/3"
    assert items[2] == {"title": "Best share", "text": "4.29", "subtext": "G"}
    assert items[3] == {"title": "Max temp", "text": "61", "subtext": "°C"}
    for item in items:
        assert all(isinstance(v, str) for v in item.values())


def test_fleet_sub_ths_uses_ghs_and_handles_missing_data():
    miners = [_miner(1, "Lucky")]
    samples = {1: _sample(hashrate_ths=0.85, temp_chip_c=None)}
    w = build_fleet_widget(miners, samples, best_alltime=None, latest_find=None, now=NOW)

    assert w["items"][0] == {"title": "Hashrate", "text": "850", "subtext": "GH/s"}
    assert w["items"][2]["text"] == "—"
    assert w["items"][3]["text"] == "—"


def test_fleet_all_offline_shows_dashes_not_zero():
    miners = [_miner(1, "Lucky")]
    samples = {1: _sample(online=False)}
    w = build_fleet_widget(miners, samples, best_alltime=None, latest_find=None, now=NOW)

    assert w["items"][0]["text"] == "—"
    assert w["items"][1]["text"] == "0/1"


def test_fleet_celebration_within_window():
    find = {
        "ts": NOW - 3600,
        "miner_name": "Lucky",
        "block_height": 905123,
        "share_difficulty": 127.4e12,
    }
    w = build_fleet_widget([], {}, best_alltime=None, latest_find=find, now=NOW)

    items = w["items"]
    assert items[0]["title"] == "🎉 Block found! 🎉"
    assert items[0] == {"title": "🎉 Block found! 🎉", "text": "905123", "subtext": "height"}
    assert items[1] == {"title": "Found by", "text": "Lucky", "subtext": ""}
    assert items[2] == {"title": "Share diff", "text": "127.40", "subtext": "T"}
    assert items[3]["title"] == "Found on"
    assert items[3]["text"] != "—"


def test_fleet_celebration_expires_after_window():
    find = {"ts": NOW - BLOCK_CELEBRATION_SECONDS - 1, "miner_name": "Lucky",
            "block_height": 905123, "share_difficulty": 127.4e12}
    w = build_fleet_widget([_miner(1, "Lucky")], {1: _sample()},
                           best_alltime=1.0e9, latest_find=find, now=NOW)

    assert w["items"][0]["title"] == "Hashrate"


def test_fleet_celebration_without_height_falls_back_to_pickaxe():
    find = {"ts": NOW - 60, "miner_name": "Lucky",
            "block_height": None, "share_difficulty": 1.0e12}
    w = build_fleet_widget([], {}, best_alltime=None, latest_find=find, now=NOW)

    assert w["items"][0]["text"] == "⛏️"
    assert w["items"][0]["subtext"] == ""


# ---------- miners (list) ----------

def test_miners_rows_offline_first_then_nominal_desc():
    miners = [_miner(1, "Lucky"), _miner(2, "Garage", "NerdQAxe++"), _miner(3, "Attic")]
    samples = {
        1: _sample(hashrate_ths=1.2, expected_hashrate_ths=1.25, temp_chip_c=58.4),
        2: _sample(hashrate_ths=4.78, expected_hashrate_ths=4.8, temp_chip_c=61.0),
        3: _sample(online=False),
    }
    w = build_miners_widget(miners, samples, last_seen={3: NOW - 2 * 3600}, now=NOW)

    assert w["type"] == "list"
    assert w["noItemsText"] == "No miners discovered yet"
    rows = w["items"]
    assert rows[0]["subtext"].startswith("Attic")
    assert rows[0]["text"] == "🔴 Offline · 2 h"
    assert rows[1]["subtext"] == "Garage · NerdQAxe++"
    assert rows[1]["text"] == "4.78 TH/s · 61 °C"
    assert rows[2]["text"] == "1.20 TH/s · 58 °C"


def test_miners_label_skips_model_when_name_contains_it():
    miners = [_miner(1, "Bitaxe Gamma garage", "Bitaxe Gamma")]
    w = build_miners_widget(miners, {1: _sample()}, last_seen={}, now=NOW)

    assert w["items"][0]["subtext"] == "Bitaxe Gamma garage"


def test_miners_offline_without_history_has_no_age():
    miners = [_miner(1, "Lucky")]
    w = build_miners_widget(miners, {1: _sample(online=False)}, last_seen={1: None}, now=NOW)

    assert w["items"][0]["text"] == "🔴 Offline"


def test_miners_seven_become_four_plus_aggregate():
    miners = [_miner(i, f"m{i}", model=None) for i in range(1, 8)]
    samples = {i: _sample(hashrate_ths=float(i), expected_hashrate_ths=float(i)) for i in range(1, 8)}
    w = build_miners_widget(miners, samples, last_seen={}, now=NOW)

    rows = w["items"]
    assert len(rows) == 5
    assert [r["subtext"] for r in rows[:4]] == ["m7", "m6", "m5", "m4"]
    assert rows[4]["subtext"] == "+3 more miners"
    assert rows[4]["text"] == "6.00 TH/s"


def test_miners_empty_fleet():
    w = build_miners_widget([], {}, last_seen={}, now=NOW)

    assert w["items"] == []
    assert w["noItemsText"] == "No miners discovered yet"


# ---------- contract shared by both widgets ----------

def test_payloads_carry_refresh_for_umbreld():
    """umbreld runs ``ms(widgetData.refresh)`` on the endpoint *response*
    (the manifest value is never merged in) and ``ms(undefined)`` throws,
    so a payload without ``refresh`` leaves the widget stuck on its
    skeleton. Regression test for the 1.11.0 launch bug.
    """
    find = {"ts": NOW - 60, "miner_name": "Lucky",
            "block_height": 905123, "share_difficulty": 1.0e12}
    payloads = (
        build_fleet_widget([], {}, best_alltime=None, latest_find=None, now=NOW),
        build_fleet_widget([], {}, best_alltime=None, latest_find=find, now=NOW),
        build_miners_widget([], {}, last_seen={}, now=NOW),
    )
    for payload in payloads:
        assert payload["refresh"] == WIDGET_REFRESH


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
