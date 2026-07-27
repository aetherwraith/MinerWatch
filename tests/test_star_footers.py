# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the milestone Telegram footers (star / donations).

Covers backend/alerts.py: the global 14-day rate limit on the star
footer, the config kill-switch on both footers, and the fact that the
footer rides ``telegram_extra`` so it lands in the Telegram text while
the push body stays clean.

Runs under pytest, or standalone: ``python tests/test_star_footers.py``.
"""
from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend import alerts

NOW = 1_900_000_000


def _with_config(enabled: bool):
    """Swap alerts.get_config for a stub; returns the restore handle."""
    original = alerts.get_config
    alerts.get_config = lambda: SimpleNamespace(
        alerts=SimpleNamespace(telegram_star_footer=enabled)
    )
    return original


def _reset_state():
    alerts._star_footer_last_ts = 0


def test_star_footer_fires_then_respects_cooldown():
    original = _with_config(True)
    try:
        _reset_state()
        first = alerts.star_footer_if_due(NOW)
        assert first is not None
        assert alerts.GITHUB_REPO_URL in first
        assert alerts.star_footer_if_due(NOW + 60) is None
        assert alerts.star_footer_if_due(NOW + alerts.STAR_FOOTER_COOLDOWN_S - 1) is None
        assert alerts.star_footer_if_due(NOW + alerts.STAR_FOOTER_COOLDOWN_S) is not None
    finally:
        alerts.get_config = original
        _reset_state()


def test_star_footer_kill_switch_does_not_consume_cooldown():
    original = _with_config(False)
    try:
        _reset_state()
        assert alerts.star_footer_if_due(NOW) is None
        alerts.get_config = lambda: SimpleNamespace(
            alerts=SimpleNamespace(telegram_star_footer=True)
        )
        assert alerts.star_footer_if_due(NOW + 1) is not None
    finally:
        alerts.get_config = original
        _reset_state()


def test_donation_footer_links_to_readme_anchor():
    original = _with_config(True)
    try:
        footer = alerts.donation_footer()
        assert footer is not None
        assert footer.rstrip().endswith("#donations")
    finally:
        alerts.get_config = original


def test_donation_footer_kill_switch():
    original = _with_config(False)
    try:
        assert alerts.donation_footer() is None
    finally:
        alerts.get_config = original


def test_footer_lands_in_telegram_text_only():
    payload = {
        "title": "🎯 New best share",
        "body": "Gamma: 21.69 G (was 18.42 G)",
        "telegram_extra": alerts.STAR_FOOTER_TEXT,
    }
    text = alerts._format_telegram_message(payload)
    assert "GitHub star" in text
    assert text.startswith("🎯 New best share\nGamma")
    assert "GitHub" not in payload["body"]


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
