"""Application context shared by all tools.

Tool functions call `get_app()` rather than receiving the context through
their signatures, so the MCP SDK sees clean business-parameter signatures
when deriving input schemas. Tests install a context with `set_app()`.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .auth import TokenManager
from .caches import ProjectIndex, TradesCache, UserCache
from .client import CompassClient
from .config import Config


@dataclass
class AppContext:
    config: Config
    tokens: TokenManager
    client: CompassClient
    trades: TradesCache
    users: UserCache
    projects: ProjectIndex

    async def aclose(self) -> None:
        await self.client.aclose()
        await self.tokens.aclose()


def create_app(
    config: Config,
    transport: httpx.AsyncBaseTransport | None = None,
    token_transport: httpx.AsyncBaseTransport | None = None,
    tokens: TokenManager | None = None,
) -> AppContext:
    token_manager = tokens or TokenManager(config, transport=token_transport)
    client = CompassClient(config, token_manager, transport=transport)
    return AppContext(
        config=config,
        tokens=token_manager,
        client=client,
        trades=TradesCache(client),
        users=UserCache(client),
        projects=ProjectIndex(client),
    )


_app: AppContext | None = None


def set_app(app: AppContext | None) -> None:
    global _app
    _app = app


def get_app() -> AppContext:
    if _app is None:
        raise RuntimeError("Compass MCP app context is not initialized")
    return _app
