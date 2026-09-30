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
    "host_limits": {"web.archive.org": 3, "rdap.org": 4},
    "download_dir": "downloads",
    # Пропускати платні/квотовані етапи (те саме, що `--free-only`).
    "free_only": False,
    "store": {
        "path": "seguro.sqlite",
        # Домен, перевірений менш ніж N днів тому, не перевіряється знову (дроп-листи повторюються).
        "rerun_after_days": 30,
    },
    # Віддалені джерела для `seguro fetch`. Типи: url | godaddy | namejet.
    "sources": [],
    "prefilter": {
        "allowed_tlds": ["com", "net", "org", "info", "io", "co", "ua", "pl", "de", "es", "it", "fr"],
        "min_length": 3,
        "max_length": 20,
        "max_hyphens": 1,
        "allow_digits": False,
        "allow_idn": False,
        "stopwords": ["xxx", "porn", "sex", "viagra", "cialis", "loan", "replica"],
        # Пороги для колонок з експорту (ExpiredDomains.net: BL, DP, ABY, ACR...).
        # Безкоштовні дані, які вже є у файлі, — відсіюють до будь-яких запитів.
        "min_extra": {},
        "max_extra": {},
    },
    "localists": {
        "enabled": True,
        # Файли з доменами (один у рядку або CSV, домен у першій колонці):
        # списки регуляторів, власні чорні списки, куплені раніше домени.
        "reject": [],   # [{name: rkn, path: lists/rkn.txt}]
        "flag": [],     # [{name: competitors, path: lists/competitors.txt}]
    },
    "blacklist": {
        "enabled": True,
        # Spamhaus/SURBL/URIBL не відповідають на запити через публічні резолвери (8.8.8.8, 1.1.1.1):
        # вкажіть власний резолвер або ключ DQS у зоні, напр. "<key>.dbl.dq.spamhaus.net".
        "zones": [
            "dbl.spamhaus.org", "multi.surbl.org", "multi.uribl.com",
            "uribl.spameatingmonkey.net", "dbl.nordspam.com",
        ],
        "nameservers": [],
        "timeout": 5.0,
    },
    "toplists": {
        "enabled": True,
        "max_age_days": 7,
        # Безкоштовні топ-1M списки: потрапляння = домен нещодавно мав реальний трафік/посилання.
        "lists": [
            {"name": "tranco", "url": "https://tranco-list.eu/top-1m.csv.zip",
             "format": "rank_domain", "enabled": True},
            {"name": "majestic", "url": "https://downloads.majestic.com/majestic_million.csv",
             "format": "majestic", "enabled": True},
            {"name": "umbrella",
             "url": "https://s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip",
             "format": "rank_domain", "enabled": False},
        ],
    },
    "openpagerank": {
        # Безкоштовний ключ на openpagerank.com; 100 доменів за запит.
        "enabled": "auto",
        "api_key_env": "SEGURO_OPR_KEY",
        # Відсів за OPR (0–10). null = лише метрика для скорингу.
        "min_score": None,
    },
    "rdap": {
        "enabled": True,
        "url": "https://rdap.org/domain/{domain}",
    },
    "safebrowsing": {
        # Google Safe Browsing v4, безкоштовний ключ; 500 доменів за запит.
        "enabled": "auto",
        "api_key_env": "SEGURO_GSB_KEY",
    },
    "wayback": {
        "enabled": True,
        "min_snapshots": 10,
        "min_years_active": 2,
        # Знімки беруться по одному на рік, від найсвіжіших; перший спам зупиняє перевірку.
        "max_samples": 6,
        "target_languages": ["uk", "en"],
        "reject_categories": ["pharma", "adult", "doorway_cjk"],
        "max_parking_ratio": 0.6,
    },
    "index": {
        # Google Custom Search JSON API: 100 запитів/день безкоштовно.
        "enabled": "auto",
        "api_key_env": "SEGURO_GOOGLE_API_KEY",
        "cx_env": "SEGURO_GOOGLE_CX",
        "max_domains_per_run": 90,
        "min_prelim_score": 40,
    },
    "backlinks": {
        # none | majestic | ahrefs | moz (для moz ключ у форматі access_id:secret)
        "provider": "none",
        "api_key_env": "SEGURO_BACKLINKS_KEY",
        "max_domains_per_run": 50,
        "min_prelim_score": 45,
        "min_ref_domains": 10,
        "min_tf_cf_ratio": 0.5,
        "max_spam_anchor_ratio": 0.2,
        "max_spam_score": 30,
    },
    "scoring": {
        "min_score": 40,
        "weights": {
            "history": 0.25,
            "backlinks": 0.20,
            "authority": 0.10,
            "topical": 0.15,
            "age": 0.10,
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
