"""RDAP: статус реєстрації (pending delete / redemption / вільний) і дати. Безкоштовно."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..models import Candidate, Result
from .base import BaseCheck, Context

# Якщо домен зареєстровано менш ніж стільки днів тому і він не в pending delete —
# його вже хтось перехопив, купити на дропі не вийде.
RECENT_DAYS = 45


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class RdapCheck(BaseCheck):
    """Інформаційна перевірка: нічого не відсіює, лише додає статус, дати та прапорці."""

    name = "rdap"

    async def run(self, cand: Candidate, result: Result, ctx: Context) -> None:
        url = self.cfg(ctx)["url"].format(domain=cand.domain)
        try:
            status, body = await ctx.http.get(url)
        except Exception:
            result.flag("rdap_error")
            return

        if status == 404:
            result.metrics["rdap_status"] = "available"
            return
        if status != 200:
            result.flag("rdap_error")
            return

        data = json.loads(body)
        statuses = [s.lower() for s in data.get("status") or []]
        result.metrics["rdap_status"] = ",".join(statuses)
        now = datetime.now(timezone.utc)
        for event in data.get("events") or []:
            action, date = event.get("eventAction"), _parse_date(event.get("eventDate", ""))
            if date is None:
                continue
            if action == "registration":
                result.metrics["registered"] = date.date().isoformat()
                result.metrics["registration_age_years"] = round((now - date).days / 365.25, 1)
                if (now - date).days < RECENT_DAYS and "pending delete" not in statuses:
                    result.flag("recently_registered")
            elif action == "expiration":
                result.metrics["expires"] = date.date().isoformat()
