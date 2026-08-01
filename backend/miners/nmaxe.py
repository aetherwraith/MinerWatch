# SPDX-License-Identifier: AGPL-3.0-only
"""Driver for the NMAxe family (NMAxe / NMAxeGamma / NMQAxe++).

NMAxe is an ESP32-S3 solo miner forked from ``bitaxeorg/ESP-Miner``, but
its REST surface was restructured, so it is a real sibling driver rather
than a thin :class:`BitaxeDriver` subclass — only ``restart()`` and the
HTTP plumbing are reused:

  * ``GET /api/system/info`` returns a *nested* object
    (``power`` / ``temps`` / ``asic`` / ``miner`` / ``identity`` /
    ``stratum`` / ``fans[]``), NOT the flat AxeOS keys the Bitaxe parser
    expects.
  * control moved under ``/api/setting/*`` (fan via
    ``PATCH /api/setting/preference``).
  * there is no MAC anywhere, no ``/api/system/asic``, and no
    pause/shutdown endpoint.

Schema verified against a real NMAxe (BM1366, fw v3.0.21) — see
``NOTES.md`` for the captured payloads. Official firmware + API docs:
https://github.com/NMminer1024/ESP-Miner-NMAxe (``docs/API.md``).

Capabilities are deliberately narrow (see ``NOTES.md``): fan control
(auto + manual duty) and restart only. Frequency/voltage, the Guardian
co-tuner, pause/shutdown and pool-repoint (donate) are all off — the
co-tuner excludes itself because it requires both
``can_set_voltage`` and ``can_set_frequency``.
"""
from __future__ import annotations

from typing import Any

import httpx

from .base import MinerSample, PoolSnapshot
from .base import parse_si_difficulty as _parse_si
from .bitaxe import BitaxeDriver, _opt_float, _opt_int


def _strip_scheme(url: str | None) -> str | None:
    """Drop a ``stratum+tcp://`` (or any) scheme prefix → bare ``host:port``."""
    if not url:
        return None
    if "://" in url:
        url = url.split("://", 1)[1]
    return url or None


class NmaxeDriver(BitaxeDriver):
    """NMAxe / NMAxeGamma / NMQAxe++ — nested AxeOS-fork REST surface.

    ``poll()`` is inherited from :class:`BitaxeDriver` (same
    ``GET /api/system/info`` URL); only ``_parse`` and the fan controls
    are overridden. The inherited frequency/voltage/pool/pause methods are
    never reached because the matching capability flags are False and
    ``main.py`` gates every control endpoint on them.
    """

    family = "nmaxe"
    DEFAULT_PORT = 80

    # Fan control (auto + manual) and restart only — see module docstring.
    can_set_fan = True
    can_set_frequency = False
    can_set_voltage = False
    can_set_workmode = False
    can_restart = True
    can_pause = False
    can_shutdown = False
    can_set_pool = False

    async def fetch_probe(self) -> dict[str, Any]:
        """GET ``/probe`` — lightweight identity (model/hostname/version).

        Used by discovery to fingerprint the family: stock AxeOS / NerdQAxe
        have no ``/probe`` endpoint, so a 200 whose ``model`` starts with
        "NM" is a reliable NMAxe marker. Best-effort: ``{}`` on any error.
        """
        if getattr(self, "_probe_cache", None) is not None:
            return getattr(self, "_probe_cache")
        url = f"{self._base_url()}/probe"
        try:
            cli = get_shared_client()
            resp = await cli.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                setattr(self, "_probe_cache", data)
                return data
        except (httpx.HTTPError, ValueError):
            return {}
        return {}

    async def probe(self) -> dict[str, Any]:
        """Alias for fetch_probe() to support probe() method call conventions."""
        return await self.fetch_probe()

    def _parse(self, data: dict[str, Any]) -> MinerSample:
        power = data.get("power") if isinstance(data.get("power"), dict) else {}
        temps = data.get("temps") if isinstance(data.get("temps"), dict) else {}
        asic = data.get("asic") if isinstance(data.get("asic"), dict) else {}
        miner = data.get("miner") if isinstance(data.get("miner"), dict) else {}
        identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
        stratum = data.get("stratum") if isinstance(data.get("stratum"), dict) else {}
        fans = data.get("fans") if isinstance(data.get("fans"), list) else []

        ghs = _opt_float(miner.get("hashRate"))
        hashrate_ths = round(ghs / 1000.0, 4) if ghs is not None else None

        power_w = _opt_float(power.get("power"))
        eff = None
        if hashrate_ths and power_w and hashrate_ths > 0:
            eff = round(power_w / hashrate_ths, 2)

        # PSU current: NMAxe reports input current in mA (`ibus`).
        ibus = _opt_float(power.get("ibus"))
        current_a = round(ibus / 1000.0, 3) if ibus is not None else None

        fan0 = fans[0] if len(fans) >= 1 and isinstance(fans[0], dict) else {}
        fan1 = fans[1] if len(fans) >= 2 and isinstance(fans[1], dict) else None

        pool_url = _strip_scheme(stratum.get("url"))
        worker = stratum.get("user") or None

        # `miner.paused` is a real bool on NMAxe → drives the Standby badge
        # and lets alerts skip a deliberately-stopped miner. (There is no
        # pause *command*, only this read — see capability flags.)
        paused = miner.get("paused")
        mining_paused = bool(paused) if isinstance(paused, bool) else None

        sample = MinerSample(
            family=self.family,
            host=self.host,
            online=True,
            mining_paused=mining_paused,
            mac=None,
            model=identity.get("hwModel") or identity.get("displayName"),
            chip_model=asic.get("model"),
            hostname=identity.get("hostName"),
            firmware_version=identity.get("fwVersion"),
            hashrate_ths=hashrate_ths,
            power_w=power_w,
            efficiency_w_per_ths=eff,
            temp_chip_c=_opt_float(temps.get("asic")),
            temp_vr_c=_opt_float(temps.get("vcore")),
            fan_rpm=_opt_int(fan0.get("rpm")),
            fan_pct=_opt_float(fan0.get("speed")),
            frequency_mhz=_opt_float(asic.get("freqReq")),
            voltage_mv=_opt_float(asic.get("vcoreReal")) or _opt_float(asic.get("vcoreReq")),
            voltage_set_mv=_opt_float(asic.get("vcoreReq")),
            asic_count=_opt_int(asic.get("count")),
            small_core_count=_opt_int(asic.get("smallCoreCnt")),
            input_voltage_mv=_opt_float(power.get("vbus")),
            current_a=current_a,
            uptime_s=_opt_int(miner.get("uptimeSeconds")),
            accepted=_opt_int(miner.get("sAccepted")),
            rejected=_opt_int(miner.get("sRejected")),
            best_difficulty=_parse_si(miner.get("bestDiffSession")),
            best_difficulty_alltime=_parse_si(miner.get("bestDiffEver")),
            network_difficulty=_parse_si(miner.get("networkDiff")),
            last_share_diff=_parse_si(miner.get("lastDiff")),
            pool_url=pool_url,
            worker=worker,
            raw=data,
        )

        # NMQAxe++ exposes a second (Vcore) fan as ``fans[1]``; single-fan
        # NMAxe / NMAxeGamma omit it, leaving these None.
        if fan1 is not None:
            sample.fan_rpm_2 = _opt_int(fan1.get("rpm"))
            sample.fan_pct_2 = _opt_float(fan1.get("speed"))

        # Single active-pool snapshot for the Pools page. NMAxe also has a
        # fallback slot, but only the *active* pool is in /api/system/info;
        # the full primary/fallback pair lives in /api/setting/mining and
        # would need a second request — left as a future enhancement.
        if pool_url:
            sample.pools = [
                PoolSnapshot(
                    url=pool_url,
                    user=worker,
                    accepted=sample.accepted,
                    rejected=sample.rejected,
                    active=True,
                    slot="primary",
                )
            ]
        return sample

    # ---- controls (fan only) -------------------------------------------

    async def _patch_preference(self, payload: dict[str, Any]) -> bool:
        url = f"{self._base_url()}/api/setting/preference"
        try:
            cli = get_shared_client()
            resp = await cli.patch(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPError:
            return False
        return True

    async def set_fan_speed(self, percent: int, percent2: int | None = None) -> bool:
        """Manual fan duty via ``PATCH /api/setting/preference``.

        ``auto:false`` switches the fan out of firmware auto mode; ``id:0``
        is the ASIC fan on NMAxe models (``id:1`` is the NMQAxe++ Vcore fan).
        """
        percent = max(0, min(100, int(percent)))
        fans = [{"id": 0, "auto": False, "speed": percent}]
        if percent2 is not None:
            p2 = max(0, min(100, int(percent2)))
            fans.append({"id": 1, "auto": False, "speed": p2})
        return await self._patch_preference({"fans": fans})

    async def set_auto_fan(self, enabled: bool, target_temp_c: float | None = None) -> bool:
        """Hand the ASIC fan back to the firmware's auto (target-temp) loop."""
        fan_obj: dict[str, Any] = {"id": 0, "auto": bool(enabled)}
        if enabled and target_temp_c is not None:
            fan_obj["target"] = int(round(target_temp_c))
        return await self._patch_preference({"fans": [fan_obj]})
