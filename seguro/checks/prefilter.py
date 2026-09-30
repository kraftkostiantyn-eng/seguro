"""Дешеві перевірки імені без мережі."""

from __future__ import annotations

from ..models import Candidate, Result
from .base import Context


class PrefilterCheck:
    name = "prefilter"

    def enabled(self, ctx: Context) -> bool:
        return True

    async def run(self, cand: Candidate, result: Result, ctx: Context) -> None:
        cfg = ctx.config["prefilter"]
        name = cand.sld
        allowed = cfg.get("allowed_tlds") or []

        if allowed and cand.tld not in allowed:
            return result.reject(self.name, f"TLD .{cand.tld} не в списку")
        if not cfg["min_length"] <= len(name) <= cfg["max_length"]:
            return result.reject(self.name, f"довжина імені {len(name)}")
        if name.count("-") > cfg["max_hyphens"]:
            return result.reject(self.name, "забагато дефісів")
        if not cfg["allow_digits"] and any(ch.isdigit() for ch in name):
            return result.reject(self.name, "цифри в імені")
        if not cfg["allow_idn"] and name.startswith("xn--"):
            return result.reject(self.name, "IDN-домен")
        for word in cfg.get("stopwords") or []:
            if word in name:
                return result.reject(self.name, f"стоп-слово '{word}'")

        result.metrics["name_length"] = len(name)
