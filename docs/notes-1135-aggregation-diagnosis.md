# SheetBench 1135 聚合稳定性诊断

日期：2026-07-16

案例：`sheetbench-complex_realhit-1135-5`

期望答案：`2, 24`

诊断基线：`origin/main@375d4ef639e99015d573a5490ffb1986ab6911c7`

## 结论

根因不是预处理结构丢失。`_context_user_name`、明细行、`Total` 行、指标列的
`header_path` 和数值统计都稳定存在。失败发生在 LLM 生成 Python 时，具体有两种
不稳定行为：

1. 同时累计明细行与等值 `Total` 行，正确的 `24` 被重复计算成 `48`。
2. 在多个 `Chats Serviced` 候选列中选到全零列，返回 `0, 0`。

现有 ResultChecker 没有工作簿真值，也没有从当前问题稳定命中这个长扁平列名对应的
列族，因此上述两类语义错误都可能通过产品内校验而不触发 semantic repair。

**发布判断：不存在已经证明为低风险的通用修复，`v0.9.2-mvp` 应将 1135 记为已知限制。**
本轮不修改产品代码。

## 运行配置

| 项目 | 值 |
|---|---|
| 模型 | `deepseek-v4-pro` |
| temperature | `0.1`（`LLMClient.call` 默认值） |
| 常规代码 repair | `2` |
| semantic repair | `1` |
| 网络最大尝试次数 | `2` |
| sandbox timeout | `60s` |
| 输入工作簿 SHA-256 | `8e4a896924844deb1ff3120f658277711dbab9102c1b8178487534fe18f3847e` |
| normalized parquet SHA-256 | `305ab6b38eb4350bf915c6f6eaa08e68f8cf63f4d9b4cc92ba17cd58bbdab9e7` |

三次运行使用相同命令，仅改变输出目录：

```bash
.venv/bin/python scripts/run_eval.py \
  --benchmark sheetbench \
  --benchmark-variant complex-qa \
  --benchmark-no-download \
  --case-id sheetbench-complex_realhit-1135-5 \
  --output-dir eval_runs/diag_1135_run<N> \
  --max-semantic-repair-attempts 1 \
  --retries 2 \
  --log-level INFO
```

## 三次复跑结果

| 运行 | 结果 | 最终答案 | 行口径 | 指标列 | repair | 耗时 |
|---|---|---|---|---|---:|---:|
| run1 | PASS | `2, 24` | 只取 `Queue == Total` | `...Chats Serviced_Total_2` | 0 | 56.240s |
| run2 | FAIL | `0, 0` | 所有带用户上下文的行 | `...Chats Serviced`（全零） | 0 | 34.129s |
| run3 | PASS | `2, 24` | 只取 `Queue == Total` | `...Chats Serviced_Total_2` | 0 | 95.509s |

本轮稳定性为 `2/3`，不能判定为稳定通过。三次 `code_history.json` 均只有
`s1_attempt_0.py`，说明 run2 的错误没有被产品内校验识别，也没有进入 semantic
repair。

### run1 / run3 的正确路径

两次通过均先找到值为 `Total` 的 Queue 列，再使用数值型总计列：

```python
mask_total = df[queue_col].astype(str).str.strip() == "Total"
df_total = df[mask_total]
filtered = df_total[df_total[total_chats_col] > 11]
total_chats = filtered[total_chats_col].sum()
```

### run2 的失败路径

run2 正确使用了 `_context_user_name`，但直接选择了同名的全零列：

```python
chats_col = "Agent Chat Productivity by Queue_Description:_All_Chats Serviced"
df_filtered = df_users[df_users[chats_col] > 11]
```

该列的 profile 为 `min=0, max=0, mean=0`。同一 profile 中，真正的总计列
`...Chats Serviced_Total_2` 为 `min=2, max=12, mean=7.85`。所以这不是数据缺失，
而是指标列选择错误。

## 与历史结果对比

| 历史运行 | 结果 | 代码口径 | 说明 |
|---|---|---|---|
| `v09_row_context_leaf_candidate` | PASS `2, 24` | 排除 `Total`，只聚合互斥明细行 | 正确路径 B |
| `v09_sheetbench_final` | FAIL `2, 48` | 不区分行角色，同时累计明细与 `Total` | 每个 12 被计算两次 |

历史 targeted pass、历史 full-run fail 和本轮三次复跑的五份 normalized parquet
具有完全相同的 SHA-256：

```text
305ab6b38eb4350bf915c6f6eaa08e68f8cf63f4d9b4cc92ba17cd58bbdab9e7
```

历史 full-run 的第一次代码已经得到 `2, 48`。随后 `s1_attempt_3.py` 主要补写
`output/result.txt`，仍保留同一聚合逻辑和错误答案。这说明当时的 semantic repair
修复了产物合同，没有修复数值语义。

## Normalized table 证据

五次运行中的 normalized table 均为 `13 x 48`，且内容逐单元一致：

- `_context_user_name`：13 行全部非空，7 个唯一用户。
- `_context_department`：13 行全部非空。
- 明细行：7 行。
- `Total` 行：6 行。
- `...Chats Serviced_Total_2`：数值型，范围 `2..12`。
- `...Chats Serviced`：数值型，但所有值均为 `0`。

两个超过 11 的用户均同时有一行明细和一行等值汇总：

| 用户 | 明细值 | `Total` 值 |
|---|---:|---:|
| Aravelli Sivapani 10170897 | 12 | 12 |
| Chalam Raju Chalam 10172481 | 12 | 12 |

因此存在两种都正确的互斥计算方式：

- 只取明细：`12 + 12 = 24`。
- 只取 `Total`：`12 + 12 = 24`。

同时取两类行才会得到 `48`。预处理已经保留了足以区分两类行的信息。

## Prompt 与 checker 诊断

### 已经提供给模型的信息

Profiler 已提供：

- 每列完整 `header_path`；
- 每列 dtype、null ratio、min/max/mean；
- `_context_user_name`；
- 12 个 `column_families`；
- Queue 枚举值中明确包含 `Total`。

Prompt 中也已经存在通用规则：有显式汇总行和总计列时，不要再对同时包含明细、
小计和总计的整列求和。因此继续叠加同义 prompt 规则不是合适的修复方向。

### 为什么仍会漏掉

当前 query-matched column-family 逻辑要求用户问题命中完整扁平化 `base`。用户只说
`Chats Serviced`，而 profile 的 base 是
`Agent Chat Productivity by Queue_Description:_All_Chats Serviced...`，所以本案例的
query-matched family hint 为空。ResultChecker 使用了同类匹配条件，也没有进入列族
选择依据检查。

run2 虽然打印了所有列名，但没有打印候选列值或“查找失败”语句。最终 `0, 0` 因而
没有触发 `no_data_answer_column_check`。Benchmark 的正确答案断言是在产品任务结束后
由评测层执行，无法反向触发产品 semantic repair；这是合理的评测边界，但暴露了产品
checker 的覆盖缺口。

## 根因判定

原要求中的二选一结论为 **B：模型聚合口径问题**，但应更准确地描述为：

> normalized 结构稳定且信息充分；LLM 对“指标列”和“明细/汇总行角色”的选择不稳定，
> ResultChecker 又没有形成足够具体的结构性反证来触发修复。

这不是 full-run 的跨案例状态污染。targeted 与 full-run 使用相同 normalized 数据，
本轮三个彼此隔离的 targeted run 也产生了不同代码路径，符合 temperature 非零下的
生成波动。

## 为什么本周不直接修

以下看似简单的处理都有明显误伤风险：

- 全局删除 `Total`：会破坏只在汇总行提供完整指标的业务表。
- 永远只取 `Total`：会破坏没有汇总行、或问题要求明细拆分的业务表。
- 在候选列中取最大值/非零值：真实业务中的零值是合法答案，也不能用数值大小决定语义。
- 把所有包含 `Chats Serviced` 的列族都强塞进 prompt：本表同时有 Assign、Transfer、
  Conference、Total 等分支，可能增加歧义和 prompt 长度。
- 看到答案为零就强制 repair：会把合法的零结果误判为失败。

要做成通用修复，需要先设计并测试基于 `header_path` 叶节点、行角色和候选值证据的
语义选择层，不适合在发布前一天作为小补丁合入。

## 后续通用方案建议（不在 v0.9.2 范围）

1. 基于 `header_path` 分词匹配用户指标，而不是要求命中完整扁平列名。
2. 为匹配到的候选列输出 dtype、null ratio、取值范围和 lineage；按语义证据排序，
   不按最大值排序。
3. 将明细、subtotal、total 作为候选行角色暴露给代码生成，但保留原始行，不在
   preprocessor 中武断删除。
4. Checker 只在证据充分时告警，例如“已选列全零，但存在 header leaf 更精确且非空的
   候选列”，并要求生成代码打印最终选择依据。
5. 新增普通业务表回归：合法零值、只有汇总行、没有汇总行、多级 subtotal、
   明细与总计并存、重复表头多指标。
6. 用普通表回归和 SheetBench A/B 同时验证，观察新增通过与回退，而不是只看 1135。

## v0.9.2 发布建议

状态文档建议写为：

> 1135：normalized 行上下文与汇总标记稳定保留，但模型对重复指标列及明细/汇总行口径
> 的选择不稳定；同配置 targeted 复跑 2/3 通过。当前无已证明低风险的通用修复，列为
> 已知限制，不阻塞本地单用户 MVP 发布。

**最终建议：不存在低风险通用修复，`v0.9.2-mvp` 记为已知限制。**
