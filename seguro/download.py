"""Завантаження великих файлів (топ-списки, дроп-листи) на диск із простим TTL."""

from __future__ import annotations

import io
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator

import httpx


async def download(client: httpx.AsyncClient, url: str, dest: Path, max_age_days: float) -> Path:
    """Скачує `url` у `dest`, якщо файлу нема або він старіший за `max_age_days`."""
    if dest.exists() and time.time() - dest.stat().st_mtime < max_age_days * 86400:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    async with client.stream("GET", url) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as fh:
            async for chunk in resp.aiter_bytes():
                fh.write(chunk)
    tmp.replace(dest)
    return dest


def _first_table_member(zf: zipfile.ZipFile) -> str:
    names = [n for n in zf.namelist() if not n.endswith("/")]
    for name in names:
        if name.lower().endswith((".csv", ".txt", ".json")):
            return name
    if not names:
        raise ValueError("порожній zip")
    return names[0]


@contextmanager
def open_text(path: Path) -> Iterator[IO[str]]:
    """Відкриває текстовий файл або перший табличний файл усередині zip."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf, zf.open(_first_table_member(zf)) as raw:
            yield io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
    else:
        with path.open(encoding="utf-8", errors="replace") as fh:
            yield fh
