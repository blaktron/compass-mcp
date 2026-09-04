"""Legal Entity tools."""

from __future__ import annotations

from typing import Any

from ..convert import humanize_timestamps, maybe_epoch_param
from ..runtime import get_app
from .common import fetch, paged, tool_errors


def _collect_trade_ids(node: Any) -> list[str]:
    ids: list[str] = []
    if isinstance(node, list):
        for item in node:
            ids.extend(_collect_trade_ids(item))
    elif isinstance(node, dict):
        if node.get("id"):
            ids.append(str(node["id"]))
        ids.extend(_collect_trade_ids(node.get("children") or []))
    return ids


@tool_errors
async def compass_list_legal_entities(
    name: str | None = None,
    type: str | None = None,
    status: str | None = None,
    nationality: str | None = None,
    gst_number: str | None = None,
    id: str | None = None,
    active: bool | None = None,
    updated_after: str | int | None = None,
    updated_before: str | int | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    limit: int = 50,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Search legal entities (companies) by name, type, status, nationality, or tax ID.

    type: gc | sub | supplier | sub_supplier | insurance.
    status: active | inactive | unclaimed.
    nationality: country ISO code.
    sort_by: created | updated | display_name.
    Timestamp parameters accept ISO-8601 or epoch seconds.
    """
    params = {
        "name": name,
        "type": type,
        "status": status,
        "nationality": nationality,
        "gst_number": gst_number,
        "id": id,
        "active": active,
        "updated_gt": maybe_epoch_param(updated_after),
        "updated_lt": maybe_epoch_param(updated_before),
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }
    return await paged("/hub/legal_entity", params, limit, max_pages)


@tool_errors
async def compass_get_legal_entity(
    id: str,
    resolve_trades: bool = False,
    resolve_work_locations: bool = False,
) -> dict[str, Any]:
    """Fetch one legal entity (company) by UUID.

    resolve_trades=true additionally resolves the trade/NAICS UUID hierarchies to
    names and codes. resolve_work_locations=true additionally resolves work-location
    UUIDs. Each adds one request.
    """
    app = get_app()
    entity = await fetch("GET", f"/hub/legal_entity/{id}", humanize=False)
    result: dict[str, Any] = dict(entity or {})
    if resolve_trades:
        trade_ids = _collect_trade_ids(result.get("trades")) + _collect_trade_ids(
            result.get("naics_codes")
        )
        if trade_ids:
            result["trades_resolved"] = await app.trades.resolve(trade_ids)
    if resolve_work_locations:
        location_ids = [str(x) for x in (result.get("work_locations") or [])]
        if location_ids:
            resp = await app.client.request(
                "POST",
                "/hub/locations/work_locations/retrieval",
                json_body={"id": location_ids},
            )
            resolved = (resp or {}).get("data") or []
            result["work_locations_resolved"] = resolved
            returned_ids = {str(loc.get("id")) for loc in resolved}
            missing = [i for i in location_ids if i not in returned_ids]
            if missing:
                result["work_locations_unresolved"] = missing
    return humanize_timestamps(result)


@tool_errors
async def compass_list_legal_entity_notes(
    sub_legal_entity_id: str | None = None,
    limit: int = 50,
    max_pages: int = 5,
) -> dict[str, Any]:
    """List public notes on a legal entity.

    sub_legal_entity_id is sent as the `child_id` query parameter.
    """
    params = {"child_id": sub_legal_entity_id}
    return await paged("/hub/legal_entity/notes/public", params, limit, max_pages)
