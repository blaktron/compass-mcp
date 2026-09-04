"""Workflows tools."""

from __future__ import annotations

from typing import Any

from ..convert import humanize_timestamps, maybe_epoch_param
from ..shaping import workflow_summary
from .common import (
    confirmation_gate,
    ensure_writes_enabled,
    fetch,
    paged,
    tool_errors,
)

_CREATABLE_NOTE_TYPES = {"internal", "comment"}


@tool_errors
async def compass_list_workflows(
    cs_status: str | None = None,
    status: str | None = None,
    sub_legal_entity_id: str | None = None,
    prequal_id: str | None = None,
    project_ids: list[str] | None = None,
    analytics_run: bool | None = None,
    submission_expires_after: str | int | None = None,
    submission_expires_before: str | int | None = None,
    on_hold_until_before: str | int | None = None,
    updated_after: str | int | None = None,
    updated_before: str | int | None = None,
    sort_dir: str | None = None,
    limit: int = 50,
    max_pages: int = 5,
) -> dict[str, Any]:
    """List workflows.

    cs_status: in_progress | on_hold | escalated | completed.
    project_ids is sent as a comma-separated query parameter.
    submission_expires_after / submission_expires_before map to inclusive _gte/_lte
    bounds; the other timestamp filters are exclusive. All timestamp parameters
    accept ISO-8601 or epoch seconds. Each result gains a derived `summary` string.
    """
    params = {
        "cs_status": cs_status,
        "status": status,
        "sub_legal_entity_id": sub_legal_entity_id,
        "prequal_id": prequal_id,
        "projects": ",".join(project_ids) if project_ids else None,
        "cs_details_is_analytics_run": analytics_run,
        "cs_details_compass_complete_submission_expiry_date_gte": maybe_epoch_param(
            submission_expires_after
        ),
        "cs_details_compass_complete_submission_expiry_date_lte": maybe_epoch_param(
            submission_expires_before
        ),
        "on_hold_until_lt": maybe_epoch_param(on_hold_until_before),
        "updated_gt": maybe_epoch_param(updated_after),
        "updated_lt": maybe_epoch_param(updated_before),
        "sort_by": "updated" if sort_dir else None,
        "sort_dir": sort_dir,
    }
    result = await paged("/hub/workflows", params, limit, max_pages, humanize=False)
    for wf in result["data"]:
        if isinstance(wf, dict):
            wf["summary"] = workflow_summary(wf)
    return humanize_timestamps(result)


@tool_errors
async def compass_list_workflow_notes(
    workflow_id: str,
    type: str | None = None,
    include_non_shareable: bool = False,
    include_history: bool = False,
    sort_dir: str | None = None,
    limit: int = 50,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Read notes attached to one workflow.

    type is sent un-namespaced and accepts: internal | comment | escalation |
    on_hold | request. The API's shareable filter defaults to true;
    include_non_shareable=true requests the non-shareable subset instead, as the two
    cannot be returned in one call.
    """
    params = {
        "type": type,
        "shareable": False if include_non_shareable else None,
        "current": False if include_history else None,
        "sort_by": "updated" if sort_dir else None,
        "sort_dir": sort_dir,
    }
    return await paged(f"/hub/workflows/{workflow_id}/notes", params, limit, max_pages)


# -- writes ------------------------------------------------------------------


@tool_errors
async def compass_create_workflow(
    sub_legal_entity_id: str,
    project_id: str | None = None,
    deadline: str | int | None = None,
    reason: str | None = None,
    internal_note: str | None = None,
) -> dict[str, Any]:
    """Create a workflow for an existing legal entity.

    deadline accepts ISO-8601 or epoch seconds. reason: new | increase | renewal |
    auto_renewal | referral_link | gc_invited | analytics | compass_suggested |
    sub_requested. There is no idempotency key, so check
    compass_list_workflows(sub_legal_entity_id=...) first to avoid duplicates. Use
    compass_invite_subcontractor when there is no legal entity yet.
    """
    ensure_writes_enabled()
    body = {
        "sub_legal_entity_id": sub_legal_entity_id,
        "project_id": project_id,
        "deadline": maybe_epoch_param(deadline),
        "reason": reason,
        "internal_note": internal_note,
    }
    body = {k: v for k, v in body.items() if v is not None}
    return await fetch("POST", "/hub/workflows", json_body=body)


@tool_errors
async def compass_invite_subcontractor(
    email: str,
    legal_entity_name: str,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    phone_ext: str | None = None,
    project_id: str | None = None,
    deadline: str | int | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Invite a subcontractor that has no legal entity yet.

    HIGH CONSEQUENCE: sends an invitation email to a real third party. Requires
    confirm=true after the user has approved the exact email address and company
    name. email is an email address and legal_entity_name a company name (max 50
    characters, no curly braces). There is no idempotency key, so calling twice may
    email the person twice.
    """
    ensure_writes_enabled()
    gate = confirmation_gate(
        confirm,
        "Create an unclaimed Compass account and send an invitation email",
        {
            "email": email,
            "legal_entity_name": legal_entity_name,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "project_id": project_id,
            "deadline": deadline,
            "warning": "This emails a real person who has not consented to contact from this integration.",
        },
    )
    if gate:
        return gate
    body = {
        "email": email,
        "legal_entity_name": legal_entity_name,
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "phone_ext": phone_ext,
        "project_id": project_id,
        "deadline": maybe_epoch_param(deadline),
    }
    body = {k: v for k, v in body.items() if v is not None}
    return await fetch("POST", "/hub/workflows/invite", json_body=body)


@tool_errors
async def compass_delete_workflow(id: str, confirm: bool = False) -> dict[str, Any]:
    """Delete a workflow.

    Requires confirm=true after the user approves; without it, a confirmation
    preview is returned instead.
    """
    ensure_writes_enabled()
    gate = confirmation_gate(
        confirm,
        "Remove a subcontractor's qualification request from Qualification Management",
        {"workflow_id": id, "warning": "Treat this deletion as irreversible."},
    )
    if gate:
        return gate
    await fetch("DELETE", f"/hub/workflows/{id}")
    return {"deleted": True, "workflow_id": id}


@tool_errors
async def compass_create_workflow_note(
    workflow_id: str,
    content: str,
    type: str = "comment",
    shareable: bool | None = None,
) -> dict[str, Any]:
    """Add a note to a workflow. `type` accepts only 'internal' or 'comment'."""
    ensure_writes_enabled()
    if type not in _CREATABLE_NOTE_TYPES:
        raise ValueError(
            f"Only {sorted(_CREATABLE_NOTE_TYPES)} notes can be created; got {type!r}."
        )
    body: dict[str, Any] = {"content": content, "type": type}
    if shareable is not None:
        body["shareable"] = shareable
    return await fetch("POST", f"/hub/workflows/{workflow_id}/notes", json_body=body)


@tool_errors
async def compass_update_workflow_note(
    workflow_id: str,
    note_id: str,
    content: str,
    shareable: bool | None = None,
) -> dict[str, Any]:
    """Overwrite a workflow note's content, and optionally its shareable flag.

    The type cannot be changed. The API returns 204 with no body, so re-read via
    compass_list_workflow_notes to confirm the result.
    """
    ensure_writes_enabled()
    body: dict[str, Any] = {"content": content}
    if shareable is not None:
        body["shareable"] = shareable
    await fetch("PATCH", f"/hub/workflows/{workflow_id}/notes/{note_id}", json_body=body)
    return {
        "updated": True,
        "workflow_id": workflow_id,
        "note_id": note_id,
        "note": "API returned 204 (no body); re-read the note to see the stored result.",
    }
