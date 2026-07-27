# SPDX-License-Identifier: AGPL-3.0-only
"""Contract tests for the ambient ingest/read endpoints.

Exercises the ESP32-C3 firmware contract at the model + endpoint level
(no network), mirroring the repo's existing TestClient-free style:
``POST /api/ambient`` validation and echo, the multi-sensor
``GET /api/fleet/ambient_temp`` list, and the LAN auth-exemption.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from pydantic import ValidationError

from backend import (
    ambient_temp,
    auth,
)
from backend import main as main_mod
from backend.main import AmbientPayload, AmbientSensorAssignment

VALID = {"temp_c": 23.48, "name": "Ambiente", "sensor_id": "020000000001"}


def _fresh_registry() -> None:
    """Point the endpoints at a clean registry (state is process-global)."""
    main_mod.ambient = ambient_temp.AmbientRegistry()


# ---- AmbientPayload: the firmware contract ----

def test_valid_payload() -> None:
    p = AmbientPayload(**VALID)
    assert p.temp_c == 23.48
    assert p.name == "Ambiente"
    assert p.sensor_id == "020000000001"


def test_name_is_trimmed() -> None:
    p = AmbientPayload(temp_c=20.0, name="  Garage  ", sensor_id="020000000001")
    assert p.name == "Garage"


def test_name_with_surrounding_space_within_40_after_trim_ok() -> None:
    # 40 real chars plus padding: must pass because length is checked AFTER trim.
    p = AmbientPayload(temp_c=20.0, name="  " + "x" * 40 + "  ", sensor_id="020000000001")
    assert p.name == "x" * 40


@pytest.mark.parametrize(
    "bad",
    [
        {"temp_c": 20.0, "sensor_id": "020000000001"},                        # name missing
        {"temp_c": 20.0, "name": "   ", "sensor_id": "020000000001"},         # name blank
        {"temp_c": 20.0, "name": "x" * 41, "sensor_id": "020000000001"},      # name too long
        {"temp_c": 20.0, "name": "Ok"},                                       # sensor_id missing
        {"temp_c": 20.0, "name": "Ok", "sensor_id": "02000000001"},           # 11 chars
        {"temp_c": 20.0, "name": "Ok", "sensor_id": "0200000000012"},         # 13 chars
        {"temp_c": 20.0, "name": "Ok", "sensor_id": "020000ABCDEF"},          # uppercase
        {"temp_c": 20.0, "name": "Ok", "sensor_id": "02000000zz01"},          # non-hex
        {"temp_c": -50.1, "name": "Ok", "sensor_id": "020000000001"},         # below range
        {"temp_c": 125.1, "name": "Ok", "sensor_id": "020000000001"},         # above range
        {"temp_c": float("nan"), "name": "Ok", "sensor_id": "020000000001"},  # non-finite
        {"temp_c": float("inf"), "name": "Ok", "sensor_id": "020000000001"},  # non-finite
        {**VALID, "status": "online"},                                        # legacy field
        {**VALID, "unexpected": 1},                                           # unknown field
    ],
)
def test_invalid_payloads_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        AmbientPayload(**bad)


# ---- endpoints: echo, list, cold start ----

def test_post_echoes_name_and_sensor_id_with_ok_true() -> None:
    _fresh_registry()
    resp = asyncio.run(main_mod.api_ambient(AmbientPayload(**VALID)))
    assert resp["ok"] is True
    assert resp["has_data"] is True
    assert resp["name"] == "Ambiente"
    assert resp["sensor_id"] == "020000000001"
    assert resp["current_c"] == 23.48


def test_get_exposes_name_and_sensor_id() -> None:
    _fresh_registry()
    asyncio.run(main_mod.api_ambient(AmbientPayload(**VALID)))
    out = asyncio.run(main_mod.api_fleet_ambient_temp())
    assert list(out.keys()) == ["sensors"]
    assert len(out["sensors"]) == 1
    s = out["sensors"][0]
    assert s["name"] == "Ambiente"
    assert s["sensor_id"] == "020000000001"
    assert s["has_data"] is True


def test_cold_start_is_empty_list() -> None:
    _fresh_registry()
    out = asyncio.run(main_mod.api_fleet_ambient_temp())
    assert out == {"sensors": []}


def test_two_sensors_two_rows_sorted_by_name() -> None:
    _fresh_registry()
    asyncio.run(main_mod.api_ambient(
        AmbientPayload(temp_c=20.0, name="Kitchen", sensor_id="0000000000aa")))
    asyncio.run(main_mod.api_ambient(
        AmbientPayload(temp_c=30.0, name="Garage", sensor_id="0000000000bb")))
    out = asyncio.run(main_mod.api_fleet_ambient_temp())
    assert [s["name"] for s in out["sensors"]] == ["Garage", "Kitchen"]


# ---- /api/ambient stays LAN auth-exempt ----

def test_ambient_endpoint_is_auth_exempt() -> None:
    assert auth.public_paths("/api/ambient") is True


# ---- history endpoint resolves the primary sensor / short-circuits empty ----

def test_history_empty_when_no_sensors() -> None:
    # No live sensors -> primary is None -> empty series without hitting the DB.
    _fresh_registry()
    out = asyncio.run(main_mod.api_fleet_ambient_temp_history())
    assert out["points"] == []
    assert out["sensor_id"] is None


# ---- per-miner room assignment payload contract ----

def test_assignment_accepts_hex_and_null() -> None:
    assert AmbientSensorAssignment(sensor_id="0000000000aa").sensor_id == "0000000000aa"
    assert AmbientSensorAssignment(sensor_id=None).sensor_id is None
    assert AmbientSensorAssignment().sensor_id is None


def test_assignment_normalizes_name() -> None:
    assert AmbientSensorAssignment(sensor_id="0000000000aa", name="  Garage  ").name == "Garage"
    assert AmbientSensorAssignment(sensor_id="0000000000aa", name="   ").name is None
    assert AmbientSensorAssignment(sensor_id="0000000000aa", name="x" * 50).name == "x" * 40


@pytest.mark.parametrize(
    "bad",
    [
        {"sensor_id": "0000000000AA"},               # uppercase
        {"sensor_id": "0000000000a"},                # 11 chars
        {"sensor_id": "0000000000aaa"},              # 13 chars
        {"sensor_id": "00000000zz01"},               # non-hex
        {"sensor_id": "0000000000aa", "extra": 1},   # unknown field
    ],
)
def test_assignment_rejects_bad(bad: dict) -> None:
    with pytest.raises(ValidationError):
        AmbientSensorAssignment(**bad)
