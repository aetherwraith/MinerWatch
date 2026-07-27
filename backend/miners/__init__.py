# SPDX-License-Identifier: AGPL-3.0-only
"""Miner drivers.

Every driver inherits from :class:`base.MinerDriver` and implements
at least ``poll()``. The registry maps the family name (``bitaxe``,
``nerdoctaxe``, ``bitforge``, ``canaan``, ``braiins``, ``luxos``) to the
driver class.
"""
from __future__ import annotations

from typing import Type

from .base import MinerDriver, MinerSample
from .bitaxe import BitaxeDriver
from .bitforge import BitForgeDriver
from .braiins import BraiinsDriver
from .canaan import CanaanDriver
from .luxos import LuxosDriver
from .nerdoctaxe import NerdOctaxeDriver
from .nmaxe import NmaxeDriver

DRIVERS: dict[str, type[MinerDriver]] = {
    "bitaxe": BitaxeDriver,
    # NerdOctaxe shares the Bitaxe REST surface but adds dual-fan,
    # dual-pool and PSU-current readings — see nerdoctaxe.py.
    "nerdoctaxe": NerdOctaxeDriver,
    # BitForge (Nano): forge-os firmware, AxeOS-derived with a few
    # renamed fields (fanSpeed, chiptemp1/2) — see bitforge.py.
    "bitforge": BitForgeDriver,
    # NMAxe (NMAxe / NMAxeGamma / NMQAxe++): AxeOS fork with a fully
    # nested /api/system/info and /api/setting/* controls — see nmaxe.py.
    # Fan + restart only; no MAC (identity keyed on host).
    "nmaxe": NmaxeDriver,
    "canaan": CanaanDriver,
    "braiins": BraiinsDriver,
    "luxos": LuxosDriver,
}


def get_driver(family: str) -> type[MinerDriver]:
    family = (family or "").lower()
    if family not in DRIVERS:
        raise ValueError(f"Unknown miner family: {family!r}")
    return DRIVERS[family]


def driver_for_record(record: dict) -> MinerDriver:
    cls = get_driver(record["family"])
    return cls(
        host=record["host"],
        port=record.get("port"),
        timeout=record.get("timeout", 4),
    )


__all__ = [
    "DRIVERS",
    "BitForgeDriver",
    "BitaxeDriver",
    "BraiinsDriver",
    "CanaanDriver",
    "LuxosDriver",
    "MinerDriver",
    "MinerSample",
    "NerdOctaxeDriver",
    "NmaxeDriver",
    "driver_for_record",
    "get_driver",
]
