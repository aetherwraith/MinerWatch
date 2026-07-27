# SPDX-License-Identifier: AGPL-3.0-only
"""forge-os v1.5 compatibility batch.

The v1.0 → v1.5 firmware jump changed three things MinerWatch relied on:

* ``bestDiff`` became a full-precision number while ``bestSessionDiff``
  stayed an SI string quantized to 3 significant digits, so a freshly
  broken record arrived as two "different" values and fell into the
  silent-seed path — the "new best share" push never fired.
* the per-share ``asic_result`` log line was demoted to DEBUG (compiled
  out of stock builds) and its target format changed from ``of 1497.``
  to ``of 1497.00.`` — live shares went dark, and even re-enabled lines
  would have been dropped by the old greedy regex.
* ``stratumTLS`` / ``stratumCert`` appeared; pool repointing that
  ignores them can leave a TLS flag pointing at a plain-TCP pool.

Field data: a real BitForge Nano on v1.5-apfix2 reported
``bestDiff: 1882611`` with ``bestSessionDiff: "1.88M"`` — the record
that silently failed to notify. Those exact values are used below.

Runs under pytest, or standalone: ``python tests/test_forgeos_15.py``.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile
from unittest.mock import AsyncMock, patch

# Make the repo root importable whether invoked via pytest or directly.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend import db, discovery
from backend.donations import (
    donation_pool_config,
    donation_pool_config_fallback,
)
from backend.log_streamer import (
    _SHARE,
    LogStreamer,
    MinerStream,
    _parse_diff_token,
)
from backend.miners.base import PoolConfig, parse_si_difficulty
from backend.miners.bitaxe import BitaxeDriver
from backend.miners.bitforge import BitForgeDriver

_TMP = tempfile.TemporaryDirectory(prefix="mw-test-forge15-")


def _use_fresh_db(name: str) -> None:
    """Point the db module at a brand-new SQLite file (one per test)."""
    db.db_path = lambda: pathlib.Path(_TMP.name) / f"{name}.db"


async def _seed_miner() -> int:
    """Init the fresh DB and register one BitForge so the FK-constrained
    tables (best_records, notable_shares) have a parent row."""
    await db.init_db()
    return await db.upsert_miner(
        {
            "name": "Nano",
            "family": "bitforge",
            "host": "10.0.0.7",
            "port": 80,
            "mac": "AA:BB:CC:CA:3E:E0",
        }
    )


# ---------------------------------------------------------------------------
# update_best_records: quantized session string vs full-precision hint
# ---------------------------------------------------------------------------


def test_best_quantized_new_record_notifies():
    """The real field case: bestSessionDiff "1.88M" + bestDiff 1882611
    are the SAME share. Must be a notifying new record carrying the
    full-precision value — the old strict `cv >= hint` test silently
    seeded it instead."""
    _use_fresh_db("best-quantized")

    async def run():
        mid = await _seed_miner()
        await db.update_best_records(mid, 1_500_000.0, 100, ts=1000)
        return await db.update_best_records(
            mid,
            parse_si_difficulty("1.88M"),
            200,
            ts=1100,
            alltime_hint=1_882_611.0,
        )

    rec = asyncio.run(run())
    assert rec["events"]["new_alltime"] is True
    assert rec["events"]["alltime_seeded"] is False
    assert rec["alltime"]["value"] == 1_882_611.0


def test_best_precision_catchup_stays_silent():
    """First poll after the firmware switch: the stored record was
    seeded from the quantized string (1.88e6) and the numeric hint is
    the same share with more digits. The row must gain precision with
    NO push — "new best 1.88 M (was 1.88 M)" is noise."""
    _use_fresh_db("best-precision")

    async def run():
        mid = await _seed_miner()
        await db.update_best_records(mid, 1_880_000.0, 100, ts=1000)
        return await db.update_best_records(
            mid, 1_880_000.0, 200, ts=1100, alltime_hint=1_882_611.0
        )

    rec = asyncio.run(run())
    assert rec["events"]["new_alltime"] is False
    assert rec["events"]["alltime_seeded"] is True
    assert rec["alltime"]["value"] == 1_882_611.0


def test_best_hint_far_ahead_seeds_silently():
    """A genuinely-ahead hint (fresh MinerWatch DB, firmware NVS knows a
    200M record) keeps the silent catch-up semantics."""
    _use_fresh_db("best-far-hint")

    async def run():
        mid = await _seed_miner()
        return await db.update_best_records(
            mid, 6_000.0, 100, ts=1000, alltime_hint=200_000_000.0
        )

    rec = asyncio.run(run())
    assert rec["events"]["new_alltime"] is False
    assert rec["events"]["alltime_seeded"] is True
    assert rec["alltime"]["value"] == 200_000_000.0


def test_best_legacy_string_firmware_path_unchanged():
    """v1.0 / stock AxeOS: bestDiff and bestSessionDiff are the same
    quantized string, cv == hint — the classic notifying path."""
    _use_fresh_db("best-legacy")

    async def run():
        mid = await _seed_miner()
        await db.update_best_records(mid, 1.0e9, 100, ts=1000)
        return await db.update_best_records(
            mid, 4.29e9, 200, ts=1100, alltime_hint=4.29e9
        )

    rec = asyncio.run(run())
    assert rec["events"]["new_alltime"] is True
    assert rec["alltime"]["value"] == 4.29e9


def test_best_rounded_up_string_uses_precise_hint():
    """3-digit rendering can also round UP ("1.89M" for 1_885_100): the
    stored record must be the true value, not the inflated parse."""
    _use_fresh_db("best-roundup")

    async def run():
        mid = await _seed_miner()
        await db.update_best_records(mid, 1_500_000.0, 100, ts=1000)
        return await db.update_best_records(
            mid, 1.89e6, 200, ts=1100, alltime_hint=1_885_100.0
        )

    rec = asyncio.run(run())
    assert rec["events"]["new_alltime"] is True
    assert rec["alltime"]["value"] == 1_885_100.0


# ---------------------------------------------------------------------------
# Share-line parsing across firmware dialects
# ---------------------------------------------------------------------------


def test_share_regex_dialects():
    cases = {
        # axeOS 2.13 / v1.0 stock: integer target (%ld) + sentence dot
        "Ver: 22816000 Nonce 639505B4 diff 3035.4 of 1497.": (3035.4, 1497.0),
        # forge-os v1.5: target printed %.2f, still followed by the sentence dot.
        # The old greedy [0-9.]+ captured "1497.00." and float() raised.
        "Ver: 22816000 Nonce 639505B4 diff 3035.4 of 1497.00.": (3035.4, 1497.0),
        # axeOS 2.14: target printed %g — a large vardiff comes out in
        # scientific notation. The old token stopped at "e" and read 1.04858.
        "Nonce 639505B4 diff 900000.0 of 1.04858e+06.": (900000.0, 1048580.0),
        # axeOS 2.14 on a low vardiff: %g stays fixed-point ("8192")
        "Nonce 639505B4 diff 636998.5 of 8192.": (636998.5, 8192.0),
        # NerdQAxe(++): slash dialect with trailing best
        "ID: 69fd, ASIC nr: 0 diff 1394.8/3065/241M": (1394.8, 3065.0),
        # SI-suffixed values
        "diff 4.29G of 1.5k": (4.29e9, 1500.0),
    }
    for line, (want_share, want_target) in cases.items():
        m = _SHARE.search(line)
        assert m is not None, line
        assert _parse_diff_token(m.group(1)) == want_share, line
        assert _parse_diff_token(m.group(2)) == want_target, line


def test_axeos_214_scientific_share_and_v1_verdict():
    """End-to-end axeOS 2.14 on a high vardiff: the share line carries the
    pool target in %g scientific notation, and the accepted/rejected
    verdict arrives under the renamed ``stratum_v1_task`` tag. Both must be
    understood, or a 2.14 miner loses its dashed line (target mis-read) and
    its verdicts (tag unmatched)."""
    streamer, stream = _stream_pair()
    share = (
        "I (1000) asic_result: ID: 69fd, ASIC nr: 0, ver: 22816000 "
        "Nonce 639505B4 diff 2000000.0 of 1.04858e+06."
    )
    verdict = "I (1100) stratum_v1_task: message result accepted"

    async def run():
        await streamer._handle_line(stream, share)
        await streamer._handle_line(stream, verdict)

    asyncio.run(run())
    ev = stream.buffer[-1]
    assert ev.estimated is False
    assert ev.pool_target == 1_048_580.0  # 1.04858e+06, not 1.04858
    assert ev.share_diff == 2_000_000.0
    assert ev.submitted is True
    assert stream.synthetic_mode is False
    assert stream.accepted_total == 1
    assert ev.accepted is True


# ---------------------------------------------------------------------------
# Synthetic share events from pool verdicts (per-share lines compiled out)
# ---------------------------------------------------------------------------

V15_SET_DIFF = "\x1b[0;32mI (2313339) stratum_task: Set stratum difficulty: 8192.00\x1b[0m"
V15_POOL_DIFF = "I (10) asic_task: New pool difficulty 4096.00"
V15_VERDICT_OK = "\x1b[0;32mI (2328669) stratum_task: message result accepted\x1b[0m"
V15_VERDICT_REJ = "I (99) stratum_task: message result rejected: above target"
V10_SHARE = (
    "I (446925478) asic_result: ID: 69fd, ASIC nr: 0, ver: 22816000 "
    "Nonce 639505B4 diff 3035.4 of 1497."
)


def _stream_pair() -> tuple[LogStreamer, MinerStream]:
    """A LogStreamer with one registered stream, no WS task attached."""
    streamer = LogStreamer()
    stream = MinerStream(miner_id=1, host="10.0.0.7", port=80)
    streamer._streams[1] = stream
    return streamer, stream


def test_synthetic_share_from_verdict():
    streamer, stream = _stream_pair()
    q = streamer.subscribe(1)

    async def run():
        await streamer._handle_line(stream, V15_SET_DIFF)
        assert stream.current_target == 8192.0
        await streamer._handle_line(stream, V15_VERDICT_OK)

    asyncio.run(run())
    assert stream.synthetic_mode is True
    assert stream.results_total == 1
    assert stream.submitted_total == 1
    assert stream.accepted_total == 1
    assert stream.estimated_total == 1
    assert len(stream.buffer) == 1
    ev = stream.buffer[0]
    assert ev.submitted is True
    assert ev.estimated is True
    assert ev.accepted is True
    assert ev.share_diff == 8192.0
    assert ev.pool_target == 8192.0
    # Wire protocol identical to the real path: share, then verdict.
    first = q.get_nowait()
    second = q.get_nowait()
    assert first["type"] == "share"
    assert first["data"]["estimated"] is True
    assert second["type"] == "verdict"
    assert second["data"]["accepted"] is True


def test_verdict_without_target_counts_but_draws_nothing():
    """No target known yet: the verdict still counts, but a dot without
    a difficulty floor has no place on the chart."""
    streamer, stream = _stream_pair()
    asyncio.run(streamer._handle_line(stream, V15_VERDICT_OK))
    assert stream.accepted_total == 1
    assert len(stream.buffer) == 0
    assert stream.synthetic_mode is False


def test_rest_target_seed_enables_synthesis():
    """The poller's stratumDiff seed substitutes for the vardiff line."""
    streamer, stream = _stream_pair()
    streamer.note_pool_target(1, 8192)
    assert stream.current_target == 8192.0
    asyncio.run(streamer._handle_line(stream, V15_VERDICT_REJ))
    assert stream.rejected_total == 1
    ev = stream.buffer[-1]
    assert ev.accepted is False
    assert ev.estimated is True


def test_asic_task_pool_difficulty_line_updates_target():
    streamer, stream = _stream_pair()
    asyncio.run(streamer._handle_line(stream, V15_POOL_DIFF))
    assert stream.current_target == 4096.0


def test_real_share_line_exits_synthetic_mode():
    """A custom build with the per-share line re-enabled (or a v1.0
    board) must get the full-fidelity path back automatically."""
    streamer, stream = _stream_pair()
    streamer.note_pool_target(1, 8192)

    async def run():
        await streamer._handle_line(stream, V15_VERDICT_OK)
        assert stream.synthetic_mode is True
        await streamer._handle_line(stream, V10_SHARE)

    asyncio.run(run())
    assert stream.synthetic_mode is False
    assert stream.results_total == 2
    real = stream.buffer[-1]
    assert real.estimated is False
    assert real.share_diff == 3035.4
    assert real.pool_target == 1497.0
    assert stream.current_target == 1497.0


def test_session_best_amends_and_feeds_hall_of_fame():
    """A REST-observed new session best upgrades the latest synthetic
    dot to the exact difficulty (amend event) and lands in the Hall of
    Fame with the verdict backfilled."""
    _use_fresh_db("ls-notable")
    streamer, stream = _stream_pair()
    q = streamer.subscribe(1)

    async def run():
        mid = await _seed_miner()
        assert mid == stream.miner_id
        streamer.note_pool_target(1, 8192)
        await streamer._handle_line(stream, V15_VERDICT_OK)
        q.get_nowait()  # share
        q.get_nowait()  # verdict
        await streamer.note_session_best(1, 1_882_611.0, ts=1_900_000_000)
        return await db.list_notable_shares(1)

    rows = asyncio.run(run())
    ev = stream.buffer[-1]
    assert ev.share_diff == 1_882_611.0
    assert ev.estimated is False
    amend = q.get_nowait()
    assert amend["type"] == "amend"
    assert amend["data"]["seq"] == ev.seq
    assert amend["data"]["diff"] == 1_882_611.0
    assert len(rows) == 1
    assert rows[0]["share_difficulty"] == 1_882_611.0
    assert rows[0]["pool_target"] == 8192.0
    assert rows[0]["accepted"] == 1  # backfilled from the synthetic verdict


def test_session_best_below_threshold_amends_only():
    _use_fresh_db("ls-small")
    streamer, stream = _stream_pair()

    async def run():
        await db.init_db()
        streamer.note_pool_target(1, 8192)
        await streamer._handle_line(stream, V15_VERDICT_OK)
        await streamer.note_session_best(1, 9_500.0, ts=1_900_000_000)
        return await db.list_notable_shares(1)

    rows = asyncio.run(run())
    assert rows == []
    assert stream.buffer[-1].share_diff == 9_500.0


def test_session_best_noop_on_full_fidelity_stream():
    """Firmware with a real per-share stream must never get duplicate
    Hall-of-Fame rows from the REST feed."""
    _use_fresh_db("ls-noop")
    streamer, stream = _stream_pair()

    async def run():
        await db.init_db()
        await streamer._handle_line(stream, V10_SHARE)
        await streamer.note_session_best(1, 5_000_000.0, ts=1_900_000_000)
        return await db.list_notable_shares(1)

    rows = asyncio.run(run())
    assert rows == []
    assert stream.buffer[-1].share_diff == 3035.4


# ---------------------------------------------------------------------------
# stratum TLS round-trip (forge-os v1.5+)
# ---------------------------------------------------------------------------


def test_set_pool_writes_tls_flags():
    drv = BitaxeDriver("10.0.0.7")
    patch_mock = AsyncMock(return_value=True)
    with patch.object(drv, "_patch_system", patch_mock), \
         patch.object(drv, "restart", AsyncMock(return_value=True)):
        ok = asyncio.run(
            drv.set_pool(
                PoolConfig(
                    url="tls-pool.example.org",
                    port=443,
                    user="bc1q.worker",
                    password="x",
                    tls=1,
                    cert="PINNED",
                    fb_url="public-pool.io",
                    fb_port=21496,
                    fb_user="bc1q.fb",
                    fb_tls=0,
                )
            )
        )
    assert ok is True
    payload = patch_mock.call_args[0][0]
    assert payload["stratumTLS"] == 1
    assert payload["stratumCert"] == "PINNED"
    assert payload["fallbackStratumTLS"] == 0
    assert "fallbackStratumCert" not in payload


def test_set_pool_none_tls_leaves_firmware_untouched():
    """Pre-TLS snapshots (tls=None) must not write the TLS keys at all,
    so restoring an old snapshot can't flip a TLS pool to plain TCP."""
    drv = BitaxeDriver("10.0.0.7")
    patch_mock = AsyncMock(return_value=True)
    with patch.object(drv, "_patch_system", patch_mock), \
         patch.object(drv, "restart", AsyncMock(return_value=True)):
        asyncio.run(
            drv.set_pool(
                PoolConfig(url="solo.ckpool.org", port=3333, user="bc1q.w")
            )
        )
    payload = patch_mock.call_args[0][0]
    assert "stratumTLS" not in payload
    assert "stratumCert" not in payload


def test_donation_configs_force_plain_tcp():
    """The donate pool is plain TCP: an inherited stratumTLS=1 in NVS
    would kill mining until the revert, so the repoint must say tls=0
    explicitly."""
    assert donation_pool_config().tls == 0
    assert donation_pool_config_fallback().fb_tls == 0


def test_read_pool_config_captures_tls():
    drv = BitaxeDriver("10.0.0.7")
    info = {
        "stratumURL": "tls-pool.example.org",
        "stratumPort": 443,
        "stratumUser": "bc1q.worker",
        "stratumTLS": 1,
        "stratumCert": "PINNED",
        "fallbackStratumURL": "eusolo.ckpool.org",
        "fallbackStratumPort": 3333,
        "fallbackStratumUser": "bc1q.fb",
        "fallbackStratumTLS": 0,
        "fallbackStratumCert": "x",
    }
    with patch.object(drv, "_system_info", AsyncMock(return_value=info)):
        cfg = asyncio.run(drv.read_pool_config())
    assert cfg.tls == 1
    assert cfg.cert == "PINNED"
    assert cfg.fb_tls == 0
    assert cfg.fb_cert == "x"
    # And the snapshot survives the JSON round-trip used by donations.
    restored = PoolConfig.from_json(cfg.to_json())
    assert restored.tls == 1
    assert restored.fb_tls == 0


# ---------------------------------------------------------------------------
# Discovery: deviceModel "invalid" (NVS default) must not name the board
# ---------------------------------------------------------------------------


def test_identify_treats_invalid_device_model_as_absent():
    """A factory-v1.0 board OTA'd to v1.5 whose NVS never got the
    devicemodel key reports the literal "invalid": classification must
    ride on the chiptemp fingerprint and the model must stay "BitForge
    Nano", not become "Invalid"."""
    info = {
        "hashRate": 2595.4,
        "power": 41.7,
        "temp": 53.75,
        "chiptemp1": 51.75,
        "chiptemp2": 55.75,
        "fanSpeed": 63,
        "fanrpm": 3859,
        "ASICModel": "BM1370",
        "asicCount": 2,
        "smallCoreCount": 2040,
        "hostname": "BitForge",
        "macAddr": "aa:bb:cc:ca:3e:e0",
        "uptimeSeconds": 2302,
        "version": "v1.5-apfix2",
    }
    asic = {"ASICModel": "BM1370", "deviceModel": "invalid", "asicCount": 2}
    sample = BitForgeDriver("10.0.0.7")._parse(info)
    sample.raw = info
    with patch.object(discovery.BitaxeDriver, "poll", AsyncMock(return_value=sample)), \
         patch.object(discovery.BitaxeDriver, "fetch_asic_info", AsyncMock(return_value=asic)):
        found = asyncio.run(discovery._identify_bitaxe("10.0.0.7"))
    assert found is not None
    assert found["family"] == "bitforge"
    assert found["model"] == "BitForge Nano"
    assert found["name"] == "BitForge"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
