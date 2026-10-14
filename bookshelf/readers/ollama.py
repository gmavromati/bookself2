"""Read spines with a local vision model through Ollama (free, runs on your computer).

Install Ollama from https://ollama.com, then `ollama pull qwen2.5vl` (about 6 GB; needs roughly
8 GB of free RAM). Much better than OCR at slanted, decorative or small spine text."""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageOps

from .base import SpineText

DEFAULT_MODEL = "qwen2.5vl"
MAX_EDGE_PX = 1800

PROMPT = """This is a photo of a bookshelf. List every book whose spine or cover text you can read, \
from left to right, top shelf first. The books can be in any language (for example Greek); copy \
the title and author exactly as printed, in the original script. Do not translate and do not guess \
books you cannot read. For position use e.g. "top shelf, 3rd from left"."""

SCHEMA = {
    "type": "object",
    "properties": {
        "books": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "author": {"type": "string"},
                    "position": {"type": "string"},
                },
                "required": ["title", "author", "position"],
            },
        }
    },
    "required": ["books"],
}


def ollama_url() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


class OllamaReader:
    name = "ollama"

    def __init__(self, model: str = DEFAULT_MODEL, session: Optional[requests.Session] = None):
        self.model = model
        self.session = session or requests.Session()

    def available(self) -> bool:
        """True if Ollama is running and the model has been pulled."""
        try:
            resp = self.session.get(f"{ollama_url()}/api/tags", timeout=3)
            resp.raise_for_status()
        except requests.RequestException:
            return False
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        want = self.model if ":" in self.model else f"{self.model}:"
        return any(n == self.model or n.startswith(want) for n in names)

    def read(self, paths: list[Path]) -> list[SpineText]:
        out: list[SpineText] = []
        for n, path in enumerate(paths, start=1):
            for book in self._read_one(path):
                position = book.get("position") or None
                if len(paths) > 1:
                    position = f"photo {n}, {position}" if position else f"photo {n}"
                title = (book.get("title") or "").strip()
                author = (book.get("author") or "").strip() or None
                if not title:
                    continue
                out.append(SpineText(
                    text=" ".join(x for x in (title, author) if x),
                    title=title, author=author, position=position,
                ))
        return out

    def _read_one(self, path: Path) -> list[dict]:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
        resp = self.session.post(
            f"{ollama_url()}/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": PROMPT,
                              "images": [base64.b64encode(buf.getvalue()).decode("ascii")]}],
                "format": SCHEMA,
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=600,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        return json.loads(content).get("books", [])
