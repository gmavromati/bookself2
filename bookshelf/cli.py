"""Command line interface: `bookshelf scan shelf.jpg --html report.html`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import anthropic

from .cache import JsonCache
from .models import DetectedBook
from .pipeline import rate_books
from .report import text_table, to_html, to_json, write_csv
from .scoring import sort_books
from .sources import ClaudeWebSource, GoogleBooksSource, HardcoverSource, OpenLibrarySource, RatingSource
from .vision import DEFAULT_MODEL, DetectionError, detect_books

ALL_SOURCES = ("openlibrary", "googlebooks", "hardcover", "web")
DEFAULT_SOURCES = ("openlibrary", "googlebooks", "hardcover")


def build_sources(names: list[str], cache: JsonCache, model: str) -> list[RatingSource]:
    factories = {
        "openlibrary": lambda: OpenLibrarySource(cache=cache),
        "googlebooks": lambda: GoogleBooksSource(cache=cache),
        "hardcover": lambda: HardcoverSource(cache=cache),
        "web": lambda: ClaudeWebSource(cache=cache, model=model),
    }
    sources = [factories[n]() for n in names]
    for s in sources:
        if not s.available():
            print(f"note: skipping {s.name} (HARDCOVER_TOKEN not set)", file=sys.stderr)
    return sources


def _parse_sources(value: str) -> list[str]:
    names = [v.strip() for v in value.split(",") if v.strip()]
    bad = [n for n in names if n not in ALL_SOURCES]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown source(s): {', '.join(bad)}; choose from {', '.join(ALL_SOURCES)}")
    return names


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bookshelf",
        description="Identify the books in bookshelf photos and rank them by original rating and popularity.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_rating_options(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--sources", type=_parse_sources, default=list(DEFAULT_SOURCES),
                        help=f"comma-separated rating sources (default: {','.join(DEFAULT_SOURCES)}; also: web)")
        sp.add_argument("--web", action="store_true",
                        help="also look up Goodreads ratings via Claude web search (uses API credits per book)")
        sp.add_argument("--sort", choices=["score", "rating", "popularity", "title"], default="score",
                        help="ranking order (score = rating adjusted for number of ratings)")
        sp.add_argument("--group-by", choices=["rating", "popularity", "none"], default="rating")
        sp.add_argument("--json", type=Path, help="write results as JSON")
        sp.add_argument("--csv", type=Path, help="write results as CSV")
        sp.add_argument("--html", type=Path, help="write an HTML report")
        sp.add_argument("--no-cache", action="store_true", help="don't read or write the ratings cache")
        sp.add_argument("--workers", type=int, default=4, help="parallel lookups (default 4)")
        sp.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model (default {DEFAULT_MODEL})")
        sp.add_argument("-v", "--verbose", action="store_true")

    scan = sub.add_parser("scan", help="scan one or more shelf photos")
    scan.add_argument("photos", nargs="+", type=Path)
    scan.add_argument("--detect-only", action="store_true",
                      help="only identify the books; print them as JSON (re-use with `rate`)")
    add_rating_options(scan)

    rate = sub.add_parser("rate", help="rate a book list saved by `scan --detect-only` (skips the photo step)")
    rate.add_argument("books_json", type=Path)
    add_rating_options(rate)

    lookup = sub.add_parser("lookup", help="rate a single book by title")
    lookup.add_argument("title")
    lookup.add_argument("--author")
    lookup.add_argument("--original-title", help="title in the original language, if different")
    add_rating_options(lookup)
    return p


def _load_books(path: Path) -> list[DetectedBook]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("books", [])
    # Accept both a detection list and a previous full result (items with a "book" key).
    return [DetectedBook.model_validate(item.get("book", item)) for item in data]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    try:
        if args.command == "scan":
            for photo in args.photos:
                if not photo.is_file():
                    print(f"error: {photo} not found", file=sys.stderr)
                    return 2
            print(f"Reading spines in {len(args.photos)} photo(s) with Claude…", file=sys.stderr)
            books = detect_books(args.photos, model=args.model)
            print(f"Found {len(books)} books.", file=sys.stderr)
            if args.detect_only:
                print(json.dumps([b.model_dump() for b in books], ensure_ascii=False, indent=2))
                return 0
        elif args.command == "rate":
            books = _load_books(args.books_json)
        else:
            books = [DetectedBook(
                spine_text=args.title, title=args.title, author=args.author,
                original_title=args.original_title or args.title, original_author=args.author,
                confidence="high",
            )]
    except DetectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except anthropic.AuthenticationError:
        print("error: no valid Anthropic credentials. Set ANTHROPIC_API_KEY.", file=sys.stderr)
        return 1
    except anthropic.APIError as exc:
        print(f"error: Claude API request failed: {exc}", file=sys.stderr)
        return 1

    names = list(dict.fromkeys(args.sources + (["web"] if args.web else [])))
    sources = build_sources(names, JsonCache(enabled=not args.no_cache), args.model)

    def progress(i: int, n: int, book: DetectedBook) -> None:
        print(f"\rLooking up ratings {i}/{n}", end="" if i < n else "\n", file=sys.stderr, flush=True)

    rated = sort_books(rate_books(books, sources, workers=args.workers, progress=progress), args.sort)

    print(text_table(rated, args.group_by))
    if args.json:
        args.json.write_text(to_json(rated), encoding="utf-8")
        print(f"wrote {args.json}", file=sys.stderr)
    if args.csv:
        write_csv(rated, args.csv)
        print(f"wrote {args.csv}", file=sys.stderr)
    if args.html:
        args.html.write_text(to_html(rated), encoding="utf-8")
        print(f"wrote {args.html}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
