import pytest

from compass_mcp.shaping import (
    annotate_approval_stage,
    explain_null_current_stage,
    group_scores,
    one_form_inventory,
    prequalification_derived_status,
    project_one_form,
    slim_one_form_envelope,
    workflow_summary,
)

NOW = 2_000_000_000
PAST = NOW - 1000
FUTURE = NOW + 1000


# -- prequalification status derivation --


def test_expired_beats_denied_and_qualified():
    assert (
        prequalification_derived_status(
            {"qualified": False, "exceptions": "x", "expires": PAST}, now=NOW
        )
        == "EXPIRED"
    )
    assert (
        prequalification_derived_status(
            {"qualified": True, "exceptions": None, "expires": PAST}, now=NOW
        )
        == "EXPIRED"
    )


def test_denied():
    assert (
        prequalification_derived_status(
            {"qualified": False, "exceptions": None, "expires": FUTURE}, now=NOW
        )
        == "DENIED"
    )


def test_qualified_with_exceptions_requires_non_empty_string():
    assert (
        prequalification_derived_status(
            {"qualified": True, "exceptions": "Bonding required", "expires": FUTURE}, now=NOW
        )
        == "QUALIFIED_WITH_EXCEPTIONS"
    )
    for empty in (None, "", "   "):
        assert (
            prequalification_derived_status(
                {"qualified": True, "exceptions": empty, "expires": FUTURE}, now=NOW
            )
            == "QUALIFIED"
        )


def test_missing_qualified_is_unknown():
    assert prequalification_derived_status({"expires": FUTURE}, now=NOW) == "UNKNOWN"


def test_missing_expires_is_not_expired():
    assert prequalification_derived_status({"qualified": True}, now=NOW) == "QUALIFIED"


# -- Q Score grouping --


def test_group_scores_by_trade_and_nationality():
    rows = [
        {"trade_id": "t1", "nationality": "us", "current": True, "q_score": 4.2},
        {"trade_id": "t1", "nationality": "us", "current": False, "q_score": 3.8},
        {"trade_id": "t2", "nationality": "us", "current": True, "q_score": 5.1},
        {"trade_id": "t1", "nationality": "ca", "current": True, "q_score": 2.7},
    ]
    groups = {(g["trade_id"], g["nationality"]): g for g in group_scores(rows)}
    assert len(groups) == 3
    assert groups[("t1", "us")]["current"]["q_score"] == 4.2
    assert [h["q_score"] for h in groups[("t1", "us")]["history"]] == [3.8]
    assert groups[("t2", "us")]["history"] == []


# -- 1Form sectioning --


def test_one_form_inventory_and_projection():
    data = {
        "legal": {"insolvent_bankruptcy": "option_no"},
        "emr": [{"emr_year": 2024}],
        "former_names": [],
        "has_former_name": "",
    }
    inv = one_form_inventory(data)
    assert inv["legal"] is True
    assert inv["emr"] is True
    assert inv["company_info"] is False
    assert inv["financials"] is False

    projected = project_one_form(data, ["legal", "financials"])
    assert projected["legal"] == {"legal": {"insolvent_bankruptcy": "option_no"}}
    assert projected["financials"] == {}
    assert "emr" not in projected


def test_project_one_form_rejects_unknown_section():
    with pytest.raises(ValueError):
        project_one_form({}, ["nonsense"])


def test_slim_envelope_suppresses_deprecated_fields():
    record = {
        "id": "abc",
        "status": "complete",
        "verified": None,
        "flagged_total": None,
        "requested_by_entity_id": None,
        "requested_by_entity_type": None,
        "data": {"legal": {}},
        "year": 2025,
    }
    slim = slim_one_form_envelope(record)
    assert slim == {"id": "abc", "year": 2025}


# -- approvals stage annotation --


def test_one_review_progress_never_reads_as_todo_list():
    stage = {
        "complete_requirements": "one_review",
        "reviewers": ["a", "b", "c", "d", "e"],
        "pending_reviewers": ["a", "b", "c"],
    }
    progress = annotate_approval_stage(stage)["progress"]
    assert "any 1" in progress
    assert "only one of them needs to" in progress


def test_all_reviews_progress():
    stage = {
        "complete_requirements": "all_reviews",
        "reviewers": ["a", "b"],
        "pending_reviewers": ["b"],
    }
    assert "all 2 reviews" in annotate_approval_stage(stage)["progress"]


def test_custom_form_stage_has_no_reviewers_by_design():
    stage = {"complete_requirements": "custom_form", "reviewers": []}
    assert "no reviewers by design" in annotate_approval_stage(stage)["progress"]


def test_sub_flow_union_warning_and_recursion():
    stage = {
        "complete_requirements": "sub_flow",
        "reviewers": ["a", "b"],
        "pending_reviewers": ["a"],
        "sub_flows": [
            {
                "review_type": "finance",
                "current_stage": {
                    "complete_requirements": "one_review",
                    "reviewers": ["a"],
                    "pending_reviewers": ["a"],
                },
            }
        ],
    }
    out = annotate_approval_stage(stage)
    assert "union" in out["progress"]
    assert "progress" in out["sub_flows"][0]["current_stage"]


def test_groups_recursion():
    stage = {
        "complete_requirements": "all_groups",
        "groups": [
            {"complete_requirements": "one_review", "reviewers": ["x"], "pending_reviewers": []}
        ],
    }
    out = annotate_approval_stage(stage)
    assert "each group" in out["progress"]
    assert "progress" in out["groups"][0]


def test_explain_null_current_stage():
    assert "awaiting" in explain_null_current_stage("awaiting_qualification")
    assert "complete" in explain_null_current_stage("complete")
    assert explain_null_current_stage("in_progress")


# -- workflow summary --


def test_workflow_summary_escalated_with_override():
    wf = {
        "sub_legal_entity_id": None,
        "invited_sub_name": "New Sub Co",
        "review_status": "changes_required",
        "cs_status": "escalated",
        "review_status_override": True,
    }
    summary = workflow_summary(wf)
    assert "New Sub Co" in summary
    assert "ESCALATED" in summary
    assert "automated stage changes are OFF" in summary
