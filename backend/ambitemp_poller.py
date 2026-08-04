# SPDX-License-Identifier: AGPL-3.0-only
"""Poller for external AmbiTemp (NMMiner CYD ESP32 BMP280) devices.

Polls AmbiTemp ESP32 devices over HTTP (GET /api/readings) and feeds
the ambient temperature registry (`ambient.update(...)`).
"""
from __future__ import annotations

import logging
import httpx

from .ambient_temp import ambient
from . import db

log = logging.getLogger("minerwatch.ambitemp")


async def poll_ambitemp_hosts(hosts: list[str]) -> list[dict]:
    """Poll a list of AmbiTemp device IPs / hostnames via HTTP GET /api/readings."""
    if not hosts:
        return []

    results = []
    async with httpx.AsyncClient(timeout=3.0) as client:
        for host in hosts:
            host_clean = host.strip()
            if not host_clean:
                continue
            
            url = f"http://{host_clean}/api/readings" if not host_clean.startswith("http://") and not host_clean.startswith("https://") else f"{host_clean}/api/readings"
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    sensor_id = str(data.get("sensor_id") or f"ambitemp-{host_clean.replace('.', '_')}")
                    name = str(data.get("name") or "AmbiTemp")
                    
                    # Support temp_c, temperature_c, temp, or temperature
                    temp_c = data.get("temp_c")
                    if temp_c is None:
                        temp_c = data.get("temperature_c")
                    if temp_c is None:
                        temp_c = data.get("temp")
                    if temp_c is None:
                        temp_c = data.get("temperature")

                    if temp_c is not None:
                        # Feed the ambient temp registry in MinerWatch
                        ambient.update(sensor_id, name, float(temp_c))
                        results.append(data)
                        log.debug("Polled AmbiTemp %s (%s): %.1f°C", name, sensor_id, float(temp_c))
            except Exception as e:
                log.debug("Failed to poll AmbiTemp at %s: %s", host_clean, e)

    return results


async def poll_ambitemp_cycle() -> list[dict]:
    """Read configured hosts from DB setting `ambitemp_hosts` (or legacy `altitemp_hosts`) and poll them."""
    try:
        hosts_str = await db.get_setting("ambitemp_hosts", "")
        if not hosts_str:
            hosts_str = await db.get_setting("altitemp_hosts", "")
        if not hosts_str:
            return []
        hosts = [h.strip() for h in hosts_str.split(",") if h.strip()]
        return await poll_ambitemp_hosts(hosts)
    except Exception:
        log.debug("AmbiTemp poll cycle failed", exc_info=True)
        return []
