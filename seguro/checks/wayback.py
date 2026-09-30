"""Історія домену з Wayback Machine: активність за роками і класифікація контенту.

Економія запитів: один запит до CDX дає всі помісячні знімки з дайджестами й розмірами;
далі завантажується щонайбільше один знімок на рік (найбільший — імовірніше справжня
сторінка), від найсвіжіших до старих, і перший же спам-знімок зупиняє перевірку.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from ..classify import PageClass, classify_html
from ..models import Candidate, Result
from .base import BaseCheck, Context

CDX_URL = "https://web.archive.org/cdx/search/cdx"
SNAPSHOT_URL = "https://web.archive.org/web/{ts}id_/http://{domain}/"


@dataclass(frozen=True)
class Capture:
    ts: str
    digest: str = ""
    length: int = 0

    @property
    def year(self) -> str:
        return self.ts[:4]

    @property
    def month_index(self) -> int:
        return int(self.ts[:4]) * 12 + int(self.ts[4:6]) - 1

    @property
    def label(self) -> str:
        return f"{self.ts[:4]}-{self.ts[4:6]}"


def parse_cdx(body: str) -> list[Capture]:
    if not body.strip():
        return []
    rows = json.loads(body)
    captures = []
    for row in rows[1:]:  # перший рядок — заголовок
        digest = row[1] if len(row) > 1 else ""
        try:
            length = int(row[2]) if len(row) > 2 else 0
        except (TypeError, ValueError):
            length = 0
        captures.append(Capture(row[0], digest, length))
    return sorted(captures, key=lambda c: c.ts)


def pick_samples(captures: list[Capture], max_samples: int) -> list[Capture]:
    """Один знімок на рік — найбільший за розміром; найсвіжіші роки першими."""
    best: dict[str, Capture] = {}
    for c in captures:
        if c.year not in best or c.length > best[c.year].length:
            best[c.year] = c
    return [best[y] for y in sorted(best, reverse=True)][:max_samples]


def longest_gap_months(captures: list[Capture]) -> int:
    months = sorted({c.month_index for c in captures})
    return max((b - a for a, b in zip(months, months[1:])), default=0)


def months_since(ts: str, now: datetime) -> int:
    return (now.year * 12 + now.month - 1) - Capture(ts).month_index


def count_topic_switches(pages: list[PageClass]) -> int:
    """Скільки разів змінювалась «основна» ознака сайту між сусідніми знімками (хронологічно)."""
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


class WaybackCheck(BaseCheck):
    name = "wayback"

    async def fetch_captures(self, domain: str, ctx: Context) -> list[Capture]:
        params = [
            ("url", domain),
            ("output", "json"),
            ("fl", "timestamp,digest,length"),
            ("filter", "statuscode:200"),
            ("filter", "mimetype:text/html"),
            # Один знімок на місяць — досить для оцінки активності.
            ("collapse", "timestamp:6"),
        ]
        status, body = await ctx.http.get(CDX_URL, params=params)
        if status != 200:
            raise RuntimeError(f"CDX HTTP {status}")
        return parse_cdx(body)

    async def run(self, cand: Candidate, result: Result, ctx: Context) -> None:
        cfg = self.cfg(ctx)
        m = result.metrics
        try:
            captures = await self.fetch_captures(cand.domain, ctx)
        except Exception as exc:
            result.flag("wayback_error")
            m["wayback_error"] = str(exc)[:200]
            return

        years = sorted({c.year for c in captures})
        m["wb_snapshots"] = len(captures)
        m["wb_years_active"] = len(years)
        if captures:
            now = datetime.now(timezone.utc)
            first, last = captures[0], captures[-1]
            m["wb_first_seen"] = first.label
            m["wb_last_seen"] = last.label
            first_dt = datetime.strptime(first.ts[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
            m["history_age_years"] = round((now - first_dt).days / 365.25, 1)
            m["wb_last_seen_months_ago"] = months_since(last.ts, now)
            m["wb_longest_gap_months"] = longest_gap_months(captures)
            digests = {c.digest for c in captures if c.digest}
            if digests:
                # Мало унікальних сторінок за багато місяців — статична заглушка або паркінг.
                m["wb_unique_ratio"] = round(len(digests) / len(captures), 2)
                if len(captures) >= 12 and m["wb_unique_ratio"] < 0.2:
                    result.flag("wb_static")
            if m["wb_longest_gap_months"] >= 36:
                result.flag("wb_revived")

        if len(captures) < cfg["min_snapshots"]:
            return result.reject(self.name, f"мало знімків в архіві ({len(captures)})")
        if len(years) < cfg["min_years_active"]:
            return result.reject(self.name, f"активний лише {len(years)} р.")

        planned = pick_samples(captures, cfg["max_samples"])
        pages: list[tuple[str, PageClass]] = []
        parking = 0
        for cap in planned:
            try:
                status, body = await ctx.http.get(SNAPSHOT_URL.format(ts=cap.ts, domain=cand.domain))
            except Exception:
                continue
            if status != 200:
                continue
            page = classify_html(body)
            pages.append((cap.ts, page))
            bad = [c for c in cfg["reject_categories"] if c in page.spam_categories]
            if bad:
                m["wb_sampled"] = len(pages)
                return result.reject(self.name, f"спам у знімку {cap.label}: {', '.join(bad)}")
            if page.is_parking:
                parking += 1
                if parking > cfg["max_parking_ratio"] * len(planned):
                    m["wb_sampled"] = len(pages)
                    return result.reject(self.name, f"переважно паркінг ({parking}/{len(planned)})")

        self._summarize(pages, result, ctx)

    def _summarize(self, pages: list[tuple[str, PageClass]], result: Result, ctx: Context) -> None:
        cfg = self.cfg(ctx)
        m = result.metrics
        pages.sort(key=lambda item: item[0])
        classified = [p for _, p in pages]
        content = [p for p in classified if not p.is_empty]
        m["wb_sampled"] = len(classified)
        m["wb_empty"] = len(classified) - len(content)
        if not content:
            result.flag("wayback_no_content")
            return

        n = len(content)
        spam = Counter(c for p in content for c in p.spam_categories)
        topics = Counter(t for p in content if p.is_clean_content for t in p.topics)
        langs = Counter(p.language for p in content if p.language)
        clean = sum(1 for p in content if p.is_clean_content)
        parking = sum(1 for p in content if p.is_parking)
        gambling = sum(1 for p in content if "gambling" in p.categories)
        targets = set(cfg.get("target_languages") or [])

        m["wb_clean_ratio"] = round(clean / n, 2)
        m["wb_parking_ratio"] = round(parking / n, 2)
        m["wb_spam"] = ",".join(f"{k}:{v}" for k, v in spam.most_common())
        m["wb_topics"] = ",".join(f"{k}:{v}" for k, v in topics.most_common(3))
        m["wb_languages"] = ",".join(f"{k}:{v}" for k, v in langs.most_common(3))
        m["wb_topic_ratio"] = round(sum(1 for p in content if p.is_clean_content and p.topics) / n, 2)
        m["wb_geo_ratio"] = round(sum(1 for p in content if p.language in targets) / n, 2) if targets else 1.0
        m["wb_topic_switches"] = count_topic_switches(content)
        m["wb_last_title"] = next((p.title for p in reversed(classified) if p.title), "")

        if gambling:
            # Колишній гемблінг-сайт — тематично доречно, але варто перевірити на бани.
            result.flag("had_gambling_content")
        if parking / n > cfg["max_parking_ratio"]:
            result.reject(self.name, f"переважно паркінг ({parking}/{n})")
