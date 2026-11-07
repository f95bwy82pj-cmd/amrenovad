import json
from datetime import date

import pytest

from vkads.auth import AuthError, TokenManager
from vkads.client import VKAdsClient
from vkads.config import Config
from vkads.report import write_csv, write_html
from vkads.stats import Metrics, by_day, by_object, date_ranges, fetch_rows, total


class Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeSession:
    """Отвечает заранее заданными ответами и запоминает запросы."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def post(self, url, data=None, **kw):
        self.calls.append(("POST", url, data))
        return self.handler("POST", url, data)

    def get(self, url, params=None, headers=None, **kw):
        self.calls.append(("GET", url, params))
        return self.handler("GET", url, params)


@pytest.fixture
def cfg(tmp_path):
    return Config(client_id="cid", client_secret="sec", token_cache=tmp_path / "tok.json")


def token_resp(n=1):
    return Resp(200, {"access_token": f"t{n}", "refresh_token": f"r{n}", "expires_in": 86400})


def test_token_cached_between_runs(cfg):
    s = FakeSession(lambda m, u, d: token_resp())
    assert TokenManager(cfg, s).get_token() == "t1"
    # Новый процесс берёт токен из файла и не тратит лимит токенов
    s2 = FakeSession(lambda m, u, d: pytest.fail("лишний запрос токена"))
    assert TokenManager(cfg, s2).get_token() == "t1"


def test_expired_token_is_refreshed(cfg):
    cfg.token_cache.write_text(json.dumps({"access_token": "old", "refresh_token": "r0", "expires_at": 0}))
    s = FakeSession(lambda m, u, d: token_resp(2))
    assert TokenManager(cfg, s).get_token() == "t2"
    assert s.calls[0][2]["grant_type"] == "refresh_token"


def test_agency_grant(cfg):
    cfg.agency_client_name = "client@agency"
    s = FakeSession(lambda m, u, d: token_resp())
    TokenManager(cfg, s).get_token()
    assert s.calls[0][2]["grant_type"] == "agency_client_credentials"
    assert s.calls[0][2]["agency_client_name"] == "client@agency"


def test_token_limit_message(cfg):
    s = FakeSession(lambda m, u, d: Resp(403, {"error": "token_limit_exceeded"}))
    with pytest.raises(AuthError, match="tokens-reset"):
        TokenManager(cfg, s).get_token()


def test_missing_credentials(tmp_path):
    with pytest.raises(AuthError, match="VK_ADS_CLIENT_ID"):
        TokenManager(Config(token_cache=tmp_path / "t.json"), FakeSession(None)).get_token()


def test_retry_on_429_and_reauth_on_401(cfg):
    state = {"get": 0, "token": 0}

    def handler(m, u, d):
        if m == "POST":
            state["token"] += 1
            return token_resp(state["token"])
        state["get"] += 1
        return [Resp(429, {}), Resp(401, {}), Resp(200, {"ok": True})][state["get"] - 1]

    client = VKAdsClient(cfg, FakeSession(handler), sleep=lambda s: None)
    assert client.get("/api/v2/user.json") == {"ok": True}
    assert state["token"] == 2  # после 401 токен получен заново


def test_paginate(cfg):
    def handler(m, u, d):
        if m == "POST":
            return token_resp()
        items = [{"id": i} for i in range(d["offset"], min(d["offset"] + d["limit"], 5))]
        return Resp(200, {"count": 5, "items": items})

    client = VKAdsClient(cfg, FakeSession(handler))
    assert [o["id"] for o in client.paginate("/api/v2/ad_plans.json", limit=2)] == [0, 1, 2, 3, 4]


def test_date_ranges():
    r = list(date_ranges(date(2026, 1, 1), date(2026, 1, 10), days=4))
    assert r == [
        (date(2026, 1, 1), date(2026, 1, 4)),
        (date(2026, 1, 5), date(2026, 1, 8)),
        (date(2026, 1, 9), date(2026, 1, 10)),
    ]


def stats_handler(m, u, d):
    if m == "POST":
        return token_resp()
    if u.endswith("/api/v2/ad_plans.json"):
        return Resp(200, {"count": 2, "items": [{"id": 1, "name": "Кухни"}, {"id": 2, "name": "Ванные"}]})
    assert u.endswith("/api/v2/statistics/ad_plans/day.json")
    assert d["id"] == "1,2" and d["metrics"] == "base"
    return Resp(200, {"items": [
        {"id": 1, "rows": [
            {"date": "2026-11-01", "base": {"shows": 1000, "clicks": 20, "goals": 2, "spent": "500.50"}},
            {"date": "2026-11-02", "base": {"shows": 0, "clicks": 0, "goals": 0, "spent": "0"}},
        ]},
        {"id": 2, "rows": [
            {"date": "2026-11-02", "base": {"shows": 3000, "clicks": 30, "goals": 3, "spent": "1500"}},
        ]},
    ]})


def test_fetch_and_aggregate(cfg):
    client = VKAdsClient(cfg, FakeSession(stats_handler))
    rows = fetch_rows(client, "ad_plans", date(2026, 11, 1), date(2026, 11, 3))
    assert len(rows) == 2  # пустой день отброшен
    t = total(rows)
    assert (t.shows, t.clicks, t.goals) == (4000, 50, 5)
    assert t.spent == pytest.approx(2000.5)
    assert t.ctr == pytest.approx(1.25)
    assert t.cpa == pytest.approx(400.1)
    assert [name for _, name, _ in by_object(rows)] == ["Ванные", "Кухни"]
    assert [d for d, _ in by_day(rows, date(2026, 11, 1), date(2026, 11, 3))] == [
        "2026-11-01", "2026-11-02", "2026-11-03"
    ]


def test_metrics_zero_division():
    m = Metrics()
    assert m.ctr is None and m.cpc is None and m.cpa is None and m.cr is None


def test_reports_written(cfg, tmp_path):
    client = VKAdsClient(cfg, FakeSession(stats_handler))
    rows = fetch_rows(client, "ad_plans", date(2026, 11, 1), date(2026, 11, 3))
    daily, summary = write_csv(rows, tmp_path, "r")
    text = summary.read_text(encoding="utf-8-sig")
    assert "Ванные" in text and "Итого" in text and "2000.50" in text
    assert daily.read_text(encoding="utf-8-sig").count("\n") == 3
    page = write_html(rows, tmp_path, "r", "ad_plans", date(2026, 11, 1), date(2026, 11, 3), "acc")
    content = page.read_text(encoding="utf-8")
    assert "Кухни" in content and "<svg" in content
