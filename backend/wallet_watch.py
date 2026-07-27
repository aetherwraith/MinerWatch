# SPDX-License-Identifier: AGPL-3.0-only
"""Watched Bitcoin addresses — incoming-transaction notifications.

The user lists one or more BTC addresses in Settings → Alerts. A slow
background loop polls mempool.space for each address and fires a
notification (browser push + Telegram, via the regular dispatcher)
when a NEW CONFIRMED INCOMING transaction shows up.

Design decisions (agreed with the user):
  * Confirmed only — a tx sitting in the mempool is ignored until it
    lands in a block, so an RBF replacement can never produce a ghost
    notification. Dedup is by txid, persisted in the DB.
  * Incoming only — the address must appear in the tx OUTPUTS and not
    in its inputs. Spends and self-transfers are marked seen silently.
  * Dust is NOT filtered: a confirmed incoming amount at or below
    ``alerts.wallet_watch_dust_sats`` still notifies, but with the
    title "Potential dust attack" and a "do not spend" warning (dust
    is an address-tracking technique; the danger is spending it).
  * Silent bootstrap — the first time an address is polled, its whole
    confirmed history is marked seen WITHOUT notifying, so adding an
    address with past activity doesn't flood every channel. A state
    row records the bootstrap so an address with zero history doesn't
    re-bootstrap forever (and swallow its very first real payment).

mempool.space is already MinerWatch's source for network difficulty,
so no new third party is involved. ``/api/address/{addr}/txs`` returns
the ~50 most recent transactions (mempool + confirmed), which is far
more than one poll interval can accumulate on a personal address.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from . import db
from .alerts import send_notification
from .config import get_config

log = logging.getLogger("minerwatch.wallet_watch")

# One pass over all watched addresses every POLL_INTERVAL_S. Address
# count is expected to be tiny (1-5), and mempool.space comfortably
# allows this cadence; SPACING_S keeps requests politely apart.
POLL_INTERVAL_S = 60
SPACING_S = 1.0
HTTP_TIMEOUT_S = 10

ADDRESS_TXS_URL = "https://mempool.space/api/address/{address}/txs"
ADDRESS_PAGE_URL = "https://mempool.space/address/{address}"
TX_PAGE_URL = "https://mempool.space/tx/{txid}"

# Loose shape check, not a checksum validation: legacy (1…), P2SH (3…)
# in base58, and bech32/bech32m (bc1q…/bc1p…). Catches pasted garbage
# and testnet addresses; the UI applies the same pattern client-side.
ADDRESS_RE = re.compile(r"^(bc1[02-9ac-hj-np-z]{11,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")


def parse_watched_addresses(raw: str) -> list[dict[str, str]]:
    """Decode ``alerts.wallet_watch_addresses`` (a JSON string).

    Expected shape: ``[{"address": "bc1…", "label": "Donations"}, …]``.
    Invalid JSON, non-list payloads and malformed entries are dropped
    (with a log line) instead of raised: a bad setting must never kill
    the loop. bech32 addresses are case-insensitive by spec but mixed
    case is invalid, so anything starting with ``bc1`` is lowercased.
    """
    try:
        data = json.loads(raw or "[]")
    except ValueError:
        log.warning("wallet_watch: alerts.wallet_watch_addresses is not valid JSON; ignoring")
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        addr = str(entry.get("address", "")).strip()
        if addr[:3].lower() == "bc1":
            addr = addr.lower()
        if not ADDRESS_RE.match(addr):
            if addr:
                log.warning("wallet_watch: skipping invalid address %r", addr)
            continue
        if addr in seen:
            continue
        seen.add(addr)
        out.append({"address": addr, "label": str(entry.get("label", "")).strip()})
    return out


def _format_amount(sats: int) -> str:
    """Human amount: small values read better in sats than in 0.00000546 BTC."""
    if sats < 100_000:
        return f"{sats:,} sats"
    btc = f"{sats / 1e8:.8f}".rstrip("0").rstrip(".")
    return f"{btc} BTC"


def _short_address(address: str) -> str:
    return address if len(address) <= 16 else f"{address[:8]}…{address[-6:]}"


def _incoming_sats(tx: dict[str, Any], address: str) -> tuple[int, bool]:
    """Return ``(received_sats, is_spend)`` for ``address`` in ``tx``.

    ``is_spend`` is True when the address funds any input — that makes
    the tx an outgoing/self-transfer from our point of view, and the
    "received" outputs are just change coming back.
    """
    received = 0
    for vout in tx.get("vout", []) or []:
        if vout.get("scriptpubkey_address") == address:
            received += int(vout.get("value", 0))
    is_spend = any(
        (vin.get("prevout") or {}).get("scriptpubkey_address") == address
        for vin in tx.get("vin", []) or []
    )
    return received, is_spend


class WalletWatcher:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="minerwatch-wallet-watch")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()
        self._task = None

    async def _run(self) -> None:
        log.info("wallet watcher started (interval %ss)", POLL_INTERVAL_S)
        while not self._stop.is_set():
            try:
                await self.poll_once()
            except Exception:
                log.exception("wallet_watch: unexpected error in poll cycle")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=POLL_INTERVAL_S)
            except asyncio.TimeoutError:
                pass
        log.info("wallet watcher stopped")

    async def poll_once(self) -> None:
        cfg = get_config()
        if not cfg.alerts.wallet_watch_enabled:
            return
        watched = parse_watched_addresses(cfg.alerts.wallet_watch_addresses)
        # Drop persisted state for addresses the user removed, so a
        # later re-add gets a fresh silent bootstrap instead of a
        # replay of whatever happened in between.
        await db.wallet_prune_state([w["address"] for w in watched])
        if not watched:
            return

        dust_sats = max(0, int(cfg.alerts.wallet_watch_dust_sats))
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            for i, entry in enumerate(watched):
                if self._stop.is_set():
                    return
                if i:
                    await asyncio.sleep(SPACING_S)
                try:
                    await self._check_address(client, entry, dust_sats)
                except httpx.HTTPError as exc:
                    log.warning(
                        "wallet_watch: fetch failed for %s (%s) — will retry next cycle",
                        _short_address(entry["address"]), exc,
                    )
                except Exception:
                    log.exception(
                        "wallet_watch: error processing %s", _short_address(entry["address"])
                    )

    async def _check_address(
        self, client: httpx.AsyncClient, entry: dict[str, str], dust_sats: int
    ) -> None:
        address = entry["address"]
        label = entry.get("label", "")

        resp = await client.get(ADDRESS_TXS_URL.format(address=address))
        resp.raise_for_status()
        txs = resp.json()
        if not isinstance(txs, list):
            log.warning("wallet_watch: unexpected payload for %s", _short_address(address))
            return

        confirmed = [
            tx for tx in txs
            if isinstance(tx, dict)
            and (tx.get("status") or {}).get("confirmed")
            and tx.get("txid")
        ]

        if not await db.wallet_is_bootstrapped(address):
            await db.wallet_mark_seen(address, [tx["txid"] for tx in confirmed])
            await db.wallet_mark_bootstrapped(address)
            log.info(
                "wallet_watch: bootstrapped %s with %d confirmed tx(s), no notifications",
                _short_address(address), len(confirmed),
            )
            return

        seen = await db.wallet_seen_txids(address)
        fresh = [tx for tx in confirmed if tx["txid"] not in seen]
        if not fresh:
            return

        # The API returns newest first; notify oldest first so multiple
        # arrivals read chronologically on phone lockscreens.
        for tx in reversed(fresh):
            txid = str(tx["txid"])
            received, is_spend = _incoming_sats(tx, address)
            await db.wallet_mark_seen(address, [txid])
            if is_spend or received <= 0:
                continue

            who = label or _short_address(address)
            amount = _format_amount(received)
            address_url = ADDRESS_PAGE_URL.format(address=address)
            tx_url = TX_PAGE_URL.format(txid=txid)

            if received <= dust_sats:
                title = "Potential dust attack"
                severity = "warning"
                code = "wallet_dust"
                body = (
                    f"{who}: +{amount} — tiny incoming transaction, possibly "
                    f"address tracking. Do not spend it."
                )
            else:
                title = "New transaction received"
                severity = "info"
                code = "wallet_tx"
                body = f"{who}: +{amount}"

            await db.insert_alert(None, severity, code, body)
            await send_notification({
                "title": title,
                "body": body,
                "code": code,
                # Browser push: clicking the notification opens the
                # address page (user's choice over the tx page).
                "url": address_url,
                # Telegram fits both links comfortably.
                "telegram_extra": f"Transaction: {tx_url}\nAddress: {address_url}",
            })
            log.info(
                "wallet_watch: %s for %s: +%s (txid %s…)",
                code, _short_address(address), amount, txid[:12],
            )


wallet_watcher = WalletWatcher()
