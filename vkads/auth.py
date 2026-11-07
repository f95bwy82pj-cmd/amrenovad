"""Получение и кэширование OAuth2-токена VK Рекламы.

VK Реклама ограничивает число активных токенов на одно приложение, поэтому токен
сохраняется в локальный файл и продлевается через refresh_token, а не
запрашивается заново при каждом запуске.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import requests

from .config import Config

TOKEN_PATH = "/api/v2/oauth2/token.json"
TOKEN_DELETE_PATH = "/api/v2/oauth2/token/delete.json"
# Обновляем токен заранее, чтобы он не истёк посреди выгрузки
EXPIRY_MARGIN = 300


class AuthError(RuntimeError):
    pass


class TokenManager:
    def __init__(self, config: Config, session: Optional[requests.Session] = None):
        self.config = config
        self.session = session or requests.Session()
        self._token: Optional[dict] = None

    # --- публичный интерфейс -------------------------------------------------

    def get_token(self) -> str:
        if self.config.access_token:
            return self.config.access_token

        token = self._token or self._load_cache()
        if token and token.get("expires_at", 0) - EXPIRY_MARGIN > time.time():
            self._token = token
            return token["access_token"]

        if token and token.get("refresh_token"):
            try:
                return self._store(self._refresh(token["refresh_token"]))
            except AuthError:
                pass  # refresh_token протух — получаем новый токен

        return self._store(self._request_new())

    def invalidate(self) -> None:
        """Сбросить токен в памяти (например, после ответа 401)."""
        if self._token:
            self._token["expires_at"] = 0
        self._save_cache(self._token)

    def delete_all_tokens(self) -> None:
        """Отозвать все токены приложения (если упёрлись в лимит токенов)."""
        self._require_credentials()
        data = {"client_id": self.config.client_id, "client_secret": self.config.client_secret}
        if self.config.agency_client_name:
            data["username"] = self.config.agency_client_name
        resp = self.session.post(self.config.base_url + TOKEN_DELETE_PATH, data=data, timeout=30)
        if resp.status_code not in (200, 204):
            raise AuthError(f"Не удалось удалить токены: HTTP {resp.status_code} {resp.text}")
        self._token = None
        try:
            self.config.token_cache.unlink()
        except FileNotFoundError:
            pass

    # --- внутреннее -----------------------------------------------------------

    def _require_credentials(self) -> None:
        if not (self.config.client_id and self.config.client_secret):
            raise AuthError(
                "Не заданы VK_ADS_CLIENT_ID и VK_ADS_CLIENT_SECRET "
                "(или VK_ADS_ACCESS_TOKEN). См. .env.example."
            )

    def _request_new(self) -> dict:
        self._require_credentials()
        data = {"client_id": self.config.client_id, "client_secret": self.config.client_secret}
        if self.config.agency_client_name:
            data["grant_type"] = "agency_client_credentials"
            data["agency_client_name"] = self.config.agency_client_name
        else:
            data["grant_type"] = "client_credentials"
        return self._post_token(data)

    def _refresh(self, refresh_token: str) -> dict:
        self._require_credentials()
        return self._post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            }
        )

    def _post_token(self, data: dict) -> dict:
        resp = self.session.post(self.config.base_url + TOKEN_PATH, data=data, timeout=30)
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if resp.status_code != 200 or "access_token" not in payload:
            error = payload.get("error") if isinstance(payload, dict) else None
            if error == "token_limit_exceeded":
                raise AuthError(
                    "Превышен лимит токенов приложения. Выполните `vkads tokens-reset`, "
                    "чтобы отозвать старые токены, и повторите запуск."
                )
            raise AuthError(f"Ошибка авторизации: HTTP {resp.status_code} {resp.text}")
        return payload

    def _store(self, payload: dict) -> str:
        token = {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token"),
            "expires_at": time.time() + int(payload.get("expires_in") or 0),
        }
        self._token = token
        self._save_cache(token)
        return token["access_token"]

    def _load_cache(self) -> Optional[dict]:
        try:
            data = json.loads(self.config.token_cache.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return None
        return data if isinstance(data, dict) and data.get("access_token") else None

    def _save_cache(self, token: Optional[dict]) -> None:
        if token is None:
            return
        path = self.config.token_cache
        path.write_text(json.dumps(token), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
