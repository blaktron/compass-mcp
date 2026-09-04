"""Write-tool tests: gating, confirmation, and request shapes."""

from __future__ import annotations

import httpx

from compass_mcp.convert import to_epoch
from compass_mcp.tools.contracts import compass_import_contracts_csv
from compass_mcp.tools.prequalification import compass_create_prequalification
from compass_mcp.tools.tags import (
    compass_assign_tag,
    compass_create_tag,
    compass_delete_tag,
    compass_unassign_tag,
)
from compass_mcp.tools.workflows import (
    compass_create_workflow,
    compass_create_workflow_note,
    compass_invite_subcontractor,
    compass_update_workflow_note,
)

VALID_CSV = (
    "project_internal_id,project_name,contract_code,contract_name,contract_tax_identifier\n"
    "PROJ-1,Alpha,CN1,Concrete,12-3456789\n"
)


async def test_writes_disabled_blocks_everything(app):
    app.config.allow_writes = False
    result = await compass_create_tag("Preferred")
    assert result["error"]["type"] == "WritesDisabledError"
    result = await compass_invite_subcontractor("a@b.c", "Co", confirm=True)
    assert result["error"]["type"] == "WritesDisabledError"


async def test_invite_requires_confirmation_and_makes_no_call(app, api):
    result = await compass_invite_subcontractor("estimating@sub.example", "New Sub Co")
    assert result["confirmation_required"] is True
    assert result["preview"]["email"] == "estimating@sub.example"
    assert "emails a real person" in result["preview"]["warning"]
    assert api.requests == []


async def test_invite_with_confirm_posts_correct_body(app, api):
    api.json("POST", "/hub/workflows/invite", {"id": "wf1", "status": "awaiting_registration"}, status=201)
    result = await compass_invite_subcontractor(
        "estimating@sub.example",
        "New Sub Co",
        first_name="Alex",
        deadline="2026-09-15",
        confirm=True,
    )
    body = api.body_json(api.requests[0])
    assert body["email"] == "estimating@sub.example"
    assert body["legal_entity_name"] == "New Sub Co"
    assert body["deadline"] == to_epoch("2026-09-15")
    assert "phone" not in body
    assert result["id"] == "wf1"


async def test_create_workflow_posts_body(app, api):
    api.json("POST", "/hub/workflows", {"id": "wf2"}, status=201)
    await compass_create_workflow("sub1", reason="new", internal_note="Q3 tender")
    body = api.body_json(api.requests[0])
    assert body == {"sub_legal_entity_id": "sub1", "reason": "new", "internal_note": "Q3 tender"}


async def test_workflow_note_type_restricted(app, api):
    result = await compass_create_workflow_note("wf1", "hello", type="escalation")
    assert result["error"]["type"] == "ValueError"
    assert api.requests == []


async def test_update_note_reports_204_semantics(app, api):
    api.add("PATCH", "/hub/workflows/wf1/notes/n1", lambda r: httpx.Response(204))
    result = await compass_update_workflow_note("wf1", "n1", "new text", shareable=True)
    assert result["updated"] is True
    body = api.body_json(api.requests[0])
    assert body == {"content": "new text", "shareable": True}


async def test_create_prequalification_preview_shows_resulting_status(app, api):
    result = await compass_create_prequalification(
        "sub1",
        qualified=True,
        expires="2030-01-01",
        exceptions="Bonding required",
    )
    assert result["confirmation_required"] is True
    assert result["preview"]["resulting_status"] == "QUALIFIED_WITH_EXCEPTIONS"
    assert api.requests == []


async def test_create_prequalification_confirmed(app, api):
    api.json(
        "POST",
        "/compass/prequalification",
        {"id": "pq1", "qualified": True, "expires": to_epoch("2030-01-01"), "exceptions": ""},
        status=201,
    )
    result = await compass_create_prequalification(
        "sub1",
        qualified=True,
        expires="2030-01-01",
        single_contract_limit=500000,
        currency="usd",
        comment="Approved on 2025 financials",
        confirm=True,
    )
    body = api.body_json(api.requests[0])
    assert body["expires"] == to_epoch("2030-01-01")
    assert body["qualified"] is True
    assert body["comment"] == "Approved on 2025 financials"
    assert result["derived_status"] == "QUALIFIED"
    assert "prequal.comment" in result["note"]


async def test_tag_label_length_enforced(app, api):
    result = await compass_create_tag("x" * 128)
    assert result["error"]["type"] == "ValueError"
    assert api.requests == []


async def test_delete_tag_previews_label_then_deletes(app, api):
    api.json("GET", "/compass/tags/tag1", {"id": "tag1", "label": "Preferred"})
    preview = await compass_delete_tag("tag1")
    assert preview["confirmation_required"] is True
    assert preview["preview"]["label"] == "Preferred"
    assert api.calls("DELETE", "/compass/tags/tag1") == []

    api.add("DELETE", "/compass/tags/tag1", lambda r: httpx.Response(204))
    result = await compass_delete_tag("tag1", confirm=True)
    assert result == {"deleted": True, "tag_id": "tag1"}
    assert len(api.calls("DELETE", "/compass/tags/tag1")) == 1


async def test_assign_and_unassign_use_legal_entity_id(app, api):
    api.json(
        "POST",
        "/compass/tags/assign",
        {"id": "join1", "tag_id": "tag1", "tagged_entity_id": "sub1", "legal_entity_id": "gc1"},
        status=200,
    )
    assigned = await compass_assign_tag("tag1", "sub1")
    assert api.body_json(api.requests[0]) == {"tag_id": "tag1", "tagged_entity_id": "sub1"}
    assert assigned["subcontractor_legal_entity_id"] == "sub1"

    api.add("PATCH", "/compass/tags/tag1/unassign", lambda r: httpx.Response(204))
    result = await compass_unassign_tag("tag1", "sub1")
    assert api.body_json(api.requests[1]) == {"tagged_entity_id": "sub1"}
    assert result["unassigned"] is True


async def test_import_csv_aborts_on_invalid_file(app, api, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("not,the,right,headers\n1,2,3,4\n")
    result = await compass_import_contracts_csv(str(bad), confirm=True)
    assert result["aborted"] is True
    assert api.requests == []


async def test_import_csv_requires_confirmation(app, api, tmp_path):
    path = tmp_path / "ok.csv"
    path.write_text(VALID_CSV)
    result = await compass_import_contracts_csv(str(path))
    assert result["confirmation_required"] is True
    assert result["preview"]["row_count"] == 1
    assert api.requests == []


async def test_import_csv_uploads_with_exact_field_name(app, api, tmp_path):
    path = tmp_path / "ok.csv"
    path.write_text(VALID_CSV)
    api.add("POST", "/compass/contract/csv_import", lambda r: httpx.Response(204))
    result = await compass_import_contracts_csv(str(path), confirm=True)
    assert result["imported"] is True
    request = api.requests[0]
    assert request.headers["Content-Type"].startswith("multipart/form-data")
    assert b'name="data.csv"' in request.content
    assert b"PROJ-1" in request.content
