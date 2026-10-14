"""Fuzzy matching of titles and authors across languages and editions."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable, Optional

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_LEADING_ARTICLES = re.compile(r"^(the|a|an|le|la|les|l|el|los|las|il|lo|gli|der|die|das|o|i|to|ta|oi)\s+")


def normalize(text: Optional[str]) -> str:
    """Lowercase, strip accents/diacritics (incl. Greek tonos) and punctuation."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _PUNCT.sub(" ", text.casefold())
    return _SPACES.sub(" ", text).strip()


def core_title(title: Optional[str]) -> str:
    """Normalized title without subtitle or leading article."""
    if not title:
        return ""
    main = re.split(r"[:(\[]| - | — ", title, maxsplit=1)[0]
    return _LEADING_ARTICLES.sub("", normalize(main))


def title_similarity(a: Optional[str], b: Optional[str]) -> float:
    ca, cb = core_title(a), core_title(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    ratio = SequenceMatcher(None, ca, cb).ratio()
    # Series titles often embed the core title ("Harry Potter and the ...").
    shorter, longer = sorted((ca, cb), key=len)
    if len(shorter) >= 4 and shorter in longer:
        ratio = max(ratio, 0.85)
    return ratio


def author_matches(wanted: Optional[str], candidates: Iterable[Optional[str]]) -> bool:
    """True if the wanted author's surname appears in any candidate author name."""
    if not wanted:
        return True
    tokens = [t for t in normalize(wanted).split() if len(t) > 2]
    if not tokens:
        return True
    surname = tokens[-1]
    for cand in candidates:
        cand_tokens = normalize(cand).split()
        if surname in cand_tokens:
            return True
    return False


def match_score(
    want_titles: Iterable[Optional[str]],
    want_author: Optional[str],
    cand_title: Optional[str],
    cand_authors: Iterable[Optional[str]],
) -> float:
    """Score in [0, 1]; 0 when the author clearly differs."""
    cand_authors = list(cand_authors)
    if cand_authors and not author_matches(want_author, cand_authors):
        return 0.0
    return max((title_similarity(t, cand_title) for t in want_titles if t), default=0.0)
