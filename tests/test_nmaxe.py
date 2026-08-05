# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the NMAxe driver, discovery and live-share parsing.

NMAxe is an AxeOS fork with a fully *nested* /api/system/info, controls
under /api/setting/*, no MAC and no /api/system/asic. These tests pin:

  * the nested field mapping in NmaxeDriver._parse(),
  * the fan-only control surface (PATCH /api/setting/preference) and the
    deliberately narrow capability flags,
  * discovery via GET /probe (model "NM…"), incl. the regression that an
    "NMQAxe++" must NOT be mis-claimed as nerdoctaxe by the "qaxe" heuristic,
  * the NMAxe live-share WS dialect (ws://<ip>/ws, "₿ |x|share|pool|net|").

Fixtures are the real payloads captured from an NMAxe BM1366 fw v3.0.21
(see NOTES.md). Runs under pytest, or standalone:
``python tests/test_nmaxe.py``.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from unittest.mock import AsyncMock, patch

# Make the repo root importable whether invoked via pytest or directly.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend import discovery
from backend.log_streamer import LogStreamer, MinerStream
from backend.miners import DRIVERS, get_driver
from backend.miners.base import MinerSample
from backend.miners.nmaxe import NmaxeDriver


def _nmaxe_info(**overrides):
    """Real NMAxe (BM1366, fw v3.0.21) /api/system/info — nested schema."""
    data = {
        "power": {"power": 23.51316071, "vbus": 11370, "ibus": 2068},
        "temps": {"vcore": 66.59999847, "asic": 56.88000107},
        "asic": {
            "count": 1,
            "model": "BM1366",
            "vcoreReq": 1350,
            "vcoreReal": 1296,
            "freqReq": 675,
            "smallCoreCnt": 894,
        },
        "miner": {
            "state": "running",
            "paused": False,
            "pauseReason": "",
            "hashRate": 629.164987,
            "bestDiffEver": "474.7M",
            "bestDiffSession": "2.874M",
            "networkDiff": "234.5M",
            "poolDiff": "2.049K",
            "lastDiff": "5.789K",
            "blkhits": 0,
            "sAccepted": 1464,
            "sRejected": 36,
            "uptimeSeconds": 17604,
        },
        "identity": {
            "fwVersion": "v3.0.21",
            "hwModel": "NMAxe",
            "displayName": "NMAxe",
            "hostName": "NMAxe_6b784",
            "ssid": "example-wifi",
            "rssi": -71,
        },
        "stratum": {
            "url": "stratum+tcp://digi.hmpool.io:3334",
            "user": "bc1qxyz.worker1",
            "pwd": "x",
        },
        "fans": [{"id": 0, "speed": 0, "rpm": 2420}],
    }
    data.update(overrides)
    return data


def _parse(**overrides):
    return NmaxeDriver("10.0.0.9")._parse(_nmaxe_info(**overrides))


# ---- registry ------------------------------------------------------


def test_family_registered():
    assert DRIVERS["nmaxe"] is NmaxeDriver
    assert get_driver("NMAxe") is NmaxeDriver


def test_minersample_has_last_share_diff_default_none():
    assert MinerSample(family="x", host="h").last_share_diff is None


# ---- _parse: nested NMAxe field dialect ----------------------------


def test_parse_core_fields_and_family():
    s = _parse()
    assert s.family == "nmaxe"
    assert s.online is True
    assert s.mac is None
    assert s.model == "NMAxe"
    assert s.chip_model == "BM1366"
    assert s.firmware_version == "v3.0.21"
    assert s.hostname == "NMAxe_6b784"
    assert s.hashrate_ths == 0.6292
    assert s.power_w == 23.51316071
    assert s.asic_count == 1
    assert s.small_core_count == 894
    assert s.uptime_s == 17604


def test_parse_thermal_and_voltage():
    s = _parse()
    assert round(s.temp_chip_c, 2) == 56.88
    assert round(s.temp_vr_c, 2) == 66.60
    assert s.voltage_set_mv == 1350
    assert s.voltage_mv == 1296
    assert s.frequency_mhz == 675
    assert s.input_voltage_mv == 11370
    assert s.current_a == 2.068


def test_parse_shares_and_difficulties():
    s = _parse()
    assert s.accepted == 1464
    assert s.rejected == 36
    assert round(s.best_difficulty) == 2_874_000
    assert round(s.best_difficulty_alltime) == 474_700_000
    assert round(s.network_difficulty) == 234_500_000
    # B-base for the Halo: last submitted share's difficulty from the poll.
    assert round(s.last_share_diff) == 5_789


def test_parse_pause_state_and_pool():
    s = _parse()
    assert s.mining_paused is False
    assert s.pool_url == "digi.hmpool.io:3334"
    assert s.worker == "bc1qxyz.worker1"
    assert len(s.pools) == 1
    assert s.pools[0].slot == "primary"
    assert s.pools[0].active is True
    assert s.pools[0].url == "digi.hmpool.io:3334"


def test_parse_efficiency():
    s = _parse()
    # 23.513 W / 0.6292 TH/s ~= 37.37 W/TH
    assert s.efficiency_w_per_ths == round(23.51316071 / 0.6292, 2)


def test_parse_single_fan():
    s = _parse()
    assert s.fan_rpm == 2420
    assert s.fan_pct == 0
    assert s.fan_rpm_2 is None
    assert s.fan_pct_2 is None


def test_parse_nmqaxe_second_fan():
    """NMQAxe++ exposes a second (Vcore) fan as fans[1]."""
    s = _parse(fans=[{"id": 0, "speed": 60, "rpm": 3600}, {"id": 1, "speed": 80, "rpm": 4200}])
    assert s.fan_rpm == 3600
    assert s.fan_pct == 60
    assert s.fan_rpm_2 == 4200
    assert s.fan_pct_2 == 80


def test_parse_paused_unknown_when_absent():
    info = _nmaxe_info()
    del info["miner"]["paused"]
    s = NmaxeDriver("10.0.0.9")._parse(info)
    assert s.mining_paused is None


# ---- capabilities --------------------------------------------------


def test_capabilities_fan_and_restart_only():
    assert NmaxeDriver.can_set_fan is True
    assert NmaxeDriver.can_restart is True
    assert NmaxeDriver.can_set_frequency is False
    assert NmaxeDriver.can_set_voltage is False
    assert NmaxeDriver.can_set_workmode is False
    assert NmaxeDriver.can_pause is False
    assert NmaxeDriver.can_shutdown is False
    assert NmaxeDriver.can_set_pool is False


# ---- fan control: PATCH /api/setting/preference --------------------


def test_set_fan_speed_clamped_and_payload():
    drv = NmaxeDriver("10.0.0.9")
    with patch.object(NmaxeDriver, "_patch_preference", AsyncMock(return_value=True)) as pp:
        ok = asyncio.run(drv.set_fan_speed(150))
    assert ok is True
    assert pp.await_args.args[0] == {"fans": [{"id": 0, "auto": False, "speed": 100}]}


def test_set_auto_fan_payload():
    drv = NmaxeDriver("10.0.0.9")
    with patch.object(NmaxeDriver, "_patch_preference", AsyncMock(return_value=True)) as pp:
        ok = asyncio.run(drv.set_auto_fan(True))
    assert ok is True
    assert pp.await_args.args[0] == {"fans": [{"id": 0, "auto": True}]}


# ---- discovery: /probe fingerprint ---------------------------------


def _probe(model: str):
    return {"model": model, "hostname": "NMAxe_6b784", "ver": "v3.0.21"}


def test_identify_nmaxe_by_probe():
    with patch.object(discovery.NmaxeDriver, "fetch_probe", AsyncMock(return_value=_probe("NMAxe"))):
        info = asyncio.run(discovery._identify_nmaxe("10.0.0.9"))
    assert info is not None
    assert info["family"] == "nmaxe"
    assert info["model"] == "NMAxe"
    assert info["mac"] is None
    assert info["name"] == "NMAxe_6b784"
    assert info["port"] == discovery.PORT_BITAXE


def test_identify_nmqaxe_not_nerd():
    """Regression: "NMQAxe++" contains "qaxe" but must classify as nmaxe."""
    with patch.object(discovery.NmaxeDriver, "fetch_probe", AsyncMock(return_value=_probe("NMQAxe++"))):
        info = asyncio.run(discovery._identify_nmaxe("10.0.0.9"))
    assert info is not None
    assert info["family"] == "nmaxe"


def test_identify_nmaxe_absent_without_probe():
    """Stock AxeOS / NerdQAxe have no /probe → fetch_probe {} → no match."""
    with patch.object(discovery.NmaxeDriver, "fetch_probe", AsyncMock(return_value={})):
        info = asyncio.run(discovery._identify_nmaxe("10.0.0.9"))
    assert info is None


def test_identify_from_ports_runs_nmaxe_first():
    """_identify_from_ports must try NMAxe before the Bitaxe path so an
    NMAxe never reaches _identify_bitaxe (which would mislabel NMQAxe++)."""
    with patch.object(discovery.NmaxeDriver, "fetch_probe", AsyncMock(return_value=_probe("NMAxe"))), \
         patch.object(discovery, "_identify_bitaxe", AsyncMock(return_value={"family": "bitaxe"})):
        info = asyncio.run(discovery._identify_from_ports("10.0.0.9", [discovery.PORT_BITAXE]))
    assert info is not None
    assert info["family"] == "nmaxe"


# ---- live-share WS dialect -----------------------------------------


def test_ws_url_path_per_family():
    ls = LogStreamer()
    assert ls._ws_url("host", 80, "nmaxe") == "ws://host/ws"
    assert ls._ws_url("host", 80, "bitaxe") == "ws://host/api/ws"
    assert ls._ws_url("host", 8080, "nmaxe") == "ws://host:8080/ws"


def test_is_supported_includes_nmaxe():
    ls = LogStreamer()
    assert ls.is_supported("nmaxe") is True
    assert ls.is_supported("bitaxe") is True
    assert ls.is_supported("canaan") is False


def test_nmaxe_share_line_parsed():
    """The captured ₿-pipe share line yields one submitted ShareEvent with
    the exact share difficulty and the pool target."""
    ls = LogStreamer()
    stream = MinerStream(miner_id=1, host="10.0.0.9", port=80, family="nmaxe")
    line = "\x1b[32m₿ |32.00 |6.588K|2.049K|234.5394M|\x1b[0m"
    asyncio.run(ls._handle_nmaxe_line(stream, line))
    assert len(stream.buffer) == 1
    ev = stream.buffer[-1]
    assert round(ev.share_diff) == 6_588
    assert round(ev.pool_target) == 2_049
    assert ev.submitted is True
    assert stream.submitted_total == 1


def test_nmaxe_v31_share_line_with_timestamp_parsed():
    """NMAxe v3.1.01 includes a timestamp [hh:mm:ss.mmm] and ASIC info before the first pipe."""
    ls = LogStreamer()
    stream = MinerStream(miner_id=1, host="10.0.0.9", port=80, family="nmaxe")
    line = "\x1b[32m₿ [20:26:25.244] | 1/1  |4.006K|885.0 |126.2315T|\x1b[0m\r\n"
    asyncio.run(ls._handle_nmaxe_line(stream, line))
    assert len(stream.buffer) == 1
    ev = stream.buffer[-1]
    assert round(ev.share_diff) == 4_006
    assert round(ev.pool_target) == 885
    assert ev.submitted is True
    assert stream.submitted_total == 1


def test_nmaxe_non_share_line_ignored():
    ls = LogStreamer()
    stream = MinerStream(miner_id=1, host="10.0.0.9", port=80, family="nmaxe")
    asyncio.run(ls._handle_nmaxe_line(stream, "\x1b[0mI (123) wifi: connected\x1b[0m"))
    assert len(stream.buffer) == 0


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
