"""Canonical locale set and pure resolution helpers (no DB)."""

import re
import unicodedata
from typing import Final

SUPPORTED_LOCALES: Final[tuple[str, ...]] = ("en", "tr", "zh-CN", "es")
DEFAULT_LOCALE: Final[str] = "en"
LOCALE_COOKIE: Final[str] = "locale"

TRANSLATION_STATUSES: Final[tuple[str, ...]] = ("missing", "draft", "reviewed", "published")
# Statuses shown to players. `draft` is shown (flagged for QA in admin); `missing` forces fallback.
PLAYER_VISIBLE_STATUSES: Final[frozenset[str]] = frozenset({"draft", "reviewed", "published"})

_KEY_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")


def is_supported(locale: str | None) -> bool:
    return locale in SUPPORTED_LOCALES


def normalize_locale_tag(tag: str) -> str | None:
    """Map an arbitrary BCP-47-ish tag onto a supported locale, or None."""
    tag = tag.strip()
    if tag in SUPPORTED_LOCALES:
        return tag
    lower = tag.lower().replace("_", "-")
    if lower.startswith("zh"):
        return "zh-CN"
    base = lower.split("-")[0]
    return base if base in SUPPORTED_LOCALES else None


def parse_accept_language(header: str | None) -> str | None:
    if not header:
        return None
    weighted: list[tuple[float, int, str]] = []
    for idx, part in enumerate(header.split(",")):
        pieces = part.strip().split(";")
        if not pieces[0]:
            continue
        q = 1.0
        for p in pieces[1:]:
            p = p.strip()
            if p.startswith("q="):
                try:
                    q = float(p[2:])
                except ValueError:
                    q = 0.0
        weighted.append((-q, idx, pieces[0]))
    for neg_q, _, tag in sorted(weighted):
        if -neg_q <= 0:
            continue
        loc = normalize_locale_tag(tag)
        if loc:
            return loc
    return None


def normalize_text(value: str) -> str:
    """All stored translation text is NFC-normalized and stripped of control chars (except newlines/tabs)."""
    value = unicodedata.normalize("NFC", value)
    return "".join(ch for ch in value if ch in "\n\t" or unicodedata.category(ch)[0] != "C")


def is_valid_key(key: str) -> bool:
    return bool(_KEY_RE.match(key)) and len(key) <= 200


def safe_label(key: str) -> str:
    """Last-resort display label derived from an internal key, e.g. `race.high_elf.name` -> `High Elf`."""
    parts = [p for p in key.split(".") if p]
    generic = {"name", "description", "desc", "short", "lore", "title", "label"}
    while len(parts) > 1 and parts[-1] in generic:
        parts.pop()
    word = parts[-1] if parts else key
    return " ".join(w.capitalize() for w in word.split("_") if w) or key
