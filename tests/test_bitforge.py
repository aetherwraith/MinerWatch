# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the BitForge (forge-os) driver and its auto-detection.

The BitForge Nano runs forge-os, an AxeOS fork whose /api/system/info
renames a handful of fields (``fanSpeed``, ``chiptemp1``/``chiptemp2``)
and whose flat ``temp`` is the *average* of the two per-ASIC sensors.
These tests pin the dialect mapping in BitForgeDriver._parse(), the
forge-os PATCH spelling for fan control, and the discovery
classification (deviceModel "BITFORGE_NANO" → family ``bitforge``,
checked before the NerdOctaxe multi-fan heuristics).

Runs under pytest, or standalone: ``python tests/test_bitforge.py``.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from unittest.mock import AsyncMock, patch

# Make the repo root importable whether invoked via pytest or directly.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend import discovery
from backend.discovery import _pretty_bitforge_model
from backend.miners import DRIVERS, get_driver
from backend.miners.bitforge import BitForgeDriver


def _forge_info(**overrides):
    """A realistic forge-os v1.5 /api/system/info payload (BitForge Nano,
    2x BM1370). Key set mirrors GET_system_info in the firmware's
    main/http_server/http_server.c."""
    data = {
        "power": 38.5,
        "voltage": 11980.0,
        "current": 3210.0,
        "temp": 52.5,
        "vrTemp": 48.0,
        "maxPower": 60,
        "nominalVoltage": 12,
        "hashRate": 1980.2,
        "bestDiff": 28100000,
        "bestSessionDiff": "3.46M",
        "stratumDiff": 1000,
        "isUsingFallbackStratum": 0,
        "isPSRAMAvailable": 1,
        "freeHeap": 8123456,
        "coreVoltage": 1150,
        "coreVoltageActual": 1142,
        "frequency": 525,
        "ssid": "example-wifi",
        "macAddr": "aa:bb:cc:11:22:33",
        "hostname": "BitForge",
        "wifiStatus": "Connected!",
        "wifiRSSI": -55,
        "apEnabled": 0,
        "sharesAccepted": 1234,
        "sharesRejected": 5,
        "sharesRejectedReasons": [],
        "uptimeSeconds": 3600,
        "asicCount": 2,
        "smallCoreCount": 2040,
        "ASICModel": "BM1370",
        "stratumURL": "solo.atlaspool.io",
        "fallbackStratumURL": "public-pool.io",
        "stratumPort": 4333,
        "fallbackStratumPort": 4333,
        "stratumUser": "bc1qxyz.BitForgeNano",
        "fallbackStratumUser": "bc1qxyz.BitForgeNano",
        "stratumTLS": 1,
        "fallbackStratumTLS": 1,
        "version": "v1.5",
        "idfVersion": "v5.4",
        "boardVersion": "800",
        "runningPartition": "ota_0",
        "overheat_mode": 0,
        "overclockEnabled": 0,
        "autofanspeed": 1,
        "fanSpeed": 66,
        "fanrpm": 4100,
        "manualFanSpeed": 66,
        "chiptemp1": 51.0,
        "chiptemp2": 54.0,
    }
    data.update(overrides)
    return data


def _forge_v10_info(**overrides):
    """A real forge-os v1.0 /api/system/info payload, captured from a
    BitForge Nano running the factory firmware (identifiers anonymised).
    Differences from v1.5 that matter to the driver: ``fanspeed`` is
    lowercase (stock-AxeOS style), ``bestDiff`` is an SI *string*, and
    there is no ``manualFanSpeed`` — nor any ``/api/system/asic``
    endpoint, so discovery gets no ``deviceModel`` from these boards."""
    data = {
        "power": 40.790000915527344,
        "voltage": 12015,
        "current": 3420,
        "temp": 54.125,
        "vrTemp": 71,
        "maxPower": 60,
        "nominalVoltage": 12,
        "hashRate": 2592.436279296875,
        "bestDiff": "6.51M",
        "bestSessionDiff": "6.51M",
        "stratumDiff": 8192,
        "isUsingFallbackStratum": 0,
        "isPSRAMAvailable": 1,
        "freeHeap": 8486096,
        "freeHeapInternal": 139375,
        "freeHeapSpiram": 8378692,
        "coreVoltage": 1160,
        "coreVoltageActual": 1129,
        "frequency": 636,
        "ssid": "example-wifi",
        "macAddr": "aa:bb:cc:00:11:22",
        "hostname": "BitForge",
        "wifiStatus": "Connected!",
        "wifiRSSI": -54,
        "apEnabled": 0,
        "requestFromAp": False,
        "sharesAccepted": 229,
        "sharesRejected": 0,
        "sharesRejectedReasons": [],
        "uptimeSeconds": 2066,
        "asicCount": 2,
        "smallCoreCount": 2040,
        "ASICModel": "BM1370",
        "stratumURL": "192.0.2.25",
        "fallbackStratumURL": "eusolo.ckpool.org",
        "stratumPort": 2018,
        "fallbackStratumPort": 3333,
        "stratumUser": "bc1qxyz.BitForge",
        "fallbackStratumUser": "bc1qxyz.BitForge",
        "version": "v1.0",
        "idfVersion": "v5.5.1",
        "boardVersion": "800",
        "runningPartition": "factory",
        "overheat_mode": 0,
        "overclockEnabled": 0,
        "autofanspeed": 1,
        "fanspeed": 63,
        "fanrpm": 3651,
        "chiptemp1": 52.25,
        "chiptemp2": 56,
    }
    data.update(overrides)
    return data


def _parse(**overrides):
    return BitForgeDriver("10.0.0.7")._parse(_forge_info(**overrides))


# ---- registry ------------------------------------------------------


def test_family_registered():
    assert DRIVERS["bitforge"] is BitForgeDriver
    assert get_driver("BitForge") is BitForgeDriver


# ---- _parse: forge-os field dialect --------------------------------


def test_parse_core_fields_and_family():
    s = _parse()
    assert s.family == "bitforge"
    assert s.online is True
    assert s.hashrate_ths == 1.9802
    assert s.power_w == 38.5
    assert s.asic_count == 2
    assert s.small_core_count == 2040
    assert s.mac == "AA:BB:CC:11:22:33"
    assert s.firmware_version == "v1.5"
    assert s.input_voltage_mv == 11980.0
    assert s.max_power_w == 60


def test_parse_chip_temps_max_second_and_average():
    """temp_chip_c must be the hotter per-ASIC sensor, not the firmware's
    flat ``temp`` (which forge-os computes as the average)."""
    s = _parse()
    assert s.temp_chip_c == 54.0
    assert s.temp_chip_2_c == 54.0
    assert s.temp_avg_c == 52.5
    assert s.temp_vr_c == 48.0


def test_parse_single_populated_sensor():
    """An unpopulated second sensor (0/-1) must not poison the max nor
    surface as a bogus second reading or average."""
    s = _parse(chiptemp1=57.0, chiptemp2=0, temp=28.5)
    assert s.temp_chip_c == 57.0
    assert s.temp_chip_2_c is None
    assert s.temp_avg_c is None


def test_parse_without_chiptemps_falls_back_to_temp():
    """Defensive: a build that drops chiptempN still shows a chip temp
    via the parent's ``temp`` mapping."""
    info = _forge_info(temp=52.5)
    del info["chiptemp1"], info["chiptemp2"]
    s = BitForgeDriver("10.0.0.7")._parse(info)
    assert s.temp_chip_c == 52.5
    assert s.temp_chip_2_c is None


def test_parse_fan_duty_capital_spelling():
    s = _parse()
    assert s.fan_pct == 66
    assert s.fan_rpm == 4100


def test_parse_current_to_amps_and_zero_sentinel():
    s = _parse()
    assert s.current_a == 3.21
    assert _parse(current=0).current_a is None


def test_parse_difficulty_and_pools():
    s = _parse()
    assert s.best_difficulty == 3.46e6
    assert s.best_difficulty_alltime == 28100000
    assert s.accepted == 1234
    assert s.rejected == 5
    assert s.pool_url == "solo.atlaspool.io:4333"
    assert s.pool_url_fallback == "public-pool.io:4333"
    assert s.pool_active == "primary"
    assert [p.slot for p in s.pools] == ["primary", "fallback"]
    assert s.pools[0].active is True
    assert s.pools[1].active is False


def test_parse_fields_forge_os_does_not_expose():
    s = _parse()
    assert s.expected_hashrate_ths is None
    assert s.error_pct is None
    assert s.hw_errors is None


def test_parse_hashrate_spike_clamped_to_none():
    """After a resume the firmware's estimator spikes far above the
    theoretical max (freq x small_core_count x asic_count) and decays over
    minutes — a real BitForge resume was seen at ~9.5e8 GH/s. That transient
    is not a reading: the driver drops it (None) so it never reaches the DB,
    the fleet totals, the efficiency figure or the Guardian. The efficiency
    must go None too rather than being computed from a bogus hashrate."""
    s = _parse(hashRate=953109632.0)
    assert s.hashrate_ths is None
    assert s.efficiency_w_per_ths is None


def test_parse_hashrate_at_theoretical_is_kept():
    """A plausible reading near the theoretical max is untouched (the clamp
    only fires well above it, so it can't drop legitimate values). 636 MHz x
    2040 cores x 2 ASICs ~= 2.594 TH/s."""
    s = _parse(hashRate=2594.0, frequency=636)
    assert s.hashrate_ths == 2.594


# ---- _parse: real v1.0 factory-firmware payload --------------------


def test_parse_v10_real_payload():
    """End-to-end mapping of the captured v1.0 payload: lowercase
    ``fanspeed`` flows through the parent mapping, ``temp`` (the
    firmware average of chiptemp1/2 — 54.125 = avg(52.25, 56)) lands in
    temp_avg_c while temp_chip_c takes the hotter sensor, and the
    SI-string ``bestDiff`` parses."""
    s = BitForgeDriver("192.0.2.19")._parse(_forge_v10_info())
    assert s.family == "bitforge"
    assert s.fan_pct == 63
    assert s.fan_rpm == 3651
    assert s.temp_chip_c == 56.0
    assert s.temp_chip_2_c == 56.0
    assert s.temp_avg_c == 54.1
    assert s.temp_vr_c == 71
    assert s.current_a == 3.42
    assert s.hashrate_ths == 2.5924
    assert s.best_difficulty == 6.51e6
    assert s.best_difficulty_alltime == 6.51e6
    assert s.asic_count == 2
    assert s.pool_url == "192.0.2.25:2018"
    assert s.pool_url_fallback == "eusolo.ckpool.org:3333"
    assert s.pool_active == "primary"


# ---- fan control: PATCH spellings across firmware generations ------


def test_set_fan_speed_sends_all_dialects():
    """v1.0 reads lowercase ``fanspeed``; v1.5+ reads ``fanSpeed`` /
    ``manualFanSpeed`` and ignores lowercase. The payload must carry
    every spelling so one call works on any firmware."""
    drv = BitForgeDriver("10.0.0.7")
    with patch.object(BitForgeDriver, "_patch_system", AsyncMock(return_value=True)) as ps:
        ok = asyncio.run(drv.set_fan_speed(150))
    assert ok is True
    payload = ps.await_args.args[0]
    assert payload == {
        "autofanspeed": 0,
        "fanspeed": 100,
        "fanSpeed": 100,
        "manualFanSpeed": 100,
    }


# ---- discovery -----------------------------------------------------


def test_pretty_bitforge_model():
    assert _pretty_bitforge_model("BITFORGE_NANO") == "BitForge Nano"
    assert _pretty_bitforge_model("BITFORGE-MAX") == "BitForge Max"
    assert _pretty_bitforge_model("") == "BitForge"


def _identify(info: dict, asic: dict) -> dict | None:
    """Run discovery._identify_bitaxe against canned API payloads."""
    sample = BitForgeDriver("10.0.0.7")._parse(info)
    sample.raw = info
    with patch.object(discovery.BitaxeDriver, "poll", AsyncMock(return_value=sample)), \
         patch.object(discovery.BitaxeDriver, "fetch_asic_info", AsyncMock(return_value=asic)):
        return asyncio.run(discovery._identify_bitaxe("10.0.0.7"))


def test_identify_bitforge_by_device_model():
    asic = {
        "ASICModel": "BM1370",
        "deviceModel": "BITFORGE_NANO",
        "asicCount": 2,
        "smallCoreCount": 2040,
    }
    info = _identify(_forge_info(), asic)
    assert info is not None
    assert info["family"] == "bitforge"
    assert info["model"] == "BitForge Nano"
    assert info["name"] == "BitForge"
    assert info["mac"] == "AA:BB:CC:11:22:33"


def test_identify_bitforge_wins_over_nerd_heuristics():
    """Ordering: a future forge-os build that adds ``fanCount: 2`` (the
    Nano IS dual-fan) must not trip the NerdOctaxe multi-fan fallback."""
    asic = {"deviceModel": "BITFORGE_NANO"}
    info = _identify(_forge_info(fanCount=2), asic)
    assert info is not None
    assert info["family"] == "bitforge"


def test_identify_bitforge_dialect_fallback_without_device_model():
    """No /api/system/asic reply: the chiptemp1 key (unique to
    forge-os) still classifies the board, and 2x BM1370 names it."""
    info = _identify(_forge_info(), {})
    assert info is not None
    assert info["family"] == "bitforge"
    assert info["model"] == "BitForge Nano"


def test_identify_bitforge_v10_no_asic_endpoint():
    """The shipping factory firmware: /api/system/asic does not exist
    (fetch_asic_info returns {}), fanspeed is lowercase — detection
    must ride on chiptemp1 alone and still name the board."""
    info = _identify(_forge_v10_info(), {})
    assert info is not None
    assert info["family"] == "bitforge"
    assert info["model"] == "BitForge Nano"
    assert info["name"] == "BitForge"
    assert info["mac"] == "AA:BB:CC:00:11:22"


def test_identify_stock_bitaxe_unaffected():
    """Regression: a stock AxeOS Gamma (lowercase ``fanspeed``, single
    ``temp`` sensor) keeps classifying as plain bitaxe."""
    stock = {
        "hashRate": 1150.0,
        "power": 17.5,
        "temp": 55.0,
        "fanspeed": 100,
        "fanrpm": 5200,
        "ASICModel": "BM1370",
        "hostname": "bitaxe-gamma",
        "macAddr": "11:22:33:44:55:66",
        "stratumURL": "public-pool.io",
        "stratumPort": 21496,
        "stratumUser": "bc1qabc.gamma",
        "uptimeSeconds": 120,
    }
    info = _identify(stock, {"deviceModel": "Gamma"})
    assert info is not None
    assert info["family"] == "bitaxe"
    assert info["model"] == "Gamma"


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
