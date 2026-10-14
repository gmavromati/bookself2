from bookshelf.models import DetectedBook, SourceRating
from bookshelf.scoring import bayesian, combine, group_books, popularity_rank, rate, rating_tier, sort_books


def _book(title):
    return DetectedBook(spine_text=title, title=title, original_title=title)


def test_combine_weights_by_count():
    avg, total = combine([
        SourceRating(source="goodreads", average=4.3, ratings_count=900),
        SourceRating(source="openlibrary", average=3.3, ratings_count=100),
    ])
    assert avg == 4.2 and total == 1000


def test_combine_ignores_empty():
    assert combine([SourceRating(source="x", average=None, ratings_count=5)]) == (None, 0)
    assert combine([SourceRating(source="x", average=4.0, ratings_count=0)]) == (None, 0)


def test_bayesian_pulls_small_samples_to_prior():
    assert bayesian(5.0, 1) < 4.0
    assert abs(bayesian(4.5, 100_000) - 4.5) < 0.01


def test_rating_tiers():
    assert rating_tier(4.4, 100) == "Exceptional"
    assert rating_tier(4.1, 100) == "Great"
    assert rating_tier(3.8, 100) == "Good"
    assert rating_tier(3.5, 100) == "Mixed"
    assert rating_tier(2.9, 100) == "Poor"
    assert rating_tier(4.9, 2) == "Too few ratings"
    assert rating_tier(None, 0) == "Unrated"


def test_popularity_uses_per_source_scale():
    # 2,000 Open Library readers is a lot; 2,000 Goodreads ratings is niche.
    assert popularity_rank([SourceRating(source="openlibrary", popularity_count=2_000)]) == 4
    assert popularity_rank([SourceRating(source="goodreads", ratings_count=2_000)]) == 2
    assert popularity_rank([SourceRating(source="goodreads", ratings_count=3_000_000)]) == 5
    assert popularity_rank([]) == 0


def test_sort_and_group():
    a = rate(_book("A"), [SourceRating(source="goodreads", average=4.5, ratings_count=1_000_000)])
    b = rate(_book("B"), [SourceRating(source="goodreads", average=4.9, ratings_count=3)])
    c = rate(_book("C"), [])
    by_score = sort_books([b, c, a], "score")
    assert [x.book.title for x in by_score] == ["A", "B", "C"]
    groups = dict(group_books(by_score, "rating"))
    assert [x.book.title for x in groups["Exceptional"]] == ["A"]
    assert [x.book.title for x in groups["Too few ratings"]] == ["B"]
    assert [x.book.title for x in groups["Unrated"]] == ["C"]
    assert sort_books([b, c, a], "popularity")[0].book.title == "A"
