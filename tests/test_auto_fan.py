# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the AutoFanController and set_fan_speed API driver calls.

Verifies that:
1. AutoFanController invokes set_fan_speed with the computed PID percentage when fan_mode == 'minerwatch'.
2. AutoFanController skips set_fan_speed when fan_mode == 'firmware'.
3. BitaxeDriver.set_fan_speed sends {"autofanspeed": 0, "fanspeed": pct} via PATCH /api/system.
4. NmaxeDriver.set_fan_speed sends {"fans": [{"id": 0, "auto": False, "speed": pct}]} via PATCH /api/setting/preference.
5. CanaanDriver.set_fan_speed sends ascset|0,fan-spd,pct.

Runs under pytest, or standalone: ``python tests/test_auto_fan.py``.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from unittest.mock import AsyncMock, Mock, patch

# Make the repo root importable whether invoked via pytest or directly.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend.auto_control import AutoFanController, _states, _watchdog_states
from backend.miners.base import MinerSample
from backend.miners.bitaxe import BitaxeDriver
from backend.miners.canaan import CanaanDriver
from backend.miners.nmaxe import NmaxeDriver


def test_bitaxe_driver_set_fan_speed_payload():
    drv = BitaxeDriver("10.0.0.50")
    with patch.object(drv, "_patch_system", new_callable=AsyncMock) as mock_patch:
        mock_patch.return_value = True
        res = asyncio.run(drv.set_fan_speed(75))
        assert res is True
        mock_patch.assert_called_once_with(
            {"autofanspeed": 0, "fanspeed": 75, "fanspeed2": 75, "manualFanSpeed": 75}
        )


def test_bitaxe_driver_set_auto_fan_payload():
    drv = BitaxeDriver("10.0.0.50")
    with patch.object(drv, "_patch_system", new_callable=AsyncMock) as mock_patch:
        mock_patch.return_value = True
        res = asyncio.run(drv.set_auto_fan(True, target_temp_c=65.0))
        assert res is True
        mock_patch.assert_called_once_with({"autofanspeed": 1, "tempTarget": 65, "pidTargetTemp": 65})


def test_nmaxe_driver_set_fan_speed_payload():
    drv = NmaxeDriver("10.0.0.51")
    with patch.object(drv, "_patch_preference", new_callable=AsyncMock) as mock_patch:
        mock_patch.return_value = True
        res = asyncio.run(drv.set_fan_speed(70))
        assert res is True
        mock_patch.assert_called_once_with(
            {"fans": [{"id": 0, "auto": False, "speed": 70}]}
        )


def test_nmaxe_driver_set_auto_fan_payload():
    drv = NmaxeDriver("10.0.0.51")
    with patch.object(drv, "_patch_preference", new_callable=AsyncMock) as mock_patch:
        mock_patch.return_value = True
        res = asyncio.run(drv.set_auto_fan(True, target_temp_c=62.0))
        assert res is True
        mock_patch.assert_called_once_with(
            {"fans": [{"id": 0, "auto": True, "target": 62}]}
        )


def test_canaan_driver_set_fan_speed_payload():
    drv = CanaanDriver("10.0.0.52")
    mock_client = Mock()
    mock_client.call = AsyncMock(return_value={"STATUS": [{"STATUS": "S"}], "BYT": "0,fan-spd,80"})
    with patch.object(drv, "_client", return_value=mock_client):
        res = asyncio.run(drv.set_fan_speed(80))
        assert res is True
        mock_client.call.assert_called_once_with("ascset", "0,fan-spd,80")


def test_autofan_controller_invokes_driver_in_minerwatch_mode():
    controller = AutoFanController()
    miner = {
        "id": 10,
        "name": "TestBitaxe",
        "family": "bitaxe",
        "fan_mode": "minerwatch",
        "auto_target_c": 60.0,
    }
    sample = MinerSample(
        family="bitaxe",
        host="10.0.0.50",
        online=True,
        temp_chip_c=70.0,  # Hotter than 60 target -> PID will request fan increase
        fan_pct=50,
    )
    _states.clear()
    _watchdog_states.clear()

    mock_drv = AsyncMock()
    mock_drv.can_set_fan = True
    mock_drv.set_fan_speed.return_value = True

    with patch("backend.auto_control.driver_for_record", return_value=mock_drv):
        asyncio.run(controller._adjust_one(miner, sample))
        mock_drv.set_fan_speed.assert_called_once()
        commanded_speed = mock_drv.set_fan_speed.call_args[0][0]
        # Since temp (70°C) > target (60°C), fan speed must increase above 50%
        assert commanded_speed > 50


def test_autofan_controller_skips_driver_in_firmware_mode():
    controller = AutoFanController()
    miner = {
        "id": 11,
        "name": "TestBitaxeFW",
        "family": "bitaxe",
        "fan_mode": "firmware",
    }
    sample = MinerSample(
        family="bitaxe",
        host="10.0.0.50",
        online=True,
        temp_chip_c=65.0,
        fan_pct=50,
    )
    _states.clear()
    _watchdog_states.clear()

    mock_drv = AsyncMock()
    mock_drv.can_set_fan = True

    with patch("backend.auto_control.driver_for_record", return_value=mock_drv), \
         patch("backend.auto_control.db.list_miners", new_callable=AsyncMock) as mock_list, \
         patch("backend.auto_control.get_config") as mock_cfg:
        mock_list.return_value = [miner]
        mock_cfg.return_value.polling.request_timeout = 5.0
        # In _tick, fan_mode == 'firmware' causes _adjust_one to be skipped
        asyncio.run(controller._tick({11: sample}))
        mock_drv.set_fan_speed.assert_not_called()


def test_autofan_controller_initializes_at_least_at_firmware_speed():
    controller = AutoFanController()
    miner = {
        "id": 12,
        "name": "TestInitialSpeed",
        "family": "bitaxe",
        "fan_mode": "minerwatch",
        "auto_target_c": 60.0,
    }
    # Miner chip is at 60°C target, and firmware was running fans at 80%
    sample = MinerSample(
        family="bitaxe",
        host="10.0.0.50",
        online=True,
        temp_chip_c=60.0,
        fan_pct=80,
    )
    _states.clear()

    mock_drv = AsyncMock()
    mock_drv.can_set_fan = True
    mock_drv.set_fan_speed.return_value = True

    with patch("backend.auto_control.driver_for_record", return_value=mock_drv):
        asyncio.run(controller._adjust_one(miner, sample))
        # Initial baseline is seeded at 80% (what firmware was running it at)
        assert _states[12].last_commanded_pct >= 80

    # On next tick with hot chip temp (75°C > 60°C target), fan speed ramps UP from 80%
    sample_hot = MinerSample(
        family="bitaxe",
        host="10.0.0.50",
        online=True,
        temp_chip_c=75.0,
        fan_pct=80,
    )
    with patch("backend.auto_control.driver_for_record", return_value=mock_drv):
        asyncio.run(controller._adjust_one(miner, sample_hot))
        mock_drv.set_fan_speed.assert_called()
        commanded_speed = mock_drv.set_fan_speed.call_args[0][0]
        assert commanded_speed > 80


if __name__ == "__main__":
    fns = {k: v for k, v in dict(globals()).items() if k.startswith("test_")}
    for name, fn in fns.items():
        fn()
        print(f"ok  {name}")
    print(f"\n{len(fns)} auto fan verification tests passed")
