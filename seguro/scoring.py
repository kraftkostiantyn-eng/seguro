"""Підсумкова оцінка 0–100 зі зважених компонентів 0..1.

Компоненти без даних (напр. беклінки без API) не штрафують домен: їхня вага
перерозподіляється між рештою. Та сама функція дає попередню оцінку після
безкоштовних етапів, за якою відбираються домени для платних.
"""

from __future__ import annotations

import math
from typing import Any

from .models import Result

# Прапорці, що множать підсумкову оцінку.
FLAG_PENALTIES = {
    "had_gambling_content": 0.9,   # тематично доречно, але вищий ризик санкцій
    "possibly_deindexed": 0.7,     # був живий, а в Google його нема
    "recently_registered": 0.5,    # уже хтось перехопив
    "wb_revived": 0.85,            # багаторічна пауза в історії — ймовірна зміна власника
    "wb_static": 0.9,              # роками одна й та сама сторінка
}


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

    ages = [m[k] for k in ("history_age_years", "registration_age_years") if m.get(k) is not None]
    comps["age"] = _clip(max(ages) / 15) if ages else None

    # Безкоштовний авторитет: Open PageRank (0–10) і місце в топ-1M списках.
    authority = []
    if "opr_score" in m:
        authority.append(_clip(m["opr_score"] / 5))
    for key, value in m.items():
        if key.startswith("top_") and key.endswith("_rank") and value:
            authority.append(_clip(1 - math.log10(float(value)) / 6))
    comps["authority"] = max(authority) if authority else None

    if "bl_ref_domains" in m:
        rd = _clip(math.log10(1 + m["bl_ref_domains"]) / math.log10(1 + 500))
        if m.get("bl_trust_flow") is not None:
            quality = _clip(m["bl_trust_flow"] / 40)
        elif m.get("bl_domain_rating") is not None:
            quality = _clip(m["bl_domain_rating"] / 60)
        elif m.get("bl_domain_authority") is not None:
            quality = _clip(m["bl_domain_authority"] / 50)
        else:
            quality = rd
        spam = 1 - _clip(m.get("bl_spam_anchor_ratio", 0) * 2)
        if m.get("bl_spam_score"):
            spam *= 1 - _clip(m["bl_spam_score"] / 50)
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
    for flag, factor in FLAG_PENALTIES.items():
        if flag in result.flags:
            value *= factor
    for k, v in comps.items():
        if v is not None:
            result.metrics[f"c_{k}"] = round(v, 2)
    return round(100 * value, 1)
