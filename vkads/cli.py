"""Командная строка: vkads check | list | report | tokens-reset."""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

from .auth import AuthError
from .client import LEVELS, APIError, VKAdsClient
from .config import Config
from .report import write_csv, write_html
from .stats import fetch_rows


def _date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Дата должна быть в формате ГГГГ-ММ-ДД: {s!r}")


def _period(args) -> tuple:
    date_to = args.date_to or (date.today() - timedelta(days=1))
    date_from = args.date_from or (date_to - timedelta(days=args.days - 1))
    return date_from, date_to


def cmd_check(client: VKAdsClient, args) -> int:
    user = client.user()
    print("Доступ к API есть.")
    for key in ("id", "username", "account"):
        if key in user:
            print(f"  {key}: {user[key]}")
    return 0


def cmd_list(client: VKAdsClient, args) -> int:
    objects = client.list_objects(args.level, include_deleted=args.include_deleted)
    print(f"{LEVELS[args.level]}: {len(objects)}")
    for o in objects:
        print(f"  {o['id']:>10}  [{o.get('status', '')}]  {o.get('name', '')}")
    return 0


def cmd_report(client: VKAdsClient, args) -> int:
    date_from, date_to = _period(args)
    rows = fetch_rows(client, args.level, date_from, date_to, include_deleted=args.include_deleted)
    stem = f"vkads_{args.level}_{date_from:%Y%m%d}_{date_to:%Y%m%d}"
    out = Path(args.out)
    formats = {f.strip() for f in args.format.split(",") if f.strip()}
    written = []
    if "csv" in formats:
        written += write_csv(rows, out, stem, delimiter=args.delimiter)
    if "html" in formats:
        account = None
        try:
            account = str(client.user().get("username") or "") or None
        except APIError:
            pass
        written.append(write_html(rows, out, stem, args.level, date_from, date_to, account))
    print(f"Период {date_from} — {date_to}, строк статистики: {len(rows)}")
    for p in written:
        print(f"  {p}")
    return 0


def cmd_tokens_reset(client: VKAdsClient, args) -> int:
    client.tokens.delete_all_tokens()
    print("Все токены приложения отозваны. Новый будет получен при следующем запуске.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vkads", description="Статистика и отчёты по кабинету VK Рекламы")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="проверить доступ к API").set_defaults(func=cmd_check)

    def level_opts(sp):
        sp.add_argument("--level", choices=list(LEVELS), default="ad_plans",
                        help="ad_plans — кампании, ad_groups — группы, banners — объявления")
        sp.add_argument("--include-deleted", action="store_true", help="включить удалённые объекты")

    sp = sub.add_parser("list", help="список кампаний / групп / объявлений")
    level_opts(sp)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("report", help="выгрузить статистику и собрать отчёт")
    level_opts(sp)
    sp.add_argument("--from", dest="date_from", type=_date, help="начало периода, ГГГГ-ММ-ДД")
    sp.add_argument("--to", dest="date_to", type=_date, help="конец периода (по умолчанию вчера)")
    sp.add_argument("--days", type=int, default=7, help="длина периода, если --from не задан (7)")
    sp.add_argument("--format", default="csv,html", help="csv, html или csv,html")
    sp.add_argument("--out", default="reports", help="папка для отчётов (reports)")
    sp.add_argument("--delimiter", default=";", help="разделитель CSV (; — для русского Excel)")
    sp.set_defaults(func=cmd_report)

    sub.add_parser("tokens-reset", help="отозвать все токены (при ошибке лимита токенов)").set_defaults(
        func=cmd_tokens_reset
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    client = VKAdsClient(Config.from_env())
    try:
        return args.func(client, args)
    except (AuthError, APIError, ValueError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
