import json
from datetime import datetime, timezone

import httpx
import respx

from seguro.cache import CachedClient
from seguro.checks.base import Context
from seguro.checks.wayback import (
    CDX_URL, Capture, WaybackCheck, longest_gap_months, months_since, parse_cdx, pick_samples,
)
from seguro.models import Candidate, Result

SPORT_PAGE = (
    "<html><title>Football news</title><body>"
    + "The football match in the league was great and this is the news for you. " * 10
    + "</body></html>"
)
PHARMA_PAGE = "<p>" + "buy viagra cialis pharmacy online and the best offer for you. " * 10 + "</p>"
PARKING_PAGE = "<p>This domain is for sale. " + "Buy this domain today from the owner. " * 10 + "</p>"


def cdx(years, digest_per_year=True):
    rows = [["timestamp", "digest", "length"]]
    for y in years:
        for month in ("01", "06"):
            digest = f"D{y}{month}" if digest_per_year else "SAME"
            rows.append([f"{y}{month}15120000", digest, str(4000 + int(month))])
    return json.dumps(rows)


def test_parse_and_pick():
    caps = parse_cdx(cdx(range(2010, 2020)))
    assert len(caps) == 20 and caps[0].ts.startswith("2010")
    picked = pick_samples(caps, max_samples=4)
    assert [c.year for c in picked] == ["2019", "2018", "2017", "2016"]
    assert all(c.ts[4:6] == "06" for c in picked)  # більший знімок року
    assert parse_cdx("") == []


def test_gaps_and_months():
    caps = [Capture("201001"), Capture("201006"), Capture("201501")]
    assert longest_gap_months(caps) == 55
    assert months_since("20250301000000", datetime(2026, 9, 30, tzinfo=timezone.utc)) == 18


def ctx(config):
    return Context(config, CachedClient(httpx.AsyncClient(), None, host_limits={"web.archive.org": 3}))


@respx.mock
async def test_early_exit_on_spam_saves_requests(config):
    respx.get(CDX_URL).mock(return_value=httpx.Response(200, text=cdx(range(2012, 2022))))
    snap = respx.get(url__regex=r"https://web\.archive\.org/web/(?P<ts>\d+)id_/.*").mock(
        side_effect=lambda request, ts: httpx.Response(
            200, text=PHARMA_PAGE if ts.startswith("2021") else SPORT_PAGE
        )
    )
    res = Result("x.com")
    await WaybackCheck().run(Candidate("x.com"), res, ctx(config))
    assert res.rejected_by == "wayback" and "2021-06" in res.reject_reason
    assert snap.call_count == 1  # найсвіжіший знімок — спам, далі не качаємо
    assert res.metrics["wb_years_active"] == 10 and res.metrics["wb_sampled"] == 1


@respx.mock
async def test_parking_early_exit(config):
    config["wayback"]["max_samples"] = 4
    respx.get(CDX_URL).mock(return_value=httpx.Response(200, text=cdx(range(2016, 2022))))
    snap = respx.get(url__regex=r"https://web\.archive\.org/web/\d+id_/.*").mock(
        return_value=httpx.Response(200, text=PARKING_PAGE)
    )
    res = Result("p.com")
    await WaybackCheck().run(Candidate("p.com"), res, ctx(config))
    assert res.rejected_by == "wayback" and "паркінг" in res.reject_reason
    assert snap.call_count == 3  # 3/4 > 0.6 — решту не качаємо


@respx.mock
async def test_static_and_revived_flags(config):
    rows = [["timestamp", "digest", "length"]]
    rows += [[f"2010{m:02d}01000000", "SAME", "900"] for m in range(1, 13)]
    rows += [[f"2016{m:02d}01000000", "SAME", "900"] for m in range(1, 13)]
    respx.get(CDX_URL).mock(return_value=httpx.Response(200, text=json.dumps(rows)))
    respx.get(url__regex=r"https://web\.archive\.org/web/\d+id_/.*").mock(
        return_value=httpx.Response(200, text=SPORT_PAGE)
    )
    res = Result("s.com")
    await WaybackCheck().run(Candidate("s.com"), res, ctx(config))
    assert not res.rejected
    assert {"wb_static", "wb_revived"} <= set(res.flags)
    assert res.metrics["wb_unique_ratio"] == round(1 / 24, 2)
    assert res.metrics["wb_longest_gap_months"] == 61


@respx.mock
async def test_cdx_error_is_error_not_rejection(config):
    respx.get(CDX_URL).mock(return_value=httpx.Response(403))
    res = Result("e.com")
    await WaybackCheck().run(Candidate("e.com"), res, ctx(config))
    assert not res.rejected and "wayback_error" in res.flags
