"""Hardcover (hardcover.app): a Goodreads alternative with a public GraphQL API.
Needs a free API token from https://hardcover.app/account/api in HARDCOVER_TOKEN."""

from __future__ import annotations

import json
import os
from typing import Optional

from ..matching import match_score
from ..models import DetectedBook, SourceRating
from .base import MIN_MATCH, RatingSource

API_URL = "https://api.hardcover.app/v1/graphql"
QUERY = """
query Search($q: String!) {
  search(query: $q, query_type: "Book", per_page: 10) { results }
}
"""


class HardcoverSource(RatingSource):
    name = "hardcover"

    def __init__(self, *args, token: Optional[str] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.token = token or os.environ.get("HARDCOVER_TOKEN")

    def available(self) -> bool:
        return bool(self.token)

    def _lookup(self, book: DetectedBook) -> Optional[SourceRating]:
        token = self.token if self.token.lower().startswith("bearer ") else f"Bearer {self.token}"
        titles = self.candidate_titles(book)
        author = book.lookup_author
        for title in titles:
            q = f"{title} {author}" if author else title
            resp = self.session.post(
                API_URL,
                json={"query": QUERY, "variables": {"q": q}},
                headers={"Authorization": token, "Content-Type": "application/json"},
                timeout=20,
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("errors"):
                raise ValueError(payload["errors"][0].get("message", "GraphQL error"))
            results = payload["data"]["search"]["results"]
            if isinstance(results, str):
                results = json.loads(results)
            best = None
            for hit in results.get("hits", []):
                doc = hit.get("document", {})
                score = match_score(titles, author, doc.get("title"), doc.get("author_names") or [])
                if score < MIN_MATCH:
                    continue
                key = (round(score, 1), doc.get("users_count") or 0)
                if best is None or key > best[0]:
                    best = (key, doc)
            if best:
                doc = best[1]
                return SourceRating(
                    source="hardcover",
                    average=doc.get("rating") or None,
                    ratings_count=doc.get("ratings_count"),
                    popularity_count=doc.get("users_count"),
                    matched_title=doc.get("title"),
                    matched_author=", ".join(doc.get("author_names") or []) or None,
                    url=f"https://hardcover.app/books/{doc['slug']}" if doc.get("slug") else None,
                )
        return None
