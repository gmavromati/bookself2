"""Google Books: ratings are per *edition*, so we pool every edition of the work that matches.
Works without a key but the anonymous quota is shared and often exhausted; set
GOOGLE_BOOKS_API_KEY for reliable results."""

from __future__ import annotations

import os
from typing import Optional

from ..matching import match_score
from ..models import DetectedBook, SourceRating
from .base import MIN_MATCH, RatingSource

SEARCH_URL = "https://www.googleapis.com/books/v1/volumes"


class GoogleBooksSource(RatingSource):
    name = "googlebooks"

    def __init__(self, *args, api_key: Optional[str] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = api_key or os.environ.get("GOOGLE_BOOKS_API_KEY")

    def _lookup(self, book: DetectedBook) -> Optional[SourceRating]:
        titles = self.candidate_titles(book)
        author = book.lookup_author
        total = 0
        weighted = 0.0
        best_item = None
        seen_ids: set[str] = set()
        for title in titles:
            q = f'intitle:"{title}"' + (f' inauthor:"{author}"' if author else "")
            params = {"q": q, "maxResults": 20, "printType": "books"}
            if self.api_key:
                params["key"] = self.api_key
            resp = self.session.get(SEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                if item.get("id") in seen_ids:
                    continue
                seen_ids.add(item.get("id"))
                info = item.get("volumeInfo", {})
                count = info.get("ratingsCount") or 0
                avg = info.get("averageRating")
                if not count or avg is None:
                    continue
                if match_score(titles, author, info.get("title"), info.get("authors") or []) < MIN_MATCH:
                    continue
                total += count
                weighted += avg * count
                if best_item is None or count > (best_item["volumeInfo"].get("ratingsCount") or 0):
                    best_item = item
        if not total or best_item is None:
            return None
        info = best_item["volumeInfo"]
        return SourceRating(
            source="googlebooks",
            average=round(weighted / total, 2),
            ratings_count=total,
            popularity_count=total,
            matched_title=info.get("title"),
            matched_author=", ".join(info.get("authors") or []) or None,
            url=info.get("infoLink"),
        )
