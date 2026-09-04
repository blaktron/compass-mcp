"""Command-line entry points.

  compass-mcp [serve]   run the MCP server on stdio (default)
  compass-mcp login     interactive OAuth login (Authorization Code grant)
  compass-mcp status    show auth status (no token material)
  compass-mcp logout    delete stored tokens for the configured environment
"""

from __future__ import annotations

import argparse
import json
import sys

from .auth import TokenManager
from .config import Config
from .errors import CompassError
from .login_server import run_login_flow
from .token_store import clear_tokens


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="compass-mcp",
        description="MCP server for the COMPASS (Bespoke Metrics) API.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="Run the MCP server on stdio (default).")
    login = sub.add_parser("login", help="Interactive Compass OAuth login (opens a browser).")
    login.add_argument("--no-browser", action="store_true", help="Print the URL instead of opening a browser.")
    login.add_argument("--timeout", type=float, default=300.0, help="Seconds to wait for the redirect (default 300).")
    sub.add_parser("status", help="Show authentication status.")
    sub.add_parser("logout", help="Delete stored tokens for the configured environment.")
    args = parser.parse_args(argv)
    command = args.command or "serve"

    try:
        config = Config.from_env()
    except CompassError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if command == "serve":
        from .server import build_server

        build_server(config).run("stdio")
        return 0

    if command == "login":
        try:
            result = run_login_flow(
                config, open_browser=not args.no_browser, timeout=args.timeout
            )
        except CompassError as exc:
            print(f"Login failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result.to_dict(), indent=2))
        if result.status == "success":
            print(
                "\nTokens stored. Run the server with COMPASS_GRANT_TYPE=authorization_code "
                "to use this login.",
                file=sys.stderr,
            )
            return 0
        return 1

    if command == "status":
        info = TokenManager(config).identity()
        info["writes_enabled"] = config.allow_writes
        print(json.dumps(info, indent=2))
        return 0

    if command == "logout":
        removed = clear_tokens(config.token_path)
        print(
            f"Removed {config.token_path}" if removed else f"No tokens stored at {config.token_path}"
        )
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
