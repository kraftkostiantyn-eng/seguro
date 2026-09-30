"""Локальні списки, топ-списки, OpenPageRank, Safe Browsing, індексація."""

import io
import json
import zipfile

import httpx
import respx

from seguro.cache import CachedClient
from seguro.checks.base import Context
from seguro.checks.index import IndexCheck
from seguro.checks.localists import LocalListsCheck, matches
from seguro.checks.openpagerank import OpenPageRankCheck
from seguro.checks.safebrowsing import SafeBrowsingCheck
from seguro.checks.toplists import ToplistsCheck, scan
from seguro.models import Candidate, Result


def items(*domains):
    return [(Candidate(d), Result(d)) for d in domains]


def ctx_with_client(config):
    return Context(config, CachedClient(httpx.AsyncClient(), None))


# --- localists -------------------------------------------------------------

def test_matches_parent_domains():
    listed = {"bad.com", "evil.co.uk"}
    assert matches("bad.com", listed) == "bad.com"
    assert matches("sub.bad.com", listed) == "bad.com"
    assert matches("notbad.com", listed) is None
    assert matches("evil.co.uk", listed) == "evil.co.uk"


async def test_localists_reject_and_flag(config, tmp_path):
    (tmp_path / "rkn.txt").write_text("blocked.com\nwww.also.net\n")
    (tmp_path / "mine.csv").write_text("domain,bought\nmine.com,2025\n")
    config["localists"]["reject"] = [{"name": "rkn", "path": str(tmp_path / "rkn.txt")}]
    config["localists"]["flag"] = [{"name": "mine", "path": str(tmp_path / "mine.csv")}]
    ctx = Context(config, None)
    check = LocalListsCheck()
    assert check.enabled(ctx)
    check.validate(ctx)
    await check.prepare(ctx)

    for domain, expect_reject, expect_flag in [
        ("blocked.com", True, False), ("also.net", True, False),
        ("mine.com", False, True), ("clean.com", False, False),
    ]:
        res = Result(domain)
        await check.run(Candidate(domain), res, ctx)
        assert res.rejected is expect_reject, domain
        assert ("list_mine" in res.flags) is expect_flag, domain


def test_localists_disabled_without_lists(config):
    assert not LocalListsCheck().enabled(Context(config, None))


# --- toplists --------------------------------------------------------------

def test_scan_formats():
    tranco = io.StringIO("1,google.com\n2,www.sport.com\n3,api.sport.com\n4,other.org\n")
    found = scan(tranco, "rank_domain", {"sport.com", "missing.com"})
    assert found == {"sport.com": (2, {})}

    majestic = io.StringIO(
        "GlobalRank,TldRank,Domain,TLD,RefSubNets,RefIPs\n"
        "5,1,news.org,org,1200,3400\n6,2,zzz.org,org,1,1\n"
    )
    found = scan(majestic, "majestic", {"news.org"})
    assert found["news.org"][0] == 5 and found["news.org"][1]["ref_subnets"] == "1200"


@respx.mock
async def test_toplists_download_once_and_match(config, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("top-1m.csv", "1,google.com\n77,sport.com\n")
    route = respx.get("https://tranco-list.eu/top-1m.csv.zip").mock(
        return_value=httpx.Response(200, content=buf.getvalue())
    )
    config["toplists"]["enabled"] = True
    config["toplists"]["lists"] = [
        {"name": "tranco", "url": "https://tranco-list.eu/top-1m.csv.zip", "format": "rank_domain"},
    ]
    ctx = ctx_with_client(config)
    check = ToplistsCheck()
    batch = items("sport.com", "nobody.com")

    await check.prepare(ctx)
    await check.run_batch(batch, ctx)
    await check.prepare(ctx)  # свіжий файл не перекачується
    assert route.call_count == 1
    assert batch[0][1].metrics["top_tranco_rank"] == 77 and "in_tranco" in batch[0][1].flags
    assert "top_tranco_rank" not in batch[1][1].metrics


# --- openpagerank ----------------------------------------------------------

@respx.mock
async def test_openpagerank_batch(config, monkeypatch):
    monkeypatch.setenv("SEGURO_OPR_KEY", "k")
    respx.get("https://openpagerank.com/api/v1.0/getPageRank").mock(
        return_value=httpx.Response(200, json={"response": [
            {"domain": "good.com", "status_code": 200, "page_rank_decimal": 4.2, "rank": 12345},
            {"domain": "weak.com", "status_code": 200, "page_rank_decimal": 0.5, "rank": None},
            {"domain": "none.com", "status_code": 404, "error": "Domain not found"},
        ]})
    )
    config["openpagerank"]["min_score"] = 1
    ctx = ctx_with_client(config)
    check = OpenPageRankCheck()
    assert check.enabled(ctx)
    batch = items("good.com", "weak.com", "none.com")
    await check.run_batch(batch, ctx)
    good, weak, none = (r for _, r in batch)
    assert good.metrics == {"opr_score": 4.2, "opr_rank": 12345} and not good.rejected
    assert weak.rejected_by == "openpagerank"
    assert not none.rejected and "opr_score" not in none.metrics


def test_auto_enabled_needs_key(config):
    assert not OpenPageRankCheck().enabled(Context(config, None))


# --- safebrowsing ----------------------------------------------------------

@respx.mock
async def test_safebrowsing_batch(config, monkeypatch):
    monkeypatch.setenv("SEGURO_GSB_KEY", "secret")
    route = respx.post("https://safebrowsing.googleapis.com/v4/threatMatches:find").mock(
        return_value=httpx.Response(200, json={"matches": [
            {"threatType": "MALWARE", "threat": {"url": "http://bad.com/"}},
        ]})
    )
    ctx = ctx_with_client(config)
    batch = items("bad.com", "ok.com")
    await SafeBrowsingCheck().run_batch(batch, ctx)
    assert batch[0][1].rejected_by == "safebrowsing" and "MALWARE" in batch[0][1].reject_reason
    assert not batch[1][1].rejected
    sent = json.loads(route.calls[0].request.content)
    assert [e["url"] for e in sent["threatInfo"]["threatEntries"]] == ["http://bad.com/", "http://ok.com/"]
    assert route.calls[0].request.url.params["key"] == "secret"


# --- index -----------------------------------------------------------------

@respx.mock
async def test_index_check_deindexed_logic(config, monkeypatch):
    monkeypatch.setenv("SEGURO_GOOGLE_API_KEY", "k")
    monkeypatch.setenv("SEGURO_GOOGLE_CX", "cx1")

    def respond(request):
        q = request.url.params["q"]
        total = "0" if "dead" in q else "42"
        return httpx.Response(200, json={"searchInformation": {"totalResults": total}})

    respx.get("https://www.googleapis.com/customsearch/v1").mock(side_effect=respond)
    ctx = ctx_with_client(config)
    check = IndexCheck()
    check.validate(ctx)

    live = Result("live.com")
    await check.run(Candidate("live.com"), live, ctx)
    assert live.metrics["indexed_pages"] == 42 and not live.flags

    dead_recent = Result("dead-recent.com", metrics={"wb_last_seen_months_ago": 3})
    await check.run(Candidate("dead-recent.com"), dead_recent, ctx)
    assert {"not_indexed", "possibly_deindexed"} <= set(dead_recent.flags)

    dead_old = Result("dead-old.com", metrics={"wb_last_seen_months_ago": 40})
    await check.run(Candidate("dead-old.com"), dead_old, ctx)
    assert dead_old.flags == ["not_indexed"]
