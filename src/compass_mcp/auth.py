"""Token acquisition and lifecycle."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .config import GRANT_AUTHORIZATION_CODE, GRANT_CLIENT_CREDENTIALS, Config
from .convert import epoch_to_iso
from .errors import LoginError, NotAuthenticatedError
from .token_store import load_tokens, save_tokens

TOKEN_PATH = "/compass/oauth2/token"
EXPIRY_SKEW_SECONDS = 60
DEFAULT_ACCESS_LIFETIME = 900


def _expiry(now: float, body: dict[str, Any], key: str, default: int | None) -> float | None:
    lifetime = body.get(key, default)
    if lifetime is None:
        return None
    return now + float(lifetime)


class TokenManager:
    """Serves a valid access token; owns nothing else."""

    def __init__(self, config: Config, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._config = config
        self._http = httpx.AsyncClient(
            base_url=config.base_url, timeout=config.timeout, transport=transport
        )
        self._lock = asyncio.Lock()
        self._access_token: str | None = None
        self._access_expires_at: float = 0.0
        self._stored: dict[str, Any] | None = None

    # -- public ----------------------------------------------------------

    async def get_token(self) -> str:
        async with self._lock:
            if self._access_token and time.time() < self._access_expires_at - EXPIRY_SKEW_SECONDS:
                return self._access_token
            if self._config.grant_type == GRANT_CLIENT_CREDENTIALS:
                await self._fetch_client_credentials()
            else:
                await self._use_or_refresh_stored()
            assert self._access_token is not None
            return self._access_token

    def invalidate(self) -> None:
        """Drop the cached access token (e.g. after a 401)."""
        self._access_token = None
        self._access_expires_at = 0.0

    def identity(self) -> dict[str, Any]:
        """Auth status for diagnostics. Never includes token material."""
        info: dict[str, Any] = {
            "mode": self._config.grant_type,
            "environment": self._config.env,
            "base_url": self._config.base_url,
            "access_token_cached": self._access_token is not None,
            "access_expires_at": (
                epoch_to_iso(int(self._access_expires_at)) if self._access_token else None
            ),
        }
        if self._config.grant_type == GRANT_AUTHORIZATION_CODE:
            stored = self._stored or load_tokens(self._config.token_path)
            if stored:
                info["logged_in"] = True
                info["user"] = stored.get("user")
                info["legal_entity"] = stored.get("legal_entity")
                refresh_at = stored.get("refresh_expires_at")
                info["refresh_expires_at"] = (
                    epoch_to_iso(int(refresh_at)) if refresh_at else None
                )
            else:
                info["logged_in"] = False
                info["hint"] = "Run `compass-mcp login` or the compass_login tool."
        return info

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- internals ---------------------------------------------------------

    async def _post_token(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._http.post(TOKEN_PATH, json=payload)
        if resp.status_code not in (200, 201):
            raise NotAuthenticatedError(
                f"Token request failed: HTTP {resp.status_code} {resp.text[:300]}"
            )
        return resp.json()

    async def _fetch_client_credentials(self) -> None:
        self._config.require_client_credentials()
        body = await self._post_token(
            {
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "grant_type": GRANT_CLIENT_CREDENTIALS,
            }
        )
        self._access_token = body["access_token"]
        self._access_expires_at = time.time() + float(
            body.get("expires_in", DEFAULT_ACCESS_LIFETIME)
        )

    async def _use_or_refresh_stored(self) -> None:
        stored = load_tokens(self._config.token_path)
        if stored is None:
            raise NotAuthenticatedError(
                f"No stored Compass login for environment {self._config.env!r}. "
                "Run `compass-mcp login` (or the compass_login tool) to sign in."
            )
        self._stored = stored
        now = time.time()

        access = stored.get("access_token")
        access_at = float(stored.get("access_expires_at") or 0)
        if access and now < access_at - EXPIRY_SKEW_SECONDS:
            self._access_token = access
            self._access_expires_at = access_at
            return

        refresh = stored.get("refresh_token")
        refresh_at = stored.get("refresh_expires_at")
        if not refresh:
            raise NotAuthenticatedError(
                "Stored login has no refresh token. Run `compass-mcp login` again."
            )
        if refresh_at is not None and now >= float(refresh_at):
            raise NotAuthenticatedError(
                "Stored refresh token has expired (they last ~180 days). "
                "Run `compass-mcp login` again."
            )

        self._config.require_client_credentials()
        body = await self._post_token(
            {
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            }
        )
        stored["access_token"] = body["access_token"]
        stored["access_expires_at"] = _expiry(now, body, "expires_in", DEFAULT_ACCESS_LIFETIME)
        if body.get("refresh_token"):
            stored["refresh_token"] = body["refresh_token"]
            stored["refresh_expires_at"] = _expiry(now, body, "refresh_token_expires_in", None)
        if body.get("user"):
            stored["user"] = body["user"]
        if body.get("legal_entity"):
            stored["legal_entity"] = body["legal_entity"]
        save_tokens(self._config.token_path, stored)
        self._stored = stored
        self._access_token = stored["access_token"]
        self._access_expires_at = float(stored["access_expires_at"])


def exchange_authorization_code(
    config: Config, code: str, http: httpx.Client | None = None
) -> dict[str, Any]:
    """Exchange a consent-page authorization_code for tokens and persist them.

    Synchronous — called from the login HTTP server thread.
    """
    config.require_client_credentials()
    own_client = http is None
    client = http or httpx.Client(base_url=config.base_url, timeout=config.timeout)
    try:
        resp = client.post(
            TOKEN_PATH,
            json={
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "grant_type": GRANT_AUTHORIZATION_CODE,
                "authorization_code": code,
                "redirect_uri": config.redirect_uri,
            },
        )
    finally:
        if own_client:
            client.close()
    if resp.status_code not in (200, 201):
        raise LoginError(
            f"Code exchange failed: HTTP {resp.status_code} {resp.text[:300]}"
        )
    body = resp.json()
    now = time.time()
    data: dict[str, Any] = {
        "env": config.env,
        "client_id": config.client_id,
        "obtained_at": now,
        "access_token": body["access_token"],
        "access_expires_at": _expiry(now, body, "expires_in", DEFAULT_ACCESS_LIFETIME),
        "refresh_token": body.get("refresh_token"),
        "refresh_expires_at": _expiry(now, body, "refresh_token_expires_in", None),
        "user": body.get("user"),
        "legal_entity": body.get("legal_entity"),
    }
    save_tokens(config.token_path, data)
    return data
