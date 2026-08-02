# SPDX-License-Identifier: AGPL-3.0-only
"""Subnet auto-discovery and miner probing routes."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend import db
from backend.discovery import discover_and_register, scan_network

log = logging.getLogger("minerwatch.routers.discovery")
router = APIRouter(tags=["discovery"])


class DiscoveryPayload(BaseModel):
    cidr: str | None = None


@router.post("/api/discovery/scan")
async def api_scan(payload: DiscoveryPayload | None = None) -> dict[str, Any]:
    cidr = payload.cidr if payload else None
    found = await scan_network(cidr=cidr)
    for info in found:
        await db.upsert_miner(info)
    return {"found": found}


@router.post("/api/discovery/auto")
async def api_discovery_auto() -> dict[str, Any]:
    found = await discover_and_register()
    return {"registered": len(found), "miners": found}
