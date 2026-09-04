"""Tests for the shared HTTP layer: pagination, params, retries, errors."""

from __future__ import annotations

import httpx
import pytest

import compass_mcp.client as client_module
from compass_mcp.client import CompassClient, normalize_params
from compass_mcp.errors import CompassApiError

from conftest import MockAPI, StaticTokens


def _client(api: MockAPI, make_config, **config_overrides) -> tuple[CompassClient, StaticTokens]:
    tokens = StaticTokens()
    config = make_config(**config_overrides)
    return CompassClient(config, tokens, transport=api.transport()), tokens


def test_normalize_params():
    out = normalize_params(
        {"active": True, "primary": False, "purposes": ["a", "b"], "skip": None, "limit": 5}
    )
    assert ("active", "true") in out
    assert ("primary", "false") in out
    assert out.count(("purposes", "a")) == 1 and ("purposes", "b") in out
    assert not any(k == "skip" for k, _ in out)
    assert ("limit", "5") in out


async def test_auth_header_attached(api, make_config):
    api.json("GET", "/compass/score", {"data": []})
    client, _ = _client(api, make_config)
    await client.request("GET", "/compass/score")
    assert api.requests[0].headers["Oauth2-Access-Token"] == "test-token"


async def test_paginate_collects_all_pages(api, make_config):
    api.collection("GET", "/hub/legal_entity", [{"id": str(n)} for n in range(5)])
    client, _ = _client(api, make_config)
    result = await client.paginate("/hub/legal_entity", limit=2, max_pages=10)
    assert result["returned"] == 5
    assert result["count"] == 5
    assert result["truncated"] is False
    assert result["next_page"] is None
    assert len(api.calls("GET", "/hub/legal_entity")) == 3  # 2 + 2 + 1


async def test_paginate_reports_truncation(api, make_config):
    api.collection("GET", "/hub/legal_entity", [{"id": str(n)} for n in range(5)])
    client, _ = _client(api, make_config)
    result = await client.paginate("/hub/legal_entity", limit=2, max_pages=1)
    assert result["returned"] == 2
    assert result["truncated"] is True
    assert result["next_page"] == 2


async def test_paginate_clamps_limit_to_api_max(api, make_config):
    api.collection("GET", "/hub/legal_entity", [])
    client, _ = _client(api, make_config)
    await client.paginate("/hub/legal_entity", limit=9999, max_pages=1)
    assert api.requests[0].url.params["limit"] == "250"


async def test_retry_on_429_then_success(api, make_config, monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(client_module, "_sleep", fake_sleep)
    state = {"calls": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={"ok": True})

    api.add("GET", "/compass/score", flaky)
    client, _ = _client(api, make_config)
    assert await client.request("GET", "/compass/score") == {"ok": True}
    assert state["calls"] == 2
    assert len(sleeps) == 1


async def test_retries_exhausted_raises(api, make_config, monkeypatch):
    async def fake_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(client_module, "_sleep", fake_sleep)
    api.add("GET", "/compass/score", lambda r: httpx.Response(503, text="down"))
    client, _ = _client(api, make_config, max_retries=2)
    with pytest.raises(CompassApiError) as excinfo:
        await client.request("GET", "/compass/score")
    assert excinfo.value.status_code == 503
    assert len(api.requests) == 3  # initial + 2 retries


async def test_401_invalidates_token_and_retries_once(api, make_config):
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(401, text="expired")
        return httpx.Response(200, json={"ok": True})

    api.add("GET", "/compass/score", handler)
    client, tokens = _client(api, make_config)
    assert await client.request("GET", "/compass/score") == {"ok": True}
    assert tokens.invalidations == 1


async def test_second_401_is_an_error(api, make_config):
    api.add("GET", "/compass/score", lambda r: httpx.Response(401, text="nope"))
    client, tokens = _client(api, make_config)
    with pytest.raises(CompassApiError) as excinfo:
        await client.request("GET", "/compass/score")
    assert excinfo.value.status_code == 401
    assert tokens.invalidations == 1


async def test_client_error_carries_raw_body(api, make_config):
    api.add("GET", "/hub/workflows", lambda r: httpx.Response(400, text='{"weird": "shape"}'))
    client, _ = _client(api, make_config)
    with pytest.raises(CompassApiError) as excinfo:
        await client.request("GET", "/hub/workflows")
    err = excinfo.value.to_dict()["error"]
    assert err["status"] == 400
    assert err["body"] == '{"weird": "shape"}'
    assert err["path"] == "/hub/workflows"


async def test_204_returns_none(api, make_config):
    api.add("DELETE", "/hub/workflows/x", lambda r: httpx.Response(204))
    client, _ = _client(api, make_config)
    assert await client.request("DELETE", "/hub/workflows/x") is None
