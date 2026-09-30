import io
import json
import zipfile
from datetime import datetime

import httpx
import respx

from seguro.sources import fetch_all, iter_payload, load_candidates, normalize_domain, resolve_url


def test_normalize():
    assert normalize_domain("https://www.Example.COM/path") == "example.com"
    assert normalize_domain("# comment") is None
    assert normalize_domain("localhost") is None
    assert normalize_domain("футбол.укр") == "футбол.укр".encode("idna").decode()


def test_txt_dedup_and_extra_fields(tmp_path):
    p = tmp_path / "list.txt"
    p.write_text("a.com\nA.com\n\nb.net,2026-10-01\nc.org\tbid=5\n")
    assert [c.domain for c in load_candidates(p)] == ["a.com", "b.net", "c.org"]


def test_csv_expireddomains_export(tmp_path):
    p = tmp_path / "export.csv"
    p.write_text("Domain;BL;DP;ABY\nsport-news.com;120;30;2009\nbad;1;1;2020\n", encoding="utf-8")
    cands = list(load_candidates(p))
    assert [c.domain for c in cands] == ["sport-news.com"]
    assert cands[0].extra["ABY"] == "2009"
    assert cands[0].source == "export"


def test_csv_from_fetch_roundtrip(tmp_path):
    p = tmp_path / "candidates.csv"
    p.write_text('domain,source,extra\na.com,godaddy,"{""price"": 12}"\n', encoding="utf-8")
    [cand] = load_candidates(p)
    assert cand.source == "godaddy" and cand.extra == {"price": 12}


def test_json_and_zip_payloads():
    data = {"data": [{"domainName": "Auction.com", "price": 10, "bids": [1]}, {"other": 1}]}
    cands = list(iter_payload(json.dumps(data).encode(), "dump.json", "gd"))
    assert [(c.domain, c.extra) for c in cands] == [("auction.com", {"price": 10})]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("list.txt", "one.com\ntwo.com\n")
        zf.writestr("dump.json", json.dumps(data))
    cands = list(iter_payload(buf.getvalue(), "bundle.zip", "z"))
    assert [c.domain for c in cands] == ["one.com", "two.com", "auction.com"]


def test_resolve_url_with_date():
    spec = {"type": "namejet"}
    assert resolve_url(spec, datetime(2026, 9, 30)).endswith("/09-30-2026.txt")
    assert resolve_url({"type": "url", "url": "https://x/y.txt"}) == "https://x/y.txt"


@respx.mock
async def test_fetch_all_merges_and_survives_failures():
    respx.get("https://lists.example/a.txt").mock(return_value=httpx.Response(200, text="a.com\nb.com\n"))
    respx.get("https://lists.example/b.csv").mock(
        return_value=httpx.Response(200, text="Domain,Bids\nb.com,3\nc.com,0\n")
    )
    respx.get("https://lists.example/broken").mock(return_value=httpx.Response(500))
    config = {"sources": [
        {"name": "a", "type": "url", "url": "https://lists.example/a.txt"},
        {"name": "b", "type": "url", "url": "https://lists.example/b.csv"},
        {"name": "x", "type": "url", "url": "https://lists.example/broken"},
        {"name": "off", "type": "url", "url": "https://lists.example/off", "enabled": False},
    ]}
    cands = await fetch_all(config)
    by_domain = {c.domain: c for c in cands}
    assert set(by_domain) == {"a.com", "b.com", "c.com"}
    assert by_domain["b.com"].source == "a"  # перше джерело виграє
    assert by_domain["c.com"].extra == {"Bids": "0"}
