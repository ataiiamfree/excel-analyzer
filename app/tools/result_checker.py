"""Deterministic checks for generated analysis results."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CheckItem:
    name: str
    status: str
    message: str = ""


@dataclass
class CheckResult:
    step_id: str
    status: str
    checks: list[CheckItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    def to_prompt_text(self) -> str:
        lines = [f"结果校验状态: {self.status}"]
        for check in self.checks:
            lines.append(f"- {check.name}: {check.status} {check.message}".strip())
        return "\n".join(lines)


class ResultChecker:
    def validate(self, step: Any, exec_result: Any, context: Any, workspace: Any) -> CheckResult:
        checks = [
            self._check_process_success(exec_result),
            self._check_stdout_not_empty(step, exec_result),
            self._check_final_answer_contract(step, exec_result, context),
            self._check_no_data_answer_against_column_names(step, exec_result, context),
            self._check_column_family_selection_basis(step, exec_result, context),
            self._check_derived_metric_when_direct_pair_exists(
                step, exec_result, context, workspace
            ),
            self._check_single_item_query_not_aggregated(step, exec_result, context, workspace),
            self._check_expected_outputs(step, workspace),
            self._check_output_files_readable(workspace, exec_result),
        ]
        checks.extend(self._check_basic_invariants(step, exec_result, context, workspace))
        failed = any(check.status == "failed" for check in checks)
        warnings = [check.message for check in checks if check.status == "warning"]
        return CheckResult(
            step_id=step.id,
            status="failed" if failed else "passed",
            checks=checks,
            warnings=warnings,
        )

    def _check_process_success(self, exec_result: Any) -> CheckItem:
        success = getattr(exec_result, "success", None)
        if success is None:
            success = not getattr(exec_result, "failed", True)
        if success:
            return CheckItem("process_success", "passed")
        return CheckItem("process_success", "failed", getattr(exec_result, "stderr", ""))

    def _check_stdout_not_empty(self, step: Any, exec_result: Any) -> CheckItem:
        if getattr(exec_result, "stdout", "").strip():
            return CheckItem("stdout_not_empty", "passed")
        if getattr(step, "expected_outputs", None):
            return CheckItem("stdout_not_empty", "warning", "stdout 为空，仅依赖输出文件")
        return CheckItem("stdout_not_empty", "failed", "没有摘要输出，Reporter 无法可靠引用结果")

    def _check_final_answer_contract(
        self,
        step: Any,
        exec_result: Any,
        context: Any,
    ) -> CheckItem:
        if not self._process_succeeded(exec_result):
            return CheckItem("final_answer_contract", "passed")
        if not self._requires_final_answer(step, context):
            return CheckItem("final_answer_contract", "passed")
        stdout = getattr(exec_result, "stdout", "") or ""
        if self._has_marked_final_answer(stdout):
            return CheckItem("final_answer_contract", "passed")
        return CheckItem(
            "final_answer_contract",
            "failed",
            "问答/查询/计算型任务必须在 stdout 最后提供 `Final Answer: ...`，否则结果无法稳定复核。",
        )

    def _check_expected_outputs(self, step: Any, workspace: Any) -> CheckItem:
        expected = getattr(step, "expected_outputs", []) or []
        if not expected:
            return CheckItem("expected_outputs", "passed")
        missing = []
        output_files = {item.get("path") or item.get("name") for item in workspace.list_files()}
        for item in expected:
            path = item.get("path") or item.get("name")
            if path and path not in output_files and not Path(workspace.path, path).exists():
                missing.append(path)
        if missing:
            return CheckItem("expected_outputs", "failed", f"缺少预期产物: {missing}")
        return CheckItem("expected_outputs", "passed")

    def _check_no_data_answer_against_column_names(
        self,
        step: Any,
        exec_result: Any,
        context: Any,
    ) -> CheckItem:
        if not self._process_succeeded(exec_result) or not self._requires_final_answer(step, context):
            return CheckItem("no_data_answer_column_check", "passed")
        stdout = getattr(exec_result, "stdout", "") or ""
        final_answer = self._extract_final_answer(stdout)
        if not final_answer:
            return CheckItem("no_data_answer_column_check", "passed")
        answer_claims_no_data = self._looks_like_no_data_answer(final_answer)
        zero_after_failed_lookup = (
            self._looks_like_zero_answer(final_answer)
            and self._stdout_reports_failed_lookup(stdout)
        )
        if not answer_claims_no_data and not zero_after_failed_lookup:
            return CheckItem("no_data_answer_column_check", "passed")

        text = self._combined_task_text(step, context)
        column_names = self._profile_column_names(context)
        for year in sorted(set(re.findall(r"\b(?:19|20)\d{2}\b", text))):
            matching_columns = [
                name
                for name in column_names
                if year in self._column_name_tokens(name)
                and not self._is_note_like_column(name)
            ]
            if matching_columns:
                return CheckItem(
                    "no_data_answer_column_check",
                    "failed",
                    (
                        f"最终答案声称没有 {year} 数据，但数据列名包含 {year}: "
                        f"{matching_columns[:8]}。请优先检查年份是否编码在列名中，而不是筛选行。"
                    ),
                )
        candidate_lines = self._nonempty_candidate_evidence_lines(stdout)
        if candidate_lines:
            return CheckItem(
                "no_data_answer_column_check",
                "failed",
                (
                    "最终答案为 0/未找到，但 stdout 已打印出非空候选值: "
                    f"{candidate_lines[:4]}。这通常说明目标实体存在，只是筛选条件或上下文重建有误。"
                    "请把候选值作为线索继续定位；若条件来自父级/楼层/分组行，不要强制要求它与明细项在同一行，"
                    "应通过相邻行、分组标题或 forward-fill 重建上下文后再筛选。"
                ),
            )
        entity_lines = self._task_entity_evidence_lines(stdout, text)
        if entity_lines and self._stdout_reports_failed_lookup(stdout):
            return CheckItem(
                "no_data_answer_column_check",
                "failed",
                (
                    "最终答案为 0/None/未找到，但 stdout 中已经出现了问题里的目标实体: "
                    f"{entity_lines[:4]}。这通常说明数据存在，只是字符串规范化、列选择或父级上下文处理有误。"
                    "请用 stdout 中出现的真实取值重新筛选；若其他条件来自父级/楼层/分组行，"
                    "应通过相邻行、分组标题或 forward-fill 重建上下文，不要直接返回空答案。"
                ),
            )
        return CheckItem("no_data_answer_column_check", "passed")

    def _check_column_family_selection_basis(
        self,
        step: Any,
        exec_result: Any,
        context: Any,
    ) -> CheckItem:
        if not self._process_succeeded(exec_result) or not self._requires_final_answer(step, context):
            return CheckItem("column_family_selection_basis", "passed")
        text = self._combined_task_text(step, context).lower()
        if self._mentions_explicit_ordinal(text):
            return CheckItem("column_family_selection_basis", "passed")

        matched_families = []
        for family in self._profile_column_families(context):
            base = str(family.get("base") or "").strip()
            columns = family.get("columns") or []
            if not base or not isinstance(columns, list) or len(columns) < 2:
                continue
            if re.search(rf"(?<!\w){re.escape(base.lower())}(?!\w)", text):
                matched_families.append((base, [str(col) for col in columns]))

        if not matched_families:
            return CheckItem("column_family_selection_basis", "passed")

        stdout = getattr(exec_result, "stdout", "") or ""
        base, columns = matched_families[0]
        if self._has_weak_column_family_selection_basis(stdout):
            return CheckItem(
                "column_family_selection_basis",
                "warning",
                (
                    f"问题命中了重复表头列族 `{base}`: {columns}，但 stdout 显示仍按 primary/first/default "
                    "选择列。若用户没有指定第几列/第几次，请检查全部列族成员，并说明选择依据。"
                ),
            )
        if self._has_column_family_selection_evidence(stdout):
            return CheckItem("column_family_selection_basis", "passed")

        return CheckItem("column_family_selection_basis", "passed")

    def _process_succeeded(self, exec_result: Any) -> bool:
        success = getattr(exec_result, "success", None)
        if success is None:
            return not getattr(exec_result, "failed", True)
        return bool(success)

    def _has_marked_final_answer(self, stdout: str) -> bool:
        return bool(re.search(r"(?im)^\s*(?:Final Answer|最终答案)\s*[:：]", stdout or ""))

    def _extract_final_answer(self, stdout: str) -> str:
        matches = list(
            re.finditer(r"(?im)^\s*(?:Final Answer|最终答案)\s*[:：]\s*(.*)$", stdout or "")
        )
        if not matches:
            return ""
        return matches[-1].group(1).strip()

    def _looks_like_no_data_answer(self, answer: str) -> bool:
        normalized = answer.strip().lower()
        patterns = (
            r"\bno\b.*\b(data|rows?|records?|available|found)\b",
            r"\bnot\s+found\b",
            r"^\s*none\s*[.!。]?\s*$",
            r"\bnone\s+(?:found|available|matched|returned)\b",
            r"\bnull\b",
            r"\bn/?a\b",
            r"无法",
            r"没有",
            r"未找到",
            r"无数据",
        )
        return any(re.search(pattern, normalized) for pattern in patterns)

    def _looks_like_zero_answer(self, answer: str) -> bool:
        numbers = self._numbers_in_text(answer)
        return len(numbers) == 1 and abs(numbers[0]) <= 1e-12

    def _stdout_reports_failed_lookup(self, stdout: str) -> bool:
        normalized = stdout or ""
        patterns = (
            r"\bno\s+matching\s+rows?\b",
            r"\bno\s+rows?\s+(?:found|matched)\b",
            r"\bnot\s+found\b",
            r"\bempty\s+(?:result|match|matches)\b",
            r"\bexact\s+match(?:es)?\D+0\s+rows?\b",
            r"\b(?:contains|case-insensitive|fuzzy)\s+match(?:es)?\D+0\s+rows?\b",
            r"\b0\s+rows?\b",
            r"未找到",
            r"没有.*匹配",
            r"0\s*行",
        )
        return any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns)

    def _nonempty_candidate_evidence_lines(self, stdout: str) -> list[str]:
        lines: list[str] = []
        for line in (stdout or "").splitlines():
            normalized = line.lower()
            if not any(keyword in normalized for keyword in ("candidate", "fuzzy", "候选")):
                continue
            if self._line_has_nonempty_candidate_value(line):
                lines.append(line.strip())
        return lines

    def _line_has_nonempty_candidate_value(self, line: str) -> bool:
        lowered = line.lower()
        empty_patterns = (
            r"\[\s*\]",
            r":\s*(?:none|null|nan|n/a|empty)\s*$",
            r":\s*(?:无|没有|空)\s*$",
        )
        if any(re.search(pattern, lowered) for pattern in empty_patterns):
            return False
        bracket_match = re.search(r"\[([^\]]+)\]", line)
        if bracket_match:
            return bool(re.search(r"[0-9A-Za-z\u4e00-\u9fff]", bracket_match.group(1)))
        return bool(
            re.search(
                r"(?:candidate|fuzzy|候选)[^:\n]*:\s*['\"]?[^'\"\s,;:]+",
                line,
                flags=re.IGNORECASE,
            )
        )

    def _task_entity_evidence_lines(self, stdout: str, task_text: str) -> list[str]:
        phrases = [self._normalize_phrase(phrase) for phrase in self._task_entity_phrases(task_text)]
        phrases = [phrase for phrase in phrases if len(phrase) >= 4]
        if not phrases:
            return []
        lines: list[str] = []
        for line in (stdout or "").splitlines():
            normalized_line = self._normalize_phrase(line)
            if not normalized_line:
                continue
            if any(phrase in normalized_line for phrase in phrases):
                lines.append(line.strip())
        return lines

    def _task_entity_phrases(self, task_text: str) -> list[str]:
        phrases: list[str] = []
        quote_patterns = (
            r'"([^"\n]{3,100})"',
            r"'([^'\n]{3,100})'",
            r"“([^”\n]{3,100})”",
            r"‘([^’\n]{3,100})’",
        )
        for pattern in quote_patterns:
            phrases.extend(match.group(1).strip() for match in re.finditer(pattern, task_text or ""))
        context_patterns = (
            r"\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+floor\b",
            r"第\s*[一二三四五六七八九十1234567890]+\s*(?:层|楼)",
        )
        for pattern in context_patterns:
            phrases.extend(match.group(0).strip() for match in re.finditer(pattern, task_text or "", flags=re.IGNORECASE))
        return list(dict.fromkeys(phrase for phrase in phrases if phrase))

    def _requires_final_answer(self, step: Any, context: Any) -> bool:
        text = self._combined_task_text(step, context)
        normalized = text.lower()
        if "final answer" in normalized or "最终答案" in text:
            return True
        if "?" in text or "？" in text:
            return True

        english_patterns = (
            r"\bwhat\b",
            r"\bwhich\b",
            r"\bwho\b",
            r"\bwhen\b",
            r"\bwhere\b",
            r"\bhow\s+many\b",
            r"\bhow\s+much\b",
            r"\bcount\b",
            r"\bcalculate\b",
            r"\bcompute\b",
            r"\bfind\b",
            r"\bidentify\b",
            r"\bprovide\b",
            r"\bcompare\b",
            r"\bquery\b",
        )
        if any(re.search(pattern, normalized) for pattern in english_patterns):
            return True

        chinese_keywords = (
            "多少",
            "几个",
            "哪",
            "什么",
            "是否",
            "有没有",
            "计算",
            "统计",
            "查询",
            "筛选",
            "找出",
            "比较",
            "给出",
        )
        return any(keyword in text for keyword in chinese_keywords)

    def _combined_task_text(self, step: Any, context: Any) -> str:
        return " ".join(
            str(part or "")
            for part in (
                getattr(context, "user_query", ""),
                getattr(step, "instruction", ""),
                getattr(step, "description", ""),
            )
        )

    def _check_derived_metric_when_direct_pair_exists(
        self,
        step: Any,
        exec_result: Any,
        context: Any,
        workspace: Any,
    ) -> CheckItem:
        if not self._process_succeeded(exec_result) or not self._requires_final_answer(step, context):
            return CheckItem("direct_pair_metric_selection", "passed")

        task_text = self._combined_task_text(step, context)
        if not self._asks_for_pairwise_difference(task_text):
            return CheckItem("direct_pair_metric_selection", "passed")

        direct_pairs = self._direct_paired_columns_mentioned_in_task(
            self._profile_column_names(context),
            task_text,
        )
        if not direct_pairs:
            return CheckItem("direct_pair_metric_selection", "passed")

        evidence_text = "\n".join(
            part for part in (
                getattr(exec_result, "stdout", "") or "",
                self._read_exec_script(exec_result, workspace),
            ) if part
        )
        if (
            not self._stdout_indicates_metric_rederived_from_cost(evidence_text)
            and not self._evidence_uses_related_pair_instead_of_direct_pair(
                evidence_text, direct_pairs
            )
        ):
            return CheckItem("direct_pair_metric_selection", "passed")

        metric, columns = direct_pairs[0]
        return CheckItem(
            "direct_pair_metric_selection",
            "warning",
            (
                f"问题要求比较 `{metric}` 相关指标，且表中存在直接配对列 {columns}，"
                "但 stdout/脚本显示可能改用了其他相关列重新推导。"
                "请优先使用这些直接配对列做差或比较；只有题目或表格明确定义公式时才自行推导。"
            ),
        )

    def _check_single_item_query_not_aggregated(
        self,
        step: Any,
        exec_result: Any,
        context: Any,
        workspace: Any,
    ) -> CheckItem:
        if not self._process_succeeded(exec_result) or not self._requires_final_answer(step, context):
            return CheckItem("single_item_not_aggregated", "passed")

        task_text = self._combined_task_text(step, context)
        if self._asks_for_aggregation(task_text):
            return CheckItem("single_item_not_aggregated", "passed")
        if not self._looks_like_single_item_value_query(task_text):
            return CheckItem("single_item_not_aggregated", "passed")

        stdout = getattr(exec_result, "stdout", "") or ""
        evidence_text = "\n".join(
            part for part in (stdout, self._read_exec_script(exec_result, workspace)) if part
        )
        if (
            self._reports_multiple_matches(stdout)
            and self._evidence_uses_sum_aggregation(evidence_text)
        ):
            return CheckItem(
                "single_item_not_aggregated",
                "warning",
                (
                    "用户是在查询单个项目/单个条件下的值，但 stdout/脚本显示匹配多行后进行了 sum/total 聚合。"
                    "除非用户明确要求 total/sum/aggregate，请先用父级/楼层/序号等上下文定位唯一行；"
                    "如果仍有多行，打印候选并说明选择依据，不要直接求和。"
                ),
            )
        return CheckItem("single_item_not_aggregated", "passed")

    def _profile_column_names(self, context: Any) -> list[str]:
        profile = getattr(context, "data_profile", {}) or {}
        tables = profile.get("tables", []) if isinstance(profile, dict) else []
        names: list[str] = []
        for table in tables:
            for column in table.get("columns_detail") or []:
                name = column.get("name")
                if name:
                    names.append(str(name))
            for family in table.get("column_families") or []:
                for name in family.get("columns") or []:
                    names.append(str(name))
        return names

    def _column_name_tokens(self, name: str) -> set[str]:
        return {
            token
            for token in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", str(name or "").lower())
            if token
        }

    def _is_note_like_column(self, name: str) -> bool:
        normalized = str(name or "").strip().lower()
        return any(token in normalized for token in ("note", "remark", "comment", "备注", "说明"))

    def _profile_column_families(self, context: Any) -> list[dict[str, Any]]:
        profile = getattr(context, "data_profile", {}) or {}
        tables = profile.get("tables", []) if isinstance(profile, dict) else []
        families: list[dict[str, Any]] = []
        for table in tables:
            families.extend(table.get("column_families") or [])
            if not table.get("column_families"):
                names = []
                for column in table.get("columns_detail") or []:
                    name = column.get("name")
                    if name:
                        names.append(str(name))
                families.extend(self._infer_column_families_from_names(names))
        return families

    def _infer_column_families_from_names(self, names: list[str]) -> list[dict[str, Any]]:
        name_set = set(names)
        families: list[dict[str, Any]] = []
        consumed: set[str] = set()
        for name in names:
            if name in consumed or self._dedupe_suffix(name) is not None:
                continue
            siblings = [name]
            index = 2
            while f"{name}_{index}" in name_set:
                siblings.append(f"{name}_{index}")
                index += 1
            if len(siblings) >= 2:
                consumed.update(siblings)
                families.append({
                    "base": name,
                    "columns": siblings,
                    "kind": "deduped_repeated_header_inferred",
                })
        return families

    def _dedupe_suffix(self, name: str) -> int | None:
        match = re.match(r"^.+_([2-9]\d*)$", str(name or ""))
        if not match:
            return None
        return int(match.group(1))

    def _mentions_explicit_ordinal(self, text: str) -> bool:
        ordinal_patterns = (
            r"\bfirst\b",
            r"\bsecond\b",
            r"\bthird\b",
            r"\b1st\b",
            r"\b2nd\b",
            r"\b3rd\b",
            r"第\s*[一二三123]\s*(次|个|列)?",
        )
        return any(re.search(pattern, text) for pattern in ordinal_patterns)

    def _has_column_family_selection_evidence(self, stdout: str) -> bool:
        evidence_keywords = (
            "column family",
            "all family",
            "all values",
            "valid values",
            "candidate values",
            "selection basis",
            "attempt values",
            "trial values",
            "列族",
            "全部列",
            "所有列",
            "所有候选",
            "候选值",
            "有效值",
            "选择依据",
            "试次",
            "尝试值",
        )
        normalized = (stdout or "").lower()
        return any(keyword in normalized for keyword in evidence_keywords)

    def _has_weak_column_family_selection_basis(self, stdout: str) -> bool:
        normalized = (stdout or "").lower()
        weak_patterns = (
            r"\bprimary\s+column\b",
            r"\bfirst\s+column\b",
            r"\bdefault(?:ed)?\s+to\b",
            r"\bmain\s+result\s+value\b",
            r"默认.*第一",
            r"主列",
            r"第一个.*列",
        )
        return any(re.search(pattern, normalized) for pattern in weak_patterns)

    def _asks_for_pairwise_difference(self, text: str) -> bool:
        normalized = (text or "").lower()
        patterns = (
            r"\bdifference\b",
            r"\bdiff\b",
            r"\bcompare\b",
            r"\bbetween\b",
            r"\bversus\b",
            r"\bvs\.?\b",
            r"差值",
            r"差异",
            r"比较",
        )
        return any(re.search(pattern, normalized) for pattern in patterns)

    def _direct_paired_columns_mentioned_in_task(
        self,
        columns: list[str],
        task_text: str,
    ) -> list[tuple[str, list[str]]]:
        normalized_task = self._normalize_phrase(task_text)
        grouped: dict[str, list[tuple[str, str]]] = {}
        for column in columns:
            split = self._split_direct_pair_column(column)
            if split is None:
                continue
            metric, entity = split
            if not metric or not entity:
                continue
            if not self._phrase_mentions_any_token(normalized_task, metric):
                continue
            if not self._phrase_contains(normalized_task, entity):
                continue
            grouped.setdefault(metric, []).append((entity, column))

        pairs: list[tuple[str, list[str]]] = []
        for metric, entity_columns in grouped.items():
            unique_entities = {entity for entity, _ in entity_columns}
            if len(unique_entities) < 2:
                continue
            pairs.append((metric, [column for _, column in entity_columns[:6]]))
        return pairs

    def _split_direct_pair_column(self, column: str) -> tuple[str, str] | None:
        normalized = str(column or "").strip().lower()
        if normalized.startswith("_source_"):
            return None
        parts = [
            part.strip()
            for part in re.split(r"[_/|\n]+", normalized)
            if part.strip()
        ]
        if len(parts) < 2:
            return None
        metric = " ".join(parts[:-1])
        entity = parts[-1]
        if metric in {"source", "_source"} or entity in {"file", "sheet", "row"}:
            return None
        return metric, entity

    def _stdout_indicates_metric_rederived_from_cost(self, stdout: str) -> bool:
        normalized = (stdout or "").lower()
        patterns = (
            r"\bprice\s*[-−]\s*cost",
            r"\bprice[^\n]{0,120}[-−][^\n]{0,120}\bcost",
            r"\bcost\b.*\bmark\s*up\b",
            r"\bmark\s*up\b.*\bcost\b",
            r"\bprice\s*=\s*[^,\n]+.*\bcost",
        )
        return any(re.search(pattern, normalized, flags=re.DOTALL) for pattern in patterns)

    def _evidence_uses_related_pair_instead_of_direct_pair(
        self,
        evidence_text: str,
        direct_pairs: list[tuple[str, list[str]]],
    ) -> bool:
        normalized_evidence = self._normalize_phrase(evidence_text)
        referenced_columns = self._referenced_column_names(evidence_text)
        if not referenced_columns:
            return False

        for metric, columns in direct_pairs:
            if any(self._phrase_contains(normalized_evidence, column) for column in columns):
                continue

            entities: set[str] = set()
            for column in columns:
                split = self._split_direct_pair_column(column)
                if split is not None:
                    entities.add(split[1])
            if len(entities) < 2:
                continue

            referenced_entities: set[str] = set()
            for column in referenced_columns:
                split = self._split_direct_pair_column(column)
                if split is None:
                    continue
                referenced_metric, referenced_entity = split
                if referenced_metric == metric:
                    continue
                if referenced_entity in entities:
                    referenced_entities.add(referenced_entity)
            if len(referenced_entities) >= 2:
                return True
        return False

    def _referenced_column_names(self, text: str) -> list[str]:
        names: list[str] = []
        patterns = (
            r"\[['\"]([^'\"]+)['\"]\]",
            r"\.get\(\s*['\"]([^'\"]+)['\"]",
        )
        for pattern in patterns:
            names.extend(match.group(1) for match in re.finditer(pattern, text or ""))
        return list(dict.fromkeys(name for name in names if name))

    def _read_exec_script(self, exec_result: Any, workspace: Any) -> str:
        script_path = getattr(exec_result, "script_path", None)
        if not script_path:
            return ""
        path = Path(script_path)
        if not path.is_absolute():
            path = Path(getattr(workspace, "path", "")) / path
        try:
            return path.read_text(encoding="utf-8")[:12000]
        except OSError:
            return ""

    def _phrase_mentions_any_token(self, normalized_text: str, phrase: str) -> bool:
        tokens = [token for token in self._normalize_phrase(phrase).split() if len(token) > 1]
        return any(self._phrase_contains(normalized_text, token) for token in tokens)

    def _phrase_contains(self, normalized_text: str, phrase: str) -> bool:
        normalized_phrase = self._normalize_phrase(phrase)
        if not normalized_phrase:
            return False
        return f" {normalized_phrase} " in f" {normalized_text} "

    def _normalize_phrase(self, text: str) -> str:
        normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", str(text or "").lower())
        return re.sub(r"\s+", " ", normalized).strip()

    def _numbers_in_text(self, text: str) -> list[float]:
        values: list[float] = []
        for match in re.finditer(r"[-+]?\d+(?:\.\d+)?", text or ""):
            try:
                values.append(float(match.group(0)))
            except ValueError:
                continue
        return values

    def _asks_for_aggregation(self, text: str) -> bool:
        normalized = (text or "").lower()
        patterns = (
            r"\bsum\b",
            r"\btotal\b",
            r"\baggregate\b",
            r"\baverage\b",
            r"\bmean\b",
            r"\bcount\b",
            r"\ball\b",
            r"总计",
            r"合计",
            r"求和",
            r"平均",
            r"统计",
            r"全部",
            r"所有",
        )
        return any(re.search(pattern, normalized) for pattern in patterns)

    def _looks_like_single_item_value_query(self, text: str) -> bool:
        normalized = (text or "").lower()
        value_patterns = (
            r"\bwhat\b",
            r"\bfind\b",
            r"\bextract\b",
            r"\bquantity\b",
            r"\bvalue\b",
            r"\bprice\b",
            r"\bamount\b",
            r"\bunit\b",
            r"多少",
            r"查找",
            r"查询",
            r"提取",
            r"数量",
            r"值",
        )
        if not any(re.search(pattern, normalized) for pattern in value_patterns):
            return False
        locator_patterns = (
            r'"[^"\n]{2,120}"',
            r"'[^'\n]{2,120}'",
            r"“[^”\n]{2,120}”",
            r"‘[^’\n]{2,120}’",
            r"\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+floor\b",
            r"第\s*[一二三四五六七八九十1234567890]+\s*(?:层|楼)",
        )
        return any(re.search(pattern, text or "", flags=re.IGNORECASE) for pattern in locator_patterns)

    def _reports_multiple_matches(self, stdout: str) -> bool:
        patterns = (
            r"(?:matched rows|exact matches count|matches count|found)\D+([2-9]\d*)",
            r"matched\s+([2-9]\d*)\s+row",
            r"number of rows matching[^:]*:\s*([2-9]\d*)",
            r"quantity values\s*:\s*\[[^\]]+,[^\]]+\]",
            r"匹配\D+([2-9]\d*)\D*行",
        )
        for pattern in patterns:
            if re.search(pattern, stdout or "", flags=re.IGNORECASE):
                return True
        return False

    def _evidence_uses_sum_aggregation(self, evidence_text: str) -> bool:
        normalized = (evidence_text or "").lower()
        patterns = (
            r"\bsum\s+of\b",
            r"\.sum\s*\(",
            r"\bsum\s*\(",
            r"sum of quantity",
            r"total_quantity",
            r"quantities\.sum",
            r"求和",
            r"合计",
        )
        return any(re.search(pattern, normalized) for pattern in patterns)

    def _check_output_files_readable(self, workspace: Any, exec_result: Any) -> CheckItem:
        """验证输出文件是否存在且可读。"""
        output_files = getattr(exec_result, "output_files", None)
        if output_files is None:
            output_files = getattr(exec_result, "files", [])
        output_files = output_files or []
        if not output_files:
            return CheckItem("output_files_readable", "passed")
        unreadable = []
        for file_path in output_files:
            full = Path(workspace.path) / file_path
            if not full.exists():
                unreadable.append(f"{file_path} (不存在)")
            elif full.stat().st_size == 0:
                unreadable.append(f"{file_path} (空文件)")
            else:
                # 尝试读取前几个字节确认可读
                try:
                    with open(full, "rb") as f:
                        f.read(64)
                except OSError as exc:
                    unreadable.append(f"{file_path} ({exc})")
        if unreadable:
            return CheckItem("output_files_readable", "failed", f"输出文件不可读: {unreadable}")
        return CheckItem("output_files_readable", "passed")

    def _check_basic_invariants(
        self,
        step: Any,
        exec_result: Any,
        context: Any,
        workspace: Any,
    ) -> list[CheckItem]:
        """基础不变量校验：筛选行数、聚合总和等。"""
        checks: list[CheckItem] = []
        instruction = getattr(step, "instruction", "") or ""
        stdout = getattr(exec_result, "stdout", "") or ""
        # 从 context 的最新 step summary 中提取信息
        summaries = getattr(context, "step_summaries", {})
        step_id = getattr(step, "id", "")
        if step_id in summaries:
            stdout = summaries[step_id]

        # 检查1: 如果是筛选操作，输出行数不应为 0
        filter_keywords = ("筛选", "过滤", "filter", "where", "query")
        if any(kw in instruction for kw in filter_keywords):
            if "0 行" in stdout or "0行" in stdout or "空表" in stdout:
                checks.append(CheckItem(
                    "filter_not_empty", "warning",
                    "筛选结果为空，请确认筛选条件是否正确",
                ))

        # 检查2: 如果是导出操作，检查输出目录是否有文件
        export_keywords = ("导出", "export", "保存", "save", "写入", "输出", "结果表")
        if any(kw in instruction for kw in export_keywords):
            output_files = getattr(exec_result, "output_files", None)
            if output_files is None:
                output_files = getattr(exec_result, "files", [])
            if not output_files:
                checks.append(CheckItem(
                    "export_has_output", "failed",
                    "指令要求导出/保存/写入，但本步骤没有在 output/ 目录产出文件；请把用户可见结果写入 output/。",
                ))
                return checks
            output_dir = Path(workspace.path) / "output"
            if output_dir.exists() and not any(output_dir.iterdir()):
                checks.append(CheckItem(
                    "export_has_output", "failed",
                    "指令要求导出但 output/ 目录为空",
                ))

        return checks
