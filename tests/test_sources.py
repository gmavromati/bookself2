import json

from bookshelf.cache import JsonCache
from bookshelf.sources import GoogleBooksSource, HardcoverSource, OpenLibrarySource

from .conftest import FakeResponse, FakeSession


def test_openlibrary_searches_original_title_and_picks_matching_work(greek_little_prince):
    session = FakeSession({
        "docs": [
            {"key": "/works/OL1W", "title": "Le Petit Prince Coloring Book", "author_name": ["Someone"],
             "ratings_average": 4.9, "ratings_count": 2, "readinglog_count": 3},
            {"key": "/works/OL2W", "title": "Le Petit Prince", "author_name": ["Antoine de Saint-Exupéry"],
             "ratings_average": 4.21, "ratings_count": 812, "readinglog_count": 9000},
        ]
    })
    r = OpenLibrarySource(session=session).lookup(greek_little_prince)
    assert r.average == 4.21 and r.ratings_count == 812 and r.popularity_count == 9000
    assert r.url == "https://openlibrary.org/works/OL2W"
    method, url, kwargs = session.calls[0]
    assert kwargs["params"]["title"] == "Le Petit Prince"
    assert kwargs["params"]["author"] == "Antoine de Saint-Exupéry"


def test_openlibrary_falls_back_to_english_title(greek_little_prince):
    session = FakeSession(
        {"docs": []},
        {"docs": [{"key": "/works/OL2W", "title": "The Little Prince", "author_name": ["Antoine de Saint-Exupéry"],
                   "ratings_average": 4.2, "ratings_count": 10}]},
    )
    r = OpenLibrarySource(session=session).lookup(greek_little_prince)
    assert r.matched_title == "The Little Prince"
    assert session.calls[1][2]["params"]["title"] == "The Little Prince"


def test_lookup_failure_returns_none_and_is_not_cached(greek_little_prince, tmp_path):
    cache = JsonCache(tmp_path / "c.json")
    src = OpenLibrarySource(session=FakeSession(FakeResponse({}, status=503)), cache=cache)
    assert src.lookup(greek_little_prince) is None
    assert cache.get(src.cache_key(greek_little_prince)) is None


def test_results_are_cached(greek_little_prince, tmp_path):
    cache = JsonCache(tmp_path / "c.json")
    doc = {"key": "/works/OL2W", "title": "Le Petit Prince", "author_name": ["Antoine de Saint-Exupéry"],
           "ratings_average": 4.2, "ratings_count": 10}
    session = FakeSession({"docs": [doc]})
    OpenLibrarySource(session=session, cache=cache).lookup(greek_little_prince)
    again = OpenLibrarySource(session=FakeSession(), cache=JsonCache(tmp_path / "c.json"))
    assert again.lookup(greek_little_prince).average == 4.2
    assert again.session.calls == []


def test_googlebooks_pools_matching_editions(greek_little_prince):
    session = FakeSession({"items": [
        {"id": "1", "volumeInfo": {"title": "Le Petit Prince", "authors": ["Antoine de Saint-Exupéry"],
                                    "averageRating": 4.0, "ratingsCount": 30, "infoLink": "http://g/1"}},
        {"id": "2", "volumeInfo": {"title": "Le petit prince", "authors": ["Saint-Exupéry"],
                                    "averageRating": 5.0, "ratingsCount": 10}},
        {"id": "3", "volumeInfo": {"title": "Unrelated", "authors": ["X"], "averageRating": 1.0, "ratingsCount": 99}},
    ]})
    r = GoogleBooksSource(session=session, api_key="k").lookup(greek_little_prince)
    assert r.ratings_count == 40 and r.average == 4.25 and r.url == "http://g/1"
    assert session.calls[0][2]["params"]["key"] == "k"


def test_hardcover_parses_search_results(greek_little_prince):
    results = {"hits": [{"document": {"title": "The Little Prince", "author_names": ["Antoine de Saint-Exupéry"],
                                      "rating": 4.1, "ratings_count": 700, "users_count": 3000,
                                      "slug": "the-little-prince"}}]}
    session = FakeSession({"data": {"search": {"results": json.dumps(results)}}})
    src = HardcoverSource(session=session, token="abc")
    r = src.lookup(greek_little_prince)
    assert r.average == 4.1 and r.popularity_count == 3000
    assert r.url == "https://hardcover.app/books/the-little-prince"
    assert session.calls[0][2]["headers"]["Authorization"] == "Bearer abc"


def test_hardcover_unavailable_without_token(monkeypatch):
    monkeypatch.delenv("HARDCOVER_TOKEN", raising=False)
    assert not HardcoverSource(session=FakeSession()).available()
