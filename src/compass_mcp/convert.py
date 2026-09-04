"""Time conversions and response humanization."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Response keys whose values are epoch seconds.
TIMESTAMP_KEYS = frozenset(
    {
        "created",
        "updated",
        "expires",
        "deadline",
        "submitted",
        "due_date",
        "renewal_date",
        "scope_start_date",
        "scope_end_date",
        "bids_due_date",
        "expected_start_date",
        "expected_finish_date",
        "on_hold_until",
        "started_on",
        "cs_status_updated",
        "main_contact_updated",
        "cs_start_chase_date",
        "finance_cs_start_chase_date",
        "expiry_date",
        "compass_complete_submission_expiry_date",
        "compass_complete_submission_cs_start_chase_date",
        "diversity_certification_expiry",
        "construction_license_expiry",
    }
)

# Values below this are not treated as epochs even under a timestamp key.
MIN_PLAUSIBLE_EPOCH = 100_000_000


def to_epoch(value: str | int | float) -> int:
    """Accept an epoch int, a numeric string, or an ISO-8601 date/datetime."""
    if isinstance(value, bool):
        raise ValueError(f"not a timestamp: {value!r}")
    if isinstance(value, (int, float)):
        if value < 0:
            raise ValueError(f"negative timestamp: {value!r}")
        return int(value)
    text = value.strip()
    if text.isdigit():
        return int(text)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"cannot parse {value!r} as an epoch timestamp or ISO-8601 date/datetime"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def epoch_to_iso(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def maybe_epoch_param(value: str | int | None) -> int | None:
    """Convert an optional tool argument to epoch seconds."""
    if value is None:
        return None
    return to_epoch(value)


def humanize_timestamps(value: Any) -> Any:
    """Deep-copy `value`, replacing epoch ints under known keys with ISO strings."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if (
                key in TIMESTAMP_KEYS
                and isinstance(item, int)
                and not isinstance(item, bool)
                and item >= MIN_PLAUSIBLE_EPOCH
            ):
                out[key] = epoch_to_iso(item)
            else:
                out[key] = humanize_timestamps(item)
        return out
    if isinstance(value, list):
        return [humanize_timestamps(item) for item in value]
    return value
