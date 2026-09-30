"""Підсумкова оцінка 0–100 зі зважених компонентів 0..1.

Компоненти без даних (напр. беклінки без API) не штрафують домен: їхня вага
перерозподіляється між рештою.
"""

from __future__ import annotations

import math
from typing import Any

from .models import Result


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def components(m: dict[str, Any]) -> dict[str, float | None]:
    comps: dict[str, float | None] = {}

    if "wb_clean_ratio" in m:
        years = _clip(m.get("wb_years_active", 0) / 8)
        stability = _clip(1 - m.get("wb_topic_switches", 0) / 4)
        comps["history"] = years * (0.6 + 0.4 * stability) * m["wb_clean_ratio"]
        comps["topical"] = m.get("wb_topic_ratio", 0.0)
        comps["geo"] = m.get("wb_geo_ratio", 0.0)
        comps["cleanliness"] = _clip(1 - m.get("wb_parking_ratio", 0.0))
    else:
        comps["history"] = comps["topical"] = comps["geo"] = comps["cleanliness"] = None

    age = m.get("history_age_years")
    comps["age"] = _clip(age / 15) if age is not None else None

    if "bl_ref_domains" in m:
        rd = _clip(math.log10(1 + m["bl_ref_domains"]) / math.log10(1 + 500))
        if "bl_trust_flow" in m:
            quality = _clip(m["bl_trust_flow"] / 40)
        else:
            quality = _clip(m.get("bl_domain_rating", 0) / 60)
        spam = 1 - _clip(m.get("bl_spam_anchor_ratio", 0) * 2)
        comps["backlinks"] = (0.5 * rd + 0.5 * quality) * spam
    else:
        comps["backlinks"] = None
    return comps


def score(result: Result, weights: dict[str, float]) -> float | None:
    comps = components(result.metrics)
    used = {k: w for k, w in weights.items() if comps.get(k) is not None}
    total_w = sum(used.values())
    if not total_w:
        return None
    value = sum(comps[k] * w for k, w in used.items()) / total_w
    if "had_gambling_content" in result.flags:
        # Легкий штраф: тематично підходить, але вищий ризик санкцій.
        value *= 0.9
    for k, v in comps.items():
        if v is not None:
            result.metrics[f"c_{k}"] = round(v, 2)
    return round(100 * value, 1)
