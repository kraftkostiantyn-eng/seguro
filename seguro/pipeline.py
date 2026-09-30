"""Воронка: кожен домен проходить етапи по черзі й зупиняється на першому відсіві."""

from __future__ import annotations

import asyncio
import csv
import logging
from pathlib import Path
from typing import Any, Iterable

import httpx

from .cache import CachedClient, HttpCache
from .checks import Check, Context, default_checks
from .models import Candidate, Result
from .scoring import score

log = logging.getLogger("seguro")

USER_AGENT = "seguro/0.1 (domain research)"


async def process(cand: Candidate, checks: list[Check], ctx: Context) -> Result:
    result = Result(domain=cand.domain)
    for check in checks:
        try:
            await check.run(cand, result, ctx)
        except Exception as exc:  # один збій не має валити весь прогін
            log.warning("%s: етап %s впав: %s", cand.domain, check.name, exc)
            result.flag(f"{check.name}_error")
        if result.rejected:
            return result

    result.score = score(result, ctx.config["scoring"]["weights"])
    if result.score is None:
        # Мережеві етапи не дали даних (помилки API) — не можна вважати домен кандидатом.
        result.reject("no_data", "недостатньо даних для оцінки, перезапустіть пізніше")
        return result
    min_score = ctx.config["scoring"]["min_score"]
    if result.score is not None and result.score < min_score:
        result.reject("scoring", f"оцінка {result.score} < {min_score}")
    return result


async def run_pipeline(
    candidates: Iterable[Candidate],
    config: dict[str, Any],
    checks: list[Check] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[Result]:
    checks = [c for c in (checks or default_checks())]
    cache = HttpCache(config["cache_path"], config["cache_ttl_days"]) if config.get("cache_path") else None
    async with httpx.AsyncClient(
        timeout=config["http_timeout"],
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        transport=transport,
    ) as client:
        ctx = Context(
            config=config,
            http=CachedClient(client, cache, host_limits=config.get("host_limits")),
        )
        checks = [c for c in checks if c.enabled(ctx)]
        for c in checks:
            validate = getattr(c, "validate", None)
            if validate:
                validate(ctx)
        log.info("етапи: %s", " → ".join(c.name for c in checks))

        sem = asyncio.Semaphore(config["concurrency"])
        cand_list = list(candidates)
        done = 0

        async def worker(cand: Candidate) -> Result:
            nonlocal done
            async with sem:
                res = await process(cand, checks, ctx)
            done += 1
            status = f"відсів [{res.rejected_by}] {res.reject_reason}" if res.rejected else f"OK {res.score}"
            log.info("[%d/%d] %s — %s", done, len(cand_list), cand.domain, status)
            return res

        try:
            results = await asyncio.gather(*(worker(c) for c in cand_list))
        finally:
            if cache is not None:
                cache.close()

    return sorted(results, key=lambda r: (r.rejected, -(r.score or 0)))


BASE_COLUMNS = ["domain", "status", "score", "rejected_by", "reject_reason", "flags"]


def write_csv(results: list[Result], path: str | Path, include_rejected: bool = True) -> int:
    rows = [r for r in results if include_rejected or not r.rejected]
    metric_keys: list[str] = []
    for r in rows:
        for k in r.metrics:
            if k not in metric_keys:
                metric_keys.append(k)

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=BASE_COLUMNS + metric_keys)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "domain": r.domain,
                "status": "rejected" if r.rejected else "candidate",
                "score": r.score if r.score is not None else "",
                "rejected_by": r.rejected_by or "",
                "reject_reason": r.reject_reason or "",
                "flags": ",".join(r.flags),
                **r.metrics,
            })
    return len(rows)
