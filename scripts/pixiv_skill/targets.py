"""Turn whatever the user pasted (URL, prefixed id, bare number) into a target."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    kind: str  # artwork | novel | series | user
    id: str


_URL_PATTERNS = [
    (r"novel/show\.php\?(?:[^#]*&)?id=(\d+)", "novel"),
    (r"novel/series/(\d+)", "series"),
    (r"/(?:[a-z]{2}/)?artworks/(\d+)", "artwork"),
    (r"illust_id=(\d+)", "artwork"),
    (r"i\.pximg\.net/.*/(\d+)_p\d+", "artwork"),
    (r"/users?/(\d+)", "user"),
    (r"member(?:_illust)?\.php\?(?:[^#]*&)?id=(\d+)", "user"),
]

_PREFIXES = {
    "art": "artwork", "artwork": "artwork", "illust": "artwork", "manga": "artwork",
    "i": "artwork", "m": "artwork",
    "novel": "novel", "n": "novel",
    "series": "series", "ser": "series", "s": "series",
    "user": "user", "u": "user", "uid": "user",
}


def parse_target(text: str, default: str = "artwork") -> Target | None:
    """Bare numbers are ambiguous on Pixiv, so they fall back to ``default``."""
    text = text.strip()
    for pattern, kind in _URL_PATTERNS:
        if m := re.search(pattern, text):
            return Target(kind, m.group(1))
    if m := re.fullmatch(r"([a-z]+)\s*[:：]\s*(\d+)", text, re.I):
        kind = _PREFIXES.get(m.group(1).lower())
        return Target(kind, m.group(2)) if kind else None
    if re.fullmatch(r"\d+", text):
        return Target(default, text)
    return None
