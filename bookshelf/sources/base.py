"""Common plumbing for rating sources."""

from __future__ import annotations

import logging
import threading
from typing import Optional

import requests

from ..cache import JsonCache
from ..models import DetectedBook, SourceRating

log = logging.getLogger(__name__)

USER_AGENT = "bookshelf-rater/0.1 (https://github.com/gmavromati/bookself2)"

# Below this title similarity a search hit is considered a different book.
MIN_MATCH = 0.72


class RatingSource:
    """Base class: subclasses implement `_lookup`; caching and error handling live here."""

    name = "base"

    def __init__(self, session: Optional[requests.Session] = None, cache: Optional[JsonCache] = None):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.cache = cache or JsonCache(enabled=False)
        self._down = False
        self._down_lock = threading.Lock()  # set after a connection failure or rate limit: stop trying this run

    def available(self) -> bool:
        return True

    def _mark_down(self) -> bool:
        """Mark this source unusable for the run; True only for the first caller (who logs it)."""
        with self._down_lock:
            first = not self._down
            self._down = True
            return first

    def cache_key(self, book: DetectedBook) -> str:
        if book.openlibrary_work or book.wikidata_id:
            return f"{self.name}|{book.openlibrary_work or ''}|{book.wikidata_id or ''}|{book.original_title}".casefold()
        return "|".join(
            [self.name, book.original_title or "", book.lookup_author or "", book.english_title or "", book.title]
        ).casefold()

    def lookup(self, book: DetectedBook) -> Optional[SourceRating]:
        key = self.cache_key(book)
        cached = self.cache.get(key)
        if cached is not None:
            return SourceRating.model_validate(cached) if cached else None
        if self._down:
            return None
        try:
            result = self._lookup(book)
        except (requests.ConnectionError, requests.Timeout) as exc:
            if self._mark_down():
                log.warning("%s is unreachable, skipping it for this run (%s)", self.name, type(exc).__name__)
            return None
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 429 and self._mark_down():
                log.warning("%s: daily quota used up, skipping it for this run%s", self.name,
                            " (set GOOGLE_BOOKS_API_KEY for your own quota)" if self.name == "googlebooks" else "")
            elif status != 429:
                log.warning("%s lookup failed for %r: %s", self.name, book.title, exc)
            return None  # don't cache transient failures
        except (requests.RequestException, ValueError, KeyError) as exc:
            log.warning("%s lookup failed for %r: %s", self.name, book.title, exc)
            return None
        self.cache.set(key, result.model_dump() if result else {})
        return result

    def _lookup(self, book: DetectedBook) -> Optional[SourceRating]:
        raise NotImplementedError

    @staticmethod
    def candidate_titles(book: DetectedBook) -> list[str]:
        """Titles to try, original first: ratings of the original work are what we want."""
        seen: list[str] = []
        for t in (book.original_title, book.english_title, book.title):
            if t and t.strip() and t.strip().casefold() not in (s.casefold() for s in seen):
                seen.append(t.strip())
        return seen
