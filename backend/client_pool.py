# SPDX-License-Identifier: AGPL-3.0-only
"""Global HTTP connection pool manager using httpx.AsyncClient.

Reuses underlying TCP connections and HTTP/1.1 keep-alive across driver calls,
external API lookups, and background tasks.
"""
from __future__ import annotations

import httpx

_client: httpx.AsyncClient | None = None


def get_shared_client() -> httpx.AsyncClient:
    """Return a shared singleton httpx.AsyncClient instance."""
    global _client
    if _client is None or _client.is_closed:
        limits = httpx.Limits(max_keepalive_connections=50, max_connections=100, keepalive_expiry=30.0)
        _client = httpx.AsyncClient(limits=limits, timeout=10.0, follow_redirects=True)
    return _client


async def close_shared_client() -> None:
    """Close the shared client on application shutdown."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.close()
        _client = None
