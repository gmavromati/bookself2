# Bookshelf Rater

Take a photo of your bookshelf and get back every book on it ranked by its **original rating**,
grouped by rating or popularity, even when your copies are translations.

**Completely free.** No paid APIs and no account needed. The photo is read on your own computer,
and books and ratings come from open databases (Wikidata, Open Library).

Example output (numbers are illustrative):

```
$ bookshelf scan shelf.jpg --html shelf.html

== Exceptional (1) ==
  #  Title                                     Author                   Rating  Ratings  Popularity  Sources
  1  Ο Μικρός Πρίγκιπας (Le Petit Prince)      Antoine de Saint-Exupéry   4.32      812  Blockbuster openlibrary

== Great (1) ==
  2  Το όνομα του ρόδου (Il nome della rosa)   Umberto Eco                4.13      190  Popular     openlibrary
...
```

## How it works

1. **Read the spines** on your computer, with one of two free readers:
   - **Tesseract OCR** (default). Works on any computer. The photo is read rotated both ways,
     since spine text runs vertically, and words are grouped into spines and shelves. It works well on
     clear, printed spines; decorative fonts and glossy reflections give it trouble.
   - **A local AI vision model through [Ollama](https://ollama.com)** (optional, recommended
     if your computer can run it). Much better on difficult spines. Used automatically when
     Ollama is running with the model installed.
2. **Find the original work.** The spine text is matched against **Wikidata**, which has book
   titles in many languages. A Greek *Ο Μικρός Πρίγκιπας* is matched to *Le Petit Prince* by
   Antoine de Saint-Exupéry (French, 1943). A match is only accepted when the title's words are
   really on the spine (allowing for OCR mistakes), so random OCR noise never becomes a book.
   **Open Library** is the fallback when Wikidata has nothing.
3. **Get the ratings of the original work**, pooled across all editions and translations:

   | Source | Cost | Notes |
   |---|---|---|
   | Open Library | free, no account | Always used. Ratings and "want to read / read" counts |
   | Google Books | free | Optional `GOOGLE_BOOKS_API_KEY`. Without it, a shared quota that is often used up |
   | Hardcover | free account | Optional `HARDCOVER_TOKEN` from https://hardcover.app/account/api |

   Goodreads has no public API, so its ratings aren't fetched. When Wikidata knows a book's
   Goodreads page, the report includes a **"see on Goodreads ↗"** link.
4. **Categorise:**
   - **Rating**: the average across sources, weighted by number of ratings.
   - **Score** (the default ranking): the rating adjusted for how many people rated it, so two
     5-star ratings don't outrank a classic with thousands.
   - **Rating tiers**: Exceptional ≥ 4.3 · Great ≥ 4.0 · Good ≥ 3.7 · Mixed ≥ 3.3 · Poor ·
     *Too few ratings* (< 5) · *Unrated*.
   - **Popularity tiers**: Blockbuster · Popular · Known · Niche · Obscure, each on the
     source's own scale.

## Install

1. **Python 3.10+** from https://www.python.org/downloads/ (on Windows, tick "Add Python to PATH").
2. **Tesseract OCR** with Greek, plus any other languages your books are in:
   - Windows: the installer from https://github.com/UB-Mannheim/tesseract/wiki. During setup,
     tick *Greek* under "Additional language data", and add `C:\Program Files\Tesseract-OCR`
     to PATH.
   - Mac: `brew install tesseract tesseract-lang`
   - Ubuntu/Debian: `sudo apt install tesseract-ocr tesseract-ocr-ell`
3. **This program:**
   ```bash
   git clone -b claude/bookshelf-rating-categorizer-8agh0d https://github.com/gmavromati/bookself2.git
   cd bookself2
   pip install -e .
   ```
4. *Optional, for much better reading:* install Ollama from https://ollama.com, then run
   `ollama pull qwen2.5vl`. This is a one-time download of about 6 GB, and it needs about
   8 GB of free memory. After that, `bookshelf scan` uses it automatically.

## Usage

```bash
# Scan a photo (several photos are fine; a book seen twice is counted once)
bookshelf scan shelf.jpg --html report.html

# Also save a spreadsheet / data file, group by popularity
bookshelf scan top.jpg bottom.jpg --group-by popularity --csv books.csv --json books.json

# Books in other languages: add their Tesseract language codes
bookshelf scan shelf.jpg --ocr-langs ell+eng+fra+deu

# Check what was recognised, fix mistakes, then rate
bookshelf scan shelf.jpg --detect-only > books.json     # edit books.json if needed
bookshelf rate books.json --html report.html

# No photo at all: type the books into a text file, one per line ("Title - Author")
bookshelf rate my_books.txt --html report.html

# One book
bookshelf lookup "Cien años de soledad" --author "García Márquez"
```

| Option | Default | |
|---|---|---|
| `--reader` | `auto` | `ollama`, `ocr`, or `auto` (Ollama if available, otherwise OCR) |
| `--ocr-langs` | `ell+eng` | Tesseract languages to read |
| `--sources` | `openlibrary,googlebooks,hardcover` | Hardcover is skipped without a token |
| `--sort` | `score` | `score`, `rating`, `popularity`, `title` |
| `--group-by` | `rating` | `rating`, `popularity`, `none` |
| `--json / --csv / --html PATH` | | write results to a file |
| `--no-cache` | | Lookups are cached in `~/.cache/bookshelf/ratings.json` |

The HTML report is a single page with three views (by rating, by popularity, ranked list),
links to each source, and light/dark mode.

## Tips for good photos

- Stand straight in front of the shelf, close enough that the spine text is easy to read on
  your phone screen. One shelf per photo is better than the whole bookcase.
- Use even light, and avoid flash and reflections on glossy spines.
- iPhone: set Settings → Camera → Formats → **Most Compatible** so photos are saved as JPG.
- Books the program wasn't sure about are marked *not identified for sure, please check*.
  Fix them in the `--detect-only` JSON, or list them in a text file.

## Development

```bash
pip install -e '.[dev]'
pytest
```

The tests use saved sample responses instead of the internet. The OCR test runs for real
when Tesseract with Greek is installed.

Layout: `bookshelf/readers/` (photo → spine text: `ocr.py`, `ollama.py`), `bookshelf/resolve.py`
(spine text → original work via Wikidata/Open Library), `bookshelf/sources/` (ratings),
`bookshelf/matching.py` (multilingual, OCR-tolerant matching), `bookshelf/scoring.py`
(tiers and ranking), `bookshelf/report.py` (table/JSON/CSV/HTML), `bookshelf/cli.py`.
