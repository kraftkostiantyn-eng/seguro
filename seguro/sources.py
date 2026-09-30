"""Завантаження кандидатів із файлів.

Підтримується:
- .txt — один домен у рядку;
- .csv — будь-який експорт (ExpiredDomains.net, аукціони), де є колонка
  `domain` / `Domain` / `name`; решта колонок зберігається в `Candidate.extra`.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

from .models import Candidate

DOMAIN_COLUMNS = ("domain", "domain name", "name", "url")


def normalize_domain(raw: str) -> str | None:
    d = raw.strip().lower()
    if not d or d.startswith("#"):
        return None
    for prefix in ("http://", "https://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    d = d.split("/", 1)[0].split(":", 1)[0].rstrip(".")
    if d.startswith("www."):
        d = d[4:]
    if "." not in d:
        return None
    try:
        # IDN -> punycode, щоб усі перевірки працювали з ASCII.
        d = d.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    return d


def _find_domain_column(fieldnames: list[str]) -> str:
    lowered = {name.strip().lower(): name for name in fieldnames}
    for col in DOMAIN_COLUMNS:
        if col in lowered:
            return lowered[col]
    raise ValueError(f"CSV без колонки домену, очікується одна з {DOMAIN_COLUMNS}, є {fieldnames}")


def load_candidates(path: str | Path, source: str | None = None) -> Iterator[Candidate]:
    path = Path(path)
    source = source or path.stem
    seen: set[str] = set()

    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            reader = csv.DictReader(fh, dialect=dialect)
            col = _find_domain_column(reader.fieldnames or [])
            for row in reader:
                domain = normalize_domain(row.get(col) or "")
                if domain and domain not in seen:
                    seen.add(domain)
                    extra = {k: v for k, v in row.items() if k != col}
                    yield Candidate(domain=domain, source=source, extra=extra)
        return

    with path.open(encoding="utf-8") as fh:
        for line in fh:
            domain = normalize_domain(line)
            if domain and domain not in seen:
                seen.add(domain)
                yield Candidate(domain=domain, source=source)
