# 办公数据分析 AI 平台化设计文档

> 目标：把当前 ChatExcel 从单一 Excel 分析应用，演进为可扩展的办公数据分析 AI 平台。ChatExcel 是平台的第一个 spreadsheet 场景，不再是架构边界。

## 一、背景与问题

当前项目已经具备一条可运行的 Excel 分析链路：

- 上传 Excel 文件
- 识别 workbook / sheet / table 结构
- 预处理为 normalized tables
- 生成数据画像
- 由 LLM 规划和生成 Python 分析代码
- 在沙箱中执行
- 校验结果
- 生成报告和产物
- 支持 WebSocket 进度展示和历史会话回放

这条链路证明了 Code-first 数据分析 agent 的可行性，但也暴露出平台化前必须解决的问题。

### 1.1 当前 Orchestrator 的局限

当前 `app/agent/orchestrator.py` 把规划、执行、修复、动态调整、报告生成等能力集中在一个 Python 类中。它适合作为 MVP，但不适合作为通用平台核心：

- 工具能力写死在 `executors` 字典和 prompt 文案中。
- Planner 可能选择未完整注册的工具，例如 `knowledge`。
- 不同办公场景需要不同流程约束，目前只能继续扩大 Orchestrator。
- 追问对产物、图表、报告、导出文件的理解不够系统。
- 工具协议不够 typed，难以稳定扩展到 Word、PPT、PDF、数据库和 BI 报表。
- 运行状态、上下文、产物血缘和 agent 决策记录之间还没有统一模型。

### 1.2 平台化目标

平台化后的系统应当支持：

- Excel、CSV、Google Sheets、数据库导出等结构化数据分析。
- Word、PDF、PPT 中的表格和指标抽取。
- 图表、导出表、报告附件的产物问答。
- 日报、周报、经营分析、异常归因等模板化工作流。
- 多轮追问中复用数据画像、产物血缘、脚本、报告摘要和用户偏好。
- 可插拔 skills，让新场景通过流程约束和工具组合接入。
- 可观测、可回放、可评测的 agent 执行过程。

## 二、总体架构

建议采用分层架构：Agent Runtime 负责通用 agent 能力，Skills 负责办公场景流程约束，Typed Tools 负责可靠执行，Artifact Graph 负责产物与血缘。

```text
办公数据分析 AI 平台
├── Product Surface
│   ├── Chat UI
│   ├── Artifact Panel
│   ├── Report / Deck / Doc Preview
│   ├── Workflow Builder
│   └── Evaluation Dashboard
│
├── Agent Runtime
│   ├── Pi agent harness 或兼容层
│   ├── Tool calling
│   ├── State management
│   ├── Context assembly
│   ├── Streaming events
│   └── Turn / run lifecycle
│
├── Skills
│   ├── spreadsheet_analysis
│   ├── artifact_qa
│   ├── chart_interpretation
│   ├── report_generation
│   ├── document_analysis
│   ├── workflow_automation
│   └── result_validation
│
├── Typed Tools
│   ├── spreadsheet.ingest_workbook
│   ├── spreadsheet.normalize_tables
│   ├── spreadsheet.profile_tables
│   ├── code.run_python_sandboxed
│   ├── result.validate
│   ├── artifact.list
│   ├── artifact.inspect
│   ├── artifact.explain
│   ├── report.generate
│   └── memory.query / memory.save
│
├── Data Plane
│   ├── Workspace
│   ├── Raw Files
│   ├── Normalized Tables
│   ├── Output Artifacts
│   ├── Artifact Graph
│   └── SQLite / Local Metadata Store
│
└── Evaluation & Governance
    ├── Golden datasets
    ├── Regression cases
    ├── Tool contract tests
    ├── Skill adherence checks
    └── Safety and permission tests
```

## 三、Pi 与 Skills 的定位

Pi 或类似 agent harness 不应该替代 Excel 数据处理代码。它应当替代的是当前项目里逐渐膨胀的通用 agent 控制层。

### 3.1 Pi 适合承担的职责

- 多模型与 provider 接入。
- 通用 tool calling loop。
- skills 的按需加载。
- 会话状态、上下文压缩和事件流。
- agent 执行过程的标准化记录。
- 后续扩展到更多办公场景时的统一 harness。

### 3.2 Pi 不应承担的职责

- 不直接解析脏 Excel。
- 不直接绕过沙箱执行代码。
- 不直接决定 artifact 文件路径。
- 不绕过 ResultChecker 输出最终结论。
- 不替代后端权限、路径保护、产物血缘和数据校验。

### 3.3 Skills 的定位

Skill 不是简单 prompt，而是业务流程协议。它应告诉 agent：

- 什么场景应该调用哪些工具。
- 哪些工具调用顺序是强约束。
- 哪些信息必须进入最终回答。
- 哪些情况下必须停止、修复或请求用户补充信息。
- 哪些产物必须登记到 Artifact Graph。

示例：`spreadsheet_analysis` skill 约束如下。

```text
1. 不直接让 LLM 读取原始 Excel 明细。
2. 必须先调用 ingest_workbook。
3. 必须调用 normalize_tables，生成 normalized tables。
4. 必须调用 profile_tables，基于 profile 规划分析。
5. 明细计算必须通过 sandbox 或受控 query tool。
6. 用户可见文件必须写入 output/ 并注册 artifact。
7. 每个计算结果必须调用 result.validate。
8. 最终回答必须说明数据口径、输出产物和限制。
```

## 四、Typed Tools 设计

Typed Tools 是平台可靠性的核心。Agent 可以选择工具，但工具必须由后端定义输入输出 schema、权限边界和错误语义。

### 4.1 工具注册模型

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    handler: Callable
    permissions: list[str]
    produces_artifacts: bool = False
    deterministic: bool = True
```

工具注册表应满足：

- Planner 只能选择已注册工具。
- 未注册工具在规划阶段就被拒绝。
- 每个工具有稳定 input / output schema。
- 工具执行结果进入 run event log。
- 产物型工具必须写 Artifact Graph。

### 4.2 第一批核心工具

#### spreadsheet.ingest_workbook

输入：文件路径或 file_id。

输出：workbook manifest，包括 sheet、hidden rows/cols、merged ranges、table candidates。

对应现有模块：`WorkbookIngestor`。

#### spreadsheet.normalize_tables

输入：workbook manifest、raw file。

输出：normalized table artifacts、preprocess report、warnings。

对应现有模块：`ExcelPreprocessor`。

#### spreadsheet.profile_tables

输入：normalized table artifacts。

输出：profile，包括 shape、columns、enum_columns、sample_rows、warnings。

对应现有模块：`Profiler`。

#### code.run_python_sandboxed

输入：Python 代码、workspace、允许读取的 artifact ids、预期输出。

输出：stdout、stderr、script artifact、output files。

对应现有模块：`PythonSandbox`。

#### result.validate

输入：step intent、tool result、expected outputs、artifact graph。

输出：passed / warning / failed、检查项、修复建议。

对应现有模块：`ResultChecker`。

#### artifact.list

输入：conversation_id 或 run_id。

输出：当前会话可用产物列表。

#### artifact.inspect

输入：artifact_id 或文件名。

输出：产物 metadata、producer step、input artifacts、schema、row_count、script_path、stdout_summary、preview。

#### artifact.explain

输入：artifact_id、用户问题、可用 lineage。

输出：产物含义、数据来源、生成口径、可读结论、局限。

这是解决“解释 `trend_ma_anomaly_chart.png`”这类追问的关键工具。

## 五、Artifact Graph

当前 artifact manifest 更像文件清单。平台化后需要升级为 Artifact Graph。

### 5.1 Artifact 节点

```json
{
  "artifact_id": "art_...",
  "name": "trend_ma_anomaly_chart.png",
  "kind": "chart",
  "path": "output/trend_ma_anomaly_chart.png",
  "producer_run_id": "run_...",
  "producer_step_id": "s1",
  "producer_tool": "code.run_python_sandboxed",
  "input_artifact_ids": ["tbl_..."],
  "source_tables": ["巡检记录_t1"],
  "script_path": "scripts/s1_attempt_0.py",
  "stdout_summary": "...",
  "schema": null,
  "row_count": null,
  "chart_metadata": {
    "title": "设备温度与振动趋势",
    "x_axis": "巡检日期",
    "y_axis": ["温度", "振动值"],
    "series": ["温度", "温度移动平均", "振动值", "振动移动平均"],
    "annotations": ["首次异常点"]
  },
  "created_at": "..."
}
```

### 5.2 Graph 能力

Artifact Graph 需要回答：

- 这个产物是谁生成的？
- 读取了哪些输入数据？
- 使用了哪段脚本？
- 生成时 stdout 里有什么关键结论？
- 报告中哪里引用了它？
- 这个文件可以如何预览？
- 它是否仍然存在且 hash 是否一致？

有了这个图，agent 才能可靠地处理产物追问。

## 六、关键 Skills 设计

### 6.1 spreadsheet_analysis

用途：结构化办公数据分析。

触发条件：

- 用户上传 Excel / CSV / Sheets。
- 用户要求统计、筛选、排名、趋势、异常、归因、导出。

强约束：

- 必须使用 ingest / normalize / profile。
- 明细计算必须走 sandbox 或 query tool。
- 不允许把原始明细直接塞给 LLM。
- 输出文件必须登记 artifact。
- 结果必须 validate。

### 6.2 artifact_qa

用途：解释已生成产物。

触发条件：

- 用户提到文件名、图表、附件、导出表、报告。
- 用户问“这个图是什么意思”“这个表怎么看”“这个文件里是什么”。

流程：

```text
1. artifact.list
2. 根据文件名、kind、时间、producer step 匹配 artifact
3. artifact.inspect
4. 如果是 chart/image，提取 chart_metadata 或调用视觉检查
5. 结合 producer stdout、script、source_tables 回答
6. 明确说明数据来源、图表含义、局限和下一步可分析方向
```

### 6.3 chart_interpretation

用途：图表解读和图表质量检查。

能力：

- 提取标题、轴、图例、标注。
- 判断图表类型。
- 说明趋势、异常、分组差异。
- 检查图表是否缺少单位、标题、图例或可读性问题。

### 6.4 report_generation

用途：把分析结果组织成报告、周报、日报、汇报材料。

强约束：

- 报告只能引用已验证结果。
- 报告中的图表引用必须来自 Artifact Graph。
- 数据口径、时间范围、字段含义必须显式说明。

### 6.5 workflow_automation

用途：沉淀可复用办公流程。

示例：

- 每日巡检日报。
- 经营周报。
- 预算执行月报。
- 销售漏斗分析。
- 应收账款账龄分析。

## 七、上下文与记忆

平台需要三类上下文。

### 7.1 Run Context

单次运行内上下文，包含：

- user_query
- selected skill
- tool calls
- tool results
- validation status
- artifacts
- final answer

### 7.2 Conversation Context

会话内上下文，包含：

- 已上传文件
- 已生成 artifacts
- 已完成 runs
- 关键发现
- 对话摘要

### 7.3 Long-term Memory

跨会话记忆，包含：

- 常见 schema 指纹
- 常用维度、时间字段、金额字段
- 用户偏好的报告格式
- 团队常用指标口径
- 历史评测结果

长期记忆不能替代当前文件事实。它只能作为规划辅助，最终计算仍以当前 normalized data 为准。

## 八、运行生命周期

```text
1. UserMessageReceived
2. IntentRouter 选择 skill
3. SkillContextBuilder 注入相关上下文
4. AgentRuntime 规划工具调用
5. ToolRegistry 执行 typed tools
6. ResultValidator 校验关键结果
7. ArtifactGraph 写入产物和血缘
8. ResponseComposer 生成回答
9. EventStream 推送给前端
10. EvalLogger 记录可回放数据
```

## 九、安全与边界

平台化后必须保留现有安全边界：

- 原始文件不可变。
- LLM 只看摘要和样本，不直接搬运全量数据。
- 代码执行必须进沙箱。
- 产物只能写 output/。
- normalized/ 默认只读。
- Planner 不能选择未注册工具。
- 工具不能访问 workspace 外文件，除非显式授权。
- API key 只能通过环境变量注入。

如果引入 Pi，仍需要保留 Python 后端的 sandbox、path protection 和 artifact resolver。Pi 负责 agent runtime，不负责数据安全边界。

## 十、与当前系统的映射

| 当前模块 | 平台化角色 |
|---|---|
| `WorkbookIngestor` | `spreadsheet.ingest_workbook` |
| `ExcelPreprocessor` | `spreadsheet.normalize_tables` |
| `Profiler` | `spreadsheet.profile_tables` |
| `PythonSandbox` | `code.run_python_sandboxed` |
| `ResultChecker` | `result.validate` |
| `Workspace` | Data Plane workspace |
| `artifact_manifest.json` | Artifact Graph v0 |
| `Session` | Conversation Context v0 |
| `Memory` | Long-term Memory v0 |
| `Orchestrator` | 将被 Agent Runtime + Skills + ToolRegistry 逐步替代 |
| FastAPI WebSocket events | EventStream v0 |
| React Artifact Panel | Artifact experience v0 |

### 10.1 当前探索分支实现映射

本分支已经把平台化骨架落到代码中，保留现有 Excel 分析链路作为默认执行路径：

| 平台化组件 | 当前实现 |
|---|---|
| ToolRegistry | `app/tools/registry.py`，注册 planner-visible 的 `python`、`artifact_qa`，同时保留 typed tool alias |
| Skills v1 | `app/skills/registry.py` 和 `skills/*/SKILL.md` |
| Intent Router | 基于用户 query、当前 artifact manifest 和文件上下文选择 `spreadsheet_analysis`、`artifact_qa` 或 `report_generation` |
| Artifact Graph v1 | `Workspace.register_artifact()` 扩展 metadata，API persistence 增加 `metadata` JSON 字段 |
| Artifact QA | `app/agent/artifact_qa.py`，按文件名/血缘/脚本提示解释已生成产物 |
| Agent Runtime v1 | `app/agent/runtime.py`，FastAPI runner 通过 runtime adapter 调用 Orchestrator，并预留 Pi sidecar transport |
| Artifact Panel | 前端 artifact 类型和列表展示支持 producer/source metadata、normalized table 预览 |

当前实现仍把 Python sandbox、Excel 预处理、结果校验和报告生成留在 Python 后端。Pi sidecar 是可测试适配层，后续可替换通用 agent loop，但不能绕过后端 typed tools 和 Artifact Graph。

## 十一、设计原则

- Harness 通用化，工具领域化。
- Skill 约束流程，Tool 保障边界。
- Agent 可以规划，但不能绕过工具协议。
- 所有用户可见结论必须能追溯到数据、脚本或产物。
- 所有产物都进入 Artifact Graph。
- 每一步都可回放、可评测、可修复。
- ChatExcel 是第一个 skill，不是最终产品边界。
