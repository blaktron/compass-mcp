from compass_mcp.csv_validator import MAX_FILE_BYTES, validate_contracts_csv

HEADER = (
    "project_internal_id,project_name,contract_code,contract_name,contract_tax_identifier,"
    "project_expected_start_date,project_expected_finish_date,project_archived,"
    "contract_completed,contract_original_value,contract_current_value,"
    "contract_invoiced_amount,contract_remaining_commitment_amount,contract_start_date,"
    "contract_end_date"
)

GOOD_ROW = (
    "PROJ-12345,Project Alpha,CN001,Concrete Works,12-3456789,1741297455,1743899455,"
    "false,false,500000,480000,250000,20000,1741297455,11-17-2025"
)


def _write(tmp_path, text, name="contracts.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _types(result):
    return {e["type"] for e in result["errors"]}


def test_docs_example_file_is_valid(tmp_path):
    rows = [
        HEADER,
        GOOD_ROW,
        "ABC.000001,Project Beta,CN002,Steel Framing,98-7654321,1741200000,1743800000,false,true,750000,750000,750000,0,1741200000,1743800000",
        "PROJ-XYZ,Project Gamma,CN003,Electrical Installation,11-2233445,1741300000,1743900000,true,false,600000,590000,300000,10000,1741300000,1743900000",
    ]
    result = validate_contracts_csv(_write(tmp_path, "\n".join(rows)))
    assert result["ok"], result["errors"]
    assert result["row_count"] == 3
    assert not any(w["type"] == "completed_will_be_inferred" for w in result["warnings"])


def test_missing_required_header(tmp_path):
    header = HEADER.replace("contract_code,", "")
    row = GOOD_ROW.replace("CN001,", "")
    result = validate_contracts_csv(_write(tmp_path, f"{header}\n{row}"))
    assert not result["ok"]
    assert "missing_required_header_fields" in _types(result)


def test_empty_required_value(tmp_path):
    row = GOOD_ROW.replace("CN001", "")
    result = validate_contracts_csv(_write(tmp_path, f"{HEADER}\n{row}"))
    errors = [e for e in result["errors"] if e["type"] == "required_header_value_empty"]
    assert errors and errors[0]["field"] == "contract_code" and errors[0]["row_number"] == 1


def test_duplicate_contract_code(tmp_path):
    second = GOOD_ROW.replace("PROJ-12345", "PROJ-99999")
    result = validate_contracts_csv(_write(tmp_path, f"{HEADER}\n{GOOD_ROW}\n{second}"))
    dupes = [e for e in result["errors"] if e["type"] == "duplicate_contract_code"]
    assert dupes and dupes[0]["row_number"] == 2 and dupes[0]["value"] == "CN001"


def test_invalid_float_bool_date_tax(tmp_path):
    row = (
        "PROJ-1,P,CN9,C,badtax,notadate,1743899455,maybe,false,"
        "12x34,480000,250000,20000,1741297455,1743899455"
    )
    result = validate_contracts_csv(_write(tmp_path, f"{HEADER}\n{row}"))
    types = _types(result)
    assert {"invalid_float_format", "invalid_bool_format", "invalid_date_format", "invalid_tax_format"} <= types


def test_accepted_formats(tmp_path):
    row = (
        "PROJ-2,P,CN10,C,123456789,16-Nov-24,2024/11/16,t,F,"
        '"1,234.00",1234,"1,234",0,16/Nov/24,11/16/2024'
    )
    result = validate_contracts_csv(_write(tmp_path, f"{HEADER}\n{row}"))
    assert result["ok"], result["errors"]


def test_completed_inference_warning(tmp_path):
    header = HEADER.replace("contract_completed,", "")
    row = (
        "PROJ-3,P,CN11,C,12-3456789,1741297455,1743899455,false,"
        "500000,500000,500000,0,1741297455,1743899455"
    )
    result = validate_contracts_csv(_write(tmp_path, f"{header}\n{row}"))
    assert result["ok"]
    warnings = [w for w in result["warnings"] if w["type"] == "completed_will_be_inferred"]
    assert warnings and warnings[0]["row_number"] == 1


def test_file_too_large(tmp_path):
    path = tmp_path / "big.csv"
    path.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    result = validate_contracts_csv(str(path))
    assert "file_too_large" in _types(result)


def test_file_not_found(tmp_path):
    result = validate_contracts_csv(str(tmp_path / "nope.csv"))
    assert not result["ok"]
    assert "file_not_found" in _types(result)
