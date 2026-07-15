# Excel 智能分析 Agent

上传 Excel 文件，用自然语言提出分析需求，自动生成 Python 代码执行分析并输出报告。当前交互层已重构为 **FastAPI + WebSocket 后端** 与 **React/TypeScript 前端**。

当前交付版本为 **v0.9.0 MVP**。交付范围、测试证据和已知限制见 [v0.9 MVP 交付说明](docs/V0.9-MVP-Release.md)。

## 架构

采用 **Adaptive Plan-Execute** 编排：先粗略规划全局，每步执行后根据实际结果动态细化下一步。每次 LLM 调用独立，不累积上下文。

详见 [Design.md](docs/Design.md) 和 [Implementation-Plan.md](docs/Implementation-Plan.md)。

## 当前实现状态

核心功能可用：

- **数据预处理**: WorkbookIngestor → ExcelPreprocessor → Profiler
- **执行引擎**: PythonSandbox + ResultChecker + Adaptive Plan-Execute
- **报告生成**: Reporter 分章节 LLM 调用，自动注册产物
- **交互层**: FastAPI + WebSocket API，React 三栏 Web 界面，支持文件上传、分析、追问、历史回看
- **会话管理**: Session 追问复用、Memory 跨会话 schema 匹配

## 公开 Benchmark 评测

项目内置了公开 Excel benchmark 的 materializer，可把 Hugging Face 压缩包转换成 `scripts/run_eval.py`
可直接读取的 manifest，并用标准答案工作簿做端到端回归评分。

```bash
# 只准备数据和 manifest；默认使用较轻量的 v1 verified / v2 example 变体
python scripts/prepare_benchmark_data.py --benchmark all

# 查看公开 benchmark 将要跑哪些 case，不调用 LLM
python scripts/run_eval.py --benchmark spreadsheetbench --dry-run --limit 5
python scripts/run_eval.py --benchmark spreadsheetbench-v2 --dry-run --limit 5

# 真正端到端跑前 N 个 case
python scripts/run_eval.py --benchmark spreadsheetbench --limit 3

# 跑完整归档时显式选择 full；会下载并解压较大的官方压缩包
python scripts/run_eval.py --benchmark spreadsheetbench-v2 --benchmark-variant full --limit 3
```

生成的数据放在 `eval_datasets/`，评测结果仍写入 `eval_runs/`。公开集 case 会要求 agent 产出 `.xlsx`
工作簿，并按 benchmark 提供的 `answer_position` 范围与 golden workbook 做单元格值比对。

## 快速开始

### 1. 环境准备

```bash
# Python 3.10+
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd web && npm install && cd ..
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的 DeepSeek API Key
```

### 3. 运行、停止和重启

开发模式使用两个终端，后端和前端分别占用一个端口。

终端 A（后端）：

```bash
source .venv/bin/activate
make run
```

终端 B（前端）：

```bash
make web-dev
```

浏览器打开 `http://127.0.0.1:5173`。后端健康检查地址为
`http://127.0.0.1:8000/api/health`。

- 停止：分别回到两个终端按 `Ctrl+C`。
- 重启：再次在终端 A 运行 `make run`，在终端 B 运行 `make web-dev`。
- 端口占用：先停止旧进程；也可用 `PORT=8001 make run` 临时更换后端端口，并用 `VITE_API_TARGET=http://127.0.0.1:8001 make web-dev` 启动前端。

构建前端后，也可以只启动后端，由 FastAPI 同时提供静态前端：

```bash
make web-build
make run
# 浏览器打开 http://127.0.0.1:8000
```

上传 Excel 后可输入分析需求、查看分步进度和报告/图表；追问时无需重新上传。当前支持 `.xlsx`、`.xlsm`，默认文件上限为 100 MB。

### 4. 测试

```bash
make test
make web-build
```

## 项目结构

```
app/
├── main.py         # 旧测试兼容 shim，服务入口为 app.api.server
├── api/            # FastAPI REST / WebSocket / SQLite persistence
├── session.py      # 会话管理（追问复用、对话摘要）
├── agent/          # 编排器、规划器、报告生成
├── context/        # TaskContext、PromptAssembler、摘要提取
├── tools/          # WorkbookIngestor、ExcelPreprocessor、Profiler、沙箱、ResultChecker
├── llm/            # LLM 客户端
└── prompts/        # 系统提示词模板
memory/             # 跨会话记忆（用户偏好、已知 schema）
web/                # React + TypeScript 前端
tests/              # 测试
workspace/          # 运行时任务目录（不进 git）
docs/               # 设计文档
```

## 技术栈

- **LLM**: DeepSeek V4 Pro（128K+ 上下文）
- **后端服务**: FastAPI + WebSocket + SQLite
- **前端**: Vite + React 18 + TypeScript + TanStack Query + Zustand
- **后端**: Python 3.10+
- **数据处理**: pandas + openpyxl + pyarrow
- **图表**: matplotlib
