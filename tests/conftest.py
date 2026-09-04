"""Shared fixtures: a mock Compass API transport and an installed app context."""

from __future__ import annotations

import json
from typing import Any, Callable

import httpx
import pytest

from compass_mcp.caches import ProjectIndex, TradesCache, UserCache
from compass_mcp.client import CompassClient
from compass_mcp.config import Config
from compass_mcp.runtime import AppContext, set_app


class StaticTokens:
    """TokenManager stand-in for tool tests."""

    def __init__(self, token: str = "test-token") -> None:
        self.token = token
        self.invalidations = 0

    async def get_token(self) -> str:
        return self.token

    def invalidate(self) -> None:
        self.invalidations += 1

    def identity(self) -> dict[str, Any]:
        return {"mode": "static-test", "access_token_cached": True}

    async def aclose(self) -> None:
        return None


class MockAPI:
    """Route table + request recorder behind an httpx.MockTransport."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = {}
        self.requests: list[httpx.Request] = []

    def add(
        self,
        method: str,
        path: str,
        handler: Callable[[httpx.Request], httpx.Response],
    ) -> None:
        self.routes[(method.upper(), path)] = handler

    def json(self, method: str, path: str, payload: Any, status: int = 200) -> None:
        self.add(method, path, lambda _req: httpx.Response(status, json=payload))

    def collection(self, method: str, path: str, items: list[Any]) -> None:
        """Serve a paginated prev/next/count/data envelope over `items`."""

        def handler(req: httpx.Request) -> httpx.Response:
            params = req.url.params
            limit = int(params.get("limit", "50"))
            page = int(params.get("page", "1"))
            start = (page - 1) * limit
            return httpx.Response(
                200,
                json={
                    "prev": f"?page={page - 1}" if page > 1 else None,
                    "next": f"?page={page + 1}",
                    "count": len(items),
                    "data": items[start : start + limit],
                },
            )

        self.add(method, path, handler)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        if key in self.routes:
            return self.routes[key](request)
        return httpx.Response(404, text=f"mock API has no route for {key}")

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    # -- assertion helpers -------------------------------------------------

    def calls(self, method: str, path: str) -> list[httpx.Request]:
        return [
            r for r in self.requests if r.method == method.upper() and r.url.path == path
        ]

    @staticmethod
    def body_json(request: httpx.Request) -> Any:
        return json.loads(request.content.decode("utf-8"))


@pytest.fixture
def api() -> MockAPI:
    return MockAPI()


@pytest.fixture
def make_config(tmp_path):
    def _make(**overrides: Any) -> Config:
        values: dict[str, Any] = dict(
            env="sandbox-app",
            client_id="cid",
            client_secret="csec",
            token_dir=tmp_path / "tokens",
            max_retries=3,
        )
        values.update(overrides)
        return Config(**values)

    return _make


@pytest.fixture
def app(api: MockAPI, make_config):
    config = make_config(allow_writes=True)
    tokens = StaticTokens()
    client = CompassClient(config, tokens, transport=api.transport())
    ctx = AppContext(
        config=config,
        tokens=tokens,
        client=client,
        trades=TradesCache(client),
        users=UserCache(client),
        projects=ProjectIndex(client),
    )
    set_app(ctx)
    yield ctx
    set_app(None)
