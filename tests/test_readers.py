import json
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from bookshelf.matching import fix_homoglyphs
from bookshelf.readers import OcrReader, OllamaReader

from .conftest import FakeResponse

FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def test_fix_homoglyphs():
    assert fix_homoglyphs("THE NAME ΟΕ ΤΗΕ ROSE") == "THE NAME OE THE ROSE"
    assert fix_homoglyphs("Ο ΜΙΚΡΟΣ ΠΡΙΓΚΙΠΑΣ") == "Ο ΜΙΚΡΟΣ ΠΡΙΓΚΙΠΑΣ"
    assert fix_homoglyphs("ZΟΡΜΠΑΣ") == "ΖΟΡΜΠΑΣ"


def _shelf(path, spines):
    font = ImageFont.truetype(str(FONT), 34)
    img = Image.new("RGB", (1000, 1000), (120, 85, 60))
    x = 60
    for text, rot in spines:
        sp = Image.new("RGB", (880, 130), (30, 50, 90))
        ImageDraw.Draw(sp).text((30, 45), text, font=font, fill=(240, 240, 230))
        img.paste(sp.rotate(rot, expand=True), (x, 60))
        x += 160
    img.save(path)


@pytest.mark.skipif(not OcrReader.available() or not FONT.exists(), reason="needs tesseract with Greek and DejaVu fonts")
def test_ocr_reads_vertical_spines_both_directions(tmp_path):
    photo = tmp_path / "shelf.png"
    _shelf(photo, [("Ο ΜΙΚΡΟΣ ΠΡΙΓΚΙΠΑΣ  ΣΑΙΝΤ-ΕΞΥΠΕΡΥ", 90), ("Pride and Prejudice  Jane Austen", 270),
                   ("1984   GEORGE ORWELL", 90)])
    spines = OcrReader().read([photo])
    assert [s.text for s in spines] == [
        "Ο ΜΙΚΡΟΣ ΠΡΙΓΚΙΠΑΣ ΣΑΙΝΤ-ΕΞΥΠΕΡΥ", "Pride and Prejudice Jane Austen", "1984 GEORGE ORWELL",
    ]
    assert [s.position for s in spines] == ["1st from left", "2nd from left", "3rd from left"]


class OllamaStub:
    def __init__(self, models, books):
        self.models, self.books, self.headers, self.posted = models, books, {}, []

    def get(self, url, **kw):
        return FakeResponse({"models": [{"name": m} for m in self.models]})

    def post(self, url, json=None, **kw):
        self.posted.append(json)
        return FakeResponse({"message": {"content": __import__("json").dumps({"books": self.books})}})


def test_ollama_reader(tmp_path):
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (3000, 2000)).save(photo)
    stub = OllamaStub(["qwen2.5vl:7b"], [{"title": "Ο Μικρός Πρίγκιπας", "author": "Σαιντ-Εξυπερύ",
                                         "position": "top shelf, 1st from left"}, {"title": "", "author": "", "position": ""}])
    reader = OllamaReader(session=stub)
    assert reader.available()
    spines = reader.read([photo])
    assert len(spines) == 1 and spines[0].title == "Ο Μικρός Πρίγκιπας" and spines[0].author == "Σαιντ-Εξυπερύ"
    req = stub.posted[0]
    assert req["model"] == "qwen2.5vl" and req["format"]["required"] == ["books"] and req["messages"][0]["images"]


def test_ollama_unavailable_without_model():
    assert not OllamaReader(session=OllamaStub(["llama3:8b"], [])).available()
