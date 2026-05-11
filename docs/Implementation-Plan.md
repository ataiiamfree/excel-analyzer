# Excel 智能分析 Agent - 实施计划

> 当前实施目标：**个人/内网单用户 robust 程序**。暂不实现企业级鉴权、RBAC、多租户、审计、Redis/Celery 分布式队列、对象存储。优先把核心体验做稳：Excel 识别准确、代码执行可控、任务可恢复、结果可校验、产物可追溯。

## 〇、架构升级：从 Plan-Execute 到 Adaptive Plan-Execute

### 问题：纯 Plan-then-Execute 不够灵活

纯 Plan-Execute 在规划时还没看到任何数据结果，后面的步骤可能完全不靠谱：

```
用户："分析采购时长，找出异常并深入分析"

纯 Plan-Execute 的问题：
  Plan 阶段（还没看到数据）：
    Step 1: 计算采购时长
    Step 2: 整体统计
    Step 3: 对超过 60天的项目做分析     ← 60天这个阈值是瞎猜的
    Step 4: 分析异常原因按地区分布       ← 不知道数据里有没有地区字段
    Step 5: ...

  实际执行到 Step 2 发现：平均时长 42天，标准差 28天，合理阈值应该是 98天
  但 Plan 已经写死了 60天 → 后续步骤都是错的
```

### 解法：Adaptive Plan-Execute（滚动规划）

**不是一次规划所有步骤，而是：先粗略规划全局，每执行完一步后根据结果细化下一步。**

```
三种模式的对比：

ReAct（完全没有规划）：
  想一步 → 做一步 → 想一步 → 做一步 → ...
  问题：走弯路、token 爆掉

Plan-Execute（一次性规划）：
  想好所有步骤 → 做步骤1 → 做步骤2 → ... → 做步骤N
  问题：后面的步骤可能因为信息不足而规划得不对

Adaptive Plan-Execute（滚动规划）：      ← 我们采用这个
  粗略规划全局 → 细化步骤1 → 执行 → 根据结果细化步骤2 → 执行 → ...
  每步都有全局视野，每步都能根据实际数据调整
```

### 核心机制：Plan → Execute → Adapt 循环

```
┌────────────────────────────────────────────────────────────┐
│                   Adaptive Plan-Execute                    │
│                                                            │
│   ┌──────────┐                                             │
│   │ 初始规划  │  粗略规划：列出大致步骤和目标                  │
│   │ (Sketch) │  不细化具体参数和阈值                         │
│   └────┬─────┘  1 次 LLM 调用，~3K tokens                  │
│        │                                                   │
│        ▼                                                   │
│   ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐              │
│   │          每步循环                        │              │
│   │                                         │              │
│   │  ┌──────────┐                           │              │
│   │  │ 细化当前步│  根据前面结果细化当前步骤    │              │
│   │  │ (Refine) │  生成具体的代码/指令         │              │
│   │  └────┬─────┘  1 次 LLM 调用             │              │
│   │       │                                  │              │
│   │       ▼                                  │              │
│   │  ┌──────────┐                           │              │
│   │  │  执行     │  沙箱执行代码              │              │
│   │  │(Execute) │  0 次 LLM 调用             │              │
│   │  └────┬─────┘                           │              │
│   │       │                                  │              │
│   │       ▼                                  │              │
│   │  ┌──────────┐                           │              │
│   │  │  适应调整  │  看结果，决定：             │              │
│   │  │ (Adapt)  │  - 下一步是否需要调整？      │              │
│   │  └────┬─────┘  - 需要插入新步骤吗？        │              │
│   │       │        - 需要删除后续步骤吗？       │              │
│   │       │        1 次轻量 LLM 调用           │              │
│   │       │                                  │              │
│   │       ▼                                  │              │
│   │    下一步                                 │              │
│   └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘              │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### Adapt 阶段的实现

Adapt 是一次**轻量级 LLM 调用**，只做决策，不生成代码：

```python
async def _adapt(self, context: TaskContext, step_result: StepResult,
                 current_step: Step) -> PlanAdjustment:
    """执行完一步后，决定是否调整后续计划"""
    prompt = f"""你是任务规划助手。刚执行完一个步骤，请根据结果决定后续计划是否需要调整。

## 当前执行结果
步骤: {current_step.description}
结果摘要: {step_result.summary}

## 剩余计划
{context.plan.remaining_steps_overview()}

## 判断
请回答以下问题（JSON格式）：
1. 下一步的描述是否需要根据当前结果调整？如需要，给出调整后的描述。
2. 是否需要在后续插入新步骤？
3. 是否有后续步骤可以跳过？

{{"next_step_adjusted": "调整后的描述 或 null",
  "insert_steps": [步骤描述] 或 [],
  "skip_steps": [步骤id] 或 [],
  "reasoning": "一句话说明调整原因"}}"""

    response = await self.llm.call(prompt, max_tokens=500)  # 轻量调用
    return self._parse_adjustment(response)
```

**Token 消耗：每次 Adapt 约 1.5K tokens（输入 ~1K + 输出 ~500）。**

### 实际例子：Adapt 如何工作

```
用户："分析采购时长，找出异常并深入分析"

=== 初始规划（Sketch）===
  s1: 计算采购时长
  s2: 整体统计分析
  s3: 识别异常项目（待定：需要根据 s2 的结果确定阈值）
  s4: 异常项目深入分析
  s5: 生成报告

=== 执行 s1 → 完成 ===
stdout: "新增采购时长列，范围 3~186天"
Adapt: 下一步无需调整。

=== 执行 s2 → 完成 ===
stdout: "平均 42.3天，中位数 35天，标准差 28.7天，P95=98天"
Adapt 判断:
  {
    "next_step_adjusted": "识别超过 98天（P95）的项目作为异常项目",
                          ← 用实际数据替代了猜测的阈值
    "insert_steps": ["按承办部门分析异常分布"],
                     ← 发现数据中有承办部门字段，值得分析
    "skip_steps": [],
    "reasoning": "P95=98天作为异常阈值更合理，新增部门维度分析"
  }

=== 执行 s3（已调整）→ 完成 ===
stdout: "超过98天的异常项目 23 个，集中在工程类和公开招标"
Adapt 判断:
  {
    "next_step_adjusted": "深入分析工程类和公开招标的异常原因",
                          ← 根据 s3 发现聚焦到具体类别
    "insert_steps": [],
    "skip_steps": [],
    "reasoning": "异常集中在工程类和公开招标，深入分析应聚焦这两类"
  }

=== 继续执行 ... ===
```

### 与 ReAct 的关键区别

虽然 Adaptive Plan-Execute 也有"看结果 → 调整"的循环，但和 ReAct 有本质不同：

| | ReAct | Adaptive Plan-Execute |
|---|---|---|
| 有全局计划吗 | 没有，走一步看一步 | 有，始终有全局规划视野 |
| 调整在哪里发生 | 在累积的长对话中 | 在独立的轻量调用中 |
| 调整的 token 成本 | 整个上下文重新处理 | 每次 ~1.5K 的独立调用 |
| 上下文会膨胀吗 | 会，越调越长 | 不会，每次调用独立释放 |

### Token 消耗对比（更新）

```
5 步任务的总 token 消耗：

ReAct:
  5轮循环在同一对话中 = 30K-48K tokens（单一对话）

纯 Plan-Execute:
  Plan ×1 + CodeGen ×5 = ~30K tokens（分散在 6 次调用中）

Adaptive Plan-Execute:
  Sketch ×1 + (CodeGen + Adapt) ×5 = ~38K tokens（分散在 11 次调用中）
  每次调用 ≤ 5K tokens

  多花了 ~8K tokens（5次 Adapt），但换来了：
  - 计划能根据实际数据调整
  - 不会用错误的阈值/假设执行后续步骤
  - 仍然保持每次调用独立、上下文不膨胀
```

### 何时触发 Adapt，何时跳过

不是每一步都需要 Adapt。简单步骤可以跳过以节省 token：

```python
def _should_adapt(self, step: Step, step_result: StepResult,
                  remaining_steps: int) -> bool:
    """判断是否需要执行 Adapt"""
    # 最后一步不需要 Adapt
    if remaining_steps == 0:
        return False
    # 步骤失败了，必须 Adapt
    if step_result.failed:
        return True
    # 探索性步骤（统计、EDA）之后需要 Adapt
    if step.is_exploratory:
        return True
    # stdout 中出现异常/意外信息时 Adapt
    if self._has_unexpected_findings(step_result.stdout):
        return True
    # 其他情况跳过
    return False
```

---

## 一、实施阶段总览

```
Phase 1: 基础骨架 + 本地任务状态      ← 能跑起来、可复现（2天）
Phase 2: WorkbookIngestor            ← 能理解多 sheet / 多表（3天）
Phase 3: Excel 预处理与标准化输出      ← 脏 Excel 能稳健变 normalized tables（3天）
Phase 4: 核心 Pipeline + 执行器        ← 单步分析能用、执行可控（3天）
Phase 5: TaskContext + Artifact       ← 多步分析能用、产物可追溯（2天）
Phase 6: Adaptive + ResultChecker     ← 能动态调整、能发现跑通但不对（3天）
Phase 7: Reporter                     ← 能生成报告（2天）
Phase 8: Chainlit + Session + 记忆     ← 能聊天交互、追问、记住偏好（2天）
Phase 9: 加固与测试                   ← 稳定性压测与脏 Excel 回归（3天）
```

每个 Phase 结束时都有可验证的交付物。

---

## 二、Phase 1: 基础骨架（能跑起来）

### 目标
搭建项目结构，LLM 调用跑通，能发送 prompt 收到回复。

### Step 1.1: 项目初始化
```bash
excel-analyzer/
├── app/
│   ├── __init__.py
│   ├── workspace.py
│   ├── agent/
│   │   └── __init__.py
│   ├── context/
│   │   └── __init__.py
│   ├── tools/
│   │   └── __init__.py
│   ├── llm/
│   │   └── __init__.py
│   └── prompts/
├── static/
├── workspace/
│   └── .gitkeep
├── tests/
│   ├── fixtures/
│   └── __init__.py
├── docs/
├── requirements.txt
└── README.md
```

### Step 1.2: requirements.txt
```
fastapi>=0.104.0
uvicorn>=0.24.0
python-multipart>=0.0.6
httpx>=0.25.0
pandas>=2.1.0
openpyxl>=3.1.0
pyarrow>=14.0.0
matplotlib>=3.8.0
tiktoken>=0.5.0
pydantic>=2.5.0
psutil>=5.9.0
```

### Step 1.3: LLM Client
文件：`app/llm/client.py`

实现要点：
- 兼容 OpenAI API 格式（vLLM / Ollama 都支持此格式）
- `base_url` 和 `model` 可配置，方便后续更换模型
- 异步调用（async/await）
- 超时处理（默认 120 秒）
- 简单的 token 计数（用 tiktoken 或字符数估算）
- 响应解析：提取 content 字段

接口定义：
```python
class LLMClient:
    async def call(self, prompt: str, max_tokens: int = 2000,
                   temperature: float = 0.1) -> str: ...
    def count_tokens(self, text: str) -> int: ...
```

### Step 1.4: 基础配置
文件：`app/config.py`

```python
import os
from dataclasses import dataclass

@dataclass
class Config:
    # LLM 配置
    llm_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    llm_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    llm_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    # 不要把 sk-... 写进代码或文档；本地用 .env / shell 环境变量注入

    # Token 预算方案: "standard"(32K窗口) | "generous"(128K+窗口) | "deepseek"(DeepSeek V4 Pro)
    budget_preset: str = os.getenv("BUDGET_PRESET", "generous")

    # 工作空间
    workspace_dir: str = "./workspace"
    sandbox_timeout: int = 60
    sandbox_memory_mb: int = 1024
    max_stdout_chars: int = 20000
    max_repair_attempts: int = 2
    max_file_size_mb: int = 100
    max_concurrent_tasks: int = 1  # 单用户版本先串行/小并发，避免本机资源打满
```

### Step 1.5: Workspace 管理
文件：`app/workspace.py`

实现要点：
- 每个任务创建独立目录：`workspace/{task_id}/`
- 子目录：`raw/`（原始上传，只读保留）、`normalized/`（标准化表格）、`output/`（用户结果）、`scripts/`（生成代码）、`logs/`（stdout/stderr）
- `state.json`：保存 `status/current_step/error/started_at/finished_at/retry_count`
- `artifact_manifest.json`：保存 `{path, kind, producer_step, inputs, schema, row_count, description}`
- 文件列表方法：返回 manifest 中登记的文件，附 size/type/preview 信息
- `record_code()`：每次 LLM 生成或修复的脚本都保存，不覆盖旧 attempt
- 清理方法：删除过期任务目录，但默认保留最近 N 个任务，方便 debug
- 本地任务状态可以用 JSON 文件，不需要 Redis/数据库

### 验证点
```python
# 能调通 LLM 并返回结果
client = LLMClient(base_url="...", model="...")
response = await client.call("你好，请返回 hello")
assert len(response) > 0
```

---

## 三、Phase 2: WorkbookIngestor（能理解多 sheet / 多表）

### 目标
先理解 Excel workbook 的结构，不急着读成 DataFrame。输出 `workbook_manifest.json`，后续预处理、画像、Planner 都基于 manifest 工作。

### Step 2.1: WorkbookIngestor 核心
文件：`app/tools/workbook_ingestor.py`

实现要点：
- 用 openpyxl 读取 workbook 结构，不修改原始文件。
- 扫描每个 sheet 的：最大行列、隐藏行列、合并单元格、公式单元格、非空矩阵、样式边界。
- 检测 table candidates：连续非空区域、空行/空列分隔、明显边框区域。
- 为每个 candidate 输出：`table_id`, `sheet_name`, `range`, `header_candidates`, `confidence`, `warnings`。
- 多 sheet 和多表合一都要进入 manifest，不能默认只取第一个 sheet。

接口定义：
```python
class WorkbookIngestor:
    def scan(self, file_path: str) -> dict:
        """返回 workbook_manifest，并写入 workspace/workbook_manifest.json"""
        ...
```

### Step 2.2: 表格区域检测规则
核心判断逻辑：
```
对每个 sheet：
  建立非空 cell mask
  找连续非空块 / 空行空列分隔带
  对每个块生成 table candidate
  扫描前 20 行作为 header candidate
  计算置信度和 warnings
```

### Step 2.3: 测试用例
准备 6 种 workbook fixture：
1. 单 sheet 单表。
2. 多 sheet，每个 sheet 一个表。
3. 一个 sheet 多个表，中间空行分隔。
4. 有标题行、脚注、隐藏列。
5. 合并单元格跨标题和数据区。
6. 含公式列和格式化数字。

### 验证点
```bash
python -m app.tools.workbook_ingestor --file messy_workbook.xlsx
# 期望：输出 workbook_manifest.json
# manifest 能列出所有 sheet 和 table candidate，且不修改原始文件
```

---

## 四、Phase 3: Excel 预处理与标准化输出（脏 Excel 能清洗）

### 目标
基于 workbook manifest，把每个 table candidate 变成可分析的 normalized table，同时保留 raw 文件和 source lineage。

### Step 3.1: ExcelPreprocessor 核心
文件：`app/tools/excel_preprocessor.py`

实现要点：
- 双层遍历 manifest 结构 `files[].sheets[].tables[]`，针对每个 table candidate 读取区域。
- 拆分合并单元格并用左上角值填充，但只在 working copy 中处理。
- 表头检测返回候选和置信度，不只返回一个行号。
- 多层表头合并为单层（"采购金额" + "计划" → "采购金额_计划"）。
- 标记标题行、空行、汇总行、脚注；不要静默删除原始数据。
- 输出 `normalized/{table_id}.parquet` 和 `normalized/{table_id}_preview.xlsx`。
- 每行保留 `_source_file`, `_source_sheet`, `_source_row`，方便追溯。
- 返回 `PreprocessResult(tables, report, warnings)`。

接口定义：
```python
class ExcelPreprocessor:
    def process(self, file_path: str, manifest: dict) -> PreprocessResult:
        """返回多个 NormalizedTable，而不是单个 _clean.xlsx"""
        ...
```

### Step 3.2: LLM 兜底判断（可选）
当规则引擎置信度低时：
- 取目标 table candidate 前 10 行、最多 15 列的文本形式。
- 轻量 LLM 调用（~1K tokens）：只判断表头/标题/汇总/数据起始行。
- LLM 只返回 JSON，不直接修改数据。

### Step 3.3: 测试用例
准备典型脏格式：
1. 正常格式（无需清洗，验证不会误处理）。
2. 有 3 行标题 + 合并单元格。
3. 双层表头 + 末尾汇总行。
4. 数据中间有分类合并单元格 + 中间汇总行。
5. 有脚注 + 隐藏列。
6. 表内有“合计”作为正常业务值，不能误删。

### 验证点
```bash
python -m app.tools.excel_preprocessor --file messy_data.xlsx
# 期望：输出 normalized/*.parquet + *_preview.xlsx + preprocess_report.json
# pandas.read_parquet() 能正确读取，列名正确，source lineage 存在
```

---

## 五、Phase 4: 核心 Pipeline + 执行器（单步分析能用）

### 目标
上传 Excel → 扫描 workbook → 预处理成 normalized tables → 生成画像 → 生成代码 → 可控执行 → 返回结果。一步到位，不分步。

### Step 4.1: Profiler（数据画像）
文件：`app/tools/profiler.py`

实现要点：
- 读取 `PreprocessResult.tables`，对每个 normalized table 生成画像
- 提取：table_id、source sheet/range、行数、列数、warnings
- 每列：名称、类型、空值率、样本值
- 数值列：min/max/mean
- 分类列：唯一值数量 + 前 3 个样本
- 日期列：时间范围
- **列名分组压缩**：检测数字模式（如 1月~12月），合并为一条
- 输出 JSON，大表/宽表时分层压缩，控制在预算内

接口定义：
```python
class Profiler:
    def profile(self, tables: list[NormalizedTable]) -> dict: ...
```

### Step 4.2: Python Sandbox（代码执行）
文件：`app/tools/python_sandbox.py`

实现要点：
- `subprocess.run()` 执行 Python 脚本，后续可选 Docker
- 工作目录设为任务的 workspace，只读 raw/normalized，写 output/
- 每次脚本保存到 `scripts/{step_id}_attempt_{n}.py`
- 运行前做轻量静态检查：禁止 `os.system/subprocess/shutil.rmtree/requests/socket` 等不必要调用
- 超时控制（默认 60 秒）
- 内存限制（默认 1GB，Unix 下用 `resource`，否则用 psutil 监控）
- stdout/stderr 截断，防止巨量输出撑爆上下文
- 捕获 stdout 和 stderr
- 收集 output/ 目录下生成的文件列表
- 返回结构化结果：`ExecResult(success, stdout, stderr, output_files, script_path)`

接口定义：
```python
class PythonSandbox:
    def execute(self, code: str, workdir: str,
                step_id: str, attempt: int = 0,
                timeout: int = 60) -> ExecResult: ...
```

### Step 4.3: 单步代码生成 + 执行
文件：`app/agent/simple_pipeline.py`

这是一个简化版流程，不含 TaskContext 和 Adaptive 机制，用于验证基础能力：

```python
async def analyze_simple(llm, profiler, sandbox, workspace, query):
    # 1. workbook 扫描 + 标准化
    manifest = ingestor.scan(workspace.raw_path)
    preprocess_result = preprocessor.process(workspace.raw_path, manifest)
    # 2. 画像
    profile = profiler.profile(preprocess_result.tables)
    # 3. 生成代码
    prompt = build_codegen_prompt(profile, query)
    code = await llm.call(prompt)
    code = extract_code_block(code)
    # 4. 执行
    result = sandbox.execute(code, workspace.path, step_id="simple")
    # 5. 失败重试
    if not result.success:
        repair_prompt = build_repair_prompt(profile, code, result.stderr)
        code = await llm.call(repair_prompt)
        code = extract_code_block(code)
        result = sandbox.execute(code, workspace.path, step_id="simple", attempt=1)
    return result
```

### Step 4.4: Prompt 模板
文件：`app/prompts/system_codegen.md`

```markdown
你是一个 Python 数据分析专家。根据数据概况和用户问题，生成完整可执行的 Python 脚本。

## 规则
1. 优先读取数据画像中给出的 normalized parquet 路径，例如 pd.read_parquet("normalized/t1.parquet")
2. 如果有多个 table，先根据用户问题选择 table，并在 print 中说明选择依据
3. 图表用 matplotlib，保存到 "output/" 目录，不要 plt.show()
4. 中文显示：plt.rcParams['font.sans-serif'] = ['SimHei']
5. 用 print() 输出关键数字、口径和结论
6. 结果超过 20 行就用 to_excel() 写文件，不要 print 全部
7. 导出的结果必须写入 output/，并尽量保留 source lineage 列
8. 直接输出完整脚本，不要解释
```

文件：`app/prompts/system_repair.md`

```markdown
代码执行失败，请修正。只输出修正后的完整 Python 脚本，不要解释。
```

### Step 4.5: 代码块提取工具
文件：`app/utils.py`

```python
def extract_code_block(text: str) -> str:
    """从 LLM 回复中提取 python 代码块"""
    # 匹配 ```python ... ``` 或 ``` ... ```
    # 如果没有代码块标记，返回原文（可能整个回复就是代码）
```

### 验证点
```bash
# 能上传 Excel，生成分析代码，执行并返回结果
python -m app.agent.simple_pipeline \
  --file test_data.xlsx \
  --query "统计各列的基本信息"
# 期望：workspace 下有 workbook_manifest/profile/scripts/logs/artifact_manifest
# stdout 中有统计结果，output/ 中有图表或导出文件
```

---

## 六、Phase 5: TaskContext + Artifact Manifest（多步分析能用）

### 目标
实现 TaskContext、Artifact Manifest 和 PromptAssembler，支持多步执行。步骤间通过摘要 + 文件产物 + lineage 传递上下文。

### Step 5.1: TaskContext 数据结构
文件：`app/context/task_context.py`

实现要点：
- 固定区：`user_query`, `data_profile`, `plan`
- 固定区增加：`workbook_manifest`
- 摘要区：`step_summaries`（OrderedDict），`key_findings`（list）
- 产物区：`workspace_files`（list），`artifact_manifest`（list），`quality_checks`（list），`code_history`（list）
- Token 预算常量
- `add_step_summary()` 方法：添加摘要 + 自动控制大小
- `_compress_oldest_summaries()` 方法：合并最老摘要
- `update_workspace_files()` 方法
- `update_artifacts()` 方法：从 `artifact_manifest.json` 更新产物清单

### Step 5.2: Summary Extractor（摘要提取）
文件：`app/context/summary_extractor.py`

实现要点：
- 纯规则，不调 LLM
- 从 stdout 中提取关键行（含数字、等号、冒号的行）
- 限制 200 字
- 提取关键发现（含特定模式的行：总计/平均/最大/异常/发现）

```python
def extract_summary(stdout: str, max_chars: int = 200) -> str: ...
def extract_findings(stdout: str, max_items: int = 5) -> list[str]: ...
```

### Step 5.3: Artifact Manifest
文件：`app/workspace.py` 或 `app/context/artifacts.py`

实现要点：
- 每次预处理、代码执行、报告生成后都登记 artifact。
- 字段：`path`, `kind`, `description`, `producer_step`, `inputs`, `schema`, `row_count`, `created_at`。
- prompt 中只放 artifact 的描述、路径、行数和 schema，不放内容。
- 文件下载/预览只能读取 manifest 中登记的文件。

```python
def register_artifact(path: str, kind: str, producer_step: str,
                      inputs: list[str], description: str = "") -> None: ...
def read_artifact_manifest() -> list[dict]: ...
```

### Step 5.4: PromptAssembler
文件：`app/context/prompt_assembler.py`

实现要点：
- `assemble(context, step)` → 组装完整 prompt
- 按区域拼接：系统指令 + 用户问题 + 画像 + 计划概览 + 摘要 + 发现 + 文件 + 当前指令
- 最终 token 检查：超 4K 则循环压缩摘要区
- `assemble_repair(context, step, code, stderr)` → 修复 prompt

### Step 5.5: ExecutionPlan 数据结构
文件：`app/agent/plan.py`

```python
@dataclass
class Step:
    id: str
    tool: str            # 对应 Orchestrator.executors 的 key: "python" | "knowledge" | 后续扩展 "graph_rag" 等
    description: str     # 步骤描述
    instruction: str     # 详细指令（给代码生成用）
    depends_on: list     # 依赖的步骤 ID
    is_exploratory: bool # 是否是探索性步骤（影响是否触发 Adapt）
    expected_outputs: list[dict]  # 期望产物：图表、表格、字段、行数约束等
    status: str          # "pending" | "running" | "done" | "failed" | "skipped"

@dataclass
class ExecutionPlan:
    steps: list[Step]
    report_outline: list[dict]  # 报告大纲（可选）

    def next_runnable_step(self) -> Step | None: ...
    def remaining_steps(self) -> list[Step]: ...
    def remaining_steps_overview(self) -> str: ...
    def mark_done(self, step_id: str, check: str = "passed"): ...
    def adjust_step(self, step_id: str, new_instruction: str): ...
    def insert_after(self, after_id: str, new_step: Step): ...
    def skip_step(self, step_id: str): ...
```

### Step 5.6: Planner（规划器）
文件：`app/agent/planner.py`

实现要点：
- `sketch(context)` → 初始粗略规划，返回 ExecutionPlan
- 解析 LLM 返回的 JSON 计划
- 容错：JSON 解析失败时尝试提取关键信息

Prompt 模板（`app/prompts/system_planner.md`）：
```markdown
你是一个数据分析任务规划专家。根据用户需求和数据结构，制定分步执行计划。

## 规则
1. 每个步骤应当是独立的、可执行的
2. 探索性步骤（统计分析、EDA）标记为 is_exploratory: true
3. 后续步骤的具体参数如果依赖前面的结果，用"待定"标注，执行时会根据实际结果细化
4. 每个步骤必须声明 expected_outputs，便于 ResultChecker 校验
5. 步骤数量控制在 3-8 步
6. 如果用户要求生成报告，在最后添加 report_outline

输出 JSON 格式的执行计划。
```

### Step 5.7: Orchestrator（基础版）
文件：`app/agent/orchestrator.py`

实现要点：
- 驱动 Profiler → Planner → 逐步执行 的流程
- 主循环用 `while plan.next_runnable_step()`，不要遍历时修改 `plan.steps`
- `_execute_step` 通过 `self.executors` 字典分发，不用 if/elif（见 Design.md §4.1.1 Skill 扩展机制）
- v1 注册两个内置执行器：`python`（代码生成+沙箱执行）和 `knowledge`（向量检索）
- 后续新增 Skill（如 `graph_rag`）只需写执行器方法 + 注册一行
- 每步执行后更新 TaskContext
- 每步执行后更新 artifact manifest 和 state.json
- 失败重试（Repair）
- 暂不含 Adapt 机制（Phase 6 加入）

### 验证点
```bash
# 多步任务能正确执行，步骤间通过摘要传递信息
python -m app.agent.orchestrator \
  --file 采购台账.xlsx \
  --query "计算采购时长并按项目类别分组统计"
# 期望：
#   Plan: [计算时长, 分组统计]
#   Step 1 完成，摘要存入 TaskContext
#   Step 2 的 prompt 中包含 Step 1 的摘要
#   最终输出统计结果
```

---

## 七、Phase 6: Adaptive + ResultChecker（智能调整计划 + 结果校验）

### 目标
在 Orchestrator 中加入 ResultChecker 和 Adapt 机制：每步执行后先校验结果，再根据结果动态调整后续计划。

### Step 6.1: ResultChecker
文件：`app/tools/result_checker.py`

实现要点：
- 检查进程是否成功、stdout 是否为空、stderr 是否有严重 warning。
- 检查 `expected_outputs` 是否存在：图表、Excel、parquet、报告片段等。
- 检查输出文件是否可读、是否登记到 artifact manifest。
- 对表格输出检查 row_count/schema；筛选结果行数不能大于输入表，聚合结果关键列不能全空。
- 返回 `CheckResult(status, checks, warnings)`。
- `failed` 时触发 repair；`warning` 时继续执行但写入报告提示。

```python
class ResultChecker:
    def validate(self, step: Step, exec_result: ExecResult,
                 context: TaskContext, workspace) -> CheckResult: ...
```

### Step 6.2: Adapt 调用
文件：在 `app/agent/orchestrator.py` 中添加

```python
async def _adapt(self, context, step, step_result) -> PlanAdjustment: ...
```

实现要点：
- 轻量 LLM 调用（max_tokens=500）
- 输入：当前步骤结果摘要 + 剩余计划概览
- 输出：JSON 格式的调整指令
- 解析调整指令，更新 ExecutionPlan

### Step 6.3: Adapt 触发判断
```python
def _should_adapt(self, step, step_result, remaining_steps) -> bool: ...
```

规则：
- 最后一步 → 不 Adapt
- 步骤失败 → 必须 Adapt
- ResultChecker failed/warning → 必须 Adapt 或 Repair
- 探索性步骤（`is_exploratory=True`）→ Adapt
- stdout 中出现"异常"/"意外"/"发现"等关键词 → Adapt
- 其他情况 → 跳过 Adapt，节省 token

### Step 6.4: Adapt Prompt
文件：`app/prompts/system_adapt.md`

```markdown
你是任务规划助手。刚执行完一个分析步骤，请根据结果判断后续计划是否需要调整。

## 判断原则
- 如果结果揭示了新的信息（如具体阈值、数据分布特征），后续步骤应该利用这些信息
- 如果发现了计划中未预料到的情况，可以插入新步骤
- 如果发现某些计划步骤已经没有必要，可以跳过

只输出 JSON，不要解释。
```

### Step 6.5: Plan 调整执行
在 `ExecutionPlan` 中实现：
- `adjust_step()` → 修改某步的 instruction
- `insert_after()` → 在某步后插入新步骤
- `skip_step()` → 标记某步为跳过

### Step 6.6: 更新 Orchestrator 主循环

```python
while True:
    step = plan.next_runnable_step()
    if step is None:
        break

    result = await self._execute_step(step, context, workspace)
    check = checker.validate(step, result, context, workspace)

    # check 失败时先尝试 repair
    if check.status == "failed" and not result.retries_exhausted:
        result = await self._repair_from_check(step, result, check, context, workspace)
        check = checker.validate(step, result, context, workspace)

    context.add_step_summary(step.id, result.stdout, step.description)
    context.update_workspace_files(workspace.list_files())
    context.update_artifacts(workspace.read_artifact_manifest())
    plan.mark_done(step.id, check=check.status)

    # repair 后仍然失败 → 重新规划
    if (result.failed or check.status == "failed") and result.retries_exhausted:
        plan = await self._replan(context, step, result.error)
        continue

    # Adaptive: 根据结果调整后续计划
    if self._should_adapt(step, result, plan.remaining_steps()):
        adjustment = await self._adapt(context, step, result)
        plan.apply_adjustment(adjustment)
```

### 验证点
```bash
# 验证 Adapt 能根据实际数据调整计划
python -m app.agent.orchestrator \
  --file 采购台账.xlsx \
  --query "分析采购时长，找出异常项目并深入分析"
# 期望：
#   初始计划 Step 3: "识别异常项目（阈值待定）"
#   执行 Step 2 后 Adapt: 将阈值调整为基于实际 P95 的值
#   Step 3 使用调整后的阈值执行
```

---

## 八、Phase 7: Reporter（能生成报告）

### 目标
支持分章节生成长报告，每章独立 LLM 调用。

### Step 7.1: Reporter
文件：`app/agent/reporter.py`

实现要点：
- 从 `ExecutionPlan.report_outline` 获取章节结构
- 每章收集对应的数据摘要（从 TaskContext.step_summaries）
- 每章独立 LLM 调用（~3K tokens 输入）
- 章节间衔接：传入上一章最后 200 字
- 最终拼接为完整报告

### Step 7.2: Reporter Prompt
文件：`app/prompts/system_reporter.md`

```markdown
你正在撰写数据分析报告的一个章节。

## 要求
- 行文专业、条理清晰
- 引用数据时标注具体数值
- 分析要有深度，不仅描述现象还要分析原因
- 与上下文章节保持连贯
```

### Step 7.3: 报告后处理
- 在报告中插入图表引用：`![描述](output/chart.png)`
- 在报告末尾添加附件列表（导出的 Excel 文件）
- 输出为 Markdown 格式

### 验证点
```bash
# 生成多章节报告
# 期望：每章内容连贯、数据引用准确、图表正确嵌入
```

---

## 九、Phase 8: Chainlit 交互层 + Session 管理（能给人用）

### 目标
提供聊天式 Web 界面（Chainlit），支持上传 Excel、自然语言提问、追问、查看分析进度和结果、下载文件。

### Step 8.1: Chainlit 入口
文件：`app/main.py`

实现要点：
- `@cl.on_chat_start`：弹出文件上传框，创建 Session
- `@cl.on_message`：接收用户消息，判断首次分析 vs 追问，调用 Orchestrator
- 每个分析步骤用 `cl.Step` 折叠展示进度
- 报告用 `cl.Message` 发送（Markdown 自动渲染）
- 图表用 `cl.Image`、文件下载用 `cl.File` 作为消息附件

```python
import chainlit as cl

@cl.on_chat_start
async def start():
    files = await cl.AskFileMessage(
        content="请上传 Excel 文件",
        accept=["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
        max_size_mb=100,
    ).send()
    session = Session.create(file=files[0])
    cl.user_session.set("session", session)
    await cl.Message(content=f"已上传 **{files[0].name}**，请输入你的分析需求。").send()

@cl.on_message
async def main(message: cl.Message):
    session = cl.user_session.get("session")
    is_follow_up = len(session.tasks) > 0

    orchestrator = build_orchestrator()
    result = await orchestrator.run(
        query=message.content,
        session=session,
    )

    # 发送报告
    await cl.Message(content=result.report).send()

    # 发送图表和文件
    elements = []
    for f in result.files:
        if f.endswith((".png", ".jpg")):
            elements.append(cl.Image(path=f, name=os.path.basename(f)))
        else:
            elements.append(cl.File(path=f, name=os.path.basename(f)))
    if elements:
        await cl.Message(content="分析产物：", elements=elements).send()
```

### Step 8.2: Session 管理
文件：`app/session.py`

实现要点：
- `Session` 数据类：session_id、file_path、tasks 列表、conversation_summary、accumulated_findings
- 首次分析后保存 profile、workbook_manifest、normalized_dir 到 session
- 追问时 `build_follow_up_context()` 返回前序任务的 profile + outputs + findings
- `update_after_task()` 追加 findings 和对话摘要
- 对话摘要限制长度（2000 字），超限截断保留最新部分

```python
@dataclass
class Session:
    session_id: str
    file_path: str
    tasks: list[str]
    conversation_summary: str
    accumulated_findings: list[str]
    workbook_manifest: dict | None = None
    profile: dict | None = None
    normalized_dir: str | None = None
```

### Step 8.3: Orchestrator 追问模式
文件：在 `app/agent/orchestrator.py` 中修改 `run()` 方法

追问时的执行流程：
```
首次: Ingestor → Preprocessor → Profiler → Plan → Execute → Report
追问: （复用 session 中的 profile + normalized）→ Plan → Execute → Report
```

实现要点：
- `run()` 接收 `session` 参数
- 如果 `session.profile is not None`（追问），跳过 Ingestor/Preprocessor/Profiler
- 追问的 TaskContext 额外包含 `prior_findings` 和 `conversation_summary`
- Planner prompt 中加入对话摘要，让 LLM 理解追问的上下文

### Step 8.4: 跨会话记忆
文件：`app/memory.py`

实现要点：
- 读写 `memory/user_memory.json`
- `match_schema(columns)` 用列名指纹匹配已知 schema
- `save_schema()` 保存新 schema（常用维度、时间/金额字段）
- `add_session_record()` 记录会话历史（最近 50 条）
- Profiler 调用 `match_schema()` 辅助列类型识别
- Planner 调用已知 schema 的"常用维度"辅助规划

### Step 8.5: Chainlit 配置
文件：`.chainlit/config.toml`

```toml
[project]
name = "Excel 智能分析"
enable_telemetry = false

[features]
prompt_playground = false

[UI]
name = "Excel 智能分析 Agent"
description = "上传 Excel，用自然语言分析数据"
```

### Step 8.6: Orchestrator 步骤进度回调

为了让 Chainlit 实时展示每步进度，Orchestrator 需要支持进度回调：

```python
# orchestrator.py
async def run(self, query, session, on_step_start=None, on_step_end=None):
    # ...
    while True:
        step = plan.next_runnable_step()
        if step is None:
            break
        if on_step_start:
            await on_step_start(step)
        result = await self._execute_step(step, context, workspace)
        if on_step_end:
            await on_step_end(step, result)
        # ...

# main.py 中传入回调
async def on_step_start(step):
    cl_step = cl.Step(name=step.description)
    await cl_step.__aenter__()
    cl.user_session.set("current_cl_step", cl_step)

async def on_step_end(step, result):
    cl_step = cl.user_session.get("current_cl_step")
    cl_step.output = result.summary
    await cl_step.__aexit__(None, None, None)
```

### 验证点
```bash
chainlit run app/main.py
# 浏览器打开 http://localhost:8000
# 1. 上传 Excel → 输入问题 → 看到分步进度 → 看到报告和图表
# 2. 追问 "再按部门细分" → 不重新上传，直接出新结果
# 3. 关闭浏览器重开 → 左侧看到历史会话
```

---

## 十、Phase 9: 加固与测试（个人 robust 版本稳定）

### Step 9.1: Token 预算强制执行
- PromptAssembler 中加入硬性检查
- 超预算时的降级策略验证
- 日志记录每次 LLM 调用的实际 token 消耗

### Step 9.2: 错误处理完善
- LLM 调用超时的处理
- LLM 返回格式异常的容错（JSON 解析失败等）
- 代码块提取失败的兜底
- 沙箱执行内存超限的处理
- stdout/stderr 巨量输出的截断
- ResultChecker failed/warning 的修复或降级策略
- 任务取消、服务重启后读取 state.json 的处理
- 全局异常捕获，返回友好错误信息

### Step 9.3: 测试用例

```
基础功能测试：
├── test_workbook_ingestor.py # 多 sheet、多表区域、隐藏行列、合并单元格
├── test_preprocessor.py      # 标准化输出、source lineage、汇总行标记
├── test_profiler.py          # 各种 Excel 格式（多 sheet、多列、日期、中文列名）
├── test_sandbox.py           # 正常执行、超时、报错
├── test_result_checker.py    # 缺文件、空输出、schema 不符、行数异常
├── test_artifact_manifest.py # 产物登记、预览、文件白名单
├── test_task_context.py      # 摘要添加、压缩、token 预算
├── test_prompt_assembler.py  # prompt 组装、超限裁剪
├── test_code_extractor.py    # 各种 LLM 回复格式的代码提取
└── test_summary_extractor.py # 各种 stdout 格式的摘要提取

集成测试：
├── test_simple_query.py      # "统计各列基本信息"
├── test_multi_step.py        # "计算采购时长并分组统计"
├── test_multi_sheet.py       # 多 sheet 中选择正确表
├── test_multi_table_sheet.py # 单 sheet 多表
├── test_summary_row_guard.py # 正常业务值包含"合计"时不能误删
├── test_large_columns.py     # 100+ 列的 Excel
├── test_detail_export.py     # 明细数据导出场景
├── test_report_generation.py # 长报告生成
├── test_repair.py            # 代码执行失败自愈
├── test_adapt.py             # Adapt 调整计划
├── test_follow_up.py         # 追问复用 profile，不重新预处理
├── test_session.py           # Session 创建、对话摘要、findings 累积
└── test_user_memory.py       # schema 匹配、偏好读写
```

### Step 9.4: 本地日志与可复现
- 日志格式统一使用 JSON Lines（每行一个 JSON），便于搜索和分析
- 日志分三类文件：`logs/llm_calls.jsonl`（LLM 调用）、`logs/steps.jsonl`（步骤执行）、`logs/system.jsonl`（系统事件）
- 每次 LLM 调用记录：prompt 长度、响应长度、耗时(ms)、token 消耗、调用类型
- 每步执行记录：步骤 ID、耗时、成功/失败、attempt 次数
- TaskContext 快照：每步执行后保存 context 状态（便于调试）
- 保存每次生成代码到 `scripts/`
- 保存 `state.json / plan.json / profile.json / artifact_manifest.json`
- 提供 `python -m app.agent.rerun --id ... --step ...` 便于单步复现

### Step 9.5: 配置外部化
- LLM 相关配置：base_url、model、temperature、max_tokens
- Token 预算配置：各区域预算可调
- 沙箱配置：超时时间、内存限制
- 支持环境变量和配置文件两种方式

---

## 十一、文件清单与依赖关系

```
实现顺序（箭头表示依赖）：

Phase 1: 基础骨架
  config.py
  llm/client.py
  workspace.py

Phase 2: WorkbookIngestor
  tools/workbook_ingestor.py   ← 核心：sheet/table candidate/manifest

Phase 3: Excel 预处理与标准化输出
  tools/excel_preprocessor.py  ← 依赖 workbook_manifest，输出 normalized tables

Phase 4: 核心 Pipeline + 执行器
  tools/profiler.py            ← 依赖 normalized tables
  tools/python_sandbox.py
  utils.py (extract_code_block)
  prompts/system_codegen.md
  prompts/system_repair.md
  agent/simple_pipeline.py     ← 依赖以上所有

Phase 5: TaskContext + Artifact
  context/summary_extractor.py
  context/task_context.py      ← 依赖 summary_extractor
  context/prompt_assembler.py  ← 依赖 task_context
  agent/plan.py
  agent/planner.py             ← 依赖 plan
  prompts/system_planner.md
  agent/orchestrator.py        ← 依赖以上所有

Phase 6: Adaptive + ResultChecker
  tools/result_checker.py
  prompts/system_adapt.md
  orchestrator.py 中增加 _adapt(), _should_adapt()

Phase 7: Reporter
  agent/reporter.py            ← 依赖 task_context, prompt_assembler
  prompts/system_reporter.md

Phase 8: Chainlit + Session + 记忆
  main.py                      ← Chainlit 入口，依赖 orchestrator + session
  session.py                   ← Session 管理（追问复用、对话摘要）
  memory.py                    ← 跨会话记忆（schema 匹配、用户偏好）
  .chainlit/config.toml        ← Chainlit 配置

Phase 9: 加固与测试
  tests/*
```

---

## 十二、关键设计决策备忘

| 决策 | 选择 | 理由 |
|------|------|------|
| 编排模式 | Adaptive Plan-Execute | 兼顾规划性和灵活性，token 不膨胀 |
| Excel 预处理 | 规则引擎优先 + LLM 兜底 | 大多数脏格式可用规则处理，减少 LLM 依赖 |
| LLM 调用模式 | 每次独立调用 | 避免上下文累积 |
| 步骤间信息传递 | TaskContext + Artifact Manifest | 摘要、产物、血缘分离，可控可追溯 |
| 代码执行 | subprocess + resource limits（个人版） | 简单、可复现；本机有 Docker 时可切换 |
| 数据传递 | normalized parquet/xlsx + output artifacts | 数据不进 LLM，明细通过文件交付 |
| 摘要提取 | 纯规则（不调 LLM） | 确定性、零 token 消耗 |
| 结果校验 | ResultChecker | 防止“代码跑通但结果不对” |
| 报告生成 | 分章节独立调用 | 每章 token 可控，质量更好 |
| Adapt 触发 | 条件判断（不是每步都触发） | 平衡灵活性与 token 消耗 |
| 错误处理 | 四级（Repair → Check Repair → Re-plan → 降级） | 不卡死，也尽量避免错结果 |
| 交互层 | Chainlit | 零前端开发量，原生支持文件上传/进度/对话历史 |
| 多轮对话 | Session + 追问复用 | 追问跳过预处理，复用 profile 和 normalized 数据 |
| 跨会话记忆 | JSON 文件（user_memory.json） | 轻量，记住 schema 和偏好，不搞复杂记忆系统 |
| Skill 扩展 | 执行器注册表（字典分发） | 新增能力只加一行，不需要插件框架 |
