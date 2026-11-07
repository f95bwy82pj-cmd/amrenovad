"""Сохранение отчётов: CSV для Excel/Google Таблиц и HTML-сводка."""

from __future__ import annotations

import csv
import html
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from .client import LEVELS
from .stats import Metrics, Row, by_day, by_object, total

METRIC_HEADERS = ["Показы", "Клики", "Расход, ₽", "Конверсии", "CTR, %", "CPC, ₽", "CPM, ₽", "CPA, ₽", "CR, %"]


def _metric_values(m: Metrics) -> list:
    def r(v: Optional[float]) -> str:
        return "" if v is None else f"{v:.2f}"

    return [m.shows, m.clicks, f"{m.spent:.2f}", m.goals, r(m.ctr), r(m.cpc), r(m.cpm), r(m.cpa), r(m.cr)]


def write_csv(rows: List[Row], out_dir: Path, stem: str, delimiter: str = ";") -> List[Path]:
    """Два файла: дневная детализация и итоги по объектам. utf-8-sig — чтобы Excel понял кириллицу."""
    out_dir.mkdir(parents=True, exist_ok=True)
    daily = out_dir / f"{stem}_daily.csv"
    with daily.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=delimiter)
        w.writerow(["Дата", "ID", "Название", *METRIC_HEADERS])
        for r in rows:
            w.writerow([r.day, r.object_id, r.name, *_metric_values(r.metrics)])

    summary = out_dir / f"{stem}_summary.csv"
    with summary.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=delimiter)
        w.writerow(["ID", "Название", *METRIC_HEADERS])
        for oid, name, m in by_object(rows):
            w.writerow([oid, name, *_metric_values(m)])
        w.writerow(["", "Итого", *_metric_values(total(rows))])
    return [daily, summary]


# --- HTML ---------------------------------------------------------------------

def _fmt_int(v: int) -> str:
    return f"{v:,}".replace(",", " ")


def _fmt_money(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def _fmt_pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.2f}".replace(".", ",") + " %"


def _cells(m: Metrics) -> str:
    vals = [
        _fmt_int(m.shows), _fmt_int(m.clicks), _fmt_money(m.spent), _fmt_int(m.goals),
        _fmt_pct(m.ctr), _fmt_money(m.cpc), _fmt_money(m.cpm), _fmt_money(m.cpa), _fmt_pct(m.cr),
    ]
    return "".join(f'<td class="num">{v}</td>' for v in vals)


def _chart(days) -> str:
    if not days:
        return ""
    w, h, pad = 720, 180, 24
    peak = max(m.spent for _, m in days) or 1
    bw = (w - pad) / len(days)
    bars = []
    for i, (d, m) in enumerate(days):
        bh = (h - pad) * m.spent / peak
        x = pad + i * bw
        bars.append(
            f'<rect x="{x + bw * 0.15:.1f}" y="{h - pad - bh:.1f}" width="{bw * 0.7:.1f}" '
            f'height="{bh:.1f}" rx="2"><title>{d}: {html.escape(_fmt_money(m.spent))}</title></rect>'
        )
    first, last = days[0][0], days[-1][0]
    return (
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Расход по дням">'
        f'<line x1="{pad}" y1="{h - pad}" x2="{w}" y2="{h - pad}" class="axis"/>'
        f'{"".join(bars)}'
        f'<text x="{pad}" y="{h - 6}" class="lbl">{first}</text>'
        f'<text x="{w}" y="{h - 6}" class="lbl" text-anchor="end">{last}</text>'
        f'<text x="{pad}" y="12" class="lbl">макс. {html.escape(_fmt_money(peak))}</text>'
        "</svg>"
    )


CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--muted:#6e6e73;--line:#e5e5ea;--card:#f5f5f7;--accent:#0077ff}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#f2f2f2;--muted:#9a9a9f;--line:#2c2c2e;--card:#1e1e20;--accent:#3d8bff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 10px}
.sub{color:var(--muted)}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(115px,1fr));gap:10px;margin-top:18px}
.kpi{background:var(--card);border-radius:10px;padding:12px}.kpi b{display:block;font-size:20px;margin-top:2px}.kpi span{color:var(--muted);font-size:12px}
svg{width:100%;height:auto}svg rect{fill:var(--accent)}.axis{stroke:var(--line)}.lbl{fill:var(--muted);font-size:11px}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{color:var(--muted);font-weight:500}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}tfoot td{font-weight:600}
"""


def write_html(rows: List[Row], out_dir: Path, stem: str, level: str, date_from: date, date_to: date,
               account: Optional[str] = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    t = total(rows)
    days = by_day(rows, date_from, date_to)
    head = "".join(f'<th class="num">{h}</th>' for h in METRIC_HEADERS)

    kpis = [
        ("Расход", _fmt_money(t.spent)), ("Показы", _fmt_int(t.shows)), ("Клики", _fmt_int(t.clicks)),
        ("Конверсии", _fmt_int(t.goals)), ("CTR", _fmt_pct(t.ctr)), ("CPC", _fmt_money(t.cpc)),
        ("CPA", _fmt_money(t.cpa)),
    ]
    obj_rows = "".join(
        f"<tr><td>{oid}</td><td>{html.escape(name)}</td>{_cells(m)}</tr>" for oid, name, m in by_object(rows)
    )
    day_rows = "".join(f"<tr><td>{d}</td>{_cells(m)}</tr>" for d, m in days)
    title = f"VK Реклама: {LEVELS[level].lower()}, {date_from:%d.%m.%Y} — {date_to:%d.%m.%Y}"
    sub = f"Сформирован {datetime.now():%d.%m.%Y %H:%M}" + (f" · кабинет {html.escape(account)}" if account else "")

    doc = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Отчёт VK Рекламы</title><style>{CSS}</style></head><body><main>
<h1>{html.escape(title)}</h1><div class="sub">{sub}</div>
<div class="kpis">{"".join(f'<div class="kpi"><span>{k}</span><b>{v}</b></div>' for k, v in kpis)}</div>
<h2>Расход по дням</h2>{_chart(days)}
<h2>{LEVELS[level]}</h2>
<div class="wrap"><table><thead><tr><th>ID</th><th>Название</th>{head}</tr></thead>
<tbody>{obj_rows or '<tr><td colspan="11" class="sub">Нет данных за период</td></tr>'}</tbody>
<tfoot><tr><td></td><td>Итого</td>{_cells(t)}</tr></tfoot></table></div>
<h2>По дням</h2>
<div class="wrap"><table><thead><tr><th>Дата</th>{head}</tr></thead><tbody>{day_rows}</tbody></table></div>
</main></body></html>
"""
    path = out_dir / f"{stem}.html"
    path.write_text(doc, encoding="utf-8")
    return path
