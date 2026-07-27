# SPDX-License-Identifier: AGPL-3.0-only
"""Live per-share streamer for AxeOS miners (Bitaxe / NerdQAxe / Titan).

The REST poller in :mod:`backend.poller` only sees *aggregates*: the
firmware's running ``bestDiff``, the share counters, a smoothed
hashrate. It can never show the individual shares as they happen.

AxeOS exposes its runtime system log over a WebSocket at
``ws://<ip>/api/ws``. Every nonce the ASIC returns is logged as an
``asic_result`` line that carries the share difficulty and the current
pool target, e.g. (ANSI colour codes stripped)::

    I (446925478) asic_result: ID: 69fd…, ASIC nr: 0, ver: 22816000 \
        Nonce 639505B4 diff 3035.4 of 1497.

``diff 3035.4`` is the difficulty of *this* result; ``of 1497.`` is the
pool/stratum target in force at that moment (ckpool vardiff). A result
is *submitted* to the pool when ``diff >= target``; the firmware then
logs a ``stratum_api: tx`` line and, a few ms later, a
``stratum_task: message result accepted`` (or ``rejected``).

This module opens one persistent WebSocket per enabled AxeOS miner,
parses that stream, and:

* keeps the last ``RING_BUFFER`` share events in memory per miner
  (for the live chart),
* fans every new event out to any number of SSE subscribers,
* persists *notable* shares (>= :data:`NOTABLE_THRESHOLD`) to the
  ``notable_shares`` table so the "near-block Hall of Fame" survives a
  restart.

Synthetic fallback: firmware that compiles the per-share line out
(forge-os v1.5+ keeps it at DEBUG) still logs the pool verdicts at
INFO, so each verdict is turned into a synthetic submitted-share event
plotted at the pool target (see :meth:`LogStreamer._synthesize_share`).
The poller feeds the REST-only bits in: ``stratumDiff`` seeds the
target (:meth:`LogStreamer.note_pool_target`) and a new
``bestSessionDiff`` upgrades the latest synthetic dot to its exact
difficulty + feeds the Hall of Fame (:meth:`LogStreamer.note_session_best`).

Privacy: the ``stratum_api: tx`` lines contain the user's payout
address and worker name. We parse-and-discard — only the numeric
difficulty/target ever leave this module. Raw stratum lines are never
buffered or written to disk.

Scope: AxeOS only. cgminer-family miners (Canaan/Braiins/LuxOS) expose
a JSON API on :4028 with no equivalent per-share log stream, so they
are simply skipped by the reconcile loop.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from . import db

log = logging.getLogger("minerwatch.log_streamer")

# `websockets` ships transitively with uvicorn[standard]; import it
# defensively so a stripped-down environment degrades to "feature off"
# instead of crashing the whole app at import time.
try:
    import websockets  # type: ignore
    from websockets.exceptions import WebSocketException  # type: ignore

    _WEBSOCKETS_AVAILABLE = True
except Exception:  # noqa: BLE001  pragma: no cover
    websockets = None  # type: ignore
    WebSocketException = Exception  # type: ignore
    _WEBSOCKETS_AVAILABLE = False


# Families that speak the AxeOS REST/WS protocol. `bitaxe` covers both
# the original Bitaxe and the NerdQAxe (they share the family tag in the
# DB); `nerdoctaxe` is the multi-ASIC fork, also AxeOS-derived.
# `bitforge` (forge-os) exposes the same /api/ws endpoint. Its v1.0
# factory firmware logs the per-share "diff X of Y" line at INFO like
# upstream, so live shares work in full. v1.5 demoted that line (and the
# register reads) to DEBUG, and the stock build compiles DEBUG out
# entirely — no per-share line can ever reach the WS. For those builds
# we fall back to SYNTHETIC share events: the pool verdict lines
# ("message result accepted/rejected") are still logged at INFO, so each
# one marks exactly one submitted share. We plot it at the pool target
# (the true difficulty is unknown but >= target by definition), track
# the target from the vardiff lines still at INFO plus the REST
# `stratumDiff`, and upgrade the difficulty retroactively when the REST
# poller observes a new `bestSessionDiff` (see note_session_best). What
# is genuinely lost on such firmware is only the below-target cloud.
# The fallback engages per-stream and automatically: a real asic_result
# line always switches the stream back to the full-fidelity path.
AXEOS_FAMILIES = {"bitaxe", "nerdoctaxe", "bitforge"}
# NMAxe is also AxeOS-derived but speaks a *different* log dialect: the WS
# is at ``ws://<ip>/ws`` (not ``/api/ws``) and a submitted share is logged
# as a compact pipe line "₿ |x|<shareDiff>|<poolDiff>|<netDiff>|" (ANSI-
# wrapped), not the ESP-IDF "I (ms) asic_result: ... diff X of Y" line. It
# therefore gets its own parse branch keyed on the per-stream family — see
# :meth:`LogStreamer._handle_nmaxe_line`.
NMAXE_FAMILIES = {"nmaxe"}
# Every family we open a live per-share WS stream for.
STREAM_FAMILIES = AXEOS_FAMILIES | NMAXE_FAMILIES

# Per-miner ring buffer for the live chart. Retention is primarily
# TIME-based (RING_BUFFER_SECONDS): a pure count cap spans far less
# wall-clock time for a high-throughput multi-ASIC board (e.g. the
# SupraHex, which logs results several times faster than a single-ASIC
# Gamma) than for a slow one, so a fast miner's older shares fell out of
# the snapshot and "dropped off" the left of the chart while slow miners
# still scrolled the full window. RING_BUFFER is the count backstop
# (a hard memory bound) layered on top of the time window.
RING_BUFFER = 20000
RING_BUFFER_SECONDS = 15 * 60  # ≥ the longest frontend chart range (10m) + margin

# A share is "notable" — worth persisting to the Hall of Fame — when its
# difficulty clears this floor. On a solo pool the vardiff target is
# tiny (~1.5k), so almost every submitted share would qualify; the floor
# keeps the table to genuine near-misses. Tunable via the settings DB
# key ``streaming.notable_threshold`` if a user wants it lower/higher.
NOTABLE_THRESHOLD = 1_000_000.0

# Keep at most this many Hall-of-Fame rows per miner (top-by-difficulty).
NOTABLE_KEEP_PER_MINER = 500

# Reconcile the set of streaming miners against the DB at this cadence.
RECONCILE_INTERVAL_S = 15

# Per-subscriber queue bound. A slow SSE client (e.g. a backgrounded
# phone) must never make the producer grow without limit: once the queue
# is full we drop the oldest event for that subscriber only.
SUBSCRIBER_QUEUE_MAX = 1000

# ---- parsing -------------------------------------------------------------
# Lines arrive wrapped in ESP-IDF ANSI colour codes, e.g.
# "\x1b[0;32mI (123) tag: msg\x1b[0m". Strip those first.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# "<LEVEL> (<ms_since_boot>) <tag>: <message>"
_LOG = re.compile(r"^([IWE]) \((\d+)\) ([^:]+): (.*)$")
# Share-line difficulty, four firmware dialects (all verified against the
# vendor sources, not docs):
#   axeOS 2.13:      "... diff 3035.4 of 1497."         target printed %ld (int)
#   axeOS 2.14+:     "... diff 900000.0 of 1.04858e+06." target printed %g, so a
#                    large vardiff comes out in SCIENTIFIC notation
#   forge-os v1.5+:  "... diff 3035.4 of 1497.00."      target printed %.2f
#                    (stock builds keep the line at DEBUG so it normally never
#                    reaches the WS, but custom builds may re-enable it at INFO)
#   NerdQAxe(++):    "... diff 1394.8/3065/241M"        "<share>/<target>/<best>"
# The number token accepts integers, decimals, a leading dot, an optional SI
# suffix (k/M/G/T/…) AND scientific notation. The scientific branch is the
# axeOS-2.14 fix: the old token stopped at the "e", so "1.04858e+06" was read
# as "1.04858" and every share on a high-vardiff 2.14 miner was mis-classified
# as submitted. The token still owns at most one dot-run, so the sentence-final
# period is never swallowed.
_DIFF_TOKEN = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+|[kKMGTPE])?"
_SHARE = re.compile(rf"\bdiff\s+({_DIFF_TOKEN})\s*(?:of|/)\s*({_DIFF_TOKEN})")

# Pool/vardiff target lines that survive at INFO on forge-os v1.5+ — the
# only in-stream target source when the per-share lines are compiled out:
#   stratum_task: "Set stratum difficulty: 8192.00"
#   asic_task:    "New pool difficulty 8192.00"
_TARGET = re.compile(
    r"\b(?:Set stratum difficulty:|New pool difficulty)\s+([0-9]+(?:\.[0-9]+)?)"
)

# NMAxe submitted-share line (fw v3.0.21, captured from a real unit):
#   "\x1b[32m₿ |32.00 |6.588K|2.049K|234.5394M|\x1b[0m"
# Fields after the ₿ marker are: <misc> | <shareDiff> | <poolDiff> | <netDiff>.
# We take the share difficulty (field 2) and the pool target (field 3); the
# leading field and the trailing net-diff are ignored. ANSI codes are stripped
# by _ANSI before matching. NOTE: derived from a single real sample — revisit
# if a future firmware reorders the fields.
_NMAXE_SHARE = re.compile(
    rf"₿\s*\|\s*[^|]*\|\s*({_DIFF_TOKEN})\s*\|\s*({_DIFF_TOKEN})\s*\|"
)

# How far back a REST-observed session-best may retroactively upgrade the
# most recent synthetic share's difficulty (see note_session_best). Wide
# enough to bridge one polling cycle plus a slow share cadence; narrow
# enough not to relabel an unrelated old dot.
AMEND_WINDOW_S = 90.0

_SI_SUFFIX = {"k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "P": 1e15, "E": 1e18}


def _parse_diff_token(tok: str) -> float:
    """Parse a difficulty token that may carry an SI suffix ("4.29G").

    A trailing period is stripped defensively: log lines end the diff
    clause with a sentence dot ("of 1497." / "of 1497.00.") and any
    future capture slip must not turn into a float() ValueError that
    silently drops the whole share line.
    """
    tok = tok.strip().rstrip(".")
    if tok and tok[-1] in _SI_SUFFIX:
        return float(tok[:-1]) * _SI_SUFFIX[tok[-1]]
    return float(tok)


@dataclass
class ShareEvent:
    """One ASIC result parsed off the log stream.

    ``ts`` is the wall-clock arrival time on the MinerWatch host, NOT the
    miner's log timestamp: the firmware logs milliseconds-since-boot,
    which resets on reboot and is useless for charting. ``uptime_ms`` is
    kept only for ordering/debugging.
    """

    seq: int
    miner_id: int
    ts: float
    uptime_ms: int
    share_diff: float
    pool_target: float
    submitted: bool
    accepted: bool | None = None
    # True for events synthesized from a verdict line (forge-os v1.5+,
    # where the per-share log line is compiled out): `share_diff` is the
    # pool target, i.e. a FLOOR for the real difficulty, not the real
    # value. Cleared again if note_session_best upgrades the event to
    # the REST-observed exact difficulty.
    estimated: bool = False
    # rowid of the persisted Hall-of-Fame row, if this share was notable.
    # Lets us back-fill `accepted` once the stratum result line arrives.
    _notable_rowid: int | None = None

    def to_public(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "diff": self.share_diff,
            "target": self.pool_target,
            "submitted": self.submitted,
            "accepted": self.accepted,
            "estimated": self.estimated,
        }


@dataclass
class MinerStream:
    """Per-miner streaming state."""

    miner_id: int
    host: str
    port: int
    # Drives the WS path and the parse dialect (see STREAM_FAMILIES).
    family: str = ""
    buffer: deque[ShareEvent] = field(default_factory=lambda: deque(maxlen=RING_BUFFER))
    # Submitted shares awaiting their accepted/rejected verdict, oldest
    # first. Bounded so an unmatched result line can't leak memory.
    pending: deque[ShareEvent] = field(default_factory=lambda: deque(maxlen=64))
    seq: int = 0
    current_target: float | None = None
    results_total: int = 0
    submitted_total: int = 0
    accepted_total: int = 0
    rejected_total: int = 0
    # True once a verdict had to be turned into a synthetic share (no
    # pending event to grade — the firmware logs no per-share lines).
    # Cleared by any real asic_result line, so a v1.0 board or a custom
    # build with DEBUG logs re-enabled gets the full-fidelity path back
    # automatically. Gates note_session_best so firmwares with a real
    # stream never get duplicate Hall-of-Fame rows.
    synthetic_mode: bool = False
    estimated_total: int = 0
    connected: bool = False
    last_event_ts: float | None = None
    started_at: float = field(default_factory=time.time)

    def stats(self) -> dict[str, Any]:
        return {
            "miner_id": self.miner_id,
            "connected": self.connected,
            "current_target": self.current_target,
            "results_total": self.results_total,
            "submitted_total": self.submitted_total,
            "accepted_total": self.accepted_total,
            "rejected_total": self.rejected_total,
            "synthetic": self.synthetic_mode,
            "estimated_total": self.estimated_total,
            "last_event_ts": self.last_event_ts,
            "buffered": len(self.buffer),
            "since": self.started_at,
        }


class LogStreamer:
    """Manages one WS task per AxeOS miner, plus the SSE pub/sub."""

    def __init__(self) -> None:
        self._streams: dict[int, MinerStream] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._subscribers: dict[int, set[asyncio.Queue]] = {}
        self._manager: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # ---- lifecycle ------------------------------------------------------

    async def start(self) -> None:
        if not _WEBSOCKETS_AVAILABLE:
            log.warning(
                "websockets library unavailable — live per-share streaming "
                "disabled. `pip install websockets` to enable it."
            )
            return
        if self._manager and not self._manager.done():
            return
        self._stop.clear()
        self._manager = asyncio.create_task(self._reconcile_loop(), name="mw-log-streamer")
        log.info("Log streamer started")

    async def stop(self) -> None:
        self._stop.set()
        for task in list(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        if self._manager:
            self._manager.cancel()
            try:
                await self._manager
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._manager = None
        log.info("Log streamer stopped")

    # ---- reconcile ------------------------------------------------------

    async def _reconcile_loop(self) -> None:
        """Keep the running WS tasks in sync with the enabled AxeOS miners."""
        while not self._stop.is_set():
            try:
                await self._reconcile_once()
            except Exception:
                log.exception("log-streamer reconcile error")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=RECONCILE_INTERVAL_S)
            except asyncio.TimeoutError:
                continue

    async def _reconcile_once(self) -> None:
        miners = await db.list_miners(only_enabled=True)
        wanted: dict[int, tuple[str, int, str]] = {}
        for m in miners:
            family = (m.get("family") or "").lower()
            if family not in STREAM_FAMILIES:
                continue
            mid = int(m["id"])
            host = m.get("host") or ""
            port = int(m.get("port") or 80)
            if host:
                wanted[mid] = (host, port, family)

        # Stop tasks for miners that vanished, got disabled, or moved host.
        for mid in list(self._tasks.keys()):
            task = self._tasks[mid]
            stream = self._streams.get(mid)
            moved = (
                stream is not None
                and mid in wanted
                and (stream.host, stream.port, stream.family) != wanted[mid]
            )
            if mid not in wanted or task.done() or moved:
                task.cancel()
                self._tasks.pop(mid, None)
                self._streams.pop(mid, None)

        # Start tasks for newly-wanted miners.
        for mid, (host, port, family) in wanted.items():
            if mid in self._tasks and not self._tasks[mid].done():
                continue
            stream = MinerStream(miner_id=mid, host=host, port=port, family=family)
            self._streams[mid] = stream
            self._tasks[mid] = asyncio.create_task(
                self._run_miner(stream), name=f"mw-stream-{mid}"
            )

    # ---- per-miner WS task ---------------------------------------------

    def _ws_url(self, host: str, port: int, family: str = "") -> str:
        # The log WS is on the HTTP port (80). NMAxe serves it at /ws; stock
        # AxeOS and the other forks use /api/ws. Only include an explicit
        # port when it's non-standard.
        path = "/ws" if family in NMAXE_FAMILIES else "/api/ws"
        if port and port != 80:
            return f"ws://{host}:{port}{path}"
        return f"ws://{host}{path}"

    async def _run_miner(self, stream: MinerStream) -> None:
        url = self._ws_url(stream.host, stream.port, stream.family)
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    url,
                    origin=f"http://{stream.host}",  # AxeOS validates Origin
                    ping_interval=20,
                    ping_timeout=20,
                    open_timeout=8,
                    close_timeout=4,
                    max_size=None,
                    max_queue=64,
                ) as ws:
                    stream.connected = True
                    backoff = 1.0
                    log.info("streaming %s (miner %s)", url, stream.miner_id)
                    async for message in ws:
                        if self._stop.is_set():
                            break
                        text = message if isinstance(message, str) else message.decode("utf-8", "replace")
                        # A frame can technically carry more than one line.
                        for line in text.splitlines():
                            await self._handle_line(stream, line)
            except asyncio.CancelledError:
                break
            except (WebSocketException, OSError, asyncio.TimeoutError) as exc:
                log.debug("stream %s dropped: %s", url, exc)
            except Exception:
                log.exception("unexpected stream error for %s", url)
            finally:
                stream.connected = False

            if self._stop.is_set():
                break
            # Reconnect with capped exponential backoff.
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 30.0)

    # ---- parsing + dispatch --------------------------------------------

    async def _handle_line(self, stream: MinerStream, line: str) -> None:
        # NMAxe speaks a different log dialect (₿-pipe share lines on /ws);
        # everything below is the ESP-IDF asic_result path of stock AxeOS.
        if stream.family in NMAXE_FAMILIES:
            await self._handle_nmaxe_line(stream, line)
            return
        clean = _ANSI.sub("", line).strip()
        if not clean:
            return
        m = _LOG.match(clean)
        if not m:
            return
        _level, ms_str, tag, msg = m.groups()
        tag = tag.strip()

        if tag == "asic_result":
            sm = _SHARE.search(msg)
            if not sm:
                return
            try:
                share_diff = _parse_diff_token(sm.group(1))
                pool_target = _parse_diff_token(sm.group(2))
            except ValueError:
                return
            try:
                uptime_ms = int(ms_str)
            except ValueError:
                uptime_ms = 0
            await self._on_result(stream, uptime_ms, share_diff, pool_target)
            return
        # Bitaxe logs the verdict under tag "stratum_task" (axeOS ≤2.13 and
        # forge-os); axeOS 2.14 renamed it to "stratum_v1_task"; NerdQAxe uses
        # "stratum task (Pri)" (space + pool marker). Match every dialect —
        # "stratum_v1_task" does NOT start with "stratum_task", so it must be
        # listed explicitly or 2.14 verdicts go ungraded.
        if tag.startswith(("stratum_task", "stratum_v1_task", "stratum task")):
            if "result accepted" in msg:
                self._on_verdict(stream, accepted=True)
                return
            if "result rejected" in msg:
                self._on_verdict(stream, accepted=False)
                return
        # Vardiff/pool-target lines ("Set stratum difficulty: 8192.00" on
        # stratum_task, "New pool difficulty 8192.00" on asic_task). They
        # keep current_target fresh even on firmware that logs no
        # per-share lines, where the target is the synthetic chart floor.
        if tag.startswith(("stratum_task", "stratum task", "asic_task")):
            tm = _TARGET.search(msg)
            if tm:
                try:
                    target = float(tm.group(1))
                except ValueError:
                    return
                if target > 0:
                    stream.current_target = target

    async def _handle_nmaxe_line(self, stream: MinerStream, line: str) -> None:
        """Parse an NMAxe submitted-share line into a :class:`ShareEvent`.

        NMAxe logs only *submitted* shares (the "₿" toast), each carrying
        the exact share difficulty and the pool target — so, unlike the
        forge-os synthetic path, we get the real difficulty (just no
        below-target cloud). This firmware emits no separate accept/reject
        verdict line, so events stay ungraded (``accepted=None``); that's
        fine for the live chart and for the Halo's share_seq/last_diff.
        """
        clean = _ANSI.sub("", line).strip()
        if "₿" not in clean:
            return
        m = _NMAXE_SHARE.search(clean)
        if not m:
            return
        try:
            share_diff = _parse_diff_token(m.group(1))
            pool_target = _parse_diff_token(m.group(2))
        except ValueError:
            return
        await self._on_result(stream, 0, share_diff, pool_target)

    async def _on_result(
        self, stream: MinerStream, uptime_ms: int, share_diff: float, pool_target: float
    ) -> None:
        # A real per-share line: this firmware logs at full fidelity, so
        # leave (or return to) the non-synthetic path.
        stream.synthetic_mode = False
        stream.seq += 1
        stream.results_total += 1
        stream.current_target = pool_target
        now = time.time()
        stream.last_event_ts = now
        submitted = share_diff >= pool_target
        ev = ShareEvent(
            seq=stream.seq,
            miner_id=stream.miner_id,
            ts=now,
            uptime_ms=uptime_ms,
            share_diff=share_diff,
            pool_target=pool_target,
            submitted=submitted,
        )
        stream.buffer.append(ev)
        self._prune_buffer(stream, now)
        if submitted:
            stream.submitted_total += 1
            stream.pending.append(ev)

        # Persist near-block-class shares so the Hall of Fame survives a
        # restart. Always submitted (diff >> target), so a verdict line
        # will follow and back-fill `accepted`.
        if share_diff >= NOTABLE_THRESHOLD:
            try:
                rowid = await db.insert_notable_share(
                    miner_id=stream.miner_id,
                    ts=int(now),
                    share_difficulty=share_diff,
                    pool_target=pool_target,
                    keep_per_miner=NOTABLE_KEEP_PER_MINER,
                )
                ev._notable_rowid = rowid
            except Exception:
                log.exception("failed to persist notable share for %s", stream.miner_id)

        self._publish(stream.miner_id, {"type": "share", "data": ev.to_public()})

    @staticmethod
    def _prune_buffer(stream: MinerStream, now: float) -> None:
        """Time-based retention on top of the deque's count cap.

        Drop events older than the chart window so a fast miner keeps the
        same time span as a slow one. Expired events are always at the
        front (ts ascending), so this is amortised O(1) per event.
        """
        cutoff = now - RING_BUFFER_SECONDS
        buf = stream.buffer
        while buf and buf[0].ts < cutoff:
            buf.popleft()

    def _synthesize_share(self, stream: MinerStream, accepted: bool) -> None:
        """Materialise a submitted share from its pool verdict alone.

        forge-os v1.5 stock builds compile the per-share ``asic_result``
        line out (demoted to DEBUG), so the only INFO-level trace a
        submitted share leaves in the log is the "message result
        accepted/rejected" verdict — exactly one verdict per submission.
        We synthesize the event at the pool target: the true difficulty
        is unknown but is >= target by definition of a submission. The
        same ``share`` + ``verdict`` SSE pair the full-fidelity path
        emits is published, so subscribers need no special casing;
        :meth:`note_session_best` may later upgrade the difficulty to
        the REST-observed exact value.
        """
        target = stream.current_target
        if target is None or target <= 0:
            # No target known yet (fresh stream: no vardiff line seen and
            # the REST seed hasn't arrived). Without a floor the dot has
            # no place on the chart — skip the event; the verdict was
            # still counted and the poller seeds the target within one
            # polling cycle.
            return
        stream.synthetic_mode = True
        stream.seq += 1
        stream.results_total += 1
        stream.submitted_total += 1
        stream.estimated_total += 1
        now = time.time()
        stream.last_event_ts = now
        ev = ShareEvent(
            seq=stream.seq,
            miner_id=stream.miner_id,
            ts=now,
            uptime_ms=0,
            share_diff=float(target),
            pool_target=float(target),
            submitted=True,
            estimated=True,
        )
        stream.buffer.append(ev)
        self._prune_buffer(stream, now)
        self._publish(stream.miner_id, {"type": "share", "data": ev.to_public()})
        # Publish the verdict as its own event, exactly like the real
        # path, so frontend stats counters keep adding up unchanged.
        ev.accepted = accepted
        self._publish(
            stream.miner_id,
            {"type": "verdict", "data": {"seq": ev.seq, "accepted": accepted}},
        )

    def _on_verdict(self, stream: MinerStream, accepted: bool) -> None:
        if accepted:
            stream.accepted_total += 1
        else:
            stream.rejected_total += 1
        if not stream.pending:
            # Nothing awaiting a grade. On firmware that logs no per-share
            # lines this is the normal case — the verdict IS the share.
            self._synthesize_share(stream, accepted)
            return
        ev = stream.pending.popleft()
        ev.accepted = accepted
        # Back-fill the persisted Hall-of-Fame row's verdict, if any.
        if ev._notable_rowid is not None:
            asyncio.create_task(
                self._update_notable_accepted(ev._notable_rowid, accepted)
            )
        self._publish(
            stream.miner_id,
            {"type": "verdict", "data": {"seq": ev.seq, "accepted": accepted}},
        )

    async def _update_notable_accepted(self, rowid: int, accepted: bool) -> None:
        try:
            await db.set_notable_share_accepted(rowid, accepted)
        except Exception:  # noqa: BLE001
            log.debug("could not update notable share %s verdict", rowid)

    # ---- pub/sub --------------------------------------------------------

    def _publish(self, miner_id: int, event: dict[str, Any]) -> None:
        subs = self._subscribers.get(miner_id)
        if not subs:
            return
        for q in list(subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: drop its oldest event to make room.
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:  # noqa: BLE001
                    pass

    def subscribe(self, miner_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAX)
        self._subscribers.setdefault(miner_id, set()).add(q)
        return q

    def unsubscribe(self, miner_id: int, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(miner_id)
        if subs:
            subs.discard(q)
            if not subs:
                self._subscribers.pop(miner_id, None)

    # ---- REST-side feeds (used by the poller) ---------------------------

    def note_pool_target(self, miner_id: int, target: Any) -> None:
        """Seed/refresh a stream's pool target from the REST poll.

        ``stratumDiff`` in ``/api/system/info`` carries the same value as
        the vardiff log lines. The REST seed matters right after a stream
        (re)connects to a firmware that logs no per-share lines: verdicts
        can arrive before any vardiff line is printed, and without a
        target they would have to be dropped for lack of a chart floor.
        """
        stream = self._streams.get(miner_id)
        if stream is None:
            return
        try:
            value = float(target) if target is not None else None
        except (TypeError, ValueError):
            return
        if value is not None and value > 0:
            stream.current_target = value

    async def note_session_best(
        self, miner_id: int, value: float, ts: int | None = None
    ) -> None:
        """Upgrade synthetic share data with a REST-observed session best.

        On firmware whose per-share lines are compiled out, the exact
        difficulty of a high share is visible only to the REST poller via
        ``bestSessionDiff``. When the poller records a NEW session best
        for a miner whose stream is running synthetic (verdict-derived)
        events, two things happen:

        * the most recent synthetic event inside :data:`AMEND_WINDOW_S`
          is upgraded from the target floor to the real difficulty, and
          an ``amend`` SSE event re-places the dot on live charts (on a
          vardiff'd solo pool shares are sparse, so "the most recent
          submission" is almost always the record-setter);
        * the share is persisted to the Hall of Fame when it clears
          :data:`NOTABLE_THRESHOLD`. This is a PARTIAL restore of that
          feature: only session-maximum shares leave a REST trace — a 2M
          share found while the session best already sits at 3M stays
          invisible.

        No-op for streams not in synthetic mode, so firmwares with a real
        per-share stream never get duplicate Hall-of-Fame rows.
        """
        stream = self._streams.get(miner_id)
        if stream is None or not stream.synthetic_mode:
            return
        try:
            diff = float(value)
        except (TypeError, ValueError):
            return
        if diff <= 0:
            return
        now = time.time()
        ev: ShareEvent | None = None
        for cand in reversed(stream.buffer):
            if cand.estimated and cand.submitted:
                ev = cand
                break
        if ev is not None and (now - ev.ts) <= AMEND_WINDOW_S and diff > ev.share_diff:
            ev.share_diff = diff
            ev.estimated = False
            self._publish(
                miner_id,
                {"type": "amend", "data": {"seq": ev.seq, "diff": diff, "estimated": False}},
            )
        else:
            ev = None
        if diff >= NOTABLE_THRESHOLD:
            try:
                rowid = await db.insert_notable_share(
                    miner_id=miner_id,
                    ts=int(ts or now),
                    share_difficulty=diff,
                    pool_target=stream.current_target,
                    keep_per_miner=NOTABLE_KEEP_PER_MINER,
                )
                # The amended event may already know the pool's verdict
                # (its synthetic verdict was published at creation time).
                if ev is not None and ev.accepted is not None:
                    await db.set_notable_share_accepted(rowid, ev.accepted)
            except Exception:
                log.exception("failed to persist notable share for %s", miner_id)

    # ---- read helpers (used by the API) --------------------------------

    def is_supported(self, family: str | None) -> bool:
        return (family or "").lower() in STREAM_FAMILIES

    def recent(self, miner_id: int, limit: int = RING_BUFFER) -> list[dict[str, Any]]:
        stream = self._streams.get(miner_id)
        if not stream:
            return []
        events = list(stream.buffer)
        if limit and limit < len(events):
            events = events[-limit:]
        return [e.to_public() for e in events]

    def stats(self, miner_id: int) -> dict[str, Any] | None:
        stream = self._streams.get(miner_id)
        return stream.stats() if stream else None


# Global instance (mirrors backend.poller.poller).
log_streamer = LogStreamer()
