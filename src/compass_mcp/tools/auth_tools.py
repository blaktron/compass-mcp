"""Auth diagnostics and the interactive login trigger."""

from __future__ import annotations

from typing import Any

from ..config import GRANT_AUTHORIZATION_CODE
from ..login_server import background_login_status, start_background_login
from ..runtime import get_app
from .common import tool_errors


@tool_errors
async def compass_auth_status() -> dict[str, Any]:
    """Report the server's authentication status: grant mode, environment, whether a
    token is cached, the signed-in identity, and whether writes are enabled. Never
    returns token material."""
    app = get_app()
    info = app.tokens.identity()
    info["writes_enabled"] = app.config.allow_writes
    login = background_login_status()
    if login.get("status") != "no_login_in_progress":
        info["interactive_login"] = login
    return info


@tool_errors
async def compass_login(open_browser: bool = True) -> dict[str, Any]:
    """Start the interactive OAuth login (Authorization Code grant).

    Starts a local loopback page and returns its URL. Only applies when
    COMPASS_GRANT_TYPE=authorization_code; check progress with compass_auth_status.
    If a login is already running, its URL is returned again.
    """
    app = get_app()
    if app.config.grant_type != GRANT_AUTHORIZATION_CODE:
        return {
            "status": "not_applicable",
            "message": (
                "The server is running with the client_credentials grant, which needs no "
                "interactive login. Set COMPASS_GRANT_TYPE=authorization_code (and restart) "
                "to act as a specific Compass user instead of the service principal."
            ),
        }
    result = start_background_login(app.config, open_browser=open_browser)
    result["instructions"] = (
        "Ask the user to open login_url in their browser on this machine and sign in "
        "with Compass. Then call compass_auth_status to confirm the login completed."
    )
    return result
