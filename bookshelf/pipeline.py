"""Look up every detected book on every rating source and score it."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from .models import DetectedBook, RatedBook
from .scoring import rate
from .sources import RatingSource


def rate_books(
    books: list[DetectedBook],
    sources: list[RatingSource],
    workers: int = 4,
    progress: Optional[Callable[[int, int, DetectedBook], None]] = None,
) -> list[RatedBook]:
    active = [s for s in sources if s.available()]

    def one(book: DetectedBook) -> RatedBook:
        ratings = [r for r in (s.lookup(book) for s in active) if r is not None]
        return rate(book, ratings)

    results: list[RatedBook] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for i, rated in enumerate(pool.map(one, books), start=1):
            results.append(rated)
            if progress:
                progress(i, len(books), rated.book)
    return results
