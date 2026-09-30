from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Candidate:
    """Домен-кандидат із джерела (дроп-лист, аукціон, експорт)."""

    domain: str
    source: str = "file"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def tld(self) -> str:
        return self.domain.rsplit(".", 1)[-1]

    @property
    def sld(self) -> str:
        """Ім'я без зони: для `best-bets.co.uk` -> `best-bets`."""
        return self.domain.split(".", 1)[0]


@dataclass
class Result:
    """Накопичений результат перевірок одного домену."""

    domain: str
    source: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    rejected_by: str | None = None
    reject_reason: str | None = None
    score: float | None = None
    # Попередня оцінка за безкоштовними етапами — нею відбираємо, кого пускати на платні.
    prelim_score: float | None = None

    @property
    def rejected(self) -> bool:
        return self.rejected_by is not None

    def reject(self, stage: str, reason: str) -> None:
        self.rejected_by = stage
        self.reject_reason = reason

    def flag(self, name: str) -> None:
        if name not in self.flags:
            self.flags.append(name)
