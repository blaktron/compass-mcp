"""Prequalification tools."""

from __future__ import annotations

from typing import Any

from ..convert import epoch_to_iso, humanize_timestamps, maybe_epoch_param
from ..shaping import prequalification_derived_status
from .common import (
    confirmation_gate,
    ensure_writes_enabled,
    fetch,
    paged,
    tool_errors,
)


@tool_errors
async def compass_list_prequalifications(
    sub_legal_entity_id: str | None = None,
    gc_legal_entity_id: str | None = None,
    qualified: bool | None = None,
    prequal_review: str | None = None,
    created_by: str | None = None,
    include_history: bool = False,
    expires_after: str | int | None = None,
    expires_before: str | int | None = None,
    created_after: str | int | None = None,
    created_before: str | int | None = None,
    updated_after: str | int | None = None,
    updated_before: str | int | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    limit: int = 50,
    max_pages: int = 5,
) -> dict[str, Any]:
    """List prequalification records.

    Every record gains a computed `derived_status`: EXPIRED | DENIED |
    QUALIFIED_WITH_EXCEPTIONS | QUALIFIED | UNKNOWN. Defaults to current records
    only; include_history=true also returns superseded revisions.
    prequal_review: approved | pending | refused. sort_by: created | updated |
    expires. Timestamp parameters accept ISO-8601 or epoch seconds.
    """
    params = {
        "sub_legal_entity_id": sub_legal_entity_id,
        "gc_legal_entity_id": gc_legal_entity_id,
        "qualified": qualified,
        "prequal_review": prequal_review,
        "created_by": created_by,
        "current": None if include_history else True,
        "expiry_gt": maybe_epoch_param(expires_after),
        "expiry_lt": maybe_epoch_param(expires_before),
        "created_gt": maybe_epoch_param(created_after),
        "created_lt": maybe_epoch_param(created_before),
        "updated_gt": maybe_epoch_param(updated_after),
        "updated_lt": maybe_epoch_param(updated_before),
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }
    result = await paged("/compass/prequalification", params, limit, max_pages, humanize=False)
    for record in result["data"]:
        if isinstance(record, dict):
            record["derived_status"] = prequalification_derived_status(record)
    return humanize_timestamps(result)


@tool_errors
async def compass_list_prequalification_notes(
    prequalification_id: str,
    type: str | None = None,
    include_history: bool = False,
    limit: int = 50,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Read notes on one prequalification record.

    type accepts 'comment' or 'feedback'. include_history=true also returns
    superseded revisions.
    """
    params = {"type": type, "current": False if include_history else None}
    return await paged(
        f"/compass/prequalification/{prequalification_id}/notes", params, limit, max_pages
    )


@tool_errors
async def compass_create_prequalification(
    sub_legal_entity_id: str,
    qualified: bool,
    expires: str | int,
    single_contract_limit: float | None = None,
    aggregate_contract_limit: float | None = None,
    currency: str | None = None,
    exceptions: str | None = None,
    comment: str | None = None,
    prequal_review: str | None = None,
    remove_from_hotlist: bool | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Create a prequalification record.

    HIGH CONSEQUENCE: requires confirm=true after the user approves every value;
    without it, a confirmation preview carrying the resulting derived status is
    returned instead. prequal_review accepts approved | refused. expires accepts
    ISO-8601 or epoch seconds. Omitted optional fields are not sent. The API only
    requires sub_legal_entity_id, but this tool also requires `qualified` and
    `expires` so that the derived status is never ambiguous.
    """
    ensure_writes_enabled()
    expires_epoch = maybe_epoch_param(expires)
    preview_record = {"qualified": qualified, "exceptions": exceptions, "expires": expires_epoch}
    gate = confirmation_gate(
        confirm,
        "Assign a prequalification (contract limits) to a subcontractor",
        {
            "sub_legal_entity_id": sub_legal_entity_id,
            "qualified": qualified,
            "single_contract_limit": single_contract_limit,
            "aggregate_contract_limit": aggregate_contract_limit,
            "currency": currency,
            "expires": epoch_to_iso(expires_epoch) if expires_epoch else None,
            "exceptions": exceptions,
            "comment": comment,
            "prequal_review": prequal_review,
            "remove_from_hotlist": remove_from_hotlist,
            "resulting_status": prequalification_derived_status(preview_record),
            "warning": (
                "This sets the subcontractor's contract limits with the GC. "
                "remove_from_hotlist=true additionally closes their open qualification requests."
            ),
        },
    )
    if gate:
        return gate
    body = {
        "sub_legal_entity_id": sub_legal_entity_id,
        "qualified": qualified,
        "expires": expires_epoch,
        "single_contract_limit": single_contract_limit,
        "aggregate_contract_limit": aggregate_contract_limit,
        "currency": currency,
        "exceptions": exceptions,
        "comment": comment,
        "prequal_review": prequal_review,
        "remove_from_hotlist": remove_from_hotlist,
    }
    body = {k: v for k, v in body.items() if v is not None}
    created = await fetch("POST", "/compass/prequalification", json_body=body, humanize=False)
    if isinstance(created, dict):
        created["derived_status"] = prequalification_derived_status(created)
        created["note"] = (
            "The `comment` (if any) was stored as a prequal.comment note and is not part "
            "of this object — read it via compass_list_prequalification_notes."
        )
    return humanize_timestamps(created)
