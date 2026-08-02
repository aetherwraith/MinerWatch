# SPDX-License-Identifier: AGPL-3.0-only
"""System, health, versioning, and update routes."""
from __future__ import annotations

from dataclasses import asdict
import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from backend import system_info, umbrel_widgets, updater, whatsnew

log = logging.getLogger("minerwatch.routers.system")
router = APIRouter(tags=["system"])


@router.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "version": updater.read_version()}


@router.get("/api/version")
async def api_version() -> dict[str, Any]:
    return {
        "version": updater.read_version(),
        "system": updater.system_summary(),
        "container": updater.in_container(),
    }


@router.get("/api/whatsnew")
async def api_whatsnew() -> dict[str, Any]:
    return whatsnew.get_whatsnew()


@router.get("/api/update/check")
async def api_update_check(force: bool = False) -> dict[str, Any]:
    result = await updater.check_for_update(force=force)
    return asdict(result)


@router.post("/api/update/install")
async def api_update_install() -> dict[str, Any]:
    if updater.in_container():
        raise HTTPException(
            status_code=409,
            detail=(
                "In-app updates are disabled under Docker/Umbrel because the "
                "container image is immutable. Update with "
                "`docker compose pull && docker compose up -d`."
            ),
        )
    return await updater.install_update()
