# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the ambient temperature registry (backend/ambient_temp.py).

Pure logic, multi-sensor. A fake monotonic clock is injected so freshness,
eviction and the moving-average window are deterministic without sleeping.
Runs under pytest, or standalone: ``python tests/test_ambient_temp.py``.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend.ambient_temp import (
    AVAIL_S,
    EVICT_S,
    AmbientRegistry,
    AmbientTemp,
)


class FakeClock:
    """Controllable monotonic stand-in shared by a holder and its registry."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


# ---- single holder: averaging / extremes / freshness (unchanged logic) ----

def test_holder_average_and_extremes() -> None:
    a = AmbientTemp(clock=FakeClock())
    for v in (20.0, 22.0, 24.0):
        assert a.update(v, "Room") is True
    s = a.snapshot()
    assert s.has_data is True and s.available is True
    assert abs(s.current_c - 22.0) < 1e-6          # mean of the window
    assert s.min_c == 20.0 and s.max_c == 24.0     # extremes of real values
    assert s.name == "Room"


def test_holder_min_max_track_spikes_not_average() -> None:
    a = AmbientTemp(clock=FakeClock())
    a.update(20.0, "Room")
    a.update(35.0, "Room")   # brief spike
    a.update(20.0, "Room")
    s = a.snapshot()
    assert s.max_c == 35.0                          # spike kept in max
    assert abs(s.current_c - 25.0) < 1e-6           # but average is 25


def test_holder_rejects_out_of_range_and_nonfinite() -> None:
    a = AmbientTemp(clock=FakeClock())
    assert a.update(999.0, "Room") is False
    assert a.update(-60.0, "Room") is False
    assert a.update(float("nan"), "Room") is False
    assert a.update(float("inf"), "Room") is False
    assert a.update("nan-ish", "Room") is False
    assert a.snapshot().has_data is False


def test_holder_staleness_blanks_current_keeps_minmax() -> None:
    clk = FakeClock()
    a = AmbientTemp(clock=clk)
    a.update(21.0, "Room")
    clk.advance(AVAIL_S + 1)
    s = a.snapshot()
    assert s.available is False
    assert s.current_c is None                      # current goes to "-"
    assert s.min_c == 21.0 and s.max_c == 21.0 and s.has_data is True


# ---- registry: multi-sensor, ordering, eviction, cap, invariants ----

def test_registry_empty() -> None:
    r = AmbientRegistry(clock=FakeClock())
    assert r.snapshot_all() == []
    p = r.primary_snapshot()
    assert p.has_data is False and p.sensor_id is None and p.name is None


def test_registry_two_sensors_independent_and_sorted_by_name() -> None:
    r = AmbientRegistry(clock=FakeClock())
    assert r.update("0000000000aa", "Kitchen", 20.0) is True
    assert r.update("0000000000bb", "Garage", 30.0) is True
    snaps = r.snapshot_all()
    assert [s.name for s in snaps] == ["Garage", "Kitchen"]   # sorted by name
    by_id = {s.sensor_id: s for s in snaps}
    assert by_id["0000000000aa"].current_c == 20.0
    assert by_id["0000000000bb"].current_c == 30.0


def test_registry_invariant_has_data_implies_name_and_id() -> None:
    r = AmbientRegistry(clock=FakeClock())
    r.update("0000000000aa", "Kitchen", 20.0)
    for s in r.snapshot_all():
        if s.has_data:
            assert s.name and s.sensor_id


def test_registry_name_follows_latest_post() -> None:
    r = AmbientRegistry(clock=FakeClock())
    r.update("0000000000aa", "Old name", 20.0)
    r.update("0000000000aa", "New name", 21.0)
    s = r.sensor_snapshot("0000000000aa")
    assert s is not None and s.name == "New name"


def test_registry_evicts_long_silent_sensor() -> None:
    clk = FakeClock()
    r = AmbientRegistry(clock=clk)
    r.update("0000000000aa", "Kitchen", 20.0)
    assert len(r.snapshot_all()) == 1
    clk.advance(EVICT_S + 1)
    assert r.snapshot_all() == []                    # row drops off the list


def test_registry_cap_rejects_extra_sensors() -> None:
    r = AmbientRegistry(clock=FakeClock(), max_sensors=2)
    assert r.update("00000000000a", "A", 20.0) is True
    assert r.update("00000000000b", "B", 20.0) is True
    assert r.update("00000000000c", "C", 20.0) is False   # cap reached
    assert len(r.snapshot_all()) == 2


def test_registry_invalid_first_sample_leaves_no_row() -> None:
    r = AmbientRegistry(clock=FakeClock())
    assert r.update("0000000000aa", "Kitchen", 999.0) is False
    assert r.snapshot_all() == []                    # no empty holder leaked


def test_registry_primary_is_first_registered() -> None:
    r = AmbientRegistry(clock=FakeClock())
    r.update("0000000000aa", "Kitchen", 20.0)        # registered first
    r.update("0000000000bb", "Garage", 30.0)
    p = r.primary_snapshot()
    assert p.sensor_id == "0000000000aa"             # insertion order, not name
    assert p.current_c == 20.0


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
    print("ok — ambient_temp tests passed" if not failures else f"{failures} FAILED")
    sys.exit(1 if failures else 0)
