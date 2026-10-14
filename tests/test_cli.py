import json

from bookshelf import cli
from bookshelf.models import SourceRating

from .test_claude import DETECTED


class StubSource:
    name = "goodreads"

    def available(self):
        return True

    def lookup(self, book):
        return SourceRating(source="goodreads", average=4.32, ratings_count=2_100_000, url="https://gr/1")


def test_rate_command_writes_all_outputs(tmp_path, monkeypatch, capsys):
    books = tmp_path / "books.json"
    books.write_text(json.dumps(DETECTED["books"]), encoding="utf-8")
    monkeypatch.setattr(cli, "build_sources", lambda names, cache, model: [StubSource()])
    out_json, out_csv, out_html = tmp_path / "r.json", tmp_path / "r.csv", tmp_path / "r.html"
    code = cli.main(["rate", str(books), "--json", str(out_json), "--csv", str(out_csv),
                     "--html", str(out_html), "--no-cache"])
    assert code == 0
    table = capsys.readouterr().out
    assert "Exceptional" in table and "Le Petit Prince" in table and "Blockbuster" in table
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data[0]["rating_tier"] == "Exceptional"
    assert "Ο Μικρός Πρίγκιπας" in out_csv.read_text(encoding="utf-8")
    page = out_html.read_text(encoding="utf-8")
    assert "<title>My Bookshelf</title>" in page and "https://gr/1" in page

    # A previous full result file can be fed back in.
    assert cli.main(["rate", str(out_json), "--no-cache"]) == 0


def test_unknown_source_is_rejected(capsys):
    import pytest

    with pytest.raises(SystemExit):
        cli.main(["lookup", "Emma", "--sources", "amazon"])
