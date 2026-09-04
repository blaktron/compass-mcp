"""Interactive OAuth login for the Authorization Code grant.

Serves a loopback-only page that links out to `{web_url}/oauth-login`, catches
the redirect back at the registered redirect_uri, validates `state`, exchanges
the `authorization_code` for tokens, and persists them via token_store.
"""

from __future__ import annotations

import secrets
import threading
import webbrowser
from dataclasses import dataclass, field
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

from .auth import exchange_authorization_code
from .config import Config
from .errors import LoginError

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass
class LoginResult:
    status: str  # "success" | "cancelled" | "error" | "timeout"
    detail: str | None = None
    user: dict[str, Any] | None = None
    legal_entity: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.detail:
            out["detail"] = self.detail
        if self.user is not None:
            out["user"] = self.user
        if self.legal_entity is not None:
            out["legal_entity"] = self.legal_entity
        return out


@dataclass
class _FlowState:
    config: Config
    state: str
    callback_path: str
    exchange_fn: Callable[[Config, str], dict[str, Any]]
    result: LoginResult | None = None
    done: threading.Event = field(default_factory=threading.Event)

    def finish(self, result: LoginResult) -> None:
        if self.result is None:
            self.result = result
            self.done.set()


def consent_url(config: Config, state: str) -> str:
    query = urlencode(
        {
            "client_id": config.client_id or "",
            "redirect_uri": config.redirect_uri,
            "state": state,
        }
    )
    return f"{config.web_url}/oauth-login?{query}"


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    max-width: 34rem; margin: 4rem auto; padding: 0 1.25rem; line-height: 1.55;
  }}
  .card {{
    border: 1px solid rgba(128,128,128,.35); border-radius: 12px; padding: 1.5rem 1.75rem;
  }}
  h1 {{ font-size: 1.15rem; margin: 0 0 .75rem; }}
  p  {{ margin: .5rem 0; }}
  .muted {{ opacity: .7; font-size: .85rem; }}
  .ok    {{ color: #1a7f37; }}
  .bad   {{ color: #b42318; }}
  a.btn {{
    display: inline-block; margin: 1rem 0 .25rem; padding: .6rem 1.1rem;
    border-radius: 8px; background: #121D2D; color: #fff; text-decoration: none;
    font-weight: 600;
  }}
  code {{ font-size: .85em; }}
</style>
</head>
<body><div class="card">{body}</div></body>
</html>"""


def _login_page(state: _FlowState) -> str:
    cfg = state.config
    url = consent_url(cfg, state.state)
    return _page(
        "Compass MCP server — sign in",
        f"""
<h1>Compass MCP server — connect your Compass account</h1>
<p>This is the local login page of your Compass MCP server
(environment <code>{escape(cfg.env)}</code>).</p>
<p>Clicking the button sends you to the Compass consent page at
<code>{escape(cfg.web_url)}</code>. You sign in <strong>on Compass's own
site</strong> — this local page never sees or asks for your password.</p>
<a class="btn" href="{escape(url, quote=True)}">Sign in with Compass</a>
<p class="muted">After you allow access, Compass redirects your browser back to
<code>{escape(cfg.redirect_uri)}</code> and this window will confirm the result.
Tokens are stored locally in <code>{escape(str(cfg.token_path))}</code>
(readable only by your user account).</p>
""",
    )


def _success_page(data: dict[str, Any]) -> str:
    user = data.get("user") or {}
    le = data.get("legal_entity") or {}
    who = escape(str(user.get("email", "your Compass account")))
    company = ""
    if le:
        company = (
            f"<p>Acting as legal entity <strong>{escape(str(le.get('name', '?')))}</strong>"
            f" (<code>{escape(str(le.get('type', '?')))}</code>).</p>"
        )
    return _page(
        "Compass MCP server — connected",
        f"""
<h1 class="ok">✓ Connected</h1>
<p>Signed in as <strong>{who}</strong>.</p>
{company}
<p>Tokens were saved for the MCP server. You can close this tab and return to
your MCP client.</p>
""",
    )


def _cancelled_page() -> str:
    return _page(
        "Compass MCP server — cancelled",
        """
<h1 class="bad">Sign-in cancelled</h1>
<p>You cancelled the Compass consent screen, so no access was granted and
nothing was stored.</p>
<p>Close this tab, or go back to the login page to try again.</p>
""",
    )


def _error_page(message: str) -> str:
    return _page(
        "Compass MCP server — error",
        f"""
<h1 class="bad">Sign-in failed</h1>
<p>{escape(message)}</p>
<p class="muted">Nothing was stored. Close this tab and retry from the login
page; if it keeps failing, check the server's COMPASS_* configuration.</p>
""",
    )


class _LoginHandler(BaseHTTPRequestHandler):
    flow: _FlowState  # set on the subclass created per server

    def log_message(self, fmt: str, *args: Any) -> None:  # silence request logging
        return

    def _send(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/login"):
            self._send(200, _login_page(self.flow))
            return
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path == self.flow.callback_path:
            self._handle_callback(parse_qs(parsed.query))
            return
        self._send(404, _error_page(f"Unknown path {parsed.path!r}."))

    def _handle_callback(self, query: dict[str, list[str]]) -> None:
        def first(key: str) -> str | None:
            values = query.get(key)
            return values[0] if values else None

        state = first("state")
        if state != self.flow.state:
            self._send(400, _error_page("State mismatch — this redirect was not initiated by this login page."))
            return

        if first("consent_status") == "cancelled":
            self.flow.finish(LoginResult(status="cancelled"))
            self._send(200, _cancelled_page())
            return

        code = first("authorization_code")
        if not code:
            self._send(400, _error_page("Redirect carried neither an authorization_code nor consent_status=cancelled."))
            return

        try:
            data = self.flow.exchange_fn(self.flow.config, code)
        except Exception as exc:  # surfaces LoginError and anything unexpected
            self.flow.finish(LoginResult(status="error", detail=str(exc)))
            self._send(502, _error_page(str(exc)))
            return
        self.flow.finish(
            LoginResult(
                status="success",
                user=data.get("user"),
                legal_entity=data.get("legal_entity"),
            )
        )
        self._send(200, _success_page(data))


def _bind_from_redirect_uri(config: Config) -> tuple[str, int, str]:
    parsed = urlparse(config.redirect_uri)
    host = (parsed.hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        raise LoginError(
            f"The built-in login page only listens on loopback, but "
            f"COMPASS_REDIRECT_URI points at {host!r}. Register a "
            f"http://localhost:<port>/... redirect URI with Compass."
        )
    port = parsed.port
    if port is None:
        raise LoginError(
            "COMPASS_REDIRECT_URI must include an explicit port "
            "(e.g. http://localhost:8765/oauth2/callback)."
        )
    return "127.0.0.1", port, parsed.path or "/oauth2/callback"


class LoginFlow:
    """One interactive login attempt: local server + state + result."""

    def __init__(
        self,
        config: Config,
        exchange_fn: Callable[[Config, str], dict[str, Any]] | None = None,
    ) -> None:
        config.require_client_credentials()
        bind_host, port, callback_path = _bind_from_redirect_uri(config)
        self.state = _FlowState(
            config=config,
            state=secrets.token_urlsafe(32),
            callback_path=callback_path,
            exchange_fn=exchange_fn or exchange_authorization_code,
        )
        handler = type("BoundLoginHandler", (_LoginHandler,), {"flow": self.state})
        try:
            self._server = ThreadingHTTPServer((bind_host, port), handler)
        except OSError as exc:
            raise LoginError(
                f"Could not listen on {bind_host}:{port} for the OAuth redirect "
                f"({exc}). Is another login already running, or the port taken?"
            ) from exc
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self.login_url = f"http://localhost:{port}/"

    @property
    def consent_url(self) -> str:
        return consent_url(self.state.config, self.state.state)

    def start(self, open_browser: bool) -> None:
        self._thread.start()
        if open_browser:
            webbrowser.open(self.login_url)

    def wait(self, timeout: float | None) -> LoginResult:
        finished = self.state.done.wait(timeout)
        if not finished:
            self.state.finish(LoginResult(status="timeout", detail=f"No redirect received within {timeout}s."))
        assert self.state.result is not None
        return self.state.result

    def poll(self) -> LoginResult | None:
        return self.state.result

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def run_login_flow(
    config: Config,
    open_browser: bool = True,
    timeout: float = 300.0,
    exchange_fn: Callable[[Config, str], dict[str, Any]] | None = None,
) -> LoginResult:
    """Blocking login (used by `compass-mcp login`)."""
    flow = LoginFlow(config, exchange_fn=exchange_fn)
    flow.start(open_browser=open_browser)
    try:
        return flow.wait(timeout)
    finally:
        flow.stop()


_active_flow: LoginFlow | None = None
_active_lock = threading.Lock()


def start_background_login(
    config: Config,
    open_browser: bool = False,
    exchange_fn: Callable[[Config, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    global _active_flow
    with _active_lock:
        if _active_flow is not None and _active_flow.poll() is None:
            return {
                "status": "already_running",
                "login_url": _active_flow.login_url,
                "consent_url": _active_flow.consent_url,
            }
        if _active_flow is not None:
            _active_flow.stop()
            _active_flow = None
        flow = LoginFlow(config, exchange_fn=exchange_fn)
        flow.start(open_browser=open_browser)
        _active_flow = flow

        def _reap() -> None:
            flow.state.done.wait(timeout=600)
            flow.stop()

        threading.Thread(target=_reap, daemon=True).start()
        return {
            "status": "started",
            "login_url": flow.login_url,
            "consent_url": flow.consent_url,
        }


def background_login_status() -> dict[str, Any]:
    with _active_lock:
        if _active_flow is None:
            return {"status": "no_login_in_progress"}
        result = _active_flow.poll()
        if result is None:
            return {"status": "pending", "login_url": _active_flow.login_url}
        return result.to_dict()
