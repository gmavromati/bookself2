# Bookshelf Rater

Take a photo of your bookshelf, and get back every book on it ranked by its **original rating**
and grouped by rating or popularity, even when your copies are translations.

```
$ bookshelf scan shelf.jpg --web --html shelf.html

== Exceptional (1) ==
  #  Title                                     Author                   Rating  Ratings  Popularity  Sources
  1  Ο Μικρός Πρίγκιπας (Le Petit Prince)      Antoine de Saint-Exupéry   4.32     2.1M  Blockbuster goodreads, openlibrary

== Great (1) ==
  2  Το όνομα του ρόδου (Il nome della rosa)   Umberto Eco                4.13   380.0k  Popular     goodreads
...
```

## How it works

1. **Read the spines.** The photo(s) go to Claude's vision model, which reads every legible
   spine in any language or script. For each book it works out the original work behind
   the edition: original title, author, original language, and best-known English title.
   A Greek *Ο Μικρός Πρίγκιπας* becomes *Le Petit Prince* by Antoine de Saint-Exupéry (fr).
2. **Find the original rating.** Each source is searched by the *original* title first, then
   the English title, then the title as printed. Search hits are fuzzy-matched on title and
   author surname, so editions of other books don't sneak in.

   | Source | Key needed | What it gives |
   |---|---|---|
   | `openlibrary` | none | Work-level rating (all editions and translations pooled) and reading-log count |
   | `googlebooks` | optional `GOOGLE_BOOKS_API_KEY` | Per-edition ratings; all matching editions are pooled |
   | `hardcover` | `HARDCOVER_TOKEN` ([get one](https://hardcover.app/account/api)) | Rating, ratings count, readers |
   | `web` (`--web`) | uses your Anthropic key | Claude searches the web for the work's **Goodreads** rating and count |

   Goodreads has no public API, but it is where most reader ratings are, so `--web` is the most
   complete option. It makes one Claude request with web search per book, which costs API credits.
3. **Combine and categorise.**
   - **Rating**: average across sources, weighted by number of ratings.
   - **Score** (default sort order): the rating with a Bayesian adjustment, so a book with
     two 5-star ratings doesn't outrank a classic with a million.
   - **Rating tier**: Exceptional ≥ 4.3 · Great ≥ 4.0 · Good ≥ 3.7 · Mixed ≥ 3.3 · Poor ·
     *Too few ratings* (< 5) · *Unrated*.
   - **Popularity tier**: Blockbuster · Popular · Known · Niche · Obscure. Each site has its
     own scale (2,000 Open Library readers is a lot; 2,000 Goodreads ratings is niche), and a
     book gets the highest tier it reaches on any source.

## Install

Requires Python 3.10+.

```bash
pip install -e .            # or: pip install -e '.[dev]' to run the tests
export ANTHROPIC_API_KEY=sk-ant-...
# optional, for more and better rating data:
export GOOGLE_BOOKS_API_KEY=...
export HARDCOVER_TOKEN=...
```

## Usage

```bash
# Scan a shelf (several photos of the same bookcase are fine; overlaps are de-duplicated)
bookshelf scan shelf1.jpg shelf2.jpg --web --html report.html --csv books.csv --json books.json

# Group by popularity instead of rating, or rank by popularity
bookshelf scan shelf.jpg --group-by popularity --sort popularity

# Check or correct the detected list before rating it
bookshelf scan shelf.jpg --detect-only > books.json   # edit if needed...
bookshelf rate books.json --web --html report.html

# Rate a single book
bookshelf lookup "Cien años de soledad" --author "Gabriel García Márquez" --web
```

Options shared by `scan`, `rate` and `lookup`:

| Option | Default | |
|---|---|---|
| `--sources` | `openlibrary,googlebooks,hardcover` | comma-separated; add `web` or use `--web` |
| `--sort` | `score` | `score`, `rating`, `popularity`, `title` |
| `--group-by` | `rating` | `rating`, `popularity`, `none` |
| `--json / --csv / --html PATH` | | write results to a file |
| `--model` | `claude-opus-5-5` | Claude model used for photos and web lookups |
| `--no-cache` | | ratings are cached in `~/.cache/bookshelf/ratings.json` |

The HTML report is a single self-contained page with three views (by rating, by popularity,
ranked list), links to each source page, and light/dark mode.

## Tips for good photos

- Shoot straight on, with spines in focus and evenly lit. One shelf per photo works best
  for large bookcases.
- Books marked *low-confidence identification* in the report were partly guessed. Check
  them, or fix them in the `--detect-only` JSON and re-run `rate`.

## Development

```bash
pip install -e '.[dev]'
pytest
```

The tests use fake HTTP sessions and a fake Claude client, so they need no network or API key.

Layout: `bookshelf/vision.py` (photo → books), `bookshelf/sources/` (one module per rating
site), `bookshelf/matching.py` (cross-language title/author matching), `bookshelf/scoring.py`
(combining, tiers, sorting), `bookshelf/report.py` (table/JSON/CSV/HTML), `bookshelf/cli.py`.
