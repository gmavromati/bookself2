"""Tiny JSON file cache so repeated runs don't re-query the rating sources."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Optional


def default_cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(Path.home(), ".cache")
    return Path(base) / "bookshelf" / "ratings.json"


class JsonCache:
    def __init__(self, path: Optional[Path] = None, enabled: bool = True):
        self.path = path or default_cache_path()
        self.enabled = enabled
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        if enabled and self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._data = {}

    def get(self, key: str) -> Any:
        if not self.enabled:
            return None
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
