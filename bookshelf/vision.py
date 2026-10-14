"""Identify the books in one or more bookshelf photos using Claude's vision."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Iterable, Optional

import anthropic
from PIL import Image, ImageOps

from .models import DetectedBook

DEFAULT_MODEL = "claude-opus-5-5"

# Spines are small text, so keep plenty of resolution, but stay under the API's per-image limits.
MAX_EDGE_PX = 2576
MAX_IMAGE_BYTES = 4_500_000

SYSTEM_PROMPT = """\
You catalogue home libraries from photos. You will see one or more photos of bookshelves \
(or stacks of books). Identify every book whose spine or cover you can read, in any language \
or script.

For each book:
- Transcribe the visible spine/cover text verbatim, then give the title and author as printed \
on this edition.
- Work out which original work it is. Many books are translations: give the title in the \
original language and the author's name in its usual Latin-script form (e.g. a Greek edition \
"Ο Μικρός Πρίγκιπας" -> original_title "Le Petit Prince", original_author \
"Antoine de Saint-Exupéry", original_language "fr", english_title "The Little Prince"). If the \
edition is already the original, repeat its title.
- english_title is the best-known English title, or null if the work has no English edition you \
know of. first_published is the year the original work first appeared, or null if unsure.
- Use ISO 639-1 language codes.
- Describe its position so the owner can find it (e.g. "photo 1, top shelf, 3rd from left").
- confidence: "high" if the spine is clearly legible and you are sure of the work, "medium" if \
partly legible or the identification is a reasoned guess, "low" if mostly guessed.

List each physical book once; if photos overlap, do not double count. Skip items that are not \
books (boxes, ornaments) and spines with no legible text at all. Never invent books."""

_NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NULLABLE_INT = {"anyOf": [{"type": "integer"}, {"type": "null"}]}

DETECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "books": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "spine_text": {"type": "string"},
                    "title": {"type": "string"},
                    "author": _NULLABLE_STR,
                    "language": _NULLABLE_STR,
                    "original_title": {"type": "string"},
                    "original_author": _NULLABLE_STR,
                    "original_language": _NULLABLE_STR,
                    "english_title": _NULLABLE_STR,
                    "first_published": _NULLABLE_INT,
                    "position": _NULLABLE_STR,
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": [
                    "spine_text",
                    "title",
                    "author",
                    "language",
                    "original_title",
                    "original_author",
                    "original_language",
                    "english_title",
                    "first_published",
                    "position",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["books"],
    "additionalProperties": False,
}


class DetectionError(RuntimeError):
    pass


def encode_image(path: Path) -> tuple[str, str]:
    """Return (media_type, base64 data) for a photo, upright and resized to fit API limits."""
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        if max(img.size) > MAX_EDGE_PX:
            img.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), Image.LANCZOS)
        quality = 92
        while True:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            data = buf.getvalue()
            if len(data) <= MAX_IMAGE_BYTES or quality <= 50:
                break
            quality -= 10
    return "image/jpeg", base64.standard_b64encode(data).decode("ascii")


def build_content(paths: Iterable[Path]) -> list[dict]:
    content: list[dict] = []
    for i, path in enumerate(paths, start=1):
        media_type, data = encode_image(path)
        content.append({"type": "text", "text": f"Photo {i}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
    content.append({"type": "text", "text": "Identify every book on these shelves."})
    return content


def parse_detection(text: str) -> list[DetectedBook]:
    payload = json.loads(text)
    return [DetectedBook.model_validate(item) for item in payload["books"]]


def detect_books(
    paths: list[Path],
    client: Optional[anthropic.Anthropic] = None,
    model: str = DEFAULT_MODEL,
) -> list[DetectedBook]:
    """Send the photos to Claude and return the books it identified."""
    client = client or anthropic.Anthropic()
    # A full shelf can produce a long answer, so stream to avoid HTTP timeouts.
    with client.beta.messages.stream(
        model=model,
        max_tokens=64000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": DETECTION_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": build_content(paths)}],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        reason = getattr(details, "explanation", None) or "no explanation given"
        raise DetectionError(f"Claude declined to process the photo: {reason}")
    if response.stop_reason == "max_tokens":
        raise DetectionError("The answer was cut off (too many books?). Try fewer or closer-up photos per run.")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise DetectionError("Claude returned no book list.")
    return parse_detection(text)
