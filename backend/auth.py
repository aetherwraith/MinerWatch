# SPDX-License-Identifier: AGPL-3.0-only
"""Optional auth: bearer token. Disabled by default.

When enabled, every request must carry ``Authorization: Bearer <password>``
or the ``mw_token=<password>`` cookie (handy for the frontend).
"""
from __future__ import annotations

import hmac
import time as _time
from threading import Lock

from fastapi import HTTPException, Request

from .config import get_config


def get_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    cookie_token = request.cookies.get("mw_token")
    return cookie_token or None


def require_auth(request: Request) -> None:
    cfg = get_config()
    if not cfg.auth.enabled:
        return
    expected = (cfg.auth.password or "").strip()
    if not expected:
        # Fail-closed: auth.enabled=True but no password configured.
        # Returning 200 here (the previous behaviour) silently bypassed
        # authentication, which is the opposite of what the operator
        # asked for. We now refuse every protected request.
        #
        # Recovery if you locked yourself out:
        #   1) edit config.yaml and set `auth.enabled: false`, OR
        #   2) `sqlite3 data/minerwatch.db
        #       "UPDATE settings SET value='false' WHERE key='auth.enabled';"`
        # then restart the app.
        raise HTTPException(
            status_code=401,
            detail="Authentication is enabled but no password is configured",
        )
    provided = get_token(request) or ""
    # Constant-time comparison: ``!=`` short-circuits on the first byte
    # that differs, which on a fast LAN can leak the password one byte at
    # a time via response-time analysis. ``hmac.compare_digest`` always
    # walks the full length so the timing is independent of how many
    # leading bytes match.
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Login rate-limit
# ---------------------------------------------------------------------------
# A very small per-IP lockout to slow down brute-force attempts on
# ``/api/auth/login``. State lives in this module only — it resets on every
# process restart, which is acceptable for a home-LAN service and avoids
# the cost (and the data-leak surface) of a persistent counter.
#
# The thresholds are conservative on purpose: a user who legitimately
# fat-fingers the password 5 times in a row gets a 60s pause, not a
# 30-minute one. If you want stricter behaviour, bump
# ``LOGIN_LOCKOUT_SECONDS`` — the rest stays the same.

LOGIN_FAIL_THRESHOLD = 5
LOGIN_LOCKOUT_SECONDS = 60

# IP -> (consecutive_failures, lock_until_ts_or_0)
_login_state: dict[str, tuple[int, float]] = {}
_login_state_lock = Lock()


def login_lockout_remaining(ip: str) -> float:
    """Seconds the given IP must still wait before retrying login.

    Returns 0 when the IP isn't currently locked out.
    """
    with _login_state_lock:
        entry = _login_state.get(ip)
        if not entry:
            return 0.0
        _, lock_until = entry
        return max(0.0, lock_until - _time.time())


def record_login_failure(ip: str) -> float:
    """Bump the failure counter for ``ip``.

    Returns the lockout remaining in seconds — 0 means "not yet locked",
    a positive number means "you just tripped the threshold and are now
    locked for this many seconds".
    """
    with _login_state_lock:
        now = _time.time()
        count, lock_until = _login_state.get(ip, (0, 0.0))
        # If the previous lock has already expired, reset and start over.
        if lock_until and lock_until <= now:
            count = 0
            lock_until = 0.0
        count += 1
        if count >= LOGIN_FAIL_THRESHOLD:
            lock_until = now + LOGIN_LOCKOUT_SECONDS
        _login_state[ip] = (count, lock_until)
        return max(0.0, lock_until - now)


def clear_login_failures(ip: str) -> None:
    """Reset the per-IP counter — called on every successful login."""
    with _login_state_lock:
        _login_state.pop(ip, None)


def public_paths(path: str) -> bool:
    """Paths that stay public even when auth is enabled.

    Two families belong here:

      1. The pieces of the auth flow itself — ``/login`` (HTML page),
         ``/api/auth/login`` (POST endpoint), ``/api/auth/status``
         (used by the SPA to decide whether to redirect).

      2. The static assets that make up the React frontend. These are
         the JS/CSS bundles, the service worker, the favicons. They
         are not "data" — they're the UI source code itself, identical
         for every visitor. If we protect them, an unauthenticated user
         hitting ``/login`` gets the HTML shell but every ``<script>``
         the shell references comes back as 401, the bundle never
         starts, and the result is a blank page on which the user can
         never log in. That's exactly the "iPad blank screen, can't
         even log in" symptom we hit before adding ``/assets/`` here.

    The actual sensitive endpoints (``/api/miners``, ``/api/settings``,
    ``/api/system/*`` and friends) stay protected because they don't
    match any prefix below.
    """
    public = (
        "/login",
        "/api/auth/login",
        "/api/auth/status",
        # Public version + update-check so the login page and the
        # sidebar can show the running version and the "update
        # available" badge before the user signs in. The actual
        # /api/update/install POST stays protected — it's destructive
        # and falls through to require_auth like every other write.
        "/api/version",
        "/api/update/check",
        # /api/health backs the Docker healthcheck: compose probes it
        # with a bare urlopen and no session, so with auth enabled the
        # probe got 401 and the container sat permanently unhealthy.
        # It exposes the same status + version /api/version already does.
        "/api/health",
        # umbrelOS desktop widgets: umbreld polls these without a
        # session cookie, so they must stay public. Read-only GETs
        # exposing only coarse fleet numbers (hashrate, online count,
        # best share, temps) — no settings, no control surface. Anyone
        # on the LAN can already reach the login page; this adds the
        # same numbers the Umbrel desktop shows.
        "/api/widgets/",
        # External read-only fleet display: a device that polls /api/halo
        # ~1×/s without a session cookie. Same posture as the umbrel
        # widgets above — a read-only GET exposing only coarse fleet
        # numbers (hashrate, miner count, best/last share), no settings
        # and no control surface.
        "/api/halo",
        # External ESPHome panel ("Monolith"): polls /api/panel ~1×/s without a
        # session cookie — same read-only posture as /api/halo (coarse fleet
        # numbers, no control surface). /api/ambient is the one write here: an
        # external sensor POSTs a plain Celsius reading for the panel's temp
        # row. LAN-trust by design — the worst case is a bogus number on a
        # display; it touches no settings and controls no miner.
        "/api/panel",
        "/api/ambient",
        "/api/ambitemp",
        "/api/altitemp",
        "/sw.js",
        "/assets/",
        "/static/",
        "/favicon.ico",
        "/favicon.svg",
    )
    return any(path == p or path.startswith(p) for p in public)
