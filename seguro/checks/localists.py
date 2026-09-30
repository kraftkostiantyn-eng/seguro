"""Локальні списки доменів: реєстри блокувань регуляторів, власні чорні списки, вже куплені домени.

Безкоштовно і без мережі. Збіг — і сам домен, і батьківський (`a.example.com` -> `example.com`).
"""

from __future__ import annotations

from pathlib import Path

from ..models import Candidate, Result
from ..sources.files import load_domain_set
from .base import BaseCheck, Context


def matches(domain: str, listed: set[str]) -> str | None:
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in listed:
            return suffix
    return None


class LocalListsCheck(BaseCheck):
    name = "localists"

    def _specs(self, ctx: Context) -> list[tuple[str, str, str]]:
        cfg = self.cfg(ctx)
        return [(action, s["name"], s["path"])
                for action in ("reject", "flag") for s in (cfg.get(action) or [])]

    def enabled(self, ctx: Context) -> bool:
        return super().enabled(ctx) and bool(self._specs(ctx))

    def validate(self, ctx: Context) -> None:
        missing = [path for _, _, path in self._specs(ctx) if not Path(path).exists()]
        if missing:
            raise RuntimeError(f"localists: файли не знайдено: {', '.join(missing)}")

    async def prepare(self, ctx: Context) -> None:
        ctx.state["localists"] = [
            (action, name, load_domain_set(path)) for action, name, path in self._specs(ctx)
        ]

    async def run(self, cand: Candidate, result: Result, ctx: Context) -> None:
        for action, name, listed in ctx.state.get("localists", []):
            hit = matches(cand.domain, listed)
            if hit is None:
                continue
            if action == "reject":
                return result.reject(self.name, f"у списку {name} ({hit})")
            result.flag(f"list_{name}")
