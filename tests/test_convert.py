from datetime import datetime, timezone

import pytest

from compass_mcp.convert import (
    epoch_to_iso,
    humanize_timestamps,
    maybe_epoch_param,
    to_epoch,
)


def test_to_epoch_int_passthrough():
    assert to_epoch(1671662349) == 1671662349


def test_to_epoch_numeric_string():
    assert to_epoch("1671662349") == 1671662349


def test_to_epoch_iso_date_is_midnight_utc():
    assert to_epoch("2026-08-22") == int(
        datetime(2026, 8, 22, tzinfo=timezone.utc).timestamp()
    )


def test_to_epoch_iso_datetime_z():
    assert to_epoch("2022-12-21T22:39:09Z") == 1671662349


def test_to_epoch_iso_datetime_with_offset():
    assert to_epoch("2022-12-22T00:39:09+02:00") == 1671662349


def test_to_epoch_rejects_garbage():
    with pytest.raises(ValueError):
        to_epoch("not-a-date")


def test_to_epoch_rejects_bool_and_negative():
    with pytest.raises(ValueError):
        to_epoch(True)
    with pytest.raises(ValueError):
        to_epoch(-5)


def test_maybe_epoch_param_none():
    assert maybe_epoch_param(None) is None
    assert maybe_epoch_param("2022-12-21T22:39:09Z") == 1671662349


def test_epoch_to_iso_roundtrip():
    assert epoch_to_iso(1671662349) == "2022-12-21T22:39:09Z"
    assert to_epoch(epoch_to_iso(1671662349)) == 1671662349


def test_humanize_converts_only_registered_keys():
    payload = {
        "created": 1671662349,
        "updated": 1671662349,
        "year": 2024,
        "count": 1671662349,
        "emr": [{"emr_year": 2023, "emr_value": 0.87}],
        "deadline": 5,
        "cs_details": {"expiry_date": 1671662349},
        "current": True,
    }
    out = humanize_timestamps(payload)
    assert out["created"] == "2022-12-21T22:39:09Z"
    assert out["updated"] == "2022-12-21T22:39:09Z"
    assert out["year"] == 2024
    assert out["count"] == 1671662349
    assert out["emr"][0]["emr_year"] == 2023
    assert out["deadline"] == 5
    assert out["cs_details"]["expiry_date"] == "2022-12-21T22:39:09Z"
    assert out["current"] is True
    # input untouched
    assert payload["created"] == 1671662349


def test_humanize_handles_lists_and_scalars():
    assert humanize_timestamps([{"created": 1671662349}, "x", 3])[0]["created"].endswith("Z")
    assert humanize_timestamps("plain") == "plain"
