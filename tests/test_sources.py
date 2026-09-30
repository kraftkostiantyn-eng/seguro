from seguro.sources import load_candidates, normalize_domain


def test_normalize():
    assert normalize_domain("https://www.Example.COM/path") == "example.com"
    assert normalize_domain("# comment") is None
    assert normalize_domain("localhost") is None
    assert normalize_domain("футбол.укр") == "футбол.укр".encode("idna").decode()


def test_txt_dedup(tmp_path):
    p = tmp_path / "list.txt"
    p.write_text("a.com\nA.com\n\nb.net\n")
    assert [c.domain for c in load_candidates(p)] == ["a.com", "b.net"]


def test_csv_expireddomains_export(tmp_path):
    p = tmp_path / "export.csv"
    p.write_text("Domain;BL;DP;ABY\nsport-news.com;120;30;2009\nbad;1;1;2020\n", encoding="utf-8")
    cands = list(load_candidates(p))
    assert [c.domain for c in cands] == ["sport-news.com"]
    assert cands[0].extra["ABY"] == "2009"
