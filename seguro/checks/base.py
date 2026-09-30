from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ..cache import CachedClient
from ..models import Candidate, Result

Item = tuple[Candidate, Result]


@dataclass
class Context:
    config: dict[str, Any]
    http: CachedClient
    # Спільний стан між етапами (завантажені списки тощо).
    state: dict[str, Any] = field(default_factory=dict)


class BaseCheck:
    """Етап воронки.

    - `costly=True` — платні або квотовані виклики: на них діють бюджети
      (`max_domains_per_run`, `min_prelim_score`) і прапорець `--free-only`.
    - `batch_size=None` — обробка по одному домену через `run`;
      число — пакетами через `run_batch` (0 = усі домени одним пакетом).
    """

    name: str = "base"
    costly: bool = False
    batch_size: int | None = None

    def cfg(self, ctx: Context) -> dict[str, Any]:
        return ctx.config.get(self.name) or {}

    def enabled(self, ctx: Context) -> bool:
        """`enabled: true|false|auto` — auto вмикає етап, якщо задано ключ API."""
        value = self.cfg(ctx).get("enabled", True)
        if value == "auto":
            env = self.cfg(ctx).get("api_key_env")
            return bool(env and os.environ.get(env))
        return bool(value)

    def api_key(self, ctx: Context) -> str:
        env = self.cfg(ctx).get("api_key_env", "")
        key = os.environ.get(env, "")
        if not key:
            raise RuntimeError(f"етап {self.name}: не задано змінну оточення {env}")
        return key

    def validate(self, ctx: Context) -> None:
        """Перевірка ключів і файлів до старту прогону. Кидає RuntimeError."""

    async def prepare(self, ctx: Context) -> None:
        """Одноразова підготовка перед першим доменом (завантажити списки тощо)."""

    async def run(self, cand: Candidate, result: Result, ctx: Context) -> None:
        raise NotImplementedError

    async def run_batch(self, items: list[Item], ctx: Context) -> None:
        raise NotImplementedError
