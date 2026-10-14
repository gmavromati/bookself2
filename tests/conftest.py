from __future__ import annotations

import pytest

from bookshelf.models import DetectedBook


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Returns queued payloads and records the requests made."""

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []
        self.headers = {}

    def _next(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        payload = self.payloads.pop(0) if self.payloads else {}
        return payload if isinstance(payload, FakeResponse) else FakeResponse(payload)

    def get(self, url, **kwargs):
        return self._next("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._next("POST", url, **kwargs)


@pytest.fixture
def greek_little_prince():
    return DetectedBook(
        spine_text="Ο ΜΙΚΡΟΣ ΠΡΙΓΚΙΠΑΣ  ΣΑΙΝΤ-ΕΞΥΠΕΡΥ",
        title="Ο Μικρός Πρίγκιπας",
        author="Αντουάν ντε Σαιντ-Εξυπερύ",
        language="el",
        original_title="Le Petit Prince",
        original_author="Antoine de Saint-Exupéry",
        original_language="fr",
        english_title="The Little Prince",
        first_published=1943,
        confidence="high",
    )
