"""Tests for the interactive OAuth login page (loopback server)."""

from __future__ import annotations

from urllib.parse import quote

import httpx
import pytest

import compass_mcp.login_server as login_server
from compass_mcp.errors import LoginError
from compass_mcp.login_server import (
    LoginFlow,
    background_login_status,
    start_background_login,
)


def _make_flow(make_config, exchange_fn):
    # Port 0 → ephemeral port, no collisions between tests.
    config = make_config(
        grant_type="authorization_code",
        redirect_uri="http://localhost:0/oauth2/callback",
    )
    flow = LoginFlow(config, exchange_fn=exchange_fn)
    flow.start(open_browser=False)
    port = flow._server.server_address[1]
    return flow, f"http://127.0.0.1:{port}"


def _ok_exchange(calls):
    def exchange(config, code):
        calls.append(code)
        return {
            "user": {"id": "u1", "email": "user@example.com"},
            "legal_entity": {"id": "le1", "name": "GC Co", "type": "gc"},
        }

    return exchange


def test_login_page_links_to_compass_consent(make_config):
    flow, base = _make_flow(make_config, _ok_exchange([]))
    try:
        page = httpx.get(f"{base}/").text
        assert "oauth-login" in page
        assert flow.state.state in page
        assert "cid" in page
        assert "csec" not in page
        assert "never sees" in page
    finally:
        flow.stop()


def test_callback_rejects_wrong_state_and_keeps_waiting(make_config):
    calls: list[str] = []
    flow, base = _make_flow(make_config, _ok_exchange(calls))
    try:
        resp = httpx.get(
            f"{base}/oauth2/callback?state=WRONG&authorization_code=abc&consent_status=allowed"
        )
        assert resp.status_code == 400
        assert calls == []
        assert flow.poll() is None
    finally:
        flow.stop()


def test_callback_cancelled(make_config):
    flow, base = _make_flow(make_config, _ok_exchange([]))
    try:
        resp = httpx.get(
            f"{base}/oauth2/callback?state={quote(flow.state.state)}&consent_status=cancelled"
        )
        assert resp.status_code == 200
        assert "cancelled" in resp.text.lower()
        assert flow.poll().status == "cancelled"
    finally:
        flow.stop()


def test_callback_success_exchanges_code(make_config):
    calls: list[str] = []
    flow, base = _make_flow(make_config, _ok_exchange(calls))
    try:
        resp = httpx.get(
            f"{base}/oauth2/callback?state={quote(flow.state.state)}"
            f"&consent_status=allowed&authorization_code=the-code"
        )
        assert resp.status_code == 200
        assert "user@example.com" in resp.text
        assert "GC Co" in resp.text
        assert calls == ["the-code"]
        result = flow.poll()
        assert result.status == "success"
        assert result.legal_entity["type"] == "gc"
    finally:
        flow.stop()


def test_callback_exchange_failure_reports_error(make_config):
    def failing(config, code):
        raise LoginError("Code exchange failed: HTTP 400 nope")

    flow, base = _make_flow(make_config, failing)
    try:
        resp = httpx.get(
            f"{base}/oauth2/callback?state={quote(flow.state.state)}&authorization_code=x"
        )
        assert resp.status_code == 502
        assert flow.poll().status == "error"
        assert "400" in flow.poll().detail
    finally:
        flow.stop()


def test_non_loopback_redirect_uri_refused(make_config):
    config = make_config(
        grant_type="authorization_code",
        redirect_uri="http://example.com:8765/oauth2/callback",
    )
    with pytest.raises(LoginError, match="loopback"):
        LoginFlow(config, exchange_fn=_ok_exchange([]))


def test_missing_port_refused(make_config):
    config = make_config(redirect_uri="http://localhost/oauth2/callback")
    with pytest.raises(LoginError, match="port"):
        LoginFlow(config, exchange_fn=_ok_exchange([]))


def test_background_login_lifecycle(make_config):
    config = make_config(
        grant_type="authorization_code",
        redirect_uri="http://localhost:0/oauth2/callback",
    )
    try:
        started = start_background_login(config, open_browser=False, exchange_fn=_ok_exchange([]))
        assert started["status"] == "started"
        assert background_login_status()["status"] == "pending"

        flow = login_server._active_flow
        port = flow._server.server_address[1]
        httpx.get(
            f"http://127.0.0.1:{port}/oauth2/callback"
            f"?state={quote(flow.state.state)}&consent_status=cancelled"
        )
        assert background_login_status()["status"] == "cancelled"
    finally:
        with login_server._active_lock:
            if login_server._active_flow is not None:
                login_server._active_flow.stop()
                login_server._active_flow = None
