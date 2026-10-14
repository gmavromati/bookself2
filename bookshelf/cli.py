"""Command line interface: `bookshelf scan shelf.jpg --html report.html`."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from .cache import JsonCache
from .models import DetectedBook
from .pipeline import identify, rate_books
from .readers import OcrReader, OllamaReader, SpineText
from .readers.ollama import DEFAULT_MODEL as DEFAULT_OLLAMA_MODEL
from .report import text_table, to_html, to_json, write_csv
from .resolve import Resolver
from .scoring import sort_books
from .sources import GoogleBooksSource, HardcoverSource, OpenLibrarySource, RatingSource

ALL_SOURCES = ("openlibrary", "googlebooks", "hardcover")


def build_sources(names: list[str], cache: JsonCache) -> list[RatingSource]:
    factories = {
        "openlibrary": lambda: OpenLibrarySource(cache=cache),
        "googlebooks": lambda: GoogleBooksSource(cache=cache),
        "hardcover": lambda: HardcoverSource(cache=cache),
    }
    return [factories[n]() for n in names]


def _parse_sources(value: str) -> list[str]:
    names = [v.strip() for v in value.split(",") if v.strip()]
    bad = [n for n in names if n not in ALL_SOURCES]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown source(s): {', '.join(bad)}; choose from {', '.join(ALL_SOURCES)}")
    return names


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bookshelf",
        description="Identify the books in bookshelf photos and rank them by original rating and popularity. "
                    "Everything runs on free tools and open data.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_rating_options(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--sources", type=_parse_sources, default=list(ALL_SOURCES),
                        help="comma-separated rating sources (default: all; hardcover needs HARDCOVER_TOKEN)")
        sp.add_argument("--sort", choices=["score", "rating", "popularity", "title"], default="score",
                        help="ranking order (score = rating adjusted for number of ratings)")
        sp.add_argument("--group-by", choices=["rating", "popularity", "none"], default="rating")
        sp.add_argument("--json", type=Path, help="write results as JSON")
        sp.add_argument("--csv", type=Path, help="write results as CSV")
        sp.add_argument("--html", type=Path, help="write an HTML report")
        sp.add_argument("--no-cache", action="store_true", help="don't read or write the lookup cache")
        sp.add_argument("--workers", type=int, default=4, help="parallel lookups (default 4)")
        sp.add_argument("-v", "--verbose", action="store_true")

    scan = sub.add_parser("scan", help="scan one or more shelf photos")
    scan.add_argument("photos", nargs="+", type=Path)
    scan.add_argument("--reader", choices=["auto", "ollama", "ocr"], default="auto",
                      help="how to read the photo: a local Ollama vision model, or Tesseract OCR "
                           "(default auto: Ollama if it is running with the model installed, else OCR)")
    scan.add_argument("--ollama-model", default=DEFAULT_OLLAMA_MODEL,
                      help=f"Ollama vision model (default {DEFAULT_OLLAMA_MODEL})")
    scan.add_argument("--ocr-langs", default="ell+eng",
                      help="Tesseract languages, e.g. ell+eng, eng+fra+deu (default ell+eng)")
    scan.add_argument("--detect-only", action="store_true",
                      help="only identify the books and print them as JSON (edit it, then use `rate`)")
    add_rating_options(scan)

    rate = sub.add_parser("rate", help="rate a book list: JSON from `scan --detect-only`, "
                                       "or a text file with one 'Title - Author' per line")
    rate.add_argument("books_file", type=Path)
    add_rating_options(rate)

    lookup = sub.add_parser("lookup", help="rate a single book by title (any language)")
    lookup.add_argument("title")
    lookup.add_argument("--author")
    add_rating_options(lookup)
    return p


def pick_reader(args) -> OcrReader | OllamaReader | None:
    ollama = OllamaReader(model=args.ollama_model)
    if args.reader in ("auto", "ollama") and ollama.available():
        return ollama
    if args.reader == "ollama":
        print(f"error: Ollama is not running or the model is missing. Install Ollama from https://ollama.com "
              f"and run: ollama pull {args.ollama_model}", file=sys.stderr)
        return None
    if not OcrReader.available():
        print("error: Tesseract OCR is not installed. See README (Install) for your system, "
              "or install Ollama for the better local reader.", file=sys.stderr)
        return None
    return OcrReader(langs=args.ocr_langs)


_SEPARATORS = re.compile(r"\s+(?:-|–|—|/|\|)\s+|\s+by\s+", re.IGNORECASE)


def parse_text_line(line: str) -> SpineText:
    parts = _SEPARATORS.split(line, maxsplit=1)
    title = parts[0].strip()
    author = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    return SpineText(text=line, title=title, author=author, confidence="high")


def load_books_file(path: Path, resolver: Resolver, workers: int) -> list[DetectedBook]:
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        lines = [l.strip() for l in raw.splitlines() if l.strip() and not l.strip().startswith("#")]
        return identify([parse_text_line(l) for l in lines], resolver, workers)
    if isinstance(data, dict):
        data = data.get("books", [])
    # Accept both a detection list and a previous full result (items with a "book" key).
    return [DetectedBook.model_validate(item.get("book", item)) for item in data]


def _progress(label: str):
    def show(i: int, n: int) -> None:
        print(f"\r{label} {i}/{n}", end="" if i < n else "\n", file=sys.stderr, flush=True)
    return show


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    cache = JsonCache(enabled=not args.no_cache)
    resolver = Resolver(cache=cache)

    if args.command == "scan":
        for photo in args.photos:
            if not photo.is_file():
                print(f"error: {photo} not found", file=sys.stderr)
                return 2
        reader = pick_reader(args)
        if reader is None:
            return 1
        print(f"Reading spines in {len(args.photos)} photo(s) with {reader.name}…", file=sys.stderr)
        try:
            spines = reader.read(args.photos)
        except Exception as exc:  # unreadable image, Ollama error, ...
            print(f"error: could not read the photo: {exc}", file=sys.stderr)
            return 1
        print(f"Read {len(spines)} spines.", file=sys.stderr)
        books = identify(spines, resolver, args.workers, _progress("Identifying books"))
        if args.detect_only:
            print(json.dumps([b.model_dump() for b in books], ensure_ascii=False, indent=2))
            return 0
    elif args.command == "rate":
        books = load_books_file(args.books_file, resolver, args.workers)
    else:
        books = identify([SpineText(text=args.title, title=args.title, author=args.author, confidence="high")],
                         resolver, 1)

    if not books:
        print("No books found. Try a sharper, straight-on photo, or list the books in a text file "
              "and use `bookshelf rate books.txt`.", file=sys.stderr)
        return 1

    sources = build_sources(args.sources, cache)
    rated = sort_books(rate_books(books, sources, args.workers, _progress("Looking up ratings")), args.sort)

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
