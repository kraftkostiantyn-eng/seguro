"""Розбір списків доменів: .txt, .csv, .json, а також zip з такими файлами.

- .txt — один домен у рядку;
- .csv — будь-який експорт (ExpiredDomains.net, аукціони) з колонкою `Domain`/`name`;
  решта колонок зберігається в `Candidate.extra` і доступна для порогів у prefilter;
- .json — дампи аукціонів (GoDaddy тощо): шукаються об'єкти з полем домену.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Any, Iterator

from ..models import Candidate

DOMAIN_COLUMNS = ("domain", "domain name", "domainname", "domain_name", "name", "url")


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
    if "." not in d or " " in d:
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


def iter_text(text: str, source: str) -> Iterator[Candidate]:
    for line in text.splitlines():
        # У списках виду "domain,extra" або "domain\textra" беремо перше поле.
        field = line.replace(";", ",").replace("\t", ",").split(",", 1)[0]
        domain = normalize_domain(field)
        if domain:
            yield Candidate(domain=domain, source=source)


def iter_csv(text: str, source: str) -> Iterator[Candidate]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    col = _find_domain_column(reader.fieldnames or [])
    for row in reader:
        domain = normalize_domain(row.get(col) or "")
        if not domain:
            continue
        extra = {k: v for k, v in row.items() if k != col and k is not None}
        row_source = extra.pop("source", None) or source
        packed = extra.pop("extra", None)
        if packed:
            try:
                extra.update(json.loads(packed))
            except (TypeError, ValueError):
                extra["extra"] = packed
        yield Candidate(domain=domain, source=row_source, extra=extra)


def iter_json(data: Any, source: str) -> Iterator[Candidate]:
    if isinstance(data, list):
        for item in data:
            yield from iter_json(item, source)
        return
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        if key.lower() in DOMAIN_COLUMNS and isinstance(value, str):
            domain = normalize_domain(value)
            if domain:
                extra = {k: v for k, v in data.items() if k != key and isinstance(v, (str, int, float))}
                yield Candidate(domain=domain, source=source, extra=extra)
            return
    for value in data.values():
        if isinstance(value, (list, dict)):
            yield from iter_json(value, source)


def iter_payload(data: bytes, filename: str, source: str) -> Iterator[Candidate]:
    """Визначає формат за розширенням/вмістом і віддає кандидатів (без дублів)."""
    seen: set[str] = set()
    for cand in _iter_payload(data, filename, source):
        if cand.domain not in seen:
            seen.add(cand.domain)
            yield cand


def _iter_payload(data: bytes, filename: str, source: str) -> Iterator[Candidate]:
    lower = filename.lower()
    if lower.endswith(".zip") or data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                if not name.endswith("/"):
                    yield from _iter_payload(zf.read(name), name, source)
        return

    text = data.decode("utf-8-sig", errors="replace")
    if lower.endswith(".json") or text.lstrip()[:1] in "[{":
        try:
            yield from iter_json(json.loads(text), source)
            return
        except ValueError:
            pass
    if lower.endswith((".csv", ".tsv")):
        yield from iter_csv(text, source)
        return
    yield from iter_text(text, source)


def load_candidates(path: str | Path, source: str | None = None) -> Iterator[Candidate]:
    path = Path(path)
    yield from iter_payload(path.read_bytes(), path.name, source or path.stem)


def load_domain_set(path: str | Path) -> set[str]:
    """Множина доменів із файлу-списку (для локальних чорних/білих списків)."""
    return {c.domain for c in load_candidates(path)}
