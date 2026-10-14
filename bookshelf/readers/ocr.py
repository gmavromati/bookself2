"""Read spines with Tesseract OCR (free, offline).

Spine text usually runs vertically, so the photo is OCR'd rotated both ways; every word is
mapped back to photo coordinates, words are grouped into spines, and for each spine the reading
direction with the higher OCR confidence wins. Horizontal text (books lying flat, covers) is read
from the unrotated photo."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from ..matching import fix_homoglyphs
from .base import SpineText

MIN_WORD_CONF = 60
MIN_SPINE_CONF = 70
MAX_EDGE_PX = 3000


@dataclass
class Word:
    text: str
    conf: float
    orient: str  # "cw", "ccw" (vertical spines) or "flat"
    across: float  # photo coordinate perpendicular to the text line
    along: float  # photo coordinate along the text line
    order: float  # reading order within the rotated image
    height: float
    length: float  # extent along the text line

    @property
    def start(self) -> float:
        return self.along - self.length / 2

    @property
    def end(self) -> float:
        return self.along + self.length / 2


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


class OcrReader:
    name = "ocr"

    def __init__(self, langs: str = "ell+eng"):
        self.langs = langs

    @staticmethod
    def available() -> bool:
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def read(self, paths: list[Path]) -> list[SpineText]:
        spines: list[SpineText] = []
        for n, path in enumerate(paths, start=1):
            with Image.open(path) as img:
                img = ImageOps.exif_transpose(img).convert("L")
                if max(img.size) > MAX_EDGE_PX:
                    img.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), Image.LANCZOS)
                spines.extend(self.read_image(img, label=f"photo {n}" if len(paths) > 1 else None))
        return spines

    # -- OCR passes -------------------------------------------------------------------------

    def _ocr(self, img: Image.Image, psm: int) -> list[dict]:
        import pytesseract

        d = pytesseract.image_to_data(
            img, lang=self.langs, config=f"--psm {psm}", output_type=pytesseract.Output.DICT
        )
        out = []
        for i, text in enumerate(d["text"]):
            text = text.strip()
            conf = float(d["conf"][i])
            if not text or conf < MIN_WORD_CONF or not _useful(text, conf):
                continue
            out.append({"text": text, "conf": conf, "x": d["left"][i], "y": d["top"][i],
                        "w": d["width"][i], "h": d["height"][i]})
        return out

    def words(self, img: Image.Image) -> list[Word]:
        W, H = img.size
        words: list[Word] = []
        for psm in (3, 11):
            for raw in self._ocr(img.rotate(-90, expand=True), psm):  # text reading bottom-to-top
                cx, cy = raw["x"] + raw["w"] / 2, raw["y"] + raw["h"] / 2
                words.append(Word(raw["text"], raw["conf"], "cw", across=cy, along=H - cx, order=cx,
                                  height=raw["h"], length=raw["w"]))
            for raw in self._ocr(img.rotate(90, expand=True), psm):  # text reading top-to-bottom
                cx, cy = raw["x"] + raw["w"] / 2, raw["y"] + raw["h"] / 2
                words.append(Word(raw["text"], raw["conf"], "ccw", across=W - cy, along=cx, order=cx,
                                  height=raw["h"], length=raw["w"]))
            for raw in self._ocr(img, psm):
                if raw["h"] > 1.2 * raw["w"]:
                    continue  # Tesseract sometimes reads vertical text here too; the rotated passes cover it
                cx, cy = raw["x"] + raw["w"] / 2, raw["y"] + raw["h"] / 2
                words.append(Word(raw["text"], raw["conf"], "flat", across=cy, along=cx, order=cx,
                                  height=raw["h"], length=raw["w"]))
        return words

    # -- grouping ---------------------------------------------------------------------------

    def read_image(self, img: Image.Image, label: Optional[str] = None) -> list[SpineText]:
        words = self.words(img)
        vertical = [w for w in words if w.orient != "flat"]
        flat = [w for w in words if w.orient == "flat"]
        spines = [g for g in _group(vertical) if _good(g)]
        lines = [g for g in _group(flat) if _good(g)]

        # Shelves: spines on the same shelf overlap vertically; a shelf board leaves a gap between rows.
        spines.sort(key=lambda g: min(w.start for w in g))
        shelves: list[list[list[Word]]] = []
        shelf_end = float("-inf")
        for g in spines:
            start, end = min(w.start for w in g), max(w.end for w in g)
            if shelves and start < shelf_end:
                shelves[-1].append(g)
                shelf_end = max(shelf_end, end)
            else:
                shelves.append([g])
                shelf_end = end

        out: list[SpineText] = []
        for s_idx, shelf in enumerate(shelves, start=1):
            shelf.sort(key=lambda g: statistics.mean(w.across for w in g))
            for b_idx, g in enumerate(shelf, start=1):
                where = f"{_ordinal(b_idx)} from left"
                if len(shelves) > 1:
                    where = f"shelf {s_idx}, {where}"
                out.append(SpineText(text=_text(g), position=f"{label}, {where}" if label else where,
                                     confidence=_confidence(g)))
        for g in lines:
            where = "lying flat / cover"
            out.append(SpineText(text=_text(g), position=f"{label}, {where}" if label else where,
                                 confidence=_confidence(g)))
        return out


def _useful(text: str, conf: float) -> bool:
    letters = sum(c.isalpha() for c in text)
    digits = sum(c.isdigit() for c in text)
    return letters >= 2 or digits >= 3 or (letters == 1 and conf >= 90)


def _group(words: list[Word]) -> list[list[Word]]:
    """Cluster words into lines/spines: close in `across`, and no big gap in `along`."""
    if not words:
        return []
    h = statistics.median(w.height for w in words)
    clusters: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w.across):
        if clusters and abs(w.across - statistics.mean(x.across for x in clusters[-1])) <= 0.7 * h:
            clusters[-1].append(w)
        else:
            clusters.append([w])
    groups: list[list[Word]] = []
    for c in clusters:
        c.sort(key=lambda w: w.start)
        current = [c[0]]
        reach = c[0].end
        for w in c[1:]:
            if w.start - reach > 6 * h:  # big empty gap: a different shelf or book
                groups.append(current)
                current = [w]
            else:
                current.append(w)
            reach = max(reach, w.end)
        groups.append(current)
    return [_best_reading(g) for g in groups]


def _best_reading(group: list[Word]) -> list[Word]:
    """Keep the orientation that read best, and one copy of words seen by several OCR passes."""
    by_orient: dict[str, list[Word]] = {}
    for w in group:
        by_orient.setdefault(w.orient, []).append(w)
    best = max(by_orient.values(), key=lambda ws: sum(w.conf * len(w.text) for w in ws))
    best.sort(key=lambda w: w.order)
    kept: list[Word] = []
    for w in best:
        if kept and abs(w.order - kept[-1].order) < 0.6 * w.height:
            if w.conf > kept[-1].conf:
                kept[-1] = w
        else:
            kept.append(w)
    return kept


def _good(group: list[Word]) -> bool:
    letters = sum(c.isalnum() for w in group for c in w.text)
    return letters >= 4 and statistics.mean(w.conf for w in group) >= MIN_SPINE_CONF


def _text(group: list[Word]) -> str:
    return fix_homoglyphs(" ".join(w.text for w in group))


def _confidence(group: list[Word]) -> str:
    conf = statistics.mean(w.conf for w in group)
    return "high" if conf >= 88 else "medium" if conf >= 78 else "low"
