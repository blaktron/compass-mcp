"""Projects tools."""

from __future__ import annotations

from typing import Any

from ..convert import humanize_timestamps, maybe_epoch_param
from ..runtime import get_app
from .common import paged, tool_errors


@tool_errors
async def compass_poll_projects(
    archived: bool | None = None,
    legal_entity_id: str | None = None,
    updated_after: str | int | None = None,
    updated_before: str | int | None = None,
    sort_dir: str | None = None,
    limit: int = 50,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Poll projects.

    `archived` and the timestamp bounds are the only server-side filters; anything
    else must be filtered client-side. Timestamp parameters accept ISO-8601 or epoch
    seconds.
    """
    params = {
        "archived": archived,
        "legal_entity_id": legal_entity_id,
        "updated_gt": maybe_epoch_param(updated_after),
        "updated_lt": maybe_epoch_param(updated_before),
        "sort_by": "updated" if sort_dir else None,
        "sort_dir": sort_dir,
    }
    return await paged("/select/projects/poll", params, limit, max_pages)


@tool_errors
async def compass_resolve_projects(
    ids: list[str] | None = None,
    internal_ids: list[str] | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Resolve project UUIDs and/or internal project codes to project details.

    Served from a short-TTL index built from the full project list;
    force_refresh=true rebuilds it. Provide ids and/or internal_ids.
    """
    if not ids and not internal_ids:
        raise ValueError("Provide ids and/or internal_ids.")
    result = await get_app().projects.resolve(
        ids=ids, internal_ids=internal_ids, force_refresh=force_refresh
    )
    return humanize_timestamps(result)
