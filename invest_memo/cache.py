"""단순 JSON 파일 캐시 (TTL 기반)."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable


class FileCache:
    def __init__(self, directory: Path | str = ".cache", ttl_seconds: int = 24 * 3600):
        self.directory = Path(directory)
        self.ttl = ttl_seconds

    def _path(self, key: str) -> Path:
        return self.directory / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if time.time() - payload.get("ts", 0) > self.ttl:
            return None
        return payload.get("data")

    def set(self, key: str, data: Any) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._path(key).write_text(
                json.dumps({"ts": time.time(), "data": data}, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass  # 캐시 실패는 치명적이지 않다


def cached(cache: FileCache | None, key: str, fetch: Callable[[], Any]) -> Any:
    """캐시에 있으면 반환, 없으면 fetch() 결과를 저장 후 반환."""
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return hit
    data = fetch()
    if cache is not None and data is not None:
        cache.set(key, data)
    return data
