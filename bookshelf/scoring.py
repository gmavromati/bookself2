"""Combine per-source ratings and sort books into rating and popularity tiers."""

from __future__ import annotations

from typing import Iterable, Optional

from .models import DetectedBook, RatedBook, SourceRating

# Bayesian prior: a book with few ratings is pulled toward a typical rating so that
# one 5-star review doesn't outrank a classic with 100k ratings.
PRIOR_MEAN = 3.8
PRIOR_WEIGHT = 25
MIN_RATINGS_FOR_TIER = 5

RATING_TIERS: list[tuple[float, str]] = [
    (4.30, "Exceptional"),
    (4.00, "Great"),
    (3.70, "Good"),
    (3.30, "Mixed"),
    (0.00, "Poor"),
]
RATING_TIER_ORDER = [name for _, name in RATING_TIERS] + ["Too few ratings", "Unrated"]

POPULARITY_TIERS = ["Unknown", "Obscure", "Niche", "Known", "Popular", "Blockbuster"]
POPULARITY_TIER_ORDER = list(reversed(POPULARITY_TIERS))

# Count needed for Blockbuster, Popular, Known, Niche on each site (below Niche is Obscure).
# Every site has a very different number of users, so each gets its own scale.
POPULARITY_SCALES: dict[str, tuple[int, int, int, int]] = {
    "goodreads": (500_000, 50_000, 5_000, 500),
    "storygraph": (50_000, 5_000, 500, 50),
    "openlibrary": (5_000, 1_000, 150, 20),
    "hardcover": (5_000, 1_000, 150, 20),
    "googlebooks": (5_000, 500, 50, 5),
}
DEFAULT_SCALE = (50_000, 5_000, 500, 50)


def combine(ratings: Iterable[SourceRating]) -> tuple[Optional[float], int]:
    """Ratings-count-weighted average across sources, and the total number of ratings."""
    total = 0
    weighted = 0.0
    weight_sum = 0.0
    for r in ratings:
        if r.average is None or r.average <= 0:
            continue
        if r.ratings_count == 0:
            continue
        weight = r.ratings_count if r.ratings_count else 1
        weighted += r.average * weight
        weight_sum += weight
        total += r.ratings_count or 0
    if not weight_sum:
        return None, 0
    return round(weighted / weight_sum, 2), total


def bayesian(rating: Optional[float], count: int) -> Optional[float]:
    if rating is None:
        return None
    n = max(count, 1)
    return round((n * rating + PRIOR_WEIGHT * PRIOR_MEAN) / (n + PRIOR_WEIGHT), 3)


def rating_tier(rating: Optional[float], count: int) -> str:
    if rating is None:
        return "Unrated"
    if count < MIN_RATINGS_FOR_TIER:
        return "Too few ratings"
    for threshold, name in RATING_TIERS:
        if rating >= threshold:
            return name
    return "Poor"


def popularity_rank(ratings: Iterable[SourceRating]) -> int:
    """0 = Unknown ... 5 = Blockbuster; the best tier reached on any source."""
    best = 0
    for r in ratings:
        count = r.popularity_count if r.popularity_count is not None else r.ratings_count
        if count is None:
            continue
        scale = POPULARITY_SCALES.get(r.source, DEFAULT_SCALE)
        rank = 1  # Obscure
        for i, threshold in enumerate(scale):
            if count >= threshold:
                rank = 5 - i
                break
        best = max(best, rank)
    return best


def rate(book: DetectedBook, ratings: list[SourceRating]) -> RatedBook:
    rating, count = combine(ratings)
    rank = popularity_rank(ratings)
    return RatedBook(
        book=book,
        ratings=ratings,
        rating=rating,
        ratings_count=count,
        score=bayesian(rating, count),
        rating_tier=rating_tier(rating, count),
        popularity_tier=POPULARITY_TIERS[rank],
        popularity_rank=rank,
    )


SORT_KEYS = {
    "score": lambda b: (b.score is None, -(b.score or 0), -b.ratings_count),
    "rating": lambda b: (b.rating is None, -(b.rating or 0), -b.ratings_count),
    "popularity": lambda b: (-b.popularity_rank, -b.ratings_count, -(b.score or 0)),
    "title": lambda b: b.book.title.casefold(),
}


def sort_books(books: list[RatedBook], by: str = "score") -> list[RatedBook]:
    return sorted(books, key=SORT_KEYS[by])


def group_books(books: list[RatedBook], by: str) -> list[tuple[str, list[RatedBook]]]:
    """Group already-sorted books into tiers, in tier order. `by` is 'rating' or 'popularity'."""
    if by == "rating":
        order, attr = RATING_TIER_ORDER, "rating_tier"
    elif by == "popularity":
        order, attr = POPULARITY_TIER_ORDER, "popularity_tier"
    else:
        return [("All books", books)]
    groups = []
    for tier in order:
        members = [b for b in books if getattr(b, attr) == tier]
        if members:
            groups.append((tier, members))
    return groups
