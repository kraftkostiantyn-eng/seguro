# seguro — відбір дроп-доменів

Воронка перевірок для списків дроп-доменів. Етапи йдуть від безкоштовних і масових
до платних; домен зупиняється на першому етапі, що його відсіяв, і причина
потрапляє в CSV та базу. На платні етапи йдуть лише найкращі за попередньою оцінкою.

```
джерела → prefilter → localists → blacklist → toplists → openpagerank → safebrowsing
        → rdap → wayback → [index] → [backlinks] → scoring → results.csv + seguro.sqlite
```

| Етап | Що робить | Вартість |
|---|---|---|
| `prefilter` | зона, довжина, дефіси, цифри, стоп-слова, пороги за колонками експорту (DP, ABY, ACR...) | 0, без мережі |
| `localists` | ваші файли: реєстри блокувань регуляторів, власні чорні списки, уже куплені домени | 0, без мережі |
| `blacklist` | Spamhaus DBL, SURBL, URIBL, SEM, Nordspam через DNS | 0 |
| `toplists` | Tranco / Majestic Million / Umbrella: один файл на тиждень, локальний пошук | 0 |
| `openpagerank` | авторитет з графа Common Crawl, 100 доменів за запит | 0, безкоштовний ключ |
| `safebrowsing` | Google Safe Browsing (малвар/фішинг), 500 доменів за запит | 0, безкоштовний ключ |
| `rdap` | статус (pending delete, вже перехоплений), дата реєстрації | 0 |
| `wayback` | роки активності, унікальність контенту, паузи; класифікація знімків: мова, паркінг, pharma/adult/CJK-дорвеї, тематика | 0, ~1–7 запитів/домен |
| `index` | `site:domain` через Google Custom Search — деіндексовані домени | 100/день безкоштовно |
| `backlinks` | Majestic / Ahrefs / Moz: реф-домени, TF/CF або DA, спамні анкори, Spam Score | платно (Moz має безкоштовний тариф) |
| `scoring` | зважена оцінка 0–100, штрафи за прапорці, відсів нижче `min_score` | 0 |

## Встановлення

```bash
pip install -e ".[dev]"
cp config.example.yaml config.yaml
```

## Запуск

```bash
# .txt (домен у рядку), .csv (експорт ExpiredDomains.net / аукціону), .json, .zip
seguro run drops.csv -c config.yaml -o results.csv

# зібрати дроп-листи з джерел конфігу і одразу перевірити
seguro fetch -c config.yaml -o candidates.csv
seguro run candidates.csv -c config.yaml
seguro run --sources -c config.yaml            # те саме одним кроком

# лише безкоштовні етапи
seguro run drops.csv -c config.yaml --free-only

# домени, що зникли між двома дампами зони/списку (CZDS тощо)
seguro diff zone_yesterday.txt zone_today.txt -o dropped.txt

# робота з базою результатів
seguro list --status candidate --min-score 60
seguro mark shortlisted example.com other.org
seguro mark bought example.com --note "GoDaddy $45"
seguro report -o report.html                    # самодостатня сторінка з фільтрами/сортуванням
```

Ключі API задаються змінними оточення: `SEGURO_OPR_KEY`, `SEGURO_GSB_KEY`,
`SEGURO_GOOGLE_API_KEY` + `SEGURO_GOOGLE_CX`, `SEGURO_BACKLINKS_KEY`.
Етапи з `enabled: auto` вмикаються самі, коли ключ задано.

## Як економляться запити

- **База результатів.** Дроп-листи повторюють одні й ті самі домени день у день;
  домен, перевірений за останні `rerun_after_days`, пропускається (`--rerun` вимикає).
- **Порядок етапів.** Безкоштовні й пакетні перевірки йдуть першими, тож до Wayback
  доходить лише частина списку, а до платних API — одиниці.
- **Бюджети платних етапів.** `max_domains_per_run` і `min_prelim_score`: перед платним
  етапом домени ранжуються за попередньою оцінкою, решта отримує прапорець
  `*_skipped_budget` і лишається кандидатом.
- **Wayback.** Один запит до CDX дає всю помісячну історію з дайджестами; далі
  завантажується не більше `max_samples` знімків, по одному на рік, від найсвіжіших.
  Перший спам-знімок зупиняє перевірку.
- **HTTP-кеш** у SQLite (`cache_ttl_days`), окремі ліміти паралельності на хост,
  повтори з урахуванням `Retry-After`. Наприкінці прогону друкується кількість
  запитів, влучань у кеш і збоїв по кожному хосту.
- **Дані з експорту.** Колонки ExpiredDomains.net (DP, ABY, ACR...) можна використати
  як пороги в `prefilter.min_extra`/`max_extra` ще до першого запиту.

## Прапорці та оцінка

Прапорці не відсіюють, але множать оцінку: `had_gambling_content` ×0.9,
`possibly_deindexed` ×0.7, `recently_registered` ×0.5 (домен уже перехопили),
`wb_revived` ×0.85 (багаторічна пауза в історії), `wb_static` ×0.9 (роками одна
сторінка). Компоненти без даних (наприклад, беклінки без API) не штрафують: їхня
вага перерозподіляється. Якщо мережеві етапи не дали даних, домен отримує
статус `no_data`, а не проходить.

## Нотатки

- **DNSBL.** Spamhaus, SURBL і URIBL не відповідають публічним резолверам. Потрібен
  власний резолвер (`blacklist.nameservers`) або ключ Spamhaus DQS; інакше домен
  отримує прапорець `dnsbl_unverified`.
- **Джерела.** URL-и дампів GoDaddy/NameJet у `seguro/sources/remote.py` задано за
  публічними адресами і можуть змінитися; будь-яке джерело можна перевизначити через
  `type: url`. Експорти ExpiredDomains.net (потрібен акаунт) завантажуються як CSV.
- **Інтеграції** Majestic, Ahrefs, Moz, OpenPageRank, Safe Browsing і Google CSE
  написані за документацією API і покриті тестами на підставних відповідях, але не
  перевірялися на реальних ключах.
- **Юридично.** Використовуйте домени лише під офери, ліцензовані в цільовій країні,
  і додайте реєстри блокувань регуляторів у `localists.reject`.

## Розширення

Новий етап — клас-нащадок `BaseCheck` (`seguro/checks/base.py`) з `name` і `run`
(або `run_batch` + `batch_size` для пакетних API), доданий у
`seguro/checks/__init__.py::default_checks`. `costly = True` вмикає бюджети.

## Тести

```bash
pytest
```
