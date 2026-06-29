"""Reusable answer matching helpers for benchmark evaluation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
import unicodedata
from typing import Any


@dataclass(frozen=True)
class AnswerComparison:
    passed: bool
    score: float
    mode: str
    detail: str
    expected_text: str
    observed_text: str
    expected_numbers: list[float]
    observed_numbers: list[float]


_FINAL_ANSWER_RE = re.compile(
    r"(?:final\s+answer|\u6700\u7ec8\u7b54\u6848|\u7b54\u6848)\s*[:\uff1a]\s*(.+)",
    re.IGNORECASE,
)

_UNIT_TOKENS = {
    "billion",
    "bn",
    "cny",
    "dollar",
    "dollars",
    "eur",
    "euro",
    "euros",
    "hour",
    "hours",
    "kg",
    "kilogram",
    "kilograms",
    "m",
    "m2",
    "million",
    "mn",
    "percent",
    "percentage",
    "pound",
    "pounds",
    "rmb",
    "ton",
    "tonne",
    "tonnes",
    "usd",
    "yuan",
}


def extract_answer_text(report: str, *, answer_regex: str | None = None) -> tuple[str, str]:
    """Return the marked final answer if present, otherwise the full report."""
    text = report or ""
    if answer_regex:
        match = re.search(answer_regex, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            if match.groups():
                return match.group(1).strip(), "regex"
            return match.group(0).strip(), "regex"

    marked: list[str] = []
    for line in text.splitlines():
        match = _FINAL_ANSWER_RE.search(line)
        if match and match.group(1).strip():
            marked.append(match.group(1).strip())
    if marked:
        return marked[-1], "marked"
    return text.strip(), "full_report"


def compare_answers(
    expected: Any,
    observed: Any,
    *,
    mode: str = "auto",
    abs_tol: float = 1e-6,
    rel_tol: float = 0.0,
    min_score: float = 0.75,
    min_token_recall: float = 0.5,
) -> AnswerComparison:
    expected_text = _clean_text(expected)
    observed_text = _clean_text(observed)
    mode = (mode or "auto").strip().lower()

    if mode in {"exact", "normalized_exact"}:
        passed = _normalized_text(expected_text) == _normalized_text(observed_text)
        return _result(
            passed,
            1.0 if passed else 0.0,
            mode,
            "normalized exact match" if passed else "normalized exact mismatch",
            expected_text,
            observed_text,
        )

    if mode in {"contains", "substring"}:
        passed = _normalized_text(expected_text) in _normalized_text(observed_text)
        return _result(
            passed,
            1.0 if passed else 0.0,
            mode,
            "expected text found" if passed else "expected text not found",
            expected_text,
            observed_text,
        )

    if mode == "numeric":
        return _numeric_result(expected_text, observed_text, abs_tol=abs_tol, rel_tol=rel_tol, mode=mode)

    if mode in {"token_f1", "f1", "text"}:
        score = _token_f1(expected_text, observed_text)
        passed = score >= min_score
        return _result(
            passed,
            score,
            mode,
            f"token_f1={score:.4f}; threshold={min_score}",
            expected_text,
            observed_text,
        )

    return _auto_result(
        expected_text,
        observed_text,
        abs_tol=abs_tol,
        rel_tol=rel_tol,
        min_score=min_score,
        min_token_recall=min_token_recall,
    )


def _auto_result(
    expected_text: str,
    observed_text: str,
    *,
    abs_tol: float,
    rel_tol: float,
    min_score: float,
    min_token_recall: float,
) -> AnswerComparison:
    expected_norm = _normalized_text(expected_text)
    observed_norm = _normalized_text(observed_text)
    if expected_norm and (expected_norm == observed_norm or expected_norm in observed_norm):
        return _result(True, 1.0, "auto", "normalized text match", expected_text, observed_text)

    expected_numbers = _numbers_from_value(expected_text)
    observed_numbers = _numbers_from_value(observed_text)
    if expected_numbers:
        numbers_matched = _all_numbers_matched(
            expected_numbers,
            observed_numbers,
            abs_tol=abs_tol,
            rel_tol=rel_tol,
        )
        expected_meaningful_tokens = _meaningful_tokens_without_numbers(expected_text)
        observed_meaningful_tokens = _meaningful_tokens_without_numbers(observed_text)
        text_recall = _token_recall(expected_meaningful_tokens, observed_meaningful_tokens)
        if numbers_matched and (not expected_meaningful_tokens or text_recall >= min_token_recall):
            return AnswerComparison(
                passed=True,
                score=max(text_recall, 1.0 if not expected_meaningful_tokens else text_recall),
                mode="auto",
                detail=(
                    f"numbers_matched=True; token_recall={text_recall:.4f}; "
                    f"min_token_recall={min_token_recall}"
                ),
                expected_text=expected_text,
                observed_text=observed_text,
                expected_numbers=expected_numbers,
                observed_numbers=observed_numbers,
            )
        return AnswerComparison(
            passed=False,
            score=text_recall,
            mode="auto",
            detail=(
                f"numbers_matched={numbers_matched}; token_recall={text_recall:.4f}; "
                f"expected_numbers={expected_numbers}; observed_numbers={observed_numbers[:20]}"
            ),
            expected_text=expected_text,
            observed_text=observed_text,
            expected_numbers=expected_numbers,
            observed_numbers=observed_numbers,
        )

    score = _token_f1(expected_text, observed_text)
    passed = score >= min_score
    return _result(
        passed,
        score,
        "auto",
        f"token_f1={score:.4f}; threshold={min_score}",
        expected_text,
        observed_text,
    )


def _numeric_result(
    expected_text: str,
    observed_text: str,
    *,
    abs_tol: float,
    rel_tol: float,
    mode: str,
) -> AnswerComparison:
    expected_numbers = _numbers_from_value(expected_text)
    observed_numbers = _numbers_from_value(observed_text)
    passed = bool(expected_numbers) and _all_numbers_matched(
        expected_numbers,
        observed_numbers,
        abs_tol=abs_tol,
        rel_tol=rel_tol,
    )
    return AnswerComparison(
        passed=passed,
        score=1.0 if passed else 0.0,
        mode=mode,
        detail=(
            f"expected_numbers={expected_numbers}; observed_numbers={observed_numbers[:20]}; "
            f"abs_tol={abs_tol}; rel_tol={rel_tol}"
        ),
        expected_text=expected_text,
        observed_text=observed_text,
        expected_numbers=expected_numbers,
        observed_numbers=observed_numbers,
    )


def _result(
    passed: bool,
    score: float,
    mode: str,
    detail: str,
    expected_text: str,
    observed_text: str,
) -> AnswerComparison:
    return AnswerComparison(
        passed=passed,
        score=score,
        mode=mode,
        detail=detail,
        expected_text=expected_text,
        observed_text=observed_text,
        expected_numbers=_numbers_from_value(expected_text),
        observed_numbers=_numbers_from_value(observed_text),
    )


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def _normalized_text(value: Any) -> str:
    text = _clean_text(value).casefold()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^\w.%+\-\u4e00-\u9fff]+", "", text, flags=re.UNICODE)
    return text


def _numbers_from_value(value: Any) -> list[float]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        number = float(value)
        return [number] if math.isfinite(number) else []

    text = _clean_text(value)
    if not text:
        return []
    if re.fullmatch(r"\d{4}[-/\u5e74]\d{1,2}([-/\u6708]\d{1,2}\u65e5?)?", text):
        return []

    normalized = (
        text.replace("\uff0c", ",")
        .replace("\uff05", "%")
        .replace("\uff0d", "-")
        .replace("\u2212", "-")
        .replace("\uffe5", "")
        .replace("\u00a5", "")
    )
    normalized = re.sub(r"(?<=\d),(?=\d{3}(\D|$))", "", normalized)

    parenthesized_negative = bool(re.fullmatch(r"\(.*\)", normalized))
    numbers: list[float] = []
    for match in re.finditer(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?%?(?![A-Za-z])", normalized):
        raw = match.group()
        is_percent = raw.endswith("%")
        raw_number = raw[:-1] if is_percent else raw
        try:
            number = float(raw_number)
        except ValueError:
            continue
        if parenthesized_negative and number > 0:
            number = -number
        if math.isfinite(number):
            numbers.append(number)
            if is_percent:
                numbers.append(number / 100)
    return numbers


def _all_numbers_matched(
    expected_numbers: list[float],
    observed_numbers: list[float],
    *,
    abs_tol: float,
    rel_tol: float,
) -> bool:
    if len(observed_numbers) < len(expected_numbers):
        return False
    used: set[int] = set()
    for expected in expected_numbers:
        match_index = None
        for index, actual in enumerate(observed_numbers):
            if index in used:
                continue
            if _numbers_close(actual, expected, abs_tol=abs_tol, rel_tol=rel_tol):
                match_index = index
                break
        if match_index is None:
            return False
        used.add(match_index)
    return True


def _numbers_close(actual: float, expected: float, *, abs_tol: float, rel_tol: float) -> bool:
    tolerance = max(abs_tol, rel_tol * abs(expected))
    return abs(actual - expected) <= tolerance


def _meaningful_tokens(value: Any) -> list[str]:
    return [token for token in _tokens(value) if token not in _UNIT_TOKENS]


def _meaningful_tokens_without_numbers(value: Any) -> list[str]:
    return [token for token in _meaningful_tokens(value) if not re.fullmatch(r"\d+(?:\.\d+)?", token)]


def _tokens(value: Any) -> list[str]:
    text = _clean_text(value).casefold()
    tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]", text)
    return tokens


def _token_recall(expected_tokens: list[str], observed_tokens: list[str]) -> float:
    expected_tokens = [token for token in expected_tokens if token]
    if not expected_tokens:
        return 1.0
    observed_counter = Counter(token for token in observed_tokens if token)
    matched = 0
    for token, count in Counter(expected_tokens).items():
        matched += min(count, observed_counter.get(token, 0))
    return matched / len(expected_tokens)


def _token_f1(expected: Any, observed: Any) -> float:
    expected_tokens = _meaningful_tokens(expected)
    observed_tokens = _meaningful_tokens(observed)
    if not expected_tokens and not observed_tokens:
        return 1.0
    if not expected_tokens or not observed_tokens:
        return 0.0
    observed_counter = Counter(observed_tokens)
    matched = 0
    for token, count in Counter(expected_tokens).items():
        matched += min(count, observed_counter.get(token, 0))
    if matched == 0:
        return 0.0
    precision = matched / len(observed_tokens)
    recall = matched / len(expected_tokens)
    return 2 * precision * recall / (precision + recall)
