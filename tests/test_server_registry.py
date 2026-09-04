"""The registered tool surface: counts, names, and safety annotations."""

from __future__ import annotations

import pytest

from compass_mcp.server import EXPECTED_TOOL_COUNT, build_server

DESTRUCTIVE = {"compass_delete_workflow", "compass_delete_tag", "compass_import_contracts_csv"}
WRITES = {
    "compass_create_workflow",
    "compass_invite_subcontractor",
    "compass_delete_workflow",
    "compass_create_workflow_note",
    "compass_update_workflow_note",
    "compass_create_prequalification",
    "compass_create_tag",
    "compass_update_tag",
    "compass_delete_tag",
    "compass_assign_tag",
    "compass_unassign_tag",
    "compass_import_contracts_csv",
}
CONFIRM_GATED = {
    "compass_invite_subcontractor",
    "compass_delete_workflow",
    "compass_create_prequalification",
    "compass_delete_tag",
    "compass_import_contracts_csv",
}


@pytest.fixture
async def tools(app):
    server = build_server(config=app.config, app=app)
    return await server.list_tools()


async def test_tool_count_and_unique_names(tools):
    names = [t.name for t in tools]
    assert len(names) == EXPECTED_TOOL_COUNT == 43
    assert len(set(names)) == len(names)
    assert all(n.startswith("compass_") for n in names)


async def test_reads_are_annotated_read_only(tools):
    for tool in tools:
        if tool.name in WRITES or tool.name == "compass_login":
            assert tool.annotations.read_only_hint is False, tool.name
        else:
            assert tool.annotations.read_only_hint is True, tool.name


async def test_destructive_annotations(tools):
    for tool in tools:
        if tool.name in DESTRUCTIVE:
            assert tool.annotations.destructive_hint is True, tool.name
        elif tool.name in WRITES:
            assert tool.annotations.destructive_hint is False, tool.name


async def test_confirm_gated_writes_expose_confirm_param(tools):
    for tool in tools:
        if tool.name in CONFIRM_GATED:
            assert "confirm" in tool.input_schema.get("properties", {}), tool.name


async def test_required_params(tools):
    by_name = {t.name: t for t in tools}
    assert by_name["compass_poll_approval_flows"].input_schema["required"] == ["flow_type"]
    assert set(by_name["compass_invite_subcontractor"].input_schema["required"]) == {
        "email",
        "legal_entity_name",
    }
    assert "sub_legal_entity_id" in by_name["compass_create_prequalification"].input_schema["required"]
    assert "qualified" in by_name["compass_create_prequalification"].input_schema["required"]
    assert "expires" in by_name["compass_create_prequalification"].input_schema["required"]


async def test_every_tool_has_a_description(tools):
    for tool in tools:
        assert tool.description and len(tool.description) > 40, tool.name
