"""Беклінк-метрики через API: Majestic, Ahrefs (платні) або Moz (є безкоштовний тариф).

Етап запускається останнім і лише для найкращих за попередньою оцінкою (бюджет
`max_domains_per_run`, `min_prelim_score`), щоб платні виклики йшли на тих, хто
пройшов усі безкоштовні фільтри. Ключ береться зі змінної оточення `api_key_env`;
для Moz — у форматі `access_id:secret`.
"""

from __future__ import annotations

import base64
import json
from datetime import date

from ..classify import CATEGORY_KEYWORDS, _cjk_ratio
from ..models import Candidate, Result
from .base import BaseCheck, Context

_SPAM_ANCHOR_WORDS = [kw for cat, kws in CATEGORY_KEYWORDS.items() if cat != "gambling" for kw in kws]


def is_spam_anchor(anchor: str) -> bool:
    low = anchor.lower()
    return _cjk_ratio(anchor) > 0.3 or any(kw in low for kw in _SPAM_ANCHOR_WORDS)


def spam_anchor_ratio(anchors: list[tuple[str, int]]) -> float:
    """Частка реф-доменів, що ведуть зі спамними анкорами."""
    total = sum(weight for _, weight in anchors)
    if not total:
        return 0.0
    return sum(weight for text, weight in anchors if is_spam_anchor(text)) / total


class MajesticProvider:
    URL = "https://api.majestic.com/api/json"

    async def fetch(self, domain: str, key: str, ctx: Context) -> dict:
        base = {"cmd": "GetIndexItemInfo", "items": "1", "item0": domain, "datasource": "fresh"}
        _, body = await ctx.http.get(self.URL, params={**base, "app_api_key": key}, cache_key_params=base)
        data = json.loads(body)
        if data.get("Code") != "OK":
            raise RuntimeError(f"Majestic: {data.get('Code')} {data.get('ErrorMessage')}")
        row = data["DataTables"]["Results"]["Data"][0]

        abase = {"cmd": "GetAnchorText", "item": domain, "Count": "50", "datasource": "fresh"}
        _, abody = await ctx.http.get(self.URL, params={**abase, "app_api_key": key}, cache_key_params=abase)
        adata = json.loads(abody)
        anchors = [
            (a.get("AnchorText", ""), int(a.get("RefDomains") or 0))
            for a in (adata.get("DataTables", {}).get("AnchorText", {}).get("Data") or [])
        ]
        return {
            "trust_flow": int(row.get("TrustFlow") or 0),
            "citation_flow": int(row.get("CitationFlow") or 0),
            "ref_domains": int(row.get("RefDomains") or 0),
            "backlinks": int(row.get("ExtBackLinks") or 0),
            "anchors": anchors,
        }


class AhrefsProvider:
    URL = "https://api.ahrefs.com/v3/site-explorer/{endpoint}"

    async def _get(self, endpoint: str, params: dict, key: str, ctx: Context) -> dict:
        status, body = await ctx.http.get(
            self.URL.format(endpoint=endpoint),
            params=params,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        )
        if status != 200:
            raise RuntimeError(f"Ahrefs {endpoint}: HTTP {status} {body[:200]}")
        return json.loads(body)

    async def fetch(self, domain: str, key: str, ctx: Context) -> dict:
        today = date.today().isoformat()
        dr = await self._get("domain-rating", {"target": domain, "date": today}, key, ctx)
        stats = await self._get(
            "backlinks-stats", {"target": domain, "mode": "domain", "date": today}, key, ctx
        )
        anchors = await self._get(
            "anchors",
            {"target": domain, "mode": "domain", "select": "anchor,refdomains", "limit": 50},
            key, ctx,
        )
        metrics = stats.get("metrics", {})
        return {
            "domain_rating": float(dr.get("domain_rating", {}).get("domain_rating") or 0),
            # Для дропів важливіші історичні посилання: живих часто вже мало.
            "ref_domains": int(metrics.get("all_time_refdomains") or metrics.get("live_refdomains") or 0),
            "backlinks": int(metrics.get("all_time") or metrics.get("live") or 0),
            "anchors": [(a.get("anchor", ""), int(a.get("refdomains") or 0)) for a in anchors.get("anchors", [])],
        }


class MozProvider:
    """Moz Links API v2: DA, Spam Score, кількість реф-доменів. Ключ `access_id:secret`."""

    URL = "https://lsapi.seomoz.com/v2/url_metrics"

    async def fetch(self, domain: str, key: str, ctx: Context) -> dict:
        token = base64.b64encode(key.encode()).decode()
        status, body = await ctx.http.post_json(
            self.URL, {"targets": [domain]},
            headers={"Authorization": f"Basic {token}"},
            cache_key=f"moz:{domain}",
        )
        if status != 200:
            raise RuntimeError(f"Moz: HTTP {status} {body[:200]}")
        row = (json.loads(body).get("results") or [{}])[0]
        return {
            "domain_authority": float(row.get("domain_authority") or 0),
            "spam_score": float(row.get("spam_score") or 0),
            "ref_domains": int(row.get("root_domains_to_root_domain") or 0),
            "backlinks": int(row.get("external_pages_to_root_domain") or 0),
            "anchors": [],
        }


PROVIDERS = {"majestic": MajesticProvider, "ahrefs": AhrefsProvider, "moz": MozProvider}


class BacklinksCheck(BaseCheck):
    name = "backlinks"
    costly = True

    def enabled(self, ctx: Context) -> bool:
        return self.cfg(ctx).get("provider", "none") in PROVIDERS

    def validate(self, ctx: Context) -> None:
        self.api_key(ctx)

    async def run(self, cand: Candidate, result: Result, ctx: Context) -> None:
        cfg = self.cfg(ctx)
        provider = PROVIDERS[cfg["provider"]]()
        try:
            data = await provider.fetch(cand.domain, self.api_key(ctx), ctx)
        except Exception as exc:
            result.flag("backlinks_error")
            result.metrics["backlinks_error"] = str(exc)[:200]
            return

        anchors = data.pop("anchors", [])
        ratio = spam_anchor_ratio(anchors)
        m = result.metrics
        for k, v in data.items():
            m[f"bl_{k}"] = v
        m["bl_provider"] = cfg["provider"]
        if anchors:
            m["bl_spam_anchor_ratio"] = round(ratio, 2)
            m["bl_top_anchors"] = " | ".join(a for a, _ in anchors[:5])
        if "trust_flow" in data and data.get("citation_flow"):
            m["bl_tf_cf"] = round(data["trust_flow"] / data["citation_flow"], 2)

        if data["ref_domains"] < cfg["min_ref_domains"]:
            return result.reject(self.name, f"мало реф-доменів ({data['ref_domains']})")
        if ratio > cfg["max_spam_anchor_ratio"]:
            return result.reject(self.name, f"спамні анкори ({ratio:.0%})")
        if "bl_tf_cf" in m and m["bl_tf_cf"] < cfg["min_tf_cf_ratio"]:
            return result.reject(self.name, f"низьке TF/CF ({m['bl_tf_cf']})")
        if data.get("spam_score", 0) > cfg.get("max_spam_score", 100):
            return result.reject(self.name, f"Moz Spam Score {data['spam_score']:g}")
