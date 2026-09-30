"""Безкоштовні топ-1M списки (Tranco, Majestic Million, Cisco Umbrella).

Домен у такому списку нещодавно мав реальний трафік або посилання — сильний
позитивний сигнал, який коштує нуль запитів: файл завантажується раз на тиждень,
а потім перевіряється локально одним проходом для всіх кандидатів.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Iterator

from ..download import download, open_text
from ..sources.files import normalize_domain
from .base import BaseCheck, Context, Item

log = logging.getLogger("seguro.toplists")


def iter_rows(fh, fmt: str) -> Iterator[tuple[str, int, dict[str, Any]]]:
    """Віддає (домен, ранг, додаткові поля) для підтримуваних форматів."""
    if fmt == "majestic":
        for row in csv.DictReader(fh):
            domain = normalize_domain(row.get("Domain") or "")
            rank = int(row.get("GlobalRank") or 0)
            if domain and rank:
                yield domain, rank, {"ref_subnets": row.get("RefSubNets"), "ref_ips": row.get("RefIPs")}
        return
    # rank_domain: "1,google.com" без заголовка (Tranco, Umbrella)
    for row in csv.reader(fh):
        if len(row) < 2 or not row[0].strip().isdigit():
            continue
        domain = normalize_domain(row[1])
        if domain:
            yield domain, int(row[0]), {}


def scan(fh, fmt: str, wanted: set[str]) -> dict[str, tuple[int, dict[str, Any]]]:
    """Один прохід по списку: для кожного кандидата — найкращий ранг (з урахуванням піддоменів)."""
    found: dict[str, tuple[int, dict[str, Any]]] = {}
    for domain, rank, extra in iter_rows(fh, fmt):
        parts = domain.split(".")
        for i in range(len(parts) - 1):
            suffix = ".".join(parts[i:])
            if suffix in wanted and (suffix not in found or rank < found[suffix][0]):
                found[suffix] = (rank, extra)
    return found


class ToplistsCheck(BaseCheck):
    name = "toplists"
    batch_size = 0  # усі домени одним проходом

    def _lists(self, ctx: Context) -> list[dict[str, Any]]:
        return [l for l in self.cfg(ctx).get("lists") or [] if l.get("enabled", True)]

    def enabled(self, ctx: Context) -> bool:
        return super().enabled(ctx) and bool(self._lists(ctx))

    async def prepare(self, ctx: Context) -> None:
        base = Path(ctx.config.get("download_dir", "downloads"))
        max_age = float(self.cfg(ctx).get("max_age_days", 7))
        paths: dict[str, Path] = {}
        for spec in self._lists(ctx):
            ext = ".zip" if spec["url"].lower().endswith(".zip") else ".csv"
            dest = base / f"toplist_{spec['name']}{ext}"
            try:
                paths[spec["name"]] = await download(ctx.http.client, spec["url"], dest, max_age)
            except Exception as exc:
                log.warning("топ-список %s не завантажено: %s", spec["name"], exc)
        ctx.state["toplists"] = paths

    async def run_batch(self, items: list[Item], ctx: Context) -> None:
        wanted = {cand.domain for cand, _ in items}
        for spec in self._lists(ctx):
            path = ctx.state.get("toplists", {}).get(spec["name"])
            if path is None:
                continue
            with open_text(path) as fh:
                found = scan(fh, spec.get("format", "rank_domain"), wanted)
            for cand, result in items:
                hit = found.get(cand.domain)
                if hit is None:
                    continue
                rank, extra = hit
                result.metrics[f"top_{spec['name']}_rank"] = rank
                for key, value in extra.items():
                    if value not in (None, ""):
                        result.metrics[f"top_{spec['name']}_{key}"] = value
                result.flag(f"in_{spec['name']}")
