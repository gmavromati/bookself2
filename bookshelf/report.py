"""Render rated books as a terminal table, JSON, CSV or a standalone HTML page."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path

from .models import RatedBook
from .scoring import group_books, sort_books


def _fmt_count(n: int | None) -> str:
    if not n:
        return "-"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def text_table(books: list[RatedBook], group_by: str = "rating") -> str:
    lines = []
    header = f"{'#':>3}  {'Title':<46} {'Author':<24} {'Rating':>6} {'Ratings':>8}  {'Popularity':<11} Sources"
    rank = 0
    for tier, members in group_books(books, group_by):
        lines.append("")
        lines.append(f"== {tier} ({len(members)}) ==")
        lines.append(header)
        for b in members:
            rank += 1
            rating = f"{b.rating:.2f}" if b.rating is not None else "-"
            sources = ", ".join(r.source for r in b.ratings) or "-"
            lines.append(
                f"{rank:>3}  {_truncate(b.book.display_title, 46):<46} "
                f"{_truncate(b.book.lookup_author or '?', 24):<24} {rating:>6} "
                f"{_fmt_count(b.ratings_count):>8}  {b.popularity_tier:<11} {sources}"
            )
    return "\n".join(lines).lstrip("\n")


def to_json(books: list[RatedBook]) -> str:
    return json.dumps([b.model_dump() for b in books], ensure_ascii=False, indent=2)


CSV_FIELDS = [
    "title", "author", "original_title", "original_author", "original_language", "english_title",
    "language", "first_published", "rating", "ratings_count", "score", "rating_tier",
    "popularity_tier", "sources", "position", "confidence", "goodreads_url",
]


def write_csv(books: list[RatedBook], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for b in books:
            writer.writerow({
                "title": b.book.title,
                "author": b.book.author,
                "original_title": b.book.original_title,
                "original_author": b.book.original_author,
                "original_language": b.book.original_language,
                "english_title": b.book.english_title,
                "language": b.book.language,
                "first_published": b.book.first_published,
                "rating": b.rating,
                "ratings_count": b.ratings_count,
                "score": b.score,
                "rating_tier": b.rating_tier,
                "popularity_tier": b.popularity_tier,
                "sources": "; ".join(
                    f"{r.source} {r.average if r.average is not None else '-'} ({r.ratings_count or 0})"
                    for r in b.ratings
                ),
                "position": b.book.position,
                "confidence": b.book.confidence,
                "goodreads_url": b.book.goodreads_url,
            })


TIER_COLORS = {
    "Exceptional": "#1a7f37", "Great": "#2f9e44", "Good": "#5c940d", "Mixed": "#e67700",
    "Poor": "#c92a2a", "Too few ratings": "#868e96", "Unrated": "#868e96",
    "Blockbuster": "#5f3dc4", "Popular": "#1971c2", "Known": "#0c8599", "Niche": "#2b8a3e",
    "Obscure": "#868e96", "Unknown": "#868e96",
}

HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>My Bookshelf</title>
<style>
:root {{ --bg:#fafaf8; --fg:#1d1d1f; --muted:#6b6b70; --card:#fff; --line:#e4e4e0; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141416; --fg:#ececec; --muted:#a0a0a8; --card:#1e1e22; --line:#2e2e34; }} }}
body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
  font:15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }}
*, *::before, *::after {{ box-sizing:border-box; }}
main {{ max-width:1000px; margin:0 auto; }}
h1 {{ margin:0 0 4px; font-size:26px; }}
.sub {{ color:var(--muted); margin-bottom:16px; }}
.controls {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:20px; }}
.controls button {{ border:1px solid var(--line); background:var(--card); color:var(--fg);
  padding:6px 12px; border-radius:6px; cursor:pointer; font:inherit; }}
.controls button.on {{ border-color:var(--fg); font-weight:600; }}
h2 {{ font-size:18px; margin:24px 0 8px; }}
.book {{ display:grid; grid-template-columns:2.2em 1fr auto; gap:4px 12px; background:var(--card);
  border:1px solid var(--line); border-radius:8px; padding:10px 12px; margin-bottom:6px; }}
.book > * {{ min-width:0; overflow-wrap:anywhere; }}
.rank {{ color:var(--muted); font-variant-numeric:tabular-nums; }}
.title {{ font-weight:600; }}
.meta, .src {{ color:var(--muted); font-size:13px; }}
.src a {{ color:inherit; }}
.right {{ text-align:right; white-space:nowrap; }}
.stars {{ font-size:18px; font-weight:700; font-variant-numeric:tabular-nums; }}
.badge {{ display:inline-block; color:#fff; border-radius:999px; padding:1px 8px; font-size:12px; margin-left:4px; }}
.book > .src {{ grid-column:2 / 4; }}
@media (max-width:560px) {{ .book {{ grid-template-columns:2em 1fr; }} .right {{ grid-column:2; text-align:left; }} }}
</style></head><body><main>
<h1>My Bookshelf</h1>
<div class="sub">{count} books &middot; ratings are for the original work, pooled across editions and translations</div>
<div class="controls" id="controls">
  <button data-view="rating" class="on">By rating</button>
  <button data-view="popularity">By popularity</button>
  <button data-view="all">Ranked list</button>
</div>
{views}
</main>
<script>
document.getElementById('controls').addEventListener('click', e => {{
  const v = e.target.dataset.view; if (!v) return;
  document.querySelectorAll('#controls button').forEach(b => b.classList.toggle('on', b.dataset.view === v));
  document.querySelectorAll('section[data-view]').forEach(s => s.hidden = s.dataset.view !== v);
}});
</script></body></html>
"""


def _badge(tier: str) -> str:
    color = TIER_COLORS.get(tier, "#868e96")
    return f'<span class="badge" style="background:{color}">{html.escape(tier)}</span>'


def _book_html(rank: int, b: RatedBook) -> str:
    e = html.escape
    bk = b.book
    meta = [e(bk.lookup_author or "Unknown author")]
    if bk.original_title and bk.original_title.casefold() != bk.title.casefold():
        meta.append(f"original: <i>{e(bk.original_title)}</i>")
    if bk.english_title and bk.english_title.casefold() not in (bk.title.casefold(), bk.original_title.casefold()):
        meta.append(f"English: <i>{e(bk.english_title)}</i>")
    if bk.first_published:
        meta.append(str(bk.first_published))
    if bk.position:
        meta.append(e(bk.position))
    sources = []
    for r in b.ratings:
        label = f"{e(r.source)} {r.average:.2f} ({_fmt_count(r.ratings_count)})" if r.average else e(r.source)
        sources.append(f'<a href="{e(r.url)}" target="_blank" rel="noopener">{label}</a>' if r.url else label)
    if bk.goodreads_url:
        sources.append(f'<a href="{e(bk.goodreads_url)}" target="_blank" rel="noopener">see on Goodreads ↗</a>')
    rating = f"{b.rating:.2f}" if b.rating is not None else "–"
    return (
        f'<div class="book"><div class="rank">{rank}</div>'
        f'<div><div class="title">{e(bk.title)}</div><div class="meta">{" · ".join(meta)}</div></div>'
        f'<div class="right"><div class="stars">★ {rating}</div>'
        f'<div>{_badge(b.rating_tier)}{_badge(b.popularity_tier)}</div></div>'
        f'<div class="src">{" · ".join(sources) or "no ratings found"}'
        f'{" · not identified for sure, please check" if bk.confidence == "low" else ""}</div></div>'
    )


def _view(books: list[RatedBook], group_by: str, hidden: bool) -> str:
    parts = [f'<section data-view="{group_by}"{" hidden" if hidden else ""}>']
    rank = 0
    for tier, members in group_books(books, group_by):
        if group_by != "all":
            parts.append(f"<h2>{html.escape(tier)} <small>({len(members)})</small></h2>")
        for b in members:
            rank += 1
            parts.append(_book_html(rank, b))
    parts.append("</section>")
    return "\n".join(parts)


def to_html(books: list[RatedBook]) -> str:
    """`books` should already be sorted (e.g. by score)."""
    by_pop = sort_books(books, "popularity")
    views = "\n".join([
        _view(books, "rating", hidden=False),
        _view(by_pop, "popularity", hidden=True),
        _view(books, "all", hidden=True),
    ])
    return HTML_TEMPLATE.format(count=len(books), views=views)
