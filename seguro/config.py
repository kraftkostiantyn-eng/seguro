from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "concurrency": 10,
    "cache_path": "seguro_cache.sqlite",
    "cache_ttl_days": 14,
    "http_timeout": 30.0,
    "host_limits": {"web.archive.org": 3},
    "prefilter": {
        "allowed_tlds": ["com", "net", "org", "info", "io", "co", "ua", "pl", "de", "es", "it", "fr"],
        "min_length": 3,
        "max_length": 20,
        "max_hyphens": 1,
        "allow_digits": False,
        "allow_idn": False,
        "stopwords": ["xxx", "porn", "sex", "viagra", "cialis", "loan", "replica"],
    },
    "blacklist": {
        "enabled": True,
        # Spamhaus/URIBL не відповідають на запити через публічні резолвери (8.8.8.8, 1.1.1.1):
        # вкажіть власний резолвер або ключ DQS у зоні, напр. "<key>.dbl.dq.spamhaus.net".
        "zones": ["dbl.spamhaus.org", "multi.surbl.org", "multi.uribl.com"],
        "nameservers": [],
        "timeout": 5.0,
    },
    "rdap": {
        "enabled": True,
        "url": "https://rdap.org/domain/{domain}",
    },
    "wayback": {
        "enabled": True,
        "min_snapshots": 10,
        "min_years_active": 2,
        "sample_per_year": 1,
        "max_samples": 8,
        "target_languages": ["uk", "en"],
        # Категорії, наявність яких в історії означає відсів.
        "reject_categories": ["pharma", "adult", "doorway_cjk"],
        # Скільки знімків-паркінгів допускається (частка).
        "max_parking_ratio": 0.6,
    },
    "backlinks": {
        # none | majestic | ahrefs
        "provider": "none",
        "api_key_env": "SEGURO_BACKLINKS_KEY",
        "min_ref_domains": 10,
        "min_tf_cf_ratio": 0.5,
        "max_spam_anchor_ratio": 0.2,
    },
    "scoring": {
        "min_score": 40,
        "weights": {
            "history": 0.25,
            "backlinks": 0.25,
            "topical": 0.15,
            "age": 0.15,
            "geo": 0.10,
            "cleanliness": 0.10,
        },
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return copy.deepcopy(DEFAULTS)
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return _merge(DEFAULTS, data)
