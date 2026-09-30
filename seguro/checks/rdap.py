"""RDAP: статус реєстрації (pending delete / redemption / вільний) і дати."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..models import Candidate, Result
from .base import Context


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class RdapCheck:
    """Інформаційна перевірка: нічого не відсіює, лише додає статус і дати."""

    name = "rdap"

    def enabled(self, ctx: Context) -> bool:
        return bool(ctx.config["rdap"].get("enabled"))

    async def run(self, cand: Candidate, result: Result, ctx: Context) -> None:
        url = ctx.config["rdap"]["url"].format(domain=cand.domain)
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
        result.metrics["rdap_status"] = ",".join(data.get("status") or [])
        for event in data.get("events") or []:
            action, date = event.get("eventAction"), _parse_date(event.get("eventDate", ""))
            if date is None:
                continue
            if action == "registration":
                result.metrics["registered"] = date.date().isoformat()
                years = (datetime.now(timezone.utc) - date).days / 365.25
                result.metrics["registration_age_years"] = round(years, 1)
            elif action == "expiration":
                result.metrics["expires"] = date.date().isoformat()
