"""Offices tools."""

from __future__ import annotations

from typing import Any

from ..convert import humanize_timestamps, maybe_epoch_param
from .common import fetch, paged, tool_errors


@tool_errors
async def compass_list_offices(
    name: str | None = None,
    primary: bool | None = None,
    purposes: list[str] | None = None,
    user_id: str | None = None,
    location_id: str | None = None,
    updated_after: str | int | None = None,
    updated_before: str | int | None = None,
    sort_dir: str | None = None,
    limit: int = 50,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Poll active offices.

    purposes: billing and/or purchasing; multiple values are sent as repeated query
    parameters. Timestamp parameters accept ISO-8601 or epoch seconds.
    """
    params = {
        "name": name,
        "primary": primary,
        "purposes": purposes,
        "user_id": user_id,
        "location_id": location_id,
        "updated_gt": maybe_epoch_param(updated_after),
        "updated_lt": maybe_epoch_param(updated_before),
        "sort_by": "updated" if sort_dir else None,
        "sort_dir": sort_dir,
    }
    return await paged("/hub/legal_entity/offices/poll", params, limit, max_pages)


@tool_errors
async def compass_get_offices_for_entity(legal_entity_id: str) -> dict[str, Any]:
    """List all offices belonging to one legal entity.

    This endpoint takes no pagination parameters; if the response reports more
    matches than it returned, a `warning` key is added to the result.
    """
    resp = await fetch("GET", f"/hub/legal_entity/{legal_entity_id}/offices", humanize=False)
    result = dict(resp or {})
    data = result.get("data") or []
    count = result.get("count")
    if isinstance(count, int) and count > len(data):
        result["warning"] = (
            f"Endpoint reported count={count} but returned {len(data)} offices and has no "
            f"page parameter — the remainder is unreachable via the API."
        )
    return humanize_timestamps(result)


@tool_errors
async def compass_list_inactive_offices(
    updated_after: str | int | None = None,
    updated_before: str | int | None = None,
    limit: int = 50,
    max_pages: int = 5,
) -> dict[str, Any]:
    """List deactivated offices.

    Timestamp parameters accept ISO-8601 or epoch seconds.
    """
    params = {
        "updated_gt": maybe_epoch_param(updated_after),
        "updated_lt": maybe_epoch_param(updated_before),
    }
    return await paged("/hub/legal_entity/offices/inactive/poll", params, limit, max_pages)
