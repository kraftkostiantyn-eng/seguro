# seguro — відбір дроп-доменів

Воронка перевірок для списку дроп-доменів: від дешевих фільтрів до платних API.
Кожен домен зупиняється на першому етапі, що його відсіяв, і причина потрапляє в CSV.

```
вхідний список → prefilter → blacklist (DNSBL) → rdap → wayback → backlinks → scoring → results.csv
```

| Етап | Що робить | Мережа |
|---|---|---|
| `prefilter` | TLD, довжина, дефіси, цифри, IDN, стоп-слова | ні |
| `blacklist` | Spamhaus DBL, SURBL, URIBL через DNS | DNS |
| `rdap` | статус (pending delete тощо), дата реєстрації — лише інформація | rdap.org |
| `wayback` | к-сть знімків, роки активності, класифікація контенту: мова, паркінг, pharma/adult/CJK-дорвеї, тематика (спорт, ігри, фінанси…) | web.archive.org |
| `backlinks` | реф-домени, TF/CF або DR, частка спамних анкорів | Majestic / Ahrefs (опційно) |
| `scoring` | зважена оцінка 0–100, відсів нижче `min_score` | ні |

Якщо мережеві етапи не дали даних (помилки API), домен отримує статус `no_data`, а не проходить.

## Встановлення

```bash
pip install -e ".[dev]"
cp config.example.yaml config.yaml
```

## Запуск

```bash
# .txt (домен у рядку) або .csv з колонкою Domain (напр. експорт ExpiredDomains.net)
seguro drops.csv -c config.yaml -o results.csv

# з беклінками
export SEGURO_BACKLINKS_KEY=...   # і backlinks.provider: majestic|ahrefs у config.yaml
seguro drops.csv -c config.yaml --only-candidates -o top.csv
```

Відповіді HTTP кешуються в `seguro_cache.sqlite` (14 днів), тож повторний прогін
не витрачає ліміти. `--no-cache` вимикає кеш.

## Нотатки

- **DNSBL:** Spamhaus і URIBL не відповідають на запити через публічні резолвери.
  Потрібен власний резолвер (`blacklist.nameservers`) або ключ Spamhaus DQS. Інакше
  домен отримає прапорець `dnsbl_unverified`.
- **Wayback** банить за частоту: паралельність до `web.archive.org` обмежена `host_limits`.
- **Колишній гемблінг-контент** не відсіюється, але позначається прапорцем
  `had_gambling_content` і отримує невеликий штраф: такі домени треба окремо
  перевіряти на санкції та блокування.
- Інтеграції Majestic та Ahrefs написані за документацією API, але ще не перевірялися на реальному ключі.

## Розширення

Новий етап — клас з `name`, `enabled(ctx)` та `async run(cand, result, ctx)`,
доданий у `seguro/checks/__init__.py::default_checks`.

## Тести

```bash
pytest
```
