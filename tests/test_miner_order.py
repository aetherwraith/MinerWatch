# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the persisted miner display order (backend/db.merge_miner_order).

Pure-function tests — no database. The merge is the write-path of the
`_miner_order` setting shared by the dashboard grid and the ESP32 panel
feed; its one non-obvious behaviour is orphan preservation: stored
entries the client didn't submit (temporarily removed miners) are
re-inserted at the index they previously occupied, so a returning miner
reclaims its slot. Runs under pytest, or standalone:
``python tests/test_miner_order.py``.
"""
from __future__ import annotations

import pathlib
import sys

# Make the repo root importable whether invoked via pytest or directly.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend.db import _MINER_ORDER_MAX, merge_miner_order


def test_merge_plain_save() -> None:
    # First save (nothing stored) keeps the submission as-is.
    assert merge_miner_order([], ["a", "b", "c"]) == ["a", "b", "c"]
    # Reorder of the same set: submission wins.
    assert merge_miner_order(["a", "b", "c"], ["c", "a", "b"]) == ["c", "a", "b"]


def test_merge_preserves_orphans_at_their_old_index() -> None:
    # B and C are stored but missing from the submission (their miners
    # were deleted meanwhile). They re-enter at their old positions and
    # keep their relative order, while the submitted entries keep the
    # relative order the user just chose (d before a).
    assert merge_miner_order(["a", "b", "c", "d"], ["d", "a"]) == ["d", "b", "c", "a"]
    # Orphans reclaim their exact old slots around the submission.
    assert merge_miner_order(["a", "b", "c"], ["b"]) == ["a", "b", "c"]
    # Empty submission (e.g. a client with no miners loaded) restores
    # the stored order untouched — also why POST [] can never reset;
    # resetting has its own DELETE endpoint.
    assert merge_miner_order(["x", "y", "z"], []) == ["x", "y", "z"]
    # Junk-padded stored list: the orphan's old index may exceed the
    # rebuilt list, in which case it clamps into range.
    assert merge_miner_order(["", "", "z"], []) == ["z"]


def test_merge_drops_junk_and_duplicates() -> None:
    # The merge faces the HTTP API: non-strings, empties and duplicates
    # must never reach the stored value (a duplicate id would otherwise
    # be ambiguous when the panel permutes its array).
    assert merge_miner_order([], ["a", "", "a", 7, None, "b"]) == ["a", "b"]
    assert merge_miner_order(["a", "a", ""], ["b"]) == ["a", "b"]


def test_merge_caps_length() -> None:
    # At the cap, the oldest orphans are dropped — never the entries the
    # client just submitted (those are live miners on screen).
    stored = [f"m{i}" for i in range(_MINER_ORDER_MAX)]
    merged = merge_miner_order(stored, ["new"])
    assert len(merged) == _MINER_ORDER_MAX
    assert "new" in merged
    assert merged[0] == "m0"
    assert f"m{_MINER_ORDER_MAX - 1}" not in merged


if __name__ == "__main__":
    test_merge_plain_save()
    test_merge_preserves_orphans_at_their_old_index()
    test_merge_drops_junk_and_duplicates()
    test_merge_caps_length()
    print("ok — miner order merge tests passed")
