# SPDX-License-Identifier: AGPL-3.0-only
"""Ambient temperature registry for external ESP32-C3 sensors.

Each sensor POSTs ``{temp_c, name, sensor_id}`` to ``/api/ambient`` every
~5 seconds. MinerWatch keeps one rolling holder *per sensor_id* (60s moving
average, session min/max, freshness-based availability) and exposes them as
a list so the dashboard shows one row per sensor::

    Garage  | 30°C | Min -12°C | Max 32°C
    Kitchen | 20°C | Min 10°C  | Max 25°C

Identity is the device-supplied ``sensor_id`` (a MAC-derived 12-hex string);
the display label is the user-set ``name``, re-sent on every POST — so
renaming a sensor updates its row within one publish interval, and the name
needs no persistence. A registry-wide cap plus stale eviction bound memory
because ``/api/ambient`` is LAN auth-exempt and anyone on the network could
otherwise mint unlimited sensor ids.

Per-sensor semantics (unchanged from the original single-sensor relay):
  * current  — mean of the values seen in the last ``WINDOW_S`` seconds;
  * min/max  — extremes of the *real* values received this session;
  * available — true only if a valid value arrived within ``AVAIL_S`` seconds.
               When false the row shows "-" for the current value but keeps
               min/max. Availability is freshness-only: an offline sensor
               stops POSTing, so its reading goes stale on its own.

A sensor silent for longer than ``EVICT_S`` drops off the list entirely
(its row disappears) so a permanently-unplugged sensor does not linger.

No I/O here — ``POST /api/ambient`` feeds ``update()`` and the panel feed /
dashboard read ``snapshot_all()`` / ``primary_snapshot()``. Pure and
unit-testable: the clock is injectable, and a restart simply re-seeds the
registry within ~5s per live sensor.
"""
from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace

WINDOW_S = 60.0          # moving-average window for the current value
AVAIL_S = 20.0           # data older than this -> current "unavailable" ("-")
EVICT_S = 300.0          # silent longer than this -> the row drops off the list
VALID_MIN_C = -50.0      # sanity bounds; values outside are ignored
VALID_MAX_C = 125.0
MAX_SENSORS = 32         # registry cap (bounds memory on a LAN-open endpoint)


@dataclass
class AmbientSnapshot:
    current_c: float | None      # None when unavailable (stale / offline)
    min_c: float | None
    max_c: float | None
    available: bool
    has_data: bool               # have we ever received a valid value?
    name: str | None = None      # user-set label, re-sent on every POST
    sensor_id: str | None = None  # device identity; set by the registry


class AmbientTemp:
    """Rolling state for ONE sensor.

    The averaging / min-max / freshness logic is identical to the original
    single-sensor relay; the only addition is carrying the last valid
    ``name`` so a snapshot can label its row.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._samples: deque[tuple[float, float]] = deque()  # (ts, value)
        self._min: float | None = None
        self._max: float | None = None
        self._last_seen: float = 0.0
        self._name: str | None = None

    def update(self, value: float, name: str | None = None) -> bool:
        """Record a reading. Returns False (and stores nothing) if rejected.

        Validation here is a defensive duplicate of the API-layer contract:
        the holder must stay correct even when driven directly (tests, future
        callers). ``name`` is stored only alongside an accepted sample, which
        keeps the "has_data implies name" invariant true.
        """
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(v):
            return False
        if not (VALID_MIN_C <= v <= VALID_MAX_C):
            return False
        now = self._clock()
        self._samples.append((now, v))
        self._last_seen = now
        self._min = v if self._min is None else min(self._min, v)
        self._max = v if self._max is None else max(self._max, v)
        if name is not None:
            self._name = name
        return True

    def is_empty(self) -> bool:
        """True before any valid sample — used to avoid leaking empty holders."""
        return self._min is None and self._last_seen == 0.0

    def last_seen(self) -> float:
        return self._last_seen

    def _prune(self, now: float) -> None:
        cutoff = now - WINDOW_S
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def snapshot(self) -> AmbientSnapshot:
        now = self._clock()
        self._prune(now)
        available = self._last_seen > 0 and (now - self._last_seen) <= AVAIL_S
        if available and self._samples:
            current = sum(v for _, v in self._samples) / len(self._samples)
        else:
            current = None
        return AmbientSnapshot(
            current_c=current,
            min_c=self._min,
            max_c=self._max,
            available=available,
            has_data=self._min is not None,
            name=self._name,
        )


class AmbientRegistry:
    """All ambient sensors, keyed by the device-supplied ``sensor_id``.

    MinerWatch runs a single app process, so a module-level instance is the
    natural shared state — same lifetime as ``poller.last_results``.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        max_sensors: int = MAX_SENSORS,
        evict_s: float = EVICT_S,
    ) -> None:
        self._clock = clock
        self._max = max_sensors
        self._evict_s = evict_s
        self._sensors: dict[str, AmbientTemp] = {}

    def _evict_stale(self, now: float) -> None:
        dead = [
            sid
            for sid, h in self._sensors.items()
            if h.last_seen() > 0 and (now - h.last_seen()) > self._evict_s
        ]
        for sid in dead:
            del self._sensors[sid]

    def update(self, sensor_id: str, name: str | None, temp_c: float) -> bool:
        """Upsert one reading for ``sensor_id``. Returns True if recorded.

        A brand-new id is registered only if there is room under the cap; a
        full registry rejects newcomers (returns False) rather than evicting a
        live sensor, which keeps memory bounded on the LAN-open endpoint. A
        new holder whose first sample is invalid is removed again so a bad
        publisher cannot leave empty rows behind.
        """
        now = self._clock()
        self._evict_stale(now)
        holder = self._sensors.get(sensor_id)
        if holder is None:
            if len(self._sensors) >= self._max:
                return False
            holder = AmbientTemp(clock=self._clock)
            self._sensors[sensor_id] = holder
        ok = holder.update(temp_c, name)
        if not ok and holder.is_empty():
            del self._sensors[sensor_id]
        return ok

    def sensor_snapshot(self, sensor_id: str) -> AmbientSnapshot | None:
        """Snapshot for a single sensor (e.g. to echo back in the POST reply)."""
        holder = self._sensors.get(sensor_id)
        if holder is None:
            return None
        return replace(holder.snapshot(), sensor_id=sensor_id)

    def snapshot_all(self) -> list[AmbientSnapshot]:
        """One snapshot per live sensor, ordered for a stable dashboard list.

        Sorted by ``(name, sensor_id)`` so rows keep a deterministic position
        across the 5s poll instead of jumping as publishers race.
        """
        now = self._clock()
        self._evict_stale(now)
        snaps = [
            replace(holder.snapshot(), sensor_id=sid)
            for sid, holder in self._sensors.items()
        ]
        snaps.sort(key=lambda s: ((s.name or ""), s.sensor_id or ""))
        return snaps

    def primary_snapshot(self) -> AmbientSnapshot:
        """A single representative reading for the wall panel / history line.

        The first still-live sensor in insertion order — typically the one in
        use before more were added. An empty registry yields a has_data=False
        snapshot, so the panel/history simply show nothing. This is the
        interim single-value bridge until the panel itself goes multi-sensor.
        """
        now = self._clock()
        self._evict_stale(now)
        for sid, holder in self._sensors.items():
            return replace(holder.snapshot(), sensor_id=sid)
        return AmbientSnapshot(None, None, None, False, False, None, None)


# Process-wide ambient holder fed by ``POST /api/ambient`` (HTTP push from
# external sensors) and read by the panel feed / dashboard. Pure in-memory: a
# restart re-seeds it within ~5s per live sensor.
ambient = AmbientRegistry()
