"""HTTP-клиент API VK Рекламы: авторизация, повторы, постраничная выгрузка."""

from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List, Optional

import requests

from .auth import TokenManager
from .config import Config

# Уровни кабинета: кампании → группы объявлений → объявления
LEVELS = {
    "ad_plans": "Кампании",
    "ad_groups": "Группы объявлений",
    "banners": "Объявления",
}


class APIError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"API VK Рекламы вернул HTTP {status}: {body}")
        self.status = status
        self.body = body


class VKAdsClient:
    def __init__(
        self,
        config: Config,
        session: Optional[requests.Session] = None,
        max_retries: int = 5,
        sleep=time.sleep,
    ):
        self.config = config
        self.session = session or requests.Session()
        self.tokens = TokenManager(config, self.session)
        self.max_retries = max_retries
        self._sleep = sleep

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self.config.base_url + path
        reauthed = False
        for attempt in range(self.max_retries + 1):
            headers = {"Authorization": f"Bearer {self.tokens.get_token()}"}
            resp = self.session.get(url, params=params, headers=headers, timeout=60)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 401 and not reauthed and not self.config.access_token:
                self.tokens.invalidate()
                reauthed = True
                continue
            if (resp.status_code == 429 or resp.status_code >= 500) and attempt < self.max_retries:
                self._sleep(min(2 ** attempt, 30))
                continue
            raise APIError(resp.status_code, resp.text)
        raise APIError(resp.status_code, resp.text)  # pragma: no cover

    def paginate(self, path: str, params: Optional[Dict[str, Any]] = None, limit: int = 250) -> Iterator[dict]:
        offset = 0
        while True:
            page = self.get(path, {**(params or {}), "limit": limit, "offset": offset})
            items = page.get("items", [])
            yield from items
            offset += len(items)
            if not items or offset >= page.get("count", 0):
                break

    # --- справочники ----------------------------------------------------------

    def user(self) -> dict:
        return self.get("/api/v2/user.json")

    def list_objects(self, level: str, include_deleted: bool = False) -> List[dict]:
        if level not in LEVELS:
            raise ValueError(f"Неизвестный уровень {level!r}, допустимы: {', '.join(LEVELS)}")
        params: Dict[str, Any] = {"fields": "id,name,status"}
        if not include_deleted:
            params["_status__in"] = "active,blocked"
        return list(self.paginate(f"/api/v2/{level}.json", params))

    # --- статистика -----------------------------------------------------------

    def day_stats(self, level: str, ids: List[int], date_from: str, date_to: str) -> List[dict]:
        """Сырые ответы /api/v2/statistics/{level}/day.json (метрики base)."""
        if not ids:
            return []
        resp = self.get(
            f"/api/v2/statistics/{level}/day.json",
            {
                "id": ",".join(str(i) for i in ids),
                "date_from": date_from,
                "date_to": date_to,
                "metrics": "base",
            },
        )
        return resp.get("items", [])
