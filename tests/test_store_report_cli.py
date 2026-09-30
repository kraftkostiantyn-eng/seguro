import yaml

from seguro import cli
from seguro.models import Result
from seguro.pipeline import RunReport
from seguro.report import render_report
from seguro.store import Store


def test_store_roundtrip(tmp_path):
    store = Store(tmp_path / "s.sqlite")
    r1 = Result("a.com", source="x", score=70.0, metrics={"k": 1})
    r1.flag("f")
    r2 = Result("b.com")
    r2.reject("wayback", "спам")
    store.save([r1, r2])

    assert store.recently_evaluated(["a.com", "b.com", "c.com"], days=1) == {"a.com", "b.com"}
    assert store.recently_evaluated(["a.com"], days=-1) == set()

    store.mark("a.com", "bought", "куплено за $50")
    store.save([r1])  # повторне збереження не стирає ручний статус і нотатку
    [row] = store.rows(manual_status="bought")
    assert row["domain"] == "a.com" and row["note"] == "куплено за $50"
    assert row["metrics"] == {"k": 1} and row["flags"] == ["f"]

    store.mark("new.com", "shortlisted")
    summary = store.summary()
    assert summary["total"] == 3
    assert summary["by_status"] == {"candidate": 1, "rejected": 1, "": 1}
    assert summary["by_manual"] == {"bought": 1, "shortlisted": 1}
    assert summary["by_stage"] == {"wayback": 1}
    assert [r["domain"] for r in store.rows(status="candidate")] == ["a.com"]
    store.close()


def test_render_report_escapes():
    rows = [{"domain": "a.com", "status": "candidate", "score": 55.5, "flags": ["x"],
             "metrics": {"wb_topics": "sport:3"}, "reject_reason": "<b>", "manual_status": None}]
    html = render_report(rows, {"total": 1, "by_status": {"candidate": 1}, "by_manual": {}, "by_stage": {}})
    assert "a.com" in html and "sport:3" in html
    table = html.split("<tbody>")[1].split("</tbody>")[0]
    assert "&lt;b&gt;" in table and "<b>" not in table


def test_cli_diff(tmp_path, capsys):
    old, new = tmp_path / "old.txt", tmp_path / "new.txt"
    old.write_text("a.com\nb.com\nc.com\n")
    new.write_text("a.com\nc.com\nd.com\n")
    out = tmp_path / "dropped.txt"
    assert cli.main(["diff", str(old), str(new), "-o", str(out)]) == 0
    assert out.read_text() == "b.com\n"


def test_cli_run_mark_list_report(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"store": {"path": str(tmp_path / "db.sqlite")}, "cache_path": None}))
    domains = tmp_path / "drops.txt"
    domains.write_text("good.com\nbad.com\n")

    async def fake_pipeline(candidates, config, checks=None, transport=None):
        results = []
        for cand in candidates:
            r = Result(cand.domain, source=cand.source)
            if cand.domain == "bad.com":
                r.reject("prefilter", "тест")
            else:
                r.score = 66.0
            results.append(r)
        return RunReport(results=results)

    monkeypatch.setattr(cli, "run_pipeline", fake_pipeline)
    out = tmp_path / "results.csv"

    # без підкоманди — те саме, що `run`
    assert cli.main([str(domains), "-c", str(cfg), "-o", str(out)]) == 0
    assert "good.com" in out.read_text() and "bad.com" in out.read_text()

    # повторний запуск пропускає вже перевірені домени
    assert cli.main(["run", str(domains), "-c", str(cfg), "-o", str(out)]) == 0
    assert "Немає нових доменів" in capsys.readouterr().err

    assert cli.main(["mark", "bought", "good.com", "--note", "ok", "-c", str(cfg)]) == 0
    assert cli.main(["list", "--manual", "bought", "-c", str(cfg)]) == 0
    assert "good.com" in capsys.readouterr().out

    report = tmp_path / "report.html"
    assert cli.main(["report", "-c", str(cfg), "-o", str(report)]) == 0
    text = report.read_text()
    assert "good.com" in text and "bad.com" not in text
    assert cli.main(["report", "--all", "-c", str(cfg), "-o", str(report)]) == 0
    assert "bad.com" in report.read_text()
