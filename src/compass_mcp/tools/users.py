"""Users tools."""

from __future__ import annotations

from typing import Any

from ..convert import maybe_epoch_param
from ..runtime import get_app
from .common import fetch, paged, tool_errors

MAX_BULK_USERS = 50


@tool_errors
async def compass_get_user(id: str) -> dict[str, Any]:
    """Fetch one user by UUID. Prefer compass_get_users when resolving more than one."""
    return await fetch("GET", f"/hub/users/{id}")


@tool_errors
async def compass_get_users(ids: list[str]) -> dict[str, Any]:
    """Resolve several user UUIDs in one call (max 50).

    Fans out to GET /hub/users/{id} with bounded concurrency and caches results.
    Prefer this over repeated compass_get_user calls.
    """
    if len(ids) > MAX_BULK_USERS:
        raise ValueError(f"At most {MAX_BULK_USERS} user ids per call (got {len(ids)}).")
    users = await get_app().users.resolve(ids)
    return {"users": users}


@tool_errors
async def compass_poll_office_main_contacts(
    changed_after: str | int | None = None,
    changed_before: str | int | None = None,
    sort_dir: str | None = None,
    limit: int = 50,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Poll office main contacts.

    changed_after / changed_before filter on the office's `main_contact_updated`
    timestamp, not on the user record's own `updated` time. Accepts ISO-8601 or
    epoch seconds.
    """
    params = {
        "main_contact_updated_gt": maybe_epoch_param(changed_after),
        "main_contact_updated_lt": maybe_epoch_param(changed_before),
        "sort_by": "updated" if sort_dir else None,
        "sort_dir": sort_dir,
    }
    return await paged("/hub/users/offices/main_contact/poll", params, limit, max_pages)
