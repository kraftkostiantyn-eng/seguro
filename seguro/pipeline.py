"""Воронка: етапи виконуються по черзі для всіх доменів; домен зупиняється на першому відсіві.

Порядок етапів — від дешевих до дорогих. Перед платним/квотованим етапом кандидати
ранжуються за попередньою оцінкою, і на нього йдуть лише найкращі в межах бюджету.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import httpx

from .cache import CachedClient, HttpCache
from .checks import BaseCheck, Context, Item, default_checks
from .models import Candidate, Result
from .scoring import score

log = logging.getLogger("seguro")

USER_AGENT = "seguro/0.2 (domain research)"


@dataclass
class StageStats:
    name: str
    entered: int = 0
    rejected: int = 0
    skipped: int = 0  # не потрапили в бюджет етапу
    errors: int = 0
    seconds: float = 0.0


@dataclass
class RunReport:
    results: list[Result]
    stages: list[StageStats] = field(default_factory=list)
    http_stats: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def candidates(self) -> list[Result]:
        return [r for r in self.results if not r.rejected]


def apply_budget(stage: BaseCheck, items: list[Item], config: dict[str, Any]) -> tuple[list[Item], list[Item]]:
    """Для платного етапу: відібрати найкращих за попередньою оцінкою в межах бюджету."""
    cfg = config.get(stage.name) or {}
    limit = cfg.get("max_domains_per_run")
    min_prelim = cfg.get("min_prelim_score")
    if not stage.costly or (limit is None and min_prelim is None):
        return items, []

    weights = config["scoring"]["weights"]
    for _, result in items:
        result.prelim_score = score(result, weights)
    ranked = sorted(items, key=lambda item: item[1].prelim_score or 0, reverse=True)
    selected: list[Item] = []
    skipped: list[Item] = []
    for item in ranked:
        prelim = item[1].prelim_score or 0
        if min_prelim is not None and prelim < float(min_prelim):
            skipped.append(item)
        elif limit is not None and len(selected) >= int(limit):
            skipped.append(item)
        else:
            selected.append(item)
    for _, result in skipped:
        result.flag(f"{stage.name}_skipped_budget")
    return selected, skipped


def chunks(items: list[Item], size: int) -> list[list[Item]]:
    if size <= 0:
        return [items]
    return [items[i:i + size] for i in range(0, len(items), size)]


async def run_stage(stage: BaseCheck, items: list[Item], ctx: Context, sem: asyncio.Semaphore) -> int:
    """Виконує етап для всіх доменів; повертає кількість збоїв."""
    errors = 0

    async def one(cand: Candidate, result: Result) -> None:
        nonlocal errors
        async with sem:
            try:
                await stage.run(cand, result, ctx)
            except Exception as exc:  # один збій не має валити весь прогін
                errors += 1
                log.warning("%s: етап %s впав: %s", cand.domain, stage.name, exc)
                result.flag(f"{stage.name}_error")
        if result.rejected:
            log.debug("%s — відсів [%s] %s", cand.domain, stage.name, result.reject_reason)

    async def batch(chunk: list[Item]) -> None:
        nonlocal errors
        async with sem:
            try:
                await stage.run_batch(chunk, ctx)
            except Exception as exc:
                errors += len(chunk)
                log.warning("етап %s впав на пакеті з %d доменів: %s", stage.name, len(chunk), exc)
                for _, result in chunk:
                    result.flag(f"{stage.name}_error")

    if stage.batch_size is None:
        await asyncio.gather(*(one(c, r) for c, r in items))
    else:
        await asyncio.gather(*(batch(chunk) for chunk in chunks(items, stage.batch_size)))
    return errors


def finalize(result: Result, config: dict[str, Any]) -> None:
    if result.rejected:
        return
    result.score = score(result, config["scoring"]["weights"])
    if result.score is None:
        # Мережеві етапи не дали даних (помилки API) — не можна вважати домен кандидатом.
        result.reject("no_data", "недостатньо даних для оцінки, перезапустіть пізніше")
        return
    min_score = config["scoring"]["min_score"]
    if result.score < min_score:
        result.reject("scoring", f"оцінка {result.score} < {min_score}")


async def run_pipeline(
    candidates: Iterable[Candidate],
    config: dict[str, Any],
    checks: list[BaseCheck] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> RunReport:
    items: list[Item] = [(c, Result(c.domain, source=c.source)) for c in candidates]
    report = RunReport(results=[r for _, r in items])
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
        stages = [c for c in (checks or default_checks()) if c.enabled(ctx)]
        if config.get("free_only"):
            stages = [s for s in stages if not s.costly]
        for stage in stages:
            stage.validate(ctx)
        log.info("етапи: %s", " → ".join(s.name for s in stages))
        sem = asyncio.Semaphore(config["concurrency"])

        try:
            for stage in stages:
                active = [(c, r) for c, r in items if not r.rejected]
                stats = StageStats(stage.name, entered=len(active))
                report.stages.append(stats)
                if not active:
                    continue
                selected, skipped = apply_budget(stage, active, config)
                stats.skipped = len(skipped)
                if not selected:
                    continue
                started = time.monotonic()
                try:
                    await stage.prepare(ctx)
                except Exception as exc:
                    log.error("етап %s: підготовка не вдалась, етап пропущено: %s", stage.name, exc)
                    stats.errors = len(selected)
                    for _, result in selected:
                        result.flag(f"{stage.name}_error")
                    continue
                stats.errors = await run_stage(stage, selected, ctx, sem)
                stats.seconds = time.monotonic() - started
                stats.rejected = sum(1 for _, r in selected if r.rejected_by == stage.name)
                log.info(
                    "%-13s вхід %5d  відсів %5d  поза бюджетом %4d  збоїв %4d  %.1fs",
                    stage.name, stats.entered, stats.rejected, stats.skipped, stats.errors, stats.seconds,
                )
        finally:
            if cache is not None:
                cache.close()
        report.http_stats = ctx.http.stats

    for result in report.results:
        finalize(result, config)
    report.results.sort(key=lambda r: (r.rejected, -(r.score or 0)))
    return report


BASE_COLUMNS = ["domain", "source", "status", "score", "rejected_by", "reject_reason", "flags"]


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
                "source": r.source,
                "status": "rejected" if r.rejected else "candidate",
                "score": r.score if r.score is not None else "",
                "rejected_by": r.rejected_by or "",
                "reject_reason": r.reject_reason or "",
                "flags": ",".join(r.flags),
                **r.metrics,
            })
    return len(rows)
