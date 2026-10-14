"""Turn spine text into the original work, using free open data.

Wikidata knows most books' titles in many languages, so a Greek spine can be matched to the
work's item, which gives the original title, original language, author, year, and IDs for Open
Library and Goodreads. When Wikidata has nothing, Open Library's search is used instead.

A candidate is only accepted if its title words actually appear on the spine (tolerating OCR
errors), and preferably its author's surname too, so random OCR noise never becomes a book."""

from __future__ import annotations

import logging
import threading
import re
from dataclasses import dataclass
from typing import Optional

import requests

from .cache import JsonCache
from .matching import core_title, normalize, title_similarity, token_coverage
from .models import DetectedBook
from .readers.base import SpineText
from .sources.base import USER_AGENT

log = logging.getLogger(__name__)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
OPENLIBRARY_SEARCH = "https://openlibrary.org/search.json"

MIN_COVERAGE = 0.8
MAX_QUERIES_PER_SPINE = 8


@dataclass
class Candidate:
    titles: list[str]  # every known title/alias, any language
    authors: list[str]  # every known author name, any language
    book: DetectedBook  # filled in with the original-work details


class Resolver:
    def __init__(self, session: Optional[requests.Session] = None, cache: Optional[JsonCache] = None):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.cache = cache or JsonCache(enabled=False)
        self._down = False
        self._down_lock = threading.Lock()

    def _mark_down(self) -> bool:
        with self._down_lock:
            first = not self._down
            self._down = True
            return first

    # -- public -----------------------------------------------------------------------------

    def resolve(self, spine: SpineText) -> DetectedBook:
        """Best identification for a spine; falls back to the raw text if nothing matches."""
        found = None
        if not self._down:
            try:
                found = self._resolve(spine)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if self._mark_down():
                    log.warning("Wikidata/Open Library unreachable, books can't be identified this run (%s)",
                                type(exc).__name__)
            except (requests.RequestException, ValueError, KeyError) as exc:
                log.warning("could not identify %r: %s", spine.text, exc)
        if found:
            found.spine_text = spine.text
            found.position = spine.position
            if spine.title:
                found.title = spine.title
            found.author = spine.author or found.author
            if spine.confidence == "low":
                found.confidence = "medium"
            return found
        title = spine.title or spine.text
        return DetectedBook(
            spine_text=spine.text, title=title, author=spine.author, original_title=title,
            original_author=spine.author, position=spine.position, confidence="low",
        )

    # -- matching ---------------------------------------------------------------------------

    def _resolve(self, spine: SpineText) -> Optional[DetectedBook]:
        if spine.title:
            queries = [f"{spine.title} {spine.author or ''}".strip(), spine.title]
        else:
            queries = sub_queries(spine.text)
        for q in queries[:MAX_QUERIES_PER_SPINE]:
            best = self._pick(spine, self.wikidata_candidates(q))
            if best:
                return best
        for q in queries[:3]:
            best = self._pick(spine, self.openlibrary_candidates(q))
            if best:
                return best
        return None

    @staticmethod
    def score(spine: SpineText, cand: Candidate) -> tuple[float, Optional[str]]:
        """(score, matched title). Score 0 = reject; higher is a better, more specific match."""
        if spine.title:
            title_score, matched = max(((title_similarity(spine.title, t), t) for t in cand.titles), default=(0.0, None))
            if title_score < 0.85:
                return 0.0, None
            if spine.author and cand.authors and not any(
                token_coverage(_surname(a), normalize(spine.author).split()) for a in cand.authors
            ):
                return 0.0, None
            return title_score, matched

        tokens = normalize(spine.text).split()
        best, matched, best_words = 0.0, None, 0
        for t in cand.titles:
            core = core_title(t)
            if len(core.replace(" ", "")) < 4 and not core.isdigit():
                continue
            cov = token_coverage(core, tokens)
            if cov >= MIN_COVERAGE and cov + 0.05 * len(core.split()) > best:
                best, matched, best_words = cov + 0.05 * len(core.split()), t, len(core.split())
        if not best:
            return 0.0, None
        if any(token_coverage(_surname(a), tokens) == 1.0 for a in cand.authors if _surname(a)):
            return best + 1.0, matched
        # Without the author on the spine, a one-word title is too ambiguous to trust.
        return (best, matched) if best_words >= 2 else (0.0, None)

    def _pick(self, spine: SpineText, candidates: list[Candidate]) -> Optional[DetectedBook]:
        scored = [(*self.score(spine, c), i, c) for i, c in enumerate(candidates)]
        scored = [s for s in scored if s[0] > 0]
        if not scored:
            return None
        score, matched, _, cand = max(scored, key=lambda s: (s[0], -s[2]))
        book = cand.book.model_copy()
        book.title = matched or book.title  # the title as printed on this copy
        book.confidence = "high" if score >= 1.8 or (spine.title and score >= 0.95) else "medium"
        return book

    # -- Wikidata ---------------------------------------------------------------------------

    def _get(self, url: str, params: dict) -> dict:
        key = url + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        resp = self.session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        self.cache.set(key, data)
        return data

    def wikidata_candidates(self, query: str) -> list[Candidate]:
        # Full-text search over labels and aliases in every language; P50 = "has an author".
        data = self._get(WIKIDATA_API, {
            "action": "query", "list": "search", "srsearch": f"{query} haswbstatement:P50",
            "srnamespace": 0, "srlimit": 7, "format": "json",
        })
        ids = [hit["title"] for hit in data.get("query", {}).get("search", [])]
        if not ids:
            return []
        entities = self._entities(ids)
        # Editions/translations point to their work with P629; use the work instead.
        work_ids = {qid: (_claim_ids(e, "P629") or [qid])[0] for qid, e in entities.items()}
        missing = [w for w in work_ids.values() if w not in entities]
        if missing:
            entities.update(self._entities(missing))
        author_ids = sorted({a for e in entities.values() for a in _claim_ids(e, "P50")})
        authors = self._entities(author_ids) if author_ids else {}

        out, seen = [], set()
        for qid in ids:
            work_id = work_ids.get(qid, qid)
            if work_id in seen or work_id not in entities:
                continue
            seen.add(work_id)
            work = entities[work_id]
            names = [n for a in _claim_ids(work, "P50") for n in _all_names(authors.get(a, {}))]
            titles = _all_names(work) + _all_names(entities.get(qid, {}))
            out.append(Candidate(titles=titles, authors=names, book=_work_to_book(work_id, work, authors)))
        return out

    def _entities(self, ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for i in range(0, len(ids), 50):
            data = self._get(WIKIDATA_API, {
                "action": "wbgetentities", "ids": "|".join(ids[i:i + 50]),
                "props": "labels|aliases|claims", "format": "json",
            })
            out.update({k: v for k, v in data.get("entities", {}).items() if "missing" not in v})
        return out

    # -- Open Library -----------------------------------------------------------------------

    def openlibrary_candidates(self, query: str) -> list[Candidate]:
        data = self._get(OPENLIBRARY_SEARCH, {
            "q": query, "limit": 5,
            "fields": "key,title,subtitle,author_name,first_publish_year,language,id_goodreads",
        })
        out = []
        for doc in data.get("docs", []):
            title = doc.get("title")
            if not title:
                continue
            authors = doc.get("author_name") or []
            key = (doc.get("key") or "").rsplit("/", 1)[-1] or None
            out.append(Candidate(titles=[title], authors=authors, book=DetectedBook(
                spine_text=query, title=title, author=authors[0] if authors else None,
                original_title=title, original_author=authors[0] if authors else None,
                first_published=doc.get("first_publish_year"), openlibrary_work=key,
            )))
        return out


# -- helpers ------------------------------------------------------------------------------------

def sub_queries(text: str) -> list[str]:
    """The full spine text, then shorter runs of words (the spine may include publisher names or OCR junk)."""
    words = text.split()
    out = [text]
    for size in range(len(words) - 1, 1, -1):
        for start in range(0, len(words) - size + 1):
            out.append(" ".join(words[start:start + size]))
    if len(words) <= 2:
        out.extend(w for w in words if len(w) >= 4)
    return list(dict.fromkeys(out))


def _surname(name: str) -> str:
    tokens = [t for t in normalize(name).split() if len(t) > 2]
    return tokens[-1] if tokens else ""


def _all_names(entity: dict) -> list[str]:
    names = [v["value"] for v in entity.get("labels", {}).values()]
    names += [a["value"] for vals in entity.get("aliases", {}).values() for a in vals]
    return list(dict.fromkeys(names))


def _claims(entity: dict, prop: str) -> list:
    out = []
    for c in entity.get("claims", {}).get(prop, []):
        dv = c.get("mainsnak", {}).get("datavalue")
        if dv:
            out.append(dv["value"])
    return out


def _claim_ids(entity: dict, prop: str) -> list[str]:
    return [v["id"] for v in _claims(entity, prop) if isinstance(v, dict) and "id" in v]


def _label(entity: dict, langs=("en",)) -> Optional[str]:
    labels = entity.get("labels", {})
    for lang in langs:
        if lang in labels:
            return labels[lang]["value"]
    return next(iter(labels.values()), {}).get("value") if labels else None


def _work_to_book(qid: str, work: dict, authors: dict[str, dict]) -> DetectedBook:
    title_claims = [v for v in _claims(work, "P1476") if isinstance(v, dict) and "text" in v]
    english = work.get("labels", {}).get("en", {}).get("value")
    original_title = title_claims[0]["text"] if title_claims else (english or _label(work))
    original_lang = title_claims[0].get("language") if title_claims else None
    author_ids = _claim_ids(work, "P50")
    author = _label(authors.get(author_ids[0], {})) if author_ids else None
    years = []
    for v in _claims(work, "P577"):
        m = re.match(r"[+-]?(\d{1,4})-", v.get("time", "")) if isinstance(v, dict) else None
        if m:
            years.append(int(m.group(1)))
    ol = [v for v in _claims(work, "P648") if isinstance(v, str) and v.endswith("W")]
    goodreads = [v for v in _claims(work, "P8383") if isinstance(v, str)]
    return DetectedBook(
        spine_text="", title=original_title or qid, original_title=original_title or qid,
        original_author=author, original_language=original_lang, english_title=english,
        first_published=min(years) if years else None, wikidata_id=qid,
        openlibrary_work=ol[0] if ol else None,
        goodreads_url=f"https://www.goodreads.com/work/editions/{goodreads[0]}" if goodreads else None,
    )
