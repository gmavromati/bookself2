"""Goodreads-style ratings via Claude with web search.

Goodreads has no public API, but it is where most "original" ratings live: it pools every
edition and translation of a work. This source asks Claude to search the web for the original
work's rating page and report the numbers through a strict tool. It costs API usage per book,
so it is opt-in (`--web`)."""

from __future__ import annotations

from typing import Optional

import anthropic

from ..models import DetectedBook, SourceRating
from ..vision import DEFAULT_MODEL
from .base import RatingSource, log

MAX_TURNS = 6

REPORT_TOOL = {
    "name": "report_rating",
    "description": (
        "Report the reader rating of the ORIGINAL work (all editions and translations pooled), "
        "preferably from Goodreads. Call it exactly once, with nulls for anything you could not find."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "site": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "e.g. goodreads"},
            "average": {"anyOf": [{"type": "number"}, {"type": "null"}], "description": "Average on a 0-5 scale."},
            "ratings_count": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "matched_title": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "matched_author": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "url": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["site", "average", "ratings_count", "matched_title", "matched_author", "url"],
        "additionalProperties": False,
    },
}

SYSTEM = (
    "You look up book ratings. Search the web for the given book's Goodreads page (or, if it has none, "
    "another large reader-rating site such as StoryGraph or a national equivalent). The rating must be "
    "for the original work, pooling all editions and translations, not for one translated edition. "
    "Read the average rating and the number of ratings from the page, then call report_rating once. "
    "Report only numbers you actually saw in search results; use null rather than guessing."
)


class ClaudeWebSource(RatingSource):
    name = "goodreads"

    def __init__(self, *args, client: Optional[anthropic.Anthropic] = None, model: str = DEFAULT_MODEL, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = client
        self.model = model

    def lookup(self, book: DetectedBook) -> Optional[SourceRating]:
        try:
            return super().lookup(book)
        except anthropic.APIError as exc:
            log.warning("web lookup failed for %r: %s", book.title, exc)
            return None

    def _lookup(self, book: DetectedBook) -> Optional[SourceRating]:
        client = self.client or anthropic.Anthropic()
        desc = [f"Original title: {book.original_title}"]
        if book.lookup_author:
            desc.append(f"Author: {book.lookup_author}")
        if book.english_title:
            desc.append(f"English title: {book.english_title}")
        if book.original_language:
            desc.append(f"Original language: {book.original_language}")
        if book.first_published:
            desc.append(f"First published: {book.first_published}")
        desc.append(f"(My copy is titled \"{book.title}\".)")
        messages: list = [{"role": "user", "content": "\n".join(desc)}]

        for _ in range(MAX_TURNS):
            response = client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM,
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}, REPORT_TOOL],
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=messages,
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "report_rating":
                    return self._to_rating(block.input)
            if response.stop_reason == "pause_turn":
                # Server-side search loop paused; resend so it can continue.
                messages = messages + [{"role": "assistant", "content": response.content}]
                continue
            return None
        return None

    def _to_rating(self, data: dict) -> Optional[SourceRating]:
        avg = data.get("average")
        if avg is None or not 0 <= float(avg) <= 5:
            return None
        count = data.get("ratings_count")
        return SourceRating(
            source=(data.get("site") or self.name).strip().lower(),
            average=round(float(avg), 2),
            ratings_count=count,
            popularity_count=count,
            matched_title=data.get("matched_title"),
            matched_author=data.get("matched_author"),
            url=data.get("url"),
        )
