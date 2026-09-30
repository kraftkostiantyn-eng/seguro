from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any

from .config import load_config
from .models import Candidate
from .pipeline import RunReport, run_pipeline, write_csv
from .report import render_report
from .sources import fetch_all, load_candidates, load_domain_set
from .store import MANUAL_STATUSES, Store

log = logging.getLogger("seguro")
SUBCOMMANDS = ("run", "fetch", "mark", "list", "report", "diff")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _collect(paths: list[str], config: dict[str, Any], with_sources: bool) -> list[Candidate]:
    merged: dict[str, Candidate] = {}
    for path in paths:
        for cand in load_candidates(path):
            merged.setdefault(cand.domain, cand)
    if with_sources:
        for cand in asyncio.run(fetch_all(config)):
            merged.setdefault(cand.domain, cand)
    return list(merged.values())


def _print_summary(report: RunReport, output: str, written: int) -> None:
    err = sys.stderr
    passed = report.candidates
    print(f"\nВсього: {len(report.results)}, кандидатів: {len(passed)}", file=err)
    print("Воронка:", file=err)
    for st in report.stages:
        extra = f"  поза бюджетом {st.skipped}" if st.skipped else ""
        errs = f"  збоїв {st.errors}" if st.errors else ""
        print(f"  {st.name:<13} вхід {st.entered:>5}  відсів {st.rejected:>5}{extra}{errs}", file=err)
    final = [r for r in report.results if r.rejected_by in ("scoring", "no_data")]
    if final:
        print(f"  {'scoring':<13} відсів {len(final):>5} (низька оцінка або нема даних)", file=err)
    if report.http_stats:
        parts = [f"{host} {s['requests']} (кеш {s['cache_hits']}, збоїв {s['errors']})"
                 for host, s in sorted(report.http_stats.items())]
        print("Запити: " + "; ".join(parts), file=err)
    for r in passed[:15]:
        print(f"  {r.score:>5}  {r.domain:<30} {','.join(r.flags)}", file=err)
    print(f"Записано {written} рядків у {output}", file=err)


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.no_cache:
        config["cache_path"] = None
    if args.free_only:
        config["free_only"] = True

    candidates = _collect(args.input, config, args.sources)
    store = None if args.no_db else Store(config["store"]["path"])
    if store is not None and not args.rerun:
        days = config["store"]["rerun_after_days"]
        seen = store.recently_evaluated([c.domain for c in candidates], days)
        if seen:
            log.info("пропущено %d доменів, перевірених за останні %s дн. (--rerun, щоб перевірити знову)",
                     len(seen), days)
        candidates = [c for c in candidates if c.domain not in seen]
    if not candidates:
        print("Немає нових доменів для перевірки", file=sys.stderr)
        return 0
    log.info("до перевірки: %d доменів", len(candidates))

    report = asyncio.run(run_pipeline(candidates, config))
    written = write_csv(report.results, args.output, include_rejected=not args.only_candidates)
    if store is not None:
        store.save(report.results)
        store.close()
    _print_summary(report, args.output, written)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if not config.get("sources"):
        print("У конфігу нема секції sources (див. config.example.yaml)", file=sys.stderr)
        return 1
    candidates = asyncio.run(fetch_all(config))
    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["domain", "source", "extra"])
        for cand in candidates:
            writer.writerow([cand.domain, cand.source, json.dumps(cand.extra, ensure_ascii=False)])
    print(f"Зібрано {len(candidates)} доменів у {args.output}", file=sys.stderr)
    return 0 if candidates else 1


def cmd_mark(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = Store(config["store"]["path"])
    status = None if args.status == "none" else args.status
    for domain in args.domain:
        store.mark(domain.lower(), status, args.note)
    store.close()
    print(f"{len(args.domain)} домен(ів): {args.status}", file=sys.stderr)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = Store(config["store"]["path"])
    rows = store.rows(status=args.status, manual_status=args.manual,
                      min_score=args.min_score, limit=args.limit)
    store.close()
    for row in rows:
        score = f"{row['score']:.1f}" if row.get("score") is not None else "-"
        tail = row.get("manual_status") or row.get("reject_reason") or ""
        print(f"{score:>6}  {row['status'] or '':<9} {row['domain']:<32} {tail}")
    print(f"({len(rows)} рядків)", file=sys.stderr)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = Store(config["store"]["path"])
    rows = store.rows(status=None if args.all else "candidate")
    summary = store.summary()
    store.close()
    Path(args.output).write_text(render_report(rows, summary), encoding="utf-8")
    print(f"Звіт: {args.output} ({len(rows)} рядків)", file=sys.stderr)
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Домени, що зникли зі списку/зони між двома дампами — кандидати на дроп."""
    old, new = load_domain_set(args.old), load_domain_set(args.new)
    dropped = sorted(old - new)
    out = open(args.output, "w", encoding="utf-8") if args.output else sys.stdout
    try:
        out.write("\n".join(dropped) + ("\n" if dropped else ""))
    finally:
        if out is not sys.stdout:
            out.close()
    print(f"Зникло {len(dropped)} з {len(old)} доменів", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seguro", description="Відбір дроп-доменів")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", help="YAML-конфіг (див. config.example.yaml)")
    common.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="прогнати домени через воронку", parents=[common])
    p.add_argument("input", nargs="*", help=".txt/.csv/.json/.zip зі списком доменів")
    p.add_argument("-o", "--output", default="results.csv")
    p.add_argument("--sources", action="store_true", help="додати домени з віддалених джерел конфігу")
    p.add_argument("--only-candidates", action="store_true", help="не писати відсіяні домени у CSV")
    p.add_argument("--free-only", action="store_true", help="пропустити платні/квотовані етапи")
    p.add_argument("--rerun", action="store_true", help="перевіряти й уже перевірені домени")
    p.add_argument("--no-cache", action="store_true", help="не використовувати HTTP-кеш")
    p.add_argument("--no-db", action="store_true", help="не писати результати в базу")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("fetch", help="зібрати домени з джерел у CSV", parents=[common])
    p.add_argument("-o", "--output", default="candidates.csv")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("mark", help="поставити ручний статус", parents=[common])
    p.add_argument("status", choices=(*MANUAL_STATUSES, "none"))
    p.add_argument("domain", nargs="+")
    p.add_argument("--note")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("list", help="показати домени з бази", parents=[common])
    p.add_argument("--status", choices=("candidate", "rejected"))
    p.add_argument("--manual", choices=MANUAL_STATUSES)
    p.add_argument("--min-score", type=float)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("report", help="HTML-звіт по базі", parents=[common])
    p.add_argument("-o", "--output", default="report.html")
    p.add_argument("--all", action="store_true", help="включити відсіяні домени")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("diff", help="домени, що зникли між двома списками (зони, дампи)", parents=[common])
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_diff)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `seguro drops.csv` без підкоманди — те саме, що `seguro run drops.csv`.
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "run")
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    if args.command == "run" and not args.input and not args.sources:
        print("Вкажіть файли зі списком доменів або --sources", file=sys.stderr)
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
