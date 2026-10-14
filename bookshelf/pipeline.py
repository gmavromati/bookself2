"""Photo -> spines -> original works -> ratings."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from .models import DetectedBook, RatedBook
from .readers import SpineText
from .resolve import Resolver
from .scoring import rate
from .sources import RatingSource

Progress = Optional[Callable[[int, int], None]]


def _run(fn, items: list, workers: int, progress: Progress) -> list:
    results = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for i, result in enumerate(pool.map(fn, items), start=1):
            results.append(result)
            if progress:
                progress(i, len(items))
    return results


def identify(spines: list[SpineText], resolver: Resolver, workers: int = 4, progress: Progress = None) -> list[DetectedBook]:
    books = _run(resolver.resolve, spines, workers, progress)
    # The same book can be seen twice (overlapping photos, or two readings of one spine).
    unique: dict[str, DetectedBook] = {}
    for b in books:
        key = b.wikidata_id or b.openlibrary_work or f"text:{b.spine_text}"
        if key not in unique or (unique[key].confidence == "low" and b.confidence != "low"):
            unique[key] = b
    return list(unique.values())


def rate_books(books: list[DetectedBook], sources: list[RatingSource], workers: int = 4,
               progress: Progress = None) -> list[RatedBook]:
    active = [s for s in sources if s.available()]

    def one(book: DetectedBook) -> RatedBook:
        return rate(book, [r for r in (s.lookup(book) for s in active) if r is not None])

    return _run(one, books, workers, progress)
