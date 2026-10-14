"""Vision detection and the web-search source, with a fake Anthropic client."""

import json
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from bookshelf.sources import ClaudeWebSource
from bookshelf.vision import DetectionError, detect_books, encode_image

DETECTED = {"books": [{
    "spine_text": "Ο ΜΙΚΡΟΣ ΠΡΙΓΚΙΠΑΣ", "title": "Ο Μικρός Πρίγκιπας", "author": "Σαιντ-Εξυπερύ",
    "language": "el", "original_title": "Le Petit Prince", "original_author": "Antoine de Saint-Exupéry",
    "original_language": "fr", "english_title": "The Little Prince", "first_published": 1943,
    "position": "photo 1, top shelf, 1st from left", "confidence": "high",
}]}


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


class FakeClient:
    def __init__(self, *messages):
        self.messages_out = list(messages)
        self.requests = []
        self.beta = NS(messages=NS(stream=self._stream, create=self._create))

    def _stream(self, **kwargs):
        self.requests.append(kwargs)
        return FakeStream(self.messages_out.pop(0))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.messages_out.pop(0)


def _msg(content, stop_reason="end_turn"):
    return NS(content=content, stop_reason=stop_reason, stop_details=None)


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "shelf.png"
    Image.new("RGB", (4000, 1000), "white").save(path)
    return path


def test_encode_image_downscales_to_jpeg(photo):
    media_type, data = encode_image(photo)
    assert media_type == "image/jpeg"
    import base64, io

    img = Image.open(io.BytesIO(base64.b64decode(data)))
    assert max(img.size) <= 2576


def test_detect_books_parses_structured_output(photo):
    client = FakeClient(_msg([NS(type="text", text=json.dumps(DETECTED))]))
    books = detect_books([photo], client=client)
    assert books[0].original_title == "Le Petit Prince"
    req = client.requests[0]
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert req["fallbacks"] == "default"
    assert [c["type"] for c in req["messages"][0]["content"]] == ["text", "image", "text"]


def test_detect_books_reports_refusal_and_truncation(photo):
    with pytest.raises(DetectionError):
        detect_books([photo], client=FakeClient(_msg([], "refusal")))
    with pytest.raises(DetectionError):
        detect_books([photo], client=FakeClient(_msg([], "max_tokens")))


def test_web_source_reads_report_tool(greek_little_prince):
    report = NS(type="tool_use", name="report_rating", input={
        "site": "Goodreads", "average": 4.32, "ratings_count": 2_100_000, "matched_title": "Le Petit Prince",
        "matched_author": "Antoine de Saint-Exupéry", "url": "https://www.goodreads.com/book/show/157993",
    })
    client = FakeClient(_msg([NS(type="text", text="searching")], "pause_turn"), _msg([report], "tool_use"))
    r = ClaudeWebSource(client=client).lookup(greek_little_prince)
    assert r.source == "goodreads" and r.average == 4.32 and r.ratings_count == 2_100_000
    # The paused turn is sent back so the search can continue.
    assert client.requests[1]["messages"][-1]["role"] == "assistant"
    assert "Le Petit Prince" in client.requests[0]["messages"][0]["content"]


def test_web_source_rejects_out_of_range(greek_little_prince):
    report = NS(type="tool_use", name="report_rating", input={
        "site": "goodreads", "average": 8.5, "ratings_count": 10, "matched_title": None,
        "matched_author": None, "url": None,
    })
    assert ClaudeWebSource(client=FakeClient(_msg([report], "tool_use"))).lookup(greek_little_prince) is None
