"""Data models shared across the pipeline."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class DetectedBook(BaseModel):
    """A book spotted in the shelf photo, identified as an original work where possible."""

    spine_text: str = Field(description="Text read from the spine/cover, verbatim.")
    title: str = Field(description="Title as printed on this edition.")
    author: Optional[str] = Field(default=None, description="Author as printed on this edition.")
    language: Optional[str] = Field(default=None, description="ISO 639-1 code of this edition.")
    original_title: str = Field(description="Title of the original work in its original language.")
    original_author: Optional[str] = Field(default=None, description="Author name in its usual Latin-script form.")
    original_language: Optional[str] = Field(default=None, description="ISO 639-1 code of the original work.")
    english_title: Optional[str] = Field(default=None, description="Best-known English title, if any.")
    first_published: Optional[int] = Field(default=None, description="Year the original work was first published.")
    position: Optional[str] = Field(default=None, description="Where on the shelf, e.g. 'top shelf, 3rd from left'.")
    confidence: Literal["high", "medium", "low"] = "medium"
    wikidata_id: Optional[str] = None
    openlibrary_work: Optional[str] = None  # e.g. "OL45883W"
    goodreads_url: Optional[str] = None

    @property
    def display_title(self) -> str:
        if self.original_title and self.original_title.strip().lower() != self.title.strip().lower():
            return f"{self.title} ({self.original_title})"
        return self.title

    @property
    def lookup_author(self) -> Optional[str]:
        return self.original_author or self.author


class SourceRating(BaseModel):
    """A rating found on one source for the original work."""

    source: str
    average: Optional[float] = None  # on a 0-5 scale
    ratings_count: Optional[int] = None
    popularity_count: Optional[int] = None  # e.g. people who shelved/read it
    matched_title: Optional[str] = None
    matched_author: Optional[str] = None
    url: Optional[str] = None


class RatedBook(BaseModel):
    """A detected book together with its ratings and categories."""

    book: DetectedBook
    ratings: list[SourceRating] = Field(default_factory=list)
    rating: Optional[float] = None  # combined average on a 0-5 scale
    ratings_count: int = 0
    score: Optional[float] = None  # Bayesian-adjusted rating used for ranking
    rating_tier: str = "Unrated"
    popularity_tier: str = "Unknown"
    popularity_rank: int = 0  # 0 = Unknown ... 5 = Blockbuster
