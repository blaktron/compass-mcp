"""Shared HTTP layer.

- every request carries `Oauth2-Access-Token` from the TokenManager;
- one automatic re-auth on 401;
- bounded exponential backoff on 429/5xx/transport errors;
- non-2xx surfaces status + raw body verbatim (CompassApiError);
- uniform auto-pagination over the `prev/next/count/data` envelope.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from .auth import TokenManager
from .config import Config
from .errors import CompassApiError

RETRY_STATUSES = {429, 500, 502, 503, 504}

# Indirection so tests can stub the backoff sleep.
_sleep = asyncio.sleep


def normalize_params(params: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Drop Nones, lower-case booleans, expand lists to repeated params."""
    out: list[tuple[str, str]] = []
    for key, value in (params or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            out.append((key, "true" if value else "false"))
        elif isinstance(value, (list, tuple)):
            for item in value:
                out.append((key, str(item)))
        else:
            out.append((key, str(value)))
    return out


class CompassClient:
    def __init__(
        self,
        config: Config,
        tokens: TokenManager,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._tokens = tokens
        self._http = httpx.AsyncClient(
            base_url=config.base_url, timeout=config.timeout, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        files: Any = None,
    ) -> Any:
        query = normalize_params(params)
        attempts = 0
        reauthed = False
        while True:
            token = await self._tokens.get_token()
            try:
                resp = await self._http.request(
                    method,
                    path,
                    params=query or None,
                    json=json_body,
                    files=files,
                    headers={"Oauth2-Access-Token": token},
                )
            except httpx.TransportError as exc:
                if attempts < self._config.max_retries:
                    attempts += 1
                    await _sleep(self._backoff(attempts))
                    continue
                raise CompassApiError(0, f"transport error: {exc}", method, path) from exc

            if resp.status_code == 401 and not reauthed:
                reauthed = True
                self._tokens.invalidate()
                continue
            if resp.status_code in RETRY_STATUSES and attempts < self._config.max_retries:
                attempts += 1
                await _sleep(self._backoff(attempts))
                continue
            if resp.status_code >= 400:
                raise CompassApiError(resp.status_code, resp.text, method, path)
            if resp.status_code == 204 or not resp.content:
                return None
            return resp.json()

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(8.0, 0.5 * (2 ** (attempt - 1))) + random.random() * 0.25

    async def paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        limit: int = 50,
        max_pages: int = 5,
        method: str = "GET",
        json_body: Any = None,
    ) -> dict[str, Any]:
        """Aggregate the standard envelope across pages.

        Returns {count, returned, truncated, next_page, data}. Truncation is
        never silent: if more matches exist than were fetched, `truncated` is
        true and `next_page` says where to resume.
        """
        limit = max(1, min(int(limit), 250))
        max_pages = max(1, int(max_pages))
        collected: list[Any] = []
        count: Any = None
        page = 1
        last_len = 0
        while True:
            merged = dict(params or {})
            merged["limit"] = limit
            merged["page"] = page
            resp = await self.request(method, path, params=merged, json_body=json_body)
            if not isinstance(resp, dict):
                break
            data = resp.get("data") or []
            if count is None:
                count = resp.get("count")
            collected.extend(data)
            last_len = len(data)
            if last_len < limit or page >= max_pages:
                break
            page += 1

        if isinstance(count, int):
            truncated = len(collected) < count
        else:
            truncated = last_len == limit and page >= max_pages
        return {
            "count": count,
            "returned": len(collected),
            "truncated": truncated,
            "next_page": page + 1 if truncated else None,
            "data": collected,
        }
