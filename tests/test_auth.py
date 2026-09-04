import json
import time

import httpx
import pytest

from compass_mcp.auth import TokenManager, exchange_authorization_code
from compass_mcp.errors import LoginError, NotAuthenticatedError
from compass_mcp.token_store import load_tokens, save_tokens


class TokenEndpoint:
    """Scripted /compass/oauth2/token endpoint."""

    def __init__(self):
        self.requests = []
        self.responses = []

    def push(self, payload, status=201):
        self.responses.append((status, payload))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/compass/oauth2/token"
        self.requests.append(json.loads(request.content))
        status, payload = self.responses.pop(0)
        return httpx.Response(status, json=payload)

    def transport(self):
        return httpx.MockTransport(self)


# -- client_credentials -------------------------------------------------------


async def test_client_credentials_fetch_and_cache(make_config):
    endpoint = TokenEndpoint()
    endpoint.push({"access_token": "tok1", "expires_in": 900, "token_type": "bearer"})
    manager = TokenManager(make_config(), transport=endpoint.transport())
    assert await manager.get_token() == "tok1"
    assert await manager.get_token() == "tok1"  # cached, no second request
    assert len(endpoint.requests) == 1
    assert endpoint.requests[0]["grant_type"] == "client_credentials"
    assert endpoint.requests[0]["client_id"] == "cid"


async def test_client_credentials_proactive_refresh_inside_skew(make_config):
    endpoint = TokenEndpoint()
    endpoint.push({"access_token": "tok1", "expires_in": 900})
    endpoint.push({"access_token": "tok2", "expires_in": 900})
    manager = TokenManager(make_config(), transport=endpoint.transport())
    await manager.get_token()
    manager._access_expires_at = time.time() + 30  # inside the 60s skew window
    assert await manager.get_token() == "tok2"


async def test_client_credentials_invalidate_forces_refetch(make_config):
    endpoint = TokenEndpoint()
    endpoint.push({"access_token": "tok1", "expires_in": 900})
    endpoint.push({"access_token": "tok2", "expires_in": 900})
    manager = TokenManager(make_config(), transport=endpoint.transport())
    await manager.get_token()
    manager.invalidate()
    assert await manager.get_token() == "tok2"


async def test_token_endpoint_failure_surfaces(make_config):
    endpoint = TokenEndpoint()
    endpoint.push({"detail": "bad credentials"}, status=400)
    manager = TokenManager(make_config(), transport=endpoint.transport())
    with pytest.raises(NotAuthenticatedError, match="400"):
        await manager.get_token()


# -- authorization_code --------------------------------------------------------


def _auth_config(make_config):
    return make_config(grant_type="authorization_code")


async def test_auth_code_without_login_file(make_config):
    manager = TokenManager(_auth_config(make_config), transport=TokenEndpoint().transport())
    with pytest.raises(NotAuthenticatedError, match="compass-mcp login"):
        await manager.get_token()


async def test_auth_code_uses_valid_stored_access_token(make_config):
    config = _auth_config(make_config)
    save_tokens(
        config.token_path,
        {"access_token": "stored", "access_expires_at": time.time() + 800, "refresh_token": "r1"},
    )
    endpoint = TokenEndpoint()  # no responses queued: any HTTP call would fail
    manager = TokenManager(config, transport=endpoint.transport())
    assert await manager.get_token() == "stored"
    assert endpoint.requests == []


async def test_auth_code_refreshes_and_rotates(make_config):
    config = _auth_config(make_config)
    save_tokens(
        config.token_path,
        {
            "access_token": "old",
            "access_expires_at": time.time() - 10,
            "refresh_token": "r1",
            "refresh_expires_at": time.time() + 10_000,
        },
    )
    endpoint = TokenEndpoint()
    endpoint.push(
        {
            "access_token": "new",
            "expires_in": 900,
            "refresh_token": "r2",
            "refresh_token_expires_in": 15552000,
            "user": {"id": "u1", "email": "a@b.c"},
            "legal_entity": {"id": "le1", "name": "GC Co", "type": "gc"},
        }
    )
    manager = TokenManager(config, transport=endpoint.transport())
    assert await manager.get_token() == "new"
    assert endpoint.requests[0]["grant_type"] == "refresh_token"
    assert endpoint.requests[0]["refresh_token"] == "r1"
    stored = load_tokens(config.token_path)
    assert stored["refresh_token"] == "r2"  # rotated
    assert stored["access_token"] == "new"
    assert stored["legal_entity"]["name"] == "GC Co"


async def test_auth_code_expired_refresh_token(make_config):
    config = _auth_config(make_config)
    save_tokens(
        config.token_path,
        {
            "access_token": "old",
            "access_expires_at": time.time() - 10,
            "refresh_token": "r1",
            "refresh_expires_at": time.time() - 5,
        },
    )
    manager = TokenManager(config, transport=TokenEndpoint().transport())
    with pytest.raises(NotAuthenticatedError, match="expired"):
        await manager.get_token()


def test_identity_never_contains_token_material(make_config, tmp_path):
    config = _auth_config(make_config)
    save_tokens(
        config.token_path,
        {
            "access_token": "SECRET",
            "refresh_token": "SECRET2",
            "refresh_expires_at": time.time() + 100,
            "user": {"email": "a@b.c"},
        },
    )
    info = TokenManager(config).identity()
    text = json.dumps(info)
    assert "SECRET" not in text
    assert info["logged_in"] is True


# -- code exchange --------------------------------------------------------------


def test_exchange_authorization_code_persists(make_config):
    config = _auth_config(make_config)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            201,
            json={
                "access_token": "at",
                "expires_in": 900,
                "refresh_token": "rt",
                "refresh_token_expires_in": 15552000,
                "user": {"id": "u1", "email": "user@example.com"},
                "legal_entity": {"id": "le1", "name": "GC Co", "type": "gc"},
            },
        )

    client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
    data = exchange_authorization_code(config, "the-code", http=client)
    assert seen["grant_type"] == "authorization_code"
    assert seen["authorization_code"] == "the-code"
    assert seen["redirect_uri"] == config.redirect_uri
    stored = load_tokens(config.token_path)
    assert stored["refresh_token"] == "rt"
    assert data["user"]["email"] == "user@example.com"
    # 0600 permissions
    assert (config.token_path.stat().st_mode & 0o777) == 0o600


def test_exchange_failure_raises_login_error(make_config):
    config = _auth_config(make_config)
    client = httpx.Client(
        base_url=config.base_url,
        transport=httpx.MockTransport(lambda r: httpx.Response(400, text="bad code")),
    )
    with pytest.raises(LoginError, match="400"):
        exchange_authorization_code(config, "bad", http=client)
    assert load_tokens(config.token_path) is None
