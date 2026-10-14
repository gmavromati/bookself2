"""Rating sources. Each looks up the *original* work and returns a SourceRating or None."""

from .base import RatingSource
from .claude_web import ClaudeWebSource
from .googlebooks import GoogleBooksSource
from .hardcover import HardcoverSource
from .openlibrary import OpenLibrarySource

__all__ = [
    "RatingSource",
    "ClaudeWebSource",
    "GoogleBooksSource",
    "HardcoverSource",
    "OpenLibrarySource",
]
