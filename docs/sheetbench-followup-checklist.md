# SheetBench Capability Improvements — Follow-up Checklist

> 针对 commit `6f69d2c` (Improve SheetBench QA repair robustness) 的 review 结论。
> 目的：留下真正的通用能力增强，去掉 SheetBench 写死片段，降低 checker false positive 引起的 repair 循环风险。
> 交付方式：按 P0 → P3 顺序做，每一项都有独立的 DoD（Definition of Done）。

---

## P0 · 必须做（否则会伤到正常产品使用）

### 1. 删除 checker 中硬编码的 SheetBench 关键词

**文件**：`app/tools/result_checker.py`

- 删除函数 `_family_likely_uses_best_valid_value` 中的关键词：
  ```python
  keywords = ("attempt", "trial", "press", "snatch", "jerk", "try", "试", "举")
  ```
  `press / snatch / jerk` 是举重三项，属于数据集泄漏。
- 一并删除 `_check_best_valid_value_for_attempt_family` 整个函数与其在 `_check_column_family_selection_basis` 中的调用点。
  - 理由：假设"列族的正确答案 = max(values)" 只在 SheetBench 举重题成立；A/B/C test round、三次独立测量、时间序列列族都不成立。
- 从 `_stdout_indicates_metric_rederived_from_cost` 中删除以下 SheetBench 题面模式：
  ```python
  r"costmaterial.*costlabor.*mark\s*up",
  r"price.*cost.*difference",
  ```
  保留通用的 `r"\bprice\s*[-−]\s*cost"` 即可。
- 从 `_evidence_uses_cost_pair_instead_of_price_pair` 中移除对 `price` metric 的硬编码；改为对任意 `direct_pairs` 里的 metric 都做同样判定。

**DoD**：`grep -in "snatch\|jerk\|press\|costmaterial\|costlabor" app/tools/ app/context/` 无命中。

---

### 2. 把 3 个高误伤 checker 降级为 warning，不再驱动 repair

**文件**：`app/tools/result_checker.py`

以下 3 个 check 的 `CheckItem(..., "failed", ...)` 改为 `"warning"`，只写入 check report 供模型看，不触发 orchestrator 的 repair 循环：

- `_check_column_family_selection_basis`
- `_check_single_item_query_not_aggregated`
- `_check_derived_metric_when_direct_pair_exists`

同时把 `_check_column_family_selection_basis` 的默认分支改为 `"passed"`，而不是"没找到证据就 fail"。

**理由**：
- 判定信号来自 stdout 里我们自造的关键词（`selection basis / 选择依据 / all family / ...`），模型换个说法就误判。
- 三者的触发条件（问题里出现 base 名、`\bwhat\b` + `\bvalue\b`、fuzzy price/cost 匹配）在真实业务上 hit 率过高。
- 降为 warning 后模型仍能拿到提示做自我修正，但正确答案不会被强制走 repair。

**DoD**：`tests/test_result_checker.py` 中对应 fail 断言全部改为 `status == "warning"`；`result.status` 不因这些 warning 变成 `failed`。

---

### 3. checker repair 与 execution repair 使用独立预算

**文件**：`app/config.py`、`app/agent/orchestrator.py`

- 在 `Config` 里新增字段 `max_semantic_repair_attempts: int = 1`（默认 1，可调）。
- `orchestrator.run_plan` 里 checker repair 循环改用 `self.config.max_semantic_repair_attempts`；`_execute_python` 内的执行错误 repair 保留原 `max_repair_attempts`。
- 保证单步最坏 LLM 调用数为 `1 + max_repair_attempts + max_semantic_repair_attempts`，不再翻倍。

**DoD**：新增测试 `test_semantic_repair_uses_own_budget`：设 `max_repair_attempts=3, max_semantic_repair_attempts=1`，构造 checker 一直 fail 的场景，断言 checker repair 只跑 1 轮。

---

### 4. `_context_group` 分支 B 收窄识别

**文件**：`app/tools/excel_preprocessor.py`

`_context_group_label` 中"首列非空 + first_header 命中 id/serial/no/编号/序号/#" 分支存在两个问题：

- **子串匹配误伤**：`"no" in "notes"` / `"id" in "middle"` / `"#" in ""` 都会 hit。
  改为 tokenize 后 exact match：
  ```python
  first_header_tokens = re.split(r"[\s_/\-]+", first_header.strip().lower())
  first_header_looks_like_id = any(
      token in {"serial", "no", "id", "#", "编号", "序号"}
      for token in first_header_tokens
  )
  ```
- **单行父级识别不稳**：单行标签本身没有下方明细支撑时，也可能是数据行。
  加守卫：只有当**下方至少 1 行不满足 group label 特征**（即后续存在真实明细行）时才承认它是父级；单行末尾的孤立标签视为普通数据。

**保留** 分支 A（合并单元格 unmerge 后同值填满多列）不变。

**DoD**：新增 3 个测试用例：
- `test_context_group_ignores_notes_column_header`：首列 header 叫 `Notes`，父级识别不生效。
- `test_context_group_requires_downstream_detail_row`：孤立单元格没有后续明细，不视为父级。
- `test_context_group_still_detects_first_floor_pattern`：现有 SheetBench 楼层用例仍能正确识别（回归保护）。

---

## P1 · 强烈建议做

### 5. Code prompt 里的规则改为条件注入

**文件**：`app/context/prompt_assembler.py`

`assemble_python` 中新增的 10+ 条否定式规则目前**无条件追加**。改造：

- 把这一段抽成方法 `_python_task_hints(context) -> str`，仅当对应特征存在时才注入对应规则：
  - "`_context_*` 优先" —— 仅当 profile 里有 `_context_*` 列。
  - "禁止 primary/first column 作为列族选择依据" —— 仅当 profile 里有 `column_families`。
  - "不要仅因绝对值 > 1 就除以 100" —— 仅当 profile 里有含 `rate/ratio/percentage/growth/率` 的列名。
  - "不要把 price-cost 派生成 markup" —— 仅当 profile 里存在多个 `Price_*` 或 `Cost_*` 前缀列。
- 与 `_format_profile_hints` 已有的 conditional 逻辑对齐。
- 从 planner prompt 中删除硬编码举例 `Sales_2023/Sales_2024、Revenue_US/Revenue_EU`，改用抽象描述"若数据概况已有可直接使用的 A/B 配对列，优先使用"。

**DoD**：
- 单元测试：无 `column_families` / 无 `_context_*` 的普通表，assemble 出的 prompt **不**包含新加的这些规则文本。
- token 抽样：同一简单查询在改造前后 prompt 长度减少 ≥ 30%。

---

### 6. LLM 异常有退避与放弃条件

**文件**：`app/agent/orchestrator.py`

`_repair_from_check` 中新增的 try/except：

```python
except Exception as exc:
    logger.warning(...)
    return StepResult(..., retries_exhausted=False, ...)
```

问题：连续 timeout / 429 会立刻进下一轮，把 repair budget 一次烧完。

改造：
- 引入简单退避：连续异常时 `asyncio.sleep(backoff)`，`backoff = min(2 ** consecutive_failures, 30)`。
- 连续 2 次 LLM 异常后，把 `retries_exhausted=True`，提前放弃而非烧完预算。
- 或者：单独增加计数器 `context.consecutive_llm_failures`，跨 repair 轮次共享。

**DoD**：新增测试 `test_repair_gives_up_after_repeated_llm_exceptions`：mock LLM 连抛 2 次异常，断言 `retries_exhausted=True`，且 `run_plan` 提前失败。

---

### 7. `no_data_answer` 的 year 匹配改成 tokenize

**文件**：`app/tools/result_checker.py`

`_check_no_data_answer_against_column_names` 里：
```python
matching_columns = [name for name in column_names if year in name]
```
是纯子串匹配，`Notes_2020_Q1_status` 也会命中。

改为对列名 tokenize 后判断：
```python
def _tokenize_column_name(name: str) -> set[str]:
    return set(re.split(r"[\s_/\-.]+", name.lower()))
```
然后 `year in _tokenize_column_name(name)` 才算 hit。

**DoD**：新增测试 `test_no_data_answer_year_check_ignores_year_in_notes_column`。

---

### 8. `single_item_not_aggregated` 逻辑澄清或删除

**文件**：`app/tools/result_checker.py`

`_looks_like_single_item_value_query` 与 `_asks_for_aggregation` 词表大面积重叠（`count / all / value / what / total`），且中文用 `\b` word-boundary 对中文根本不生效。

二选一：
- **方案 A（推荐）**：既然在 P0#2 已经降级为 warning，可以直接删除整个 `_check_single_item_query_not_aggregated`。它现在也没有稳定信号。
- **方案 B**：保留但明确优先级：优先看 `_asks_for_aggregation`，命中即 return pass；只有明确的"单项定位"关键词（`what is the X of "quoted entity"` / `"某某"的 X 是多少`）才触发。删除中文 `\b` 词表。

**DoD**：删除或改造后，删除对应误伤测试；用真实业务表跑 `tests/test_eval_answer_scoring.py` 一遍确认无 regression。

---

## P2 · 有余力做

### 9. `_context_group` 起效时明示可见

**文件**：`app/tools/excel_preprocessor.py` + profile 输出

- 在 `NormalizedTable.warnings` 或 profile 顶层字段加一条 `context_group_summary`：
  ```
  跳过 N 行父级/分组标题，取值 [First Floor, Second Floor]，写入 _context_group 列
  ```
- profile 里同步给出 `context_group_source_rows: [2, 5]`，便于用户核对。

**DoD**：`test_process_converts_group_title_rows_to_context_column` 增补对该 summary 字段的断言。

---

### 10. 补 false-positive 回归测试集

**文件**：`tests/test_result_checker_regression.py`（新建）

- 挑 15–20 张非 SheetBench 的正常业务 Excel（销售明细、库存、财务月结…），跑一遍完整 `ResultChecker.validate`。
- 断言所有 check 的 `status` **不含 `"failed"`**（可以有 warning）。
- 用作后续 checker 改动的守门测试。

**DoD**：`pytest tests/test_result_checker_regression.py` 全通过；文档里说明"新增/修改 checker 前必须跑此回归"。

---

### 11. Repair 预算耗尽时留 audit trail

**文件**：`app/agent/orchestrator.py`

repair 循环结束仍失败时，把每一轮的 `check.to_prompt_text()` 和 stderr 摘要写进 `workspace` 一份 `repair_trail.json`，便于事后 debug 为什么一直修不好。

**DoD**：新增测试断言 workspace 里存在 `repair_trail.json`，包含 N 轮记录。

---

## P3 · 可选

### 12. Commit message 写具体

下一次 follow-up commit 请拆开写：

- `checker: drop SheetBench-specific keywords from column-family heuristic`
- `orchestrator: separate execution and semantic repair budgets`
- `preprocessor: tighten _context_group detection for id-like first columns`
- `prompt: make python task hints conditional on profile features`
- ...

避免用一句 `Improve SheetBench QA repair robustness` 覆盖 2000 行改动。

---

## 验收总闸

上述 P0 + P1 全部完成后，跑一遍：

1. `make test` 全绿。
2. `tests/test_result_checker_regression.py`（新增，见 P2#10）全绿。
3. SheetBench A/B 分数**不明显回退**：允许 -1 ~ +N，且 case-by-case review 回退原因。
4. 至少 3 张非 SheetBench 真实业务表跑 e2e 分析，观察：
   - 单步 LLM 调用数 ≤ 2（无异常）；
   - 无 warning 之外的 checker 失败；
   - Prompt 长度 vs. 主分支基线 涨幅 ≤ 15%。

任一项不满足，PR 不合并。
