from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..cache import CachedClient
from ..models import Candidate, Result


@dataclass
class Context:
    config: dict[str, Any]
    http: CachedClient


class Check(Protocol):
    """Етап воронки. Може записати метрики, прапорці або відхилити домен через `result.reject`."""

    name: str

    def enabled(self, ctx: Context) -> bool: ...

    async def run(self, cand: Candidate, result: Result, ctx: Context) -> None: ...
