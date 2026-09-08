"""Canonical fork-naming rule shared by session storage, /fork and auto-titling.

Every forked session carries a trailing marker so its lineage stays visible in
the session tree even after auto-titling rewrites the descriptive part:

* ``<base> (fork)``   — first fork taken from ``<base>``
* ``<base> (fork 2)`` — second fork, and so on

``<base>`` is kept short (see :data:`FORK_BASE_MAX_LEN`) so the marker survives
title ellipsis in the resume list.
"""

from __future__ import annotations

import re

# Upper bound for the descriptive part of a fork title: ``base + " (fork N)"``
# must stay inside the resume row budget, otherwise the trailing marker is the
# first thing clipped by ``ellipsize``.
FORK_BASE_MAX_LEN = 40

_FORK_SUFFIX = re.compile(r"\s*\(fork(?:\s+\d+)?\)\s*$", re.IGNORECASE)


def strip_fork_suffix(title: str | None) -> str:
    """Session title without its trailing ``(fork)`` / ``(fork N)`` marker."""
    return _FORK_SUFFIX.sub("", title or "").strip()


def fork_marker(title: str | None) -> str:
    """Trailing fork marker (``" (fork 2)"``), or ``""`` when there is none."""
    match = _FORK_SUFFIX.search(title or "")
    return f" {match.group(0).strip()}" if match else ""


def cap_at_word(text: str, max_len: int, *, strip: str = "") -> str:
    """``text`` capped to ``max_len`` at a word boundary (no-op when short enough).

    ``strip`` removes surrounding junk (e.g. punctuation) from the cut; without
    it the cut is only right-stripped of whitespace. The single word-boundary
    cap rule for session titles so every caller clips identically.
    """
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    r_space = cut.rfind(" ")
    if r_space > 15:
        cut = cut[:r_space]
    return cut.strip(strip) if strip else cut.rstrip()


def build_fork_title(base: str | None, number: int) -> str:
    """Title of the ``number``-th (1-based) fork taken from ``base``.

    The base is capped to :data:`FORK_BASE_MAX_LEN` here — the single place a
    fork title is assembled — so the marker survives resume-row ellipsis no
    matter which caller supplied the base (UI hint, store title fallback,
    auto-titling).
    """
    clean = cap_at_word(strip_fork_suffix(base) or "Untitled", FORK_BASE_MAX_LEN)
    return f"{clean} (fork)" if number <= 1 else f"{clean} (fork {number})"
