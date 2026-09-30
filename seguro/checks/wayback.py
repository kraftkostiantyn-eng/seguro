"""Історія домену з Wayback Machine: активність за роками і класифікація контенту."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone

from ..classify import PageClass, classify_html
from ..models import Candidate, Result
from .base import Context

CDX_URL = "https://web.archive.org/cdx/search/cdx"
SNAPSHOT_URL = "https://web.archive.org/web/{ts}id_/http://{domain}/"


def pick_samples(timestamps: list[str], per_year: int, max_samples: int) -> list[str]:
    """Рівномірна вибірка знімків: до `per_year` на рік, свіжі роки в пріоритеті."""
    by_year: dict[str, list[str]] = {}
    for ts in timestamps:
        by_year.setdefault(ts[:4], []).append(ts)
    samples: list[str] = []
    for year in sorted(by_year, reverse=True):
        items = by_year[year]
        step = max(1, len(items) // per_year)
        samples.extend(items[::step][:per_year])
    return sorted(samples[:max_samples])


def count_topic_switches(pages: list[PageClass]) -> int:
    """Скільки разів змінювалась «основна» ознака сайту між сусідніми знімками."""
    def label(p: PageClass) -> str:
        if p.is_parking:
            return "parking"
        if p.spam_categories:
            return p.spam_categories[0]
        if "gambling" in p.categories:
            return "gambling"
        return p.language or "unknown"

    labels = [label(p) for p in pages if not p.is_empty]
    return sum(1 for a, b in zip(labels, labels[1:]) if a != b)


class WaybackCheck:
    name = "wayback"

    def enabled(self, ctx: Context) -> bool:
        return bool(ctx.config["wayback"].get("enabled"))

    async def fetch_timestamps(self, domain: str, ctx: Context) -> list[str]:
        params = {
            "url": domain,
            "output": "json",
            "fl": "timestamp,statuscode",
            "filter": "statuscode:200",
            # Один знімок на місяць — досить для оцінки активності.
            "collapse": "timestamp:6",
        }
        status, body = await ctx.http.get(CDX_URL, params=params)
        if status != 200:
            raise RuntimeError(f"CDX HTTP {status}")
        if not body.strip():
            return []
        rows = json.loads(body)
        return [row[0] for row in rows[1:]]  # перший рядок — заголовок

    async def run(self, cand: Candidate, result: Result, ctx: Context) -> None:
        cfg = ctx.config["wayback"]
        try:
            timestamps = await self.fetch_timestamps(cand.domain, ctx)
        except Exception as exc:
            result.flag("wayback_error")
            result.metrics["wayback_error"] = str(exc)[:200]
            return

        years = sorted({ts[:4] for ts in timestamps})
        result.metrics["wb_snapshots"] = len(timestamps)
        result.metrics["wb_years_active"] = len(years)
        if timestamps:
            first = datetime.strptime(timestamps[0][:8], "%Y%m%d").replace(tzinfo=timezone.utc)
            result.metrics["wb_first_seen"] = first.date().isoformat()
            result.metrics["wb_last_seen"] = f"{timestamps[-1][:4]}-{timestamps[-1][4:6]}"
            result.metrics["history_age_years"] = round(
                (datetime.now(timezone.utc) - first).days / 365.25, 1
            )

        if len(timestamps) < cfg["min_snapshots"]:
            return result.reject(self.name, f"мало знімків в архіві ({len(timestamps)})")
        if len(years) < cfg["min_years_active"]:
            return result.reject(self.name, f"активний лише {len(years)} р.")

        pages: list[PageClass] = []
        for ts in pick_samples(timestamps, cfg["sample_per_year"], cfg["max_samples"]):
            url = SNAPSHOT_URL.format(ts=ts, domain=cand.domain)
            try:
                status, body = await ctx.http.get(url)
            except Exception:
                continue
            if status == 200:
                pages.append(classify_html(body))

        if not pages:
            result.flag("wayback_no_content")
            return
        self._summarize(pages, result, ctx)

    def _summarize(self, pages: list[PageClass], result: Result, ctx: Context) -> None:
        cfg = ctx.config["wayback"]
        n = len(pages)
        spam = Counter(c for p in pages for c in p.spam_categories)
        topics = Counter(t for p in pages if p.is_clean_content for t in p.topics)
        langs = Counter(p.language for p in pages if p.language)
        clean = sum(1 for p in pages if p.is_clean_content)
        parking = sum(1 for p in pages if p.is_parking)
        gambling = sum(1 for p in pages if "gambling" in p.categories)
        targets = set(cfg.get("target_languages") or [])

        m = result.metrics
        m["wb_sampled"] = n
        m["wb_clean_ratio"] = round(clean / n, 2)
        m["wb_parking_ratio"] = round(parking / n, 2)
        m["wb_spam"] = ",".join(f"{k}:{v}" for k, v in spam.most_common())
        m["wb_topics"] = ",".join(f"{k}:{v}" for k, v in topics.most_common(3))
        m["wb_languages"] = ",".join(f"{k}:{v}" for k, v in langs.most_common(3))
        m["wb_topic_ratio"] = round(sum(1 for p in pages if p.is_clean_content and p.topics) / n, 2)
        m["wb_geo_ratio"] = round(sum(1 for p in pages if p.language in targets) / n, 2) if targets else 1.0
        m["wb_topic_switches"] = count_topic_switches(pages)
        m["wb_last_title"] = next((p.title for p in reversed(pages) if p.title), "")

        if gambling:
            # Колишній гемблінг-сайт — тематично доречно, але варто перевірити на бани.
            result.flag("had_gambling_content")

        bad = [c for c in cfg["reject_categories"] if spam.get(c)]
        if bad:
            return result.reject(self.name, f"спам в історії: {', '.join(bad)}")
        if parking / n > cfg["max_parking_ratio"]:
            return result.reject(self.name, f"переважно паркінг ({parking}/{n})")
