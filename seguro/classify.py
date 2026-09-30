"""Класифікація HTML-знімків з архіву: мова, паркінг, спам-категорії, тематика.

Навмисно проста евристика на словниках — швидка й прозора. Для складних випадків
цей модуль можна замінити на LLM-класифікатор із тим самим інтерфейсом.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

_TAG_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_WORD_RE = re.compile(r"\w+", re.U)

PARKING_MARKERS = [
    "this domain is for sale", "this domain may be for sale", "buy this domain",
    "domain is parked", "parked free", "sedo.com", "parkingcrew", "bodis", "dan.com",
    "afternic", "hugedomains", "godaddy.com/domainsearch", "domain has expired",
    "домен продается", "домен продається", "домен припаркован",
]

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "pharma": ["viagra", "cialis", "levitra", "pharmacy", "tramadol", "xanax", "без рецепта"],
    "adult": ["porn", "xxx", "sex video", "escort", "порно", "эскорт", "секс знакомства"],
    "gambling": ["casino", "slots", "betting", "bookmaker", "poker", "roulette", "jackpot",
                 "казино", "слоти", "ставки", "букмекер", "покер", "рулетка"],
    "loans": ["payday loan", "микрозайм", "кредит онлайн", "позика онлайн"],
    "replica": ["replica watches", "cheap nike", "louis vuitton outlet"],
}

# Теми, що добре лягають під гемблінг-проєкти.
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "sport": ["football", "soccer", "match", "league", "tennis", "hockey", "sport",
              "футбол", "матч", "ліга", "лига", "спорт", "хокей", "хоккей", "теніс"],
    "games": ["game", "gaming", "esports", "playstation", "xbox", "steam",
              "гра", "ігри", "игры", "кіберспорт", "киберспорт"],
    "finance": ["finance", "money", "crypto", "bitcoin", "invest", "bank",
                "фінанси", "финансы", "гроші", "деньги", "крипто", "інвест"],
    "entertainment": ["movie", "music", "celebrity", "entertainment", "tv show",
                      "кіно", "кино", "музика", "музыка", "розваги", "развлечения"],
    "news": ["news", "новини", "новости", "breaking"],
}

LANG_STOPWORDS: dict[str, set[str]] = {
    "en": {"the", "and", "of", "to", "is", "in", "for", "with", "you", "this"},
    "uk": {"і", "та", "що", "не", "на", "для", "це", "як", "від", "але", "й", "з"},
    "ru": {"и", "что", "не", "на", "для", "это", "как", "от", "но", "по", "он", "же"},
    "pl": {"i", "w", "nie", "się", "na", "że", "jest", "do", "z", "to", "jak"},
    "de": {"und", "der", "die", "das", "ist", "nicht", "mit", "für", "auf", "ein"},
    "es": {"el", "la", "de", "que", "y", "en", "los", "para", "con", "una", "por"},
    "fr": {"le", "la", "les", "et", "des", "est", "pour", "dans", "une", "que", "pas"},
    "it": {"il", "di", "che", "e", "la", "per", "un", "non", "con", "sono", "della"},
}


@dataclass
class PageClass:
    language: str | None = None
    is_parking: bool = False
    is_empty: bool = False
    categories: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    cjk_ratio: float = 0.0
    title: str = ""

    @property
    def is_clean_content(self) -> bool:
        return not (self.is_parking or self.is_empty or self.spam_categories)

    @property
    def spam_categories(self) -> list[str]:
        spam = [c for c in self.categories if c != "gambling"]
        if self.cjk_ratio > 0.3:
            spam.append("doorway_cjk")
        return spam


def html_to_text(raw: str) -> tuple[str, str]:
    m = _TITLE_RE.search(raw)
    title = html.unescape(m.group(1)).strip() if m else ""
    text = html.unescape(_TAG_RE.sub(" ", raw))
    return title, re.sub(r"\s+", " ", text).strip()


def _cjk_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    cjk = sum(
        1 for ch in letters
        if "぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" or "가" <= ch <= "힯"
    )
    return cjk / len(letters)


def detect_language(words: list[str]) -> str | None:
    if len(words) < 20:
        return None
    scores = {lang: sum(1 for w in words if w in sw) for lang, sw in LANG_STOPWORDS.items()}
    # Українську від російської відрізняємо за специфічними літерами.
    joined = " ".join(words)
    if any(ch in joined for ch in "їєґі"):
        scores["uk"] += 5
    if any(ch in joined for ch in "ыэъё"):
        scores["ru"] += 5
    lang, best = max(scores.items(), key=lambda kv: kv[1])
    return lang if best >= 3 else None


def _count_hits(text: str, keywords: list[str]) -> int:
    return sum(text.count(k) for k in keywords)


def classify_html(raw: str) -> PageClass:
    title, text = html_to_text(raw)
    low = f"{title} {text}".lower()
    words = _WORD_RE.findall(low)
    result = PageClass(title=title[:200], cjk_ratio=_cjk_ratio(text))

    if len(words) < 30:
        result.is_empty = True
    if any(marker in low for marker in PARKING_MARKERS):
        result.is_parking = True

    result.language = detect_language(words)
    for cat, kws in CATEGORY_KEYWORDS.items():
        # Поріг у 3 входження, щоб одиничне слово в новині не робило сайт «спамним».
        if _count_hits(low, kws) >= 3:
            result.categories.append(cat)
    for topic, kws in TOPIC_KEYWORDS.items():
        if _count_hits(low, kws) >= 3:
            result.topics.append(topic)
    return result
