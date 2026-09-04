"""Locations tools."""

from __future__ import annotations

from typing import Any

from ..convert import humanize_timestamps
from ..runtime import get_app
from .common import tool_errors

_CHUNK = 100


@tool_errors
async def compass_get_work_locations(ids: list[str]) -> dict[str, Any]:
    """Resolve work-location UUIDs from a legal entity's `work_locations` field.

    Requests are chunked; UUIDs the API does not return are listed under
    `unresolved`.
    """
    app = get_app()
    wanted = [str(i) for i in dict.fromkeys(ids)]
    resolved: list[dict[str, Any]] = []
    for start in range(0, len(wanted), _CHUNK):
        chunk = wanted[start : start + _CHUNK]
        resp = await app.client.request(
            "POST", "/hub/locations/work_locations/retrieval", json_body={"id": chunk}
        )
        resolved.extend((resp or {}).get("data") or [])
    returned = {str(loc.get("id")) for loc in resolved}
    unresolved = [i for i in wanted if i not in returned]
    return humanize_timestamps(
        {
            "requested": len(wanted),
            "resolved": resolved,
            "unresolved": unresolved,
        }
    )
