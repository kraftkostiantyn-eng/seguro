"""Дешеві перевірки імені та даних з експорту — без мережі."""

from __future__ import annotations

from typing import Any

from ..models import Candidate, Result
from .base import BaseCheck, Context


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _extra_value(cand: Candidate, column: str) -> Any:
    wanted = column.strip().lower()
    for key, value in cand.extra.items():
        if str(key).strip().lower() == wanted:
            return value
    return None


class PrefilterCheck(BaseCheck):
    name = "prefilter"

    async def run(self, cand: Candidate, result: Result, ctx: Context) -> None:
        cfg = self.cfg(ctx)
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

        # Пороги за колонками експорту: дані вже безкоштовно є у файлі.
        for column, threshold in (cfg.get("min_extra") or {}).items():
            value = _number(_extra_value(cand, column))
            if value is not None and value < float(threshold):
                return result.reject(self.name, f"{column}={value:g} < {threshold}")
        for column, threshold in (cfg.get("max_extra") or {}).items():
            value = _number(_extra_value(cand, column))
            if value is not None and value > float(threshold):
                return result.reject(self.name, f"{column}={value:g} > {threshold}")

        result.metrics["name_length"] = len(name)
