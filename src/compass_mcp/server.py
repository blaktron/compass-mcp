"""MCP server assembly.

Reads are annotated read-only; deletes and the CSV import are annotated
destructive. All writes additionally require COMPASS_ALLOW_WRITES=true at
runtime, and the high-consequence writes require per-call confirm=true.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import __version__
from .config import Config
from .runtime import AppContext, create_app, set_app
from .tools import (
    approvals,
    auth_tools,
    contracts,
    legal_entities,
    locations,
    offices,
    one_form,
    prequalification,
    projects,
    reviews,
    scores,
    tags,
    trades,
    users,
    workflows,
)

INSTRUCTIONS = """Tools for the COMPASS (Bespoke Metrics) API.

Most tools take a legal_entity_id; resolve one from a company name with
compass_list_legal_entities. Resolve user UUIDs with compass_get_user or
compass_get_users, and project UUIDs or internal project codes with
compass_resolve_projects.

Write tools are disabled unless the server was started with
COMPASS_ALLOW_WRITES=true, and the high-consequence ones (prequalification create,
new-sub invite, workflow delete, tag delete, CSV import) additionally require
confirm=true after explicit human approval.
"""

_REMOTE_READS = [
    legal_entities.compass_list_legal_entities,
    legal_entities.compass_get_legal_entity,
    legal_entities.compass_list_legal_entity_notes,
    offices.compass_list_offices,
    offices.compass_get_offices_for_entity,
    offices.compass_list_inactive_offices,
    users.compass_get_user,
    users.compass_get_users,
    users.compass_poll_office_main_contacts,
    locations.compass_get_work_locations,
    trades.compass_list_trades,
    trades.compass_get_trade,
    trades.compass_get_trades_bulk,
    workflows.compass_list_workflows,
    workflows.compass_list_workflow_notes,
    prequalification.compass_list_prequalifications,
    prequalification.compass_list_prequalification_notes,
    scores.compass_list_scores,
    tags.compass_list_tags,
    tags.compass_get_tag,
    tags.compass_get_tags_bulk,
    tags.compass_get_tag_assignments,
    one_form.compass_poll_one_form,
    reviews.compass_poll_reviews,
    projects.compass_poll_projects,
    projects.compass_resolve_projects,
    approvals.compass_poll_approval_requests,
    approvals.compass_poll_approval_flows,
]

_LOCAL_READS = [
    contracts.compass_validate_contracts_csv,
    auth_tools.compass_auth_status,
]

# (function, destructive, idempotent)
_WRITES = [
    (workflows.compass_create_workflow, False, False),
    (workflows.compass_invite_subcontractor, False, False),
    (workflows.compass_delete_workflow, True, True),
    (workflows.compass_create_workflow_note, False, False),
    (workflows.compass_update_workflow_note, False, True),
    (prequalification.compass_create_prequalification, False, False),
    (tags.compass_create_tag, False, False),
    (tags.compass_update_tag, False, True),
    (tags.compass_delete_tag, True, True),
    (tags.compass_assign_tag, False, True),
    (tags.compass_unassign_tag, False, True),
    (contracts.compass_import_contracts_csv, True, False),
]

_AUTH_ACTIONS = [auth_tools.compass_login]

EXPECTED_TOOL_COUNT = (
    len(_REMOTE_READS) + len(_LOCAL_READS) + len(_WRITES) + len(_AUTH_ACTIONS)
)


def build_server(config: Config | None = None, app: AppContext | None = None) -> MCPServer:
    if config is None:
        config = Config.from_env()
    if app is None:
        app = create_app(config)
    set_app(app)

    server = MCPServer(
        name="compass",
        instructions=INSTRUCTIONS,
        version=__version__,
    )
    for fn in _REMOTE_READS:
        server.add_tool(
            fn, annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True)
        )
    for fn in _LOCAL_READS:
        server.add_tool(
            fn, annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False)
        )
    for fn, destructive, idempotent in _WRITES:
        server.add_tool(
            fn,
            annotations=ToolAnnotations(
                read_only_hint=False,
                destructive_hint=destructive,
                idempotent_hint=idempotent,
                open_world_hint=True,
            ),
        )
    for fn in _AUTH_ACTIONS:
        server.add_tool(
            fn,
            annotations=ToolAnnotations(
                read_only_hint=False, destructive_hint=False, open_world_hint=False
            ),
        )
    return server
