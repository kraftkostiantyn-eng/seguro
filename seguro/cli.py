from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter

from .config import load_config
from .pipeline import run_pipeline, write_csv
from .sources import load_candidates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="seguro", description="Відбір дроп-доменів")
    parser.add_argument("input", nargs="+", help=".txt (домен у рядку) або .csv з колонкою domain")
    parser.add_argument("-c", "--config", help="YAML-конфіг (див. config.example.yaml)")
    parser.add_argument("-o", "--output", default="results.csv", help="вихідний CSV")
    parser.add_argument("--only-candidates", action="store_true", help="не писати відсіяні домени")
    parser.add_argument("--no-cache", action="store_true", help="не використовувати SQLite-кеш")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = load_config(args.config)
    if args.no_cache:
        config["cache_path"] = None

    candidates = []
    seen: set[str] = set()
    for path in args.input:
        for cand in load_candidates(path):
            if cand.domain not in seen:
                seen.add(cand.domain)
                candidates.append(cand)
    if not candidates:
        print("Не знайдено жодного домену у вхідних файлах", file=sys.stderr)
        return 1

    results = asyncio.run(run_pipeline(candidates, config))
    written = write_csv(results, args.output, include_rejected=not args.only_candidates)

    passed = [r for r in results if not r.rejected]
    by_stage = Counter(r.rejected_by for r in results if r.rejected)
    print(f"\nВсього: {len(results)}, пройшли: {len(passed)}", file=sys.stderr)
    for stage, n in by_stage.most_common():
        print(f"  відсіяно на етапі {stage}: {n}", file=sys.stderr)
    for r in passed[:10]:
        print(f"  {r.score:>5}  {r.domain}  {','.join(r.flags)}", file=sys.stderr)
    print(f"Записано {written} рядків у {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
