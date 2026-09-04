"""Shared behavior for all tools: error surfacing, write gating, confirmation,
pagination, and timestamp humanization."""

from __future__ import annotations

import functools
from typing import Any, Awaitable, Callable, TypeVar

from ..convert import humanize_timestamps
from ..errors import (
    CompassApiError,
    ConfigError,
    NotAuthenticatedError,
    WritesDisabledError,
)
from ..runtime import get_app

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def tool_errors(fn: F) -> F:
    """Convert known failures into structured results instead of protocol errors.

    CompassApiError carries the raw status + body verbatim.
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except CompassApiError as exc:
            return exc.to_dict()
        except (NotAuthenticatedError, WritesDisabledError, ConfigError, ValueError) as exc:
            return {"error": {"type": type(exc).__name__, "message": str(exc)}}

    return wrapper  # type: ignore[return-value]


def ensure_writes_enabled() -> None:
    if not get_app().config.allow_writes:
        raise WritesDisabledError()


def confirmation_gate(confirm: bool, action: str, preview: dict[str, Any]) -> dict[str, Any] | None:
    """Per-call human confirmation for high-consequence writes.

    Returns a preview payload when confirmation is still needed; None when the
    call may proceed.
    """
    if confirm:
        return None
    return {
        "confirmation_required": True,
        "action": action,
        "preview": preview,
        "instructions": (
            "Show these exact values to the user and get an explicit approval, "
            "then re-call this tool with confirm=true and identical arguments."
        ),
    }


async def paged(
    path: str,
    params: dict[str, Any],
    limit: int,
    max_pages: int,
    *,
    method: str = "GET",
    json_body: Any = None,
    humanize: bool = True,
) -> dict[str, Any]:
    app = get_app()
    result = await app.client.paginate(
        path, params=params, limit=limit, max_pages=max_pages, method=method, json_body=json_body
    )
    return humanize_timestamps(result) if humanize else result


async def fetch(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    files: Any = None,
    humanize: bool = True,
) -> Any:
    app = get_app()
    result = await app.client.request(
        method, path, params=params, json_body=json_body, files=files
    )
    return humanize_timestamps(result) if humanize and result is not None else result
