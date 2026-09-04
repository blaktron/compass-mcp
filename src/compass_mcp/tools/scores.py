"""Score tools."""

from __future__ import annotations

from typing import Any

from ..convert import humanize_timestamps, maybe_epoch_param
from ..runtime import get_app
from ..shaping import group_scores
from .common import paged, tool_errors


@tool_errors
async def compass_list_scores(
    legal_entity_id: str | None = None,
    nationality: str | None = None,
    include_history: bool = False,
    resolve_trade_names: bool = True,
    updated_after: str | int | None = None,
    updated_before: str | int | None = None,
    sort_dir: str | None = None,
    limit: int = 50,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Call GET /compass/score and group the rows it returns.

    Rows are grouped into `score_groups`, one entry per (trade_id, nationality),
    each with `current` and `history`. The API has no server-side current filter,
    so history is separated client-side: include_history=true returns the history
    rows, otherwise only `history_count`. resolve_trade_names=true adds a resolved
    `trade` object to each group. Timestamp parameters accept ISO-8601 or epoch
    seconds.
    """
    params = {
        "legal_entity_id": legal_entity_id,
        "nationality": nationality,
        "updated_gt": maybe_epoch_param(updated_after),
        "updated_lt": maybe_epoch_param(updated_before),
        "sort_by": "updated" if sort_dir else None,
        "sort_dir": sort_dir,
    }
    result = await paged("/compass/score", params, limit, max_pages, humanize=False)
    groups = group_scores([s for s in result["data"] if isinstance(s, dict)])
    for group in groups:
        group["history_count"] = len(group["history"])
        if not include_history:
            group["history"] = []
    if resolve_trade_names:
        trade_ids = [g["trade_id"] for g in groups if g.get("trade_id")]
        if trade_ids:
            resolved = await get_app().trades.resolve(trade_ids)
            for group in groups:
                if group.get("trade_id"):
                    group["trade"] = resolved.get(str(group["trade_id"]))
    return humanize_timestamps(
        {
            "count": result["count"],
            "returned": result["returned"],
            "truncated": result["truncated"],
            "next_page": result["next_page"],
            "score_groups": groups,
        }
    )
