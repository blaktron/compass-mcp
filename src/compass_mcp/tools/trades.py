"""Trades tools."""

from __future__ import annotations

from typing import Any

from ..runtime import get_app
from .common import fetch, paged, tool_errors


@tool_errors
async def compass_list_trades(
    taxonomy: str | None = None,
    name: str | None = None,
    division_1: str | None = None,
    division_2: str | None = None,
    division_3: str | None = None,
    division_4: str | None = None,
    division_5: str | None = None,
    limit: int = 50,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Search the trade taxonomy.

    taxonomy: csi_code (default) or naics_code. Search by name, or filter by
    division_1..division_5 code segments. The full code is division_1..5 concatenated.
    """
    params = {
        "type": taxonomy,
        "name": name,
        "division_1": division_1,
        "division_2": division_2,
        "division_3": division_3,
        "division_4": division_4,
        "division_5": division_5,
    }
    return await paged("/hub/trades", params, limit, max_pages)


@tool_errors
async def compass_get_trade(id: str) -> dict[str, Any]:
    """Fetch one trade or NAICS code by UUID. Prefer compass_get_trades_bulk for >1."""
    return await fetch("GET", f"/hub/trades/{id}")


@tool_errors
async def compass_get_trades_bulk(ids: list[str]) -> dict[str, Any]:
    """Resolve trade/NAICS UUIDs to names and full codes in one call (cached).

    Each result includes `code` = the concatenated division segments.
    """
    trades = await get_app().trades.resolve(ids)
    return {"trades": trades}
