"""Open PageRank (openpagerank.com): безкоштовний авторитет домену з графа Common Crawl.

Ключ безкоштовний, до 100 доменів за запит — тому етап пакетний і дуже дешевий.
"""

from __future__ import annotations

import json

from .base import BaseCheck, Context, Item


class OpenPageRankCheck(BaseCheck):
    name = "openpagerank"
    batch_size = 100
    URL = "https://openpagerank.com/api/v1.0/getPageRank"

    def validate(self, ctx: Context) -> None:
        self.api_key(ctx)

    async def run_batch(self, items: list[Item], ctx: Context) -> None:
        params = [("domains[]", cand.domain) for cand, _ in items]
        status, body = await ctx.http.get(
            self.URL, params=params, headers={"API-OPR": self.api_key(ctx)}
        )
        if status != 200:
            raise RuntimeError(f"OpenPageRank HTTP {status}: {body[:200]}")
        rows = {row.get("domain", "").lower(): row for row in json.loads(body).get("response", [])}
        min_score = self.cfg(ctx).get("min_score")

        for cand, result in items:
            row = rows.get(cand.domain)
            if not row or row.get("status_code") != 200:
                continue
            value = float(row.get("page_rank_decimal") or 0)
            result.metrics["opr_score"] = value
            if row.get("rank"):
                result.metrics["opr_rank"] = int(row["rank"])
            if min_score is not None and value < float(min_score):
                result.reject(self.name, f"OPR {value} < {min_score}")
