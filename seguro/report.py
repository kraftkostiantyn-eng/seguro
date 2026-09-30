"""Самодостатній HTML-звіт по базі результатів: зведення, таблиця з сортуванням і фільтром."""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

COLUMNS = [
    ("domain", "Домен"),
    ("score", "Оцінка"),
    ("status", "Статус"),
    ("manual_status", "Рішення"),
    ("wb_years_active", "Років в архіві"),
    ("history_age_years", "Вік"),
    ("wb_topics", "Теми"),
    ("wb_languages", "Мови"),
    ("opr_score", "OPR"),
    ("top_tranco_rank", "Tranco"),
    ("bl_ref_domains", "Реф-домени"),
    ("indexed_pages", "В індексі"),
    ("flags", "Прапорці"),
    ("rejected_by", "Етап відсіву"),
    ("reject_reason", "Причина"),
    ("note", "Нотатка"),
]

STYLE = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#e3e3e3;--ok:#1b7f3b;--bad:#b3261e;--accent:#2457c5}
@media(prefers-color-scheme:dark){:root{--bg:#141414;--fg:#eaeaea;--muted:#9a9a9a;--line:#333;--ok:#4cc26b;--bad:#f28b82;--accent:#8ab4f8}}
body{margin:0;padding:16px;font:14px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
h1{font-size:20px;margin:0 0 4px}.muted{color:var(--muted)}
.tiles{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}
.tile{border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:120px}
.tile b{display:block;font-size:22px}
.tools{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
input,select{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap;vertical-align:top}
th{cursor:pointer;position:sticky;top:0;background:var(--bg)}td.wrapc{white-space:normal;max-width:360px}
.candidate{color:var(--ok);font-weight:600}.rejected{color:var(--bad)}
.bought{color:var(--accent);font-weight:600}
"""

SCRIPT = """
const rows=[...document.querySelectorAll('tbody tr')];
const q=document.getElementById('q'),st=document.getElementById('st'),ms=document.getElementById('ms');
function apply(){const t=q.value.toLowerCase(),s=st.value,m=parseFloat(ms.value)||0;
rows.forEach(r=>{const ok=(!t||r.textContent.toLowerCase().includes(t))&&(!s||r.dataset.status===s||r.dataset.manual===s)&&((parseFloat(r.dataset.score)||0)>=m);r.style.display=ok?'':'none'})}
[q,st,ms].forEach(e=>e.addEventListener('input',apply));
document.querySelectorAll('th').forEach((th,i)=>{let asc=false;th.addEventListener('click',()=>{asc=!asc;
const body=th.closest('table').tBodies[0];const sorted=[...body.rows].sort((a,b)=>{const x=a.cells[i].dataset.v??a.cells[i].textContent,y=b.cells[i].dataset.v??b.cells[i].textContent;
const nx=parseFloat(x),ny=parseFloat(y);const c=(!isNaN(nx)&&!isNaN(ny))?nx-ny:String(x).localeCompare(String(y));return asc?c:-c});sorted.forEach(r=>body.appendChild(r))})});
"""


def _cell(key: str, row: dict[str, Any]) -> str:
    if key in row:
        value = row[key]
    else:
        value = row.get("metrics", {}).get(key)
    if key == "flags":
        value = ", ".join(row.get("flags") or [])
    if value is None or value == "":
        return '<td data-v=""></td>'
    css = ""
    if key in ("status", "manual_status"):
        css = f' class="{html.escape(str(value))}"'
    elif key in ("reject_reason", "flags", "note", "wb_topics"):
        css = ' class="wrapc"'
    return f"<td{css} data-v=\"{html.escape(str(value))}\">{html.escape(str(value))}</td>"


def render_report(rows: list[dict[str, Any]], summary: dict[str, Any],
                  generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now()
    by_status = summary.get("by_status", {})
    by_manual = summary.get("by_manual", {})
    tiles = [
        ("Всього", summary.get("total", 0)),
        ("Кандидати", by_status.get("candidate", 0)),
        ("Відсіяно", by_status.get("rejected", 0)),
        ("Шорт-лист", by_manual.get("shortlisted", 0)),
        ("Куплено", by_manual.get("bought", 0)),
    ]
    stage_lines = ", ".join(f"{k}: {v}" for k, v in summary.get("by_stage", {}).items()) or "—"

    head = "".join(f"<th>{html.escape(title)}</th>" for _, title in COLUMNS)
    body = []
    for row in rows:
        cells = "".join(_cell(key, row) for key, _ in COLUMNS)
        body.append(
            f'<tr data-status="{html.escape(str(row.get("status") or ""))}" '
            f'data-manual="{html.escape(str(row.get("manual_status") or ""))}" '
            f'data-score="{row.get("score") or 0}">{cells}</tr>'
        )

    return f"""<!doctype html>
<html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Seguro — дроп-домени</title><style>{STYLE}</style></head>
<body>
<h1>Відбір дроп-доменів</h1>
<div class="muted">Згенеровано {generated_at:%Y-%m-%d %H:%M}. Відсів за етапами: {html.escape(stage_lines)}</div>
<div class="tiles">{"".join(f'<div class="tile"><span class="muted">{t}</span><b>{v}</b></div>' for t, v in tiles)}</div>
<div class="tools">
  <input id="q" placeholder="пошук по таблиці" size="28">
  <select id="st"><option value="">усі статуси</option><option value="candidate">кандидати</option>
    <option value="rejected">відсіяні</option><option value="shortlisted">шорт-лист</option>
    <option value="bought">куплені</option><option value="skipped">пропущені</option></select>
  <input id="ms" type="number" placeholder="мін. оцінка" size="10">
</div>
<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>
<script>{SCRIPT}</script>
</body></html>"""


def dump_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=1, default=str)
