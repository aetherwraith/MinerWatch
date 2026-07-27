"""Network-difficulty lookups for solo-mining odds across coins.

A miner only reports the network difficulty of the coin it is *currently*
mining (the stratum ``networkDifficulty`` field). To let the Analytics
"Solo Chance" widget compare BTC vs BCH — same fleet hashrate, different
network difficulty, different odds — we fetch each coin's current network
difficulty from a public explorer (Blockchair) and cache it in memory with
a short TTL so we don't hammer the API on every poll.

Both BTC and BCH are SHA-256, so the same hashrate applies to either; only
the difficulty (and therefore the odds) changes.

Design notes
------------
* Failures are soft: on any error we fall back to the last known value if
  we have one, otherwise return ``None``. Callers treat ``None`` exactly
  like "no difficulty available" and simply omit the prediction — the same
  graceful path used when a miner doesn't report a difficulty.
* Difficulty retargets are slow (BTC ~2 weeks; BCH adjusts per block but in
  small steps), so a 15-minute cache is plenty fresh and very gentle on the
  upstream API.
"""

from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger("minerwatch.coin_difficulty")

# Blockchair "stats" endpoints expose ``data.difficulty`` for each chain.
# One source for both coins keeps the parsing uniform.
_ENDPOINTS: dict[str, str] = {
    "btc": "https://api.blockchair.com/bitcoin/stats",
    "bch": "https://api.blockchair.com/bitcoin-cash/stats",
}

_CACHE_TTL_SECONDS = 15 * 60

# coin -> (difficulty, fetched_at_epoch)
_cache: dict[str, tuple[float, float]] = {}


def supported_coins() -> tuple[str, ...]:
    """Coins we can resolve a network difficulty for."""
    return tuple(_ENDPOINTS.keys())


def _fresh(coin: str) -> float | None:
    """Return the cached difficulty if it's within the TTL, else None."""
    entry = _cache.get(coin)
    if not entry:
        return None
    value, ts = entry
    if (time.time() - ts) < _CACHE_TTL_SECONDS:
        return value
    return None


def _stale(coin: str) -> float | None:
    """Last known value regardless of age — used as a fallback when a
    refresh fails so a transient API hiccup doesn't blank the widget."""
    entry = _cache.get(coin)
    return entry[0] if entry else None


async def get_difficulty(coin: str) -> float | None:
    """Return the current network difficulty for ``coin`` ('btc' | 'bch').

    Returns ``None`` when the coin is unknown or the lookup fails with no
    cached value to fall back on.
    """
    coin = (coin or "").strip().lower()
    url = _ENDPOINTS.get(coin)
    if not url:
        return None

    cached = _fresh(coin)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(url, headers={"User-Agent": "MinerWatch"})
        if resp.status_code != 200:
            log.warning(
                "difficulty fetch for %s failed: HTTP %s", coin, resp.status_code
            )
            return _stale(coin)
        payload = resp.json()
        raw = (payload.get("data") or {}).get("difficulty")
        value = float(raw) if raw is not None else None
        if value is None or value <= 0:
            return _stale(coin)
        _cache[coin] = (value, time.time())
        return value
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        log.warning("difficulty fetch for %s errored: %s", coin, exc)
        return _stale(coin)


def cached_difficulty(coin: str) -> float | None:
    """Return the cached difficulty for ``coin`` without any network call.

    A hot, non-blocking read for callers that must never stall on the
    upstream API — notably the 1 Hz ``/api/halo`` endpoint. Returns the
    fresh cached value, else the last known (stale) value, else ``None``.
    Populating the cache is left to :func:`get_difficulty`, which the
    Analytics "Solo Chance" widget already calls on its own schedule.
    """
    coin = (coin or "").strip().lower()
    return _fresh(coin) or _stale(coin)
