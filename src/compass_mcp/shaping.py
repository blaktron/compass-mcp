"""Response shaping helpers."""

from __future__ import annotations

import time
from typing import Any


def prequalification_derived_status(record: dict[str, Any], now: float | None = None) -> str:
    """Derive a status string from a prequalification record."""
    now = time.time() if now is None else now
    expires = record.get("expires")
    if isinstance(expires, (int, float)) and not isinstance(expires, bool) and expires < now:
        return "EXPIRED"
    qualified = record.get("qualified")
    if qualified is False:
        return "DENIED"
    if qualified is True:
        exceptions = record.get("exceptions")
        if isinstance(exceptions, str) and exceptions.strip():
            return "QUALIFIED_WITH_EXCEPTIONS"
        return "QUALIFIED"
    return "UNKNOWN"


def group_scores(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group score rows by (trade_id, nationality) into `current` and `history`."""
    groups: dict[tuple[Any, Any], dict[str, Any]] = {}
    for score in scores:
        key = (score.get("trade_id"), score.get("nationality"))
        group = groups.setdefault(
            key,
            {
                "trade_id": score.get("trade_id"),
                "nationality": score.get("nationality"),
                "current": None,
                "history": [],
            },
        )
        if score.get("current") is True and group["current"] is None:
            group["current"] = score
        else:
            group["history"].append(score)
    return list(groups.values())


ONE_FORM_SECTIONS: dict[str, list[str]] = {
    "company_info": ["company_information", "has_former_name", "former_names"],
    "offices": ["has_additional_offices", "additional_office_locations"],
    "certifications": [
        "has_business_certifications",
        "business_certifications",
        "has_diversity_certification",
        "diversity_certifications",
        "has_construction_license",
        "construction_licenses",
        "has_iso_cert",
    ],
    "workforce": [
        "employee_details_turnover",
        "number_of_trades_people",
        "union_details",
        "percentage_subcontract_work",
    ],
    "legal": ["legal"],
    "projects": ["largest_current_projects", "largest_completed_projects"],
    "financials": [
        "average_contract_values",
        "current_backlog",
        "current_backlog_currency_actual",
        "current_backlog_currency_guessed",
        "backlog_breakdown",
        "total_contracts_3_years",
        "currency_tracked",
        "diversification_by_gc",
        "diversification_by_province_state",
    ],
    "expertise": [
        "contract_size_expertise",
        "project_type_expertise",
        "trade_scope_expertise",
    ],
    "safety_personnel": ["has_hs_safety_person", "hs_safety_person_details"],
    "emr": ["emr", "has_emr_letters"],
    "osha_incidents": ["has_osha_msha", "osha_300_incident_information"],
    "incidents": ["incident_information"],
    "convictions": ["has_convictions_or_fines", "convictions_or_fines_details"],
    "hs_programs": ["has_hs_program", "hs_program_details"],
}

# Envelope fields suppressed from tool output.
ONE_FORM_SUPPRESSED_ENVELOPE_FIELDS = frozenset(
    {"flagged_total", "verified", "requested_by_entity_id", "requested_by_entity_type", "status"}
)


def _has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, dict, str)):
        return len(value) > 0
    return True


def one_form_inventory(data: dict[str, Any]) -> dict[str, bool]:
    return {
        section: any(_has_content(data.get(key)) for key in keys)
        for section, keys in ONE_FORM_SECTIONS.items()
    }


def project_one_form(data: dict[str, Any], sections: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    unknown = [s for s in sections if s not in ONE_FORM_SECTIONS]
    if unknown:
        raise ValueError(
            f"Unknown 1Form section(s) {unknown}; valid: {sorted(ONE_FORM_SECTIONS)}"
        )
    for section in sections:
        out[section] = {
            key: data.get(key) for key in ONE_FORM_SECTIONS[section] if key in data
        }
    return out


def slim_one_form_envelope(record: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in record.items()
        if k != "data" and k not in ONE_FORM_SUPPRESSED_ENVELOPE_FIELDS
    }


def _stage_progress(stage: dict[str, Any]) -> str:
    rule = stage.get("complete_requirements")
    reviewers = stage.get("reviewers") or []
    pending = stage.get("pending_reviewers")
    if rule == "custom_form":
        return "awaiting subcontractor form submission (stage has no reviewers by design)"
    if rule == "one_review":
        if pending is None:
            return f"completes when ANY ONE of {len(reviewers)} reviewers reviews"
        return (
            f"needs any 1 review; {len(pending)} of {len(reviewers)} reviewers have not "
            f"acted, but only one of them needs to"
        )
    if rule == "all_reviews":
        if pending is None:
            return f"needs a review from EVERY one of {len(reviewers)} reviewers"
        return f"needs all {len(reviewers)} reviews; {len(pending)} still pending"
    if rule == "all_groups":
        return "each group must satisfy its own completion rule — see groups"
    if rule == "sub_flow":
        return (
            "parallel independent tracks — see sub_flows; parent reviewer lists are the "
            "union across tracks (do not sum parent and per-track counts)"
        )
    return f"completion rule: {rule!r}"


def annotate_approval_stage(stage: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a copy of a stage (flow- or request-side) with `progress` strings."""
    if stage is None:
        return None
    out = dict(stage)
    out["progress"] = _stage_progress(stage)
    if isinstance(stage.get("groups"), list):
        out["groups"] = [annotate_approval_stage(g) for g in stage["groups"]]
    if isinstance(stage.get("sub_flows"), list):
        annotated = []
        for track in stage["sub_flows"]:
            track_out = dict(track)
            if isinstance(track.get("current_stage"), dict):
                track_out["current_stage"] = annotate_approval_stage(track["current_stage"])
            if isinstance(track.get("stages"), list):
                track_out["stages"] = [annotate_approval_stage(s) for s in track["stages"]]
            annotated.append(track_out)
        out["sub_flows"] = annotated
    return out


def explain_null_current_stage(status: Any) -> str:
    if status == "awaiting_qualification":
        return "no review stage yet — awaiting the subcontractor's qualification submission"
    if status in ("complete", "cancelled"):
        return f"request is {status} — no active review stage"
    return "not currently at a review stage"


_REVIEW_STATUS_PHRASES = {
    "compass": "COMPASS is still gathering or analyzing subcontractor data",
    "in_review": "ready for the GC to review",
    "changes_required": "needs GC involvement (changes required)",
    "completed": "review completed — qualification assigned",
    "cancelled": "invitation cancelled",
}

_CS_STATUS_PHRASES = {
    "in_progress": "COMPASS client services is chasing/analyzing",
    "on_hold": "on hold — sub agreed to submit but needs more time",
    "escalated": "ESCALATED — COMPASS needs the GC to step in",
    "completed": "COMPASS finished registration/submission/authorization/analytics",
}


def workflow_summary(wf: dict[str, Any]) -> str:
    parts: list[str] = []
    if wf.get("sub_legal_entity_id") is None and (
        wf.get("invited_sub_name") or wf.get("invited_user_id")
    ):
        name = wf.get("invited_sub_name") or "invited user"
        parts.append(f"{name}: invited, not yet registered")
    review = wf.get("review_status")
    if review in _REVIEW_STATUS_PHRASES:
        parts.append(f"review stage: {_REVIEW_STATUS_PHRASES[review]}")
    cs = wf.get("cs_status")
    if cs in _CS_STATUS_PHRASES:
        parts.append(f"COMPASS: {_CS_STATUS_PHRASES[cs]}")
    if wf.get("review_status_override") is True:
        parts.append(
            "review stage was set manually by the GC — automated stage changes are OFF "
            "for this request"
        )
    return "; ".join(parts) if parts else "status unknown"
