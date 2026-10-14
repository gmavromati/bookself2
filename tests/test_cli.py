import json

import pytest

from bookshelf import cli
from bookshelf.models import DetectedBook, SourceRating
from bookshelf.readers import SpineText

BOOK = DetectedBook(
    spine_text="Ο ΜΙΚΡΟΣ ΠΡΙΓΚΙΠΑΣ", title="Ο Μικρός Πρίγκιπας", original_title="Le Petit Prince",
    original_author="Antoine de Saint-Exupéry", original_language="fr", english_title="The Little Prince",
    goodreads_url="https://www.goodreads.com/work/editions/2023003", confidence="high",
)


class StubSource:
    name = "openlibrary"

    def available(self):
        return True

    def lookup(self, book):
        return SourceRating(source="openlibrary", average=4.32, ratings_count=900, popularity_count=9000,
                            url="https://openlibrary.org/works/OL45883W")


@pytest.fixture
def stub_sources(monkeypatch):
    monkeypatch.setattr(cli, "build_sources", lambda names, cache: [StubSource()])


def test_rate_json_writes_all_outputs(tmp_path, stub_sources, capsys):
    books = tmp_path / "books.json"
    books.write_text(json.dumps([BOOK.model_dump()]), encoding="utf-8")
    out_json, out_csv, out_html = tmp_path / "r.json", tmp_path / "r.csv", tmp_path / "r.html"
    code = cli.main(["rate", str(books), "--json", str(out_json), "--csv", str(out_csv),
                     "--html", str(out_html), "--no-cache"])
    assert code == 0
    table = capsys.readouterr().out
    assert "Exceptional" in table and "Le Petit Prince" in table and "Blockbuster" in table
    assert json.loads(out_json.read_text(encoding="utf-8"))[0]["rating_tier"] == "Exceptional"
    assert "Ο Μικρός Πρίγκιπας" in out_csv.read_text(encoding="utf-8")
    page = out_html.read_text(encoding="utf-8")
    assert "<title>My Bookshelf</title>" in page and "see on Goodreads" in page
    # A previous full result file can be fed back in.
    assert cli.main(["rate", str(out_json), "--no-cache"]) == 0


def test_rate_text_file(tmp_path, stub_sources, monkeypatch, capsys):
    seen = []

    def fake_resolve(self, spine):
        seen.append((spine.title, spine.author))
        return BOOK
    monkeypatch.setattr(cli.Resolver, "resolve", fake_resolve)
    books = tmp_path / "books.txt"
    books.write_text("# my shelf\nΟ Μικρός Πρίγκιπας - Σαιντ-Εξυπερύ\nEmma by Jane Austen\n1984\n", encoding="utf-8")
    assert cli.main(["rate", str(books), "--no-cache"]) == 0
    assert sorted(seen) == sorted([("Ο Μικρός Πρίγκιπας", "Σαιντ-Εξυπερύ"), ("Emma", "Jane Austen"), ("1984", None)])


def test_scan_uses_reader_and_resolver(tmp_path, stub_sources, monkeypatch, capsys):
    photo = tmp_path / "shelf.jpg"
    photo.write_bytes(b"x")

    class Reader:
        name = "ocr"

        def read(self, paths):
            return [SpineText(text="Ο ΜΙΚΡΟΣ ΠΡΙΓΚΙΠΑΣ"), SpineText(text="Ο ΜΙΚΡΟΣ ΠΡΙΓΚΙΠΑΣ")]
    monkeypatch.setattr(cli, "pick_reader", lambda args: Reader())
    monkeypatch.setattr(cli.Resolver, "resolve", lambda self, spine: BOOK.model_copy(update={"wikidata_id": "Q25338"}))
    assert cli.main(["scan", str(photo), "--detect-only", "--no-cache"]) == 0
    detected = json.loads(capsys.readouterr().out)
    assert len(detected) == 1  # duplicates of the same work are merged


def test_parse_text_line():
    assert cli.parse_text_line("Cien años de soledad — Gabriel García Márquez").author == "Gabriel García Márquez"
    assert cli.parse_text_line("Anna Karenina").author is None


def test_unknown_source_is_rejected():
    with pytest.raises(SystemExit):
        cli.main(["lookup", "Emma", "--sources", "amazon"])
