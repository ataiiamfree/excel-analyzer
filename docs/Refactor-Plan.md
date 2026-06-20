# ChatExcel 前后端重构方案

> 目的：把 Chainlit 单体替换为 **FastAPI + WebSocket 后端** 与 **独立 React 前端**。
> 设计图：`docs/frontend_prototype.html`。
> 本文档负责说明架构、协议、目录、迁移路径与每个阶段的可交付物，便于 review 与逐步推进。

> 当前实现状态（2026-06-20）：本分支已落地 FastAPI 服务入口、SQLite 会话/消息/产物存储、WebSocket 事件流、headless REST run 通道，以及 `web/` React/TypeScript 三栏前端。旧 Chainlit 入口已替换为兼容 shim。

---

## 1. 目标与非目标

### 目标
- 把 UI 从 Chainlit 完全剥离，前端是一个独立的 React/TypeScript 工程。
- 把业务编排（Plan-Execute-Repair）保留在 `app/agent/`，作为后端服务的核心库使用，不重写。
- 用 FastAPI 提供 HTTP（会话/文件/产物）+ WebSocket（流式事件）的最小 API 表面。
- **同时提供 headless REST 通道**，让 eval 脚本、CI、批量回归无需依赖 WS 也能跑分析，详见 §3.8。
- 真正支持"会话列表 + 历史回看"——当前 Chainlit 没有真正的多会话持久化。
- 视觉与交互对齐 `frontend_prototype.html`。

### 非目标（先不做）
- 多租户与登录鉴权。第一版按单用户/单机部署。
- Postgres / Redis / Celery。第一版用 SQLite + asyncio 任务即可。
- 移动端响应式之外的设备适配。
- Chainlit 与新前端的长期共存。完成切换后即下线 Chainlit。

---

## 2. 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│  Browser                                                     │
│  React SPA (web/)                                            │
│  ├─ Conversation List / Chat / Artifact Panel                │
│  ├─ 状态：Zustand + TanStack Query                           │
│  └─ 传输：HTTP（REST）+ WebSocket（流式事件）                │
└────────────────────────────▲─────────────────────────────────┘
                             │ HTTP + WS
┌────────────────────────────┴─────────────────────────────────┐
│  FastAPI 服务 (app/api/)                                     │
│  ├─ REST：会话 / 消息 / 产物 / 文件下载                      │
│  ├─ WS  ：/ws/sessions/{id}  转发 orchestrator 事件          │
│  ├─ 任务队列：asyncio.create_task + 单进程内 Task Registry   │
│  └─ 持久化：SQLite (sessions, messages, artifacts)           │
└────────────────────────────▲─────────────────────────────────┘
                             │ 函数调用
┌────────────────────────────┴─────────────────────────────────┐
│  业务核心（沿用，不动）                                       │
│  app/agent/   app/context/   app/llm/   app/tools/           │
│  app/session.py   app/workspace.py                           │
└──────────────────────────────────────────────────────────────┘
```

关键决策：
- **业务核心零改动**：`Orchestrator.run()` 的回调签名（`on_plan_ready / on_step_start / on_step_end / on_report_token / on_reasoning_token`）已经是事件流形式，FastAPI WS 层只是把这些回调改写成 JSON 事件推送出去。
- **WebSocket 而非 SSE**：可双向，便于将来加入"中断/取消任务"指令。Workspace 已有 `is_cancel_requested()` 钩子。
- **SQLite + 文件系统**：会话元数据用 SQLite；分析过程的 workspace 目录、产物文件继续用现有 `Workspace` 抽象，不迁移到 DB。

---

## 3. 后端设计

### 3.1 目录结构（增量）

```
app/
├── agent/          ← 不动
├── context/        ← 不动
├── llm/            ← 不动
├── tools/          ← 不动
├── session.py      ← 不动（内存会话对象）
├── workspace.py    ← 不动
├── config.py       ← 微调（加 web 静态目录、CORS 配置）
├── api/            ← 新增
│   ├── __init__.py
│   ├── server.py       # FastAPI 入口（uvicorn 启动点）
│   ├── deps.py         # 依赖注入：DB、orchestrator 工厂
│   ├── schemas.py      # Pydantic 请求/响应/事件模型
│   ├── ws_events.py    # WS 事件类型（与前端 TS 类型对齐）
│   ├── routers/
│   │   ├── conversations.py   # /api/conversations
│   │   ├── files.py           # 文件上传/下载
│   │   └── artifacts.py       # 产物预览/下载
│   ├── ws/
│   │   ├── manager.py    # ConnectionManager
│   │   └── runner.py     # 跑 orchestrator + 推事件
│   └── persistence/
│       ├── db.py         # SQLAlchemy + SQLite
│       ├── models.py     # Conversation / Message / Artifact
│       └── store.py      # repository 风格的访问
└── main.py         ← 删除（chainlit 入口），改为 thin shim 或彻底移除
```

`run` 入口：
```bash
# 旧
chainlit run app/main.py
# 新
uvicorn app.api.server:app --reload
```

### 3.2 数据模型（SQLite via SQLAlchemy 2.x）

```python
class Conversation(Base):
    id: str (uuid)              # = workspace.task_id 兼容
    title: str                  # 默认取首条 query 截 24 字
    file_name: str | None
    file_size: int | None
    sheet_count: int | None
    row_count: int | None
    created_at, updated_at: datetime
    starred: bool = False
    archived_at: datetime | None

class Message(Base):
    id: str (uuid)
    conversation_id: FK
    role: Literal["user", "assistant"]
    created_at: datetime
    # 用户消息：文本 + 附件指针
    # 助手消息：把一次 run 的结构化产物全塞 JSON 里，避免拆很多张表
    payload: JSON
    # payload 结构见 §4

class Artifact(Base):
    id: str
    conversation_id, message_id: FK
    path: str           # workspace 内相对路径
    kind: Literal["chart", "excel", "csv", "report", "file"]
    name: str
    size: int
    created_at: datetime
```

不为 Plan / Step / Reasoning 建表——它们都是一次 run 的内部产物，按 JSON 存进 `Message.payload` 即可。

### 3.3 REST 接口

| 方法   | 路径                                       | 说明                                              |
| ------ | ------------------------------------------ | ------------------------------------------------- |
| GET    | `/api/conversations`                       | 侧栏列表，分日期组返回                            |
| POST   | `/api/conversations`                       | 新建（multipart：上传 Excel + 可选首问）          |
| GET    | `/api/conversations/{id}`                  | 单个会话元数据 + 文件 profile 摘要                |
| PATCH  | `/api/conversations/{id}`                  | 重命名 / 收藏 / 归档                              |
| DELETE | `/api/conversations/{id}`                  | 删除（连同 workspace 目录）                       |
| GET    | `/api/conversations/{id}/messages`         | 拉历史消息（用于打开会话时回放）                  |
| POST   | `/api/conversations/{id}/files`            | 切换/追加 Excel（同当前的"再发新文件"）           |
| POST   | `/api/conversations/{id}/runs`             | **同步**跑一次问答（持久化，eval 复现 bug 用）    |
| POST   | `/api/runs`                                | **一次性**同步跑（multipart：file + query，不建会话） |
| GET    | `/api/runs/{run_id}`                       | 查询某个 run 状态（用于异步轮询场景）             |
| DELETE | `/api/runs/{run_id}`                       | 取消 run                                          |
| GET    | `/api/artifacts/{id}`                      | 文件流下载                                        |
| GET    | `/api/artifacts/{id}/preview`              | 表格 JSON 预览（前 50 行 × 24 列）                |
| GET    | `/api/artifacts/{id}/sha256`               | 产物指纹（eval 断言用）                           |

`/api/runs` 与 `/api/conversations/{id}/runs` 的详细语义见 §3.8。

### 3.4 WebSocket：`/ws/conversations/{id}`

**客户端 → 服务端**：
```json
{ "type": "user_message", "content": "...", "client_msg_id": "..." }
{ "type": "cancel" }
```

**服务端 → 客户端**（事件流，所有事件都有 `seq` 单调递增）：

```ts
type ServerEvent =
  | { type: "run.start",     seq, ts, message_id }
  | { type: "plan.ready",    seq, steps: PlanStep[] }
  | { type: "step.start",    seq, step_id, index, total, description, tool, instruction }
  | { type: "reasoning.delta", seq, step_id?, delta: string }
  | { type: "step.end",      seq, step_id, status: "done"|"failed", stdout, error, files, script_path, duration_ms }
  | { type: "report.delta",  seq, delta: string }
  | { type: "artifact.created", seq, artifact_id, name, kind, size, message_id }
  | { type: "run.complete",  seq, message_id, report: string, file_ids: string[], duration_ms, result?: AssistantMessagePayload }
  | { type: "run.failed",    seq, failed_step_description, error_summary }
  | { type: "cancelled",     seq }
```

这套事件类型 = 现有 Orchestrator 五个回调的 1:1 映射，只是把 Python `await callback(token)` 改成 `await ws.send_json(event)`。

### 3.5 任务运行

- 每个 WS 连接对应一个 `conversation_id`。
- 用户发 `user_message` 时，在后端启动 `asyncio.create_task(run_with_events(...))`。
- 任务句柄存进进程内 `RunRegistry[conversation_id] = task`，便于 `cancel` 指令调用 `Workspace.request_cancel()`。
- `run_with_events` 把 5 个回调实现为 `await ws.send_json(...)`，并在 LLM token / step 结束时往 `Message.payload` 累积写入。

### 3.6 文件上传与 workspace

- 上传走 `POST /api/conversations`，FastAPI 接收 multipart，落到 `workspace/<task_id>/raw/`。
- 复用 `Workspace.save_upload()`，行为与现在 `_setup_session()` 一致。
- 产物下载：用 `FileResponse` 直接吐 `Workspace` 里的相对路径，不暴露绝对路径。

### 3.7 兼容性与回归

- 因为业务核心没动，`tests/` 里的 `test_eval_runner.py` / `test_sandbox.py` 等继续跑通。
- 新增 `tests/test_api/` 用 `httpx.AsyncClient` 覆盖 REST + WS。

### 3.8 Headless API / Eval 通道

**动机**：基于公开数据集做准确性回归时，eval 脚本只关心最终结果（report + 产物），不关心流式过程。强制走 WS 会引入事件循环、reconnect、批量并发连接管理等冗余复杂度。因此在 §3.3 已有端点之外，**专门为脚本/CI/eval 暴露同步阻塞的 REST 通道**，复用同一个 orchestrator。

#### 3.8.1 端点定义

**`POST /api/runs`** — 一次性同步问答。**不建 Conversation，不污染侧栏。**

```http
POST /api/runs
Content-Type: multipart/form-data

file=@datasets/q3.xlsx
query="按区域汇总 Q3 销售额，找出 TOP5 和 BTM5 城市"
params={"budget_preset": "fast", "max_repair_attempts": 2}    # 可选，JSON 字符串
ephemeral=true                                                 # 默认 true，workspace 进 TTL 清理队列
```

响应（阻塞到任务结束）：

```http
200 OK
Content-Type: application/json
X-Run-Id: run_01HXXX...
X-Duration-Ms: 38214

{ ... RunResult ... }
```

**`POST /api/conversations/{id}/runs`** — 同步跑一次，**复用已有会话**。用于：
- eval 想复用一次预处理后的 workspace 跑多个追问；
- 复现某次失败 bug 时把脚本挂进真实会话。

```http
POST /api/conversations/{id}/runs
Content-Type: application/json

{ "query": "...", "stream": false, "params": {...} }
```

`stream=false`（默认）= 阻塞返回 `RunResult`；`stream=true` 见 §3.8.3。

#### 3.8.2 `RunResult` schema

`RunResult` = §4 的 `AssistantMessagePayload` 加上**产物直链与指纹**：

```python
class RunArtifact(BaseModel):
    id: str               # art_xxx
    kind: Literal["chart", "excel", "csv", "report", "file"]
    name: str
    size: int
    sha256: str           # 用于 eval 断言
    url: str              # /api/artifacts/{id}
    preview_url: str | None  # 表格类才有

class RunResult(AssistantMessagePayload):
    run_id: str
    conversation_id: str | None    # /api/runs 时为 None
    artifacts: list[RunArtifact]   # 替换 AssistantMessagePayload.artifact_ids
    metrics: RunMetrics            # 比 UI 版本更详细

class RunMetrics(BaseModel):
    duration_ms: int
    started_at: datetime
    ended_at: datetime
    llm_calls: int
    llm_tokens: dict[str, int]       # {"prompt": ..., "completion": ..., "reasoning": ...}
    sandbox_attempts: int            # 含 repair 重试次数
    sandbox_wall_ms: int
```

#### 3.8.3 中间事件（可选）

**默认场景**：eval 不需要中间事件，REST 阻塞返回 `RunResult` 即可。

**进阶场景**：当 `Accept: application/x-ndjson` 时，同一端点改为 NDJSON 流：每行一个 §3.4 的 `ServerEvent`，最后一行是 `run.complete` 携带完整 `RunResult`。这给"批量但又想看中间步"的脚本兜底，不需要切到 WS。

```python
with httpx.stream("POST", "/api/runs", files=..., 
                  headers={"Accept": "application/x-ndjson"}) as r:
    for line in r.iter_lines():
        evt = json.loads(line)
        if evt["type"] == "step.end": ...
        if evt["type"] == "run.complete":
            result = evt["result"]
```

#### 3.8.4 超时与取消

- 客户端 `httpx.post(..., timeout=300)` 起步；服务端用 `asyncio.wait_for(run, timeout=cfg.run_timeout_seconds)` 包一层，避免分析挂死。
- 长任务可用 `DELETE /api/runs/{run_id}` 取消，背后调 `Workspace.request_cancel()`。**不依赖 WS**。
- `GET /api/runs/{run_id}` 返回 `{ status: "running"|"done"|"failed"|"cancelled", progress: {step, total} }`，给那种"先提交再轮询"的客户端用。

#### 3.8.5 并发与隔离

- 每个 `/api/runs` 创建独立 `Workspace`，互不影响。
- 进程内信号量限制并发数（`MAX_CONCURRENT_RUNS`，默认 4，按 CPU 调），避免沙箱抢占。
- `ephemeral=true` 的 workspace 在任务完成后由后台 GC 协程按 TTL 清理（默认 24h），便于事后排查失败用例；`ephemeral=false` 才长期保留。

#### 3.8.6 Python 客户端（薄包装）

为了让 eval 脚本一行调用，提供 `scripts/eval_client.py`：

```python
from scripts.eval_client import ChatExcelClient

client = ChatExcelClient(base_url="http://localhost:8000")

result = client.run(
    file="datasets/q3.xlsx",
    query="按区域汇总 Q3 销售额，找出 TOP5",
    timeout=300,
)

assert result.status == "done"
assert "上海" in result.report
xlsx = next(a for a in result.artifacts if a.name.endswith(".xlsx"))
assert xlsx.sha256 == expected_sha   # 或者下载下来用 pandas 校验内容
```

这个客户端是后端代码包的一部分，与 `tests/test_api/` 共用 fixtures。**eval 不绕过 HTTP**——保证测的是部署后的真实路径。

#### 3.8.7 与现有 eval 脚本的衔接

- 现有 `scripts/run_eval.py` 目前直接 import `Orchestrator` 跑。重构后改为通过 `ChatExcelClient` 走 HTTP，确保测试覆盖到 API 层。
- 旧的 in-process eval 入口保留为 `scripts/run_eval_inproc.py`，作为不依赖服务的快速 smoke。

---

## 4. 消息 payload 协议（前后端共享）

为避免 SQL 拆很多表，每条 assistant `Message.payload` 用 JSON 存这套结构。前端 TS 类型与后端 Pydantic 模型一一对应。

```ts
interface AssistantMessagePayload {
  status: "running" | "done" | "failed" | "cancelled";
  query: string;                      // 触发本次 run 的用户消息
  plan: { steps: PlanStep[] };
  reasoning?: { text: string; tokens: number };
  steps: StepRecord[];                // 与 plan.steps 一一对应，含执行结果
  report: string;                     // markdown
  next_actions: string[];             // LLM 基于报告摘要生成的下一步行动建议
  artifact_ids: string[];             // 指向 Artifact 表
  metrics: { duration_ms: number; started_at: string; ended_at?: string };
  error?: { failed_step_description: string; summary: string };
}

interface PlanStep {
  id: string; tool: "python" | "knowledge";
  description: string; instruction: string;
  depends_on: string[]; is_exploratory: boolean;
}

interface StepRecord {
  step_id: string;
  status: "pending" | "running" | "done" | "failed";
  started_at?: string; ended_at?: string;
  stdout?: string; error?: string;
  script_path?: string;
  artifact_ids: string[];
}
```

用户消息更简单：`{ text: string; attached_file?: { name, size } }`。

---

## 5. 前端设计

### 5.1 技术栈

| 关注点         | 选型                                        | 理由                                                  |
| -------------- | ------------------------------------------- | ----------------------------------------------------- |
| 构建           | Vite + React 18 + TypeScript                | 启动快、Vite HMR 体验好                               |
| 路由           | React Router v6                             | `/c/:conversationId`                                  |
| HTTP           | TanStack Query                              | 列表/历史的缓存 + 失效控制                            |
| WS             | 自实现 hook `useConversationStream`         | 业务事件少，无需 Socket.IO                            |
| 状态           | Zustand (UI 状态) + TanStack Query (服务态) | 不引入 Redux                                          |
| 样式           | Tailwind CSS + 设计 token CSS 变量          | 把原型里的 `--bg / --ink / --accent` 等映射到 Tailwind |
| Markdown       | `react-markdown` + `remark-gfm`             | 报告渲染                                              |
| 表格           | TanStack Table                              | 排序/筛选/虚拟滚动                                    |
| 字体           | Fraunces + Instrument Sans + JetBrains Mono | 与原型一致                                            |

显式不引入：UI 组件库（MUI/AntD/Chakra）——会破坏报刊感；Recharts/ECharts——产物图表后端已生成 PNG。

### 5.2 目录结构

```
web/
├── index.html
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── vite.config.ts
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── styles/
    │   ├── tokens.css         # CSS 变量（迁自原型）
    │   ├── editorial.css      # 报告/标题的衬线规则
    │   └── index.css
    ├── api/
    │   ├── http.ts            # axios/fetch 封装
    │   ├── ws.ts              # WS hook
    │   └── types.ts           # 与后端 schemas.py 对齐
    ├── store/
    │   └── uiStore.ts         # 当前会话 id、面板折叠态
    ├── layout/
    │   ├── AppShell.tsx       # 三栏壳子
    │   ├── Sidebar.tsx
    │   ├── Topbar.tsx
    │   └── ArtifactPanel.tsx
    ├── chat/
    │   ├── Thread.tsx
    │   ├── Composer.tsx
    │   ├── MessageUser.tsx
    │   ├── MessageAssistant.tsx
    │   ├── ReasoningCapsule.tsx
    │   ├── PlanBlock.tsx
    │   ├── StepItem.tsx
    │   ├── ProgressLine.tsx
    │   ├── ReportArticle.tsx
    │   └── ArtifactChips.tsx
    ├── artifacts/
    │   ├── ChartPreview.tsx
    │   ├── TablePreview.tsx
    │   └── FileList.tsx
    └── pages/
        ├── ConversationPage.tsx   # /c/:id
        └── HomePage.tsx           # 空态 + 上传
```

### 5.3 状态与事件流处理

- `useConversationStream(conversationId)` 内部维护：
  - WS 连接（带 reconnect 退避）
  - `assistantMessageBuffer`：本次 run 的累积 payload
  - 收到事件后用 reducer 把 buffer 推进，组件订阅它即可流式渲染
- 一次 run 结束后，把最终 payload 通过 TanStack Query 的 `setQueryData` 写入 `["conversations", id, "messages"]` 缓存，刷新页面无需重拉。

### 5.4 与原型一致的视觉规则

把 `frontend_prototype.html` 的 `<style>` 拆为 `tokens.css` + `editorial.css` + 组件 Tailwind class。CSS 变量保留：
```
--bg / --bg-elev / --bg-tint / --ink / --ink-2..4
--rule / --rule-2
--accent / --indigo / --jade / --amber 以及各自的 -soft 变体
```
Tailwind `theme.extend.colors` 直接映射。

---

## 6. 阶段任务与里程碑

### 阶段 0 · 协议先行（0.5 d）
**目标**：把 §3.4 §4 的 Pydantic 模型与 TS 类型敲定，避免后续来回改。
- [x] `app/api/schemas.py`：会话/消息/产物的请求响应模型
- [x] `app/api/ws_events.py`：所有 server→client 事件 Pydantic 模型
- [ ] `scripts/export_types.py`：从 Pydantic 导出 JSON Schema，前端用 `json-schema-to-typescript` 转 TS
- **DoD**：`make types` 一键同步前后端类型

### 阶段 1 · 后端骨架（1 d）
- [x] FastAPI app + CORS + 静态前端挂载（构建后）
- [x] SQLite 初始表结构与 repository（当前使用 stdlib sqlite3，避免新增运行时安装阻塞；schema 按文档保留）
- [x] `Conversation / Message / Artifact` 三张表的 CRUD
- [x] 文件上传到 workspace，与现有 `Workspace.save_upload` 接好
- [ ] `tests/test_api/test_conversations.py` 覆盖增删改查
- **DoD**：用 `httpie` 可以完成"创建会话→列出→删除"全流程

### 阶段 2 · WebSocket + Orchestrator 接线（1 d）
- [x] `ws/manager.py` 单连接 / 单 conversation 的 ConnectionManager
- [x] `ws/runner.py` 把 5 个 orchestrator 回调改写为 `ws.send_json`
- [x] 事件 `seq` 编号
- [ ] 断线重连协议（客户端发 `resume_from_seq`）
- [ ] `cancel` 指令调用 `Workspace.request_cancel()`
- [x] 把 assistant payload 落盘到 `Message`
- **DoD**：用 `wscat` 手动连一次，能看到完整事件流；中断指令生效

### 阶段 2.5 · Headless / Eval REST 通道（0.5 d）
**目标**：脱离 WS 也能跑端到端分析，给 eval/CI 用。详见 §3.8。
- [x] `POST /api/runs`（一次性、不建会话）与 `POST /api/conversations/{id}/runs`（会话内同步）
- [x] `RunResult` schema：含 artifacts 直链、sha256、详细 metrics
- [ ] `Accept: application/x-ndjson` 时改为事件流（复用 §3.4 事件类型）
- [ ] `DELETE /api/runs/{run_id}` 取消；`GET /api/runs/{run_id}` 查询状态
- [ ] `MAX_CONCURRENT_RUNS` 信号量与 ephemeral workspace TTL GC
- [ ] `scripts/eval_client.py` 薄客户端 + `scripts/run_eval.py` 切换到 HTTP 调用
- [ ] `tests/test_api/test_runs.py` 跑一个公开数据集 smoke 用例
- **DoD**：`python scripts/run_eval.py` 通过 HTTP 跑完 manifest 全部用例，产出准确率报告

### 阶段 3 · 前端骨架（1 d）
- [x] `web/` 工程脚手架（Vite + React + TS + Tailwind）
- [x] Tokens / Tailwind 主题配置，跑通衬线字体
- [x] `AppShell` 三栏布局 + 路由
- [x] 用真实 API / WS 数据渲染原型三栏界面
- **DoD**：`pnpm dev` 打开后视觉 1:1 复现 `frontend_prototype.html`

### 阶段 4 · 核心交互闭环（1.5 d）
- [ ] 侧栏会话列表（HTTP）
- [ ] 上传 Excel + 新建会话
- [ ] Composer 发消息触发 WS
- [ ] 流式渲染：reasoning / plan / step / report 四路流分别接入对应组件
- [ ] 产物 chips + 右侧产物预览面板（图表/表格/文件列表三个 Tab）
- **DoD**：跑通 Q3 销售示例，UI 表现与原型一致

### 阶段 5 · 历史回看与持久化（0.5 d）
- [ ] 切换会话 → 加载历史 messages 并回放为最终态
- [ ] 刷新页面不丢上下文
- [ ] 重命名 / 删除 / 收藏（PATCH）
- **DoD**：关浏览器再开能看到之前的 12 次分析

### 阶段 6 · 边角与上线（0.5 d）
- [ ] 错误态：网络断开、LLM 429、文件解析失败
- [ ] 空态：未上传文件时的首页
- [ ] 取消任务按钮
- [ ] README + `make dev` 一键起前后端
- [ ] **下线 Chainlit**：删 `chainlit.md` / `.chainlit/` / `public/chat_excel.*` / `app/main.py` 中的 chainlit 引用，更新 `requirements.txt`
- **DoD**：仓库里搜不到 `chainlit`

**预估总工**：5.5–6.5 个人日（含阶段 2.5 的 0.5 d）。

---

## 7. 迁移与回滚策略

- 整个重构在 `feat/web-refactor` 分支上推进。
- 阶段 0–5 期间 Chainlit 入口保留，`uvicorn` 和 `chainlit run` 并存，方便对照。
- 阶段 6 完成才删 Chainlit 代码，最后一次 commit 单独负责"删除 Chainlit"，回滚成本最低。
- 现有用户分析历史不迁移（当前 Chainlit 也没真正持久化），从新前端开始重新积累。

---

## 8. 需要你 review 的关键决策

1. **会话持久化用 SQLite**——同意还是想直接上 Postgres？
2. **WS 事件 schema**（§3.4）——字段是否够用、命名是否合心意。
3. **assistant payload 用 JSON 整存**——是否接受这种"不拆细表"的方式。
4. **样式**：Tailwind + 原型 CSS 变量（vs 直接复用原型 CSS 不上 Tailwind）。
5. **删除 Chainlit 的时机**：完成阶段 6 一次性删，还是阶段 4 跑通后就删？
6. **`/api/` 前缀** vs **裸路径**。
7. **rebuild 时是否需要"导入历史 chainlit 任务"**——默认否，需要的话要补迁移脚本。
8. **`/api/runs` 默认 `ephemeral=true`**（不建 Conversation、按 TTL 清理 workspace）——同意还是默认持久化？
9. **eval 是否必须通过 HTTP**（§3.8.7）——还是允许保留 in-process 入口作为 smoke 兜底？
10. **`MAX_CONCURRENT_RUNS` 默认值**——4 还是按 CPU 自动？

确认上述之后我开始动手实现，按阶段交付，每个阶段结束后给你一次小 review。
