"""Approvals tools."""

from __future__ import annotations

from typing import Any

from ..convert import humanize_timestamps, maybe_epoch_param
from ..runtime import get_app
from ..shaping import annotate_approval_stage, explain_null_current_stage
from .common import paged, tool_errors


def _stage_people(stage: Any) -> set[str]:
    people: set[str] = set()
    if not isinstance(stage, dict):
        return people
    for key in ("reviewers", "pending_reviewers"):
        for uid in stage.get(key) or []:
            people.add(str(uid))
    for group in stage.get("groups") or []:
        people |= _stage_people(group)
    for track in stage.get("sub_flows") or []:
        if isinstance(track, dict):
            people |= _stage_people(track.get("current_stage"))
            for sub_stage in track.get("stages") or []:
                people |= _stage_people(sub_stage)
    return people


@tool_errors
async def compass_poll_approval_requests(
    id: str | None = None,
    flow_type: str | None = None,
    statuses: list[str] | None = None,
    outcomes: list[str] | None = None,
    approval_flow_id: str | None = None,
    sub_legal_entity_id: str | None = None,
    project_id: str | None = None,
    legal_entity_id: str | None = None,
    resolve_reviewer_names: bool = True,
    updated_after: str | int | None = None,
    updated_before: str | int | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    limit: int = 50,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Poll approval requests.

    statuses: awaiting_qualification | in_progress | compass | changes_required |
    complete | cancelled. outcomes: approved | qualified | qualified_with_exceptions |
    denied | push_back | submitted. Both are sent as comma-separated query
    parameters. flow_type: project | company. sort_by: created | updated.

    current_stage is annotated with a derived `progress` string; when it is null a
    `current_stage_note` is added instead. resolve_reviewer_names=true attaches a
    `people` map (uuid -> user) for every reviewer and requester, via cached user
    lookups. Timestamp parameters accept ISO-8601 or epoch seconds.
    """
    params = {
        "id": id,
        "flow_type": flow_type,
        "status": ",".join(statuses) if statuses else None,
        "outcome": ",".join(outcomes) if outcomes else None,
        "approval_flow_id": approval_flow_id,
        "sub_legal_entity_id": sub_legal_entity_id,
        "project_id": project_id,
        "legal_entity_id": legal_entity_id,
        "updated_gt": maybe_epoch_param(updated_after),
        "updated_lt": maybe_epoch_param(updated_before),
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }
    result = await paged("/compass/approval_requests/poll", params, limit, max_pages, humanize=False)

    people_ids: set[str] = set()
    for request in result["data"]:
        if not isinstance(request, dict):
            continue
        if request.get("requested_by"):
            people_ids.add(str(request["requested_by"]))
        stage = request.get("current_stage")
        people_ids |= _stage_people(stage)
        if stage:
            request["current_stage"] = annotate_approval_stage(stage)
        else:
            request["current_stage_note"] = explain_null_current_stage(request.get("status"))

    if id is not None and not result["data"]:
        result["note"] = (
            "Empty result for an id lookup means the request is unknown OR not accessible "
            "to this caller — the API does not distinguish (no 404)."
        )
    if resolve_reviewer_names and people_ids:
        result["people"] = await get_app().users.resolve(sorted(people_ids))
    return humanize_timestamps(result)


@tool_errors
async def compass_poll_approval_flows(
    flow_type: str,
    id: str | None = None,
    legal_entity_id: str | None = None,
    is_archived: bool | None = None,
    resolve_reviewer_names: bool = False,
    updated_after: str | int | None = None,
    updated_before: str | int | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    limit: int = 50,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Poll approval flow definitions with their ordered stages, groups, and sub-flows.

    flow_type is required by the API and accepts 'project' or 'company'; call once
    per value to cover both. Each stage is annotated with a derived `progress`
    string. sort_by: name | created | updated. resolve_reviewer_names=true attaches a
    `people` map (uuid -> user). Timestamp parameters accept ISO-8601 or epoch seconds.
    """
    params = {
        "flow_type": flow_type,
        "id": id,
        "legal_entity_id": legal_entity_id,
        "is_archived": is_archived,
        "updated_gt": maybe_epoch_param(updated_after),
        "updated_lt": maybe_epoch_param(updated_before),
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }
    result = await paged("/compass/approval_flows/poll", params, limit, max_pages, humanize=False)

    people_ids: set[str] = set()
    for flow in result["data"]:
        if not isinstance(flow, dict):
            continue
        stages = flow.get("stages")
        if isinstance(stages, list):
            flow["stages"] = [annotate_approval_stage(s) for s in stages]
            for stage in stages:
                people_ids |= _stage_people(stage)

    if resolve_reviewer_names and people_ids:
        result["people"] = await get_app().users.resolve(sorted(people_ids))
    return humanize_timestamps(result)
