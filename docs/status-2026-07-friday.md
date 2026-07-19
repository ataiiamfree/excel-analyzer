# v0.9.x 状态基线 · 截至 2026-07-17（周五）

> 本文件是本周所有 PR / merge / release note 的**事实基线**。任何声称与此不符的进度都以本文为准。
>
> 前一份 `docs/execution-status.md` 引用的"4 周 / 8-8"节奏已作废，不再作为当前基线；保留不动只是历史存档。

---

## 已发布 · v0.9.1-mvp

- **Tag**：`v0.9.1-mvp`（从 `375d4ef`）
- **合并 PR**：#5 · hotfix + `/api/runs` 生命周期 + 并发信号量
- **修复项**：
  - P0-1 SPA fallback 任意文件读取
  - P1-2 `/api/runs/{id}` GET/DELETE 死路
  - P1-3 `MAX_CONCURRENT_TASKS` 信号量真正落地
  - P1-4 ephemeral upload 失败留孤儿目录
  - P1-7 artifact 绝对路径 containment
- **测试**：264 → **278 passed**
- **SheetBench 关键词泄漏**：无

## v0.9.2 hardening · 代码与 QA 闸门已完成，待人工确认 tag

### CC 线（本文档所在分支）

- **分支**：`codex/v0.9.2-conversation-lifecycle`
- **In scope**：
  - P1-5 `SessionRegistry.delete` + `delete_conversation` 清理 ✅
  - P1-6 `delete_conversation` 检查运行中分析 → 409 ✅（已修正：区分 connected 与 active_run。`ConnectionManager` 拆成 `has_connections` 与 `begin_run`/`end_run`/`has_active_run`，WS 处理器在分析任务生命周期内标记；删除守卫只看 `has_active_run`，空闲会话页可正常删除）
- **Optional（快速无风险时做）**：CORS `cors_origins` 空时启动日志明确告警
- **明确不做**（推 Backlog）：
  - access log middleware
  - WebSocket ping/pong heartbeat
  - prompt budget test
  - 单会话多 WS 保护（P2-8）

### Smoke 定义（固定，闸门条件 2 的执行口径）

- **答案回归**：`python scripts/run_eval.py --manifest docs/test_datasets/simple_accuracy_manifest.json --case-id simple-01-q01 --case-id simple-07-q03 --case-id simple-12-q01 --output-dir eval_runs/<run-name> --max-semantic-repair-attempts 1 --retries 2 --log-level INFO`
- **删除生命周期**：`python scripts/smoke_delete_lifecycle.py`（真实 API + 真实 LLM：空闲 WS 可删 / 运行中 409 / 取消或完成后可删）
- 不再需要人工挑表。

### Smoke 结果 · 2026-07-16（P1-6 修正后）

- 删除生命周期：**全部通过**（S1/S2/S3，20 项检查）
- 答案回归：simple-01-q01 **PASS**、simple-12-q01 **PASS**、simple-07-q03 **FAIL ×2**（复跑一次仍失败）
- simple-07-q03 定性：**非回归**。两次运行主结论均正确（取消率 32%、8 单、并列最多 3 客户全列出）；失败均为结果表格式断言——首跑缺汇总行，复跑有汇总行但指标名为英文（断言要求行内含"取消"）且明细表多含 0 取消客户行。该 case 无历史通过基线（v0.9 普通表回归跑的是 simple-07-q01），且本分支 diff 仅涉及 `app/api/*` + 测试 + 文档，不触碰分析管线。归入下方已知限制。

### Codex 线 · 1135 诊断 ✅ 已完成（不实现，结论成立）

- **产物**：`docs/notes-1135-aggregation-diagnosis.md`（Codex 提交 `026a2fe`，已 cherry-pick 至 main `66c01a7`）
- **结论**：根因为**模型聚合口径问题**（判定 B），非预处理结构丢失——normalized 行上下文与 `Total` 标记稳定保留；不稳定发生在 LLM 对重复指标列和明细/汇总行角色的选择上，同配置 targeted 复跑 **2/3 通过**（run2 选中全零列返回 `0, 0`）。
- **发布判断**：当前无已证明低风险的通用修复 → **v0.9.2 记为已知限制，本周不为 1135 合入任何产品补丁**。通用方案（header_path 分词匹配 + 候选列证据排序 + 行角色暴露）留待 v0.10+。

## 已知限制（不在本周修复范围）

| Case | 现象 | 归属 |
|---|---|---|
| 1135 | 同配置复跑 2/3 通过；模型对重复指标列及明细/汇总口径的选择不稳定（`48` 为明细+Total 重复累计，`0` 为选中全零列） | **v0.9.2 已知限制**（诊断见 `docs/notes-1135-aggregation-diagnosis.md`；无低风险通用修复，本周不合入产品补丁） |
| 104, 101, 126, 2292, 515 | v0.9.0 release note 已列 | Backlog（可能 v0.10+ 或更远） |
| 普通表 5 例的第 5 例 | 主结论正确、缺派生字段 | Backlog（输出完整性问题非主结论错误） |
| simple-07-q03 | 主结论正确（取消率/并列最多客户均对），结果表缺中文标签汇总行或含多余明细行，断言不过 | Backlog（同上：输出完整性/格式约定类；无历史通过基线，非 v0.9.2 回归） |

## 周五唯一发布闸门

只打**一个** tag：`v0.9.2-mvp`。合并的**必要条件**（全部满足才合，任一不达即保 v0.9.1）：

1. `pytest` 全绿（本地 + 每个 PR 各跑一次）
2. 3 张普通业务表手动 smoke 无回归
3. 本文档与代码事实一致
4. P1-5 + P1-6 合入且有对应回归测试
5. 1135 状态明确：**已合入通用修复** 或 **保留为已知限制**（在此文档"已知限制"段明写）

**明确禁止**：
- 因为"周五时间到了"强行 double-merge
- 存在普通表回退但"能力提升更重要"的合并
- 1135 追分补丁（若诊断结论不支持通用修复）
- 本周开任何 Batch C 项目（鉴权、部署、监控、压测、用户文档等一律进 Backlog）

## 变更日志

| 时间 | 事件 |
|---|---|
| 2026-07-15 | v0.9-mvp 发布（`42871cc`），review 发现 P0 SPA 路径遍历 |
| 2026-07-15 | v0.9.1-mvp 发布（`375d4ef`），P0/P1 hotfix |
| 2026-07-16（进行中） | v0.9.2 hardening 双线：CC 做 API 正确性，Codex 做 1135 诊断 |
| 2026-07-16 | CC 线 P1-5 + P1-6 + CORS 告警完成（`5074d09`，284 passed），PR #6 已开，待合并；Codex 线 1135 诊断未开工 |
| 2026-07-16 | Codex 复核 PR #6：P1-5 正确；P1-6 误把"任意 WS 连接"当"分析运行中"，空闲会话页无法删除 → 改判**待修正**，PR #6 暂缓合并 |
| 2026-07-16 | P1-6 修正：`ConnectionManager` 区分 connected 与 active_run，新增 3 项删除生命周期回归（空闲可删 / 运行中 409 / 取消或完成后可删），291 passed |
| 2026-07-16 | Smoke 完成：删除生命周期全过；答案回归 2/3（simple-07-q03 定性为已知限制类、非回归，详见上文）；PR #6 合并 |
| 2026-07-16 | Codex 1135 诊断完成并 cherry-pick 至 main（`66c01a7`）：根因为模型聚合口径不稳定，无低风险通用修复 → 记为 v0.9.2 已知限制。**闸门条件 1-5 全部满足**，待周五打 tag |
| 2026-07-17（预期） | v0.9.2-mvp 单一发布（若闸门条件全满足） |
| 2026-07-18 | 真实浏览器验收完成：首次分析、同会话追问、刷新恢复、产物预览/下载、错误格式、损坏文件、空问题、取消、删除生命周期和重连降级路径已验证。发现并修复 Pi 读取 `CLAUDE.md` 后越权提交 Git 的 P0、全仓库 reload 被运行时脚本触发的 P0、空白问题按钮可点击的 P1。293 passed，前端生产构建通过；待人工确认后打 `v0.9.2-mvp` tag。 |
