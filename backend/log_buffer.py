# SPDX-License-Identifier: AGPL-3.0-only
"""In-memory ring buffer for system logging.

Attaches a standard logging.Handler to standard library logging so that
all application logs (INFO, WARNING, ERROR) are captured and accessible via
the REST API GET /api/logs.
"""
from __future__ import annotations

import collections
import datetime
import logging
import threading
from typing import Any

MAX_LOG_RECORDS = 1000

_log_id_counter = 0
_id_lock = threading.Lock()


class LogRecordDict:
    __slots__ = ("id", "ts", "timestamp", "level", "logger", "message")

    def __init__(self, record_id: int, ts: float, level: str, logger_name: str, message: str) -> None:
        self.id = record_id
        self.ts = ts
        self.timestamp = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()
        self.level = level
        self.logger = logger_name
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger,
            "message": self.message,
        }


class RingBufferHandler(logging.Handler):
    """Logging handler storing log records in a fixed-size deque."""

    def __init__(self, maxlen: int = MAX_LOG_RECORDS) -> None:
        super().__init__()
        self.buffer: collections.deque[LogRecordDict] = collections.deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        global _log_id_counter
        try:
            msg = self.format(record)
            with _id_lock:
                _log_id_counter += 1
                rec_id = _log_id_counter

            item = LogRecordDict(
                record_id=rec_id,
                ts=record.created,
                level=record.levelname,
                logger_name=record.name,
                message=msg,
            )
            self.buffer.append(item)
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def get_logs(
        self,
        limit: int = 200,
        level: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        search_lower = search.lower() if search else None
        level_upper = level.upper() if level else None

        # Snapshot buffer
        items = list(self.buffer)
        # Reverse to get newest first
        items.reverse()

        for item in items:
            if level_upper and item.level != level_upper:
                continue
            if search_lower and (search_lower not in item.message.lower() and search_lower not in item.logger.lower()):
                continue
            results.append(item.to_dict())
            if len(results) >= limit:
                break

        return results

    def clear(self) -> None:
        self.buffer.clear()


# Global instance
ring_buffer_handler = RingBufferHandler(MAX_LOG_RECORDS)
ring_buffer_handler.setFormatter(logging.Formatter("%(message)s"))
