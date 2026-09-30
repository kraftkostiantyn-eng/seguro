"""Перевірка доменних чорних списків (DNSBL/URIBL) через DNS-запити — безкоштовно."""

from __future__ import annotations

import asyncio

import dns.asyncresolver
import dns.exception
import dns.resolver

from ..models import Candidate, Result
from .base import BaseCheck, Context

# Відповіді 127.255.255.x / 127.0.0.1 від Spamhaus і URIBL означають помилку запиту
# (публічний резолвер, перевищено ліміт), а не лістинг.
_ERROR_ANSWERS = {"127.255.255.252", "127.255.255.254", "127.255.255.255", "127.0.0.1"}


class BlacklistCheck(BaseCheck):
    name = "blacklist"

    def __init__(self) -> None:
        self._resolver: dns.asyncresolver.Resolver | None = None

    def _get_resolver(self, ctx: Context) -> dns.asyncresolver.Resolver:
        if self._resolver is None:
            cfg = self.cfg(ctx)
            resolver = dns.asyncresolver.Resolver()
            if cfg.get("nameservers"):
                resolver.nameservers = list(cfg["nameservers"])
            resolver.lifetime = float(cfg.get("timeout", 5.0))
            self._resolver = resolver
        return self._resolver

    async def lookup(self, query: str, ctx: Context) -> list[str] | None:
        """Повертає A-записи (лістинг), [] якщо чисто, None якщо відповідь невалідна."""
        try:
            answer = await self._get_resolver(ctx).resolve(query, "A")
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return []
        except (dns.exception.Timeout, dns.resolver.NoNameservers):
            return None
        ips = [r.to_text() for r in answer]
        if any(ip in _ERROR_ANSWERS for ip in ips):
            return None
        return ips

    async def run(self, cand: Candidate, result: Result, ctx: Context) -> None:
        zones = self.cfg(ctx)["zones"]
        answers = await asyncio.gather(*(self.lookup(f"{cand.domain}.{z}", ctx) for z in zones))

        listed = [z for z, ips in zip(zones, answers) if ips]
        unknown = [z for z, ips in zip(zones, answers) if ips is None]
        result.metrics["blacklists"] = ",".join(listed)
        if unknown:
            result.flag("dnsbl_unverified")
        if listed:
            result.reject(self.name, f"у чорних списках: {', '.join(listed)}")
