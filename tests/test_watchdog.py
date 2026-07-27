# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the overheat-watchdog threshold resolution.

``resolve_watchdog_thresholds`` is pure (no miner, poller, or event loop), so
it can be exercised directly. It picks the per-miner overheat trigger and the
derived release point for the server-side fan watchdog in ``auto_control``.

Runs under pytest, or standalone: ``python tests/test_watchdog.py``.
"""
from __future__ import annotations

import pathlib
import sys

# Make the repo root importable whether invoked via pytest or directly.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend.auto_control import (
    WATCHDOG_OVERHEAT_C,
    WATCHDOG_RELEASE_C,
    WATCHDOG_RELEASE_MARGIN_C,
    resolve_watchdog_thresholds,
)


def test_margin_matches_stock_band():
    # The derived margin must reproduce the historical 75 -> 65 band exactly.
    assert WATCHDOG_RELEASE_MARGIN_C == WATCHDOG_OVERHEAT_C - WATCHDOG_RELEASE_C


def test_default_when_no_override():
    overheat, release = resolve_watchdog_thresholds({"family": "bitaxe"})
    assert overheat == WATCHDOG_OVERHEAT_C
    assert release == WATCHDOG_RELEASE_C


def test_canaan_override_moves_band():
    overheat, release = resolve_watchdog_thresholds(
        {"family": "canaan", "watchdog_overheat_c": 85.0}
    )
    assert overheat == 85.0
    assert release == 75.0  # trails by the fixed 10° margin


def test_canaan_low_override_band_stays_valid():
    overheat, release = resolve_watchdog_thresholds(
        {"family": "canaan", "watchdog_overheat_c": 60.0}
    )
    assert overheat == 60.0
    assert release == 50.0
    assert release < overheat  # the band must never invert


def test_canaan_none_uses_default():
    overheat, release = resolve_watchdog_thresholds(
        {"family": "canaan", "watchdog_overheat_c": None}
    )
    assert (overheat, release) == (WATCHDOG_OVERHEAT_C, WATCHDOG_RELEASE_C)


def test_override_ignored_for_non_canaan():
    # A stray value on a non-Avalon family must NOT change the hard 75° net.
    overheat, release = resolve_watchdog_thresholds(
        {"family": "bitaxe", "watchdog_overheat_c": 90.0}
    )
    assert overheat == WATCHDOG_OVERHEAT_C
    assert release == WATCHDOG_RELEASE_C


def test_malformed_value_falls_back_to_default():
    # A corrupt stored value must arm the default net, never disarm it.
    overheat, release = resolve_watchdog_thresholds(
        {"family": "canaan", "watchdog_overheat_c": "nonsense"}
    )
    assert overheat == WATCHDOG_OVERHEAT_C
    assert release == WATCHDOG_RELEASE_C


def test_missing_or_empty_family():
    assert resolve_watchdog_thresholds({})[0] == WATCHDOG_OVERHEAT_C
    assert resolve_watchdog_thresholds({"family": None})[0] == WATCHDOG_OVERHEAT_C


if __name__ == "__main__":
    fns = {k: v for k, v in dict(globals()).items() if k.startswith("test_")}
    for name, fn in fns.items():
        fn()
        print(f"ok  {name}")
    print(f"\n{len(fns)} watchdog tests passed")
