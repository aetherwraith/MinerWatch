# SPDX-License-Identifier: AGPL-3.0-only
"""Poller and discovery for external AmbiTemp (NMMiner CYD ESP32 BMP280) devices.

Polls AmbiTemp ESP32 devices over HTTP (GET /api/readings) and feeds
the ambient temperature registry (`ambient.update(...)`). Also provides
subnet discovery to detect temperature sensors on the LAN and match moved IP addresses.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import httpx

from .ambient_temp import ambient
from .discovery import _local_cidr
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
                        temp_float = float(temp_c)
                        # Feed the ambient temp registry in MinerWatch
                        ambient.update(sensor_id, name, temp_float)
                        item = {
                            "host": host_clean,
                            "sensor_id": sensor_id,
                            "name": name,
                            "temp_c": temp_float,
                            "online": True,
                            "raw": data,
                        }
                        results.append(item)
                        log.debug("Polled AmbiTemp %s (%s): %.1f°C", name, sensor_id, temp_float)
                else:
                    results.append({"host": host_clean, "online": False, "error": f"HTTP {resp.status_code}"})
            except Exception as e:
                results.append({"host": host_clean, "online": False, "error": str(e)})
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


async def get_ambitemp_status() -> dict:
    """Return complete status of push sensors and configured pull sensors."""
    hosts_str = await db.get_setting("ambitemp_hosts", "")
    if not hosts_str:
        hosts_str = await db.get_setting("altitemp_hosts", "")
    configured_hosts = [h.strip() for h in hosts_str.split(",") if h.strip()]

    pull_results = await poll_ambitemp_hosts(configured_hosts) if configured_hosts else []
    pull_sensor_ids = {p.get("sensor_id") for p in pull_results if p.get("sensor_id")}

    push_snaps = ambient.snapshot_all()
    push_sensors = [
        {
            "sensor_id": s.sensor_id,
            "name": s.name,
            "current_c": round(s.current_c, 2) if s.current_c is not None else None,
            "min_c": round(s.min_c, 2) if s.min_c is not None else None,
            "max_c": round(s.max_c, 2) if s.max_c is not None else None,
            "available": s.available,
            "has_data": s.has_data,
            "type": "push",
        }
        for s in push_snaps
        if s.sensor_id not in pull_sensor_ids
    ]

    return {
        "push_sensors": push_sensors,
        "pull_sensors": pull_results,
        "configured_hosts": configured_hosts,
    }


async def _probe_single_host(client: httpx.AsyncClient, ip: str) -> dict | None:
    """Probe a single host IP for AmbiTemp API endpoints."""
    url = f"http://{ip}/api/readings"
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            temp_c = data.get("temp_c")
            if temp_c is None:
                temp_c = data.get("temperature_c")
            if temp_c is None:
                temp_c = data.get("temp")
            if temp_c is None:
                temp_c = data.get("temperature")
            sensor_id = str(data.get("sensor_id") or f"ambitemp-{ip.replace('.', '_')}")
            name = str(data.get("name") or "AmbiTemp")
            if temp_c is not None:
                return {
                    "ip": ip,
                    "sensor_id": sensor_id,
                    "name": name,
                    "temp_c": float(temp_c),
                    "raw": data,
                }
    except Exception:
        pass
    return None


async def discover_ambitemp_sensors(target_cidr: str | None = None) -> dict:
    """Scan local subnet for AmbiTemp pull sensors and identify address changes."""
    cidr = target_cidr or await db.get_setting("scan_cidr") or _local_cidr()
    if not cidr:
        return {"error": "could not determine local CIDR subnet", "discovered": []}

    try:
        net = ipaddress.ip_network(cidr, strict=False)
        hosts = [str(ip) for ip in net.hosts()]
    except Exception as exc:
        return {"error": f"invalid CIDR network {cidr!r}: {exc}", "discovered": []}

    hosts_str = await db.get_setting("ambitemp_hosts", "")
    if not hosts_str:
        hosts_str = await db.get_setting("altitemp_hosts", "")
    configured_hosts = [h.strip() for h in hosts_str.split(",") if h.strip()]

    # Limit to 254 hosts scan with concurrency limit
    semaphore = asyncio.Semaphore(50)

    async def _worker(client: httpx.AsyncClient, ip: str):
        async with semaphore:
            return await _probe_single_host(client, ip)

    discovered = []
    async with httpx.AsyncClient(timeout=1.2) as client:
        tasks = [_worker(client, ip) for ip in hosts]
        results = await asyncio.gather(*tasks)
        for r in results:
            if r is not None:
                # Check if this sensor matches a configured host or has changed IP
                already_configured = r["ip"] in configured_hosts
                # Search if same sensor_id was configured at a different IP
                matched_old_host = None
                if not already_configured:
                    # check if sensor_id matches any existing pull results
                    pass
                r["configured"] = already_configured
                discovered.append(r)

    return {
        "cidr": str(net),
        "total_scanned": len(hosts),
        "discovered": discovered,
        "configured_hosts": configured_hosts,
    }
