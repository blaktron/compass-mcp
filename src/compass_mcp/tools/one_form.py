"""1Form tools."""

from __future__ import annotations

from typing import Any

from ..convert import humanize_timestamps, maybe_epoch_param
from ..shaping import (
    ONE_FORM_SECTIONS,
    one_form_inventory,
    project_one_form,
    slim_one_form_envelope,
)
from .common import paged, tool_errors


@tool_errors
async def compass_poll_one_form(
    legal_entity_id: str | None = None,
    sections: list[str] | None = None,
    summary_only: bool = False,
    updated_after: str | int | None = None,
    updated_before: str | int | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    limit: int = 5,
    max_pages: int = 1,
) -> dict[str, Any]:
    """Poll 1Form submissions, projected to the requested sections.

    Payloads are very large, so pass only the sections you need. Sections:
    company_info, offices, certifications, workforce, legal, projects, financials,
    expertise, safety_personnel, emr, osha_incidents, incidents, convictions,
    hs_programs; the full list is echoed back as `available_sections`. With no
    sections (or summary_only=true) the result carries the envelope plus a
    per-section inventory under `sections_with_data` instead of `data`.
    Timestamp parameters accept ISO-8601 or epoch seconds.
    """
    params = {
        "legal_entity_id": legal_entity_id,
        "updated_gt": maybe_epoch_param(updated_after),
        "updated_lt": maybe_epoch_param(updated_before),
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }
    result = await paged("/compass/one_form/unified/poll", params, limit, max_pages, humanize=False)

    shaped: list[dict[str, Any]] = []
    for record in result["data"]:
        if not isinstance(record, dict):
            continue
        entry = slim_one_form_envelope(record)
        data = record.get("data") or {}
        if summary_only or not sections:
            entry["sections_with_data"] = one_form_inventory(data)
            if not summary_only:
                entry["note"] = "Pass sections=[...] to fetch payload sections."
        else:
            entry["data"] = project_one_form(data, sections)
        shaped.append(entry)

    return humanize_timestamps(
        {
            "count": result["count"],
            "returned": result["returned"],
            "truncated": result["truncated"],
            "next_page": result["next_page"],
            "available_sections": sorted(ONE_FORM_SECTIONS),
            "data": shaped,
        }
    )
