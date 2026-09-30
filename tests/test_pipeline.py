import json

import httpx
import respx

from seguro.checks.base import BaseCheck
from seguro.checks.wayback import CDX_URL
from seguro.models import Candidate
from seguro.pipeline import run_pipeline, write_csv

SPORT_PAGE = (
    "<html><title>Football news</title><body>"
    + "The football match in the league was great and this is the news for you. " * 10
    + "</body></html>"
)
PHARMA_PAGE = "<p>" + "buy viagra cialis pharmacy online and the best offer for you. " * 10 + "</p>"


def cdx(years):
    rows = [["timestamp", "digest", "length"]]
    for y in years:
        for month in ("01", "06"):
            rows.append([f"{y}{month}15120000", f"D{y}{month}", "5000"])
    return json.dumps(rows)


@respx.mock
async def test_end_to_end(config, tmp_path):
    def cdx_route(request):
        domain = request.url.params["url"]
        return httpx.Response(200, text=cdx([2021] if domain == "young.com" else range(2012, 2022)))

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

    cands = [Candidate(d, source="test") for d in
             ("goodsport.com", "pharmaold.com", "young.com", "bad-name-here.com")]
    report = await run_pipeline(cands, config)
    results = {r.domain: r for r in report.results}

    good = results["goodsport.com"]
    assert not good.rejected, good.reject_reason
    assert good.score and good.score >= config["scoring"]["min_score"]
    assert good.metrics["rdap_status"] == "pending delete"
    assert "sport" in good.metrics["wb_topics"]
    assert good.source == "test"

    assert results["pharmaold.com"].rejected_by == "wayback"
    assert results["young.com"].rejected_by == "wayback"
    assert results["bad-name-here.com"].rejected_by == "prefilter"

    stages = {s.name: s for s in report.stages}
    assert stages["prefilter"].entered == 4 and stages["prefilter"].rejected == 1
    assert stages["wayback"].entered == 3 and stages["wayback"].rejected == 2
    assert "index" not in stages and "backlinks" not in stages  # без ключів вимкнені
    assert report.http_stats["web.archive.org"]["requests"] > 0

    out = tmp_path / "out.csv"
    assert write_csv(report.results, out, include_rejected=False) == 1
    text = out.read_text()
    assert "goodsport.com" in text and text.startswith("domain,source,status,score")


@respx.mock
async def test_no_data_is_not_candidate(config):
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(403))
    report = await run_pipeline([Candidate("goodsport.com")], config)
    assert report.results[0].rejected_by == "no_data"


class FreeStage(BaseCheck):
    name = "free"

    async def run(self, cand, result, ctx):
        result.metrics.update({
            "wb_clean_ratio": {"a.com": 1.0, "b.com": 0.3, "c.com": 0.9}[cand.domain],
            "wb_years_active": 8, "wb_topic_ratio": 1.0, "wb_geo_ratio": 1.0,
        })


class PaidStage(BaseCheck):
    name = "paid"
    costly = True

    def __init__(self):
        self.calls = []

    async def run(self, cand, result, ctx):
        self.calls.append(cand.domain)
        result.metrics["bl_ref_domains"] = 100


async def test_budget_sends_only_best_to_paid_stage(config):
    config["paid"] = {"max_domains_per_run": 1, "min_prelim_score": 50}
    paid = PaidStage()
    report = await run_pipeline([Candidate(d) for d in ("b.com", "a.com", "c.com")],
                                config, checks=[FreeStage(), paid])
    assert paid.calls == ["a.com"]
    by = {r.domain: r for r in report.results}
    assert "paid_skipped_budget" in by["c.com"].flags and not by["c.com"].rejected
    assert by["a.com"].prelim_score and by["a.com"].prelim_score >= by["c.com"].prelim_score
    assert [s.skipped for s in report.stages if s.name == "paid"] == [2]


async def test_free_only_skips_costly_stages(config):
    config["free_only"] = True
    paid = PaidStage()
    await run_pipeline([Candidate("a.com")], config, checks=[FreeStage(), paid])
    assert paid.calls == []


class BrokenBatch(BaseCheck):
    name = "broken"
    batch_size = 2

    async def run_batch(self, items, ctx):
        raise RuntimeError("API down")


class BrokenPrepare(BaseCheck):
    name = "noprep"

    async def prepare(self, ctx):
        raise RuntimeError("no file")

    async def run(self, cand, result, ctx):
        raise AssertionError("не має викликатись")


async def test_stage_failures_flag_but_do_not_reject(config):
    cands = [Candidate(d) for d in ("a.com", "b.com", "c.com")]
    report = await run_pipeline(cands, config, checks=[BrokenBatch(), BrokenPrepare(), FreeStage()])
    for r in report.results:
        assert {"broken_error", "noprep_error"} <= set(r.flags)
        assert not r.rejected
    errors = {s.name: s.errors for s in report.stages}
    assert errors == {"broken": 3, "noprep": 3, "free": 0}
