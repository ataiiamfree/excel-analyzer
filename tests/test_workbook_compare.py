from pathlib import Path

import openpyxl

from scripts.run_eval import _answer_workbook_assertions
from scripts.workbook_compare import compare_workbooks, parse_range_specs


def _save_workbook(path: Path, rows, *, sheet_name: str = "Sheet1") -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_parse_range_specs_handles_quoted_sheet_commas():
    specs = parse_range_specs("'DebtWaterfall'!A1:E2,'Shared Data'!B2:B12")

    assert len(specs) == 2
    assert specs[0].sheet_name == "DebtWaterfall"
    assert specs[0].coordinate == "A1:E2"
    assert specs[1].sheet_name == "Shared Data"
    assert specs[1].coordinate == "B2:B12"


def test_compare_workbooks_passes_with_numeric_tolerance(tmp_path):
    expected = tmp_path / "expected.xlsx"
    candidate = tmp_path / "candidate.xlsx"
    _save_workbook(expected, [["name", "value"], ["A", 10.0], ["B", 20.0]])
    _save_workbook(candidate, [["name", "value"], ["A", 10.000001], ["B", 20.0]])

    result = compare_workbooks(candidate, expected, ranges="A1:B3", abs_tol=0.001)

    assert result.passed()
    assert result.checked_cells == 6
    assert result.mismatched_cells == 0


def test_compare_workbooks_reports_best_mismatch_sample(tmp_path):
    expected = tmp_path / "expected.xlsx"
    candidate = tmp_path / "candidate.xlsx"
    _save_workbook(expected, [["name", "value"], ["A", 10], ["B", 20]])
    _save_workbook(candidate, [["name", "value"], ["A", 10], ["B", 21]])

    result = compare_workbooks(candidate, expected, ranges="A1:B3")

    assert not result.passed()
    assert result.mismatched_cells == 1
    assert result.sample_mismatches[0].coordinate == "B3"


def test_compare_workbooks_reports_mismatch_for_empty_expected_cell(tmp_path):
    expected = tmp_path / "expected.xlsx"
    candidate = tmp_path / "candidate.xlsx"
    _save_workbook(expected, [["name", "value"], ["A", 10]])
    _save_workbook(candidate, [["name", "value"], ["A", 10], [None, "extra"]])

    result = compare_workbooks(candidate, expected, ranges="A1:B3")

    assert not result.passed()
    assert result.sample_mismatches[0].coordinate == "B3"


def test_answer_workbook_assertion_uses_generated_output(tmp_path):
    expected = tmp_path / "golden.xlsx"
    output_dir = tmp_path / "case" / "workspace" / "task" / "output"
    output_dir.mkdir(parents=True)
    candidate = output_dir / "completed.xlsx"
    _save_workbook(expected, [["name", "value"], ["A", 10]])
    _save_workbook(candidate, [["name", "value"], ["A", 10]])

    outcomes = _answer_workbook_assertions(
        {"path": str(expected), "ranges": "A1:B2"},
        [candidate],
        tmp_path,
    )

    assert len(outcomes) == 1
    assert outcomes[0].passed
