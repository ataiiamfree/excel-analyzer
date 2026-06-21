# 办公数据分析 AI 平台化实现计划与 Milestone

> 本计划面向探索分支，用于评估并逐步推进 “Pi / Agent Harness + Skills + Typed Tools” 架构。计划不追求一次性替换当前后端，而是通过可回滚的阶段性改造验证平台化价值。

## 一、目标

把当前 ChatExcel 的单一 Excel 分析能力演进为通用办公数据分析 AI 平台能力。短期目标不是重写所有代码，而是完成以下架构转向：

- 从硬编码 Orchestrator 转向 Agent Runtime + Skills。
- 从松散 executor 转向 typed tools。
- 从文件清单转向 Artifact Graph。
- 从 Excel-only 转向 spreadsheet-first，再扩展到文档、图表、报告和自动化工作流。

## 二、非目标

本阶段暂不做：

- 企业级多租户、RBAC、审计系统。
- 分布式任务队列。
- 云对象存储。
- 完整工作流编排器。
- 全量替换前端交互体验。
- 一次性替换所有现有 Python 分析链路。

## 三、总体推进策略

采用渐进式迁移：

```text
当前 Orchestrator
  ↓
ToolRegistry + Artifact Graph v1
  ↓
Skills v1 接管流程约束
  ↓
Pi / Harness Sidecar 接入
  ↓
Agent Runtime 替换 Orchestrator 核心循环
  ↓
多办公场景扩展
```

核心原则：

- 每个 milestone 都要能独立验证。
- 每一步都保持当前 ChatExcel 可用。
- 先把领域工具稳定化，再替换 agent runtime。
- 不把安全边界交给 LLM 或外部 harness。

### 3.1 当前分支实现状态

本探索分支已实现 Milestone 1 到 Milestone 6 的 v1 能力，Milestone 7 暂不实现：

| Milestone | 状态 | 主要落地文件 |
|---|---|---|
| M1 工具协议与注册表 | 已实现 | `app/tools/registry.py`、`app/agent/orchestrator.py` |
| M2 Artifact Graph v1 | 已实现 | `app/workspace.py`、`app/api/persistence/store.py`、`app/api/artifact_utils.py` |
| M3 Artifact QA | 已实现 | `app/agent/artifact_qa.py`、`tests/test_artifact_qa.py` |
| M4 Skills v1 | 已实现 | `app/skills/registry.py`、`skills/*/SKILL.md` |
| M5 Pi / Harness Sidecar 试点 | 已实现 | `app/agent/runtime.py`、`app/agent/pi_tool_service.py`、`tests/test_agent_runtime.py` |
| M6 Agent Runtime 替换核心循环 | 已实现 v1 | `app/api/ws/runner.py` 默认通过 Pi primary runtime 调用 agent，Orchestrator 作为 fallback |
| M7 办公场景扩展 | 未实现 | 后续再扩展非 Excel 数据源和更多输出形态 |

当前默认 `AGENT_RUNTIME=pi`，系统会优先启动 `pi --mode rpc --no-session`。如果本机未安装 Pi、模型凭证不可用或 sidecar 运行失败，默认 `AGENT_RUNTIME_FALLBACK=true` 会回退到当前 Python Orchestrator。部署 Pi primary runtime 需要本机安装 `@earendil-works/pi-coding-agent` 或提供兼容的 `PI_COMMAND`。

## 四、Milestone 1：工具协议与注册表

### 目标

把当前隐含在 Orchestrator 里的工具能力显式化，建立 typed tool registry，确保 planner 只能选择已注册工具。

### 主要工作

- 新增 `app/tools/registry.py`。
- 定义 `ToolSpec`、`ToolCall`、`ToolResult`。
- 把现有能力包装成工具：
  - `spreadsheet.ingest_workbook`
  - `spreadsheet.normalize_tables`
  - `spreadsheet.profile_tables`
  - `code.run_python_sandboxed`
  - `result.validate`
  - `artifact.list`
  - `artifact.inspect`
- Planner prompt 从“tool 只能是 python 或 knowledge”改为基于 registry 动态生成。
- 规划解析阶段拒绝未注册工具。
- 移除或禁用当前未完成的 `knowledge` 路径，避免再次出现未注入工具导致的运行时失败。

### 验收标准

- 当前 Excel 分析流程仍然可跑。
- Planner 不能生成未注册工具。
- 未注册工具错误发生在规划校验阶段，而不是执行阶段。
- 单测覆盖工具注册、工具查找、未知工具拒绝。

## 五、Milestone 2：Artifact Graph v1

### 目标

把 `artifact_manifest.json` 从文件清单升级为可追溯的产物图，为产物问答、报告引用和评测提供统一事实源。

### 主要工作

- 扩展 artifact manifest 字段：
  - artifact_id
  - kind
  - path
  - producer_step_id
  - producer_tool
  - input_artifact_ids
  - source_tables
  - script_path
  - stdout_summary
  - schema
  - row_count
  - chart_metadata
  - sha256
- 更新 `Workspace.register_artifact()`。
- 更新 API persistence 中 artifacts 表或增加 metadata JSON 字段。
- 更新 artifact preview/download 逻辑，保留兼容老字段。
- 在 sandbox 执行后自动把 stdout、script_path 和 output files 关联起来。

### 验收标准

- 每个 output 产物能反查 producer step。
- report.md 能作为普通 artifact 进入图。
- API 能返回 artifact metadata。
- 前端 Artifact Panel 不破坏现有展示。

## 六、Milestone 3：Artifact QA Skill 和工具

### 目标

解决“解释某个生成图表/导出表/报告附件”的追问能力，这是从 ChatExcel 走向办公 AI 平台的关键体验。

### 主要工作

- 新增 `artifact_qa` skill 文档。
- 新增工具：
  - `artifact.resolve_by_name`
  - `artifact.inspect`
  - `artifact.explain`
- 对 chart/image 增加初版图表解释能力：
  - 优先读取 chart_metadata。
  - 回退到 producer stdout。
  - 再回退到生成脚本中的标题、轴名、保存文件名。
- Planner / Router 识别用户提到的文件名、图表、附件、导出表。
- 对产物追问跳过不必要的重新预处理。

### 验收标准

- 用户问“解释 trend_ma_anomaly_chart.png”时，不走 spreadsheet 重新分析，也不走未注册 knowledge。
- 回答包含：
  - 这是什么图。
  - 数据来源。
  - 横纵轴和主要元素。
  - 异常点或趋势含义。
  - 生成口径和局限。
- 增加至少 3 个产物追问回归测试。

## 七、Milestone 4：Skills v1

### 目标

把当前 prompt 中散落的业务流程约束沉淀为 skills，让不同办公场景可以独立演进。

### 主要工作

- 新增 skills 目录：
  - `skills/spreadsheet_analysis/SKILL.md`
  - `skills/artifact_qa/SKILL.md`
  - `skills/report_generation/SKILL.md`
  - `skills/result_validation/SKILL.md`
- 增加 Skill Registry。
- 增加 Intent Router，根据用户输入、附件、会话上下文选择 skill。
- PromptAssembler 改为按 selected skill 组装流程约束。
- 为每个 skill 定义允许调用的工具集合。

### 验收标准

- 普通 Excel 分析选择 `spreadsheet_analysis`。
- 产物解释选择 `artifact_qa`。
- 明确要求报告时选择或追加 `report_generation`。
- Skill 约束进入每次 LLM planning / tool selection prompt。

## 八、Milestone 5：Pi / Agent Harness Sidecar 试点

### 目标

在不替换核心 Python 数据工具的前提下，验证 Pi 或兼容 agent harness 是否适合承担通用 agent runtime。

### 建议接入方式

先采用 sidecar，而不是直接嵌入主进程：

```text
FastAPI
  → AgentRuntimeAdapter
      → Pi RPC / SDK
          → Python Tool Service
              → existing spreadsheet tools / sandbox / artifact graph
```

### 主要工作

- 新增 `AgentRuntimeAdapter` 接口。
- 实现当前 Orchestrator adapter。
- 实现 Pi RPC sidecar adapter，使用 `pi --mode rpc --no-session` JSONL 协议。
- 将 typed tools 通过 `app.agent.pi_tool_service` 命令行桥暴露给 sidecar。
- 将 sidecar event stream 映射回现有 WebSocket event schema：
  - `message_update.text_delta` 中 `<<FINAL_REPORT>>` 之后的内容 → `report.delta`
  - `message_update.text_delta` 中 marker 之前的内容 → `reasoning.delta`
  - `message_update.thinking_delta` 和 `tool_execution_*` → `reasoning.delta`
  - `agent_start/agent_end` → synthetic `pi-runtime` step start/end
- 增加 runtime factory：
  - `AGENT_RUNTIME=pi`：Pi 为主 runtime。
  - `AGENT_RUNTIME=orchestrator`：强制走旧 Orchestrator。
  - `AGENT_RUNTIME_FALLBACK=true`：Pi 失败时自动回退。
- 选择少量场景跑 A/B：
  - 普通表格统计。
  - 复杂多步分析。
  - 产物解释。
  - 报告生成。

### 验收标准

- Pi sidecar 能通过 tool service 调用 spreadsheet ingest / normalize / profile / sandbox 工具，具备完成 spreadsheet analysis case 的运行路径。
- Pi sidecar 能通过 `artifact.explain` 完成 artifact_qa case。
- 现有 FastAPI / React UI 不需要大改即可展示事件。
- 出现失败时能回退当前 Orchestrator adapter。

## 九、Milestone 6：Agent Runtime 替换核心循环

### 目标

在 sidecar 验证通过后，把当前 Orchestrator 的通用 agent loop 逐步替换为 Agent Runtime。

### 主要工作

- 将 planning、tool selection、repair、follow-up routing 迁移到 Pi Agent Runtime。
- 保留 Python typed tools、sandbox、workspace 和 artifact graph。
- 将 ResultChecker 升级为强制工具。
- 将 reporter 从 Orchestrator 内部组件变为 report skill/tool。
- 统一 run event log：Pi 事件被折回现有 WebSocket event schema，并继续进入消息 payload。

### 验收标准

- 当前回归测试通过。
- Eval simple accuracy 不低于迁移前基线。
- 每次运行都能回放 tool calls、tool results、artifacts 和 final answer。

## 十、Milestone 7：办公场景扩展

### 目标

在 spreadsheet-first 稳定后，开始扩展为办公数据分析平台。

### 候选方向

- CSV / TSV 分析。
- Google Sheets 连接器。
- PDF / Word 表格抽取。
- PPT / Word 报告生成。
- 日报、周报、月报模板。
- 数据库或 BI 导出分析。
- 团队指标口径库。
- 批量任务与定时任务。

### 验收标准

- 至少新增一个非 Excel 数据源。
- 至少新增一个报告类输出形态。
- Skills 可以复用 typed tools，而不是为每个场景复制一套 Orchestrator。

## 十一、关键技术风险

### 11.1 Harness 与 Python 数据工具跨语言集成复杂

Pi 是 TypeScript 生态，当前后端是 Python/FastAPI。建议先通过 RPC 或 sidecar 解耦，不直接把 Python 核心逻辑迁到 TypeScript。

### 11.2 Skill 不能替代硬约束

Skill 是流程协议，但不是安全边界。权限、路径、沙箱、产物写入和校验必须由后端工具强制执行。

### 11.3 Agent 自由度提升后，回归稳定性可能下降

需要通过 Tool Registry、Skill allowlist、ResultChecker 和 eval cases 控制。

### 11.4 Artifact Graph 设计过重

第一版只实现产物追问必需字段，避免一开始做成复杂 lineage 平台。

## 十二、推荐优先级

建议优先顺序：

1. ToolRegistry。
2. Artifact Graph v1。
3. Artifact QA。
4. Skills v1。
5. Pi sidecar。
6. Runtime 替换。
7. 多办公场景扩展。

理由：

- ToolRegistry 先解决“未注册工具被 planner 选中”的基础可靠性问题。
- Artifact Graph 和 Artifact QA 先解决真实用户追问痛点。
- Skills 在有稳定工具后才有价值。
- Pi sidecar 在工具和 skills 结构清晰后接入，风险最低。

## 十三、近期探索产物

本探索分支建议先交付：

- 平台化设计文档。
- 实现计划与 milestone。
- ToolRegistry 设计草案。
- Artifact Graph v1 schema 草案。
- `artifact_qa` skill 草案。
- 1 到 2 个关键回归用例定义。

这些产物足以支持后续决定：继续使用当前 Python Orchestrator 增量演进，还是正式引入 Pi / Agent Harness。
