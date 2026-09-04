"""Read-tool tests against the mock Compass API."""

from __future__ import annotations

import httpx

from compass_mcp.tools.approvals import compass_poll_approval_requests
from compass_mcp.tools.legal_entities import (
    compass_get_legal_entity,
    compass_list_legal_entities,
)
from compass_mcp.tools.locations import compass_get_work_locations
from compass_mcp.tools.offices import compass_get_offices_for_entity, compass_list_offices
from compass_mcp.tools.one_form import compass_poll_one_form
from compass_mcp.tools.projects import compass_resolve_projects
from compass_mcp.tools.reviews import compass_poll_reviews
from compass_mcp.tools.scores import compass_list_scores
from compass_mcp.tools.tags import compass_get_tag_assignments
from compass_mcp.tools.users import compass_get_users
from compass_mcp.tools.workflows import compass_list_workflow_notes, compass_list_workflows

EPOCH = 1671662349  # 2022-12-21T22:39:09Z


async def test_list_legal_entities_converts_iso_and_passes_filters(app, api):
    api.collection("GET", "/hub/legal_entity", [{"id": "le1", "created": EPOCH}])
    result = await compass_list_legal_entities(
        type="sub", status="active", updated_after="2022-12-21T22:39:09Z", limit=10
    )
    request = api.requests[0]
    assert request.url.params["type"] == "sub"
    assert request.url.params["status"] == "active"
    assert request.url.params["updated_gt"] == str(EPOCH)
    assert result["data"][0]["created"] == "2022-12-21T22:39:09Z"


async def test_get_legal_entity_resolves_trade_hierarchy(app, api):
    api.json(
        "GET",
        "/hub/legal_entity/le1",
        {
            "id": "le1",
            "trades": [{"id": "t1", "priority": 1, "children": [{"id": "t2", "priority": 1}]}],
            "naics_codes": [{"id": "n1", "priority": 1}],
        },
    )
    api.json(
        "POST",
        "/hub/trades/retrieval",
        {
            "data": [
                {"id": "t1", "name": "Concrete", "type": "csi_code", "level": 1,
                 "division_1": "03", "division_2": "", "division_3": ""},
                {"id": "t2", "name": "Formwork", "type": "csi_code", "level": 2,
                 "division_1": "03", "division_2": "11", "division_3": ""},
                {"id": "n1", "name": "Lawyers", "type": "naics_code", "level": 4,
                 "division_1": "54", "division_2": "11", "division_3": "1"},
            ]
        },
    )
    result = await compass_get_legal_entity("le1", resolve_trades=True)
    resolved = result["trades_resolved"]
    assert resolved["t2"]["code"] == "0311"
    assert resolved["n1"]["code"] == "54111"
    body = api.body_json(api.calls("POST", "/hub/trades/retrieval")[0])
    assert set(body["id"]) == {"t1", "t2", "n1"}


async def test_offices_purposes_sent_as_repeated_params(app, api):
    api.collection("GET", "/hub/legal_entity/offices/poll", [])
    await compass_list_offices(purposes=["billing", "purchasing"])
    assert api.requests[0].url.params.get_list("purposes") == ["billing", "purchasing"]


async def test_offices_for_entity_warns_on_unreachable_pages(app, api):
    api.json(
        "GET",
        "/hub/legal_entity/le1/offices",
        {"count": 5, "data": [{"id": "o1"}, {"id": "o2"}]},
    )
    result = await compass_get_offices_for_entity("le1")
    assert "unreachable" in result["warning"]


async def test_get_users_caps_batch_size(app):
    result = await compass_get_users([f"u{i}" for i in range(51)])
    assert result["error"]["type"] == "ValueError"


async def test_get_users_resolves_and_caches(app, api):
    api.json("GET", "/hub/users/u1", {"id": "u1", "first_name": "Ada", "last_name": "L", "title": "PM"})
    first = await compass_get_users(["u1"])
    assert first["users"]["u1"]["display_name"] == "Ada L"
    await compass_get_users(["u1"])
    assert len(api.calls("GET", "/hub/users/u1")) == 1


async def test_work_locations_reports_unresolved(app, api):
    api.json(
        "POST",
        "/hub/locations/work_locations/retrieval",
        {"data": [{"id": "w1", "country": "ca", "province": "ON"}]},
    )
    result = await compass_get_work_locations(["w1", "w2"])
    assert result["unresolved"] == ["w2"]
    assert result["resolved"][0]["province"] == "ON"


async def test_scores_grouped_by_trade_with_names(app, api):
    api.collection(
        "GET",
        "/compass/score",
        [
            {"trade_id": "t1", "nationality": "us", "current": True, "q_score": 4.2, "updated": EPOCH},
            {"trade_id": "t1", "nationality": "us", "current": False, "q_score": 3.8, "updated": EPOCH},
            {"trade_id": "t2", "nationality": "us", "current": True, "q_score": 5.1, "updated": EPOCH},
        ],
    )
    api.json(
        "POST",
        "/hub/trades/retrieval",
        {"data": [
            {"id": "t1", "name": "Concrete", "type": "csi_code", "level": 1, "division_1": "03"},
            {"id": "t2", "name": "Electrical", "type": "csi_code", "level": 1, "division_1": "26"},
        ]},
    )
    result = await compass_list_scores(legal_entity_id="le1")
    groups = {g["trade_id"]: g for g in result["score_groups"]}
    assert len(groups) == 2
    assert groups["t1"]["current"]["q_score"] == 4.2
    assert groups["t1"]["history"] == [] and groups["t1"]["history_count"] == 1
    assert groups["t1"]["trade"]["name"] == "Concrete"
    assert "note" not in result


async def test_one_form_inventory_then_sections(app, api):
    record = {
        "id": "s1",
        "legal_entity_id": "le1",
        "year": 2025,
        "submitted": EPOCH,
        "status": "complete",
        "verified": None,
        "data": {
            "legal": {"insolvent_bankruptcy": "option_no"},
            "emr": [{"emr_year": 2024, "emr_value": 0.9}],
        },
    }
    api.collection("GET", "/compass/one_form/unified/poll", [record])

    inventory = await compass_poll_one_form(legal_entity_id="le1")
    entry = inventory["data"][0]
    assert "data" not in entry
    assert entry["sections_with_data"]["legal"] is True
    assert entry["sections_with_data"]["financials"] is False
    assert "status" not in entry and "verified" not in entry
    assert entry["submitted"] == "2022-12-21T22:39:09Z"

    projected = await compass_poll_one_form(legal_entity_id="le1", sections=["legal"])
    entry = projected["data"][0]
    assert entry["data"] == {"legal": {"legal": {"insolvent_bankruptcy": "option_no"}}}

    bad = await compass_poll_one_form(sections=["nope"])
    assert bad["error"]["type"] == "ValueError"


async def test_reviews_flags_and_answer_counts(app, api):
    api.collection(
        "GET",
        "/hub/reviews/gc-sub/poll",
        [
            {
                "legal_entity_id": "gc1",
                "sub_legal_entity_id": "sub1",
                "data": {
                    "scheduling": {"adheres_to_master_schedule": "4"},
                    "quality": {},
                    "internal_info": {
                        "would_recommend_sub": "option_yes",
                        "has_sub_liened_project": "option_no",
                    },
                },
            }
        ],
    )
    result = await compass_poll_reviews(sub_legal_entity_id="sub1")
    submission = result["data"][0]
    assert submission["sections_answered"]["scheduling"] == 1
    assert submission["sections_answered"]["quality"] == 0
    assert submission["flags"]["would_recommend_sub"] == "option_yes"


async def test_approval_requests_annotation_and_people(app, api):
    api.collection(
        "GET",
        "/compass/approval_requests/poll",
        [
            {
                "id": "ar1",
                "status": "in_progress",
                "requested_by": "u9",
                "current_stage": {
                    "complete_requirements": "one_review",
                    "reviewers": ["u1", "u2", "u3", "u4", "u5"],
                    "pending_reviewers": ["u1", "u2", "u3"],
                },
            },
            {"id": "ar2", "status": "awaiting_qualification", "current_stage": None},
        ],
    )
    for uid in ("u1", "u2", "u3", "u4", "u5", "u9"):
        api.json("GET", f"/hub/users/{uid}", {"id": uid, "first_name": uid.upper(), "last_name": "X"})

    result = await compass_poll_approval_requests(statuses=["in_progress", "awaiting_qualification"])
    assert api.requests[0].url.params["status"] == "in_progress,awaiting_qualification"

    first, second = result["data"]
    assert "only one of them needs to" in first["current_stage"]["progress"]
    assert "awaiting" in second["current_stage_note"]
    assert result["people"]["u9"]["display_name"] == "U9 X"


async def test_approval_request_id_miss_notes_ambiguity(app, api):
    api.collection("GET", "/compass/approval_requests/poll", [])
    result = await compass_poll_approval_requests(id="unknown", resolve_reviewer_names=False)
    assert "unknown OR not accessible" in result["note"]


async def test_resolve_projects_uses_cached_index(app, api):
    api.collection(
        "GET",
        "/select/projects/poll",
        [
            {"id": "p1", "internal_id": "PROJ-1", "name": "Alpha"},
            {"id": "p2", "internal_id": "PROJ-2", "name": "Beta"},
        ],
    )
    result = await compass_resolve_projects(ids=["p1"], internal_ids=["PROJ-2", "MISSING"])
    assert result["projects"]["p1"]["name"] == "Alpha"
    assert result["projects"]["PROJ-2"]["name"] == "Beta"
    assert result["unresolved"] == ["MISSING"]
    calls_before = len(api.calls("GET", "/select/projects/poll"))
    await compass_resolve_projects(ids=["p2"])
    assert len(api.calls("GET", "/select/projects/poll")) == calls_before


async def test_tag_assignments_sends_legal_entity_ids_and_renames(app, api):
    api.json(
        "POST",
        "/compass/tags/tagged_entities/retrieval",
        {
            "count": 1,
            "data": [
                {
                    "id": "join1",
                    "tag_id": "tag1",
                    "tagged_entity_id": "sub1",
                    "legal_entity_id": "gc1",
                    "entity_type": "legal_entity",
                    "active": True,
                }
            ],
        },
    )
    result = await compass_get_tag_assignments(["sub1"])
    body = api.body_json(api.requests[0])
    assert body == {"tagged_entity_ids": ["sub1"]}
    record = result["data"][0]
    assert record["assignment_record_id"] == "join1"
    assert record["subcontractor_legal_entity_id"] == "sub1"
    assert record["owning_gc_legal_entity_id"] == "gc1"
    assert "tagged_entity_id" not in record and "legal_entity_id" not in record


async def test_workflows_comma_joined_projects_and_summary(app, api):
    api.collection(
        "GET",
        "/hub/workflows",
        [
            {
                "id": "wf1",
                "sub_legal_entity_id": None,
                "invited_sub_name": "New Sub Co",
                "cs_status": "escalated",
                "review_status": "changes_required",
            }
        ],
    )
    result = await compass_list_workflows(
        project_ids=["p1", "p2"], analytics_run=True, submission_expires_before="2026-01-01"
    )
    params = api.requests[0].url.params
    assert params["projects"] == "p1,p2"
    assert params["cs_details_is_analytics_run"] == "true"
    assert "cs_details_compass_complete_submission_expiry_date_lte" in dict(params)
    assert "ESCALATED" in result["data"][0]["summary"]


async def test_workflow_notes_shareable_toggle(app, api):
    api.collection("GET", "/hub/workflows/wf1/notes", [])
    await compass_list_workflow_notes("wf1")
    assert "shareable" not in dict(api.requests[0].url.params)
    await compass_list_workflow_notes("wf1", include_non_shareable=True)
    assert api.requests[1].url.params["shareable"] == "false"


async def test_api_error_surfaced_as_structured_result(app, api):
    api.add("GET", "/hub/legal_entity", lambda r: httpx.Response(500, text="boom"))
    app.config.max_retries = 0
    result = await compass_list_legal_entities()
    assert result["error"]["status"] == 500
    assert result["error"]["body"] == "boom"
