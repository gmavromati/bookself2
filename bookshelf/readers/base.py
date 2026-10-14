from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class SpineText:
    """What a reader saw on one book.

    OCR only gives raw `text`; a vision model can also split it into `title` and `author`."""

    text: str
    position: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    confidence: str = "medium"
