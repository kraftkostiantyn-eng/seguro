"""Google Safe Browsing v4: малвар/фішинг. Безкоштовний ключ, до 500 URL за запит."""

from __future__ import annotations

import hashlib
import json

import httpx

from .base import BaseCheck, Context, Item

THREAT_TYPES = ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"]


class SafeBrowsingCheck(BaseCheck):
    name = "safebrowsing"
    batch_size = 500
    URL = "https://safebrowsing.googleapis.com/v4/threatMatches:find"

    def validate(self, ctx: Context) -> None:
        self.api_key(ctx)

    async def run_batch(self, items: list[Item], ctx: Context) -> None:
        domains = sorted(cand.domain for cand, _ in items)
        body = {
            "client": {"clientId": "seguro", "clientVersion": "0.2"},
            "threatInfo": {
                "threatTypes": THREAT_TYPES,
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": f"http://{d}/"} for d in domains],
            },
        }
        # Ключ API іде в query — у ключ кешу він потрапити не повинен.
        cache_key = "gsb:" + hashlib.sha1(",".join(domains).encode()).hexdigest()
        status, text = await ctx.http.post_json(
            self.URL, body, params={"key": self.api_key(ctx)}, cache_key=cache_key
        )
        if status != 200:
            raise RuntimeError(f"Safe Browsing HTTP {status}: {text[:200]}")

        threats: dict[str, str] = {}
        for match in (json.loads(text) if text.strip() else {}).get("matches", []):
            host = httpx.URL(match.get("threat", {}).get("url", "")).host
            if host:
                threats[host.lower()] = match.get("threatType", "THREAT")

        for cand, result in items:
            threat = threats.get(cand.domain)
            if threat:
                result.metrics["safebrowsing"] = threat
                result.reject(self.name, f"Safe Browsing: {threat}")
