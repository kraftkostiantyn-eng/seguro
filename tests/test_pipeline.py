import json

import httpx
import respx

from seguro.checks.wayback import CDX_URL, pick_samples
from seguro.models import Candidate
from seguro.pipeline import run_pipeline, write_csv

SPORT_PAGE = (
    "<html><title>Football news</title><body>"
    + "The football match in the league was great and this is the news for you. " * 10
    + "</body></html>"
)
PHARMA_PAGE = "<p>" + "buy viagra cialis pharmacy online and the best offer for you. " * 10 + "</p>"


def cdx(years):
    rows = [["timestamp", "statuscode"]]
    for y in years:
        for month in ("01", "06"):
            rows.append([f"{y}{month}15120000", "200"])
    return json.dumps(rows)


def test_pick_samples():
    ts = [f"{y}0{m}01000000" for y in range(2010, 2020) for m in range(1, 4)]
    samples = pick_samples(ts, per_year=1, max_samples=4)
    assert [s[:4] for s in samples] == ["2016", "2017", "2018", "2019"]


@respx.mock
async def test_end_to_end(config, tmp_path):
    years = range(2012, 2022)

    def cdx_route(request):
        domain = request.url.params["url"]
        if domain == "young.com":
            return httpx.Response(200, text=cdx([2021]))
        return httpx.Response(200, text=cdx(years))

    def snapshot_route(request):
        page = PHARMA_PAGE if "pharmaold.com" in str(request.url) else SPORT_PAGE
        return httpx.Response(200, text=page)

    respx.get(CDX_URL).mock(side_effect=cdx_route)
    respx.get(url__regex=r"https://web\.archive\.org/web/\d+id_/.*").mock(side_effect=snapshot_route)
    respx.get(url__regex=r"https://rdap\.org/domain/.*").mock(
        return_value=httpx.Response(200, json={
            "status": ["pending delete"],
            "events": [{"eventAction": "registration", "eventDate": "2012-01-01T00:00:00Z"}],
        })
    )

    cands = [Candidate(d) for d in ("goodsport.com", "pharmaold.com", "young.com", "bad-name-here.com")]
    results = {r.domain: r for r in await run_pipeline(cands, config)}

    good = results["goodsport.com"]
    assert not good.rejected, good.reject_reason
    assert good.score and good.score >= config["scoring"]["min_score"]
    assert good.metrics["rdap_status"] == "pending delete"
    assert "sport" in good.metrics["wb_topics"]

    assert results["pharmaold.com"].rejected_by == "wayback"
    assert results["young.com"].rejected_by == "wayback"
    assert results["bad-name-here.com"].rejected_by == "prefilter"

    out = tmp_path / "out.csv"
    assert write_csv(list(results.values()), out, include_rejected=False) == 1
    assert "goodsport.com" in out.read_text()


@respx.mock
async def test_no_data_is_not_candidate(config):
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(403))
    [res] = await run_pipeline([Candidate("goodsport.com")], config)
    assert res.rejected_by == "no_data"
