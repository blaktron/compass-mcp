"""Local validation for the contracts CSV import.

Row numbering convention here: the first data row (after the header) is row 1.
"""

from __future__ import annotations

import csv
import os
import re
from datetime import datetime
from typing import Any

MAX_FILE_BYTES = 5 * 1024 * 1024

REQUIRED_COLUMNS = [
    "project_internal_id",
    "project_name",
    "contract_code",
    "contract_name",
    "contract_tax_identifier",
]

DATE_COLUMNS = [
    "project_expected_start_date",
    "project_expected_finish_date",
    "contract_start_date",
    "contract_end_date",
]

BOOL_COLUMNS = ["project_archived", "contract_completed"]

DECIMAL_COLUMNS = [
    "contract_original_value",
    "contract_current_value",
    "contract_invoiced_amount",
    "contract_remaining_commitment_amount",
]

KNOWN_COLUMNS = set(REQUIRED_COLUMNS + DATE_COLUMNS + BOOL_COLUMNS + DECIMAL_COLUMNS)

_DATE_FORMATS = ["%d-%b-%y", "%m-%d-%Y", "%Y-%m-%d", "%d/%b/%y", "%m/%d/%Y", "%Y/%m/%d"]
_BOOL_VALUES = {"true", "false", "t", "f"}
_DECIMAL_RE = re.compile(r"^\d[\d,]*(\.\d+)?$")
_TAX_RE = re.compile(r"^(\d{2}-\d{7}|\d{9})$")


def _err(
    type_: str, message: str, row: int | None = None, field: str | None = None, value: str | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {"type": type_, "message": message}
    if row is not None:
        out["row_number"] = row
    if field is not None:
        out["field"] = field
    if value is not None:
        out["value"] = value
    return out


def _valid_date(value: str) -> bool:
    if value.isdigit():
        return True
    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


def _valid_decimal(value: str) -> bool:
    if not _DECIMAL_RE.match(value):
        return False
    try:
        float(value.replace(",", ""))
        return True
    except ValueError:
        return False


def validate_contracts_csv(path: str) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not os.path.isfile(path):
        return {
            "ok": False,
            "file": path,
            "errors": [_err("file_not_found", f"No such file: {path}")],
            "warnings": [],
        }

    size = os.path.getsize(path)
    if size > MAX_FILE_BYTES:
        return {
            "ok": False,
            "file": path,
            "file_size_bytes": size,
            "errors": [
                _err(
                    "file_too_large",
                    f"File is {size} bytes; Compass caps uploads at 5 MB ({MAX_FILE_BYTES} bytes).",
                )
            ],
            "warnings": [],
        }

    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        try:
            headers = [h.strip() for h in (reader.fieldnames or [])]
        except csv.Error as exc:
            return {
                "ok": False,
                "file": path,
                "file_size_bytes": size,
                "errors": [_err("csv_parse_error", f"Cannot parse CSV: {exc}")],
                "warnings": [],
            }
        missing = [c for c in REQUIRED_COLUMNS if c not in headers]
        if missing:
            errors.append(
                _err(
                    "missing_required_header_fields",
                    "Missing required header fields: " + ", ".join(missing),
                )
            )
        unknown = [h for h in headers if h and h not in KNOWN_COLUMNS]
        if unknown:
            warnings.append(
                _err(
                    "unknown_columns",
                    "Columns not in the expected format (Compass may ignore them): "
                    + ", ".join(unknown),
                )
            )

        seen_codes: dict[str, int] = {}
        row_count = 0
        try:
            rows = list(reader) if not missing else []
        except csv.Error as exc:
            errors.append(_err("csv_parse_error", f"Cannot parse CSV: {exc}"))
            rows = []
        if not missing:
            for row_number, raw_row in enumerate(rows, start=1):
                row_count += 1
                row = {
                    (k or "").strip(): (v or "").strip()
                    for k, v in raw_row.items()
                    if k is not None
                }

                for column in REQUIRED_COLUMNS:
                    if not row.get(column):
                        errors.append(
                            _err(
                                "required_header_value_empty",
                                f"Required header value: {column} is empty for row number: {row_number}",
                                row_number,
                                column,
                                "",
                            )
                        )

                code = row.get("contract_code")
                if code:
                    if code in seen_codes:
                        errors.append(
                            _err(
                                "duplicate_contract_code",
                                f"Duplicate contract_code value found: {code} for row number: "
                                f"{row_number} (first used on row {seen_codes[code]})",
                                row_number,
                                "contract_code",
                                code,
                            )
                        )
                    else:
                        seen_codes[code] = row_number

                for column in DECIMAL_COLUMNS:
                    value = row.get(column)
                    if value and not _valid_decimal(value):
                        errors.append(
                            _err(
                                "invalid_float_format",
                                f"Invalid float value: {value} for row number: {row_number}",
                                row_number,
                                column,
                                value,
                            )
                        )

                for column in BOOL_COLUMNS:
                    value = row.get(column)
                    if value and value.lower() not in _BOOL_VALUES:
                        errors.append(
                            _err(
                                "invalid_bool_format",
                                f"Invalid bool value: {value} for row number: {row_number}",
                                row_number,
                                column,
                                value,
                            )
                        )

                for column in DATE_COLUMNS:
                    value = row.get(column)
                    if value and not _valid_date(value):
                        errors.append(
                            _err(
                                "invalid_date_format",
                                f"Invalid date value: {value} for row number: {row_number}",
                                row_number,
                                column,
                                value,
                            )
                        )

                tax = row.get("contract_tax_identifier")
                if tax and not _TAX_RE.match(tax):
                    errors.append(
                        _err(
                            "invalid_tax_format",
                            f"Invalid contract_tax_identifier value: {tax} for row number: {row_number}",
                            row_number,
                            "contract_tax_identifier",
                            tax,
                        )
                    )

                completed = row.get("contract_completed")
                remaining = row.get("contract_remaining_commitment_amount")
                if not completed and remaining and _valid_decimal(remaining):
                    if float(remaining.replace(",", "")) == 0.0:
                        warnings.append(
                            _err(
                                "completed_will_be_inferred",
                                f"Row {row_number}: contract_completed is omitted and "
                                f"contract_remaining_commitment_amount is 0 — Compass will "
                                f"mark this contract COMPLETED. Send contract_completed "
                                f"explicitly if that is not intended.",
                                row_number,
                                "contract_completed",
                            )
                        )

    return {
        "ok": not errors,
        "file": path,
        "file_size_bytes": size,
        "row_count": row_count if not missing else None,
        "errors": errors,
        "warnings": warnings,
        "row_number_convention": "first data row after the header is row 1 (local validator only)",
    }
