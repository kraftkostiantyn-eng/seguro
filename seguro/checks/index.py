"""Індексація в Google (`site:domain`) через Custom Search JSON API — 100 запитів/день безкоштовно.

Квотований етап: іде після всіх безкоштовних, лише для найкращих за попередньою оцінкою.
Нуль сторінок в індексі у домену, що був живий останній рік, — ознака деіндексації/санкцій.
"""

from __future__ import annotations

import json
import os

from ..models import Candidate, Result
from .base import BaseCheck, Context

RECENT_MONTHS = 12


class IndexCheck(BaseCheck):
    name = "index"
    costly = True
    URL = "https://www.googleapis.com/customsearch/v1"

    def _cx(self, ctx: Context) -> str:
        env = self.cfg(ctx).get("cx_env", "")
        cx = os.environ.get(env, "")
        if not cx:
            raise RuntimeError(f"етап index: не задано змінну оточення {env} (id пошукової системи)")
        return cx

    def validate(self, ctx: Context) -> None:
        self.api_key(ctx)
        self._cx(ctx)

    async def run(self, cand: Candidate, result: Result, ctx: Context) -> None:
        public = {"cx": self._cx(ctx), "q": f"site:{cand.domain}", "num": 1}
        status, body = await ctx.http.get(
            self.URL, params={**public, "key": self.api_key(ctx)}, cache_key_params=public
        )
        if status != 200:
            raise RuntimeError(f"Google CSE HTTP {status}: {body[:200]}")
        total = int(json.loads(body).get("searchInformation", {}).get("totalResults") or 0)
        result.metrics["indexed_pages"] = total
        if total > 0:
            return
        result.flag("not_indexed")
        months = result.metrics.get("wb_last_seen_months_ago")
        if months is not None and months <= RECENT_MONTHS:
            result.flag("possibly_deindexed")
