"""Tags tools."""

from __future__ import annotations

from typing import Any

from ..convert import humanize_timestamps
from .common import (
    confirmation_gate,
    ensure_writes_enabled,
    fetch,
    tool_errors,
)

MAX_LABEL_LENGTH = 127


def _rename_assignment(record: dict[str, Any]) -> dict[str, Any]:
    """Rename the assignment record's ambiguous id fields."""
    out = dict(record)
    if "id" in out:
        out["assignment_record_id"] = out.pop("id")
    if "tagged_entity_id" in out:
        out["subcontractor_legal_entity_id"] = out.pop("tagged_entity_id")
    if "legal_entity_id" in out:
        out["owning_gc_legal_entity_id"] = out.pop("legal_entity_id")
    return out


@tool_errors
async def compass_list_tags(
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> dict[str, Any]:
    """List all tags for the authenticated caller.

    sort_by: created | updated | label. This endpoint takes no pagination or filter
    parameters; if the response reports more matches than it returned, a `warning`
    key is added to the result.
    """
    resp = await fetch(
        "GET", "/compass/tags", params={"sort_by": sort_by, "sort_dir": sort_dir}, humanize=False
    )
    result = dict(resp or {})
    data = result.get("data") or []
    count = result.get("count")
    if isinstance(count, int) and count > len(data):
        result["warning"] = (
            f"Endpoint reported count={count} but returned {len(data)} tags and has no page "
            f"parameter — the remainder is unreachable via the API."
        )
    return humanize_timestamps(result)


@tool_errors
async def compass_get_tag(id: str) -> dict[str, Any]:
    """Fetch one tag by UUID. Prefer compass_get_tags_bulk when resolving more than one."""
    return await fetch("GET", f"/compass/tags/{id}")


@tool_errors
async def compass_get_tags_bulk(ids: list[str]) -> dict[str, Any]:
    """Resolve several tag UUIDs to their labels and details in one call."""
    resp = await fetch(
        "POST", "/compass/tags/retrieval", json_body={"tag_ids": [str(i) for i in ids]}
    )
    return resp or {}


@tool_errors
async def compass_get_tag_assignments(entity_ids: list[str]) -> dict[str, Any]:
    """Look up tag assignments for one or more companies.

    entity_ids are legal entity UUIDs, sent as `tagged_entity_ids`. Returned records
    have their id fields renamed to assignment_record_id,
    subcontractor_legal_entity_id, and owning_gc_legal_entity_id. Resolve the
    returned tag_ids to labels with compass_get_tags_bulk.
    """
    resp = await fetch(
        "POST",
        "/compass/tags/tagged_entities/retrieval",
        json_body={"tagged_entity_ids": [str(i) for i in entity_ids]},
        humanize=False,
    )
    result = dict(resp or {})
    result["data"] = [
        _rename_assignment(r) if isinstance(r, dict) else r for r in result.get("data") or []
    ]
    return humanize_timestamps(result)


# -- writes ------------------------------------------------------------------


@tool_errors
async def compass_create_tag(label: str) -> dict[str, Any]:
    """Create a tag. `label` must be 1–127 characters."""
    ensure_writes_enabled()
    if not 1 <= len(label) <= MAX_LABEL_LENGTH:
        raise ValueError(f"label must be 1–{MAX_LABEL_LENGTH} characters (got {len(label)}).")
    return await fetch("POST", "/compass/tags", json_body={"label": label})


@tool_errors
async def compass_update_tag(id: str, label: str) -> dict[str, Any]:
    """Rename a tag. `label` must be 1–127 characters; only the label is mutable."""
    ensure_writes_enabled()
    if not 1 <= len(label) <= MAX_LABEL_LENGTH:
        raise ValueError(f"label must be 1–{MAX_LABEL_LENGTH} characters (got {len(label)}).")
    await fetch("PATCH", f"/compass/tags/{id}", json_body={"label": label})
    return {"updated": True, "tag_id": id, "label": label}


@tool_errors
async def compass_delete_tag(id: str, confirm: bool = False) -> dict[str, Any]:
    """Delete a tag.

    Requires confirm=true after the user approves the named tag; without it, a
    confirmation preview carrying the tag's label is returned instead.
    """
    ensure_writes_enabled()
    if not confirm:
        label = None
        try:
            tag = await fetch("GET", f"/compass/tags/{id}", humanize=False)
            label = (tag or {}).get("label")
        except Exception:
            pass
        return confirmation_gate(
            False,
            "Delete a tag and cascade-delete all of its assignments",
            {
                "tag_id": id,
                "label": label,
                "warning": (
                    "Deleting a tag also deletes every assignment of it. The affected "
                    "companies cannot be fully enumerated first, and this is not "
                    "recoverable via the API."
                ),
            },
        )
    await fetch("DELETE", f"/compass/tags/{id}")
    return {"deleted": True, "tag_id": id}


@tool_errors
async def compass_assign_tag(tag_id: str, sub_legal_entity_id: str) -> dict[str, Any]:
    """Assign a tag to a company.

    sub_legal_entity_id is a legal entity UUID, sent as `tagged_entity_id`.
    """
    ensure_writes_enabled()
    resp = await fetch(
        "POST",
        "/compass/tags/assign",
        json_body={"tag_id": tag_id, "tagged_entity_id": sub_legal_entity_id},
        humanize=False,
    )
    return humanize_timestamps(_rename_assignment(resp or {}))


@tool_errors
async def compass_unassign_tag(tag_id: str, sub_legal_entity_id: str) -> dict[str, Any]:
    """Remove a tag from a company.

    sub_legal_entity_id is a legal entity UUID, sent as `tagged_entity_id`.
    """
    ensure_writes_enabled()
    await fetch(
        "PATCH",
        f"/compass/tags/{tag_id}/unassign",
        json_body={"tagged_entity_id": sub_legal_entity_id},
    )
    return {
        "unassigned": True,
        "tag_id": tag_id,
        "subcontractor_legal_entity_id": sub_legal_entity_id,
    }
