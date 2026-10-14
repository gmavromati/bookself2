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


# Greek capitals that look identical to Latin ones. OCR often mixes them up ("ΤΗΕ" for "THE").
_GREEK_TO_LATIN = str.maketrans("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ", "ABEZHIKMNOPTYX")
_LATIN_TO_GREEK = str.maketrans("ABEZHIKMNOPTYX", "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ")


def _script(ch: str) -> str:
    name = unicodedata.name(ch, "")
    if name.startswith("GREEK"):
        return "greek"
    if name.startswith("LATIN"):
        return "latin"
    return "other"


def fix_homoglyphs(line: str) -> str:
    """Make each word consistently Greek or Latin.

    A word containing a letter that only exists in one script is converted to that script; a word
    made only of look-alike letters follows the line's script when the line is clearly one script,
    and is left as OCR read it otherwise."""
    lookalikes = set("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧABEZHIKMNOPTYX")
    words = line.split()
    votes = {"greek": 0, "latin": 0}
    word_scripts = []
    for w in words:
        distinctive = [_script(c) for c in w if c.isalpha() and c not in lookalikes]
        s = max(("greek", "latin"), key=distinctive.count) if distinctive else None
        word_scripts.append(s)
        for d in distinctive:
            if d in votes:
                votes[d] += 1
    line_script = None
    if votes["greek"] and not votes["latin"]:
        line_script = "greek"
    elif votes["latin"] and not votes["greek"]:
        line_script = "latin"
    fixed = []
    for w, s in zip(words, word_scripts):
        target = s or line_script
        if target is None:
            fixed.append(w)
        else:
            fixed.append(w.translate(_GREEK_TO_LATIN if target == "latin" else _LATIN_TO_GREEK))
    return " ".join(fixed)


def skeleton(word: str) -> str:
    """Compare words by shape: Greek and Latin look-alike letters count as equal."""
    return word.upper().translate(_GREEK_TO_LATIN).lower()


def token_coverage(phrase: Optional[str], text_tokens: list[str]) -> float:
    """Fraction of the phrase's words found (fuzzily, to tolerate OCR errors) among text_tokens."""
    words = [skeleton(w) for w in normalize(phrase).split() if w]
    if not words:
        return 0.0
    text_tokens = [skeleton(t) for t in text_tokens]
    hit = 0
    for w in words:
        if any(w == t or (len(w) >= 4 and SequenceMatcher(None, w, t).ratio() >= 0.8) for t in text_tokens):
            hit += 1
    return hit / len(words)
