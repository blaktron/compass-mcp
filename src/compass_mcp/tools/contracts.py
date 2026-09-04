"""Contracts tools."""

from __future__ import annotations

import os
from typing import Any

from ..csv_validator import MAX_FILE_BYTES, validate_contracts_csv
from .common import confirmation_gate, ensure_writes_enabled, fetch, tool_errors


@tool_errors
async def compass_validate_contracts_csv(file_path: str) -> dict[str, Any]:
    """Validate a contracts CSV locally, without uploading anything.

    Checks required headers, duplicate contract_code, decimal/boolean/date/tax-identifier
    formats, and the 5 MB size cap. Run this before compass_import_contracts_csv.
    """
    return validate_contracts_csv(file_path)


@tool_errors
async def compass_import_contracts_csv(file_path: str, confirm: bool = False) -> dict[str, Any]:
    """Upload a contracts CSV file.

    HIGH CONSEQUENCE: requires confirm=true after the user approves the file. The
    file is validated locally first and validation errors abort the upload. Only
    import files the user supplied or explicitly approved.
    """
    ensure_writes_enabled()
    validation = validate_contracts_csv(file_path)
    if not validation["ok"]:
        return {
            "aborted": True,
            "reason": "Local validation failed — nothing was uploaded.",
            "validation": validation,
        }
    gate = confirmation_gate(
        confirm,
        "Upload a contracts CSV to Compass (creates/updates contracts and projects)",
        {
            "file": file_path,
            "file_size_bytes": validation.get("file_size_bytes"),
            "row_count": validation.get("row_count"),
            "warnings": validation.get("warnings"),
            "warning": (
                "This import cannot be read back or undone via the API. Verify the row "
                "count and contents with the user."
            ),
        },
    )
    if gate:
        return gate

    size = os.path.getsize(file_path)
    if size > MAX_FILE_BYTES:
        raise ValueError(f"File is {size} bytes; the Compass limit is 5 MB.")
    with open(file_path, "rb") as fh:
        content = fh.read()
    await fetch(
        "POST",
        "/compass/contract/csv_import",
        files={"data.csv": (os.path.basename(file_path), content, "text/csv")},
    )
    return {
        "imported": True,
        "file": file_path,
        "rows": validation.get("row_count"),
        "note": (
            "Compass returned 204. There is no API read-back for contracts — verify in "
            "the Compass UI if confirmation matters."
        ),
    }
