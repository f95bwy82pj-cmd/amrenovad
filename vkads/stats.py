"""Выгрузка дневной статистики и расчёт показателей."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from .client import VKAdsClient

ID_CHUNK = 200
DAYS_CHUNK = 90


@dataclass
class Metrics:
    shows: int = 0
    clicks: int = 0
    goals: int = 0
    spent: float = 0.0

    def add(self, other: "Metrics") -> None:
        self.shows += other.shows
        self.clicks += other.clicks
        self.goals += other.goals
        self.spent += other.spent

    # Производные показатели считаем сами из сумм — так итоги корректны
    # при любой агрегации (по дням, объектам, периоду).
    @property
    def ctr(self) -> Optional[float]:
        return self.clicks / self.shows * 100 if self.shows else None

    @property
    def cpc(self) -> Optional[float]:
        return self.spent / self.clicks if self.clicks else None

    @property
    def cpm(self) -> Optional[float]:
        return self.spent / self.shows * 1000 if self.shows else None

    @property
    def cpa(self) -> Optional[float]:
        return self.spent / self.goals if self.goals else None

    @property
    def cr(self) -> Optional[float]:
        return self.goals / self.clicks * 100 if self.clicks else None

    def is_empty(self) -> bool:
        return not (self.shows or self.clicks or self.goals or self.spent)

    @classmethod
    def from_base(cls, base: Optional[dict]) -> "Metrics":
        base = base or {}
        return cls(
            shows=int(_num(base.get("shows"))),
            clicks=int(_num(base.get("clicks"))),
            goals=int(_num(base.get("goals"))),
            spent=_num(base.get("spent")),
        )


@dataclass
class Row:
    day: str
    object_id: int
    name: str
    metrics: Metrics = field(default_factory=Metrics)


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _chunks(seq: List[int], size: int) -> Iterator[List[int]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def date_ranges(start: date, end: date, days: int = DAYS_CHUNK) -> Iterator[Tuple[date, date]]:
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=days - 1), end)
        yield cur, stop
        cur = stop + timedelta(days=1)


def fetch_rows(
    client: VKAdsClient,
    level: str,
    date_from: date,
    date_to: date,
    objects: Optional[List[dict]] = None,
    include_deleted: bool = False,
) -> List[Row]:
    """Дневные строки статистики по всем объектам уровня. Пустые дни отбрасываются."""
    if date_from > date_to:
        raise ValueError("Дата начала позже даты окончания")
    if objects is None:
        objects = client.list_objects(level, include_deleted=include_deleted)
    names: Dict[int, str] = {int(o["id"]): o.get("name") or f"#{o['id']}" for o in objects}
    ids = sorted(names)

    rows: List[Row] = []
    for d1, d2 in date_ranges(date_from, date_to):
        for chunk in _chunks(ids, ID_CHUNK):
            for item in client.day_stats(level, chunk, d1.isoformat(), d2.isoformat()):
                oid = int(item["id"])
                for r in item.get("rows", []):
                    m = Metrics.from_base(r.get("base"))
                    if m.is_empty():
                        continue
                    rows.append(Row(r["date"], oid, names.get(oid, f"#{oid}"), m))
    rows.sort(key=lambda r: (r.day, r.object_id))
    return rows


def total(rows: Iterable[Row]) -> Metrics:
    t = Metrics()
    for r in rows:
        t.add(r.metrics)
    return t


def by_object(rows: Iterable[Row]) -> List[Tuple[int, str, Metrics]]:
    acc: Dict[int, Tuple[str, Metrics]] = {}
    for r in rows:
        name, m = acc.setdefault(r.object_id, (r.name, Metrics()))
        m.add(r.metrics)
    result = [(oid, name, m) for oid, (name, m) in acc.items()]
    result.sort(key=lambda x: x[2].spent, reverse=True)
    return result


def by_day(rows: Iterable[Row], date_from: date, date_to: date) -> List[Tuple[str, Metrics]]:
    """Итоги по дням, включая дни без показов (чтобы в графике не было дыр)."""
    acc: Dict[str, Metrics] = {}
    d = date_from
    while d <= date_to:
        acc[d.isoformat()] = Metrics()
        d += timedelta(days=1)
    for r in rows:
        acc.setdefault(r.day, Metrics()).add(r.metrics)
    return sorted(acc.items())
