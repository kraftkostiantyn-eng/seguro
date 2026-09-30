"""Віддалені джерела дроп-листів (`seguro fetch`).

Конфіг `sources:` — список записів `{name, type, url?, enabled?}`:
- `url`     — будь-який txt/csv/json/zip зі списком доменів;
- `godaddy` — публічний дамп аукціонів GoDaddy (json.zip);
- `namejet` — щоденний список NameJet, у `url` можна вжити `{date:%m-%d-%Y}`.

URL-и джерел змінюються; якщо завантаження впало, виправте `url` у конфігу.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ..models import Candidate
from .files import iter_payload

log = logging.getLogger("seguro.sources")

DEFAULT_URLS = {
    "godaddy": "https://inventory.auctions.godaddy.com/all_expiring_auctions.json.zip",
    "namejet": "https://www.namejet.com/download/{date:%m-%d-%Y}.txt",
    "url": None,
}


def resolve_url(spec: dict[str, Any], now: datetime | None = None) -> str:
    url = spec.get("url") or DEFAULT_URLS.get(spec.get("type", "url"))
    if not url:
        raise ValueError(f"джерело {spec.get('name')}: не задано url")
    if "{date" in url:
        url = url.format(date=now or datetime.now(timezone.utc))
    return url


async def fetch_source(client: httpx.AsyncClient, spec: dict[str, Any]) -> list[Candidate]:
    url = resolve_url(spec)
    name = spec.get("name") or spec.get("type", "url")
    resp = await client.get(url)
    resp.raise_for_status()
    filename = httpx.URL(url).path.rsplit("/", 1)[-1] or name
    cands = list(iter_payload(resp.content, filename, name))
    log.info("джерело %s: %d доменів (%s)", name, len(cands), url)
    return cands


async def fetch_all(config: dict[str, Any],
                    transport: httpx.AsyncBaseTransport | None = None) -> list[Candidate]:
    specs = [s for s in config.get("sources") or [] if s.get("enabled", True)]
    if not specs:
        return []
    async with httpx.AsyncClient(
        timeout=config.get("http_timeout", 60.0), follow_redirects=True,
        headers={"User-Agent": "seguro/0.2 (domain research)"}, transport=transport,
    ) as client:
        outcomes = await asyncio.gather(
            *(fetch_source(client, s) for s in specs), return_exceptions=True
        )
    merged: dict[str, Candidate] = {}
    for spec, outcome in zip(specs, outcomes):
        if isinstance(outcome, BaseException):
            log.error("джерело %s не завантажилось: %s", spec.get("name"), outcome)
            continue
        for cand in outcome:
            merged.setdefault(cand.domain, cand)
    return list(merged.values())
