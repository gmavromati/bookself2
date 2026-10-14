from bookshelf.readers import SpineText
from bookshelf.resolve import Resolver, sub_queries

from .conftest import FakeResponse

LITTLE_PRINCE = {
    "labels": {"en": {"value": "The Little Prince"}, "el": {"value": "Ο Μικρός Πρίγκιπας"},
               "fr": {"value": "Le Petit Prince"}},
    "aliases": {},
    "claims": {
        "P50": [{"mainsnak": {"datavalue": {"value": {"id": "Q2908"}}}}],
        "P1476": [{"mainsnak": {"datavalue": {"value": {"text": "Le Petit Prince", "language": "fr"}}}}],
        "P577": [{"mainsnak": {"datavalue": {"value": {"time": "+1943-04-06T00:00:00Z"}}}}],
        "P648": [{"mainsnak": {"datavalue": {"value": "OL45883W"}}}],
        "P8383": [{"mainsnak": {"datavalue": {"value": "2023003"}}}],
    },
}
GREEK_EDITION = {  # an edition item that points to the work with P629
    "labels": {"el": {"value": "Ο μικρός πρίγκιπας (Πατάκης)"}},
    "claims": {"P50": [{"mainsnak": {"datavalue": {"value": {"id": "Q2908"}}}}],
               "P629": [{"mainsnak": {"datavalue": {"value": {"id": "Q25338"}}}}]},
}
SAINT_EX = {"labels": {"en": {"value": "Antoine de Saint-Exupéry"}, "el": {"value": "Αντουάν ντε Σαιντ-Εξυπερύ"}},
            "aliases": {"el": [{"value": "Σαιντ-Εξυπερύ"}]}}
UNRELATED = {"labels": {"en": {"value": "Prince Caspian"}},
             "claims": {"P50": [{"mainsnak": {"datavalue": {"value": {"id": "Q1"}}}}]}}
ENTITIES = {"Q25338": LITTLE_PRINCE, "Q999": GREEK_EDITION, "Q2908": SAINT_EX, "Q7": UNRELATED,
            "Q1": {"labels": {"en": {"value": "C. S. Lewis"}}}}


class WikidataStub:
    """Answers Wikidata API calls from ENTITIES; search returns `hits` for any query."""

    def __init__(self, hits, ol_docs=()):
        self.hits = hits
        self.ol_docs = list(ol_docs)
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, **kwargs):
        self.calls.append(params)
        if "openlibrary" in url:
            return FakeResponse({"docs": self.ol_docs})
        if params.get("list") == "search":
            return FakeResponse({"query": {"search": [{"title": h} for h in self.hits]}})
        ids = params["ids"].split("|")
        return FakeResponse({"entities": {i: ENTITIES.get(i, {"missing": ""}) for i in ids}})


def test_greek_spine_resolves_to_original_work():
    r = Resolver(session=WikidataStub(["Q7", "Q999"]))
    book = r.resolve(SpineText(text="Ο ΜΙΚΡΟΣ ΠΡΙΓΚΙΠΑΣ ΣΑΙΝΤ-ΕΞΥΠΕΡΥ", position="1st from left"))
    assert book.wikidata_id == "Q25338"  # followed the edition to its work
    assert book.original_title == "Le Petit Prince" and book.original_language == "fr"
    assert book.english_title == "The Little Prince" and book.original_author == "Antoine de Saint-Exupéry"
    assert book.title == "Ο Μικρός Πρίγκιπας"  # as printed on this copy
    assert book.first_published == 1943 and book.openlibrary_work == "OL45883W"
    assert book.goodreads_url == "https://www.goodreads.com/work/editions/2023003"
    assert book.position == "1st from left" and book.confidence == "high"


def test_structured_title_and_author():
    r = Resolver(session=WikidataStub(["Q25338"]))
    book = r.resolve(SpineText(text="", title="Ο Μικρός Πρίγκιπας", author="Σαιντ-Εξυπερύ"))
    assert book.wikidata_id == "Q25338" and book.title == "Ο Μικρός Πρίγκιπας"


def test_wrong_author_is_rejected():
    r = Resolver(session=WikidataStub(["Q25338"]))
    book = r.resolve(SpineText(text="", title="The Little Prince", author="Jane Austen"))
    assert book.wikidata_id is None and book.confidence == "low"


def test_ocr_noise_is_not_turned_into_a_book():
    r = Resolver(session=WikidataStub(["Q25338", "Q7"]))
    book = r.resolve(SpineText(text="VIEVNOW VINOdX"))
    assert book.wikidata_id is None and book.confidence == "low" and book.title == "VIEVNOW VINOdX"


def test_one_word_title_needs_the_author_on_the_spine():
    one_word = {"Q5": {"labels": {"en": {"value": "Prince"}},
                       "claims": {"P50": [{"mainsnak": {"datavalue": {"value": {"id": "Q1"}}}}]}}}
    ENTITIES.update(one_word)
    r = Resolver(session=WikidataStub(["Q5"]))
    assert r.resolve(SpineText(text="PRINCE PUBLISHING HOUSE")).wikidata_id is None


def test_openlibrary_fallback_when_wikidata_has_nothing():
    docs = [{"key": "/works/OL1168007W", "title": "Nineteen Eighty-Four", "author_name": ["George Orwell"],
             "first_publish_year": 1949},
            {"key": "/works/OL2W", "title": "1984", "author_name": ["George Orwell"]}]
    r = Resolver(session=WikidataStub([], ol_docs=docs))
    book = r.resolve(SpineText(text="1984 GEORGE ORWELL"))
    assert book.openlibrary_work == "OL2W" and book.original_author == "George Orwell"


def test_sub_queries_shrink_from_full_text():
    q = sub_queries("A B C D")
    assert q[0] == "A B C D" and "A B C" in q and "B C D" in q and "C D" in q
