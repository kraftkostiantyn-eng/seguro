"""SQLite-кеш HTTP-відповідей і облік запитів, щоб повторні прогони не витрачали ліміти API."""

from __future__ import annotations

import asyncio
import hashlib
import json as jsonlib
import sqlite3
import time
from pathlib import Path
from typing import Any

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
    """Обгортка над httpx.AsyncClient: кеш за ключем, повтори, ліміти на хост, лічильники."""

    def __init__(self, client: httpx.AsyncClient, cache: HttpCache | None, retries: int = 3,
                 host_limits: dict[str, int] | None = None):
        self.client = client
        self.cache = cache
        self.retries = retries
        # Окремі ліміти паралельності для хостів, що банять за частоту (web.archive.org).
        self._host_sems = {h: asyncio.Semaphore(n) for h, n in (host_limits or {}).items()}
        # host -> {"requests": n, "cache_hits": n, "errors": n}
        self.stats: dict[str, dict[str, int]] = {}

    def _stat(self, host: str, key: str) -> None:
        self.stats.setdefault(host, {"requests": 0, "cache_hits": 0, "errors": 0})[key] += 1

    async def _send(self, method: str, url: str, params: Any, headers: dict | None,
                    json: Any) -> httpx.Response:
        sem = self._host_sems.get(httpx.URL(url).host)
        if sem is None:
            return await self.client.request(method, url, params=params, headers=headers, json=json)
        async with sem:
            return await self.client.request(method, url, params=params, headers=headers, json=json)

    @staticmethod
    def _backoff(attempt: int, resp: httpx.Response | None) -> float:
        if resp is not None and resp.headers.get("Retry-After", "").isdigit():
            return min(60.0, float(resp.headers["Retry-After"]))
        return float(2 ** attempt)

    async def request(self, method: str, url: str, *, params: Any = None,
                      headers: dict | None = None, json: Any = None,
                      cache_key: str | None = None) -> tuple[int, str]:
        """Повертає (status, text). `cache_key` задають явно, коли в запиті є секрети."""
        host = httpx.URL(url).host
        if cache_key is None:
            cache_key = f"{method} {httpx.URL(url, params=params)}"
            if json is not None:
                digest = hashlib.sha1(jsonlib.dumps(json, sort_keys=True).encode()).hexdigest()
                cache_key += f" {digest}"
        if self.cache is not None:
            hit = self.cache.get(cache_key)
            if hit is not None:
                self._stat(host, "cache_hits")
                return hit

        last_exc: Exception | None = None
        for attempt in range(self.retries):
            self._stat(host, "requests")
            resp: httpx.Response | None = None
            try:
                resp = await self._send(method, url, params, headers, json)
            except httpx.TransportError as exc:
                last_exc = exc
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp
                    )
                else:
                    if self.cache is not None:
                        self.cache.put(cache_key, resp.status_code, resp.text)
                    return resp.status_code, resp.text
            if attempt + 1 < self.retries:
                await asyncio.sleep(self._backoff(attempt, resp))
        self._stat(host, "errors")
        assert last_exc is not None
        raise last_exc

    async def get(self, url: str, *, params: Any = None, headers: dict | None = None,
                  cache_key_params: Any = None) -> tuple[int, str]:
        """`cache_key_params` дозволяє виключити ключі API з ключа кешу."""
        key_params = cache_key_params if cache_key_params is not None else params
        key = f"GET {httpx.URL(url, params=key_params)}"
        return await self.request("GET", url, params=params, headers=headers, cache_key=key)

    async def post_json(self, url: str, json: Any, *, params: Any = None,
                        headers: dict | None = None, cache_key: str | None = None) -> tuple[int, str]:
        return await self.request("POST", url, params=params, headers=headers, json=json,
                                  cache_key=cache_key)
