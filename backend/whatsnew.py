# SPDX-License-Identifier: AGPL-3.0-only
"""What's-new highlights for the post-update dialog.

The frontend shows a small "What's new in MinerWatch" dialog once per
version (tracked client-side in localStorage). Its content comes from
CHANGELOG.md, which already follows a convention that makes this
extraction clean: every top-level bullet starts with a **bold lead
sentence** summarising the change, followed by the long technical
detail. We surface only the bold leads (plus the first sentence of the
detail as a one-line body) — the full changelog stays one click away
on GitHub.

No new data source, no cloud: the file is read from the repo root at
runtime (the Dockerfile ships it next to VERSION). A missing file or a
version without bold leads degrades to a single generic "Bug fixes and
improvements" highlight, so the dialog still appears on every release,
which is the point — it carries the star/donate ask.
"""
from __future__ import annotations

import re
from typing import Any

from . import updater
from .config import ROOT_DIR

# At most this many highlights reach the dialog; beyond that it stops
# being a glance and starts being a changelog.
MAX_HIGHLIGHTS = 4

# One-line body cap (characters) for the dialog.
MAX_BODY_CHARS = 160

_FALLBACK = {"title": "Bug fixes and improvements", "body": ""}

_cache: tuple[str, list[dict[str, str]]] | None = None


def parse_changelog_highlights(text: str, version: str) -> list[dict[str, str]]:
    """Extract dialog highlights for ``version`` from a changelog.

    Finds the ``## [<version>]`` section, then for each top-level
    bullet that follows the house convention (``- **Bold lead.** long
    detail…``) returns the bold lead as ``title`` and the first
    sentence of the detail, truncated, as ``body``. Bullets without a
    bold lead are skipped. Returns [] when the section is missing or
    has no conforming bullets — the caller decides the fallback.
    """
    section = _version_section(text, version)
    if not section:
        return []

    highlights: list[dict[str, str]] = []
    for chunk in re.split(r"\n- ", section):
        match = re.match(r"\s*\*\*(.+?)\*\*\s*(.*)", chunk, flags=re.DOTALL)
        if not match:
            continue
        title = _strip_markdown(match.group(1)).strip().rstrip(".")
        body = _first_sentence(match.group(2))
        if title:
            highlights.append({"title": title, "body": body})
        if len(highlights) >= MAX_HIGHLIGHTS:
            break
    return highlights


def _version_section(text: str, version: str) -> str:
    """The body of ``## [<version>]`` up to the next ``## `` heading."""
    pattern = re.compile(
        r"^## \[" + re.escape(version) + r"\][^\n]*\n(.*?)(?=^## |\Z)",
        flags=re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(text)
    return match.group(1) if match else ""


def _strip_markdown(text: str) -> str:
    """Drop the inline markdown the dialog can't render (bold markers,
    code backticks, link syntax → link text)."""
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)


def _first_sentence(detail: str) -> str:
    """First sentence of the bullet detail, whitespace-collapsed and
    capped at MAX_BODY_CHARS. Good enough for a one-line teaser; the
    full text lives in the changelog link."""
    flat = re.sub(r"\s+", " ", _strip_markdown(detail)).strip()
    if not flat:
        return ""
    sentence = flat.split(". ", 1)[0].strip()
    if not sentence.endswith("."):
        sentence += "."
    if len(sentence) > MAX_BODY_CHARS:
        sentence = sentence[: MAX_BODY_CHARS - 1].rstrip() + "…"
    return sentence


def get_whatsnew() -> dict[str, Any]:
    """Highlights for the running version, cached per version."""
    global _cache
    version = updater.read_version()
    if _cache is not None and _cache[0] == version:
        return {"version": version, "highlights": _cache[1]}

    try:
        text = (ROOT_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
    except OSError:
        text = ""

    highlights = parse_changelog_highlights(text, version)
    if not highlights:
        highlights = [dict(_FALLBACK)]

    _cache = (version, highlights)
    return {"version": version, "highlights": highlights}
