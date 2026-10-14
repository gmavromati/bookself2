"""Open Library (openlibrary.org): free, no key. Ratings are per *work*, i.e. pooled across
all editions and translations, which is exactly the "original rating" we want."""

from __future__ import annotations

from typing import Optional

from ..matching import match_score
from ..models import DetectedBook, SourceRating
from .base import MIN_MATCH, RatingSource

SEARCH_URL = "https://openlibrary.org/search.json"
FIELDS = "key,title,author_name,ratings_average,ratings_count,readinglog_count,first_publish_year"


class OpenLibrarySource(RatingSource):
    name = "openlibrary"

    def _lookup(self, book: DetectedBook) -> Optional[SourceRating]:
        titles = self.candidate_titles(book)
        author = book.lookup_author
        for title in titles:
            params = {"title": title, "fields": FIELDS, "limit": 10}
            if author:
                params["author"] = author
            resp = self.session.get(SEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
            best = self._best(resp.json().get("docs", []), titles, author)
            if best:
                return best
        return None

    @staticmethod
    def _best(docs: list[dict], titles: list[str], author: Optional[str]) -> Optional[SourceRating]:
        scored = []
        for doc in docs:
            score = match_score(titles, author, doc.get("title"), doc.get("author_name") or [])
            if score >= MIN_MATCH:
                scored.append((round(score, 1), doc.get("readinglog_count") or 0, doc))
        if not scored:
            return None
        _, _, doc = max(scored, key=lambda s: (s[0], s[1]))
        return SourceRating(
            source="openlibrary",
            average=doc.get("ratings_average"),
            ratings_count=doc.get("ratings_count"),
            popularity_count=doc.get("readinglog_count"),
            matched_title=doc.get("title"),
            matched_author=", ".join(doc.get("author_name") or []) or None,
            url=f"https://openlibrary.org{doc['key']}" if doc.get("key") else None,
        )
