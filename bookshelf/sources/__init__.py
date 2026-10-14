"""Rating sources. Each looks up the *original* work and returns a SourceRating or None."""

from .base import RatingSource
from .googlebooks import GoogleBooksSource
from .hardcover import HardcoverSource
from .openlibrary import OpenLibrarySource

__all__ = [
    "RatingSource",
    "GoogleBooksSource",
    "HardcoverSource",
    "OpenLibrarySource",
]
