import csv
import json

from scripts.answer_compare import compare_answers, extract_answer_text
from scripts.run_eval import ExecutionSnapshot, EvalCase, run_assertions, _expected_answer_assertions, classify_failure, write_summary


def test_extract_answer_text_prefers_last_marked_answer():
    report = "Working...\nFinal Answer: 40\nMore checks\nFinal Answer: 42\n"

    answer, method = extract_answer_text(report)

    assert answer == "42"
    assert method == "marked"


def test_extract_answer_text_keeps_multiline_marked_answer():
    report = "Working...\nFinal Answer: first line\nsecond line\nthird line"

    answer, method = extract_answer_text(report)

    assert answer == "first line\nsecond line\nthird line"
    assert method == "marked"


def test_compare_answers_matches_numeric_with_unit_tolerance():
    result = compare_answers("74.434541420118 Yuan/m2", "74.434541420118", mode="auto")

    assert result.passed
    assert result.expected_numbers == [74.434541420118]


def test_compare_answers_requires_text_when_expected_has_meaningful_tokens():
    result = compare_answers("163802, 6987, much higher", "163802 and 6987", mode="auto")

    assert not result.passed
    assert "token_recall" in result.detail


def test_expected_answer_assertion_requires_marked_answer_when_configured():
    outcomes = _expected_answer_assertions(
        {"value": "42", "require_marked_answer": True},
        "The answer is 42.",
    )

    assert len(outcomes) == 1
    assert not outcomes[0].passed
    assert "No marked final answer" in outcomes[0].detail


def test_expected_answer_assertion_passes_marked_numeric_answer():
    outcomes = _expected_answer_assertions(
        {"value": "42", "require_marked_answer": True},
        "Analysis complete.\nFinal Answer: 42.0",
    )

    assert len(outcomes) == 1
    assert outcomes[0].passed


def test_expected_answer_assertion_uses_step_outputs_when_report_truncates_answer(tmp_path):
    case = EvalCase(
        id="c1",
        file_path=tmp_path / "input.xlsx",
        question="question",
        source="manifest.json",
        assertions={"expected_answer": {"value": "14400", "require_marked_answer": True}},
    )
    snapshot = ExecutionSnapshot(
        state={"status": "completed"},
        report="The report mentions July_Budget: 14400 but omits the final marker.",
        step_outputs=["debug...\nFinal Answer: 14400"],
    )

    outcomes = run_assertions(case, snapshot)

    expected_answer = [item for item in outcomes if item.name.startswith("expected_answer:")]
    assert len(expected_answer) == 1
    assert expected_answer[0].passed


def test_classify_failure_identifies_wrong_numeric_answer():
    result = {
        "passed": False,
        "exception": None,
        "assertions": [
            {
                "name": "expected_answer:answer_1",
                "passed": False,
                "required": True,
                "detail": "numbers_matched=False; expected_numbers=[42]; observed_numbers=[40]",
            }
        ],
    }

    assert classify_failure(result) == "wrong_numeric_answer"


def test_write_summary_writes_failure_breakdowns(tmp_path):
    results = [
        {
            "case": {"id": "c1", "source": "manifest.json", "notes": ["tag=complex"]},
            "passed": True,
            "duration_seconds": 1.2,
            "workspace": "/tmp/ws1",
            "failed_assertions": [],
            "failure_category": None,
        },
        {
            "case": {"id": "c2", "source": "manifest.json", "notes": ["tag=complex"]},
            "passed": False,
            "duration_seconds": 2.3,
            "workspace": "/tmp/ws2",
            "failed_assertions": ["expected_answer:answer_1"],
            "failure_category": "wrong_answer",
        },
    ]

    write_summary(tmp_path, results)
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))

    assert summary["failure_categories"] == {"passed": 1, "wrong_answer": 1}
    with (tmp_path / "failures.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["case_id"] == "c2"
    assert rows[0]["failure_category"] == "wrong_answer"
    assert (tmp_path / "by_note.csv").exists()
