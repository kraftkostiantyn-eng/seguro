"""SQLite-кеш HTTP-відповідей, щоб повторні прогони не витрачали ліміти API."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import httpx


class HttpCache:
    def __init__(self, path: str | Path, ttl_days: float = 14):
        self.ttl = ttl_days * 86400
        self.conn = sqlite3.connect(str(path))
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS http_cache ("
            " key TEXT PRIMARY KEY, status INTEGER, body TEXT, ts REAL)"
        )

    def get(self, key: str) -> tuple[int, str] | None:
        row = self.conn.execute(
            "SELECT status, body, ts FROM http_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None or time.time() - row[2] > self.ttl:
            return None
        return row[0], row[1]

    def put(self, key: str, status: int, body: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO http_cache (key, status, body, ts) VALUES (?, ?, ?, ?)",
            (key, status, body, time.time()),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class CachedClient:
    """Обгортка над httpx.AsyncClient: кешує GET за повним URL (без секретних заголовків)."""

    def __init__(self, client: httpx.AsyncClient, cache: HttpCache | None, retries: int = 3,
                 host_limits: dict[str, int] | None = None):
        self.client = client
        self.cache = cache
        self.retries = retries
        # Окремі ліміти паралельності для хостів, що банять за частоту (web.archive.org).
        self._host_sems = {h: asyncio.Semaphore(n) for h, n in (host_limits or {}).items()}

    async def _request(self, url: str, params: dict | None, headers: dict | None) -> httpx.Response:
        sem = self._host_sems.get(httpx.URL(url).host)
        if sem is None:
            return await self.client.get(url, params=params, headers=headers)
        async with sem:
            return await self.client.get(url, params=params, headers=headers)

    async def get(self, url: str, *, params: dict | None = None, headers: dict | None = None,
                  cache_key_params: dict | None = None) -> tuple[int, str]:
        """Повертає (status, text). `cache_key_params` дозволяє виключити ключі API з ключа кешу."""
        key = str(httpx.URL(url, params=cache_key_params if cache_key_params is not None else params))
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                return hit

        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                resp = await self._request(url, params, headers)
            except httpx.TransportError as exc:
                last_exc = exc
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp
                    )
                else:
                    if self.cache is not None:
                        self.cache.put(key, resp.status_code, resp.text)
                    return resp.status_code, resp.text
            if attempt + 1 < self.retries:
                await asyncio.sleep(2 ** attempt)
        assert last_exc is not None
        raise last_exc
