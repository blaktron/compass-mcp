"""Reviews tools."""

from __future__ import annotations

from typing import Any

from ..convert import humanize_timestamps, maybe_epoch_param
from .common import paged, tool_errors

_RATED_SECTIONS = ["scheduling", "cost_change_mgmt", "quality", "relationships", "health_safety_env"]


@tool_errors
async def compass_poll_reviews(
    sub_legal_entity_id: str | None = None,
    legal_entity_id: str | None = None,
    updated_after: str | int | None = None,
    updated_before: str | int | None = None,
    sort_dir: str | None = None,
    limit: int = 25,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Poll GC-to-subcontractor reviews.

    Each returned submission gains `sections_answered` (answer counts for
    scheduling, cost_change_mgmt, quality, relationships, health_safety_env) and
    `flags` (would_recommend_sub, has_sub_liened_project) lifted from
    data.internal_info. Timestamp parameters accept ISO-8601 or epoch seconds.
    """
    params = {
        "sub_legal_entity_id": sub_legal_entity_id,
        "legal_entity_id": legal_entity_id,
        "updated_gt": maybe_epoch_param(updated_after),
        "updated_lt": maybe_epoch_param(updated_before),
        "sort_by": "updated" if sort_dir else None,
        "sort_dir": sort_dir,
    }
    result = await paged("/hub/reviews/gc-sub/poll", params, limit, max_pages, humanize=False)
    for submission in result["data"]:
        if not isinstance(submission, dict):
            continue
        data = submission.get("data") or {}
        submission["sections_answered"] = {
            section: len(data.get(section) or {}) for section in _RATED_SECTIONS
        }
        internal = data.get("internal_info") or {}
        submission["flags"] = {
            "would_recommend_sub": internal.get("would_recommend_sub"),
            "has_sub_liened_project": internal.get("has_sub_liened_project"),
        }
    return humanize_timestamps(result)
